"""Voice profile management endpoints."""

from __future__ import annotations
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from app.services.voices.registry import VoiceRegistry
from app.services.voices.upload import validate_and_save
from app.config import VOICE_SAMPLE_PATH

router = APIRouter(prefix="/voices", tags=["voices"])


def _get_registry() -> VoiceRegistry:
    voices_dir = Path(VOICE_SAMPLE_PATH).parent.parent
    return VoiceRegistry(voices_dir)


@router.get("")
def list_voices():
    """List all available voice profiles."""
    registry = _get_registry()
    profiles = registry.list_profiles()
    return {"profiles": profiles, "count": len(profiles)}


@router.post("/upload")
async def upload_voice(name: str, file: UploadFile = File(...)):
    """Upload a new voice reference WAV and register it as a named profile."""
    if not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(
            status_code=400,
            detail="Profile name must be alphanumeric (hyphens/underscores allowed)",
        )
    if name == "default":
        raise HTTPException(
            status_code=400,
            detail="Use voices/default/reference.wav to update the default voice",
        )
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="Only WAV files are accepted")

    registry = _get_registry()
    dest = registry._profiles_dir / f"{name}.wav"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        validate_and_save(tmp_path, dest)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    return JSONResponse({"profile": name, "status": "created"}, status_code=201)


@router.delete("/{name}")
def delete_voice(name: str):
    """Delete a named voice profile."""
    registry = _get_registry()
    try:
        registry.delete_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"profile": name, "status": "deleted"}
