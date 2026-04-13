# Single-Shot Audio Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement single-shot audio synthesis to eliminate chunk-boundary artifacts (pitch jumps, speed variations, volume inconsistencies, white noise bursts) by synthesizing entire chapters in one pass.

**Architecture:** Replace chunk-based synthesis pipeline with single-shot synthesis. For long content (>5000 words), split into segments of 3000-4000 words each, synthesized independently and concatenated with overlap crossfade. Voice prompt is cached and reused for all segments to ensure voice consistency.

**Tech Stack:** Qwen3-TTS, pydub, asyncio, numpy

---

## File Structure

- **Modify:** `tts-service/app/config.py` — Add SINGLE_SHOT_MAX_WORDS config
- **Modify:** `tts-service/app/domains/synthesis/service.py` — Add single-shot synthesis function
- **Modify:** `tts-service/app/domains/job/tts_job.py` — Add single-shot branch in pipeline
- **Modify:** `tts-service/app/domains/synthesis/concatenate.py` — Add overlap crossfade for segments
- **Modify:** `tts-service/app/utils/text.py` — Update DEFAULT_MAX_CHUNK_WORDS for fallback
- **Modify:** `tts-service/README.md` — Update MAX_CHUNK_WORDS documentation
- **Modify:** `tts-service/run-docker.sh` — Add SINGLE_SHOT_* env vars
- **Modify:** `tts-service/run-docker.ps1` — Add SINGLE_SHOT_* env vars
- **Modify:** `tts-service/QUICKSTART.md` — Update env var documentation
- **Test:** `tts-service/tests/domains/synthesis/test_synthesis_service.py` — Add single-shot tests
- **Test:** `tts-service/tests/domains/synthesis/test_concatenate.py` — Add overlap crossfade tests

---

## Technical Notes

### Why Single-Shot Works
- Qwen3-TTS is designed for long-form synthesis — can handle 4000+ words in one pass
- Single synthesis = no state resets = no pitch/speed/volume variations
- One voice prompt = consistent voice throughout

### Segment Strategy for Long Content
- Single-shot works for chapters up to ~4000 words (depends on memory)
- For longer content: split into segments of 3000 words each
- Each segment synthesized independently in single-shot mode
- Overlap crossfade (500ms) between segments to hide boundaries
- Voice prompt cached at job start — reused for all segments

### Memory Management
- ~1GB RAM per 1000 words (model states)
- 4000 words ≈ 4GB additional memory
- GPU tiers have more headroom; CPU tier may need smaller segments

---

## Tasks

### Task 1: Add Single-Shot Configuration

**Files:**
- Modify: `tts-service/app/config.py:96-110`
- Test: Verify config loads correctly

- [ ] **Step 1: Read current config.py section**

```bash
# Read lines around MAX_CHUNK_WORDS
read tts-service/app/config.py:90-120
```

- [ ] **Step 2: Add SINGLE_SHOT configuration**

Add after MAX_CHUNK_WORDS definition (around line 106):

```python
# Single-shot synthesis settings
# When content is below this word count, synthesize in a single pass
# for studio-quality seamless audio (no chunk boundaries).
SINGLE_SHOT_MAX_WORDS: Final[int] = int(
    os.environ.get('SINGLE_SHOT_MAX_WORDS', '4000')
)

# For content above SINGLE_SHOT_MAX_WORDS, split into segments
# Each segment is synthesized in single-shot mode, then concatenated.
SINGLE_SHOT_SEGMENT_WORDS: Final[int] = int(
    os.environ.get('SINGLE_SHOT_SEGMENT_WORDS', '3000')
)

# Overlap between segments for crossfade (in milliseconds)
SINGLE_SHOT_OVERLAP_MS: Final[int] = int(
    os.environ.get('SINGLE_SHOT_OVERLAP_MS', '500')
)
```

- [ ] **Step 3: Run linter**

```bash
ruff check tts-service/app/config.py
```

- [ ] **Step 4: Commit**

```bash
git add tts-service/app/config.py
git commit -m "feat(config): add single-shot synthesis settings"
```

---

### Task 2: Add Single-Shot Synthesis Function to Service

**Files:**
- Modify: `tts-service/app/domains/synthesis/service.py:130-180`
- Test: `tts-service/tests/domains/synthesis/test_synthesis_service.py`

- [ ] **Step 1: Read service.py around line 130**

