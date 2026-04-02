# Plan A: Foundation + Core Engine + Narration Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hardware auto-detection, Qwen3-TTS engine, tiered audio quality, and the information-preserving narration pipeline to ghost-narrator.

**Architecture:** A new `hardware.py` module probes GPU/VRAM at startup and produces an `EngineConfig` that drives model selection, audio settings, and narration strategy. The `tts_engine.py` is rewritten for Qwen3-TTS (replacing Fish Speech). A new `narration/` package handles LLM-based script generation with chunking, continuity context, and entity-level validation.

**Tech Stack:** Python 3.12, `qwen-tts`, PyTorch 2.4+, CUDA 12.1, FastAPI, pytest, httpx

**Spec:** `docs/superpowers/specs/2026-04-02-standalone-tts-design.md` — Sections 3, 4

**Prerequisite:** Verify before starting:
- `Qwen/Qwen3-TTS-0.6B` exists on HuggingFace Hub: `huggingface-cli info Qwen/Qwen3-TTS-0.6B`
- `Qwen/Qwen3-TTS-1.7B` exists: `huggingface-cli info Qwen/Qwen3-TTS-1.7B`
- `qwen-tts` pip package name: `pip index versions qwen-tts` (may be `qwen3-tts` or shipped via `transformers`)

---

## File Map

```
tts-service/
├── app/
│   ├── config.py                         MODIFY — new env vars
│   ├── core/
│   │   ├── hardware.py                   NEW — HardwareTier, HardwareProbe, EngineConfig, EngineSelector
│   │   └── tts_engine.py                 REWRITE — Qwen3-TTS engine
│   ├── services/
│   │   ├── audio.py                      MODIFY — tiered bitrate/samplerate/LUFS
│   │   ├── synthesis.py                  MODIFY — parallel workers on HIGH_VRAM
│   │   └── narration/
│   │       ├── __init__.py               NEW
│   │       ├── strategy.py               NEW — NarrationStrategy ABC, ChunkedStrategy, SingleShotStrategy
│   │       ├── prompt.py                 NEW — tier-specific system prompts
│   │       └── validator.py              NEW — NarrationValidator
│   └── services/tts_job.py               MODIFY — wire narration strategy
└── tests/
    ├── test_hardware.py                  NEW
    ├── test_narration_strategy.py        NEW
    └── test_narration_validator.py       NEW
```

---

## Task 1: Hardware detection module

**Files:**
- Create: `tts-service/app/core/hardware.py`
- Create: `tts-service/tests/test_hardware.py`

- [ ] **Step 1: Write failing tests**

```python
# tts-service/tests/test_hardware.py
from unittest.mock import patch, MagicMock
import pytest
import os

from app.core.hardware import HardwareTier, EngineConfig, get_engine_config


def test_cpu_only_when_cuda_unavailable():
    with patch("app.core.hardware.torch") as mock_torch:
        mock_torch.cuda.is_available.return_value = False
        config = get_engine_config()
    assert config.tier == HardwareTier.CPU_ONLY
    assert config.tts_device == "cpu"
    assert config.tts_model == "Qwen/Qwen3-TTS-0.6B"
    assert config.synthesis_workers == 4
    assert config.llm_model == "qwen3:1.7b"
    assert config.mp3_bitrate == "192k"
    assert config.sample_rate == 44100
    assert config.target_lufs == -16.0


def test_low_vram_when_6gb():
    with patch("app.core.hardware.torch") as mock_torch:
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 6 * 1024**3  # 6 GB
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.LOW_VRAM
    assert config.tts_model == "Qwen/Qwen3-TTS-0.6B"
    assert config.llm_model == "qwen3:4b-q4"
    assert config.synthesis_workers == 1


def test_mid_vram_when_12gb():
    with patch("app.core.hardware.torch") as mock_torch:
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 12 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.MID_VRAM
    assert config.tts_model == "Qwen/Qwen3-TTS-1.7B"
    assert config.llm_model == "qwen3:8b-q4"
    assert config.synthesis_workers == 1


def test_high_vram_when_24gb():
    with patch("app.core.hardware.torch") as mock_torch:
        mock_torch.cuda.is_available.return_value = True
        props = MagicMock()
        props.total_memory = 24 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = props
        config = get_engine_config()
    assert config.tier == HardwareTier.HIGH_VRAM
    assert config.tts_model == "Qwen/Qwen3-TTS-1.7B"
    assert config.llm_model == "qwen3:8b-q4"
    assert config.synthesis_workers == 2
    assert config.mp3_bitrate == "256k"
    assert config.sample_rate == 48000
    assert config.target_lufs == -14.0


def test_env_override_skips_probe():
    with patch.dict(os.environ, {"HARDWARE_TIER": "mid_vram"}):
        with patch("app.core.hardware.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False  # would be CPU_ONLY
            config = get_engine_config()
    assert config.tier == HardwareTier.MID_VRAM  # env wins


def test_invalid_env_override_falls_back_to_probe():
    with patch.dict(os.environ, {"HARDWARE_TIER": "supercomputer"}):
        with patch("app.core.hardware.torch") as mock_torch:
            mock_torch.cuda.is_available.return_value = False
            config = get_engine_config()
    assert config.tier == HardwareTier.CPU_ONLY
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd tts-service
python -m pytest tests/test_hardware.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app.core.hardware'`

