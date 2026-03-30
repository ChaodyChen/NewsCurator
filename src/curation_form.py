"""
Curation form backend: serve candidates, receive rankings, save to Google Drive.

Weekly workflow (Thursday-Sunday):
1. Load candidates CSV from Google Drive (candidates-{date}.csv)
2. Serve as JSON to web form
3. Receive user rankings (1-7, or "skip")
4. Validate and store in selections CSV (selections-{date}.csv)
"""

import logging
import csv
import json
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional
from pathlib import Path
from src.config import Config

logger = logging.getLogger(__name__)


class CurationSelection:
    """Represents a user's ranking of an article."""

    RANK_SKIP = "skip"
    VALID_RANKS = {"1", "2", "3", "4", "5", "skip"}

    def __init__(self, url: str, title: str, rank: str):
        self.url = url
        self.title = title
        self.rank = rank  # "1"-"5" (stars) or "skip"
        self.timestamp = datetime.now(timezone.utc).isoformat()

        if rank not in self.VALID_RANKS:
            raise ValueError(f"Invalid rank: {rank}. Must be 1-5 stars or 'skip'")

    def to_dict(self) -> Dict:
        """Convert to dictionary for CSV storage."""
        return {
            'url': self.url,
            'title': self.title,
            'rank': self.rank,
            'timestamp': self.timestamp,
        }

    @property
    def is_selected(self) -> bool:
        """Return True if ranked 1-5 stars (not skipped)."""
        return self.rank != self.RANK_SKIP


def load_candidates_csv(filepath: str) -> List[Dict]:
    """
    Load candidate articles from CSV.

    Load candidates from local CSV file (synced via GitHub).

    Expected columns: title, url, source, published_at, snippet, link_verified, fetch_timestamp

    Args:
        filepath: Path to candidates CSV

    Returns:
        List of article dicts

    Raises:
        FileNotFoundError: If CSV doesn't exist locally
        csv.Error: If CSV is malformed
    """
    articles = []

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Candidates file not found: {filepath}")

    try:
        with open(filepath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise csv.Error(f"CSV file has no headers: {filepath}")

            for row in reader:
                if row and any(row.values()):
                    articles.append(row)

        logger.info(f"Loaded {len(articles)} candidates from: {filepath}")
        return articles
    except csv.Error as e:
        logger.error(f"CSV parsing error in {filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading candidates from Drive: {e}")
        raise


def load_selections_csv(filepath: str) -> List[CurationSelection]:
    """
    Load previous selections from CSV (for reference during curation).

    Expected columns: url, title, rank, timestamp

    Args:
        filepath: Path to selections CSV (may not exist yet)

    Returns:
        List of CurationSelection objects (empty if file doesn't exist)
    """
    selections = []

    try:
        with open(filepath, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return selections

            for row in reader:
                if row and row.get('url'):  # Skip empty rows
                    try:
                        selection = CurationSelection(
                            url=row['url'],
                            title=row.get('title', ''),
                            rank=row['rank']
                        )
                        selections.append(selection)
                    except ValueError as e:
                        logger.warning(f"Skipping invalid selection row: {e}")
                        continue

        logger.info(f"Loaded {len(selections)} previous selections from {filepath}")

    except FileNotFoundError:
        logger.debug(f"Selections file not found (expected on first curation): {filepath}")
    except csv.Error as e:
        logger.error(f"CSV parsing error in {filepath}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error loading selections: {e}")
        raise

    return selections


def validate_selections(selections: List[CurationSelection]) -> bool:
    """
    Validate curation selections.

    Rules:
    - At least 3 stories must be rated 1-5 stars (not all skipped)
    - No duplicate URLs
    - All ranks must be in VALID_RANKS

    Args:
        selections: List of CurationSelection objects

    Returns:
        True if valid, raises ValueError otherwise

    Raises:
        ValueError: If validation fails
    """
    # Check at least 3 are rated (not "skip")
    ranked = [s for s in selections if s.is_selected]
    if len(ranked) < 3:
        raise ValueError(
            f"At least 3 stories must be rated (1-5 stars). "
            f"Currently rated: {len(ranked)}"
        )

    # Check for duplicate URLs
    urls = [s.url for s in selections]
    if len(urls) != len(set(urls)):
        duplicates = [url for url in urls if urls.count(url) > 1]
        raise ValueError(f"Duplicate URLs found: {set(duplicates)}")

    # Check all ranks are valid
    invalid_ranks = [s for s in selections if s.rank not in CurationSelection.VALID_RANKS]
    if invalid_ranks:
        raise ValueError(
            f"Invalid ranks found: {[(s.url, s.rank) for s in invalid_ranks]}"
        )

    logger.info(f"Validated {len(selections)} selections: {len(ranked)} ranked, {len(selections) - len(ranked)} skipped")
    return True


def save_selections_csv(selections: List[CurationSelection], filepath: str) -> None:
    """
    Save user selections to CSV and upload to Google Drive.

    Args:
        selections: List of CurationSelection objects
        filepath: Path to output CSV

    Raises:
        IOError: If write fails
        ValueError: If selections invalid (see validate_selections)
    """
    # Validate first
    validate_selections(selections)

    try:
        fieldnames = ['url', 'title', 'rank', 'timestamp']

        # Save to local file
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for selection in selections:
                writer.writerow(selection.to_dict())

        ranked_count = len([s for s in selections if s.is_selected])
        logger.info(f"Saved {len(selections)} selections ({ranked_count} ranked) to local: {filepath}")

        # CSV saved locally; git commit & push handles sharing via GitHub

    except IOError as e:
        logger.error(f"Failed to save selections to {filepath}: {e}")
        raise
    except ValueError as e:
        logger.error(f"Validation failed before saving: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error saving selections: {e}")
        raise


def get_top_n_ranked(selections: List[CurationSelection], n: int = 5) -> List[Dict]:
    """
    Get top N ranked stories from selections.

    Args:
        selections: List of CurationSelection objects
        n: Number of top stories (default 5)

    Returns:
        List of top N ranked selections as dicts, sorted by rank

    Note:
        If fewer than N stories are ranked, returns all ranked stories.
    """
    # Filter to only ranked stories (not "skip")
    ranked = [s for s in selections if s.is_selected]

    # Sort by rank descending (5★ first, higher stars = better)
    ranked_sorted = sorted(
        ranked,
        key=lambda s: -int(s.rank) if s.rank != "skip" else float('-inf')
    )

    # Return top N as dicts
    top_n = ranked_sorted[:n]
    result = [s.to_dict() for s in top_n]

    logger.info(f"Extracted top {len(result)} ranked stories (requested: {n})")
    return result