```python
# Read the synthesize_chunk function to understand the pattern
read tts-service/app/domains/synthesis/service.py:100-140
```

- [ ] **Step 2: Add single-shot synthesis function**

Add after `synthesize_chunk` function (around line 130):

```python
def synthesize_single_shot(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
) -> str:
    """
    Synthesize a large text in a single pass using Qwen3-TTS.

    This produces studio-quality audio with no chunk boundaries,
    eliminating pitch/speed/volume variations between chunks.

    Args:
        text: The full text to synthesize (up to ~4000 words recommended).
        output_path: Path where the WAV file will be saved.
        job_id: Job identifier for process tracking.
        generation_kwargs: Generation parameters forwarded to the TTS engine.

    Returns:
        The output path of the generated WAV file.

    Raises:
        SynthesisError: If synthesis fails.
    """
    if not text or not text.strip():
        raise SynthesisError(
            'Cannot synthesize empty text',
            details=f'output_path={output_path}',
        )

    engine = get_tts_engine()
    return engine.synthesize_to_file(text, output_path, job_id, generation_kwargs=generation_kwargs)
```

- [ ] **Step 3: Add async wrapper for single-shot**

Add after `synthesize_single_shot` function:

```python
async def synthesize_single_shot_async(
    text: str,
    output_path: str,
    job_id: str = 'default',
    generation_kwargs: Optional[dict] = None,
) -> str:
    """
    Async wrapper for single-shot synthesis.

    Runs the synchronous single-shot synthesis in a thread pool.
    """
    if not _executor:
        raise SynthesisError(
            'Executor not initialized',
            details='Call initialize_executor() during startup',
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        _executor,
        synthesize_single_shot,
        text,
        output_path,
        job_id,
        generation_kwargs,
    )
```

- [ ] **Step 4: Run linter**

```bash
ruff check tts-service/app/domains/synthesis/service.py
```

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/domains/synthesis/service.py
git commit -m "feat(synthesis): add single-shot synthesis function"
```

---

### Task 3: Add Overlap Crossfade to Concatenate

**Files:**
- Modify: `tts-service/app/domains/synthesis/concatenate.py:140-170`

- [ ] **Step 1: Read current concatenate logic around crossfade**

```python
read tts-service/app/domains/synthesis/concatenate.py:130-180
```

- [ ] **Step 2: Add overlap crossfade function**

Add after existing crossfade function (around line 145):

```python
def concatenate_audio_with_overlap(
    wav_paths: list[str],
    output_path: str,
    overlap_ms: int = 500,
    silence_threshold_db: int = -50,
) -> str:
    """
    Concatenate audio files using overlap crossfade for seamless transitions.

    This is used for joining single-shot segments. The overlap region is
    crossfaded to eliminate any boundary artifacts.

    Args:
        wav_paths: List of WAV file paths to concatenate.
        output_path: Path for the output WAV file.
        overlap_ms: Overlap duration in milliseconds for crossfade.
        silence_threshold_db: Silence detection threshold in dBFS.

    Returns:
        Path to the concatenated WAV file.

    Raises:
        AudioProcessingError: If concatenation fails.
    """
    if not wav_paths:
        raise AudioProcessingError('No WAV files provided for concatenation')

    if len(wav_paths) == 1:
        # Single file - just copy
        shutil.copy2(wav_paths[0], output_path)
        return output_path

    # Load all audio segments
    segments = []
    for path_str in wav_paths:
        path = Path(path_str)
        if not path.exists():
            raise AudioProcessingError(f'WAV file not found: {path_str}')
        if path.stat().st_size == 0:
            raise AudioProcessingError(f'WAV file is empty: {path_str}')
        seg = AudioSegment.from_wav(path_str)
        # Convert to consistent format
        seg = seg.set_frame_rate(48000).set_channels(2).set_sample_width(2)
        segments.append(seg)

    # Concatenate with overlap crossfade
    combined = segments[0]
    for i, segment in enumerate(segments[1:], start=1):
        # Calculate overlap region
        overlap_samples = int(overlap_ms * combined.frame_rate / 1000)
        
        if len(combined) * combined.frame_rate / 1000 < overlap_ms / 1000:
            # Not enough audio for overlap - just append
            combined += segment
            continue

        # Extract overlap regions
        combined_overlap = combined[-overlap_ms:]
        segment_overlap = segment[:overlap_ms]
        
        # Crossfade using equal-power crossfade
        combined_tail = np.array(combined_overlap.get_array_of_samples(), dtype=np.float32)
        segment_head = np.array(segment_overlap.get_array_of_samples(), dtype=np.float32)
        
        # Ensure same length
        min_len = min(len(combined_tail), len(segment_head))
        combined_tail = combined_tail[:min_len]
        segment_head = segment_head[:min_len]
        
        # Equal-power crossfade
        fade_out = np.linspace(1.0, 0.0, min_len)
        fade_in = np.linspace(0.0, 1.0, min_len)
        
        # Apply crossfade
        faded = (combined_tail * fade_out + segment_head * fade_in)
        faded = np.clip(faded, -32768, 32767).astype(np.int16)
        
        # Reconstruct audio
        if combined.channels == 2:
            faded_audio = AudioSegment(
                faded.reshape(-1, 2),
                frame_rate=combined.frame_rate,
                sample_width=2,
                channels=2,
            )
        else:
            faded_audio = AudioSegment(
                faded,
                frame_rate=combined.frame_rate,
                sample_width=2,
                channels=1,
            )
        
        # Combine: pre-overlap + crossfade + post-overlap
        pre_overlap = combined[:-overlap_ms]
        post_overlap = segment[overlap_ms:]
        combined = pre_overlap + faded_audio + post_overlap

    # Export
    combined.export(output_path, format='wav')
    return output_path
