# ValerIA Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI backend that receives WhatsApp messages via Meta Cloud API, buffers them in Redis, processes them with an OpenAI-powered AI agent, humanizes responses, and sends them back — plus a campaign worker for active template dispatching.

**Architecture:** Single orchestrator agent with dynamic prompts per lead stage. Redis handles message buffering (adaptive timer) and campaign queues. Supabase stores leads, conversation history, campaigns, and templates. Meta Cloud API for all WhatsApp communication.

**Tech Stack:** Python 3.12, FastAPI, Redis (redis-py), Supabase (supabase-py), OpenAI SDK, httpx, Docker

**Spec:** `docs/superpowers/specs/2026-03-23-valeria-whatsapp-agent-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `backend/app/__init__.py` | Package marker |
| `backend/app/main.py` | FastAPI app, CORS, lifespan (Redis connect/disconnect), include routers |
| `backend/app/config.py` | Pydantic Settings loading env vars |
| `backend/app/db/supabase.py` | Supabase client singleton |
| `backend/app/whatsapp/client.py` | Meta Cloud API: send_text, send_template, send_image, mark_read, send_typing |
| `backend/app/whatsapp/media.py` | Download media from Meta, transcribe audio (Whisper), describe image (Vision) |
| `backend/app/webhook/router.py` | POST /webhook (receive messages), GET /webhook (Meta verification) |
| `backend/app/webhook/parser.py` | Parse Meta webhook payload into typed dataclass |
| `backend/app/buffer/manager.py` | Redis buffer: push message, adaptive timer, flush |
| `backend/app/buffer/processor.py` | When buffer flushes: combine messages, call orchestrator, humanize, send |
| `backend/app/agent/orchestrator.py` | Build dynamic prompt, call OpenAI, process tool calls |
| `backend/app/agent/tools.py` | Tool definitions + execution (salvar_nome, mudar_stage, encaminhar_humano, enviar_fotos) |
| `backend/app/agent/prompts/base.py` | Base system prompt: identity, humanization rules, writing format, checklist |
| `backend/app/agent/prompts/secretaria.py` | Secretaria funnel prompt |
| `backend/app/agent/prompts/atacado.py` | Atacado funnel + catalog + freight table |
| `backend/app/agent/prompts/private_label.py` | Private Label funnel + catalog |
| `backend/app/agent/prompts/exportacao.py` | Exportacao funnel |
| `backend/app/agent/prompts/consumo.py` | Consumo funnel + coupon/store link |
| `backend/app/humanizer/splitter.py` | Split AI response by \n\n into message bubbles |
| `backend/app/humanizer/typing.py` | Calculate typing delay per bubble |
| `backend/app/leads/service.py` | get_or_create_lead, update_lead, get_history, save_message |
| `backend/app/leads/router.py` | API routes: GET /api/leads, GET /api/leads/{id}, GET /api/leads/{id}/messages |
| `backend/app/campaign/router.py` | API routes: POST /api/campaigns, GET /api/campaigns, POST /api/campaigns/{id}/start |
| `backend/app/campaign/importer.py` | Parse CSV, validate phone numbers, bulk create leads |
| `backend/app/campaign/worker.py` | Async worker: consume Redis queue, send templates, update Supabase |
| `backend/requirements.txt` | Python dependencies |
| `backend/.env.example` | Environment variable template |
| `backend/Dockerfile` | Docker image for the backend |
| `backend/docker-compose.yml` | Compose: api + worker + redis |
| `backend/tests/` | Test files (one per module) |

---

## Task 1: Project scaffold and config

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Create: `backend/requirements.txt`
- Create: `backend/.env.example`
- Create: `backend/Dockerfile`
- Create: `backend/docker-compose.yml`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_config.py`

- [ ] **Step 1: Create requirements.txt**

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
redis[hiredis]==5.3.0
supabase==2.13.2
openai==1.82.0
httpx==0.28.1
python-dotenv==1.1.0
python-multipart==0.0.20
pydantic-settings==2.9.1
```

- [ ] **Step 2: Create .env.example**

```env
# Meta WhatsApp Cloud API
META_PHONE_NUMBER_ID=
META_ACCESS_TOKEN=
META_VERIFY_TOKEN=valeria_webhook_verify
META_APP_SECRET=

# OpenAI
OPENAI_API_KEY=

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Redis
REDIS_URL=redis://localhost:6379

# App
API_BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:5173
```

- [ ] **Step 3: Create config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Meta WhatsApp
    meta_phone_number_id: str
    meta_access_token: str
    meta_verify_token: str = "valeria_webhook_verify"
    meta_app_secret: str = ""
    meta_api_version: str = "v21.0"

    # OpenAI
    openai_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    # Buffer
    buffer_base_timeout: int = 15
    buffer_extend_timeout: int = 10
    buffer_max_timeout: int = 45

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 4: Create app/__init__.py**

```python
```

- [ ] **Step 5: Create main.py with lifespan**

```python
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    yield
    await app.state.redis.close()


