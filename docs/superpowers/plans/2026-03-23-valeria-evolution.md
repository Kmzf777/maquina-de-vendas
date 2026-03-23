# ValerIA Evolution API Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a `backend-evolution/` folder that clones the existing ValerIA backend but replaces the Meta Cloud API layer with Evolution API v2 for WhatsApp messaging, so the agent can be tested immediately.

**Architecture:** Copy all shared modules (agent, buffer, humanizer, leads, campaign, db) unchanged. Replace only the WhatsApp-specific layers: config (Evolution credentials), webhook parser (Evolution payload format), webhook router (simpler, no Meta verification), WhatsApp client (Evolution REST endpoints), and media handler (Evolution media download).

**Tech Stack:** Python 3.12, FastAPI, Redis, Supabase, OpenAI SDK, httpx, Evolution API v2.3.x

**Spec:** Design approved in brainstorming session (2026-03-23)

---

## File Map

| File | Responsibility | Changed vs Meta? |
|---|---|---|
| `backend-evolution/app/__init__.py` | Package marker | Same |
| `backend-evolution/app/config.py` | Settings with Evolution env vars | **Changed** |
| `backend-evolution/app/main.py` | FastAPI app, routers, lifespan | Same |
| `backend-evolution/app/db/supabase.py` | Supabase client | Same |
| `backend-evolution/app/whatsapp/client.py` | Evolution API: send_text, send_template, send_image, mark_read | **Changed** |
| `backend-evolution/app/whatsapp/media.py` | Download media via Evolution, transcribe/describe | **Changed** |
| `backend-evolution/app/webhook/router.py` | POST /webhook (Evolution format, no GET verify) | **Changed** |
| `backend-evolution/app/webhook/parser.py` | Parse Evolution MESSAGES_UPSERT payload | **Changed** |
| `backend-evolution/app/buffer/*` | Redis buffer (identical) | Same |
| `backend-evolution/app/agent/*` | Orchestrator + prompts + tools (identical) | Same |
| `backend-evolution/app/humanizer/*` | Splitter + typing (identical) | Same |
| `backend-evolution/app/leads/*` | Service + router (identical) | Same |
| `backend-evolution/app/campaign/*` | Importer + router + worker (identical) | Same |
| `backend-evolution/app/requirements.txt` | Dependencies (same) | Same |
| `backend-evolution/.env.example` | Evolution env vars | **Changed** |
| `backend-evolution/Dockerfile` | Docker image | Same |
| `backend-evolution/docker-compose.yml` | Compose (api + worker + redis) | Same |
| `backend-evolution/tests/*` | Tests for changed modules | **Changed** |

---

## Task 1: Copy backend and update config

**Files:**
- Create: `backend-evolution/` (copy from `backend/`)
- Modify: `backend-evolution/app/config.py`
- Modify: `backend-evolution/.env.example`

- [ ] **Step 1: Copy backend folder**

```bash
cp -r backend backend-evolution
```

- [ ] **Step 2: Update .env.example**

```env
# Evolution API
EVOLUTION_API_URL=https://your-evolution-instance.com
EVOLUTION_API_KEY=your-api-key
EVOLUTION_INSTANCE=your-instance-name

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

- [ ] **Step 3: Update config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Evolution API
    evolution_api_url: str
    evolution_api_key: str
    evolution_instance: str

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


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()  # type: ignore
```

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/
git commit -m "feat: clone backend for Evolution API variant with updated config"
```

---

## Task 2: WhatsApp client (Evolution API v2)

**Files:**
- Modify: `backend-evolution/app/whatsapp/client.py`
- Create: `backend-evolution/tests/test_whatsapp_client.py`

- [ ] **Step 1: Rewrite client.py for Evolution API**

```python
import httpx

from app.config import settings


def _base_url() -> str:
    return settings.evolution_api_url.rstrip("/")


def _headers() -> dict:
    return {
        "apikey": settings.evolution_api_key,
        "Content-Type": "application/json",
    }


def _instance() -> str:
    return settings.evolution_instance