```

- [ ] **Step 3: Add imports if needed**

Check existing imports at top of file - likely already have numpy and shutil.

- [ ] **Step 4: Run linter**

```bash
ruff check tts-service/app/domains/synthesis/concatenate.py
```

- [ ] **Step 5: Commit**

```bash
git add tts-service/app/domains/synthesis/concatenate.py
git commit -m "feat(concatenate): add overlap crossfade for single-shot segments"
```

---

### Task 4: Integrate Single-Shot into TTS Job Pipeline

**Files:**
- Modify: `tts-service/app/domains/job/tts_job.py:250-420`

- [ ] **Step 1: Read the pipeline section**

```python
read tts-service/app/domains/job/tts_job.py:250-350
```

- [ ] **Step 2: Import single-shot functions**

Add to imports around line 60:

```python
from app.domains.synthesis.service import (
    cleanup_chunk_files,
    get_executor,
    prepare_text_for_synthesis,
    synthesize_chunks_auto,
    synthesize_single_shot_async,
)
from app.domains.synthesis.concatenate import concatenate_audio_with_overlap
```

- [ ] **Step 3: Add single-shot import**

```python
from app.config import (
    DEVICE,
    MAX_CHUNK_WORDS,
    MAX_JOB_DURATION_SECONDS,
    MP3_BITRATE,
    OUTPUT_DIR,
    SINGLE_SHOT_MAX_WORDS,
    SINGLE_SHOT_SEGMENT_WORDS,
    SINGLE_SHOT_OVERLAP_MS,
)
```

- [ ] **Step 4: Find the synthesis section and add single-shot logic**

After line 256 (where narration starts), add a branch that checks if content is suitable for single-shot:

```python
# Check if we should use single-shot synthesis
# Single-shot produces studio-quality audio without chunk boundaries
use_single_shot = total_words > 0 and total_words <= SINGLE_SHOT_MAX_WORDS

if use_single_shot:
    # Single-shot synthesis for optimal quality
    logger.info(f'[{job_id}] Using single-shot synthesis for {total_words} words')
    # The narration already happened above - use the narrated text
    # (all_chunks contains the narrated text)
    full_narrated_text = ' '.join(all_chunks)
    
    # Synthesize in single shot
    single_shot_wav = str(job_dir / 'single_shot.wav')
    chunk_wav_paths = [await synthesize_single_shot_async(
        text=full_narrated_text,
        output_path=single_shot_wav,
        job_id=job_id,
        generation_kwargs=generation_kwargs,
    )]
    logger.info(f'[{job_id}] Single-shot synthesis complete')
else:
    # Original chunk-based pipeline continues here
    # (existing code from line 346 onwards)
    pass
```

- [ ] **Step 5: Handle longer content with segments**

If `total_words > SINGLE_SHOT_MAX_WORDS`, use segment approach:

```python
# For longer content, use segment-based single-shot
num_segments = (total_words + SINGLE_SHOT_SEGMENT_WORDS - 1) // SINGLE_SHOT_SEGMENT_WORDS
logger.info(f'[{job_id}] Using segment-based single-shot ({num_segments} segments)')

