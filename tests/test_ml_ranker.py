"""
Unit tests for ML ranking module.
"""

import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest import mock

import pytest
import pandas as pd
import numpy as np

from src.ml_ranker import (
    extract_features,
    compute_source_scores,
    build_training_dataset,
    train_model,
    save_model,
    load_model,
    cold_start_score,
    predict,
    retrain,
    MIN_TRAINING_EXAMPLES,
)


class TestExtractFeatures:
    """Test feature extraction (pure unit tests, no mocking)."""

    def test_keyword_title_hit(self):
        """Article with keyword in title should have keyword_title_count > 0."""
        articles = [{'title': 'TSMC Q1 Earnings', 'snippet': '', 'source': '',
                     'published_at': '', 'link_verified': 'False'}]
        keywords = ['TSMC', 'Samsung']

        features = extract_features(articles, keywords)

        assert features.shape == (1, 12)
        assert features[0, 0] > 0  # keyword_title_count

    def test_keyword_snippet_hit(self):
        """Article with keyword in snippet."""
        articles = [{'title': 'Chip News', 'snippet': 'Samsung released new 3nm',
                     'source': '', 'published_at': '', 'link_verified': 'False'}]
        keywords = ['Samsung']

        features = extract_features(articles, keywords)

        assert features[0, 1] > 0  # keyword_snippet_count

    def test_verified_link_feature(self):
        """Verified link should produce feature value 1.0."""
        articles = [{'title': '', 'snippet': '', 'source': '',
                     'published_at': '', 'link_verified': 'True'}]
        keywords = []

        features = extract_features(articles, keywords)

        assert features[0, 6] == 1.0  # has_verified_link

    def test_missing_snippet_handled(self):
        """Missing snippet should not crash, snippet_length should be 0."""
        articles = [{'title': 'Title', 'snippet': None, 'source': '',
                     'published_at': '', 'link_verified': 'False'}]
        keywords = []

        features = extract_features(articles, keywords)

        assert features[0, 4] == 0.0  # snippet_length

    def test_hours_since_published_capped(self):
        """Very old published_at should be capped at 72."""
        old_date = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        articles = [{'title': '', 'snippet': '', 'source': '',
                     'published_at': old_date, 'link_verified': 'False'}]
        keywords = []

        features = extract_features(articles, keywords)

        assert features[0, 7] == 72.0  # hours_since_published capped

    def test_feature_vector_shape(self):
        """Three articles should produce shape (3, 12)."""
        articles = [
            {'title': f'Article {i}', 'snippet': f'Snippet {i}', 'source': 'Source',
             'published_at': datetime.now(timezone.utc).isoformat(),
             'link_verified': 'False'}
            for i in range(3)
        ]
        keywords = []

        features = extract_features(articles, keywords)

        assert features.shape == (3, 12)

    def test_malformed_article_uses_zeros(self):
        """Article with missing fields should not crash."""
        articles = [{}]  # Empty dict

        features = extract_features(articles, [])

        assert features.shape == (1, 12)
        assert np.all(np.isfinite(features))


class TestComputeSourceScores:
    """Test source credibility scoring."""

    def test_source_appears_multiple_times(self):
        """Source with 2/3 selections should score ~0.67."""
        df = pd.DataFrame({
            'source': ['Reuters', 'Reuters', 'Reuters', 'Bloomberg'],
            'label': [1, 1, 0, 1],
        })

        scores = compute_source_scores(df)

        # Reuters: (2 selected + 1) / (3 total + 2) = 3/5 = 0.6
        assert 'Reuters' in scores
        assert 0.55 < scores['Reuters'] < 0.65

    def test_unknown_source_gets_default(self):
        """Source not in training data should not appear in result."""
        df = pd.DataFrame({'source': ['Reuters'], 'label': [1]})

        scores = compute_source_scores(df)

        assert 'Bloomberg' not in scores
        assert 'Reuters' in scores

    def test_empty_dataframe(self):
        """Empty df should return empty dict."""
        df = pd.DataFrame({'source': [], 'label': []})

        scores = compute_source_scores(df)

        assert scores == {}