async def _post(path: str, payload: dict) -> dict:
    url = f"{_base_url()}{path}/{_instance()}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def send_text(to: str, body: str) -> dict:
    return await _post("/message/sendText", {
        "number": to,
        "text": body,
    })


async def send_template(to: str, template_name: str, language: str = "pt_BR", components: list | None = None) -> dict:
    """Evolution API doesn't have Meta-style templates.
    Send as regular text message instead.
    """
    # Templates are a Meta concept - in Evolution we just send text directly
    # The campaign worker will need to send the template text as a regular message
    return await send_text(to, f"[Template: {template_name}]")


async def send_image(to: str, image_url: str, caption: str | None = None) -> dict:
    return await _post("/message/sendMedia", {
        "number": to,
        "mediatype": "image",
        "mimetype": "image/jpeg",
        "caption": caption or "",
        "media": image_url,
        "fileName": "image.jpg",
    })


async def send_audio(to: str, audio_url: str) -> dict:
    return await _post("/message/sendWhatsAppAudio", {
        "number": to,
        "audio": audio_url,
    })


async def mark_read(message_id: str, remote_jid: str) -> dict:
    """Mark a message as read in Evolution API."""
    return await _post("/chat/markMessageAsRead", {
        "readMessages": [
            {
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }
        ],
    })
```

- [ ] **Step 2: Write test**

```python
# backend-evolution/tests/test_whatsapp_client.py
import pytest
import httpx

from app.whatsapp import client


