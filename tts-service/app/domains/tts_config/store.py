"""Redis-backed store for TTS generation config overrides.

Tier defaults live in EngineConfig (hardware.py). This store holds
user overrides that are merged on top at synthesis time. Config persists
across restarts (no TTL) until explicitly reset via DELETE /tts/config/generation.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_REDIS_KEY = 'tts:generation_config'
_redis = None


async def initialize(redis_url: str) -> None:
    """Connect to Redis. Called once at app startup."""
    global _redis
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(redis_url, decode_responses=True)
        logger.info('TTS config store connected to Redis')
    except Exception as exc:
        logger.warning('TTS config store Redis unavailable: %s — overrides disabled', exc)
        _redis = None


async def get_overrides() -> dict:
    """Return the user-saved overrides dict (empty if none saved)."""
    if _redis is None:
        return {}
    try:
        data = await _redis.get(_REDIS_KEY)
        return json.loads(data) if data else {}
    except Exception as exc:
        logger.warning('Failed to read TTS config overrides: %s', exc)
        return {}


async def save_overrides(overrides: dict) -> None:
    """Persist overrides to Redis (no TTL — survives restarts)."""
    if _redis is None:
        return
    try:
        await _redis.set(_REDIS_KEY, json.dumps(overrides))
    except Exception as exc:
        logger.warning('Failed to save TTS config overrides: %s', exc)


async def clear_overrides() -> None:
    """Delete all overrides, reverting to tier defaults."""
    if _redis is None:
        return
    try:
        await _redis.delete(_REDIS_KEY)
    except Exception as exc:
        logger.warning('Failed to clear TTS config overrides: %s', exc)


def get_tier_defaults() -> dict:
    """Return the current tier's generation param defaults."""
    from app.core.hardware import ENGINE_CONFIG

    cfg = ENGINE_CONFIG
    return {
        'temperature': cfg.tts_temperature,
        'repetition_penalty': cfg.tts_repetition_penalty,
        'top_k': cfg.tts_top_k,
        'top_p': cfg.tts_top_p,
        'temperature_sub_talker': cfg.tts_temperature_sub_talker,
        'top_k_sub_talker': cfg.tts_top_k_sub_talker,
        'do_sample_sub_talker': cfg.tts_do_sample_sub_talker,
        'max_new_tokens': cfg.tts_max_new_tokens,
    }


async def get_effective_config() -> tuple[dict, dict]:
    """Return (effective_kwargs, overrides) where effective = defaults | overrides."""
    defaults = get_tier_defaults()
    overrides = await get_overrides()
    effective = {**defaults, **overrides}
    return effective, overrides