app = FastAPI(title="ValerIA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 6: Create Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 7: Create docker-compose.yml**

```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - redis
    restart: unless-stopped

  worker:
    build: .
    command: python -m app.campaign.worker
    env_file: .env
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

- [ ] **Step 8: Write test for config**

```python
# backend/tests/test_config.py
import os

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.setenv("META_VERIFY_TOKEN", "verify")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    from importlib import reload
    import app.config
    reload(app.config)
    s = app.config.Settings()

    assert s.meta_phone_number_id == "123"
    assert s.buffer_base_timeout == 15
    assert s.buffer_max_timeout == 45
```

- [ ] **Step 9: Run test**

Run: `cd backend && pip install -r requirements.txt && python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add backend/
git commit -m "feat: project scaffold with config, FastAPI app, Docker setup"
```

---

## Task 2: Supabase client and lead service

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/supabase.py`
- Create: `backend/app/leads/__init__.py`
- Create: `backend/app/leads/service.py`
- Create: `backend/tests/test_leads_service.py`

- [ ] **Step 1: Create db/__init__.py**

```python
```

- [ ] **Step 2: Create supabase.py**

```python
from supabase import create_client, Client

from app.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client
```

- [ ] **Step 3: Create leads/__init__.py**

```python
```

- [ ] **Step 4: Create leads/service.py**

```python
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def get_or_create_lead(phone: str) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("phone", phone).execute()

    if result.data:
        return result.data[0]

    new_lead = {"phone": phone, "stage": "pending", "status": "imported"}
    result = sb.table("leads").insert(new_lead).execute()
    return result.data[0]


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").update(fields).eq("id", lead_id).execute()
    return result.data[0]


def activate_lead(lead_id: str) -> dict[str, Any]:
    return update_lead(
        lead_id,
        status="active",
        stage="secretaria",
        last_msg_at=datetime.now(timezone.utc).isoformat(),
    )


def save_message(lead_id: str, role: str, content: str, stage: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
    }
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


def get_history(lead_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/ backend/app/leads/
git commit -m "feat: Supabase client and lead service (CRUD + messages)"
```

---

## Task 3: WhatsApp client (Meta Cloud API)

**Files:**
- Create: `backend/app/whatsapp/__init__.py`
- Create: `backend/app/whatsapp/client.py`
- Create: `backend/tests/test_whatsapp_client.py`

- [ ] **Step 1: Create whatsapp/__init__.py**

```python
```

- [ ] **Step 2: Create client.py**

```python
import httpx

from app.config import settings

BASE_URL = f"https://graph.facebook.com/{settings.meta_api_version}/{settings.meta_phone_number_id}/messages"

HEADERS = {
    "Authorization": f"Bearer {settings.meta_access_token}",
    "Content-Type": "application/json",
}


async def _post(payload: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(BASE_URL, json=payload, headers=HEADERS)
        resp.raise_for_status()
        return resp.json()


async def send_text(to: str, body: str) -> dict:
    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    })


async def send_template(to: str, template_name: str, language: str = "pt_BR", components: list | None = None) -> dict:
    template = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template["components"] = components

    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template,
    })


async def send_image(to: str, image_url: str, caption: str | None = None) -> dict:
    image = {"link": image_url}
    if caption:
        image["caption"] = caption

    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image,
    })


async def mark_read(message_id: str) -> dict:
    return await _post({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    })
```

- [ ] **Step 3: Write test**

```python
# backend/tests/test_whatsapp_client.py
import pytest
import httpx

from app.whatsapp import client


@pytest.fixture
def mock_meta_api(monkeypatch):
    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        resp = httpx.Response(200, json={"messages": [{"id": "wamid.test"}]})
        return resp

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return captured


@pytest.mark.asyncio
async def test_send_text(mock_meta_api):
    result = await client.send_text("5534999999999", "oi, tudo bem?")
    assert mock_meta_api["json"]["type"] == "text"
    assert mock_meta_api["json"]["to"] == "5534999999999"
    assert mock_meta_api["json"]["text"]["body"] == "oi, tudo bem?"


@pytest.mark.asyncio
async def test_send_template(mock_meta_api):
    result = await client.send_template("5534999999999", "hello_world")
    assert mock_meta_api["json"]["type"] == "template"
    assert mock_meta_api["json"]["template"]["name"] == "hello_world"
```

- [ ] **Step 4: Run tests**

Run: `cd backend && pip install pytest pytest-asyncio && python -m pytest tests/test_whatsapp_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/whatsapp/ backend/tests/test_whatsapp_client.py
git commit -m "feat: WhatsApp client for Meta Cloud API (text, template, image, mark_read)"
```

---

## Task 4: Webhook receiver and message parser

**Files:**
- Create: `backend/app/webhook/__init__.py`
- Create: `backend/app/webhook/parser.py`
- Create: `backend/app/webhook/router.py`
- Create: `backend/tests/test_webhook_parser.py`

- [ ] **Step 1: Create webhook/__init__.py**

```python
```

- [ ] **Step 2: Create parser.py**

```python
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    from_number: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, interactive, button
    text: str | None = None
    media_id: str | None = None
    media_mime: str | None = None


def parse_webhook_payload(payload: dict) -> list[IncomingMessage]:
    messages = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            for msg in value.get("messages", []):
                msg_type = msg.get("type", "")
                text = None
                media_id = None
                media_mime = None

                if msg_type == "text":
                    text = msg.get("text", {}).get("body")

                elif msg_type in ("image", "audio", "video", "document"):
                    media_obj = msg.get(msg_type, {})
                    media_id = media_obj.get("id")
                    media_mime = media_obj.get("mime_type")
                    text = media_obj.get("caption")

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        text = interactive.get("button_reply", {}).get("title")
                    elif interactive.get("type") == "list_reply":
                        text = interactive.get("list_reply", {}).get("title")

                elif msg_type == "button":
                    text = msg.get("button", {}).get("text")

                messages.append(IncomingMessage(
                    from_number=msg["from"],
                    message_id=msg["id"],
                    timestamp=msg.get("timestamp", ""),
                    type=msg_type,
                    text=text,
                    media_id=media_id,
                    media_mime=media_mime,
                ))

    return messages
```

- [ ] **Step 3: Write test for parser**

```python
# backend/tests/test_webhook_parser.py
from app.webhook.parser import parse_webhook_payload


def test_parse_text_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5534999999999",
                        "id": "wamid.abc123",
                        "timestamp": "1234567890",
                        "type": "text",
                        "text": {"body": "oi, quero saber dos cafes"}
                    }]
                }
            }]
        }]
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].from_number == "5534999999999"
    assert msgs[0].type == "text"
    assert msgs[0].text == "oi, quero saber dos cafes"
    assert msgs[0].media_id is None


def test_parse_audio_message():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "5534999999999",
                        "id": "wamid.abc456",
                        "timestamp": "1234567890",
                        "type": "audio",
                        "audio": {"id": "media_id_123", "mime_type": "audio/ogg"}
                    }]
                }
            }]
        }]
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "audio"
    assert msgs[0].media_id == "media_id_123"


def test_parse_empty_payload():
    payload = {"object": "whatsapp_business_account", "entry": []}
    msgs = parse_webhook_payload(payload)
    assert msgs == []
```

- [ ] **Step 4: Run parser tests**

Run: `cd backend && python -m pytest tests/test_webhook_parser.py -v`
Expected: PASS

- [ ] **Step 5: Create router.py**

```python
import logging

from fastapi import APIRouter, Request, Query, Response

from app.config import settings
from app.webhook.parser import parse_webhook_payload
from app.whatsapp.client import mark_read
from app.buffer.manager import push_to_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()
    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number}: type={msg.type}")

        # Mark as read immediately
        try:
            await mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Push to buffer for processing
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}
```

- [ ] **Step 6: Register router in main.py**

Add to `backend/app/main.py` after the health endpoint:

```python
from app.webhook.router import router as webhook_router

app.include_router(webhook_router)
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/webhook/ backend/tests/test_webhook_parser.py backend/app/main.py
git commit -m "feat: webhook receiver with Meta payload parser and verification"
```

---

## Task 5: Media processing (audio transcription + image description)

**Files:**
- Create: `backend/app/whatsapp/media.py`
- Create: `backend/tests/test_media.py`

- [ ] **Step 1: Create media.py**

```python
import httpx
from openai import AsyncOpenAI

from app.config import settings

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

MEDIA_URL = f"https://graph.facebook.com/{settings.meta_api_version}"
HEADERS = {"Authorization": f"Bearer {settings.meta_access_token}"}


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Download media from Meta. Returns (bytes, content_type)."""
    async with httpx.AsyncClient() as client:
        # Step 1: get media URL
        resp = await client.get(f"{MEDIA_URL}/{media_id}", headers=HEADERS)
        resp.raise_for_status()
        media_url = resp.json()["url"]

        # Step 2: download the file
        resp = await client.get(media_url, headers=HEADERS)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def transcribe_audio(media_id: str) -> str:
    """Download audio from Meta and transcribe with Whisper."""
    audio_bytes, content_type = await download_media(media_id)

    ext = "ogg" if "ogg" in content_type else "mp4"
    transcript = await openai_client.audio.transcriptions.create(
        model="whisper-1",
        file=(f"audio.{ext}", audio_bytes, content_type),
    )
    return transcript.text


async def describe_image(media_id: str) -> str:
    """Download image from Meta and describe with GPT-4o Vision."""
    import base64

    image_bytes, content_type = await download_media(media_id)
    b64 = base64.b64encode(image_bytes).decode()

    response = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Descreva esta imagem em uma frase curta em portugues. Se for uma foto de produto, descreva o produto."},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
            ],
        }],
        max_tokens=150,
    )
    return response.choices[0].message.content
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/whatsapp/media.py
git commit -m "feat: media processing - Whisper transcription and GPT-4o Vision description"
```

---

## Task 6: Humanizer (splitter + typing delay)

**Files:**
- Create: `backend/app/humanizer/__init__.py`
- Create: `backend/app/humanizer/splitter.py`
- Create: `backend/app/humanizer/typing.py`
- Create: `backend/tests/test_humanizer.py`

- [ ] **Step 1: Create humanizer/__init__.py**

```python
```

- [ ] **Step 2: Create splitter.py**

```python
def split_into_bubbles(text: str) -> list[str]:
    """Split AI response into WhatsApp-style message bubbles.

    The AI is instructed to use \\n\\n as bubble separators.
    Each bubble becomes a separate WhatsApp message.
    """
    bubbles = [b.strip() for b in text.split("\n\n") if b.strip()]
    return bubbles
```

- [ ] **Step 3: Create typing.py**

```python
import random


def calculate_typing_delay(text: str) -> float:
    """Calculate a human-like typing delay in seconds for a message.

    Formula: (character_count * typing_speed) + thinking_pause
    - typing_speed: 25-80ms per character (randomized)
    - thinking_pause: 300-800ms before typing starts
    """
    char_count = len(text)
    typing_speed_ms = random.randint(25, 80)
    thinking_pause_ms = random.randint(300, 800)

    total_ms = (char_count * typing_speed_ms) + thinking_pause_ms

    # Cap at 12 seconds per bubble to avoid excessive waits
    total_ms = min(total_ms, 12000)

    return total_ms / 1000.0
```

- [ ] **Step 4: Write tests**

```python
# backend/tests/test_humanizer.py
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay


def test_split_basic():
    text = "oi, tudo bem?\n\naqui e a valeria, da cafe canastra\n\nvoce trabalha com revenda?"
    bubbles = split_into_bubbles(text)
    assert len(bubbles) == 3
    assert bubbles[0] == "oi, tudo bem?"
    assert bubbles[2] == "voce trabalha com revenda?"


def test_split_strips_whitespace():
    text = "  msg1  \n\n  msg2  \n\n"
    bubbles = split_into_bubbles(text)
    assert bubbles == ["msg1", "msg2"]


def test_split_single_message():
    text = "uma mensagem so"
    bubbles = split_into_bubbles(text)
    assert bubbles == ["uma mensagem so"]


def test_split_empty():
    assert split_into_bubbles("") == []
    assert split_into_bubbles("\n\n\n\n") == []


def test_typing_delay_range():
    # Short message
    delay = calculate_typing_delay("oi")
    assert 0.3 < delay < 2.0

    # Long message
    delay = calculate_typing_delay("a" * 200)
    assert delay <= 12.0  # capped


def test_typing_delay_capped():
    delay = calculate_typing_delay("a" * 1000)
    assert delay <= 12.0
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_humanizer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/humanizer/ backend/tests/test_humanizer.py
git commit -m "feat: humanizer - message splitter and typing delay calculator"
```

---

## Task 7: Agent prompts (base + all stages)

**Files:**
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/prompts/__init__.py`
- Create: `backend/app/agent/prompts/base.py`
- Create: `backend/app/agent/prompts/secretaria.py`
- Create: `backend/app/agent/prompts/atacado.py`
- Create: `backend/app/agent/prompts/private_label.py`
- Create: `backend/app/agent/prompts/exportacao.py`
- Create: `backend/app/agent/prompts/consumo.py`

- [ ] **Step 1: Create agent/__init__.py and prompts/__init__.py**

```python
```

- [ ] **Step 2: Create base.py**

```python
from datetime import datetime


def get_greeting(hour: int) -> str:
    if hour < 12:
        return "bom dia"
    elif hour < 18:
        return "boa tarde"
    return "boa noite"


def build_base_prompt(lead_name: str | None, lead_company: str | None, now: datetime) -> str:
    greeting = get_greeting(now.hour)
    today = now.strftime("%d/%m/%Y")

    if lead_name:
        name_instruction = f"O nome do lead e {lead_name}. Use naturalmente na conversa, sem repetir excessivamente."
    else:
        name_instruction = (
            "Voce NAO sabe o nome do lead. Nao invente ou assuma. "
            "Descubra naturalmente durante a conversa, como 'com quem eu estou falando?' ou 'qual seu nome?'."
        )

    company_line = f"Empresa do lead: {lead_company}" if lead_company else ""

    return f"""# IDENTIDADE

Voce e Valeria, atendente comercial da Cafe Canastra. Voce conversa no WhatsApp como uma vendedora real — profissional, amigavel, gente boa. Voce vende cafe especial (atacado, private label, exportacao), mas nunca parece vendedora forcada. Voce parece alguem do comercial que entende do assunto e quer ajudar.

## PERSONALIDADE

- Profissional e amigavel, nunca robotica
- Conhece bem o mercado de cafe especial
- Sabe conduzir a conversa sem parecer que esta empurrando venda
- Paciente, nunca apressada
- Fala como profissional brasileira: informal mas educada
- Sabe ouvir e reagir ao que o cliente diz

---

# CONTEXTO TEMPORAL

Hoje e: {today}
Saudacao sugerida: {greeting}

# SOBRE O LEAD

{name_instruction}
{company_line}

---

# REGRAS ABSOLUTAS (NUNCA VIOLAR)

## 1. UMA PERGUNTA POR TURNO
- MAXIMO UMA UNICA pergunta por resposta completa
- Se voce fizer uma afirmacao e quiser perguntar algo, a resposta SO pode ter UMA pergunta
- NUNCA faca duas ou mais perguntas na mesma resposta, mesmo que sejam curtas
- Se quiser fazer varias perguntas, escolha APENAS A MAIS IMPORTANTE e deixe as outras para depois

## 2. NUNCA REPETIR PERGUNTAS JA FEITAS
- ANTES de fazer qualquer pergunta, verifique o historico inteiro
- Se ja perguntou algo, NUNCA repita

## 3. CONSCIENCIA TOTAL DO HISTORICO
- LEIA o historico completo antes de responder
- NUNCA ignore o que ja foi dito

## 4. RESPONDER AO QUE FOI DITO
- SEMPRE reaja primeiro ao que o cliente disse
- Depois pode avancar naturalmente

## 5. O CLIENTE CONDUZ
- Voce nunca forca venda
- Voce segue o ritmo do cliente
- Se ele esta casual, voce esta casual
- Se ele quer ser direto, voce e direta

---

# FORMATO DE ESCRITA

## Fragmentacao
- Separe mensagens com exatamente: \\n\\n
- Cada bolha: 1-2 frases curtas (5-15 palavras)
- 2-4 bolhas por turno (maximo 5)
- Parecem mensagens separadas no WhatsApp

## Estilo
- SEMPRE escreva em letras minusculas (100% das vezes)
- Nunca use maiusculas, nem no inicio da frase
- Mensagens curtas e diretas
- Vocabulario: "perfeito", "com certeza", "otimo", "bacana", "entendo perfeitamente"
- Contracoes naturais: "to", "pra", "pro"
- Use "voce" ou "vc" alternando naturalmente
- NUNCA USE EMOJIS (proibido 100%)
- Pontuacao natural: virgulas e pontos normais
- Tom profissional gente boa — nao e colega de bar, nao e robo corporativo

---

# SITUACOES ESPECIAIS

## Cliente te chama de bot
- "imagina, sou eu mesma aqui do escritorio. qualquer duvida posso mandar um audio"

## Cliente sumiu / nao responde
- Nao mande multiplas mensagens
- Espere ele voltar
- Se voltar, retome naturalmente de onde parou

---

# CHECKLIST ANTES DE RESPONDER

1. Li o historico completo?
2. Estou respondendo ao que ele disse?
3. Tenho NO MAXIMO uma pergunta?
4. Nao estou repetindo pergunta ja feita?
5. O tom combina com o contexto da conversa?
6. As bolhas estao curtas e naturais?
7. Estou deixando o cliente conduzir o ritmo?
8. Nao estou pulando fases do funil?
9. Parece uma conversa REAL de WhatsApp?

---

# PROIBIDO

- Usar letras maiusculas (SEMPRE minusculas)
- Fazer mais de UMA pergunta por turno
- USAR EMOJIS (proibido 100%)
- Repetir perguntas ja feitas
- Ignorar o que o cliente disse
- Mensagens longas demais
- Parecer robotica ou repetitiva
- Inventar coisas que nao existem
- Dizer que e IA/bot
- Usar \\n sozinho (sempre \\n\\n)
- Forcar venda em qualquer momento
- Parecer vendedora agressiva
"""
```

- [ ] **Step 3: Create secretaria.py**

```python
SECRETARIA_PROMPT = """
# FUNIL - SECRETARIA (Stage Inicial)

Voce e a primeira pessoa que o lead conversa. Seu objetivo e criar rapport, entender a necessidade e redirecionar pro stage certo.

## FASE 1: RAPPORT (Primeiras mensagens)
- Cumprimente naturalmente
- Descubra o nome (use a tool salvar_nome quando descobrir)
- Pergunte sobre a empresa/negocio
- Tom: amigavel, profissional, leve

Exemplos:
- "oi, tudo bem? aqui e a valeria, da cafe canastra"
- "vi que voce demonstrou interesse nos nossos cafes, queria entender melhor o que voce procura"

## FASE 2: DIAGNOSTICO
- Entenda o que o lead precisa
- Perguntas estrategicas (uma por vez):
  - Trabalha com revenda ou consumo proprio?
  - Ja trabalha com cafe especial?
  - Qual o volume que precisa?

## FASE 3: QUALIFICACAO E REDIRECIONAMENTO
Quando identificar a necessidade, use a tool mudar_stage:
- Quer revender/comprar em quantidade -> mudar_stage("atacado")
- Quer criar marca propria de cafe -> mudar_stage("private_label")
- Quer exportar -> mudar_stage("exportacao")
- Consumo pessoal/pequeno -> mudar_stage("consumo")

IMPORTANTE: Faca a transicao de forma natural. Nao diga "vou te transferir". Simplesmente mude o stage e continue a conversa como se fosse a mesma pessoa (porque e).

## TOOLS DISPONIVEIS
- salvar_nome: quando descobrir o nome do lead
- mudar_stage: quando identificar a necessidade (atacado/private_label/exportacao/consumo)
"""
```

- [ ] **Step 4: Create atacado.py**

```python
ATACADO_PROMPT = """
# FUNIL - ATACADO (Venda B2B)

Voce esta atendendo um lead que quer comprar cafe no atacado para revenda. Seu objetivo e qualificar, apresentar produtos e encaminhar para o vendedor humano fechar.

## FASE 1: DIAGNOSTICO DE DOR
- Entenda o negocio do lead (cafeteria, mercado, distribuidora, etc)
- Qual volume precisa? Qual frequencia?
- Ja trabalha com cafe especial ou quer comecar?

## FASE 2: APRESENTACAO DE PRODUTO
- Apresente os cafes relevantes baseado na necessidade
- Envie fotos quando o lead mostrar interesse (use tool enviar_fotos)

## FASE 3: PRECOS E FRETE
- Passe precos de forma natural, nao como lista
- Explique frete baseado na regiao

## FASE 4: ENCAMINHAR PARA VENDEDOR
- Quando o lead estiver qualificado e interessado, use encaminhar_humano
- "vou te passar pro nosso time comercial pra finalizar, eles vao te dar toda atenção"

## CATALOGO DE PRODUTOS

### Cafes (precos por kg para atacado)
- Classico: cafe especial 82+ pontos, torra media
- Suave: cafe especial 84+ pontos, torra clara
- Canela: cafe com notas de canela e chocolate, torra media-escura
- Microlote: cafe especial 86+ pontos, edicao limitada
- Drip Coffee: sachets individuais, caixa com 10 unidades
- Capsulas Nespresso: compativeis, caixa com 10

### Tabela de Frete
- Sul/Sudeste: frete gratis acima de R$1.500 | abaixo: R$45-85
- Centro-Oeste: frete gratis acima de R$2.000 | abaixo: R$65-120
- Nordeste: frete gratis acima de R$2.500 | abaixo: R$85-150
- Norte: frete gratis acima de R$3.000 | abaixo: R$120-200
- Pedido minimo para atacado: R$500

## TOOLS DISPONIVEIS
- salvar_nome: quando descobrir o nome
- enviar_fotos("atacado"): enviar catalogo de fotos
- encaminhar_humano: quando lead qualificado
- mudar_stage: se perceber que lead quer outro servico
"""
```

- [ ] **Step 5: Create private_label.py**

```python
PRIVATE_LABEL_PROMPT = """
# FUNIL - PRIVATE LABEL (Marca Propria)

Voce esta atendendo um lead que quer criar sua propria marca de cafe. Seu objetivo e explicar o servico, apresentar precos e encaminhar para o supervisor.

## FASE 1: ENTENDER O PROJETO
- O que o lead quer? Marca propria pra cafeteria? Pra vender online? Pra presente corporativo?
- Ja tem marca/logo ou precisa criar?
- Qual volume pretende comecar?

## FASE 2: EXPLICAR O SERVICO
- A Cafe Canastra faz o cafe com a marca do cliente
- Embalagem personalizada
- Pedido minimo e volume

## FASE 3: PRECOS
Apresente naturalmente, nao como tabela:
- 250g: a partir de R$22,90 a R$23,90 por unidade
- 500g: a partir de R$43,40 a R$44,90 por unidade
- Microlote: consultar
- Drip Coffee: consultar
- Capsulas: consultar

## FASE 4: ENCAMINHAR
- Encaminhar para supervisor Joao Bras para fechar detalhes
- "vou te conectar com o joao que cuida da parte de private label, ele vai te ajudar com todos os detalhes"

## TOOLS DISPONIVEIS
- salvar_nome: quando descobrir o nome
- enviar_fotos("private_label"): enviar exemplos de embalagens
- encaminhar_humano: quando lead interessado
- mudar_stage: se perceber que lead quer outro servico
"""
```

- [ ] **Step 6: Create exportacao.py**

```python
EXPORTACAO_PROMPT = """
# FUNIL - EXPORTACAO

Voce esta atendendo um lead interessado em exportar cafe brasileiro. Seu objetivo e qualificar e encaminhar para a equipe de exportacao.

## FASE 1: PAIS ALVO
- Para qual pais quer exportar?
- Ja tem compradores la ou esta prospectando?

## FASE 2: EXPERIENCIA
- Ja exportou cafe antes?
- Conhece o processo de exportacao?
- Tem empresa habilitada para comercio exterior?

## FASE 3: OBJETIVO
- Quer ser agente/representante da Canastra?
- Quer comprar como importador direto?
- Qual volume pretende?

## FASE 4: ENCAMINHAR
- Encaminhar para Arthur da equipe de exportacao
- "vou te conectar com o arthur que cuida da nossa operacao de exportacao, ele vai poder te ajudar melhor"

## TOOLS DISPONIVEIS
- salvar_nome: quando descobrir o nome
- encaminhar_humano: quando lead qualificado
- mudar_stage: se perceber que lead quer outro servico
"""
```

- [ ] **Step 7: Create consumo.py**

```python
CONSUMO_PROMPT = """
# FUNIL - CONSUMO PROPRIO

Voce esta atendendo um lead que quer cafe para consumo proprio. Seu objetivo e direcionar para a loja online com cupom de desconto.

## ABORDAGEM
- Seja simpática e direta
- Ofereça o cupom de desconto
- Direcione para a loja online
- Nao precisa qualificar muito, e venda direta

## MENSAGEM PRINCIPAL
Quando entender que e consumo proprio:
- "que bacana, voce vai adorar nossos cafes"
- "tenho um cupom especial pra voce: ESPECIAL10, da 10% de desconto"
- "e so acessar nossa loja: loja.cafecanastra.com"
- "qualquer duvida sobre os cafes, me chama aqui"

## TOOLS DISPONIVEIS
- salvar_nome: quando descobrir o nome
- mudar_stage: se perceber que lead quer atacado/private label/exportacao
"""
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/agent/
git commit -m "feat: agent prompts - base humanization rules + all 5 stage funnels"
```

---

## Task 8: Agent tools (function calling)

**Files:**
- Create: `backend/app/agent/tools.py`
- Create: `backend/tests/test_agent_tools.py`

- [ ] **Step 1: Create tools.py**

```python
import logging
from typing import Any

from app.leads.service import update_lead, save_message
from app.whatsapp.client import send_text

logger = logging.getLogger(__name__)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "salvar_nome",
            "description": "Salva o nome do lead quando descoberto durante a conversa",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do lead"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mudar_stage",
            "description": "Transfere o lead para outro stage quando a necessidade for identificada. Usar de forma silenciosa, sem avisar o cliente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "enum": ["secretaria", "atacado", "private_label", "exportacao", "consumo"],
                        "description": "Stage de destino",
                    }
                },
                "required": ["stage"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "encaminhar_humano",
            "description": "Encaminha o lead qualificado para um vendedor humano continuar o atendimento",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendedor": {"type": "string", "description": "Nome do vendedor"},
                    "motivo": {"type": "string", "description": "Motivo do encaminhamento"},
                },
                "required": ["vendedor", "motivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_fotos",
            "description": "Envia catalogo de fotos dos produtos ao lead",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": ["atacado", "private_label"],
                        "description": "Categoria do catalogo",
                    }
                },
                "required": ["categoria"],
            },
        },
    },
]