@pytest.fixture
def mock_evolution_api(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "https://evo.test.com")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-key")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "test-instance")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    # Reset cached settings
    import app.config
    app.config._settings = None

    captured = {}

    async def fake_post(self, url, json=None, headers=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(201, json={"key": {"id": "msg123"}})

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    return captured


@pytest.mark.asyncio
async def test_send_text(mock_evolution_api):
    result = await client.send_text("5534999999999", "oi, tudo bem?")
    assert "/message/sendText/test-instance" in mock_evolution_api["url"]
    assert mock_evolution_api["json"]["number"] == "5534999999999"
    assert mock_evolution_api["json"]["text"] == "oi, tudo bem?"
    assert mock_evolution_api["headers"]["apikey"] == "test-key"


@pytest.mark.asyncio
async def test_send_image(mock_evolution_api):
    result = await client.send_image("5534999999999", "https://img.com/cafe.jpg", "nosso cafe")
    assert "/message/sendMedia/test-instance" in mock_evolution_api["url"]
    assert mock_evolution_api["json"]["mediatype"] == "image"
    assert mock_evolution_api["json"]["caption"] == "nosso cafe"
```

- [ ] **Step 3: Run tests**

Run: `cd backend-evolution && python -m pytest tests/test_whatsapp_client.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/app/whatsapp/client.py backend-evolution/tests/test_whatsapp_client.py
git commit -m "feat(evolution): WhatsApp client for Evolution API v2 (sendText, sendMedia, markRead)"
```

---

## Task 3: Webhook parser (Evolution MESSAGES_UPSERT format)

**Files:**
- Modify: `backend-evolution/app/webhook/parser.py`
- Modify: `backend-evolution/tests/test_webhook_parser.py`

- [ ] **Step 1: Rewrite parser.py for Evolution format**

The Evolution API v2 MESSAGES_UPSERT payload format:
```json
{
  "event": "messages.upsert",
  "instance": "instance-name",
  "data": {
    "key": {
      "remoteJid": "5534999999999@s.whatsapp.net",
      "fromMe": false,
      "id": "3EB0BF8072876BE899FE20"
    },
    "pushName": "Joao",
    "status": "SERVER_ACK",
    "message": {
      "conversation": "oi, quero saber dos cafes"
    },
    "messageType": "conversation",
    "messageTimestamp": 1764253714,
    "source": "web"
  }
}
```

For audio messages:
```json
{
  "data": {
    "key": { "remoteJid": "...@s.whatsapp.net", "fromMe": false, "id": "..." },
    "message": {
      "audioMessage": {
        "url": "https://...",
        "mimetype": "audio/ogg; codecs=opus",
        "fileSha256": "...",
        "fileLength": "12345",
        "mediaKey": "..."
      }
    },
    "messageType": "audioMessage"
  }
}
```

For image messages:
```json
{
  "data": {
    "key": { "remoteJid": "...@s.whatsapp.net", "fromMe": false, "id": "..." },
    "message": {
      "imageMessage": {
        "url": "https://...",
        "mimetype": "image/jpeg",
        "caption": "olha isso",
        "mediaKey": "..."
      }
    },
    "messageType": "imageMessage"
  }
}
```

```python
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    from_number: str
    remote_jid: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, video, document
    text: str | None = None
    media_url: str | None = None
    media_mime: str | None = None
    push_name: str | None = None


def parse_webhook_payload(payload: dict) -> list[IncomingMessage]:
    """Parse Evolution API v2 MESSAGES_UPSERT webhook payload."""
    messages = []

    event = payload.get("event", "")
    if event != "messages.upsert":
        return messages

    data = payload.get("data", {})
    key = data.get("key", {})

    # Skip messages from ourselves
    if key.get("fromMe", False):
        return messages

    remote_jid = key.get("remoteJid", "")
    # Extract phone number from JID (5534999999999@s.whatsapp.net -> 5534999999999)
    from_number = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    message_id = key.get("id", "")
    timestamp = str(data.get("messageTimestamp", ""))
    push_name = data.get("pushName")
    message_type = data.get("messageType", "")
    message_data = data.get("message", {})

    text = None
    media_url = None
    media_mime = None
    msg_type = "text"

    # Text messages
    if message_type == "conversation":
        text = message_data.get("conversation")
    elif message_type == "extendedTextMessage":
        text = message_data.get("extendedTextMessage", {}).get("text")

    # Audio messages
    elif message_type == "audioMessage":
        msg_type = "audio"
        audio = message_data.get("audioMessage", {})
        media_url = audio.get("url")
        media_mime = audio.get("mimetype")

    # Image messages
    elif message_type == "imageMessage":
        msg_type = "image"
        image = message_data.get("imageMessage", {})
        media_url = image.get("url")
        media_mime = image.get("mimetype")
        text = image.get("caption")

    # Video messages
    elif message_type == "videoMessage":
        msg_type = "video"
        video = message_data.get("videoMessage", {})
        media_url = video.get("url")
        media_mime = video.get("mimetype")
        text = video.get("caption")

    # Document messages
    elif message_type == "documentMessage":
        msg_type = "document"
        doc = message_data.get("documentMessage", {})
        media_url = doc.get("url")
        media_mime = doc.get("mimetype")
        text = doc.get("caption")

    else:
        # Unknown type - try to extract any text
        text = message_data.get("conversation") or message_data.get("extendedTextMessage", {}).get("text")
        if not text:
            return messages  # Skip unknown non-text messages

    messages.append(IncomingMessage(
        from_number=from_number,
        remote_jid=remote_jid,
        message_id=message_id,
        timestamp=timestamp,
        type=msg_type,
        text=text,
        media_url=media_url,
        media_mime=media_mime,
        push_name=push_name,
    ))

    return messages
```

- [ ] **Step 2: Rewrite tests**

```python
# backend-evolution/tests/test_webhook_parser.py
from app.webhook.parser import parse_webhook_payload


def test_parse_text_message():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "3EB0BF8072876BE899FE20"
            },
            "pushName": "Joao",
            "message": {
                "conversation": "oi, quero saber dos cafes"
            },
            "messageType": "conversation",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].from_number == "5534999999999"
    assert msgs[0].remote_jid == "5534999999999@s.whatsapp.net"
    assert msgs[0].type == "text"
    assert msgs[0].text == "oi, quero saber dos cafes"
    assert msgs[0].push_name == "Joao"


def test_parse_audio_message():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "msg456"
            },
            "message": {
                "audioMessage": {
                    "url": "https://evo.com/audio/123",
                    "mimetype": "audio/ogg; codecs=opus"
                }
            },
            "messageType": "audioMessage",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "audio"
    assert msgs[0].media_url == "https://evo.com/audio/123"


