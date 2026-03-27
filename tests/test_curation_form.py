"""
Tests for curation_form module.

Coverage:
- CurationSelection class
- load_candidates_csv()
- load_selections_csv()
- validate_selections()
- save_selections_csv()
- get_top_n_ranked()
"""

import pytest
from pathlib import Path
import tempfile

from src.curation_form import (
    CurationSelection,
    load_candidates_csv,
    load_selections_csv,
    validate_selections,
    save_selections_csv,
    get_top_n_ranked,
)


class TestCurationSelection:
    """Test CurationSelection data class."""

    def test_create_selection_ranked(self):
        """Test creating a ranked selection (1-7)."""
        selection = CurationSelection(
            url="https://example.com/article1",
            title="Test Article",
            rank="1"
        )
        assert selection.url == "https://example.com/article1"
        assert selection.title == "Test Article"
        assert selection.rank == "1"
        assert selection.is_selected is True

    def test_create_selection_skipped(self):
        """Test creating a skipped selection."""
        selection = CurationSelection(
            url="https://example.com/article2",
            title="Skipped Article",
            rank="skip"
        )
        assert selection.is_selected is False
        assert selection.rank == "skip"

    def test_invalid_rank(self):
        """Test invalid rank raises error."""
        with pytest.raises(ValueError, match="Invalid rank"):
            CurationSelection(
                url="https://example.com/article3",
                title="Bad Article",
                rank="8"
            )


class TestLoadCandidatesCSV:
    """Test load_candidates_csv() function."""

    def test_load_candidates_success(self, tmp_path):
        """Test loading valid candidates CSV."""
        # Create temp CSV with candidate articles
        csv_file = tmp_path / "candidates.csv"
        csv_file.write_text(
            "title,url,source,published_at,snippet,link_verified,fetch_timestamp\n"
            "Article 1,https://example.com/1,Source A,2026-03-26T10:00:00Z,Snippet 1,True,2026-03-26T10:00:00Z\n"
            "Article 2,https://example.com/2,Source B,2026-03-26T09:00:00Z,Snippet 2,False,2026-03-26T10:00:00Z\n"
        )

        articles = load_candidates_csv(str(csv_file))
        assert len(articles) == 2
        assert articles[0]["title"] == "Article 1"
        assert articles[0]["url"] == "https://example.com/1"
        assert articles[1]["title"] == "Article 2"

    def test_load_candidates_missing_file(self):
        """Test loading non-existent file."""
        with pytest.raises(FileNotFoundError):
            load_candidates_csv("/nonexistent/path/candidates.csv")


class TestLoadSelectionsCSV:
    """Test load_selections_csv() function."""

    def test_load_selections_success(self, tmp_path):
        """Test loading valid selections CSV."""
        # Create temp CSV with selections
        csv_file = tmp_path / "selections.csv"
        csv_file.write_text(
            "url,title,rank,timestamp\n"
            "https://example.com/1,Article 1,1,2026-03-26T10:00:00\n"
            "https://example.com/2,Article 2,2,2026-03-26T10:00:00\n"
        )

        selections = load_selections_csv(str(csv_file))
        assert len(selections) == 2
        assert selections[0].url == "https://example.com/1"
        assert selections[0].rank == "1"
        assert selections[0].is_selected is True
        assert selections[1].rank == "2"

    def test_load_selections_missing_file(self):
        """Test loading non-existent selections file."""
        selections = load_selections_csv("/nonexistent/path/selections.csv")
        assert selections == []