class TestColdStartScore:
    """Test cold-start keyword-based scoring."""

    def test_more_keywords_higher_score(self):
        """Article with 3 keyword hits should score higher than 1 hit."""
        articles = [
            {'title': 'TSMC Samsung Intel chips', 'snippet': '', 'source': '',
             'published_at': '', 'link_verified': 'False'},
            {'title': 'TSMC news', 'snippet': '', 'source': '',
             'published_at': '', 'link_verified': 'False'},
        ]
        keywords = ['TSMC', 'Samsung', 'Intel']

        scores = cold_start_score(articles, keywords)

        assert scores[0] > scores[1]

    def test_scores_normalized_0_to_1(self):
        """All scores should be in [0, 1]."""
        articles = [
            {'title': f'Article {i}', 'snippet': 'snippet', 'source': '',
             'published_at': '', 'link_verified': 'False'}
            for i in range(5)
        ]
        keywords = ['TSMC', 'Samsung']

        scores = cold_start_score(articles, keywords)

        assert all(0 <= s <= 1 for s in scores)

    def test_empty_articles_returns_empty(self):
        """Empty articles list should return empty list."""
        scores = cold_start_score([], [])

        assert scores == []


class TestBuildTrainingDataset:
    """Test training data builder (uses tmp_path for file I/O)."""

    def test_join_candidates_with_selections(self, tmp_path):
        """Candidates joined with selections should get proper labels."""
        # Write candidates file
        candidates_csv = tmp_path / 'candidates-2026-03-20.csv'
        candidates_csv.write_text(
            'title,url,source,published_at,snippet,link_verified,fetch_timestamp\n'
            'Article 1,https://example.com/1,Reuters,2026-03-20T00:00:00Z,Snippet 1,True,2026-03-20\n'
            'Article 2,https://example.com/2,Bloomberg,2026-03-20T00:00:00Z,Snippet 2,True,2026-03-20\n'
            'Article 3,https://example.com/3,TechNews,2026-03-20T00:00:00Z,Snippet 3,True,2026-03-20\n'
        )

        # Write selections file
        selections_csv = tmp_path / 'selections-2026-03-20.csv'
        selections_csv.write_text(
            'url,title,rank,timestamp\n'
            'https://example.com/1,Article 1,5,2026-03-20T10:00:00Z\n'
            'https://example.com/2,Article 2,skip,2026-03-20T10:00:00Z\n'
        )

        df = build_training_dataset(str(tmp_path), str(tmp_path), [])

        # Article 1: rank 5 (5★) -> label 1 (positive)
        # Article 2: rank skip -> label 0
        # Article 3: no selection -> label 0
        assert len(df) == 3
        assert df[df['url'] == 'https://example.com/1']['label'].iloc[0] == 1
        assert df[df['url'] == 'https://example.com/2']['label'].iloc[0] == 0
        assert df[df['url'] == 'https://example.com/3']['label'].iloc[0] == 0

    def test_missing_selections_file_labels_all_zero(self, tmp_path):
        """If no selections file exists, all articles should be labeled 0."""
        candidates_csv = tmp_path / 'candidates-2026-03-20.csv'
        candidates_csv.write_text(
            'title,url,source,published_at,snippet,link_verified,fetch_timestamp\n'
            'Article 1,https://example.com/1,Reuters,2026-03-20T00:00:00Z,Snippet 1,True,2026-03-20\n'
        )

        df = build_training_dataset(str(tmp_path), str(tmp_path), [])

        assert len(df) == 1
        assert df['label'].iloc[0] == 0

    def test_multiple_dates_combined(self, tmp_path):
        """Multiple weeks of data should be combined."""
        for i in range(2):
            date = f'2026-03-{20+i:02d}'
            candidates_csv = tmp_path / f'candidates-{date}.csv'
            candidates_csv.write_text(
                'title,url,source,published_at,snippet,link_verified,fetch_timestamp\n'
                f'Article {i},https://example.com/{i},Reuters,{date}T00:00:00Z,Snippet,True,{date}\n'
            )

        df = build_training_dataset(str(tmp_path), str(tmp_path), [])

        assert len(df) == 2


