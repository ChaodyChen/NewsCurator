"""
Tests for Google Drive integration module.

Mocks the Google Drive API to test upload/download functions.
"""

import pytest
import os
import tempfile
from unittest.mock import MagicMock, patch, call
from io import BytesIO

from src.google_drive import (
    get_drive_service,
    upload_csv,
    download_csv,
    list_csv_files,
    _find_file_by_name,
)


class TestGetDriveService:
    """Tests for get_drive_service()."""

    @patch.dict(os.environ, {'GOOGLE_APPLICATION_CREDENTIALS': '/fake/path.json'})
    @patch('src.google_drive.service_account.Credentials.from_service_account_file')
    @patch('src.google_drive.build')
    def test_get_drive_service_success(self, mock_build, mock_from_file):
        """Test successful authentication."""
        mock_creds = MagicMock()
        mock_from_file.return_value = mock_creds
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        # Mock the file existence check
        with patch('os.path.exists', return_value=True):
            service = get_drive_service()

        assert service == mock_service
        mock_from_file.assert_called_once_with('/fake/path.json', scopes=['https://www.googleapis.com/auth/drive.file'])
        mock_build.assert_called_once_with('drive', 'v3', credentials=mock_creds)

    def test_get_drive_service_missing_env_var(self):
        """Test error when GOOGLE_APPLICATION_CREDENTIALS not set."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="GOOGLE_APPLICATION_CREDENTIALS"):
                get_drive_service()

    @patch.dict(os.environ, {'GOOGLE_APPLICATION_CREDENTIALS': '/nonexistent/path.json'})
    def test_get_drive_service_missing_file(self):
        """Test error when credentials file doesn't exist."""
        with patch('os.path.exists', return_value=False):
            with pytest.raises(FileNotFoundError):
                get_drive_service()


class TestFindFileByName:
    """Tests for _find_file_by_name()."""

    def test_find_file_found(self):
        """Test finding an existing file."""
        mock_service = MagicMock()
        mock_files_resource = MagicMock()
        mock_service.files.return_value = mock_files_resource
        mock_list = MagicMock()
        mock_files_resource.list.return_value = mock_list
        mock_execute = MagicMock(return_value={'files': [{'id': 'file-123', 'name': 'test.csv'}]})
        mock_list.execute.return_value = mock_execute

        result = _find_file_by_name(mock_service, 'folder-456', 'test.csv')

        # File ID returned should match response
        mock_list.execute.assert_called_once()

    def test_find_file_not_found(self):
        """Test when file doesn't exist."""
        mock_service = MagicMock()
        mock_files_resource = MagicMock()
        mock_service.files.return_value = mock_files_resource
        mock_list = MagicMock()
        mock_files_resource.list.return_value = mock_list
        mock_execute = MagicMock(return_value={'files': []})
        mock_list.execute.return_value = mock_execute

        with patch.object(mock_list, 'execute', return_value={'files': []}):
            result = _find_file_by_name(mock_service, 'folder-456', 'nonexistent.csv')

        assert result is None


