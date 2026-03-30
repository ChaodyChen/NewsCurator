"""
ML ranking module for Semiconductor News Curator.

Learns from curator's selections and predicts which articles will be ranked.
Includes cold-start fallback (keyword scoring) before sufficient training data accumulates.
"""

import logging
import re
import os
import glob
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import pandas as pd
import numpy as np

# Guard import: never crash app if sklearn is missing
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    import joblib
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    LogisticRegression = None
    StandardScaler = None
    Pipeline = None
    joblib = None

logger = logging.getLogger(__name__)

MIN_TRAINING_EXAMPLES = 20
MODEL_PATH = Path(__file__).parent.parent / 'models' / 'ranker.joblib'

# Sentiment word lists (hardcoded, no NLP dependency)
_POSITIVE_WORDS = {
    'breakthrough', 'record', 'growth', 'advanced', 'launch', 'new',
    'innovative', 'leading', 'strong', 'success', 'expand', 'partnership',
    'announced', 'achieve', 'improve', 'gain', 'record', 'beat', 'surge',
}
_NEGATIVE_WORDS = {
    'shortage', 'delay', 'risk', 'concern', 'decline', 'loss', 'cut',
    'layoff', 'recall', 'fail', 'ban', 'restrict', 'sanction', 'crisis',
    'weak', 'challenge', 'threat', 'struggle',
}


def extract_features(
    articles: List[Dict],
    keywords: List[str],
    source_scores: Optional[Dict[str, float]] = None,
) -> np.ndarray:
    """
    Extract 12-feature vector for each article.

    Features:
      1. keyword_title_count - distinct keywords in title
      2. keyword_snippet_count - distinct keywords in snippet
      3. top5_kw_title - binary: any top-5 keyword in title
      4. title_length - character count
      5. snippet_length - character count
      6. source_score - from source_scores dict (0.5 default)
      7. has_verified_link - 1 if link_verified == "True"
      8. hours_since_published - capped at 72
      9. is_weekend_published - binary
     10. title_has_number - binary
     11. snippet_sentiment_pos - positive word count
     12. snippet_sentiment_neg - negative word count

    Args:
        articles: List of article dicts (title, snippet, source, published_at, link_verified)
        keywords: List of keyword strings
        source_scores: Dict mapping source -> float [0, 1]

    Returns:
        np.ndarray of shape (n_articles, 12)
    """
    if source_scores is None:
        source_scores = {}

    # Filter empty keywords
    keywords = [kw for kw in keywords if kw and kw.strip()]

    features_list = []

    for article in articles:
        try:
            title = (article.get('title') or '').lower()
            snippet = (article.get('snippet') or '').lower()
            source = article.get('source', '')
            published_at = article.get('published_at', '')
            link_verified = article.get('link_verified', 'False')

            # Feature 1-2: Keyword counts
            keyword_title_count = sum(1 for kw in keywords if kw.lower() in title)
            keyword_snippet_count = sum(1 for kw in keywords if kw.lower() in snippet)

            # Feature 3: Top-5 keywords (simplified: just check if any keyword matched)
            # In real impl, rank keywords by frequency in positive examples and check top-5
            top5_kw_title = 1.0 if keyword_title_count > 0 else 0.0

            # Feature 4-5: Length
            title_length = float(len(title))
            snippet_length = float(len(snippet) if snippet else 0)

            # Feature 6: Source score
            source_score = float(source_scores.get(source, 0.5))

            # Feature 7: Verified link
            has_verified_link = 1.0 if link_verified == 'True' else 0.0

            # Feature 8: Hours since published
            try:
                pub_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                hours_diff = (now - pub_dt).total_seconds() / 3600
                hours_since_published = min(float(hours_diff), 72.0)
            except (ValueError, AttributeError):
                hours_since_published = 36.0  # Default midpoint

            # Feature 9: Weekend published
            try:
                pub_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                is_weekend = 1.0 if pub_dt.weekday() >= 5 else 0.0
            except (ValueError, AttributeError):
                is_weekend = 0.0

            # Feature 10: Title has number
            title_has_number = 1.0 if re.search(r'\d', title) else 0.0

            # Feature 11-12: Sentiment
            snippet_sentiment_pos = float(sum(1 for word in _POSITIVE_WORDS if word in snippet))
            snippet_sentiment_neg = float(sum(1 for word in _NEGATIVE_WORDS if word in snippet))

            features = [
                keyword_title_count,
                keyword_snippet_count,
                top5_kw_title,
                title_length,
                snippet_length,
                source_score,
                has_verified_link,
                hours_since_published,
                is_weekend,
                title_has_number,
                snippet_sentiment_pos,
                snippet_sentiment_neg,
            ]
            features_list.append(features)

        except Exception as e:
            logger.warning(f"Error extracting features for article: {e}, using zeros")
            features_list.append([0.0] * 12)

    return np.array(features_list, dtype=np.float32)


