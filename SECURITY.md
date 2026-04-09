# Security Policy

## Supported Versions

We currently support the following versions of Ghost Narrator:

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| < 1.0   | :x:                |

*The current release is v2.0.0 - see [releases](https://github.com/getsimpledirect/ghost-narrator/releases) for details.*

## Reporting a Vulnerability

If you discover a security vulnerability within Ghost Narrator, please report it via **GitHub Issues**: https://github.com/getsimpledirect/ghost-narrator/issues

Please mark the issue as "Security" or email the maintainer directly if it's sensitive.

Please include the following information:

- **Type** of vulnerability (e.g., XSS, SQL injection, etc.)
- **Full paths** of source file(s) related to the vulnerability
- **Location** of the affected source code (tag/branch/commit or direct URL)
- **Any** special configuration required to reproduce the issue
- **Step-by-step** instructions to reproduce the issue
- **Proof-of-concept** or exploit code (if possible)
- **Impact** of the issue, including how an attacker might exploit it

## What to Expect

- **Acknowledgment**: You should receive a response within 24 hours
- **Status Update**: We will provide updates on the progress of fixing the vulnerability
- **Disclosure**: Once the vulnerability is fixed, we will publicly disclose the vulnerability details

## Security Best Practices

When deploying Ghost Narrator:

1. **Never commit secrets** - Use `.env.example` as a template, never commit `.env`
2. **Rotate credentials regularly** - Especially n8n encryption keys and API keys
3. **Use HTTPS** - Enable TLS/SSL for all web-facing services
4. **Restrict network access** - Use firewall rules to limit access to internal services
5. **Keep dependencies updated** - Use Dependabot to receive security updates
6. **Monitor logs** - Review Docker and application logs for suspicious activity

## Architecture Security Model

Ghost Narrator uses a **defense-in-depth** approach with multiple security layers:

### Layer 1: Docker Network Isolation
The `docker-compose.yml` keeps internal services isolated on `pipeline_net`:

- **TTS Service** (`tts-service`) - Port 8020 published to host for direct API access; protected by API key auth (see Layer 3)
- **n8n** (`n8n`) - Port 5678 published for webhook receiving and UI access
- **Redis** (`redis`) - Port NOT published; accessible only within `pipeline_net`
- **Ollama** (`ollama`) - Port 11434 published for local LLM access

### Layer 2: VM Firewall
For production deployments, restrict access at the firewall level:
- Allow inbound to n8n (port 5678) only from Ghost CMS IPs
- Allow inbound to TTS service (port 8020) only from trusted IPs or keep internal
- Block all other inbound access

### Layer 3: TTS Service API Key Authentication
The TTS service requires an `Authorization: Bearer <TTS_API_KEY>` header on all synthesis requests. The `install.sh` script auto-generates this key and writes it to `.env`. The n8n workflow is pre-configured to read it from `$env.TTS_API_KEY` and send it with every request.

To rotate the key: generate a new value (`openssl rand -hex 32`), update `TTS_API_KEY` in `.env`, and restart all services (`docker compose restart`).

### Layer 4: Ghost Webhook Signature Verification
Incoming Ghost webhooks are verified using HMAC-SHA256 with `N8N_GHOST_WEBHOOK_SECRET`. The `install.sh` script auto-generates this secret. Set the same value in Ghost Admin → Settings → Integrations → Webhooks.

### Layer 5: n8n Authentication
Users access the pipeline through n8n's built-in owner account authentication, not directly to the TTS service.

## Scope

This security policy applies to:
- The Ghost Narrator codebase
- The TTS Service (Qwen3-TTS integration)
- n8n workflows
- Shell scripts and Docker configurations

This policy does NOT apply to:
- Third-party services (Ollama, n8n) - see their respective security policies
- External dependencies (Qwen3-TTS, PyTorch, etc.) - report to upstream maintainers