"""
Tests for Flask web application.

Coverage:
- GET / (health check)
- GET /curate (curation form)
- GET /api/candidates (candidates JSON)
- POST /api/rankings (submit rankings)
- Error handlers (400, 500)
"""

import pytest
import json
from unittest.mock import patch, MagicMock

# Import after setting up path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.app import app as flask_app


@pytest.fixture
def client():
    """Flask test client."""
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


class TestHealthCheck:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test GET / returns ok status."""
        response = client.get('/')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'
        assert data['service'] == 'news-curator'


class TestCurateForm:
    """Test curation form endpoint."""

    def test_curate_form_success(self, client):
        """Test GET /curate returns form."""
        response = client.get('/curate')
        assert response.status_code == 200
        assert response.content_type == 'text/html; charset=utf-8'
        assert b'Semiconductor News Curator' in response.data
        assert b'rank-buttons' in response.data  # Check for ranking UI

    def test_curate_form_custom_file(self, client):
        """Test GET /curate with custom candidates file parameter."""
        response = client.get('/curate?file=custom.csv')
        assert response.status_code == 200
        assert response.content_type == 'text/html; charset=utf-8'


class TestGetCandidatesJSON:
    """Test GET /api/candidates endpoint."""

    @patch('src.app.load_candidates_csv')
    @patch('src.app.load_selections_csv')
    def test_get_candidates_success(self, mock_selections, mock_candidates, client):
        """Test GET /api/candidates returns JSON."""
        mock_candidates.return_value = [
            {
                'title': 'Article 1',
                'url': 'https://example.com/1',
                'source': 'News Source',
                'published_at': '2026-03-26T10:00:00Z',
                'snippet': 'Preview text'
            }
        ]
        mock_selections.return_value = []

        response = client.get('/api/candidates')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'candidates' in data
        assert 'previous_selections' in data
        assert 'fetched_at' in data
        assert len(data['candidates']) == 1
        assert data['candidates'][0]['title'] == 'Article 1'

    @patch('src.app.load_candidates_csv')
    def test_get_candidates_missing_file(self, mock_load, client):
        """Test GET /api/candidates when file missing."""
        mock_load.side_effect = FileNotFoundError("candidates.csv not found")

        response = client.get('/api/candidates')
        assert response.status_code == 200  # Still 200, returns empty candidates
        data = json.loads(response.data)
        assert data['candidates'] == []


class TestPostRankings:
    """Test POST /api/rankings endpoint."""

    @patch('src.app.save_selections_csv')
    def test_post_rankings_success(self, mock_save, client):
        """Test POST /api/rankings with valid data."""
        rankings = [
            {'url': f'https://example.com/{i}', 'title': f'Article {i}', 'rank': str(i)}
            for i in range(1, 7)
        ]

        response = client.post(
            '/api/rankings',
            data=json.dumps({'rankings': rankings}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['num_ranked'] == 6
        assert data['num_skipped'] == 0

    def test_post_rankings_invalid_json(self, client):
        """Test POST /api/rankings with invalid JSON."""
        response = client.post(
            '/api/rankings',
            data='invalid json {',
            content_type='application/json'
        )
        # Flask returns 400 for bad JSON, but it may be wrapped as 500 by error handler
        assert response.status_code in [400, 500]

    @patch('src.app.save_selections_csv')
    def test_post_rankings_validation_failure(self, mock_save, client):
        """Test POST /api/rankings with invalid rankings."""
        # Only 5 ranked stories (less than 6)
        rankings = [
            {'url': f'https://example.com/{i}', 'title': f'Article {i}', 'rank': str(i)}
            for i in range(1, 6)
        ]

        response = client.post(
            '/api/rankings',
            data=json.dumps({'rankings': rankings}),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_post_rankings_missing_required_fields(self, client):
        """Test POST /api/rankings with missing fields."""
        response = client.post(
            '/api/rankings',
            data=json.dumps({'invalid_key': []}),
            content_type='application/json'
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data


class TestErrorHandlers:
    """Test error handling."""

    def test_404_not_found(self, client):
        """Test 404 error handling."""
        response = client.get('/nonexistent-route')
        assert response.status_code == 404

    def test_health_check_api(self, client):
        """Test /api/health endpoint."""
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'


class TestIntegration:
    """Integration tests for full workflow."""

    @patch('src.app.load_candidates_csv')
    @patch('src.app.load_selections_csv')
    @patch('src.app.save_selections_csv')
    def test_full_curation_workflow(
        self, mock_save, mock_old_selections, mock_candidates, client
    ):
        """Test full curation workflow: load form → submit rankings."""
        # Setup mocks
        mock_candidates.return_value = [
            {
                'title': f'Article {i}',
                'url': f'https://example.com/{i}',
                'source': 'News Source',
                'published_at': '2026-03-26T10:00:00Z',
                'snippet': f'Preview {i}'
            }
            for i in range(1, 10)
        ]
        mock_old_selections.return_value = []

        # 1. GET /api/candidates
        candidates_response = client.get('/api/candidates')
        assert candidates_response.status_code == 200
        candidates_data = json.loads(candidates_response.data)
        assert len(candidates_data['candidates']) == 9

        # 2. POST /api/rankings with 6 ranked articles
        rankings = [
            {'url': f'https://example.com/{i}', 'title': f'Article {i}', 'rank': str(i)}
            for i in range(1, 7)
        ]
        rankings_response = client.post(
            '/api/rankings',
            data=json.dumps({'rankings': rankings}),
            content_type='application/json'
        )
        assert rankings_response.status_code == 200
        rankings_data = json.loads(rankings_response.data)
        assert rankings_data['success'] is True
        assert rankings_data['num_ranked'] == 6