def compute_source_scores(df: pd.DataFrame) -> Dict[str, float]:
    """
    Compute source credibility scores from labeled data.

    score = (selected_count + 1) / (total_count + 2)  [Laplace smoothed]

    Args:
        df: DataFrame with 'source' and 'label' columns

    Returns:
        Dict mapping source -> float [0, 1]
    """
    if df.empty or 'source' not in df.columns or 'label' not in df.columns:
        return {}

    source_scores = {}
    for source in df['source'].unique():
        if pd.isna(source):
            continue
        source_data = df[df['source'] == source]
        selected_count = (source_data['label'] == 1).sum()
        total_count = len(source_data)
        # Laplace smoothing: (selected + 1) / (total + 2)
        score = (selected_count + 1) / (total_count + 2)
        source_scores[source] = float(score)

    return source_scores


def _normalize_url(url: str) -> str:
    """Normalize URL for matching: lowercase + strip trailing slash."""
    if not url:
        return ''
    return url.lower().rstrip('/')


def build_training_dataset(
    candidates_dir: str,
    selections_dir: str,
    keywords: List[str],
) -> pd.DataFrame:
    """
    Build labeled dataset by joining candidates + selections CSVs.

    Glob all candidates-YYYY-MM-DD.csv files, join with matching
    selections-YYYY-MM-DD.csv files by URL.

    Label: 1 if rank in {4,5} (top stars), else 0.

    Args:
        candidates_dir: Directory with candidates-*.csv files
        selections_dir: Directory with selections-*.csv files
        keywords: List of keywords (for compatibility)

    Returns:
        DataFrame with columns: url, title, source, published_at,
        snippet, link_verified, fetch_timestamp, rank, label
    """
    all_rows = []

    # Find all candidates files
    candidates_files = glob.glob(os.path.join(candidates_dir, 'candidates-*.csv'))
    logger.info(f"Found {len(candidates_files)} candidates files")

    for candidates_file in candidates_files:
        # Extract date from filename
        match = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(candidates_file))
        if not match:
            logger.warning(f"Could not extract date from {candidates_file}")
            continue

        date_str = match.group(1)
        selections_file = os.path.join(selections_dir, f'selections-{date_str}.csv')

        # Load candidates
        try:
            candidates_df = pd.read_csv(candidates_file)
            logger.info(f"Loaded {len(candidates_df)} candidates from {candidates_file}")
        except Exception as e:
            logger.warning(f"Failed to read {candidates_file}: {e}")
            continue

        # Load selections (if exists)
        selections_df = None
        if os.path.exists(selections_file):
            try:
                selections_df = pd.read_csv(selections_file)
                logger.info(f"Loaded {len(selections_df)} selections from {selections_file}")
            except Exception as e:
                logger.warning(f"Failed to read {selections_file}: {e}")

        # Normalize URLs for joining
        candidates_df['url_normalized'] = candidates_df['url'].apply(_normalize_url)
        if selections_df is not None:
            selections_df['url_normalized'] = selections_df['url'].apply(_normalize_url)

        # Join on normalized URLs
        if selections_df is not None:
            merged = candidates_df.merge(
                selections_df[['url_normalized', 'rank']],
                on='url_normalized',
                how='left'
            )
        else:
            merged = candidates_df.copy()
            merged['rank'] = None

        # Assign label: 1 if rank in {2,3} (top stars = good article), else 0
        merged['label'] = merged['rank'].apply(
            lambda x: 1 if pd.notna(x) and str(x) in {'2', '3'} else 0
        )

        # Drop the normalized URL column
        merged = merged.drop(columns=['url_normalized'], errors='ignore')

        all_rows.append(merged)
        logger.info(f"Date {date_str}: {len(merged)} total rows, {(merged['label']==1).sum()} positive")

    if not all_rows:
        logger.warning("No training data found")
        return pd.DataFrame()

    df = pd.concat(all_rows, ignore_index=True)
    logger.info(f"Combined dataset: {len(df)} rows, {(df['label']==1).sum()} positive ({100*(df['label']==1).sum()/len(df):.1f}%)")

    return df