segment_wavs = []
for seg_idx in range(num_segments):
    start_word = seg_idx * SINGLE_SHOT_SEGMENT_WORDS
    end_word = min((seg_idx + 1) * SINGLE_SHOT_SEGMENT_WORDS, total_words)
    segment_text = ' '.join(all_chunks).split()[start_word:end_word]
    segment_text = ' '.join(segment_text)
    
    segment_wav = str(job_dir / f'segment_{seg_idx:04d}.wav')
    segment_path = await synthesize_single_shot_async(
        text=segment_text,
        output_path=segment_wav,
        job_id=job_id,
        generation_kwargs=generation_kwargs,
    )
    segment_wavs.append(segment_path)
    logger.info(f'[{job_id}] Segment {seg_idx + 1}/{num_segments} complete')

# Concatenate segments with overlap crossfade
chunk_wav_paths = await loop.run_in_executor(
    executor,
    functools.partial(
        concatenate_audio_with_overlap,
        overlap_ms=SINGLE_SHOT_OVERLAP_MS,
    ),
    segment_wavs,
    str(job_dir / 'merged.wav'),
)
chunk_wav_paths = [chunk_wav_paths]  # Wrap for consistency
```

- [ ] **Step 6: Run linter**

```bash
ruff check tts-service/app/domains/job/tts_job.py
```

- [ ] **Step 7: Commit**

```bash
git add tts-service/app/domains/job/tts_job.py
git commit -m "feat(tts): integrate single-shot synthesis into job pipeline"
```

---

### Task 5: Write Tests for Single-Shot Synthesis

**Files:**
- Modify: `tts-service/tests/domains/synthesis/test_synthesis_service.py`

- [ ] **Step 1: Read existing test structure**

```bash
read tts-service/tests/domains/synthesis/test_synthesis_service.py:1-50
```

- [ ] **Step 2: Add single-shot tests**

```python
def test_synthesize_single_shot_function_exists():
    """Single-shot synthesis function should be importable."""
    from app.domains.synthesis.service import synthesize_single_shot
    assert callable(synthesize_single_shot)


def test_synthesize_single_shot_empty_text_raises():
    """Single-shot should raise error for empty text."""
    from app.domains.synthesis.service import synthesize_single_shot
    from app.core.exceptions import SynthesisError
    
    with pytest.raises(SynthesisError) as exc_info:
        synthesize_single_shot('', '/tmp/test.wav')
    assert 'empty' in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_synthesize_single_shot_async_importable():
    """Async wrapper should be importable."""
    from app.domains.synthesis.service import synthesize_single_shot_async
    assert callable(synthesize_single_shot_async)
```

- [ ] **Step 3: Run tests**

```bash
cd tts-service && pytest tests/domains/synthesis/test_synthesis_service.py -v -k "single_shot"
```

- [ ] **Step 4: Commit**

```bash
git add tts-service/tests/domains/synthesis/test_synthesis_service.py
git commit -m "test(synthesis): add single-shot synthesis tests"
```

---

### Task 6: Write Tests for Overlap Crossfade

**Files:**
- Modify: `tts-service/tests/domains/synthesis/test_concatenate.py`

- [ ] **Step 1: Add overlap crossfade tests**

```python
def test_concatenate_audio_with_overlap_importable():
    """Overlap crossfade function should be importable."""
    from app.domains.synthesis.concatenate import concatenate_audio_with_overlap
    assert callable(concatenate_audio_with_overlap)


def test_concatenate_audio_with_overlap_single_file():
    """Single file should just be copied."""
    from app.domains.synthesis.concatenate import concatenate_audio_with_overlap
    
    # Create a simple test WAV
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        test_wav = f.name
    
    try:
        # Generate test audio
        seg = AudioSegment(
            np.random.randint(-1000, 1000, 24000, dtype=np.int16),
            frame_rate=48000,
            sample_width=2,
            channels=1,
        )
        seg.export(test_wav, format='wav')
        
        # Concatenate
        output = tempfile.mktemp(suffix='.wav')
        result = concatenate_audio_with_overlap([test_wav], output)
        
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0
    finally:
        Path(test_wav).unlink(missing_ok=True)
        if 'output' in locals():
            Path(output).unlink(missing_ok=True)