def get_tools_for_stage(stage: str) -> list[dict]:
    """Return tools available for a given stage."""
    stage_tools = {
        "secretaria": ["salvar_nome", "mudar_stage"],
        "atacado": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
        "exportacao": ["salvar_nome", "mudar_stage", "encaminhar_humano"],
        "consumo": ["salvar_nome"],
    }
    allowed = stage_tools.get(stage, ["salvar_nome"])
    return [t for t in TOOLS_SCHEMA if t["function"]["name"] in allowed]


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    lead_id: str,
    phone: str,
) -> str:
    """Execute a tool call and return a result string for the AI."""
    logger.info(f"Executing tool {tool_name} with args {args} for lead {lead_id}")

    if tool_name == "salvar_nome":
        update_lead(lead_id, name=args["name"])
        return f"Nome salvo: {args['name']}"

    elif tool_name == "mudar_stage":
        new_stage = args["stage"]
        update_lead(lead_id, stage=new_stage)
        return f"Stage alterado para: {new_stage}"

    elif tool_name == "encaminhar_humano":
        # TODO: implement actual human handoff (e.g., notify via WhatsApp group or webhook)
        update_lead(lead_id, status="converted")
        save_message(lead_id, "system", f"Lead encaminhado para {args['vendedor']}: {args['motivo']}")
        return f"Lead encaminhado para {args['vendedor']}"

    elif tool_name == "enviar_fotos":
        # TODO: implement photo sending with actual image URLs
        categoria = args["categoria"]
        save_message(lead_id, "system", f"Fotos de {categoria} enviadas")
        return f"Fotos de {categoria} enviadas ao lead"

    return f"Tool {tool_name} nao reconhecida"