- [ ] **Step 3: Create `app/core/hardware.py`**

```python
"""Hardware detection and engine configuration for tiered model selection."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import torch

logger = logging.getLogger(__name__)

_GB = 1024 ** 3


class HardwareTier(str, Enum):
    CPU_ONLY  = "cpu_only"
    LOW_VRAM  = "low_vram"
    MID_VRAM  = "mid_vram"
    HIGH_VRAM = "high_vram"


@dataclass
class EngineConfig:
    tier: HardwareTier
    tts_model: str
    tts_device: str
    tts_precision: str          # "fp32" or "fp16"
    llm_model: str
    narration_strategy: str     # "chunked" or "single_shot"
    narration_chunk_words: int  # LLM narration chunk size
    tts_chunk_words: int        # TTS synthesis chunk size
    synthesis_workers: int
    mp3_bitrate: str
    sample_rate: int
    target_lufs: float


_TIER_CONFIGS: dict[HardwareTier, EngineConfig] = {
    HardwareTier.CPU_ONLY: EngineConfig(
        tier=HardwareTier.CPU_ONLY,
        tts_model="Qwen/Qwen3-TTS-0.6B",
        tts_device="cpu",
        tts_precision="fp32",
        llm_model="qwen3:1.7b",
        narration_strategy="chunked",
        narration_chunk_words=500,
        tts_chunk_words=150,
        synthesis_workers=4,
        mp3_bitrate="192k",
        sample_rate=44100,
        target_lufs=-16.0,
    ),
    HardwareTier.LOW_VRAM: EngineConfig(
        tier=HardwareTier.LOW_VRAM,
        tts_model="Qwen/Qwen3-TTS-0.6B",
        tts_device="cuda",
        tts_precision="fp16",
        llm_model="qwen3:4b-q4",
        narration_strategy="chunked",
        narration_chunk_words=1000,
        tts_chunk_words=150,
        synthesis_workers=1,
        mp3_bitrate="192k",
        sample_rate=44100,
        target_lufs=-16.0,
    ),
    HardwareTier.MID_VRAM: EngineConfig(
        tier=HardwareTier.MID_VRAM,
        tts_model="Qwen/Qwen3-TTS-1.7B",
        tts_device="cuda",
        tts_precision="fp16",
        llm_model="qwen3:8b-q4",
        narration_strategy="single_shot",
        narration_chunk_words=2500,
        tts_chunk_words=200,
        synthesis_workers=1,
        mp3_bitrate="192k",
        sample_rate=44100,
        target_lufs=-16.0,
    ),
    HardwareTier.HIGH_VRAM: EngineConfig(
        tier=HardwareTier.HIGH_VRAM,
        tts_model="Qwen/Qwen3-TTS-1.7B",
        tts_device="cuda",
        tts_precision="fp16",
        llm_model="qwen3:8b-q4",
        narration_strategy="single_shot",
        narration_chunk_words=9999,  # no fallback on HIGH_VRAM
        tts_chunk_words=200,
        synthesis_workers=2,
        mp3_bitrate="256k",
        sample_rate=48000,
        target_lufs=-14.0,
    ),
}


def _probe_tier() -> HardwareTier:
    """Probe hardware and return the appropriate tier."""
    if not torch.cuda.is_available():
        logger.info("No CUDA device detected — using CPU_ONLY tier")
        return HardwareTier.CPU_ONLY
    vram = torch.cuda.get_device_properties(0).total_memory
    vram_gb = vram / _GB
    logger.info("CUDA device detected — %.1f GB VRAM", vram_gb)
    if vram_gb < 9:
        return HardwareTier.LOW_VRAM
    if vram_gb < 18:
        return HardwareTier.MID_VRAM
    return HardwareTier.HIGH_VRAM


def get_engine_config() -> EngineConfig:
    """Return EngineConfig for this machine. Respects HARDWARE_TIER env override."""
    override = os.environ.get("HARDWARE_TIER", "").strip().lower()
    if override:
        try:
            tier = HardwareTier(override)
            logger.info("HARDWARE_TIER override: %s", tier.value)
        except ValueError:
            logger.warning("Invalid HARDWARE_TIER=%r — probing hardware instead", override)
            tier = _probe_tier()
    else:
        tier = _probe_tier()
    return _TIER_CONFIGS[tier]


# Module-level singleton — computed once at import time
ENGINE_CONFIG: EngineConfig = get_engine_config()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd tts-service
python -m pytest tests/test_hardware.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/core/hardware.py tts-service/tests/test_hardware.py
git commit -m "feat(hardware): add HardwareTier probe and EngineConfig selector"
```