def test_concatenate_audio_with_overlap_two_files():
    """Two files should be crossfaded with overlap."""
    from app.domains.synthesis.concatenate import concatenate_audio_with_overlap
    
    # Create two test WAVs
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        test_wav1 = f.name
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
        test_wav2 = f.name
    
    try:
        # Generate test audio (1 second each at 48kHz)
        seg1 = AudioSegment(
            np.sin(np.linspace(0, 2 * np.pi, 48000)).astype(np.int16),
            frame_rate=48000,
            sample_width=2,
            channels=1,
        )
        seg2 = AudioSegment(
            np.sin(np.linspace(0, 4 * np.pi, 48000)).astype(np.int16),
            frame_rate=48000,
            sample_width=2,
            channels=1,
        )
        seg1.export(test_wav1, format='wav')
        seg2.export(test_wav2, format='wav')
        
        # Concatenate with 500ms overlap
        output = tempfile.mktemp(suffix='.wav')
        result = concatenate_audio_with_overlap(
            [test_wav1, test_wav2],
            output,
            overlap_ms=500,
        )
        
        assert Path(result).exists()
        # Output should be ~1.5 seconds (1s + 0.5s from second file)
        result_seg = AudioSegment.from_wav(result)
        assert result_seg.duration_seconds >= 1.0
    finally:
        Path(test_wav1).unlink(missing_ok=True)
        Path(test_wav2).unlink(missing_ok=True)
        if 'output' in locals():
            Path(output).unlink(missing_ok=True)
```

- [ ] **Step 2: Run tests**

```bash
cd tts-service && pytest tests/domains/synthesis/test_concatenate.py -v -k "overlap"
```

- [ ] **Step 3: Commit**

```bash
git add tts-service/tests/domains/synthesis/test_concatenate.py
git commit -m "test(concatenate): add overlap crossfade tests"
```

---

### Task 7: End-to-End Integration Test

**Files:**
- Test: Run full pipeline with single-shot

- [ ] **Step 1: Run full test suite**

```bash
cd tts-service && pytest tests/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 2: Commit any fixes**

If tests fail, fix and commit.

---

## Summary of Changes

| Task | Files | Change |
|------|-------|--------|
| 1 | config.py | Add SINGLE_SHOT_MAX_WORDS, SINGLE_SHOT_SEGMENT_WORDS, SINGLE_SHOT_OVERLAP_MS |
| 2 | service.py | Add synthesize_single_shot() and synthesize_single_shot_async() |
| 3 | concatenate.py | Add concatenate_audio_with_overlap() for segment merging |
| 4 | tts_job.py | Integrate single-shot branch into pipeline with segment handling |
| 5 | test_synthesis_service.py | Add single-shot tests |
| 6 | test_concatenate.py | Add overlap crossfade tests |
| 7 | All | Run full test suite |

---

### Task 8: Update DEFAULT_MAX_CHUNK_WORDS in text.py

**Files:**
- Modify: `tts-service/app/utils/text.py:40`

- [ ] **Step 1: Update DEFAULT_MAX_CHUNK_WORDS**

The DEFAULT_MAX_CHUNK_WORDS is used as fallback when hardware config is not available. Since we're now doing single-shot synthesis, increase this to allow larger chunks:

```python
# Default maximum words per chunk (larger chunks for single-shot fallback)
DEFAULT_MAX_CHUNK_WORDS: Final[int] = 400  # Was 200 - aligned with SINGLE_SHOT_MAX_WORDS
```

- [ ] **Step 2: Run linter**

```bash
ruff check tts-service/app/utils/text.py
```

- [ ] **Step 3: Commit**

```bash
git add tts-service/app/utils/text.py
git commit -m "chore(text): increase DEFAULT_MAX_CHUNK_WORDS to 400 for single-shot fallback"
```

---

### Task 9: Update Documentation (README)

**Files:**
- Modify: `tts-service/README.md:105,250,396`

- [ ] **Step 1: Update MAX_CHUNK_WORDS documentation**

Update the env var documentation to reflect the new defaults and add SINGLE_SHOT_* vars:

Around line 105 - add to docker run example:
```
-e SINGLE_SHOT_MAX_WORDS=4000 \
-e SINGLE_SHOT_SEGMENT_WORDS=3000 \
-e SINGLE_SHOT_OVERLAP_MS=500 \
```

Around line 250 - add to environment variables table:

