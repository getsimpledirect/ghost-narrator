import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import os
import sys
import types

# Mock qwen_tts before any app imports
_mock = types.ModuleType('qwen_tts')
_mock.QwenTTS = MagicMock
sys.modules.setdefault('qwen_tts', _mock)


def test_get_storage_backend_local():
    """Test that get_storage_backend returns LocalStorageBackend when STORAGE_BACKEND=local."""
    # Need to mock config before importing
    with patch.dict(
        os.environ,
        {
            'STORAGE_BACKEND': 'local',
            'OUTPUT_DIR': '/tmp/output',
            'SERVER_EXTERNAL_IP': 'localhost',
        },
    ):
        # Clear any cached imports
        if 'app.config' in sys.modules:
            del sys.modules['app.config']
        if 'app.domains.storage' in sys.modules:
            del sys.modules['app.domains.storage']
        if 'app.domains.storage.local' in sys.modules:
            del sys.modules['app.domains.storage.local']

        from app.domains.storage import get_storage_backend

        backend = get_storage_backend()

    from app.domains.storage import LocalStorageBackend

    assert isinstance(backend, LocalStorageBackend)


def test_get_storage_backend_unknown_raises():
    """Test that get_storage_backend raises ValueError for unknown backend."""
    # Clear any cached imports
    if 'app.domains.storage' in sys.modules:
        del sys.modules['app.domains.storage']

    from app.domains.storage import get_storage_backend

    with pytest.raises(ValueError, match='Unknown storage type'):
        get_storage_backend(config={'type': 'dropbox'})


@pytest.mark.asyncio
async def test_local_storage_upload(tmp_path):
    """Test LocalStorageBackend upload copies file and returns correct URI."""
    from app.domains.storage import LocalStorageBackend

    audio_file = tmp_path / 'test.mp3'
    audio_file.write_bytes(b'fake-audio')
    output_dir = tmp_path / 'output'
    output_dir.mkdir()

    backend = LocalStorageBackend(output_dir=output_dir, server_ip='localhost', port=8020)
    uri = await backend.upload(audio_file, job_id='job123', site_slug='site1')

    assert uri == 'local://job123.mp3'
    assert (output_dir / 'job123.mp3').exists()


def test_local_storage_make_public_url():
    """Test LocalStorageBackend generates correct public URL."""
    from app.domains.storage import LocalStorageBackend

    backend = LocalStorageBackend(output_dir=Path('/tmp'), server_ip='1.2.3.4', port=8020)
    url = backend.make_public_url('local://job123.mp3')
    assert url == 'http://1.2.3.4:8020/tts/download/job123'


@pytest.mark.asyncio
async def test_gcs_storage_upload(tmp_path):
    """Test GCSStorageBackend upload with mocked client."""
    # Mock the config values before importing
    with patch.dict(
        os.environ,
        {'GCS_BUCKET_NAME': 'my-bucket', 'GCS_AUDIO_PREFIX': 'audio/articles'},
    ):
        # Clear cached config and all storage modules
        for mod in list(sys.modules.keys()):
            if mod.startswith('app.config') or mod.startswith('app.domains.storage'):
                del sys.modules[mod]

        from app.domains.storage import GCSStorageBackend

        audio_file = tmp_path / 'test.mp3'
        audio_file.write_bytes(b'fake-audio')

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        with patch.object(GCSStorageBackend, '_get_client', return_value=mock_client):
            backend = GCSStorageBackend()
            uri = await backend.upload(audio_file, job_id='job1', site_slug='site1')

        assert uri == 'gs://my-bucket/audio/articles/site1/job1.mp3'
        mock_blob.upload_from_filename.assert_called_once()


def test_gcs_make_public_url():
    """Test GCSStorageBackend generates correct public URL."""
    with patch.dict(os.environ, {'GCS_BUCKET_NAME': 'my-bucket'}):
        # Clear cached config and both storage modules
        if 'app.config' in sys.modules:
            del sys.modules['app.config']
        if 'app.domains.storage.gcs' in sys.modules:
            del sys.modules['app.domains.storage.gcs']
        if 'app.domains.storage.gcs' in sys.modules:
            del sys.modules['app.domains.storage.gcs']

        from app.domains.storage import GCSStorageBackend

        backend = GCSStorageBackend()

    url = backend.make_public_url('gs://my-bucket/audio/articles/site1/job1.mp3')
    assert url == 'https://storage.googleapis.com/my-bucket/audio/articles/site1/job1.mp3'


@pytest.mark.asyncio
async def test_s3_storage_upload(tmp_path):
    """Test S3StorageBackend upload with mocked boto3."""
    boto3 = pytest.importorskip('boto3', reason='boto3 not installed')

    with patch.dict(
        os.environ,
        {
            'AWS_ACCESS_KEY_ID': 'key',
            'AWS_SECRET_ACCESS_KEY': 'secret',
            'AWS_REGION': 'us-east-1',
            'S3_BUCKET_NAME': 'my-bucket',
            'S3_AUDIO_PREFIX': 'audio/articles',
        },
    ):
        # Clear cached config and both storage modules
        if 'app.config' in sys.modules:
            del sys.modules['app.config']
        if 'app.domains.storage.s3' in sys.modules:
            del sys.modules['app.domains.storage.s3']
        if 'app.domains.storage.s3' in sys.modules:
            del sys.modules['app.domains.storage.s3']

        from app.domains.storage.s3 import S3StorageBackend

        audio_file = tmp_path / 'test.mp3'
        audio_file.write_bytes(b'fake-audio')

        with patch('boto3.client') as mock_boto_client:
            mock_s3 = MagicMock()
            mock_boto_client.return_value = mock_s3

            backend = S3StorageBackend()
            uri = await backend.upload(audio_file, job_id='job1', site_slug='site1')

        assert uri == 's3://my-bucket/audio/articles/site1/job1.mp3'
        mock_s3.upload_file.assert_called_once()


def test_s3_make_public_url():
    """Test S3StorageBackend generates correct public URL."""
    pytest.importorskip('boto3', reason='boto3 not installed')

    with patch.dict(
        os.environ,
        {
            'AWS_ACCESS_KEY_ID': 'key',
            'AWS_SECRET_ACCESS_KEY': 'secret',
            'AWS_REGION': 'us-east-1',
            'S3_BUCKET_NAME': 'my-bucket',
        },
    ):
        # Clear cached config and both storage modules
        if 'app.config' in sys.modules:
            del sys.modules['app.config']
        if 'app.domains.storage.s3' in sys.modules:
            del sys.modules['app.domains.storage.s3']
        if 'app.domains.storage.s3' in sys.modules:
            del sys.modules['app.domains.storage.s3']

        from app.domains.storage.s3 import S3StorageBackend

        backend = S3StorageBackend()

    url = backend.make_public_url('s3://my-bucket/audio/articles/site1/job1.mp3')
    assert url == 'https://my-bucket.s3.us-east-1.amazonaws.com/audio/articles/site1/job1.mp3'