class TestUploadCsv:
    """Tests for upload_csv()."""

    def test_upload_csv_new_file(self):
        """Test uploading a new file (not replacing existing)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('title,url\nTest,https://example.com\n')
            temp_path = f.name

        try:
            mock_service = MagicMock()

            # Mock _find_file_by_name to return None (file doesn't exist)
            with patch('src.google_drive._find_file_by_name', return_value=None):
                with patch('src.google_drive.get_drive_service', return_value=mock_service):
                    # Mock the create operation
                    mock_files = MagicMock()
                    mock_service.files.return_value = mock_files
                    mock_create = MagicMock()
                    mock_files.create.return_value = mock_create
                    mock_create.execute.return_value = {'id': 'new-file-id'}

                    result = upload_csv(temp_path, 'test.csv', 'folder-id')

            assert result == 'new-file-id'
            mock_files.create.assert_called_once()
        finally:
            try:
                os.unlink(temp_path)
            except (OSError, PermissionError):
                pass  # File may be in use on Windows

    def test_upload_csv_update_existing(self):
        """Test updating an existing file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write('title,url\nTest,https://example.com\n')
            temp_path = f.name

        try:
            mock_service = MagicMock()

            # Mock _find_file_by_name to return existing file ID
            with patch('src.google_drive._find_file_by_name', return_value='existing-id'):
                with patch('src.google_drive.get_drive_service', return_value=mock_service):
                    # Mock the update operation
                    mock_files = MagicMock()
                    mock_service.files.return_value = mock_files
                    mock_update = MagicMock()
                    mock_files.update.return_value = mock_update
                    mock_update.execute.return_value = {'id': 'existing-id'}

                    result = upload_csv(temp_path, 'test.csv', 'folder-id')

            assert result == 'existing-id'
            mock_files.update.assert_called_once()
        finally:
            try:
                os.unlink(temp_path)
            except (OSError, PermissionError):
                pass  # File may be in use on Windows

    def test_upload_csv_file_not_found(self):
        """Test error when local file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            upload_csv('/nonexistent/file.csv', 'test.csv', 'folder-id')


class TestDownloadCsv:
    """Tests for download_csv()."""

    def test_download_csv_success(self):
        """Test successful download."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, 'downloaded.csv')
            mock_service = MagicMock()

            # Mock _find_file_by_name to return file ID
            with patch('src.google_drive._find_file_by_name', return_value='file-id-123'):
                with patch('src.google_drive.get_drive_service', return_value=mock_service):
                    # Mock the download operation
                    mock_files = MagicMock()
                    mock_service.files.return_value = mock_files
                    mock_get_media = MagicMock()
                    mock_files.get_media.return_value = mock_get_media

                    # Simulate file download with content
                    csv_content = b'title,url\nTest,https://example.com\n'

                    with patch('src.google_drive.MediaIoBaseDownload') as mock_downloader_class:
                        # Create a mock downloader that returns the content
                        mock_downloader = MagicMock()
                        mock_downloader_class.return_value = mock_downloader
                        mock_downloader.next_chunk.side_effect = [(None, False), (None, True)]

                        # Mock the BytesIO to return our content
                        with patch('src.google_drive.BytesIO') as mock_bytesio_class:
                            mock_bytesio = MagicMock()
                            mock_bytesio_class.return_value = mock_bytesio
                            mock_bytesio.getvalue.return_value = csv_content

                            result = download_csv('test.csv', 'folder-id', output_path)

            assert result is True
            assert os.path.exists(output_path)

    def test_download_csv_not_found(self):
        """Test when file doesn't exist in Drive."""
        mock_service = MagicMock()

        with patch('src.google_drive._find_file_by_name', return_value=None):
            with patch('src.google_drive.get_drive_service', return_value=mock_service):
                result = download_csv('nonexistent.csv', 'folder-id', '/tmp/out.csv')

        assert result is False


class TestListCsvFiles:
    """Tests for list_csv_files()."""

    def test_list_csv_files_success(self):
        """Test listing CSV files in folder."""
        mock_service = MagicMock()
        mock_files = MagicMock()
        mock_service.files.return_value = mock_files
        mock_list = MagicMock()
        mock_files.list.return_value = mock_list
        mock_list.execute.return_value = {
            'files': [
                {'id': 'id-1', 'name': 'candidates-2026-03-27.csv', 'createdTime': '2026-03-27T10:00:00Z'},
                {'id': 'id-2', 'name': 'selections-2026-03-27.csv', 'createdTime': '2026-03-27T12:00:00Z'},
            ]
        }

        with patch('src.google_drive.get_drive_service', return_value=mock_service):
            result = list_csv_files('folder-id')

        assert len(result) == 2
        assert result[0][0] == 'candidates-2026-03-27.csv'
        assert result[1][0] == 'selections-2026-03-27.csv'

    def test_list_csv_files_empty(self):
        """Test listing when folder has no CSV files."""
        mock_service = MagicMock()
        mock_files = MagicMock()
        mock_service.files.return_value = mock_files
        mock_list = MagicMock()
        mock_files.list.return_value = mock_list
        mock_execute = MagicMock(return_value={'files': []})
        mock_list.execute.return_value = mock_execute

        with patch('src.google_drive.get_drive_service', return_value=mock_service):
            result = list_csv_files('folder-id')

        assert result == []