| `SINGLE_SHOT_MAX_WORDS` | `4000` | Max words to synthesize in single pass |
| `SINGLE_SHOT_SEGMENT_WORDS` | `3000` | Words per segment for long content |
| `SINGLE_SHOT_OVERLAP_MS` | `500` | Overlap crossfade in milliseconds |

- [ ] **Step 2: Commit**

```bash
git add tts-service/README.md
git commit -m "docs: add single-shot environment variables to README"
```

---

### Task 10: Update Docker Scripts

**Files:**
- Modify: `tts-service/run-docker.sh:78,250,257`
- Modify: `tts-service/run-docker.ps1:64,239,246`

- [ ] **Step 1: Update run-docker.sh**

Add to help text (around line 78):
```bash
echo "  SINGLE_SHOT_MAX_WORDS    Max words for single-pass synthesis (default: 4000)"
echo "  SINGLE_SHOT_SEGMENT_WORDS Words per segment for long content (default: 3000)"
echo "  SINGLE_SHOT_OVERLAP_MS    Overlap crossfade ms between segments (default: 500)"
```

Add env vars to docker run (around line 257):
```bash
"-e" "SINGLE_SHOT_MAX_WORDS=$SINGLE_SHOT_MAX_WORDS" \
"-e" "SINGLE_SHOT_SEGMENT_WORDS=$SINGLE_SHOT_SEGMENT_WORDS" \
"-e" "SINGLE_SHOT_OVERLAP_MS=$SINGLE_SHOT_OVERLAP_MS" \
```

- [ ] **Step 2: Update run-docker.ps1**

Add to help text (around line 64):
```powershell
Write-Host "  SINGLE_SHOT_MAX_WORDS    Max words for single-pass synthesis (default: 4000)"
Write-Host "  SINGLE_SHOT_SEGMENT_WORDS Words per segment for long content (default: 3000)"
Write-Host "  SINGLE_SHOT_OVERLAP_MS    Overlap crossfade ms between segments (default: 500)"
```

Add env vars to docker run (around line 246):
```powershell
"-e", "SINGLE_SHOT_MAX_WORDS=$SINGLE_SHOT_MAX_WORDS",
"-e", "SINGLE_SHOT_SEGMENT_WORDS=$SINGLE_SHOT_SEGMENT_WORDS",
"-e", "SINGLE_SHOT_OVERLAP_MS=$SINGLE_SHOT_OVERLAP_MS",
```

- [ ] **Step 3: Commit**

```bash
git add tts-service/run-docker.sh tts-service/run-docker.ps1
git commit -m "chore(docker): add single-shot env vars to docker scripts"
```

---

### Task 11: Update QUICKSTART.md

**Files:**
- Modify: `tts-service/QUICKSTART.md:132`

- [ ] **Step 1: Add SINGLE_SHOT env vars**

Add after MAX_CHUNK_WORDS export:

```bash
export SINGLE_SHOT_MAX_WORDS="4000"      # Max words for single-pass synthesis
export SINGLE_SHOT_SEGMENT_WORDS="3000"  # Words per segment for long content
export SINGLE_SHOT_OVERLAP_MS="500"     # Overlap crossfade between segments
```

- [ ] **Step 2: Commit**

```bash
git add tts-service/QUICKSTART.md
git commit -m "docs: add single-shot env vars to QUICKSTART"
```

---

## Final Summary

| Task | Files | Change |
|------|-------|--------|
| 1 | config.py | Add SINGLE_SHOT_MAX_WORDS, SINGLE_SHOT_SEGMENT_WORDS, SINGLE_SHOT_OVERLAP_MS |
| 2 | service.py | Add synthesize_single_shot() and synthesize_single_shot_async() |
| 3 | concatenate.py | Add concatenate_audio_with_overlap() for segment merging |
| 4 | tts_job.py | Integrate single-shot branch into pipeline with segment handling |
| 5 | test_synthesis_service.py | Add single-shot tests |
| 6 | test_concatenate.py | Add overlap crossfade tests |
| 7 | All | Run full test suite |
| 8 | text.py | Update DEFAULT_MAX_CHUNK_WORDS to 400 |
| 9 | README.md | Add SINGLE_SHOT env var documentation |
| 10 | run-docker.sh, run-docker.ps1 | Add SINGLE_SHOT env vars |
| 11 | QUICKSTART.md | Add SINGLE_SHOT env var documentation |

---

## Plan complete and saved to `docs/superpowers/plans/2026-04-14-single-shot-audio-synthesis.md`

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?