---

## Task 2: Config additions

**Files:**
- Modify: `tts-service/app/config.py`

- [ ] **Step 1: Add new env vars to `config.py`**

Add after the existing `DEVICE` line (line 48):

```python
from app.core.hardware import ENGINE_CONFIG  # noqa: E402 — import after torch

# Hardware tier (read from ENGINE_CONFIG — set at startup)
HARDWARE_TIER: Final[str] = ENGINE_CONFIG.tier.value
SELECTED_TTS_MODEL: Final[str] = ENGINE_CONFIG.tts_model
SELECTED_LLM_MODEL: Final[str] = ENGINE_CONFIG.llm_model

# Override DEVICE from engine config (replaces static env var)
DEVICE: Final[str] = ENGINE_CONFIG.tts_device

# Narration LLM endpoint (Ollama default; override for external vLLM)
LLM_BASE_URL: Final[str] = os.environ.get(
    "LLM_BASE_URL", "http://ollama:11434/v1"
)
LLM_MODEL_NAME: Final[str] = os.environ.get(
    "LLM_MODEL_NAME", ENGINE_CONFIG.llm_model
)

# Storage backend
STORAGE_BACKEND: Final[str] = os.environ.get("STORAGE_BACKEND", "local").lower()

# S3 settings (used when STORAGE_BACKEND=s3)
AWS_ACCESS_KEY_ID: Final[str] = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY: Final[str] = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION: Final[str] = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET_NAME: Final[str] = os.environ.get("S3_BUCKET_NAME", "")
S3_AUDIO_PREFIX: Final[str] = os.environ.get("S3_AUDIO_PREFIX", "audio/articles")

# GCS service account key (optional — leave blank for ADC)
GCS_SERVICE_ACCOUNT_KEY_PATH: Final[str] = os.environ.get(
    "GCS_SERVICE_ACCOUNT_KEY_PATH", ""
)

# Audio quality (from ENGINE_CONFIG — overridable via env)
MP3_BITRATE: Final[str] = os.environ.get("MP3_BITRATE", ENGINE_CONFIG.mp3_bitrate)
AUDIO_SAMPLE_RATE: Final[int] = int(
    os.environ.get("AUDIO_SAMPLE_RATE", str(ENGINE_CONFIG.sample_rate))
)
TARGET_LUFS: Final[float] = float(
    os.environ.get("TARGET_LUFS", str(ENGINE_CONFIG.target_lufs))
)

# TTS chunk words (from ENGINE_CONFIG)
MAX_CHUNK_WORDS: Final[int] = int(
    os.environ.get("MAX_CHUNK_WORDS", str(ENGINE_CONFIG.tts_chunk_words))
)
```

Remove the old static `DEVICE` and `MP3_BITRATE` definitions (they are now sourced from `ENGINE_CONFIG`).

- [ ] **Step 2: Verify import works**

```bash
cd tts-service
python -c "from app import config; print(config.HARDWARE_TIER, config.MP3_BITRATE)"
```
Expected: `cpu_only 192k` (or appropriate tier for the machine)

- [ ] **Step 3: Commit**

```bash
git add tts-service/app/config.py
git commit -m "feat(config): wire ENGINE_CONFIG into config — hardware-aware settings"
```

---

## Task 3: Qwen3-TTS engine rewrite

**Files:**
- Rewrite: `tts-service/app/core/tts_engine.py`
- Modify: `tts-service/requirements.txt`
- Modify: `tts-service/Dockerfile`

> **Note:** Verify the exact `qwen-tts` package name and import path before implementing. Run `pip index versions qwen-tts` and check HuggingFace for the correct model IDs. The interface below (synthesize_to_file, is_ready, cancel_job) must be preserved exactly.

- [ ] **Step 1: Update `requirements.txt`**

Remove `fish-speech` and any Fish Speech dependencies. Add:
```
qwen-tts>=0.1.0
soundfile>=0.12.1
torch>=2.4.0
```

Keep: `fastapi`, `uvicorn`, `httpx`, `redis`, `pydub`, `ffmpeg-python`, `google-cloud-storage`, `psutil`

- [ ] **Step 2: Rewrite `tts_engine.py`**

The public interface must remain identical to the existing engine:
- `get_tts_engine() -> TTSEngine` (singleton getter)
- `TTSEngine.initialize() -> None`
- `TTSEngine.is_ready() -> bool`
- `TTSEngine.synthesize_to_file(text: str, output_path: Path, voice_path: Path) -> None`
- `TTSEngine.cancel_job(job_id: str) -> None`