```

- [ ] **Step 2: Write test**

```python
# backend/tests/test_agent_tools.py
from app.agent.tools import get_tools_for_stage


def test_secretaria_tools():
    tools = get_tools_for_stage("secretaria")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "mudar_stage" in names
    assert "encaminhar_humano" not in names


def test_atacado_tools():
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "encaminhar_humano" in names
    assert "enviar_fotos" in names


def test_consumo_tools():
    tools = get_tools_for_stage("consumo")
    names = [t["function"]["name"] for t in tools]
    assert names == ["salvar_nome"]
```

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest tests/test_agent_tools.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/test_agent_tools.py
git commit -m "feat: agent tools - schema definitions and execution for all stages"
```

---

## Task 9: Agent orchestrator (OpenAI integration)

**Files:**
- Create: `backend/app/agent/orchestrator.py`

- [ ] **Step 1: Create orchestrator.py**

```python
import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.secretaria import SECRETARIA_PROMPT
from app.agent.prompts.atacado import ATACADO_PROMPT
from app.agent.prompts.private_label import PRIVATE_LABEL_PROMPT
from app.agent.prompts.exportacao import EXPORTACAO_PROMPT
from app.agent.prompts.consumo import CONSUMO_PROMPT
from app.agent.tools import get_tools_for_stage, execute_tool
from app.leads.service import get_history, save_message

logger = logging.getLogger(__name__)

openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

STAGE_PROMPTS = {
    "secretaria": SECRETARIA_PROMPT,
    "atacado": ATACADO_PROMPT,
    "private_label": PRIVATE_LABEL_PROMPT,
    "exportacao": EXPORTACAO_PROMPT,
    "consumo": CONSUMO_PROMPT,
}

STAGE_MODELS = {
    "secretaria": "gpt-4.1",
    "atacado": "gpt-4.1",
    "private_label": "gpt-4.1",
    "exportacao": "gpt-4.1-mini",
    "consumo": "gpt-4.1-mini",
}

# Brazil timezone
TZ_BR = timezone(timedelta(hours=-3))


def build_system_prompt(lead: dict) -> str:
    now = datetime.now(TZ_BR)
    stage = lead.get("stage", "secretaria")

    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
    )

    stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)

    return base + "\n\n" + stage_prompt


def build_messages(lead: dict, user_text: str) -> list[dict]:
    """Build the messages array for OpenAI from conversation history."""
    system_prompt = build_system_prompt(lead)
    history = get_history(lead["id"], limit=30)

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_text})

    return messages


async def run_agent(lead: dict, user_text: str) -> str:
    """Run the AI agent for a lead and return the response text."""
    stage = lead.get("stage", "secretaria")
    model = STAGE_MODELS.get(stage, "gpt-4.1")
    tools = get_tools_for_stage(stage)

    messages = build_messages(lead, user_text)

    # Save user message
    save_message(lead["id"], "user", user_text, stage)

    # Call OpenAI
    response = await openai_client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    message = response.choices[0].message

    # Process tool calls if any
    while message.tool_calls:
        # Add assistant message with tool calls
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            result = await execute_tool(
                func_name, func_args, lead["id"], lead["phone"]
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        # Call again to get the text response after tool execution
        response = await openai_client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )
        message = response.choices[0].message

    assistant_text = message.content or ""

    # Save assistant message
    save_message(lead["id"], "assistant", assistant_text, stage)

    logger.info(f"Agent response for {lead['phone']} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agent/orchestrator.py
git commit -m "feat: agent orchestrator - dynamic prompt builder + OpenAI with tool loop"
```