def test_parse_image_with_caption():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "msg789"
            },
            "message": {
                "imageMessage": {
                    "url": "https://evo.com/img/456",
                    "mimetype": "image/jpeg",
                    "caption": "olha esse cafe"
                }
            },
            "messageType": "imageMessage",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "image"
    assert msgs[0].text == "olha esse cafe"
    assert msgs[0].media_url == "https://evo.com/img/456"


def test_skip_from_me():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": True,
                "id": "msg999"
            },
            "message": {"conversation": "oi"},
            "messageType": "conversation",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert msgs == []


def test_skip_non_messages_upsert():
    payload = {
        "event": "connection.update",
        "instance": "test",
        "data": {"state": "open"}
    }

    msgs = parse_webhook_payload(payload)
    assert msgs == []


def test_parse_extended_text():
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
                "id": "msgext"
            },
            "message": {
                "extendedTextMessage": {
                    "text": "mensagem com link https://example.com"
                }
            },
            "messageType": "extendedTextMessage",
            "messageTimestamp": 1764253714,
        }
    }

    msgs = parse_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].text == "mensagem com link https://example.com"
```

- [ ] **Step 3: Run tests**

Run: `cd backend-evolution && python -m pytest tests/test_webhook_parser.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend-evolution/app/webhook/parser.py backend-evolution/tests/test_webhook_parser.py
git commit -m "feat(evolution): webhook parser for Evolution API v2 MESSAGES_UPSERT format"
```

---

## Task 4: Webhook router (Evolution API)

**Files:**
- Modify: `backend-evolution/app/webhook/router.py`

- [ ] **Step 1: Rewrite router.py**

Evolution API doesn't need the GET verify endpoint. It just POSTs to the webhook URL. We also need to pass `remote_jid` to `mark_read`.

```python
import logging

from fastapi import APIRouter, Request

from app.webhook.parser import parse_webhook_payload
from app.whatsapp.client import mark_read
from app.buffer.manager import push_to_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def receive_webhook(request: Request):
    payload = await request.json()

    logger.info(f"Webhook event: {payload.get('event', 'unknown')}")

    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}, text={msg.text[:50] if msg.text else 'N/A'}")

        # Mark as read
        try:
            await mark_read(msg.message_id, msg.remote_jid)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Push to buffer for processing
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/webhook/router.py
git commit -m "feat(evolution): simplified webhook router (no Meta verification needed)"
```

---

## Task 5: Media processing (Evolution API)

**Files:**
- Modify: `backend-evolution/app/whatsapp/media.py`

- [ ] **Step 1: Rewrite media.py**

In Evolution API, media URLs are provided directly in the webhook payload (no need to call a separate endpoint to get the download URL like Meta). We just download from the URL directly.

```python
import httpx
from openai import AsyncOpenAI