class TestValidateSelections:
    """Test validate_selections() function."""

    def test_validate_success(self):
        """Test valid selections pass validation."""
        selections = [
            CurationSelection(f"https://example.com/{i}", f"Article {i}", str(i))
            for i in range(1, 7)  # Create ranks 1-6
        ]
        assert validate_selections(selections) is True

    def test_validate_too_few_ranked(self):
        """Test validation fails with <6 ranked stories."""
        selections = [
            CurationSelection(f"https://example.com/{i}", f"Article {i}", str(i))
            for i in range(1, 6)  # Create only 5 ranked
        ]
        selections.extend([
            CurationSelection(f"https://example.com/skip{i}", f"Skip {i}", "skip")
            for i in range(1, 6)
        ])

        with pytest.raises(ValueError, match="At least 6 stories must be ranked"):
            validate_selections(selections)

    def test_validate_duplicate_urls(self):
        """Test validation fails with duplicate URLs."""
        selections = [
            CurationSelection("https://example.com/1", "Article 1", "1"),
            CurationSelection("https://example.com/1", "Article 1 Duplicate", "2"),  # Same URL
            CurationSelection("https://example.com/3", "Article 3", "3"),
            CurationSelection("https://example.com/4", "Article 4", "4"),
            CurationSelection("https://example.com/5", "Article 5", "5"),
            CurationSelection("https://example.com/6", "Article 6", "6"),
        ]

        with pytest.raises(ValueError, match="Duplicate URLs found"):
            validate_selections(selections)

    def test_validate_all_skipped(self):
        """Test validation fails when all stories skipped."""
        selections = [
            CurationSelection(f"https://example.com/{i}", f"Skip {i}", "skip")
            for i in range(1, 11)
        ]

        with pytest.raises(ValueError, match="At least 6 stories must be ranked"):
            validate_selections(selections)


class TestSaveSelectionsCSV:
    """Test save_selections_csv() function."""

    def test_save_selections_success(self, tmp_path):
        """Test successful selections save."""
        csv_file = tmp_path / "selections_out.csv"
        selections = [
            CurationSelection(f"https://example.com/{i}", f"Article {i}", str(i))
            for i in range(1, 8)  # Create ranks 1-7
        ]

        save_selections_csv(selections, str(csv_file))

        assert csv_file.exists()
        content = csv_file.read_text()
        assert "url,title,rank,timestamp" in content
        assert "https://example.com/1" in content
        assert ",1," in content  # Rank 1 as CSV field (unquoted)

    def test_save_selections_invalid(self, tmp_path):
        """Test saving invalid selections."""
        csv_file = tmp_path / "selections_invalid.csv"
        selections = [
            CurationSelection(f"https://example.com/{i}", f"Article {i}", str(i))
            for i in range(1, 5)  # Only 4 ranked (less than 6)
        ]

        with pytest.raises(ValueError, match="At least 6 stories must be ranked"):
            save_selections_csv(selections, str(csv_file))


class TestGetTopNRanked:
    """Test get_top_n_ranked() function."""

    def test_get_top_5(self):
        """Test getting top 5 ranked stories."""
        selections = [
            CurationSelection("https://example.com/1", "Article 1", "1"),
            CurationSelection("https://example.com/2", "Article 2", "2"),
            CurationSelection("https://example.com/3", "Article 3", "3"),
            CurationSelection("https://example.com/4", "Article 4", "4"),
            CurationSelection("https://example.com/5", "Article 5", "5"),
            CurationSelection("https://example.com/6", "Article 6", "6"),
            CurationSelection("https://example.com/7", "Article 7", "7"),
            CurationSelection("https://example.com/skip1", "Skipped", "skip"),
        ]

        top_5 = get_top_n_ranked(selections, n=5)
        assert len(top_5) == 5
        assert top_5[0]["rank"] == "1"
        assert top_5[1]["rank"] == "2"
        assert top_5[4]["rank"] == "5"

    def test_get_top_fewer_than_n(self):
        """Test when fewer than N ranked stories exist."""
        selections = [
            CurationSelection("https://example.com/1", "Article 1", "1"),
            CurationSelection("https://example.com/2", "Article 2", "2"),
            CurationSelection("https://example.com/3", "Article 3", "3"),
            CurationSelection("https://example.com/skip1", "Skipped 1", "skip"),
            CurationSelection("https://example.com/skip2", "Skipped 2", "skip"),
        ]

        top_5 = get_top_n_ranked(selections, n=5)
        assert len(top_5) == 3
        assert [item["rank"] for item in top_5] == ["1", "2", "3"]

    def test_get_top_all_skipped(self):
        """Test when all stories are skipped."""
        selections = [
            CurationSelection(f"https://example.com/skip{i}", f"Skip {i}", "skip")
            for i in range(1, 6)
        ]

        top = get_top_n_ranked(selections, n=5)
        assert top == []