```python
"""Qwen3-TTS engine wrapper — replaces Fish Speech v1.5."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from app.config import DEVICE, SELECTED_TTS_MODEL
from app.core.exceptions import SynthesisError, TTSEngineError, VoiceSampleNotFoundError
from app.core.hardware import ENGINE_CONFIG

logger = logging.getLogger(__name__)

# ── Verify these imports match the installed qwen-tts package ─────────────────
# Run: python -c "import qwen_tts; print(qwen_tts.__version__)"
# Adjust import path if the package uses a different module name.
try:
    from qwen_tts import QwenTTS  # type: ignore[import]
except ImportError as e:
    raise ImportError(
        "qwen-tts package not found. Install with: pip install qwen-tts"
    ) from e
# ─────────────────────────────────────────────────────────────────────────────


class TTSEngine:
    """Singleton Qwen3-TTS engine with voice cloning support."""

    def __init__(self) -> None:
        self._model: Optional[QwenTTS] = None
        self._ready = False
        self._lock = threading.Lock()
        self._cancelled_jobs: set[str] = set()

    def initialize(self) -> None:
        """Load Qwen3-TTS model into memory. Called once at startup."""
        with self._lock:
            if self._ready:
                return
            logger.info(
                "Loading %s on %s (%s)",
                SELECTED_TTS_MODEL,
                DEVICE,
                ENGINE_CONFIG.tts_precision,
            )
            try:
                # Adjust constructor kwargs to match actual qwen-tts API
                self._model = QwenTTS(
                    model_name=SELECTED_TTS_MODEL,
                    device=DEVICE,
                    dtype=ENGINE_CONFIG.tts_precision,  # "fp16" or "fp32"
                )
                self._ready = True
                logger.info("Qwen3-TTS engine ready")
            except Exception as e:
                raise TTSEngineError(f"Failed to load Qwen3-TTS model: {e}") from e

    def is_ready(self) -> bool:
        return self._ready

    def synthesize_to_file(
        self,
        text: str,
        output_path: Path,
        voice_path: Path,
        job_id: str = "",
    ) -> None:
        """Synthesize text to WAV using voice_path as reference. Raises SynthesisError on failure."""
        if not self._ready or self._model is None:
            raise TTSEngineError("Engine not initialized — call initialize() first")
        if not voice_path.exists():
            raise VoiceSampleNotFoundError(f"Voice sample not found: {voice_path}")
        if job_id and job_id in self._cancelled_jobs:
            raise SynthesisError(f"Job {job_id} was cancelled")

        try:
            # Load reference voice for cloning
            # Adjust method name to match actual qwen-tts API
            self._model.load_reference(str(voice_path))

            # Synthesize — adjust method name as needed
            audio_data = self._model.synthesize(text)

            # Save to WAV — qwen-tts may return numpy array or bytes
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._model.save_wav(audio_data, str(output_path))
        except SynthesisError:
            raise
        except Exception as e:
            raise SynthesisError(f"Synthesis failed: {e}") from e
        finally:
            if job_id:
                self._cancelled_jobs.discard(job_id)

    def cancel_job(self, job_id: str) -> None:
        """Signal that the next synthesize_to_file call for this job_id should abort."""
        self._cancelled_jobs.add(job_id)


_engine: Optional[TTSEngine] = None
_engine_lock = threading.Lock()


def get_tts_engine() -> TTSEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = TTSEngine()
    return _engine
```

- [ ] **Step 3: Update `Dockerfile`**

Change base image and remove Fish Speech build steps. The Dockerfile should:
1. Use `pytorch/pytorch:2.4.1-cuda12.1-cudnn9-runtime` base
2. Remove all Fish Speech model downloads
3. Install `qwen-tts` via uv
4. Keep the existing non-root `appuser` setup

Key diff (do not copy verbatim — read existing Dockerfile first):
```dockerfile
# Remove these Fish Speech lines:
# RUN python -m tools.vqgan.inference ...
# RUN python -m tools.llama.generate ...

# Replace fish-speech in requirements with qwen-tts (already done in Task 3 Step 1)
# No other Dockerfile changes needed — uv handles the rest
```

- [ ] **Step 4: Verify engine imports cleanly**

```bash
cd tts-service
python -c "from app.core.tts_engine import get_tts_engine; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/core/tts_engine.py tts-service/requirements.txt tts-service/Dockerfile
git commit -m "feat(engine): replace Fish Speech with Qwen3-TTS engine"
```

---

## Task 4: Tiered audio quality

**Files:**
- Modify: `tts-service/app/services/audio.py`

- [ ] **Step 1: Read current `apply_final_mastering()` signature**

Find the function in `audio.py` — it currently uses hardcoded `MP3_BITRATE = "128k"` and `-16 LUFS`. Locate lines with `128k`, `loudnorm`, and `44100`.

