"""
Fetch semiconductor news candidates from NewsAPI.

Daily workflow:
1. Fetch from NewsAPI with keyword + source filters
2. Verify each URL is accessible (HEAD request, 5-sec timeout)
3. Filter by timestamp (keep only <48h old)
4. Deduplicate by URL
5. Save to CSV on Google Drive
"""

import logging
import requests
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from requests.exceptions import RequestException, Timeout
from src.google_drive import upload_csv
from src.config import Config

logger = logging.getLogger(__name__)


class Article:
    """Represents a news article."""

    def __init__(self, title: str, url: str, source: str, published_at: str, snippet: str = ""):
        self.title = title
        self.url = url
        self.source = source
        self.published_at = published_at
        self.snippet = snippet
        self.link_verified = False
        self.fetch_timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict:
        """Convert to dictionary for CSV storage."""
        return {
            'title': self.title,
            'url': self.url,
            'source': self.source,
            'published_at': self.published_at,
            'snippet': self.snippet,
            'link_verified': self.link_verified,
            'fetch_timestamp': self.fetch_timestamp,
        }


def get_news_from_api(api_key: str, keywords: List[str], max_results: int = 100) -> List[Article]:
    """
    Fetch news from NewsAPI using keyword search.

    Args:
        api_key: NewsAPI API key
        keywords: List of keywords to search
        max_results: Maximum articles to return per keyword

    Returns:
        List of Article objects

    Raises:
        RequestException: If API call fails
    """
    if not api_key:
        raise ValueError("API key is required")

    articles = []
    base_url = "https://newsapi.org/v2/everything"

    for keyword in keywords:
        try:
            params = {
                "q": keyword,
                "apiKey": api_key,
                "pageSize": min(max_results, 100),  # NewsAPI max is 100 per request
                "sortBy": "publishedAt",
            }

            response = requests.get(base_url, params=params, timeout=10, verify=False)
            response.raise_for_status()  # Raise exception for bad status codes

            data = response.json()

            if data.get("status") != "ok":
                logger.error(f"NewsAPI error for keyword '{keyword}': {data.get('message')}")
                continue

            # Parse articles from response
            for article_data in data.get("articles", []):
                article = Article(
                    title=article_data.get("title", ""),
                    url=article_data.get("url", ""),
                    source=article_data.get("source", {}).get("name", "Unknown"),
                    published_at=article_data.get("publishedAt", ""),
                    snippet=article_data.get("description", "")
                )
                articles.append(article)

            logger.info(f"Fetched {len(data.get('articles', []))} articles for keyword '{keyword}'")

        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching news for keyword '{keyword}'")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching news for keyword '{keyword}': {e}")
        except Exception as e:
            logger.error(f"Unexpected error parsing articles for keyword '{keyword}': {e}")

    logger.info(f"Total articles fetched: {len(articles)}")
    return articles


def verify_url(url: str, timeout_seconds: int = 5) -> bool:
    """
    Verify URL is accessible by sending HEAD request.

    Args:
        url: URL to verify
        timeout_seconds: Timeout in seconds

    Returns:
        True if URL is accessible, False if dead/timeout

    Note:
        If timeout occurs, returns False but story is kept with link_verified=False
    """
    if not url or not url.startswith(("http://", "https://")):
        return False

    try:
        # Send HEAD request (faster than GET, just checks headers)
        response = requests.head(url, timeout=timeout_seconds, allow_redirects=True, verify=False)

        # Return True for successful responses (2xx, 3xx status codes)
        # Return False for 404, 410, and other client/server errors
        return 200 <= response.status_code < 400

    except Timeout:
        logger.debug(f"URL timeout (>{timeout_seconds}s): {url}")
        return False
    except requests.exceptions.ConnectionError:
        logger.debug(f"Connection error: {url}")
        return False
    except requests.exceptions.RequestException as e:
        logger.debug(f"Request error verifying {url}: {e}")
        return False
    except Exception as e:
        logger.debug(f"Unexpected error verifying {url}: {e}")
        return False


def filter_by_timestamp(articles: List[Article], max_age_hours: int = 48) -> List[Article]:
    """
    Filter articles to keep only recent ones (<max_age_hours old).

    Args:
        articles: List of articles
        max_age_hours: Maximum age in hours

    Returns:
        Filtered list of articles
    """
    now = datetime.utcnow()
    max_age = timedelta(hours=max_age_hours)
    filtered = []

    for article in articles:
        try:
            # Parse ISO 8601 timestamp (e.g., "2026-03-26T10:30:00Z")
            # Remove 'Z' suffix if present and parse
            pub_time_str = article.published_at.replace('Z', '+00:00')
            pub_time = datetime.fromisoformat(pub_time_str)

            # Make pub_time timezone-naive for comparison
            if pub_time.tzinfo is not None:
                pub_time = pub_time.replace(tzinfo=None)

            # Check if article is within max_age
            age = now - pub_time
            if age <= max_age:
                filtered.append(article)
            else:
                logger.debug(f"Article too old ({age.total_seconds()/3600:.1f}h): {article.title[:50]}")

        except ValueError as e:
            logger.warning(f"Could not parse timestamp '{article.published_at}': {e}")
            # Skip articles with unparseable timestamps
            continue
        except Exception as e:
            logger.warning(f"Error filtering article: {e}")
            continue

    logger.info(f"Filtered: {len(articles)} -> {len(filtered)} articles (keeping <{max_age_hours}h old)")
    return filtered