---

## Task 10: Buffer manager (Redis adaptive timer)

**Files:**
- Create: `backend/app/buffer/__init__.py`
- Create: `backend/app/buffer/manager.py`
- Create: `backend/app/buffer/processor.py`
- Create: `backend/tests/test_buffer.py`

- [ ] **Step 1: Create buffer/__init__.py**

```python
```

- [ ] **Step 2: Create manager.py**

```python
import asyncio
import logging

import redis.asyncio as aioredis

from app.config import settings
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)

# Track active timers per phone number
_active_timers: dict[str, asyncio.Task] = {}


async def push_to_buffer(r: aioredis.Redis, msg: IncomingMessage):
    """Push a message to the buffer. Start or extend the timer."""
    phone = msg.from_number
    buffer_key = f"buffer:{phone}"
    lock_key = f"buffer:{phone}:lock"

    # Determine text content (will be resolved later for media)
    text = msg.text or f"[{msg.type}: media_id={msg.media_id}]"

    # Push message to the list
    await r.rpush(buffer_key, text)

    # Check if timer is already active
    has_lock = await r.exists(lock_key)

    if has_lock:
        # Timer already running — extend it
        current_ttl = await r.ttl(lock_key)
        new_ttl = min(
            current_ttl + settings.buffer_extend_timeout,
            settings.buffer_max_timeout,
        )
        await r.expire(lock_key, new_ttl)
        logger.info(f"Buffer extended for {phone}: TTL now {new_ttl}s")
    else:
        # First message — set lock and start timer
        await r.set(lock_key, "1", ex=settings.buffer_base_timeout)
        logger.info(f"Buffer started for {phone}: {settings.buffer_base_timeout}s")

        # Start async timer
        if phone in _active_timers:
            _active_timers[phone].cancel()

        _active_timers[phone] = asyncio.create_task(
            _wait_and_flush(r, phone)
        )


async def _wait_and_flush(r: aioredis.Redis, phone: str):
    """Wait for the buffer to expire, then flush."""
    from app.buffer.processor import process_buffered_messages

    while True:
        await asyncio.sleep(1)
        lock_key = f"buffer:{phone}:lock"
        exists = await r.exists(lock_key)
        if not exists:
            break

    buffer_key = f"buffer:{phone}"

    # Get all messages
    messages = await r.lrange(buffer_key, 0, -1)
    await r.delete(buffer_key)

    # Clean up timer reference
    _active_timers.pop(phone, None)

    if messages:
        combined = "\n".join(messages)
        logger.info(f"Buffer flushed for {phone}: {len(messages)} messages")
        await process_buffered_messages(phone, combined)
```