- [ ] **Step 2: Update `apply_final_mastering()` to use config values**

Replace hardcoded audio constants with config imports. Find and update the ffmpeg loudnorm and output format calls:

```python
# At the top of audio.py, update imports:
from app.config import MP3_BITRATE, AUDIO_SAMPLE_RATE, TARGET_LUFS

# In apply_final_mastering(), replace hardcoded values:
# OLD: "-b:a", "128k"
# NEW: "-b:a", MP3_BITRATE

# OLD: f"loudnorm=I=-16:TP=-1.5:LRA=11"
# NEW: f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11"

# OLD: "-ar", "44100"
# NEW: "-ar", str(AUDIO_SAMPLE_RATE)
```

- [ ] **Step 3: Verify no regressions**

```bash
cd tts-service
python -m pytest tests/test_tts_job.py -v -k "audio"
```
Expected: same pass rate as before

- [ ] **Step 4: Commit**

```bash
git add tts-service/app/services/audio.py
git commit -m "feat(audio): tiered quality — bitrate/samplerate/LUFS from EngineConfig"
```

---

## Task 5: Parallel synthesis workers for HIGH_VRAM

**Files:**
- Modify: `tts-service/app/services/synthesis.py`

- [ ] **Step 1: Read `synthesize_chunks_auto()` in `synthesis.py`**

Locate the function that dispatches CPU parallel vs GPU sequential. It currently checks `DEVICE == "cuda"` to go sequential.

- [ ] **Step 2: Update to use `ENGINE_CONFIG.synthesis_workers`**

```python
# At top of synthesis.py, add:
from app.core.hardware import ENGINE_CONFIG

# In synthesize_chunks_auto() or equivalent dispatcher:
# OLD logic: if DEVICE == "cuda": sequential else: parallel(MAX_WORKERS)
# NEW logic:
workers = ENGINE_CONFIG.synthesis_workers
if workers == 1:
    # sequential (current GPU path)
    results = [await synthesize_chunk(chunk, ...) for chunk in chunks]
else:
    # parallel — works for both CPU (4 workers) and HIGH_VRAM (2 workers)
    semaphore = asyncio.Semaphore(workers)
    async def bounded_synthesize(chunk):
        async with semaphore:
            return await synthesize_chunk(chunk, ...)
    results = await asyncio.gather(*[bounded_synthesize(c) for c in chunks])
```

- [ ] **Step 3: Run existing synthesis tests**

```bash
cd tts-service
python -m pytest tests/test_tts_job.py -v
```
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add tts-service/app/services/synthesis.py
git commit -m "feat(synthesis): parallel workers driven by EngineConfig.synthesis_workers"
```

---

## Task 6: NarrationValidator

**Files:**
- Create: `tts-service/app/services/narration/__init__.py`
- Create: `tts-service/app/services/narration/validator.py`
- Create: `tts-service/tests/test_narration_validator.py`

- [ ] **Step 1: Write failing tests**

```python
# tts-service/tests/test_narration_validator.py
import pytest
from app.services.narration.validator import NarrationValidator, ValidationResult


def test_passes_when_number_present():
    v = NarrationValidator()
    result = v.validate(
        source="Revenue grew 47% to $2.3 billion in Q3",
        narration="Revenue grew 47% to $2.3 billion in the third quarter"
    )
    assert result.passed
    assert result.missing_entities == []


def test_fails_when_number_missing():
    v = NarrationValidator()
    result = v.validate(
        source="Revenue grew 47% to $2.3 billion",
        narration="Revenue grew significantly this year"
    )
    assert not result.passed
    assert "47%" in result.missing_entities


def test_fails_when_quoted_string_missing():
    v = NarrationValidator()
    result = v.validate(
        source='CEO said "we are on track"',
        narration="The CEO made a statement about progress"
    )
    assert not result.passed
    assert "we are on track" in result.missing_entities


def test_case_insensitive_match():
    v = NarrationValidator()
    result = v.validate(
        source="The GDP grew by 3.2%",
        narration="the gdp grew by 3.2%"
    )
    assert result.passed


def test_passes_on_empty_source():
    v = NarrationValidator()
    result = v.validate(source="", narration="some narration")
    assert result.passed


def test_build_retry_prompt_contains_missing():
    v = NarrationValidator()
    result = v.validate(
        source="Revenue grew 47%",
        narration="Revenue grew"
    )
    prompt = v.build_retry_prompt(result, original_chunk="Revenue grew 47%")
    assert "47%" in prompt
    assert "missing" in prompt.lower()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd tts-service
python -m pytest tests/test_narration_validator.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `narration/__init__.py`**

```python
"""Narration pipeline — LLM-based content-to-script conversion."""
```

- [ ] **Step 4: Create `narration/validator.py`**