class TestTrainModel:
    """Test model training."""

    def test_train_returns_fitted_pipeline(self, tmp_path):
        """Training on sufficient data should return fitted pipeline."""
        # Create dataset with 25 rows: 20 negative, 5 positive (4★ and 5★)
        df = pd.DataFrame({
            'title': ['Article'] * 25,
            'url': [f'https://example.com/{i}' for i in range(25)],
            'source': ['Reuters'] * 25,
            'published_at': [datetime.now(timezone.utc).isoformat()] * 25,
            'snippet': ['Snippet'] * 25,
            'link_verified': ['True'] * 25,
            'fetch_timestamp': ['2026-03-20'] * 25,
            'rank': ['skip'] * 20 + ['3', '3', '4', '4', '5'],
            'label': [0] * 20 + [0, 0, 1, 1, 1],  # Only 4★ and 5★ = positive (label=1)
        })

        model = train_model(df, ['Article'])

        assert hasattr(model, 'predict_proba')
        assert hasattr(model, 'predict')

    def test_train_raises_on_insufficient_data(self):
        """Training on <20 rows should raise ValueError."""
        df = pd.DataFrame({'label': [0, 1] * 5})

        with pytest.raises(ValueError):
            train_model(df, [])

    def test_train_works_with_imbalanced_classes(self):
        """Heavily imbalanced dataset (24 negative, 1 positive) should train with class_weight='balanced'."""
        df = pd.DataFrame({
            'title': ['Article'] * 25,
            'url': [f'https://example.com/{i}' for i in range(25)],
            'source': ['Reuters'] * 25,
            'published_at': [datetime.now(timezone.utc).isoformat()] * 25,
            'snippet': ['Snippet'] * 25,
            'link_verified': ['True'] * 25,
            'fetch_timestamp': ['2026-03-20'] * 25,
            'label': [0] * 24 + [1],  # 1 positive out of 25
        })

        model = train_model(df, [])

        assert model is not None


class TestSaveLoadModel:
    """Test model serialization."""

    @mock.patch('src.ml_ranker.joblib')
    def test_save_creates_directory(self, mock_joblib, tmp_path):
        """Save should create parent directory if missing."""
        nested_path = tmp_path / 'nested' / 'dir' / 'model.joblib'
        model = mock.Mock()

        save_model(model, nested_path)

        assert nested_path.parent.exists()
        mock_joblib.dump.assert_called_once()

    @mock.patch('src.ml_ranker.joblib')
    def test_load_returns_none_if_missing(self, mock_joblib, tmp_path):
        """Load should return None if file doesn't exist."""
        model = load_model(tmp_path / 'nonexistent.joblib')

        assert model is None
        mock_joblib.load.assert_not_called()

    def test_save_and_load_roundtrip(self, tmp_path):
        """Save and load should preserve model (integration test)."""
        df = pd.DataFrame({
            'title': ['Article'] * 25,
            'url': [f'https://example.com/{i}' for i in range(25)],
            'source': ['Reuters'] * 25,
            'published_at': [datetime.now(timezone.utc).isoformat()] * 25,
            'snippet': ['Snippet'] * 25,
            'link_verified': ['True'] * 25,
            'fetch_timestamp': ['2026-03-20'] * 25,
            'label': [0] * 20 + [1] * 5,
        })

        model = train_model(df, [])
        save_model(model, tmp_path / 'test_model.joblib')

        loaded = load_model(tmp_path / 'test_model.joblib')

        assert loaded is not None
        assert hasattr(loaded, 'predict_proba')


