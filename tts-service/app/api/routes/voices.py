# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Voice profile management endpoints."""

from __future__ import annotations
import tempfile
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from app.api.dependencies import require_api_key
from app.domains.voices.registry import VoiceRegistry
from app.config import VOICE_SAMPLE_PATH

router = APIRouter(prefix='/voices', tags=['Voices'], dependencies=[Depends(require_api_key)])


def _get_registry() -> VoiceRegistry:
    voices_dir = Path(VOICE_SAMPLE_PATH).parent.parent
    return VoiceRegistry(voices_dir)


def _validate_and_save(source_path: Path, dest_path: Path) -> None:
    """Lazy import wrapper for validate_and_save."""
    from app.domains.voices.upload import validate_and_save

    return validate_and_save(source_path, dest_path)


@router.get(
    '',
    summary='List voice profiles',
    description='Returns all registered voice profiles. The `default` profile is always present.',
    responses={
        200: {'description': 'Available voice profiles'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
    },
)
def list_voices():
    """List all available voice profiles."""
    registry = _get_registry()
    profiles = registry.list_profiles()
    return {'profiles': profiles, 'count': len(profiles)}


@router.post(
    '/upload',
    summary='Upload a voice profile',
    description=(
        'Upload a WAV file to register a new named voice profile. '
        'The file must be a valid WAV (5–120 seconds recommended). '
        'Once uploaded, reference it in synthesis requests via `voice_profile`. '
        'The `default` profile name is reserved.'
    ),
    status_code=201,
    responses={
        201: {'description': 'Voice profile created'},
        400: {'description': 'Invalid profile name, reserved name, or non-WAV file'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        422: {'description': 'Audio file failed validation'},
    },
)
async def upload_voice(name: str, file: UploadFile = File(...)):
    """Upload a new voice reference WAV and register it as a named profile."""
    if not name.replace('-', '').replace('_', '').isalnum():
        raise HTTPException(
            status_code=400,
            detail='Profile name must be alphanumeric (hyphens/underscores allowed)',
        )
    if name == 'default':
        raise HTTPException(
            status_code=400,
            detail='Use voices/default/reference.wav to update the default voice',
        )
    if not file.filename or not file.filename.lower().endswith('.wav'):
        raise HTTPException(status_code=400, detail='Only WAV files are accepted')

    registry = _get_registry()
    dest = registry.profile_path(name)

    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        _validate_and_save(tmp_path, dest)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)

    return JSONResponse({'profile': name, 'status': 'created'}, status_code=201)


@router.delete(
    '/{name}',
    summary='Delete a voice profile',
    description=(
        'Permanently delete a named voice profile and its reference WAV. '
        'The `default` profile cannot be deleted.'
    ),
    responses={
        200: {'description': 'Voice profile deleted'},
        400: {'description': 'Cannot delete the default profile'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        404: {'description': 'No voice profile found with the given name'},
    },
)
def delete_voice(name: str):
    """Delete a named voice profile."""
    registry = _get_registry()
    try:
        registry.delete_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {'profile': name, 'status': 'deleted'}