- [ ] **Step 3: Create processor.py**

```python
import asyncio
import logging

from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.whatsapp.client import send_text
from app.whatsapp.media import transcribe_audio, describe_image

logger = logging.getLogger(__name__)


async def process_buffered_messages(phone: str, combined_text: str):
    """Process accumulated buffer messages: resolve media, run agent, humanize, send."""
    try:
        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text)

        # Get or create lead
        lead = get_or_create_lead(phone)

        # Activate lead if pending/template_sent
        if lead.get("status") in ("imported", "template_sent"):
            lead = activate_lead(lead["id"])

        # Run agent
        response = await run_agent(lead, resolved_text)

        # Humanize and send
        bubbles = split_into_bubbles(response)
        for bubble in bubbles:
            delay = calculate_typing_delay(bubble)
            await asyncio.sleep(delay)
            await send_text(phone, bubble)

        # Update last_msg timestamp
        from datetime import datetime, timezone
        update_lead(lead["id"], last_msg_at=datetime.now(timezone.utc).isoformat())

    except Exception as e:
        logger.error(f"Error processing messages for {phone}: {e}", exc_info=True)


async def _resolve_media(text: str) -> str:
    """Replace media placeholders with actual content."""
    import re

    # Pattern: [audio: media_id=xxx] or [image: media_id=xxx]
    audio_pattern = r"\[audio: media_id=(\S+)\]"
    image_pattern = r"\[image: media_id=(\S+)\]"

    for match in re.finditer(audio_pattern, text):
        media_id = match.group(1)
        try:
            transcription = await transcribe_audio(media_id)
            text = text.replace(match.group(0), f"[audio transcrito: {transcription}]")
        except Exception as e:
            logger.warning(f"Failed to transcribe audio {media_id}: {e}")
            text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_pattern, text):
        media_id = match.group(1)
        try:
            description = await describe_image(media_id)
            text = text.replace(match.group(0), f"[imagem recebida: {description}]")
        except Exception as e:
            logger.warning(f"Failed to describe image {media_id}: {e}")
            text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text
```