class TestPredict:
    """Test prediction endpoint."""

    @mock.patch('src.ml_ranker.load_model')
    def test_predict_uses_model_when_available(self, mock_load_model):
        """If model exists, should use it."""
        mock_pipeline = mock.Mock()
        mock_pipeline.predict_proba.return_value = np.array([[0.3, 0.7], [0.6, 0.4]])
        mock_load_model.return_value = mock_pipeline

        articles = [
            {'title': 'Article 1', 'snippet': '', 'source': '', 'published_at': '', 'link_verified': 'False'},
            {'title': 'Article 2', 'snippet': '', 'source': '', 'published_at': '', 'link_verified': 'False'},
        ]

        results = predict(articles, [])

        assert len(results) == 2
        assert results[0]['ml_mode'] == 'model'
        assert results[1]['ml_mode'] == 'model'

    @mock.patch('src.ml_ranker.load_model')
    def test_predict_falls_back_to_cold_start(self, mock_load_model):
        """If model missing, should fall back to cold start."""
        mock_load_model.return_value = None

        articles = [
            {'title': 'TSMC Article', 'snippet': '', 'source': '', 'published_at': '', 'link_verified': 'False'},
        ]
        keywords = ['TSMC']

        results = predict(articles, keywords)

        assert results[0]['ml_mode'] == 'cold_start'
        assert results[0]['ml_score'] > 0

    def test_predict_never_raises(self):
        """Predict should never crash, even with malformed input."""
        articles = [
            {},  # Empty dict
            {'title': None},  # None title
            {'title': 'OK', 'snippet': 'OK'},  # OK
        ]

        results = predict(articles, [])

        assert len(results) == 3
        assert all('ml_score' in r for r in results)

    @mock.patch('src.ml_ranker.load_model')
    def test_predict_output_structure(self, mock_load_model):
        """Each result should have required keys."""
        mock_load_model.return_value = None

        articles = [{'title': 'Article', 'snippet': '', 'source': '', 'published_at': '', 'link_verified': 'False'}]

        results = predict(articles, [])

        assert len(results) == 1
        result = results[0]
        assert 'url' in result
        assert 'ml_score' in result
        assert 'ml_label' in result
        assert 'ml_mode' in result
        assert result['ml_label'] in ['top5', 'skip']
        assert result['ml_mode'] in ['model', 'cold_start']


class TestRetrain:
    """Test full retrain pipeline."""

    @mock.patch('src.ml_ranker.save_model')
    @mock.patch('src.ml_ranker.train_model')
    @mock.patch('src.ml_ranker.build_training_dataset')
    def test_retrain_success_path(self, mock_build, mock_train, mock_save):
        """Retrain with sufficient data should return success."""
        df = pd.DataFrame({'label': [0] * 20 + [1] * 5})
        mock_build.return_value = df
        mock_train.return_value = mock.Mock()

        result = retrain('/candidates', '/selections', [])

        assert result['success'] is True
        assert result['mode'] == 'trained'
        assert result['n_samples'] == 25
        assert result['n_positive'] == 5

    @mock.patch('src.ml_ranker.build_training_dataset')
    def test_retrain_insufficient_data(self, mock_build):
        """Retrain with <20 rows should return insufficient_data."""
        df = pd.DataFrame({'label': [0] * 10})
        mock_build.return_value = df

        result = retrain('/candidates', '/selections', [])

        assert result['success'] is True
        assert result['mode'] == 'insufficient_data'
        assert result['n_samples'] == 10

    @mock.patch('src.ml_ranker.build_training_dataset')
    def test_retrain_empty_data(self, mock_build):
        """Retrain with empty data should return insufficient_data."""
        mock_build.return_value = pd.DataFrame()

        result = retrain('/candidates', '/selections', [])

        assert result['success'] is True
        assert result['mode'] == 'insufficient_data'
        assert result['n_samples'] == 0