def deduplicate_by_url(articles: List[Article]) -> List[Article]:
    """
    Remove duplicate articles by URL.

    Handles URL normalization (http vs https, trailing slash).

    Args:
        articles: List of articles

    Returns:
        Deduplicated list (first occurrence kept)
    """
    seen_urls = set()
    deduplicated = []

    for article in articles:
        # Normalize URL: remove trailing slash, convert to lowercase
        normalized_url = article.url.lower().rstrip('/')

        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            deduplicated.append(article)
        else:
            logger.debug(f"Duplicate URL removed: {article.url}")

    logger.info(f"Deduplicated: {len(articles)} -> {len(deduplicated)} articles")
    return deduplicated


def save_to_csv(articles: List[Article], filepath: str) -> None:
    """
    Save articles to CSV file.

    Args:
        articles: List of articles to save
        filepath: Path to output CSV file
    """
    if not articles:
        logger.warning(f"No articles to save to {filepath}")
        return

    try:
        fieldnames = [
            'title',
            'url',
            'source',
            'published_at',
            'snippet',
            'link_verified',
            'fetch_timestamp'
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            # Write header row
            writer.writeheader()

            # Write article rows
            for article in articles:
                writer.writerow(article.to_dict())

        logger.info(f"Saved {len(articles)} articles to {filepath}")

    except IOError as e:
        logger.error(f"Failed to save CSV to {filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving CSV: {e}")
        raise


def fetch_and_save(
    api_key: str,
    keywords: List[str],
    output_filepath: str,
    max_age_hours: int = 48,
    url_timeout_seconds: int = 5,
    max_results: int = 100,
) -> int:
    """
    Full daily fetch pipeline: fetch → verify → filter → deduplicate → save.

    Args:
        api_key: NewsAPI key
        keywords: Keywords to search
        output_filepath: Where to save CSV
        max_age_hours: Keep only articles <this many hours old
        url_timeout_seconds: Timeout for URL verification
        max_results: Max articles per keyword

    Returns:
        Number of articles saved

    Raises:
        RequestException: If API fetch fails
        IOError: If CSV write fails
    """
    logger.info("Starting daily fetch pipeline...")

    # Step 1: Fetch from NewsAPI
    logger.info(f"Step 1: Fetching from NewsAPI ({len(keywords)} keywords)...")
    articles = get_news_from_api(api_key, keywords, max_results)
    logger.info(f"  Fetched {len(articles)} total articles")

    if not articles:
        logger.warning("No articles fetched. Aborting pipeline.")
        return 0

    # Step 2: Verify URLs (sequential)
    logger.info(f"Step 2: Verifying {len(articles)} URLs ({url_timeout_seconds}s timeout)...")
    verified_count = 0
    for article in articles:
        is_live = verify_url(article.url, url_timeout_seconds)
        article.link_verified = is_live
        if is_live:
            verified_count += 1
    logger.info(f"  {verified_count}/{len(articles)} URLs verified as live")

    # Step 3: Filter by timestamp
    logger.info(f"Step 3: Filtering by timestamp (<{max_age_hours}h old)...")
    articles = filter_by_timestamp(articles, max_age_hours)

    if not articles:
        logger.warning("No articles after timestamp filtering. Aborting.")
        return 0

    # Step 4: Deduplicate
    logger.info("Step 4: Deduplicating by URL...")
    articles = deduplicate_by_url(articles)

    if not articles:
        logger.warning("No articles after deduplication. Aborting.")
        return 0

    # Step 5: Save to CSV
    logger.info(f"Step 5: Saving {len(articles)} articles to {output_filepath}...")
    save_to_csv(articles, output_filepath)

    # Step 6: Upload to Google Drive
    try:
        logger.info("Step 6: Uploading to Google Drive...")
        filename = output_filepath.split('/')[-1]  # Extract filename from path
        upload_csv(output_filepath, filename, Config.GOOGLE_DRIVE_FOLDER_ID)
        logger.info(f"Uploaded {len(articles)} articles to Drive")
    except Exception as e:
        logger.error(f"Failed to upload to Drive (local CSV saved): {e}")
        # Continue - local CSV is saved even if Drive upload fails

    logger.info(f"Daily fetch pipeline complete: {len(articles)} articles saved")
    return len(articles)
