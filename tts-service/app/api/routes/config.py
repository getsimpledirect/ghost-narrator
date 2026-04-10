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

"""TTS generation config API routes.

GET    /tts/config/generation  — current effective config (tier defaults + Redis overrides)
PUT    /tts/config/generation  — partial update; merges into saved overrides
DELETE /tts/config/generation  — reset to tier defaults (clears Redis overrides)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import require_api_key
from app.core.hardware import ENGINE_CONFIG
from app.domains.tts_config.store import (
    clear_overrides,
    get_effective_config,
    get_overrides,
    get_tier_defaults,
    save_overrides,
)
from app.models.schemas import TTSGenerationConfigResponse, TTSGenerationConfigUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/tts/config', tags=['Config'], dependencies=[Depends(require_api_key)])


@router.get(
    '/generation',
    response_model=TTSGenerationConfigResponse,
    summary='Get generation config',
    description=(
        'Returns the current TTS generation parameters in three layers: '
        'hardware-tier defaults, any user overrides saved in Redis, and '
        'the merged effective values that will be used for the next synthesis job.'
    ),
    responses={
        200: {'description': 'Current generation config'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
    },
)
async def get_generation_config() -> TTSGenerationConfigResponse:
    """Return the effective TTS generation parameters."""
    effective, overrides = await get_effective_config()
    return TTSGenerationConfigResponse(
        tier=ENGINE_CONFIG.tier.value,
        effective=effective,
        overrides=overrides,
        defaults=get_tier_defaults(),
    )


@router.put(
    '/generation',
    response_model=TTSGenerationConfigResponse,
    summary='Update generation config',
    description=(
        'Partially update TTS generation parameters. Only fields you include are changed — '
        'omitted fields keep their current value. Changes are persisted to Redis and '
        'survive container restarts. Takes effect on the next synthesis job.'
    ),
    responses={
        200: {'description': 'Updated generation config'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
        422: {'description': 'Validation error — a parameter value is out of range'},
    },
)
async def update_generation_config(
    body: TTSGenerationConfigUpdate,
) -> TTSGenerationConfigResponse:
    """Partially update TTS generation parameters."""
    existing = await get_overrides()
    # Merge: only include explicitly-set fields from the request
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = {**existing, **patch}
    await save_overrides(updated)
    logger.info('TTS generation config updated: %s', patch)

    effective, overrides = await get_effective_config()
    return TTSGenerationConfigResponse(
        tier=ENGINE_CONFIG.tier.value,
        effective=effective,
        overrides=overrides,
        defaults=get_tier_defaults(),
    )


@router.delete(
    '/generation',
    response_model=TTSGenerationConfigResponse,
    summary='Reset generation config to defaults',
    description=(
        'Clear all saved overrides and revert to the hardware-tier defaults. '
        'This deletes the Redis-stored config — the next synthesis job will use '
        'the defaults for your detected hardware tier.'
    ),
    responses={
        200: {'description': 'Config reset to tier defaults'},
        401: {'description': 'Missing Authorization header'},
        403: {'description': 'Invalid API key'},
    },
)
async def reset_generation_config() -> TTSGenerationConfigResponse:
    """Clear all user overrides and revert to hardware-tier defaults."""
    await clear_overrides()
    logger.info('TTS generation config reset to tier defaults (%s)', ENGINE_CONFIG.tier.value)

    effective, overrides = await get_effective_config()
    return TTSGenerationConfigResponse(
        tier=ENGINE_CONFIG.tier.value,
        effective=effective,
        overrides=overrides,
        defaults=get_tier_defaults(),
    )
