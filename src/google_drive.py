"""
Google Drive integration for NewsCurator.

Provides functions to upload/download CSV files to/from Google Drive.
Uses service account authentication.
"""

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)

# Google Drive API scope for file access
SCOPES = ['https://www.googleapis.com/auth/drive.file']


def get_drive_service():
    """
    Authenticate and return a Google Drive API service object.

    Uses credentials from GOOGLE_APPLICATION_CREDENTIALS environment variable.
    Loads service account JSON and builds Drive API v3 client.

    Returns:
        googleapiclient.discovery.Resource: Authenticated Drive API service

    Raises:
        ValueError: If GOOGLE_APPLICATION_CREDENTIALS is not set
        FileNotFoundError: If credentials JSON file doesn't exist
        google.auth.exceptions.MalformedError: If JSON is invalid
    """
    creds_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not creds_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable not set")

    if not os.path.exists(creds_path):
        raise FileNotFoundError(f"Credentials file not found: {creds_path}")

    try:
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=credentials)
        logger.debug(f"Google Drive service authenticated using {creds_path}")
        return service
    except Exception as e:
        logger.error(f"Failed to authenticate Google Drive: {e}")
        raise


def _find_file_by_name(service, folder_id: str, filename: str) -> Optional[str]:
    """
    Find a file by name in a Drive folder.

    Args:
        service: Authenticated Drive API service
        folder_id: Google Drive folder ID
        filename: File name to search for

    Returns:
        str: File ID if found, None otherwise
    """
    try:
        query = f"'{folder_id}' in parents and name = '{filename}' and trashed = false"
        results = service.files().list(
            spaces='drive',
            pageSize=1,
            q=query,
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])
        if files:
            logger.debug(f"Found file in Drive: {filename}")
            return files[0]['id']
        else:
            logger.debug(f"File not found in Drive: {filename}")
            return None
    except HttpError as e:
        logger.error(f"Error searching Drive for {filename}: {e}")
        raise


def upload_csv(local_path: str, filename: str, folder_id: str) -> str:
    """
    Upload or update a CSV file to Google Drive.

    If a file with the same name exists in the folder, updates it.
    Otherwise creates a new file.

    Args:
        local_path: Path to local CSV file to upload
        filename: File name to use in Drive (e.g., 'candidates-2026-03-27.csv')
        folder_id: Google Drive folder ID to upload to

    Returns:
        str: File ID of uploaded file

    Raises:
        FileNotFoundError: If local_path doesn't exist
        ValueError: If folder_id is invalid
        google.auth.exceptions.MalformedError: If credentials invalid
    """
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Local file not found: {local_path}")

    service = get_drive_service()
    file_metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaFileUpload(local_path, mimetype='text/csv')

    existing_file_id = _find_file_by_name(service, folder_id, filename)

    try:
        if existing_file_id:
            # Update existing file
            result = service.files().update(
                fileId=existing_file_id,
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            logger.info(f"Updated file in Drive: {filename} (id={result['id']})")
            return result['id']
        else:
            # Create new file
            result = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            logger.info(f"Created file in Drive: {filename} (id={result['id']})")
            return result['id']
    except HttpError as e:
        logger.error(f"Error uploading {filename} to Drive: {e}")
        raise


def download_csv(filename: str, folder_id: str, local_path: str) -> bool:
    """
    Download a CSV file from Google Drive to local filesystem.

    Args:
        filename: File name in Drive (e.g., 'candidates-2026-03-27.csv')
        folder_id: Google Drive folder ID to download from
        local_path: Path where to save the file locally

    Returns:
        bool: True if file found and downloaded, False if not found

    Raises:
        IOError: If write to local_path fails
        google.auth.exceptions.MalformedError: If credentials invalid
    """
    service = get_drive_service()
    file_id = _find_file_by_name(service, folder_id, filename)

    if not file_id:
        logger.debug(f"File not found in Drive for download: {filename}")
        return False

    try:
        # Download file content
        request = service.files().get_media(fileId=file_id)
        file_content = BytesIO()
        downloader = MediaIoBaseDownload(file_content, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        # Write to local path
        with open(local_path, 'wb') as f:
            f.write(file_content.getvalue())

        logger.info(f"Downloaded file from Drive: {filename} -> {local_path}")
        return True

    except HttpError as e:
        logger.error(f"Error downloading {filename} from Drive: {e}")
        raise
    except IOError as e:
        logger.error(f"Error writing file to {local_path}: {e}")
        raise


def list_csv_files(folder_id: str) -> list:
    """
    List all CSV files in a Drive folder.

    Useful for debugging and monitoring.

    Args:
        folder_id: Google Drive folder ID

    Returns:
        list: List of tuples (filename, file_id) for all CSV files in folder

    Raises:
        google.auth.exceptions.MalformedError: If credentials invalid
    """
    service = get_drive_service()

    try:
        query = f"'{folder_id}' in parents and mimeType = 'text/csv' and trashed = false"
        results = service.files().list(
            spaces='drive',
            pageSize=50,
            q=query,
            fields='files(id, name, createdTime)',
            orderBy='createdTime desc'
        ).execute()

        files = results.get('files', [])
        logger.info(f"Listed {len(files)} CSV files in Drive folder {folder_id}")
        return [(f['name'], f['id']) for f in files]

    except HttpError as e:
        logger.error(f"Error listing files in Drive folder {folder_id}: {e}")
        raise