from app.config import settings

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def download_media(media_url: str) -> tuple[bytes, str]:
    """Download media from URL. Returns (bytes, content_type)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def transcribe_audio(media_url: str) -> str:
    """Download audio and transcribe with Whisper."""
    audio_bytes, content_type = await download_media(media_url)

    ext = "ogg" if "ogg" in content_type else "mp4"
    transcript = await _get_openai().audio.transcriptions.create(
        model="whisper-1",
        file=(f"audio.{ext}", audio_bytes, content_type),
    )
    return transcript.text


async def describe_image(media_url: str) -> str:
    """Download image and describe with GPT-4o Vision."""
    import base64

    image_bytes, content_type = await download_media(media_url)
    b64 = base64.b64encode(image_bytes).decode()

    response = await _get_openai().chat.completions.create(
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
git add backend-evolution/app/whatsapp/media.py
git commit -m "feat(evolution): media processing with direct URL download (no Meta media ID)"
```

---

## Task 6: Update buffer manager for Evolution format

**Files:**
- Modify: `backend-evolution/app/buffer/manager.py`
- Modify: `backend-evolution/app/buffer/processor.py`

- [ ] **Step 1: Update manager.py**

The `IncomingMessage` now has `media_url` instead of `media_id`, and includes `push_name`. Update the buffer to use `media_url`.

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
    if msg.text:
        text = msg.text
    elif msg.media_url:
        text = f"[{msg.type}: media_url={msg.media_url}]"
    else:
        text = f"[{msg.type}: sem conteudo]"

    # Save push_name for later use
    if msg.push_name:
        await r.set(f"pushname:{phone}", msg.push_name, ex=86400)

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

- [ ] **Step 2: Update processor.py**

Change media resolution to use `media_url` instead of `media_id`.

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

    # Pattern: [audio: media_url=xxx] or [image: media_url=xxx]
    audio_pattern = r"\[audio: media_url=(\S+)\]"
    image_pattern = r"\[image: media_url=(\S+)\]"

    for match in re.finditer(audio_pattern, text):
        media_url = match.group(1)
        try:
            transcription = await transcribe_audio(media_url)
            text = text.replace(match.group(0), f"[audio transcrito: {transcription}]")
        except Exception as e:
            logger.warning(f"Failed to transcribe audio: {e}")
            text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_pattern, text):
        media_url = match.group(1)
        try:
            description = await describe_image(media_url)
            text = text.replace(match.group(0), f"[imagem recebida: {description}]")
        except Exception as e:
            logger.warning(f"Failed to describe image: {e}")
            text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text
```

- [ ] **Step 3: Update test_buffer.py**

```python
# backend-evolution/tests/test_buffer.py
import re


def test_media_placeholder_format():
    """Verify media placeholder format matches what processor expects."""
    placeholder = "[audio: media_url=https://evo.com/audio/123]"
    pattern = r"\[audio: media_url=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "https://evo.com/audio/123"


def test_image_placeholder_format():
    placeholder = "[image: media_url=https://evo.com/img/456]"
    pattern = r"\[image: media_url=(\S+)\]"
    match = re.search(pattern, placeholder)
    assert match is not None
    assert match.group(1) == "https://evo.com/img/456"
```

- [ ] **Step 4: Run tests**

Run: `cd backend-evolution && python -m pytest tests/test_buffer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend-evolution/app/buffer/ backend-evolution/tests/test_buffer.py
git commit -m "feat(evolution): update buffer to use media_url instead of media_id"
```

---

## Task 7: Run all tests and final verification

- [ ] **Step 1: Run all tests**

Run: `cd backend-evolution && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Commit any remaining fixes**

```bash
git add backend-evolution/
git commit -m "feat(evolution): complete Evolution API backend variant - all tests passing"
```

---

## Task 8: Quickstart tutorial

- [ ] **Step 1: Create QUICKSTART.md inside backend-evolution**

Create `backend-evolution/QUICKSTART.md` with step-by-step instructions for running the agent locally and configuring the Evolution API webhook.

Content should cover:
1. Prerequisites (Python 3.12, Redis, Evolution API running)
2. Clone and install dependencies
3. Configure .env
4. Set up Supabase tables (run migration SQL)
5. Start Redis
6. Start the backend
7. Configure Evolution webhook to point to the backend
8. Test by sending a WhatsApp message

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/QUICKSTART.md
git commit -m "docs: add quickstart tutorial for Evolution API backend"
```

---

## Summary

| Task | Component | What Changes |
|---|---|---|
| 1 | Config + scaffold | Copy backend, replace Meta env vars with Evolution vars |
| 2 | WhatsApp client | Evolution API v2 endpoints (sendText, sendMedia, markRead) |
| 3 | Webhook parser | Parse MESSAGES_UPSERT format instead of Meta format |
| 4 | Webhook router | Remove GET verify, simplify POST handler |
| 5 | Media processing | Direct URL download instead of Meta media ID |
| 6 | Buffer manager | Use media_url placeholders instead of media_id |
| 7 | Final tests | Run all tests, verify everything works |
| 8 | Quickstart | Tutorial for running and testing |