- [ ] **Step 4: Write buffer test**

```python
# backend/tests/test_buffer.py
import pytest
from app.humanizer.splitter import split_into_bubbles


def test_media_placeholder_format():
    """Verify media placeholder format matches what processor expects."""
    import re
    placeholder = "[audio: media_id=abc123]"
    pattern = r"\[audio: media_id=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "abc123"


def test_image_placeholder_format():
    import re
    placeholder = "[image: media_id=img456]"
    pattern = r"\[image: media_id=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "img456"
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_buffer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/buffer/ backend/tests/test_buffer.py
git commit -m "feat: Redis buffer manager with adaptive timer + message processor"
```

---

## Task 11: Leads API router

**Files:**
- Create: `backend/app/leads/router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create leads/router.py**

```python
from fastapi import APIRouter, Query
from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("")
async def list_leads(
    status: str | None = None,
    stage: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    sb = get_supabase()
    query = sb.table("leads").select("*")

    if status:
        query = query.eq("status", status)
    if stage:
        query = query.eq("stage", stage)

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": result.data, "count": len(result.data)}


@router.get("/{lead_id}")
async def get_lead(lead_id: str):
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).single().execute()
    return result.data


@router.get("/{lead_id}/messages")
async def get_lead_messages(lead_id: str, limit: int = Query(50, le=200)):
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("*")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return {"data": result.data}
```

- [ ] **Step 2: Register router in main.py**

Add to `backend/app/main.py`:

```python
from app.leads.router import router as leads_router

app.include_router(leads_router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/leads/router.py backend/app/main.py
git commit -m "feat: leads API - list, get, messages endpoints"
```

---

## Task 12: Campaign system (importer + router + worker)

**Files:**
- Create: `backend/app/campaign/__init__.py`
- Create: `backend/app/campaign/importer.py`
- Create: `backend/app/campaign/router.py`
- Create: `backend/app/campaign/worker.py`
- Create: `backend/tests/test_importer.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create campaign/__init__.py**

```python
```

- [ ] **Step 2: Create importer.py**

```python
import csv
import io
import re
from dataclasses import dataclass


@dataclass
class ImportResult:
    valid: list[str]
    invalid: list[str]


def normalize_phone(phone: str) -> str | None:
    """Normalize a Brazilian phone number to international format (5511999999999).
    Returns None if invalid.
    """
    digits = re.sub(r"\D", "", phone)

    # Remove leading +
    if digits.startswith("0"):
        digits = digits[1:]

    # Add country code if missing
    if len(digits) == 10 or len(digits) == 11:
        digits = "55" + digits
    elif len(digits) == 12 or len(digits) == 13:
        if not digits.startswith("55"):
            return None
    else:
        return None

    # Validate: 55 + 2 digit DDD + 8-9 digit number
    if len(digits) < 12 or len(digits) > 13:
        return None

    return digits


def parse_csv(file_content: str | bytes) -> ImportResult:
    """Parse a CSV file and extract valid phone numbers."""
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig")

    valid = []
    invalid = []

    reader = csv.reader(io.StringIO(file_content))
    header = next(reader, None)

    # Find phone column
    phone_col = 0
    if header:
        for i, col in enumerate(header):
            if col.strip().lower() in ("phone", "telefone", "numero", "whatsapp", "celular"):
                phone_col = i
                break

    for row in reader:
        if not row or len(row) <= phone_col:
            continue

        raw = row[phone_col].strip()
        if not raw:
            continue

        normalized = normalize_phone(raw)
        if normalized:
            valid.append(normalized)
        else:
            invalid.append(raw)

    return ImportResult(valid=valid, invalid=invalid)
```

- [ ] **Step 3: Write test for importer**

```python
# backend/tests/test_importer.py
from app.campaign.importer import normalize_phone, parse_csv


def test_normalize_full_number():
    assert normalize_phone("5534999999999") == "5534999999999"


def test_normalize_without_country():
    assert normalize_phone("34999999999") == "5534999999999"


def test_normalize_with_plus():
    assert normalize_phone("+5534999999999") == "5534999999999"


def test_normalize_with_formatting():
    assert normalize_phone("(34) 99999-9999") == "5534999999999"


def test_normalize_landline():
    assert normalize_phone("3432221111") == "553432221111"


def test_normalize_invalid():
    assert normalize_phone("123") is None
    assert normalize_phone("abcdefghij") is None


def test_parse_csv_basic():
    csv_content = "telefone\n5534999999999\n5534888888888\n"
    result = parse_csv(csv_content)
    assert len(result.valid) == 2
    assert result.valid[0] == "5534999999999"


def test_parse_csv_with_invalid():
    csv_content = "phone\n5534999999999\n123\n"
    result = parse_csv(csv_content)
    assert len(result.valid) == 1
    assert len(result.invalid) == 1
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_importer.py -v`
Expected: PASS

- [ ] **Step 5: Create router.py**

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.campaign.importer import parse_csv

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    template_name: str
    template_params: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8


@router.get("")
async def list_campaigns():
    sb = get_supabase()
    result = sb.table("campaigns").select("*").order("created_at", desc=True).execute()
    return {"data": result.data}


@router.post("")
async def create_campaign(campaign: CampaignCreate):
    sb = get_supabase()
    result = sb.table("campaigns").insert(campaign.model_dump()).execute()
    return result.data[0]


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    sb = get_supabase()
    result = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute()
    return result.data


@router.post("/{campaign_id}/import")
async def import_leads(campaign_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()

    # Create leads (ignore duplicates)
    created = 0
    for phone in result.valid:
        try:
            sb.table("leads").insert({
                "phone": phone,
                "campaign_id": campaign_id,
                "status": "imported",
                "stage": "pending",
            }).execute()
            created += 1
        except Exception:
            # Duplicate phone, skip
            pass

    # Update campaign total
    sb.table("campaigns").update({"total_leads": created}).eq("id", campaign_id).execute()

    return {
        "imported": created,
        "invalid": len(result.invalid),
        "invalid_numbers": result.invalid[:20],
    }


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str):
    sb = get_supabase()

    # Get campaign
    campaign = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute().data

    if campaign["status"] == "running":
        raise HTTPException(400, "Campanha ja esta rodando")

    # Get leads for this campaign that haven't been sent
    leads = (
        sb.table("leads")
        .select("id, phone")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .execute()
        .data
    )

    if not leads:
        raise HTTPException(400, "Nenhum lead pendente para envio")

    # Enqueue leads in Redis (done by worker polling, or push to Redis list)
    # For simplicity, update campaign status — worker picks up from there
    sb.table("campaigns").update({"status": "running"}).eq("id", campaign_id).execute()

    return {"status": "started", "leads_queued": len(leads)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    sb = get_supabase()
    sb.table("campaigns").update({"status": "paused"}).eq("id", campaign_id).execute()
    return {"status": "paused"}
```

- [ ] **Step 6: Create worker.py**

```python
import asyncio
import logging
import random

from app.config import settings
from app.db.supabase import get_supabase
from app.whatsapp.client import send_template

logger = logging.getLogger(__name__)


async def run_worker():
    """Main worker loop: polls for running campaigns and sends templates."""
    logger.info("Campaign worker started")

    while True:
        try:
            await process_campaigns()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)


async def process_campaigns():
    """Find running campaigns and send pending templates."""
    sb = get_supabase()

    # Get running campaigns
    campaigns = (
        sb.table("campaigns")
        .select("*")
        .eq("status", "running")
        .execute()
        .data
    )

    for campaign in campaigns:
        await process_single_campaign(campaign)


async def process_single_campaign(campaign: dict):
    """Process one campaign: send templates to pending leads."""
    sb = get_supabase()
    campaign_id = campaign["id"]

    # Get next batch of unsent leads
    leads = (
        sb.table("leads")
        .select("id, phone")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .limit(10)
        .execute()
        .data
    )

    if not leads:
        # All done — mark campaign as completed
        sb.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute()
        logger.info(f"Campaign {campaign_id} completed")
        return

    for lead in leads:
        # Check if campaign is still running (might have been paused)
        current = sb.table("campaigns").select("status").eq("id", campaign_id).single().execute().data
        if current["status"] != "running":
            logger.info(f"Campaign {campaign_id} paused, stopping")
            return

        try:
            await send_template(
                to=lead["phone"],
                template_name=campaign["template_name"],
                components=campaign.get("template_params", {}).get("components"),
            )
            sb.table("leads").update({"status": "template_sent"}).eq("id", lead["id"]).execute()

            # Update sent counter
            sb.rpc("increment_campaign_sent", {"campaign_id_param": campaign_id}).execute()
            logger.info(f"Template sent to {lead['phone']}")

        except Exception as e:
            logger.error(f"Failed to send to {lead['phone']}: {e}")
            sb.table("leads").update({"status": "failed"}).eq("id", lead["id"]).execute()

        # Wait between sends (randomized interval)
        interval = random.randint(
            campaign.get("send_interval_min", 3),
            campaign.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
```

- [ ] **Step 7: Register campaign router in main.py**

Add to `backend/app/main.py`:

```python
from app.campaign.router import router as campaign_router

app.include_router(campaign_router)
```

- [ ] **Step 8: Commit**

```bash
git add backend/app/campaign/ backend/tests/test_importer.py backend/app/main.py
git commit -m "feat: campaign system - CSV importer, API routes, template dispatch worker"
```

---

## Task 13: Supabase SQL migrations

**Files:**
- Create: `backend/migrations/001_initial.sql`

- [ ] **Step 1: Create migration file**

```sql
-- 001_initial.sql
-- Run this in Supabase SQL Editor

-- Campaigns table (must exist before leads due to FK)
CREATE TABLE IF NOT EXISTS campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    template_name text NOT NULL,
    template_params jsonb,
    total_leads int DEFAULT 0,
    sent int DEFAULT 0,
    failed int DEFAULT 0,
    replied int DEFAULT 0,
    status text DEFAULT 'draft',
    send_interval_min int DEFAULT 3,
    send_interval_max int DEFAULT 8,
    created_at timestamptz DEFAULT now()
);

-- Leads table
CREATE TABLE IF NOT EXISTS leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone text UNIQUE NOT NULL,
    name text,
    company text,
    stage text DEFAULT 'pending',
    status text DEFAULT 'imported',
    campaign_id uuid REFERENCES campaigns(id),
    last_msg_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Messages table (unified history)
CREATE TABLE IF NOT EXISTS messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    stage text,
    created_at timestamptz DEFAULT now()
);