```python
"""NarrationValidator — entity-level completeness check for narration output."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    passed: bool
    missing_entities: list[str] = field(default_factory=list)


class NarrationValidator:
    """Verifies that key entities from source appear in narration output.

    Extracts: numbers/percentages, quoted strings, dollar amounts.
    Fast regex matching — no LLM calls.
    """

    _NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%|\$[\d,.]+|\b\d{4}\b|\b\d+(?:\.\d+)?\s*(?:billion|million|trillion|thousand)\b", re.IGNORECASE)
    _QUOTE_RE = re.compile(r'"([^"]{4,})"')

    def _extract_entities(self, text: str) -> list[str]:
        entities = []
        entities.extend(self._NUMBER_RE.findall(text))
        entities.extend(self._QUOTE_RE.findall(text))
        return [e.strip() for e in entities if e.strip()]

    def validate(self, source: str, narration: str) -> ValidationResult:
        if not source.strip():
            return ValidationResult(passed=True)
        entities = self._extract_entities(source)
        narration_lower = narration.lower()
        missing = [e for e in entities if e.lower() not in narration_lower]
        return ValidationResult(passed=len(missing) == 0, missing_entities=missing)

    def build_retry_prompt(self, result: ValidationResult, original_chunk: str) -> str:
        missing_list = "\n".join(f"- {e}" for e in result.missing_entities)
        return (
            f"Your previous output was missing the following information:\n"
            f"{missing_list}\n\n"
            f"Please redo the narration conversion of the following text, "
            f"ensuring every item above is included:\n\n{original_chunk}"
        )
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
cd tts-service
python -m pytest tests/test_narration_validator.py -v
```
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add tts-service/app/services/narration/ tts-service/tests/test_narration_validator.py
git commit -m "feat(narration): NarrationValidator with entity-level completeness check"
```

---

## Task 7: Narration prompts

**Files:**
- Create: `tts-service/app/services/narration/prompt.py`

- [ ] **Step 1: Create `narration/prompt.py`**

```python
"""Tier-specific system prompts for narration script generation."""
from __future__ import annotations

from app.core.hardware import HardwareTier


_BASE_PROMPT = """You are converting written article content into spoken audio narration for a podcast.

RULES:
- This is a FORMAT CONVERSION, not a rewrite or summary
- DO NOT skip, condense, or omit any information
- Every fact, statistic, quote, and argument must appear in your output
- Convert markdown and HTML to natural spoken language
- Replace visual elements (bullet lists, headers) with spoken transitions
- Write in a clear, engaging podcast narrator voice
- Do not add information that is not in the source

OUTPUT: Return only the narration text. No preamble, no metadata, no explanations."""

_PACING_ADDON = """
- Add natural pacing: use sentence rhythm and paragraph breaks for breathing room
- Emphasize key terms and numbers with natural spoken stress patterns
- Use transitional phrases between sections for narrative flow"""


def get_system_prompt(tier: HardwareTier) -> str:
    """Return the system prompt appropriate for the given hardware tier."""
    if tier == HardwareTier.HIGH_VRAM:
        return _BASE_PROMPT + _PACING_ADDON
    return _BASE_PROMPT


def get_continuity_instruction(previous_tail: str) -> str:
    """Return instruction to maintain stylistic continuity with previous chunk output."""
    if not previous_tail.strip():
        return ""
    return (
        f"\n\nContinuity context — your previous output ended with:\n"
        f'"{previous_tail}"\n'
        f"Begin your output in a way that flows naturally from this."
    )
```

- [ ] **Step 2: Verify import**

```bash
cd tts-service
python -c "from app.services.narration.prompt import get_system_prompt; print(get_system_prompt.__doc__)"
```
Expected: prints docstring

- [ ] **Step 3: Commit**

```bash
git add tts-service/app/services/narration/prompt.py
git commit -m "feat(narration): tier-specific system prompts with pacing for HIGH_VRAM"
```

---

## Task 8: NarrationStrategy — ChunkedStrategy and SingleShotStrategy

**Files:**
- Create: `tts-service/app/services/narration/strategy.py`
- Create: `tts-service/tests/test_narration_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tts-service/tests/test_narration_strategy.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.narration.strategy import ChunkedStrategy, SingleShotStrategy
from app.core.hardware import HardwareTier


def _make_llm_client(response: str) -> AsyncMock:
    """Return a mock LLM client that returns `response` for any request."""
    client = AsyncMock()
    choice = MagicMock()
    choice.message.content = response
    client.chat.completions.create.return_value = MagicMock(choices=[choice])
    return client


@pytest.mark.asyncio
async def test_chunked_strategy_joins_chunks():
    client = _make_llm_client("Narrated text.")
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=10,
        tier=HardwareTier.CPU_ONLY,
    )
    # 30 words → 3 chunks of 10
    source = " ".join(["word"] * 30)
    result = await strategy.narrate(source)
    assert client.chat.completions.create.call_count == 3
    assert "Narrated text." in result


