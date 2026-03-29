"""
PythonAnywhere WSGI entry point for NewsCurator Flask app.

File path on PythonAnywhere:
  /var/www/chaody_pythonanywhere_com_wsgi.py should import from this file,
  OR you can paste this content directly into the PythonAnywhere WSGI config.

Usage in PythonAnywhere WSGI config:
  import sys
  sys.path.insert(0, '/home/Chaody/NewsCurator')
  from wsgi import application
"""

import sys
import os

# Project home directory on PythonAnywhere
project_home = '/home/Chaody/NewsCurator'

if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set working directory so relative CSV paths resolve correctly
os.chdir(project_home)

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, '.env'))

# Import Flask app as 'application' (required by WSGI standard)
from src.app import app as application
