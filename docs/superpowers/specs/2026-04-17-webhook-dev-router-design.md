# Webhook Dev Router — Design Spec

**Date:** 2026-04-17  
**Status:** Approved  

## Problem

The production backend (Docker Swarm + Traefik) is the sole webhook receiver registered with Meta and Evolution API. There is no safe way to redirect real webhook traffic to a developer's local environment without disrupting live production traffic. Simulating payloads locally via scripts lacks fidelity for testing async flows, media handling, and real-time CRM reactivity.

## Goal

Allow a developer running `uvicorn` on port `8001` on the same VPS to receive **exact, real webhook payloads** from Meta and Evolution — while production continues processing all other traffic without interruption.

## Approach: Phone-Number Whitelist Routing via Redis

When a webhook arrives at production, the router checks if the sender's phone number is in the Redis Set `dev:phone_whitelist`. If yes, the payload is forwarded as a `BackgroundTask` to the dev server (`http://localhost:8001`) and production processing is **skipped** for that number. All other traffic is processed normally.

## Architecture

### New Module: `backend/app/dev_router/`

| File | Responsibility |
|------|---------------|
| `service.py` | Read/write Redis Set `dev:phone_whitelist`; normalize phone numbers |
| `forwarder.py` | Async HTTP forward via `httpx`; fire-and-forget; errors only logged |
| `router.py` | REST endpoints for whitelist management, mounted at `/api/dev` |

### Modified Files

| File | Change |
|------|--------|
| `app/webhook/router.py` | Intercept Evolution webhooks: check whitelist before processing |
| `app/webhook/meta_router.py` | Intercept Meta webhooks: check whitelist before processing |
| `app/config.py` | Add `dev_server_url` (default `http://localhost:8001`) and `dev_api_key` |
| `app/main.py` | Register `dev_router` |

## Data Flow

```
Webhook received by production FastAPI (Docker, port 8000)
  │
  ▼
Extract sender phone number from payload
  │
  ▼
Redis: phone in dev:phone_whitelist?
  ├── NO  → process normally in production
  └── YES → BackgroundTask: forward raw payload to http://localhost:8001{path}
             return {"status": "ok"} immediately to Meta/Evolution
             (dev server processes independently and calls outbound API itself)
```

## Forwarder Details (`forwarder.py`)

- Uses `httpx.AsyncClient` with connect timeout 10s, read timeout 30s
- Replicates original request headers (including `x-hub-signature-256` for Meta signature validation on dev)
- Forwards raw `bytes` body — zero re-serialization, byte-perfect replica
- If dev server is offline or times out: logs `WARNING`, swallows exception — production is never affected
- Affected message is silently dropped (acceptable: dev-only traffic, no real client impact)

**Evolution router note:** currently reads `await request.json()` only. Must also call `await request.body()` before json parsing to obtain raw bytes for forwarding.

## Whitelist Management Endpoints

All endpoints require header `X-Dev-Key: {dev_api_key}`.  
If `dev_api_key` is not set in `.env`, all endpoints return `503 Service Unavailable` (safe default for production).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dev/whitelist` | List all whitelisted phone numbers |
| `POST` | `/api/dev/whitelist/{phone}` | Add phone number to whitelist |
| `DELETE` | `/api/dev/whitelist/{phone}` | Remove phone number from whitelist |

Phone numbers are normalized on input: `+` and spaces stripped, stored as `5511999999999`.

### Usage Example

```bash
# Enable dev routing for your test number
curl -X POST https://api.canastrainteligencia.com/api/dev/whitelist/5511999999999 \
  -H "X-Dev-Key: sua-chave"

# Check whitelist
curl https://api.canastrainteligencia.com/api/dev/whitelist \
  -H "X-Dev-Key: sua-chave"

# Disable when done
curl -X DELETE https://api.canastrainteligencia.com/api/dev/whitelist/5511999999999 \
  -H "X-Dev-Key: sua-chave"
```

## Configuration (`.env` additions)

```env
DEV_SERVER_URL=http://localhost:8001   # default, override if needed
DEV_API_KEY=your-secret-key            # leave empty to disable feature
```

## Dev Server Startup

The dev server is the **same application** (`backend/app/main.py`) run directly on the VPS host:

```bash
uvicorn app.main:app --reload --port 8001
```

- Uses the same `.env` as production (same Redis, Supabase, LLM credentials)
- Redis at `redis://localhost:6379` — Docker already publishes this port to host
- Only required `.env` override: `API_BASE_URL=http://localhost:8001`

VS Code task (`.vscode/tasks.json`) should specify `--port 8001`.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Dev server offline | Log WARNING, return ok to Meta, message dropped silently |
| Dev server timeout (>30s) | Same as above |
| Redis unavailable during whitelist check | Log ERROR, fall through to normal production processing (safe default) |
| Invalid/missing `X-Dev-Key` | 401 Unauthorized |
| `DEV_API_KEY` not configured | 503 Service Unavailable |

## Non-Goals

- No Ngrok or external tunnel required
- No separate Meta App or test numbers required
- No changes to Docker Swarm or Traefik configuration
- No separate Supabase project or LLM keys required
