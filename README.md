# Ghost Narrator

> Automated studio-quality audio narration for Ghost CMS — powered by Qwen3-TTS voice cloning.

Ghost Narrator converts your Ghost articles into podcast-quality MP3 audio automatically when you publish. Drop in a voice reference file and every post gets a narrated audio version — embedded directly in the article.

## Features

- **Zero-config hardware detection** — auto-selects the right Qwen3-TTS model for your machine
- **Voice cloning** — natural voice cloning from a 5-second reference audio sample
- **Information-preserving narration** — LLM rewrites articles to spoken format without losing facts
- **Flexible storage** — local folder, Google Cloud Storage, or AWS S3
- **Ghost CMS integration** — webhook-driven, embeds an HTML5 audio player in published posts
- **Static content support** — narrate books, series pages, or any plain text via API

## Hardware Tiers

| Tier | VRAM | TTS Model | Output Quality |
|---|---|---|---|
| CPU only | None | Qwen3-TTS-0.6B | 192kbps, 44.1kHz |
| Low (4–8 GB) | 4–8 GB | Qwen3-TTS-0.6B | 192kbps, 44.1kHz |
| Mid (10–16 GB) | 10–16 GB | Qwen3-TTS-1.7B | 192kbps, 44.1kHz |
| High (20+ GB) | 20+ GB | Qwen3-TTS-1.7B | 256kbps, 48kHz, −14 LUFS |

## Quick Start

```bash
cp .env.example .env
# Edit .env — set Ghost API keys, storage backend, server IP
# Place voice reference: tts-service/voices/default/reference.wav
./start.sh up -d
```

Open `http://YOUR_IP:5678` and import the three n8n workflows from `n8n/workflows/`.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full setup.

## Storage

```env
STORAGE_BACKEND=local   # default — no cloud setup needed
STORAGE_BACKEND=gcs     # Google Cloud Storage
STORAGE_BACKEND=s3      # AWS S3
```

Run `bash scripts/setup-storage.sh gcs` or `bash scripts/setup-storage.sh s3` for guided setup.

## License

Project code: [MIT License](LICENSE)
Qwen3-TTS models: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)
