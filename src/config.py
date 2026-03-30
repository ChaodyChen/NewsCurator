"""
Configuration management for News Curator application.
Loads environment variables and provides config object.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)


class Config:
    """Base configuration."""

    # NewsAPI
    NEWSAPI_KEY = os.getenv('NEWSAPI_KEY')

    # Google Drive
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    GOOGLE_DRIVE_FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER_ID')

    # LINE Bot
    LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
    LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
    LINE_GROUP_ID = os.getenv('LINE_GROUP_ID')

    # Email (fallback)
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    FALLBACK_RECIPIENT_EMAIL = os.getenv('FALLBACK_RECIPIENT_EMAIL')

    # Application settings
    KEYWORDS = os.getenv('KEYWORD_LIST', '').split(',')
    NEWS_SOURCES = os.getenv('NEWS_SOURCES', '').split(',')

    # Timing
    FETCH_HOUR = int(os.getenv('FETCH_HOUR', 6))
    FETCH_MINUTE = int(os.getenv('FETCH_MINUTE', 0))
    DELIVERY_HOUR = int(os.getenv('DELIVERY_HOUR', 8))
    DELIVERY_MINUTE = int(os.getenv('DELIVERY_MINUTE', 0))
    CURATION_DEADLINE_HOUR = int(os.getenv('CURATION_DEADLINE_HOUR', 22))
    CURATION_DEADLINE_MINUTE = int(os.getenv('CURATION_DEADLINE_MINUTE', 0))

    # System
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    MAX_ARTICLES_PER_FETCH = int(os.getenv('MAX_ARTICLES_PER_FETCH', 20))
    URL_TIMEOUT_SECONDS = int(os.getenv('URL_TIMEOUT_SECONDS', 5))
    MAX_ARTICLE_AGE_HOURS = int(os.getenv('MAX_ARTICLE_AGE_HOURS', 48))

    # ML settings (all optional with safe defaults)
    ML_MIN_TRAINING_EXAMPLES = int(os.getenv('ML_MIN_TRAINING_EXAMPLES', 20))
    ML_MODEL_PATH = os.getenv('ML_MODEL_PATH',
        str(Path(__file__).parent.parent / 'models' / 'ranker.joblib'))
    ML_CANDIDATES_DIR = os.getenv('ML_CANDIDATES_DIR',
        str(Path(__file__).parent.parent / 'data'))
    ML_SELECTIONS_DIR = os.getenv('ML_SELECTIONS_DIR',
        str(Path(__file__).parent.parent / 'data'))

    @classmethod
    def validate(cls):
        """Validate required configuration is set."""
        required = [
            'NEWSAPI_KEY',
            'LINE_CHANNEL_ACCESS_TOKEN',
            'LINE_GROUP_ID',
            'GOOGLE_DRIVE_FOLDER_ID',
            'GOOGLE_APPLICATION_CREDENTIALS'
        ]
        missing = [key for key in required if not getattr(cls, key)]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")

        # Verify credentials file exists
        creds_path = cls.GOOGLE_APPLICATION_CREDENTIALS
        if not os.path.exists(creds_path):
            raise ValueError(f"Google credentials file not found: {creds_path}")