def train_model(df: pd.DataFrame, keywords: List[str]) -> Pipeline:
    """
    Train logistic regression on labeled dataset.

    Pipeline: StandardScaler -> LogisticRegression

    Args:
        df: Labeled DataFrame from build_training_dataset()
        keywords: List of keywords

    Returns:
        Fitted sklearn Pipeline

    Raises:
        ValueError: If insufficient data or sklearn unavailable
    """
    if not SKLEARN_AVAILABLE:
        raise ImportError("scikit-learn not available")

    if len(df) < MIN_TRAINING_EXAMPLES:
        raise ValueError(
            f"Insufficient training data: {len(df)} < {MIN_TRAINING_EXAMPLES}"
        )

    # Extract features
    articles = df.to_dict('records')
    source_scores = compute_source_scores(df)
    X = extract_features(articles, keywords, source_scores)

    # Extract labels
    y = df['label'].values

    # Build and train pipeline
    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('lr', LogisticRegression(C=1.0, class_weight='balanced', max_iter=500)),
    ])
    pipeline.fit(X, y)

    logger.info(f"Trained model: {len(df)} samples, {(y==1).sum()} positive")
    return pipeline


def save_model(pipeline: Pipeline, path: Path = MODEL_PATH) -> None:
    """
    Serialize fitted pipeline to disk.

    Args:
        pipeline: Fitted sklearn Pipeline
        path: Output path (default: models/ranker.joblib)
    """
    if not SKLEARN_AVAILABLE or joblib is None:
        logger.warning("scikit-learn not available, skipping model save")
        return

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        joblib.dump(pipeline, path)
        logger.info(f"Saved model to {path}")
    except Exception as e:
        logger.error(f"Failed to save model: {e}")


def load_model(path: Path = MODEL_PATH) -> Optional[Pipeline]:
    """
    Load serialized pipeline from disk.

    Args:
        path: Path to joblib file

    Returns:
        Fitted Pipeline if file exists, None otherwise
    """
    if not SKLEARN_AVAILABLE or joblib is None:
        return None

    path = Path(path)
    if not path.exists():
        logger.debug(f"Model file not found: {path}")
        return None

    try:
        model = joblib.load(path)
        logger.info(f"Loaded model from {path}")
        return model
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        return None


def cold_start_score(articles: List[Dict], keywords: List[str]) -> List[float]:
    """
    Fallback scorer using keyword heuristics.

    score = keyword_title_hits * 2 + keyword_snippet_hits * 1 + has_verified_link * 0.5
    Normalized to [0, 1] per batch.

    Args:
        articles: List of article dicts
        keywords: List of keywords

    Returns:
        List of float scores in [0, 1]
    """
    if not articles:
        return []

    keywords = [kw for kw in keywords if kw and kw.strip()]
    scores = []

    for article in articles:
        try:
            title = (article.get('title') or '').lower()
            snippet = (article.get('snippet') or '').lower()
            link_verified = article.get('link_verified', 'False')

            title_hits = sum(1 for kw in keywords if kw.lower() in title)
            snippet_hits = sum(1 for kw in keywords if kw.lower() in snippet)
            has_verified = 1.0 if link_verified == 'True' else 0.0

            score = (title_hits * 2.0) + (snippet_hits * 1.0) + (has_verified * 0.5)
            scores.append(score)
        except Exception as e:
            logger.warning(f"Error computing cold start score: {e}")
            scores.append(0.0)

    # Normalize to [0, 1]
    scores = np.array(scores, dtype=np.float32)
    max_score = scores.max() if scores.max() > 0 else 1.0
    scores = scores / max_score

    return scores.tolist()


