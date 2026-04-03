# Ghost Narrator Resilience Guide

> Detailed guide on the resilience and observability features implemented in Ghost Narrator.

---

## Table of Contents

1. [Circuit Breaker](#circuit-breaker)
2. [API Versioning](#api-versioning)
3. [Metrics & Monitoring](#metrics--monitoring)
4. [Distributed Tracing](#distributed-tracing)
5. [Bulkhead Pattern](#bulkhead-pattern)
6. [Rate Limiting](#rate-limiting)

---

## Circuit Breaker

### Purpose
Prevents cascading failures when external services (n8n callbacks, Ghost API) are unavailable.

### How It Works
1. **Closed State**: Normal operation - requests pass through
2. **Open State**: After threshold failures - requests fail fast
3. **Half-Open State**: After recovery timeout - test if service recovered

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `CIRCUIT_BREAKER_FAILURE_THRESHOLD` | 5 | Failures before opening |
| `CIRCUIT_BREAKER_RECOVERY_TIMEOUT` | 30 | Seconds before recovery attempt |

### Monitoring
Check circuit state via health endpoint logs:
```
INFO: Circuit breaker CLOSED - normal operation
WARNING: Circuit breaker OPEN - failing fast
```

---

## API Versioning

### Usage
```bash
# Use default version (v1)
curl http://localhost:8020/tts/generate

# Explicit version
curl -H "Accept-Version: v1" http://localhost:8020/tts/generate
```

### Response Headers
All responses include `API-Version` header indicating the version used.

### Error Responses
Unsupported version returns 406:
```json
{
  "error": "Unsupported API version",
  "supported_versions": ["v1"],
  "requested_version": "v99"
}
```

---

## Metrics & Monitoring

### Prometheus Endpoint
```
http://localhost:8020/metrics
```

### Key Metrics

#### Job Metrics
- `tts_jobs_total{status="started|completed|failed"}` - Job counts
- `tts_jobs_processing_time_seconds` - Total job processing time

#### Synthesis Metrics
- `tts_synthesis_duration_seconds` - Audio synthesis time (bucket: 0.1s - 60s)
- `tts_chunks_total` - Audio chunks processed

#### Storage Metrics
- `tts_storage_upload_duration_seconds` - Upload time (bucket: 0.5s - 30s)

#### LLM Metrics
- `tts_narration_duration_seconds` - Narration time (bucket: 1s - 60s)

---

## Distributed Tracing

### Configuration
```bash
# Enable OTLP export
export OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317

# Set service name
export OTEL_SERVICE_NAME=ghost-narrator-tts
```

### Trace Context
Trace context is propagated via `traceparent` header:
```
traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01
```

### Viewing Traces
- Jaeger UI: `http://localhost:16686`
- Zipkin: `http://localhost:9411`

---

## Bulkhead Pattern

### Purpose
Isolates resource-intensive jobs from quick jobs to prevent starvation.

### Implementation
- **Short Jobs** (<1000 words): 4 concurrent slots, 60s timeout
- **Long Jobs** (>=1000 words): 1 concurrent slot, 300s timeout

### Behavior
When bulkhead is full:
1. Request is queued (wait for slot)
2. If timeout exceeded, falls back to direct execution
3. Logs warning: "Bulkhead full for job X"

---

## Rate Limiting

### Default Limits
- 60 requests per minute per IP
- Health and metrics endpoints excluded

### Configuration
```python
# In main.py
app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
```

### Response
```json
{
  "error": "Rate limit exceeded",
  "retry_after": 60
}
```

Headers:
- `Retry-After: 60`
- `HTTP 429 Too Many Requests`

---

## Troubleshooting

### Circuit Breaker Stuck Open
```bash
# Check recent failures
docker logs tts-service | grep "circuit breaker"

# Manually reset (restart service)
docker compose restart tts-service
```

### Rate Limited When Expected
```bash
# Check current rate limit state
docker logs tts-service | grep "rate limit"
```

### Metrics Not Appearing
```bash
# Verify endpoint accessible
curl http://localhost:8020/metrics

# Check Prometheus scrape configuration
```