"""
Flask web application for curation form.

Routes:
- GET /: Health check
- GET /curate: Serve curation form (displays candidates)
- POST /curate: Receive rankings, save to CSV
- GET /api/candidates: Get candidates as JSON
- POST /api/rankings: Submit rankings
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template, request, jsonify
from src.config import Config
from src.curation_form import (
    load_candidates_csv,
    load_selections_csv,
    validate_selections,
    save_selections_csv,
    CurationSelection,
)
from src.ml_ranker import predict as ml_predict, retrain as ml_retrain

logger = logging.getLogger(__name__)

# Flask app with custom template folder (one level up from src/)
template_dir = Path(__file__).parent.parent / 'templates'
app = Flask(__name__, template_folder=str(template_dir))
app.config.from_object(Config)


@app.route('/', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({'status': 'ok', 'service': 'news-curator'}), 200


@app.route('/curate', methods=['GET'])
def curate_form():
    """
    Serve curation form (HTML).

    Loads candidates CSV and displays as form.
    """
    try:
        # Get candidates CSV file path (allow override via query param for testing)
        candidates_file = request.args.get('file')
        if not candidates_file:
            # Default: today's candidates file
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            candidates_file = f'data/candidates-{today}.csv'

        # For now, use a default path; in production this would be from Google Drive
        # This allows the form to be served even if candidates file doesn't exist
        logger.info(f"Serving curation form (candidates_file: {candidates_file})")
        return render_template('curate.html')

    except Exception as e:
        logger.error(f"Error serving curation form: {e}")
        return jsonify({'error': 'Failed to load form', 'message': str(e)}), 500


@app.route('/api/candidates', methods=['GET'])
def get_candidates_json():
    """
    Get candidates as JSON (for frontend).

    Returns candidates CSV and previous selections for reference.
    """
    try:
        # Get candidates CSV file path (allow override for testing)
        candidates_file = request.args.get('file')
        if not candidates_file:
            # Default: today's candidates file
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            candidates_file = f'data/candidates-{today}.csv'

        # Try to load candidates from default location
        # In production, this would read from Google Drive
        candidates = []
        try:
            candidates = load_candidates_csv(candidates_file)
            logger.info(f"Loaded {len(candidates)} candidates from {candidates_file}")
        except FileNotFoundError:
            logger.warning(f"Candidates file not found: {candidates_file}, returning empty list")
            # Return empty candidates rather than error - allow form to still load
            candidates = []

        # Load previous selections for reference
        selections_file = request.args.get('selections_file')
        if not selections_file:
            # Default: today's selections file
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            selections_file = f'data/selections-{today}.csv'

        previous_selections = []
        try:
            selection_objs = load_selections_csv(selections_file)
            previous_selections = [{'url': s.url, 'rank': s.rank} for s in selection_objs]
            logger.info(f"Loaded {len(previous_selections)} previous selections")
        except Exception as e:
            logger.debug(f"Could not load previous selections: {e}")
            # It's OK if selections file doesn't exist yet

        return jsonify({
            'candidates': candidates,
            'previous_selections': previous_selections,
            'fetched_at': datetime.now(timezone.utc).isoformat()
        }), 200

    except Exception as e:
        logger.error(f"Error fetching candidates JSON: {e}")
        return jsonify({
            'error': 'Failed to load candidates',
            'message': str(e),
            'candidates': [],
            'previous_selections': []
        }), 500


@app.route('/api/rankings', methods=['POST'])
def submit_rankings():
    """
    Receive user rankings from form.

    Expected request body:
    ```json
    {
      "rankings": [
        {"url": "https://...", "title": "...", "rank": "1"},
        ...
      ]
    }
    ```

    Returns:
    ```json
    {
      "success": true,
      "message": "Rankings saved",
      "num_ranked": 6,
      "num_skipped": 14
    }
    ```
    """
    try:
        # Parse request JSON
        data = request.get_json()
        if not data or 'rankings' not in data:
            return jsonify({'error': 'Missing rankings in request'}), 400

        rankings = data['rankings']
        if not isinstance(rankings, list):
            return jsonify({'error': 'rankings must be a list'}), 400

        # Create CurationSelection objects
        selections = []
        for item in rankings:
            if not isinstance(item, dict) or 'url' not in item or 'rank' not in item:
                return jsonify({'error': 'Each ranking must have url and rank'}), 400

            try:
                selection = CurationSelection(
                    url=item['url'],
                    title=item.get('title', ''),
                    rank=item['rank']
                )
                selections.append(selection)
            except ValueError as e:
                logger.warning(f"Invalid ranking item: {e}")
                return jsonify({'error': f'Invalid ranking: {e}'}), 400

        # Validate selections
        try:
            validate_selections(selections)
        except ValueError as e:
            logger.warning(f"Validation failed: {e}")
            return jsonify({'error': 'Validation failed', 'message': str(e)}), 400

        # Save to CSV
        selections_file = request.args.get('file')
        if not selections_file:
            # Default: today's selections file
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            selections_file = f'data/selections-{today}.csv'

        try:
            save_selections_csv(selections, selections_file)
            logger.info(f"Saved {len(selections)} selections to {selections_file}")
        except IOError as e:
            logger.error(f"Failed to save selections: {e}")
            return jsonify({'error': 'Failed to save selections', 'message': str(e)}), 500

        # Calculate counts
        num_ranked = len([s for s in selections if s.is_selected])
        num_skipped = len(selections) - num_ranked

        return jsonify({
            'success': True,
            'message': 'Rankings saved',
            'num_ranked': num_ranked,
            'num_skipped': num_skipped,
            'filepath': selections_file
        }), 200

    except Exception as e:
        logger.error(f"Error submitting rankings: {e}")
        return jsonify({'error': 'Internal error', 'message': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check for monitoring."""
    return jsonify({'status': 'healthy'}), 200