@pytest.mark.asyncio
async def test_chunked_strategy_uses_continuity_seed():
    responses = ["First chunk output ending here.", "Second chunk output."]
    client = AsyncMock()
    choice1, choice2 = MagicMock(), MagicMock()
    choice1.message.content = responses[0]
    choice2.message.content = responses[1]
    client.chat.completions.create.side_effect = [
        MagicMock(choices=[choice1]),
        MagicMock(choices=[choice2]),
    ]
    strategy = ChunkedStrategy(
        llm_client=client,
        chunk_words=5,
        tier=HardwareTier.CPU_ONLY,
    )
    source = " ".join(["word"] * 10)
    result = await strategy.narrate(source)
    # Second call should include continuity context from first response
    second_call_messages = client.chat.completions.create.call_args_list[1][1]["messages"]
    user_content = next(m["content"] for m in second_call_messages if m["role"] == "user")
    assert "ending here." in user_content


@pytest.mark.asyncio
async def test_single_shot_strategy_one_call():
    client = _make_llm_client("Full narration.")
    strategy = SingleShotStrategy(
        llm_client=client,
        fallback_threshold_words=100,
        fallback_chunk_words=50,
        tier=HardwareTier.MID_VRAM,
    )
    source = " ".join(["word"] * 50)  # under threshold
    result = await strategy.narrate(source)
    assert client.chat.completions.create.call_count == 1
    assert result == "Full narration."


@pytest.mark.asyncio
async def test_single_shot_falls_back_to_chunked_when_over_threshold():
    client = _make_llm_client("Chunk narration.")
    strategy = SingleShotStrategy(
        llm_client=client,
        fallback_threshold_words=10,
        fallback_chunk_words=5,
        tier=HardwareTier.MID_VRAM,
    )
    source = " ".join(["word"] * 30)  # over threshold
    result = await strategy.narrate(source)
    # Chunked fallback → multiple calls
    assert client.chat.completions.create.call_count > 1
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd tts-service
python -m pytest tests/test_narration_strategy.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `narration/strategy.py`**

```python
"""NarrationStrategy implementations for chunked and single-shot LLM narration."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.core.hardware import HardwareTier
from app.services.narration.prompt import get_system_prompt, get_continuity_instruction
from app.services.narration.validator import NarrationValidator

logger = logging.getLogger(__name__)

_validator = NarrationValidator()


def _split_into_chunks(text: str, chunk_words: int) -> list[str]:
    """Split text at paragraph boundaries, targeting chunk_words per chunk."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in paragraphs:
        para_words = len(para.split())
        if current_words + para_words > chunk_words and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_words = para_words
        else:
            current.append(para)
            current_words += para_words
    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text]


def _tail_sentences(text: str, n: int = 3) -> str:
    """Return last n sentences of text for continuity seeding."""
    sentences = [s.strip() for s in text.replace("\n", " ").split(". ") if s.strip()]
    return ". ".join(sentences[-n:]) + ("." if sentences else "")


async def _call_llm(client, messages: list[dict], model: str) -> str:
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()


class NarrationStrategy(ABC):
    @abstractmethod
    async def narrate(self, text: str) -> str:
        ...


class ChunkedStrategy(NarrationStrategy):
    def __init__(self, llm_client, chunk_words: int, tier: HardwareTier, model: str = "") -> None:
        self._client = llm_client
        self._chunk_words = chunk_words
        self._tier = tier
        self._model = model
        self._system_prompt = get_system_prompt(tier)

    async def _narrate_chunk(self, chunk: str, previous_tail: str) -> str:
        continuity = get_continuity_instruction(previous_tail)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": chunk + continuity},
        ]
        result = await _call_llm(self._client, messages, self._model)
        validation = _validator.validate(chunk, result)
        if not validation.passed:
            logger.warning("Validation failed for chunk — retrying. Missing: %s", validation.missing_entities)
            retry_prompt = _validator.build_retry_prompt(validation, chunk)
            messages.append({"role": "assistant", "content": result})
            messages.append({"role": "user", "content": retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
        return result

    async def narrate(self, text: str) -> str:
        chunks = _split_into_chunks(text, self._chunk_words)
        outputs: list[str] = []
        previous_tail = ""
        for chunk in chunks:
            output = await self._narrate_chunk(chunk, previous_tail)
            outputs.append(output)
            previous_tail = _tail_sentences(output)
        return "\n\n".join(outputs)


class SingleShotStrategy(NarrationStrategy):
    def __init__(
        self,
        llm_client,
        fallback_threshold_words: int,
        fallback_chunk_words: int,
        tier: HardwareTier,
        model: str = "",
    ) -> None:
        self._client = llm_client
        self._fallback_threshold = fallback_threshold_words
        self._fallback_chunk_words = fallback_chunk_words
        self._tier = tier
        self._model = model
        self._system_prompt = get_system_prompt(tier)

    async def narrate(self, text: str) -> str:
        word_count = len(text.split())
        if word_count > self._fallback_threshold:
            logger.info("Content (%d words) exceeds threshold — using chunked fallback", word_count)
            fallback = ChunkedStrategy(
                llm_client=self._client,
                chunk_words=self._fallback_chunk_words,
                tier=self._tier,
                model=self._model,
            )
            return await fallback.narrate(text)
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": text},
        ]
        result = await _call_llm(self._client, messages, self._model)
        validation = _validator.validate(text, result)
        if not validation.passed:
            logger.warning("Validation failed — retrying. Missing: %s", validation.missing_entities)
            retry_prompt = _validator.build_retry_prompt(validation, text)
            messages.append({"role": "assistant", "content": result})
            messages.append({"role": "user", "content": retry_prompt})
            result = await _call_llm(self._client, messages, self._model)
        return result
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd tts-service
python -m pytest tests/test_narration_strategy.py -v
```
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/services/narration/strategy.py tts-service/tests/test_narration_strategy.py
git commit -m "feat(narration): ChunkedStrategy and SingleShotStrategy with validator and continuity"
```

---

## Task 9: Wire narration strategy into tts_job.py

**Files:**
- Modify: `tts-service/app/services/tts_job.py`
- Modify: `tts-service/app/config.py`

- [ ] **Step 1: Add LLM client factory to `config.py`**

```python
# Add at the bottom of config.py:
from openai import AsyncOpenAI  # Ollama is OpenAI-compatible