def predict(
    articles: List[Dict],
    keywords: List[str],
    model_path: Path = MODEL_PATH,
) -> List[Dict]:
    """
    Predict ML scores for articles.

    Uses trained model if available, falls back to keyword scoring.

    Args:
        articles: List of article dicts
        keywords: List of keywords
        model_path: Path to joblib model file

    Returns:
        List of dicts: {'url': str, 'ml_score': float, 'ml_label': str, 'ml_mode': str}
        ml_label: 'top5' if score >= 0.5, else 'skip'
        ml_mode: 'model' or 'cold_start'
    """
    if not articles:
        return []

    try:
        # Try to load and use model
        model = load_model(model_path)
        if model is not None and SKLEARN_AVAILABLE:
            source_scores = {}  # Would need historical data to compute properly
            X = extract_features(articles, keywords, source_scores)
            probas = model.predict_proba(X)[:, 1]  # Probability of class 1

            results = []
            for i, article in enumerate(articles):
                score = float(probas[i])
                results.append({
                    'url': article.get('url', ''),
                    'ml_score': score,
                    'ml_label': 'top5' if score >= 0.5 else 'skip',
                    'ml_mode': 'model',
                })
            return results

    except Exception as e:
        logger.warning(f"Error using trained model: {e}, falling back to cold start")

    # Fallback: cold start scoring
    try:
        scores = cold_start_score(articles, keywords)
        results = []
        for i, article in enumerate(articles):
            score = scores[i]
            results.append({
                'url': article.get('url', ''),
                'ml_score': score,
                'ml_label': 'top5' if score >= 0.5 else 'skip',
                'ml_mode': 'cold_start',
            })
        return results
    except Exception as e:
        logger.error(f"Error in cold start scoring: {e}")
        # Return neutral scores
        return [
            {
                'url': article.get('url', ''),
                'ml_score': 0.5,
                'ml_label': 'skip',
                'ml_mode': 'cold_start',
            }
            for article in articles
        ]


def retrain(
    candidates_dir: str,
    selections_dir: str,
    keywords: List[str],
    model_path: Path = MODEL_PATH,
) -> Dict:
    """
    Full retrain pipeline: build data -> train -> save.

    Args:
        candidates_dir: Directory with candidates-*.csv
        selections_dir: Directory with selections-*.csv
        keywords: List of keywords
        model_path: Where to save model

    Returns:
        Dict with keys: success, mode, n_samples, n_positive, model_path
        mode: 'trained' or 'insufficient_data'
    """
    try:
        # Build training dataset
        df = build_training_dataset(candidates_dir, selections_dir, keywords)

        if df.empty or len(df) == 0:
            logger.warning("Empty training dataset")
            return {
                'success': True,
                'mode': 'insufficient_data',
                'n_samples': 0,
                'n_positive': 0,
                'model_path': None,
            }

        n_samples = len(df)
        n_positive = int((df['label'] == 1).sum())

        # Check if sufficient data
        if n_samples < MIN_TRAINING_EXAMPLES:
            logger.info(f"Insufficient data for training: {n_samples} < {MIN_TRAINING_EXAMPLES}")
            return {
                'success': True,
                'mode': 'insufficient_data',
                'n_samples': n_samples,
                'n_positive': n_positive,
                'model_path': None,
            }

        # Train model
        model = train_model(df, keywords)

        # Save model
        save_model(model, model_path)

        return {
            'success': True,
            'mode': 'trained',
            'n_samples': n_samples,
            'n_positive': n_positive,
            'model_path': str(model_path),
        }

    except Exception as e:
        logger.error(f"Error during retrain: {e}")
        return {
            'success': False,
            'mode': 'error',
            'n_samples': 0,
            'n_positive': 0,
            'model_path': None,
            'error': str(e),
        }