@app.route('/api/ml-suggest', methods=['GET'])
def get_ml_suggestions():
    """
    Get ML-predicted scores for today's candidates.

    Returns JSON:
    {
      "suggestions": [
        {"url": "...", "ml_score": 0.82, "ml_label": "top5", "ml_mode": "model"},
        ...
      ],
      "mode": "model" | "cold_start",
      "model_exists": true | false
    }

    Always returns 200. On any error, returns empty suggestions list.
    """
    try:
        candidates_file = request.args.get('file')
        if not candidates_file:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            candidates_file = f'data/candidates-{today}.csv'

        try:
            candidates = load_candidates_csv(candidates_file)
        except FileNotFoundError:
            candidates = []

        if not candidates:
            return jsonify({
                'suggestions': [],
                'mode': 'cold_start',
                'model_exists': False
            }), 200

        # Get ML predictions
        suggestions = ml_predict(candidates, Config.KEYWORDS)
        mode = suggestions[0]['ml_mode'] if suggestions else 'cold_start'
        model_exists = mode == 'model'

        return jsonify({
            'suggestions': suggestions,
            'mode': mode,
            'model_exists': model_exists,
        }), 200

    except Exception as e:
        logger.error(f"Error getting ML suggestions: {e}")
        return jsonify({
            'suggestions': [],
            'mode': 'cold_start',
            'model_exists': False
        }), 200


@app.route('/api/retrain', methods=['POST'])
def trigger_retrain():
    """
    Trigger ML model retraining.

    Called after each curation session to incorporate new selections into training data.

    Returns JSON:
    {
      "success": true | false,
      "mode": "trained" | "insufficient_data" | "error",
      "n_samples": int,
      "n_positive": int,
      "model_path": str | null,
      "error": str | null
    }

    Always returns 200.
    """
    try:
        result = ml_retrain(
            Config.ML_CANDIDATES_DIR,
            Config.ML_SELECTIONS_DIR,
            Config.KEYWORDS
        )
        logger.info(f"Retrain result: {result}")
        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error triggering retrain: {e}")
        return jsonify({
            'success': False,
            'mode': 'error',
            'n_samples': 0,
            'n_positive': 0,
            'model_path': None,
            'error': str(e)
        }), 200


@app.errorhandler(400)
def bad_request(error):
    """Handle 400 errors."""
    return jsonify({'error': 'Bad request', 'message': str(error)}), 400


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors."""
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Validate config before starting
    try:
        Config.validate()
        logger.info("Configuration validated successfully")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise

    # Run app
    logger.info("Starting News Curator Flask app on http://127.0.0.1:5000/curate")
    app.run(host='127.0.0.1', port=5000, debug=False)
