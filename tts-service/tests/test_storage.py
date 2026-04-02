import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import os
import sys
import types

# Mock qwen_tts before any app imports
_mock = types.ModuleType("qwen_tts")
_mock.QwenTTS = MagicMock
sys.modules.setdefault("qwen_tts", _mock)


def test_get_storage_backend_local():
    """Test that get_storage_backend returns LocalStorage when STORAGE_BACKEND=local."""
    # Need to mock config before importing
    with patch.dict(
        os.environ,
        {
            "STORAGE_BACKEND": "local",
            "OUTPUT_DIR": "/tmp/output",
            "SERVER_EXTERNAL_IP": "localhost",
        },
    ):
        # Clear any cached imports
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        if "app.services.storage" in sys.modules:
            del sys.modules["app.services.storage"]
        if "app.services.storage.local" in sys.modules:
            del sys.modules["app.services.storage.local"]

        from app.services.storage import get_storage_backend

        backend = get_storage_backend()

    from app.services.storage.local import LocalStorage

    assert isinstance(backend, LocalStorage)


def test_get_storage_backend_unknown_raises():
    """Test that get_storage_backend raises ValueError for unknown backend."""
    with patch.dict(os.environ, {"STORAGE_BACKEND": "dropbox"}):
        # Clear any cached imports
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        if "app.services.storage" in sys.modules:
            del sys.modules["app.services.storage"]

        from app.services.storage import get_storage_backend

        with pytest.raises(ValueError, match="Unknown STORAGE_BACKEND"):
            get_storage_backend()


@pytest.mark.asyncio
async def test_local_storage_upload(tmp_path):
    """Test LocalStorage upload copies file and returns correct URI."""
    from app.services.storage.local import LocalStorage

    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake-audio")
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    backend = LocalStorage(output_dir=output_dir, server_ip="localhost", port=8020)
    uri = await backend.upload(audio_file, job_id="job123", site_slug="site1")

    assert uri == "local://job123.mp3"
    assert (output_dir / "job123.mp3").exists()


def test_local_storage_make_public_url():
    """Test LocalStorage generates correct public URL."""
    from app.services.storage.local import LocalStorage

    backend = LocalStorage(output_dir=Path("/tmp"), server_ip="1.2.3.4", port=8020)
    url = backend.make_public_url("local://job123.mp3")
    assert url == "http://1.2.3.4:8020/tts/download/job123"


@pytest.mark.asyncio
async def test_gcs_storage_upload(tmp_path):
    """Test GCSStorage upload with mocked client."""
    # Mock the config values before importing
    with patch.dict(
        os.environ,
        {"GCS_BUCKET_NAME": "my-bucket", "GCS_AUDIO_PREFIX": "audio/articles"},
    ):
        # Clear cached config
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        if "app.services.storage.gcs" in sys.modules:
            del sys.modules["app.services.storage.gcs"]

        from app.services.storage.gcs import GCSStorage

        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake-audio")

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket

        with patch.object(GCSStorage, "_get_client", return_value=mock_client):
            backend = GCSStorage()
            uri = await backend.upload(audio_file, job_id="job1", site_slug="site1")

        assert uri == "gs://my-bucket/audio/articles/site1/job1.mp3"
        mock_blob.upload_from_filename.assert_called_once()


def test_gcs_make_public_url():
    """Test GCSStorage generates correct public URL."""
    with patch.dict(os.environ, {"GCS_BUCKET_NAME": "my-bucket"}):
        # Clear cached config
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        if "app.services.storage.gcs" in sys.modules:
            del sys.modules["app.services.storage.gcs"]

        from app.services.storage.gcs import GCSStorage

        backend = GCSStorage()

    url = backend.make_public_url("gs://my-bucket/audio/articles/site1/job1.mp3")
    assert (
        url == "https://storage.googleapis.com/my-bucket/audio/articles/site1/job1.mp3"
    )


@pytest.mark.asyncio
async def test_s3_storage_upload(tmp_path):
    """Test S3Storage upload with mocked boto3."""
    with patch.dict(
        os.environ,
        {
            "AWS_ACCESS_KEY_ID": "key",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_REGION": "us-east-1",
            "S3_BUCKET_NAME": "my-bucket",
            "S3_AUDIO_PREFIX": "audio/articles",
        },
    ):
        # Clear cached config
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        if "app.services.storage.s3" in sys.modules:
            del sys.modules["app.services.storage.s3"]

        from app.services.storage.s3 import S3Storage

        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake-audio")

        with patch("app.services.storage.s3.boto3") as mock_boto:
            mock_s3 = MagicMock()
            mock_boto.client.return_value = mock_s3

            backend = S3Storage()
            uri = await backend.upload(audio_file, job_id="job1", site_slug="site1")

        assert uri == "s3://my-bucket/audio/articles/site1/job1.mp3"
        mock_s3.upload_file.assert_called_once()


def test_s3_make_public_url():
    """Test S3Storage generates correct public URL."""
    with patch.dict(
        os.environ,
        {
            "AWS_ACCESS_KEY_ID": "key",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_REGION": "us-east-1",
            "S3_BUCKET_NAME": "my-bucket",
        },
    ):
        # Clear cached config
        if "app.config" in sys.modules:
            del sys.modules["app.config"]
        if "app.services.storage.s3" in sys.modules:
            del sys.modules["app.services.storage.s3"]

        from app.services.storage.s3 import S3Storage

        backend = S3Storage()

    url = backend.make_public_url("s3://my-bucket/audio/articles/site1/job1.mp3")
    assert (
        url
        == "https://my-bucket.s3.us-east-1.amazonaws.com/audio/articles/site1/job1.mp3"
    )
