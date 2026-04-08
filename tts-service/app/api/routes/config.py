"""TTS generation config API routes.

GET    /tts/config/generation  — current effective config (tier defaults + Redis overrides)
PUT    /tts/config/generation  — partial update; merges into saved overrides
DELETE /tts/config/generation  — reset to tier defaults (clears Redis overrides)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

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

router = APIRouter(prefix='/tts/config', tags=['Config'])


@router.get(
    '/generation',
    response_model=TTSGenerationConfigResponse,
    summary='Get TTS generation config',
)
async def get_generation_config() -> TTSGenerationConfigResponse:
    """Return the effective TTS generation parameters.

    Shows tier defaults, any user overrides saved in Redis, and the
    merged effective values that will be used for the next synthesis job.
    """
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
    summary='Update TTS generation config',
)
async def update_generation_config(
    body: TTSGenerationConfigUpdate,
) -> TTSGenerationConfigResponse:
    """Partially update TTS generation parameters.

    Only supplied fields are updated; omitted fields keep their current
    override value (or fall through to tier defaults if not previously set).
    Changes are persisted to Redis and survive container restarts.
    """
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
    summary='Reset TTS generation config to tier defaults',
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