def get_llm_client() -> AsyncOpenAI:
    """Return async OpenAI-compatible client pointed at Ollama (or override URL)."""
    return AsyncOpenAI(base_url=LLM_BASE_URL, api_key="ollama")
```

- [ ] **Step 2: Add `get_narration_strategy()` factory to `config.py`**

```python
from app.core.hardware import ENGINE_CONFIG, HardwareTier
from app.services.narration.strategy import ChunkedStrategy, SingleShotStrategy

def get_narration_strategy():
    """Return the NarrationStrategy for the current hardware tier."""
    client = get_llm_client()
    tier = ENGINE_CONFIG.tier
    if ENGINE_CONFIG.narration_strategy == "chunked":
        return ChunkedStrategy(
            llm_client=client,
            chunk_words=ENGINE_CONFIG.narration_chunk_words,
            tier=tier,
            model=LLM_MODEL_NAME,
        )
    return SingleShotStrategy(
        llm_client=client,
        fallback_threshold_words=3000 if tier == HardwareTier.MID_VRAM else 999999,
        fallback_chunk_words=ENGINE_CONFIG.narration_chunk_words,
        tier=tier,
        model=LLM_MODEL_NAME,
    )
```

- [ ] **Step 3: Locate narration call in `tts_job.py`**

Find where `tts_job.py` calls the external vLLM for narration rewriting. It currently uses `httpx` or similar to POST to `VLLM_BASE_URL`. Replace with `get_narration_strategy().narrate(text)`.

The relevant function is likely called something like `_rewrite_as_narration(text)` or similar. Replace its body:

```python
from app.config import get_narration_strategy

async def _rewrite_as_narration(text: str) -> str:
    """Convert article text to narration script using the tier-selected strategy."""
    strategy = get_narration_strategy()
    return await strategy.narrate(text)
```

- [ ] **Step 4: Run full test suite**

```bash
cd tts-service
python -m pytest tests/ -v
```
Expected: all previously passing tests still pass; new tests pass

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/services/tts_job.py tts-service/app/config.py
git commit -m "feat(job): wire NarrationStrategy into tts_job pipeline"
```

---

## Task 10: Final Plan A verification

- [ ] **Step 1: Run full test suite**

```bash
cd tts-service
python -m pytest tests/ -v --tb=short
```
Expected: all tests pass, no skips

- [ ] **Step 2: Verify hardware config prints correctly**

```bash
cd tts-service
python -c "
from app.core.hardware import ENGINE_CONFIG
print('Tier:', ENGINE_CONFIG.tier.value)
print('TTS model:', ENGINE_CONFIG.tts_model)
print('LLM model:', ENGINE_CONFIG.llm_model)
print('Strategy:', ENGINE_CONFIG.narration_strategy)
print('Bitrate:', ENGINE_CONFIG.mp3_bitrate)
"
```
Expected: prints coherent config matching the machine's hardware

- [ ] **Step 3: Commit any remaining changes**

```bash
git add -p  # review any unstaged changes
git commit -m "chore(plan-a): Plan A complete — hardware detection, Qwen3-TTS, narration pipeline"
```