-- Templates table (mirror of Meta approved templates)
CREATE TABLE IF NOT EXISTS templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_id text,
    name text NOT NULL,
    language text DEFAULT 'pt_BR',
    category text,
    body_text text,
    status text,
    synced_at timestamptz
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_messages_lead_id ON messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

-- RPC for atomic counter increment (used by worker)
CREATE OR REPLACE FUNCTION increment_campaign_sent(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET sent = sent + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;

-- RPC for incrementing replied counter
CREATE OR REPLACE FUNCTION increment_campaign_replied(campaign_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE campaigns SET replied = replied + 1 WHERE id = campaign_id_param;
END;
$$ LANGUAGE plpgsql;
```

- [ ] **Step 2: Commit**

```bash
git add backend/migrations/
git commit -m "feat: Supabase SQL migration - tables, indexes, RPC functions"
```

---

## Task 14: Wire everything together and final main.py

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Final main.py**

```python
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    yield
    await app.state.redis.close()


app = FastAPI(title="ValerIA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.campaign.router import router as campaign_router

app.include_router(webhook_router)
app.include_router(leads_router)
app.include_router(campaign_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: Verify all __init__.py files exist**

Ensure these empty files exist:
- `backend/app/__init__.py`
- `backend/app/db/__init__.py`
- `backend/app/webhook/__init__.py`
- `backend/app/whatsapp/__init__.py`
- `backend/app/buffer/__init__.py`
- `backend/app/humanizer/__init__.py`
- `backend/app/agent/__init__.py`
- `backend/app/agent/prompts/__init__.py`
- `backend/app/leads/__init__.py`
- `backend/app/campaign/__init__.py`
- `backend/tests/__init__.py`

- [ ] **Step 3: Run all tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add backend/
git commit -m "feat: wire all components together - final main.py with all routers"
```

---

## Summary

| Task | Component | Key Files |
|---|---|---|
| 1 | Project scaffold | config.py, main.py, Docker, requirements |
| 2 | Supabase + lead service | db/supabase.py, leads/service.py |
| 3 | WhatsApp client | whatsapp/client.py |
| 4 | Webhook receiver | webhook/router.py, webhook/parser.py |
| 5 | Media processing | whatsapp/media.py |
| 6 | Humanizer | humanizer/splitter.py, humanizer/typing.py |
| 7 | Agent prompts | agent/prompts/*.py |
| 8 | Agent tools | agent/tools.py |
| 9 | Agent orchestrator | agent/orchestrator.py |
| 10 | Buffer system | buffer/manager.py, buffer/processor.py |
| 11 | Leads API | leads/router.py |
| 12 | Campaign system | campaign/router.py, importer.py, worker.py |
| 13 | SQL migrations | migrations/001_initial.sql |
| 14 | Final wiring | main.py (final version) |
