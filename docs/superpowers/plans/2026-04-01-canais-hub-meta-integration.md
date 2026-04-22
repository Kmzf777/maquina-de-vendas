# Canais Hub + Meta Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate channel management into /canais, add Meta Cloud API webhook support to backend, remove out-of-scope pages.

**Architecture:** Backend-evolution gets two new webhook endpoints (Evolution + Meta), a multi-provider WhatsApp client abstraction, and channel-aware message routing. CRM removes /agentes page, WhatsApp config tab, and refactors /canais to be the central hub with QR code connection and Meta credential management.

**Tech Stack:** FastAPI (Python), Next.js (TypeScript/React), Supabase, Evolution API, Meta Cloud API, Redis

---

## File Map

### Backend — New Files
- `backend-evolution/app/whatsapp/base.py` — Abstract WhatsApp client interface
- `backend-evolution/app/whatsapp/evolution.py` — Evolution API client (extracted from current client.py)
- `backend-evolution/app/whatsapp/meta.py` — Meta Cloud API client
- `backend-evolution/app/whatsapp/factory.py` — Client factory from channel config
- `backend-evolution/app/webhook/meta_parser.py` — Meta Cloud API payload parser
- `backend-evolution/app/webhook/meta_router.py` — Meta webhook endpoint
- `backend-evolution/app/channels/service.py` — Channel lookup from DB

### Backend — Modified Files
- `backend-evolution/app/config.py` — Make Evolution env vars optional
- `backend-evolution/app/main.py` — Register new routers
- `backend-evolution/app/webhook/router.py` — Refactor to channel-aware routing
- `backend-evolution/app/webhook/parser.py` — Add `channel_id` to IncomingMessage
- `backend-evolution/app/buffer/manager.py` — Pass channel_id through buffer
- `backend-evolution/app/buffer/processor.py` — Use channel-aware client for sending
- `backend-evolution/app/agent/orchestrator.py` — Accept channel + agent_profile context
- `backend-evolution/app/whatsapp/client.py` — Keep as thin backward-compat wrapper, delegates to evolution.py

### CRM — New Files
- `crm/src/app/api/channels/[id]/connect/route.ts` — Per-channel Evolution connect proxy
- `crm/src/app/api/channels/[id]/status/route.ts` — Per-channel Evolution status proxy
- `crm/src/app/api/channels/[id]/disconnect/route.ts` — Per-channel Evolution disconnect proxy

### CRM — Modified Files
- `crm/src/app/(authenticated)/canais/page.tsx` — Full refactor with QR code, Meta fields
- `crm/src/app/(authenticated)/config/page.tsx` — Remove WhatsApp tab
- `crm/src/components/sidebar.tsx` — Remove Agentes nav item

### CRM — Deleted Files
- `crm/src/app/(authenticated)/agentes/page.tsx`
- `crm/src/components/config/whatsapp-tab.tsx`
- `crm/src/app/api/evolution/connect/route.ts`
- `crm/src/app/api/evolution/status/route.ts`
- `crm/src/app/api/evolution/disconnect/route.ts`
- `crm/src/app/api/agent-profiles/route.ts` (POST removed, GET kept — see Task 8)

---

## Task 1: Channel Lookup Service

**Files:**
- Create: `backend-evolution/app/channels/service.py`

- [ ] **Step 1: Create channels service**

```python
# backend-evolution/app/channels/service.py
import logging
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def get_channel_by_phone(phone: str, provider: str) -> dict | None:
    """Find a channel by phone number and provider."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq("phone", phone)
        .eq("provider", provider)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_channel_by_provider_config(key: str, value: str, provider: str) -> dict | None:
    """Find a channel by a key inside provider_config JSON."""
    sb = get_supabase()
    # Supabase supports JSON arrow operator
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq(f"provider_config->>{ key }", value)
        .eq("provider", provider)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_channel_by_id(channel_id: str) -> dict | None:
    """Get a channel by its ID."""
    sb = get_supabase()
    res = (
        sb.table("channels")
        .select("*, agent_profiles(*)")
        .eq("id", channel_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def update_channel_phone(channel_id: str, phone: str) -> None:
    """Update a channel's phone number (e.g., after Evolution QR scan)."""
    sb = get_supabase()
    sb.table("channels").update({"phone": phone}).eq("id", channel_id).execute()
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/channels/service.py
git commit -m "feat: add channel lookup service for multi-channel routing"
```

---

## Task 2: WhatsApp Client Abstraction

**Files:**
- Create: `backend-evolution/app/whatsapp/base.py`
- Create: `backend-evolution/app/whatsapp/evolution.py`
- Create: `backend-evolution/app/whatsapp/meta.py`
- Create: `backend-evolution/app/whatsapp/factory.py`

- [ ] **Step 1: Create abstract base client**

```python
# backend-evolution/app/whatsapp/base.py
from abc import ABC, abstractmethod


class WhatsAppClient(ABC):
    """Abstract interface for WhatsApp message sending."""

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict:
        ...

    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        ...

    @abstractmethod
    async def send_audio(self, to: str, audio_url: str) -> dict:
        ...

    @abstractmethod
    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        ...
```

- [ ] **Step 2: Create Evolution client class**

Extract from current `client.py` into a class:

```python
# backend-evolution/app/whatsapp/evolution.py
import httpx
from app.whatsapp.base import WhatsAppClient


class EvolutionClient(WhatsAppClient):
    def __init__(self, api_url: str, api_key: str, instance: str):
        self.base_url = api_url.rstrip("/")
        self.api_key = api_key
        self.instance = instance

    def _headers(self) -> dict:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}/{self.instance}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post("/message/sendText", {
            "number": to,
            "text": body,
        })

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        return await self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "caption": caption or "",
            "media": image_url,
            "fileName": "image.jpg",
        })

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        return await self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "image",
            "mimetype": mimetype,
            "caption": caption or "",
            "media": base64_data,
            "fileName": "image.jpg" if "jpeg" in mimetype else "image.png",
        })

    async def send_audio(self, to: str, audio_url: str) -> dict:
        return await self._post("/message/sendWhatsAppAudio", {
            "number": to,
            "audio": audio_url,
        })

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post("/chat/markMessageAsRead", {
            "readMessages": [{
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }],
        })
```

- [ ] **Step 3: Create Meta Cloud client class**

```python
# backend-evolution/app/whatsapp/meta.py
import httpx
from app.whatsapp.base import WhatsAppClient

META_API_BASE = "https://graph.facebook.com/v21.0"


class MetaCloudClient(WhatsAppClient):
    def __init__(self, phone_number_id: str, access_token: str):
        self.phone_number_id = phone_number_id
        self.access_token = access_token

    def _url(self) -> str:
        return f"{META_API_BASE}/{self.phone_number_id}/messages"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url(), json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        })

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload)

    async def send_audio(self, to: str, audio_url: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        })

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })
```

- [ ] **Step 4: Create factory function**

```python
# backend-evolution/app/whatsapp/factory.py
from app.whatsapp.base import WhatsAppClient
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient


def get_whatsapp_client(channel: dict) -> WhatsAppClient:
    """Instantiate the correct WhatsApp client based on channel provider."""
    provider = channel["provider"]
    config = channel.get("provider_config", {})

    if provider == "evolution":
        return EvolutionClient(
            api_url=config["api_url"],
            api_key=config["api_key"],
            instance=config["instance"],
        )
    elif provider == "meta_cloud":
        return MetaCloudClient(
            phone_number_id=config["phone_number_id"],
            access_token=config["access_token"],
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
```

- [ ] **Step 5: Commit**

```bash
git add backend-evolution/app/whatsapp/base.py backend-evolution/app/whatsapp/evolution.py backend-evolution/app/whatsapp/meta.py backend-evolution/app/whatsapp/factory.py
git commit -m "feat: add multi-provider WhatsApp client abstraction (Evolution + Meta)"
```

---

## Task 3: Meta Cloud Webhook Parser

**Files:**
- Create: `backend-evolution/app/webhook/meta_parser.py`

- [ ] **Step 1: Create Meta parser**

```python
# backend-evolution/app/webhook/meta_parser.py
import logging
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)


def parse_meta_webhook_payload(payload: dict) -> list[IncomingMessage]:
    """Parse Meta Cloud API webhook payload into IncomingMessage list."""
    messages = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            if value.get("messaging_product") != "whatsapp":
                continue

            # Get the phone_number_id that received this message
            metadata = value.get("metadata", {})
            display_phone = metadata.get("display_phone_number", "")

            for msg in value.get("messages", []):
                from_number = msg.get("from", "")
                message_id = msg.get("id", "")
                timestamp = msg.get("timestamp", "")
                msg_type = msg.get("type", "")

                # Extract contact name if available
                contacts = value.get("contacts", [])
                push_name = None
                if contacts:
                    profile = contacts[0].get("profile", {})
                    push_name = profile.get("name")

                text = None
                media_url = None
                media_mime = None
                parsed_type = "text"

                if msg_type == "text":
                    text = msg.get("text", {}).get("body")

                elif msg_type == "image":
                    parsed_type = "image"
                    image = msg.get("image", {})
                    media_url = image.get("id")  # Meta uses media IDs, not URLs
                    media_mime = image.get("mime_type")
                    text = image.get("caption")

                elif msg_type == "audio":
                    parsed_type = "audio"
                    audio = msg.get("audio", {})
                    media_url = audio.get("id")
                    media_mime = audio.get("mime_type")

                elif msg_type == "video":
                    parsed_type = "video"
                    video = msg.get("video", {})
                    media_url = video.get("id")
                    media_mime = video.get("mime_type")
                    text = video.get("caption")

                elif msg_type == "document":
                    parsed_type = "document"
                    doc = msg.get("document", {})
                    media_url = doc.get("id")
                    media_mime = doc.get("mime_type")
                    text = doc.get("caption")

                else:
                    logger.info(f"Skipping unsupported Meta message type: {msg_type}")
                    continue

                messages.append(IncomingMessage(
                    from_number=from_number,
                    remote_jid="",  # Meta doesn't use JIDs
                    message_id=message_id,
                    timestamp=timestamp,
                    type=parsed_type,
                    text=text,
                    media_url=media_url,
                    media_mime=media_mime,
                    push_name=push_name,
                ))

    return messages


def extract_phone_number_id(payload: dict) -> str | None:
    """Extract the phone_number_id from a Meta webhook payload."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")
            if phone_number_id:
                return phone_number_id
    return None
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/webhook/meta_parser.py
git commit -m "feat: add Meta Cloud API webhook payload parser"
```

---

## Task 4: Add channel_id to IncomingMessage and Buffer

**Files:**
- Modify: `backend-evolution/app/webhook/parser.py:4-14`
- Modify: `backend-evolution/app/buffer/manager.py:15-69`

- [ ] **Step 1: Add channel_id to IncomingMessage**

In `backend-evolution/app/webhook/parser.py`, add `channel_id` field to the dataclass:

```python
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
    channel_id: str | None = None
```

- [ ] **Step 2: Pass channel_id through buffer**

In `backend-evolution/app/buffer/manager.py`, update `push_to_buffer` to store and pass channel_id:

Replace the function signature and the immediate-process path (lines 15-38):

```python
async def push_to_buffer(r: aioredis.Redis, msg: IncomingMessage):
    """Push a message to the buffer (or process immediately if buffer is off)."""
    from app.buffer.processor import process_buffered_messages

    phone = msg.from_number
    channel_id = msg.channel_id or ""

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

    # Save channel_id for this phone (used when flushing buffer)
    if channel_id:
        await r.set(f"channel:{phone}", channel_id, ex=86400)

    # Check if buffer is enabled
    buffer_enabled = await r.get("config:buffer_enabled")
    if buffer_enabled == "0":
        logger.info(f"Buffer OFF — processing immediately for {phone}")
        await process_buffered_messages(phone, text, channel_id)
        return
```

Update `_wait_and_flush` (lines 72-95) to pass channel_id:

```python
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

    # Get channel_id stored for this phone
    channel_id = await r.get(f"channel:{phone}") or ""

    # Clean up timer reference
    _active_timers.pop(phone, None)

    if messages:
        combined = "\n".join(messages)
        logger.info(f"Buffer flushed for {phone}: {len(messages)} messages")
        await process_buffered_messages(phone, combined, channel_id)
```

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/app/webhook/parser.py backend-evolution/app/buffer/manager.py
git commit -m "feat: pass channel_id through IncomingMessage and buffer pipeline"
```

---

## Task 5: Refactor Buffer Processor for Multi-Channel

**Files:**
- Modify: `backend-evolution/app/buffer/processor.py`

- [ ] **Step 1: Update processor to use channel-aware client**

Replace the entire `process_buffered_messages` function:

```python
# backend-evolution/app/buffer/processor.py
import asyncio
import logging

from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.whatsapp.factory import get_whatsapp_client
from app.whatsapp.media import transcribe_audio, describe_image
from app.cadence.service import get_cadence_state, pause_cadence
from app.agent.token_tracker import track_token_usage
from app.channels.service import get_channel_by_id
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


async def process_buffered_messages(phone: str, combined_text: str, channel_id: str = ""):
    """Process accumulated buffer messages: resolve media, run agent, humanize, send."""
    try:
        lead = get_or_create_lead(phone)

        # Look up channel for sending
        channel = get_channel_by_id(channel_id) if channel_id else None
        if not channel:
            logger.warning(f"No channel found for {phone} (channel_id={channel_id}), skipping")
            return

        # Get WhatsApp client for this channel
        wa_client = get_whatsapp_client(channel)

        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text, lead)

        # Pause cadence if active
        cadence = get_cadence_state(lead["id"])
        if cadence:
            pause_cadence(cadence["id"])
            sb = get_supabase()
            sb.rpc("increment_cadence_responded", {"campaign_id_param": cadence["campaign_id"]}).execute()
            logger.info(f"[CADENCE] Lead {phone} responded — pausing cadence")

        # Activate lead if pending/template_sent
        if lead.get("status") in ("imported", "template_sent"):
            lead = activate_lead(lead["id"])

        # Check if channel has an agent profile
        agent_profile = channel.get("agent_profiles")
        if agent_profile:
            # Run AI agent with profile context
            response = await run_agent(lead, resolved_text, channel)
            # Humanize and send
            bubbles = split_into_bubbles(response)
            for bubble in bubbles:
                delay = calculate_typing_delay(bubble)
                await asyncio.sleep(delay)
                await wa_client.send_text(phone, bubble)
        else:
            # Human-only mode: just save the message, don't run agent
            from app.leads.service import save_message
            save_message(lead["id"], "user", resolved_text, lead.get("stage", "secretaria"))
            logger.info(f"Human-only channel for {phone} — message saved, no agent response")

        # Update last_msg timestamp
        from datetime import datetime, timezone
        update_lead(lead["id"], last_msg_at=datetime.now(timezone.utc).isoformat())

    except Exception as e:
        logger.error(f"Error processing messages for {phone}: {e}", exc_info=True)
```

Keep the existing `_resolve_media` function unchanged (lines 56-103 of the original file).

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/buffer/processor.py
git commit -m "feat: refactor buffer processor for multi-channel with provider-aware sending"
```

---

## Task 6: Refactor Orchestrator for Agent Profiles

**Files:**
- Modify: `backend-evolution/app/agent/orchestrator.py`

- [ ] **Step 1: Update run_agent to accept channel context**

Change `run_agent` signature and use agent_profile from channel when available. The key changes are:

1. Add `channel` parameter to `run_agent`
2. If channel has an `agent_profiles` record, use its `stages` config for prompts/models/tools
3. Fall back to the hardcoded STAGE_PROMPTS/STAGE_MODELS if no profile

Replace `run_agent` function (lines 80-164):

```python
async def run_agent(lead: dict, user_text: str, channel: dict | None = None) -> str:
    """Run the AI agent for a lead and return the response text."""
    stage = lead.get("stage", "secretaria")

    # If channel has an agent profile, use its configuration
    agent_profile = channel.get("agent_profiles") if channel else None

    if agent_profile and agent_profile.get("stages"):
        profile_stages = agent_profile["stages"]
        stage_config = profile_stages.get(stage, {})
        model = stage_config.get("model") or agent_profile.get("model", "gpt-4.1")
        tools = get_tools_for_stage(stage)  # tools stay the same for now
        # Build system prompt from profile
        system_prompt = _build_profile_prompt(lead, agent_profile, stage)
    else:
        model = STAGE_MODELS.get(stage, "gpt-4.1")
        tools = get_tools_for_stage(stage)
        system_prompt = build_system_prompt(lead)

    # Build messages with the resolved system prompt
    history = get_history(lead["id"], limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    # Save user message
    save_message(lead["id"], "user", user_text, stage)

    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    # Track token usage
    if response.usage:
        track_token_usage(
            lead_id=lead["id"],
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message

    # Process tool calls if any
    while message.tool_calls:
        messages.append(message.model_dump())
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)
            result = await execute_tool(func_name, func_args, lead["id"], lead["phone"])
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )
        if response.usage:
            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        message = response.choices[0].message

    assistant_text = message.content or ""
    save_message(lead["id"], "assistant", assistant_text, stage)

    if stage == "secretaria":
        await _guardrail_secretaria(lead, messages)

    logger.info(f"Agent response for {lead['phone']} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
```

- [ ] **Step 2: Add profile prompt builder**

Add this helper function after `build_system_prompt` (after line 61):

```python
def _build_profile_prompt(lead: dict, agent_profile: dict, stage: str) -> str:
    """Build system prompt from an agent_profile record."""
    now = datetime.now(TZ_BR)
    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
    )

    # Use profile's base_prompt if set
    profile_base = agent_profile.get("base_prompt", "")
    if profile_base:
        base = base + "\n\n" + profile_base

    # Use stage-specific prompt from profile, fall back to hardcoded
    stages = agent_profile.get("stages", {})
    stage_config = stages.get(stage, {})
    stage_prompt = stage_config.get("prompt", "")
    if not stage_prompt:
        stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)

    return base + "\n\n" + stage_prompt
```

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/app/agent/orchestrator.py
git commit -m "feat: orchestrator accepts channel context and agent_profile configuration"
```

---

## Task 7: Refactor Webhook Router + Add Meta Endpoint

**Files:**
- Modify: `backend-evolution/app/webhook/router.py`
- Create: `backend-evolution/app/webhook/meta_router.py`
- Modify: `backend-evolution/app/main.py`
- Modify: `backend-evolution/app/config.py`

- [ ] **Step 1: Update Evolution webhook to be channel-aware**

Replace `backend-evolution/app/webhook/router.py`:

```python
import logging

from fastapi import APIRouter, Request

from app.webhook.parser import parse_webhook_payload
from app.whatsapp.factory import get_whatsapp_client
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, reset_lead
from app.channels.service import get_channel_by_phone

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook/evolution")
async def receive_evolution_webhook(request: Request):
    payload = await request.json()
    logger.info(f"Evolution webhook event: {payload.get('event', 'unknown')}")

    messages = parse_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}")

        # Find the channel this message belongs to
        channel = get_channel_by_phone(msg.from_number, "evolution")
        if not channel:
            # Try to find by instance name from the webhook payload
            instance = payload.get("instance", {}).get("instanceName", "")
            if instance:
                from app.channels.service import get_channel_by_provider_config
                channel = get_channel_by_provider_config("instance", instance, "evolution")

        if not channel:
            logger.warning(f"No active Evolution channel found for {msg.from_number}")
            continue

        if not channel.get("is_active"):
            logger.info(f"Channel {channel['id']} is inactive, skipping")
            continue

        # Set channel_id on message
        msg.channel_id = channel["id"]

        # Mark as read
        try:
            wa_client = get_whatsapp_client(channel)
            await wa_client.mark_read(msg.message_id, msg.remote_jid)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Handle !resetar command
        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                lead = get_or_create_lead(msg.from_number)
                reset_lead(lead["id"])
                wa_client = get_whatsapp_client(channel)
                await wa_client.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
            except Exception as e:
                logger.error(f"Failed to reset lead: {e}", exc_info=True)
            continue

        # Push to buffer
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}


# Keep old /webhook endpoint for backward compatibility during transition
@router.post("/webhook")
async def receive_webhook_legacy(request: Request):
    return await receive_evolution_webhook(request)
```

- [ ] **Step 2: Create Meta webhook router**

```python
# backend-evolution/app/webhook/meta_router.py
import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, Response

from app.webhook.meta_parser import parse_meta_webhook_payload, extract_phone_number_id
from app.whatsapp.factory import get_whatsapp_client
from app.buffer.manager import push_to_buffer
from app.leads.service import get_or_create_lead, reset_lead
from app.channels.service import get_channel_by_provider_config

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(payload_bytes: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify Meta webhook HMAC-SHA256 signature."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = signature_header[7:]  # strip "sha256=" prefix
    computed = hmac.new(app_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, expected)


@router.get("/webhook/meta")
async def verify_meta_webhook(request: Request):
    """Meta webhook verification challenge."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode != "subscribe" or not token or not challenge:
        return Response(status_code=403)

    # Find a channel with this verify_token
    channel = get_channel_by_provider_config("verify_token", token, "meta_cloud")
    if not channel:
        logger.warning(f"Meta verify: no channel found with verify_token={token}")
        return Response(status_code=403)

    logger.info(f"Meta webhook verified for channel {channel['id']}")
    return Response(content=challenge, media_type="text/plain")


@router.post("/webhook/meta")
async def receive_meta_webhook(request: Request):
    """Receive incoming WhatsApp messages from Meta Cloud API."""
    payload_bytes = await request.body()
    payload = await request.json()

    # Extract phone_number_id to identify the channel
    phone_number_id = extract_phone_number_id(payload)
    if not phone_number_id:
        logger.warning("Meta webhook: no phone_number_id found in payload")
        return {"status": "ok"}

    channel = get_channel_by_provider_config("phone_number_id", phone_number_id, "meta_cloud")
    if not channel:
        logger.warning(f"No active Meta channel for phone_number_id={phone_number_id}")
        return {"status": "ok"}

    if not channel.get("is_active"):
        logger.info(f"Channel {channel['id']} is inactive, skipping")
        return {"status": "ok"}

    # Verify signature
    signature = request.headers.get("x-hub-signature-256", "")
    app_secret = channel.get("provider_config", {}).get("app_secret", "")
    if app_secret and not _verify_signature(payload_bytes, signature, app_secret):
        logger.warning(f"Meta webhook: invalid signature for channel {channel['id']}")
        return Response(status_code=403)

    # Parse messages
    messages = parse_meta_webhook_payload(payload)

    for msg in messages:
        logger.info(f"Meta message from {msg.from_number}: type={msg.type}")
        msg.channel_id = channel["id"]

        # Mark as read
        try:
            wa_client = get_whatsapp_client(channel)
            await wa_client.mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read via Meta: {e}")

        # Handle !resetar command
        if msg.text and msg.text.strip().lower() == "!resetar":
            try:
                lead = get_or_create_lead(msg.from_number)
                reset_lead(lead["id"])
                wa_client = get_whatsapp_client(channel)
                await wa_client.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
            except Exception as e:
                logger.error(f"Failed to reset lead: {e}", exc_info=True)
            continue

        # Push to buffer
        redis = request.app.state.redis
        await push_to_buffer(redis, msg)

    return {"status": "ok"}
```

- [ ] **Step 3: Update config to make Evolution env vars optional**

In `backend-evolution/app/config.py`, change the Evolution fields to optional:

```python
class Settings(BaseSettings):
    # Evolution API (optional — per-channel config used instead)
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""

    # OpenAI
    openai_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # Buffer
    buffer_base_timeout: int = 15
    buffer_extend_timeout: int = 10
    buffer_max_timeout: int = 45

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

- [ ] **Step 4: Register new routers in main.py**

In `backend-evolution/app/main.py`, add the Meta router import and include it. After line 44:

```python
from app.webhook.meta_router import router as meta_webhook_router
```

After line 46 (`app.include_router(webhook_router)`), add:

```python
app.include_router(meta_webhook_router)
```

- [ ] **Step 5: Commit**

```bash
git add backend-evolution/app/webhook/router.py backend-evolution/app/webhook/meta_router.py backend-evolution/app/config.py backend-evolution/app/main.py
git commit -m "feat: add Meta Cloud webhook endpoint and channel-aware Evolution webhook"
```

---

## Task 8: CRM Cleanup — Remove Agentes Page + WhatsApp Tab

**Files:**
- Delete: `crm/src/app/(authenticated)/agentes/page.tsx`
- Modify: `crm/src/components/sidebar.tsx:79-87` (remove Agentes nav item)
- Modify: `crm/src/app/(authenticated)/config/page.tsx` (remove WhatsApp tab)
- Delete: `crm/src/components/config/whatsapp-tab.tsx`
- Delete: `crm/src/app/api/evolution/connect/route.ts`
- Delete: `crm/src/app/api/evolution/status/route.ts`
- Delete: `crm/src/app/api/evolution/disconnect/route.ts`
- Modify: `crm/src/app/api/agent-profiles/route.ts` (keep GET only)

- [ ] **Step 1: Delete agentes page**

```bash
rm "crm/src/app/(authenticated)/agentes/page.tsx"
```

- [ ] **Step 2: Remove Agentes from sidebar**

In `crm/src/components/sidebar.tsx`, remove the entire nav item object for `/agentes` (lines 79-87):

```typescript
// DELETE this entire object from NAV_ITEMS:
  {
    href: "/agentes",
    label: "Agentes",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21M6.75 19.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z" />
      </svg>
    ),
  },
```

- [ ] **Step 3: Remove WhatsApp tab from config page**

Replace `crm/src/app/(authenticated)/config/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { TagsTab } from "@/components/config/tags-tab";
import { PricingTab } from "@/components/config/pricing-tab";

const TABS = [
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("tags");

  return (
    <div className="max-w-3xl">
      <h1 className="text-[28px] font-bold text-[#1f1f1f] mb-8">Configuracoes</h1>

      <div className="mb-8">
        <nav className="inline-flex gap-1 p-1 bg-[#f6f7ed] rounded-xl">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-5 py-2 text-[13px] font-medium rounded-lg transition-all ${
                activeTab === tab.key
                  ? "bg-[#1f1f1f] text-white shadow-sm"
                  : "text-[#5f6368] hover:text-[#1f1f1f] hover:bg-white/60"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === "tags" && <TagsTab />}
      {activeTab === "pricing" && <PricingTab />}
    </div>
  );
}
```

- [ ] **Step 4: Delete obsolete files**

```bash
rm "crm/src/components/config/whatsapp-tab.tsx"
rm "crm/src/app/api/evolution/connect/route.ts"
rm "crm/src/app/api/evolution/status/route.ts"
rm "crm/src/app/api/evolution/disconnect/route.ts"
```

- [ ] **Step 5: Make agent-profiles API GET-only**

Replace `crm/src/app/api/agent-profiles/route.ts` — keep only GET:

```typescript
import { createClient } from "@supabase/supabase-js";
import { NextResponse } from "next/server";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET() {
  const { data, error } = await supabase
    .from("agent_profiles")
    .select("id, name")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json(data);
}
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "cleanup: remove /agentes page, WhatsApp config tab, and obsolete Evolution API routes"
```

---

## Task 9: Per-Channel Evolution API Proxy Routes (CRM)

**Files:**
- Create: `crm/src/app/api/channels/[id]/connect/route.ts`
- Create: `crm/src/app/api/channels/[id]/status/route.ts`
- Create: `crm/src/app/api/channels/[id]/disconnect/route.ts`

- [ ] **Step 1: Create per-channel connect route**

```typescript
// crm/src/app/api/channels/[id]/connect/route.ts
import { createClient } from "@supabase/supabase-js";
import { NextResponse } from "next/server";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  // Fetch channel
  const { data: channel, error } = await supabase
    .from("channels")
    .select("*")
    .eq("id", id)
    .single();

  if (error || !channel) {
    return NextResponse.json({ error: "Channel not found" }, { status: 404 });
  }

  if (channel.provider !== "evolution") {
    return NextResponse.json({ error: "Only Evolution channels support QR connection" }, { status: 400 });
  }

  const config = channel.provider_config;
  const baseUrl = (config.api_url as string).replace(/\/+$/, "");
  const instanceName = config.instance as string;
  const encodedInstance = encodeURIComponent(instanceName);
  const headers = {
    apikey: config.api_key as string,
    "Content-Type": "application/json",
  };

  try {
    // Try to connect existing instance
    const connectRes = await fetch(
      `${baseUrl}/instance/connect/${encodedInstance}`,
      { method: "GET", headers }
    );

    if (connectRes.ok) {
      const data = await connectRes.json();
      const qr = data.base64 ?? data.qrcode?.base64 ?? "";
      if (qr) {
        return NextResponse.json({ qrcode: qr });
      }
      return NextResponse.json({ connected: true });
    }

    // If 404, create instance
    if (connectRes.status === 404) {
      const createRes = await fetch(`${baseUrl}/instance/create`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          instanceName,
          qrcode: true,
          integration: "WHATSAPP-BAILEYS",
        }),
      });

      if (!createRes.ok) {
        const err = await createRes.text();
        return NextResponse.json({ error: err }, { status: createRes.status });
      }

      const data = await createRes.json();
      const qr = data.qrcode?.base64 ?? data.base64 ?? "";
      return NextResponse.json({ qrcode: qr });
    }

    const err = await connectRes.text();
    return NextResponse.json({ error: err }, { status: connectRes.status });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
```

- [ ] **Step 2: Create per-channel status route**

```typescript
// crm/src/app/api/channels/[id]/status/route.ts
import { createClient } from "@supabase/supabase-js";
import { NextResponse } from "next/server";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const { data: channel, error } = await supabase
    .from("channels")
    .select("*")
    .eq("id", id)
    .single();

  if (error || !channel) {
    return NextResponse.json({ error: "Channel not found" }, { status: 404 });
  }

  if (channel.provider !== "evolution") {
    return NextResponse.json({ error: "Only Evolution channels have connection status" }, { status: 400 });
  }

  const config = channel.provider_config;
  const baseUrl = (config.api_url as string).replace(/\/+$/, "");
  const instanceName = config.instance as string;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    const res = await fetch(
      `${baseUrl}/instance/connectionState/${encodedInstance}`,
      { headers: { apikey: config.api_key as string } }
    );

    if (!res.ok) {
      return NextResponse.json({ connected: false });
    }

    const data = await res.json();
    const connected = data?.instance?.state === "open";
    const number = connected ? data?.instance?.phoneNumber : undefined;

    // If connected and phone not yet saved, update it
    if (connected && number && !channel.phone) {
      await supabase
        .from("channels")
        .update({ phone: number.replace(/\D/g, "") })
        .eq("id", id);
    }

    return NextResponse.json({
      connected,
      ...(number ? { number } : {}),
    });
  } catch {
    return NextResponse.json({ connected: false });
  }
}
```

- [ ] **Step 3: Create per-channel disconnect route**

```typescript
// crm/src/app/api/channels/[id]/disconnect/route.ts
import { createClient } from "@supabase/supabase-js";
import { NextResponse } from "next/server";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const { data: channel, error } = await supabase
    .from("channels")
    .select("*")
    .eq("id", id)
    .single();

  if (error || !channel) {
    return NextResponse.json({ error: "Channel not found" }, { status: 404 });
  }

  if (channel.provider !== "evolution") {
    return NextResponse.json({ error: "Only Evolution channels support disconnect" }, { status: 400 });
  }

  const config = channel.provider_config;
  const baseUrl = (config.api_url as string).replace(/\/+$/, "");
  const instanceName = config.instance as string;
  const encodedInstance = encodeURIComponent(instanceName);

  try {
    await fetch(
      `${baseUrl}/instance/logout/${encodedInstance}`,
      {
        method: "DELETE",
        headers: { apikey: config.api_key as string },
      }
    );
    return NextResponse.json({ ok: true });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add "crm/src/app/api/channels/[id]/connect/route.ts" "crm/src/app/api/channels/[id]/status/route.ts" "crm/src/app/api/channels/[id]/disconnect/route.ts"
git commit -m "feat: add per-channel Evolution API proxy routes (connect/status/disconnect)"
```

---

## Task 10: Refactor Canais Page — Hub Central

**Files:**
- Modify: `crm/src/app/(authenticated)/canais/page.tsx`

- [ ] **Step 1: Rewrite Canais page with QR code modal and Meta fields**

This is the largest change. The page needs:
- Table listing with connection status column (Evolution only)
- Create/Edit modal with dynamic provider fields
- QR Code connection modal for Evolution channels
- Webhook URL display for Meta channels
- Agent profile dropdown (read-only from DB)

Replace the entire `crm/src/app/(authenticated)/canais/page.tsx` with:

```tsx
"use client";

import { useState, useEffect, useRef, useCallback } from "react";

interface AgentProfile {
  id: string;
  name: string;
}

interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profiles: AgentProfile | null;
  is_active: boolean;
  created_at: string;
}

interface FormData {
  name: string;
  provider: "meta_cloud" | "evolution";
  phone: string;
  agent_profile_id: string;
  is_active: boolean;
  // Evolution fields
  evo_api_url: string;
  evo_api_key: string;
  evo_instance: string;
  // Meta fields
  meta_phone_number_id: string;
  meta_access_token: string;
  meta_app_secret: string;
  meta_verify_token: string;
}

const EMPTY_FORM: FormData = {
  name: "",
  provider: "evolution",
  phone: "",
  agent_profile_id: "",
  is_active: true,
  evo_api_url: "",
  evo_api_key: "",
  evo_instance: "",
  meta_phone_number_id: "",
  meta_access_token: "",
  meta_app_secret: "",
  meta_verify_token: "",
};

export default function CanaisPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // QR Code modal state
  const [qrChannelId, setQrChannelId] = useState<string | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [qrStatus, setQrStatus] = useState<"idle" | "loading" | "scanning" | "connected">("idle");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Connection status cache
  const [connectionStatus, setConnectionStatus] = useState<Record<string, { connected: boolean; number?: string }>>({});

  const fetchChannels = useCallback(async () => {
    const res = await fetch("/api/channels");
    const data = await res.json();
    setChannels(data);
    setLoading(false);
  }, []);

  const fetchProfiles = useCallback(async () => {
    const res = await fetch("/api/agent-profiles");
    const data = await res.json();
    setProfiles(data);
  }, []);

  useEffect(() => {
    fetchChannels();
    fetchProfiles();
  }, [fetchChannels, fetchProfiles]);

  // Check connection status for Evolution channels
  useEffect(() => {
    const evoChannels = channels.filter((c) => c.provider === "evolution");
    evoChannels.forEach(async (ch) => {
      try {
        const res = await fetch(`/api/channels/${ch.id}/status`);
        const data = await res.json();
        setConnectionStatus((prev) => ({ ...prev, [ch.id]: data }));
      } catch {
        setConnectionStatus((prev) => ({ ...prev, [ch.id]: { connected: false } }));
      }
    });
  }, [channels]);

  const handleSave = async () => {
    setSaving(true);
    const providerConfig =
      form.provider === "evolution"
        ? { api_url: form.evo_api_url, api_key: form.evo_api_key, instance: form.evo_instance }
        : {
            phone_number_id: form.meta_phone_number_id,
            access_token: form.meta_access_token,
            app_secret: form.meta_app_secret,
            verify_token: form.meta_verify_token,
          };

    const body = {
      name: form.name,
      phone: form.provider === "meta_cloud" ? form.phone : "",
      provider: form.provider,
      provider_config: providerConfig,
      agent_profile_id: form.agent_profile_id || null,
      is_active: form.is_active,
    };

    if (editingId) {
      await fetch(`/api/channels/${editingId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } else {
      await fetch("/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    }

    setSaving(false);
    setShowForm(false);
    setEditingId(null);
    setForm(EMPTY_FORM);
    fetchChannels();
  };

  const handleEdit = (ch: Channel) => {
    const config = ch.provider_config || {};
    setForm({
      name: ch.name,
      provider: ch.provider,
      phone: ch.phone || "",
      agent_profile_id: ch.agent_profile_id || "",
      is_active: ch.is_active,
      evo_api_url: config.api_url || "",
      evo_api_key: config.api_key || "",
      evo_instance: config.instance || "",
      meta_phone_number_id: config.phone_number_id || "",
      meta_access_token: config.access_token || "",
      meta_app_secret: config.app_secret || "",
      meta_verify_token: config.verify_token || "",
    });
    setEditingId(ch.id);
    setShowForm(true);
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Tem certeza que deseja excluir este canal?")) return;
    await fetch(`/api/channels/${id}`, { method: "DELETE" });
    fetchChannels();
  };

  const handleToggleActive = async (ch: Channel) => {
    await fetch(`/api/channels/${ch.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !ch.is_active }),
    });
    fetchChannels();
  };

  // QR Code connection flow
  const handleConnect = async (channelId: string) => {
    setQrChannelId(channelId);
    setQrStatus("loading");
    setQrCode(null);

    try {
      const res = await fetch(`/api/channels/${channelId}/connect`, { method: "POST" });
      const data = await res.json();

      if (data.connected) {
        setQrStatus("connected");
        fetchChannels();
        return;
      }

      if (data.qrcode) {
        setQrCode(data.qrcode);
        setQrStatus("scanning");

        // Start polling for connection
        pollRef.current = setInterval(async () => {
          try {
            const statusRes = await fetch(`/api/channels/${channelId}/status`);
            const statusData = await statusRes.json();
            if (statusData.connected) {
              clearInterval(pollRef.current!);
              pollRef.current = null;
              setQrStatus("connected");
              setConnectionStatus((prev) => ({ ...prev, [channelId]: statusData }));
              fetchChannels();
            }
          } catch {}
        }, 3000);

        // Timeout after 60s
        setTimeout(() => {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setQrStatus("idle");
            setQrChannelId(null);
          }
        }, 60000);
      }
    } catch {
      setQrStatus("idle");
    }
  };

  const handleDisconnect = async (channelId: string) => {
    await fetch(`/api/channels/${channelId}/disconnect`, { method: "POST" });
    setConnectionStatus((prev) => ({ ...prev, [channelId]: { connected: false } }));
    fetchChannels();
  };

  const closeQrModal = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    setQrChannelId(null);
    setQrCode(null);
    setQrStatus("idle");
  };

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-[#8a8a8a] text-sm">Carregando...</div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <h1 className="text-[28px] font-bold text-[#1f1f1f]">Canais</h1>
        <button
          onClick={() => { setForm(EMPTY_FORM); setEditingId(null); setShowForm(true); }}
          className="px-5 py-2.5 text-[13px] font-medium text-white rounded-xl transition-all hover:opacity-90"
          style={{ background: "var(--accent-olive)" }}
        >
          + Novo Canal
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-2xl border border-[#e5e7eb] overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[#f0f0f0]">
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Nome</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Telefone</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Provider</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Agente</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Conexao</th>
              <th className="text-left px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Ativo</th>
              <th className="text-right px-5 py-3.5 text-[12px] font-semibold text-[#8a8a8a] uppercase tracking-wider">Acoes</th>
            </tr>
          </thead>
          <tbody>
            {channels.map((ch) => {
              const connStatus = connectionStatus[ch.id];
              return (
                <tr key={ch.id} className="border-b border-[#f8f8f8] last:border-0 hover:bg-[#fafafa] transition-colors">
                  <td className="px-5 py-3.5 text-[13px] font-medium text-[#1f1f1f]">{ch.name}</td>
                  <td className="px-5 py-3.5 text-[13px] text-[#5f6368]">{ch.phone || "—"}</td>
                  <td className="px-5 py-3.5">
                    <span className={`inline-flex px-2.5 py-1 text-[11px] font-semibold rounded-full ${
                      ch.provider === "meta_cloud"
                        ? "bg-blue-50 text-blue-700"
                        : "bg-emerald-50 text-emerald-700"
                    }`}>
                      {ch.provider === "meta_cloud" ? "Meta" : "Evolution"}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-[13px] text-[#5f6368]">
                    {ch.agent_profiles?.name || <span className="text-[#b0b0b0]">Sem agente</span>}
                  </td>
                  <td className="px-5 py-3.5">
                    {ch.provider === "evolution" ? (
                      connStatus?.connected ? (
                        <span className="inline-flex items-center gap-1.5 text-[12px] text-emerald-600 font-medium">
                          <span className="w-2 h-2 rounded-full bg-emerald-500" />
                          Conectado
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-[12px] text-red-500 font-medium">
                          <span className="w-2 h-2 rounded-full bg-red-400" />
                          Desconectado
                        </span>
                      )
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[12px] text-blue-600 font-medium">
                        <span className="w-2 h-2 rounded-full bg-blue-500" />
                        Webhook
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3.5">
                    <button
                      onClick={() => handleToggleActive(ch)}
                      className={`relative w-10 h-5 rounded-full transition-colors ${ch.is_active ? "bg-emerald-500" : "bg-gray-300"}`}
                    >
                      <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${ch.is_active ? "translate-x-5" : ""}`} />
                    </button>
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {ch.provider === "evolution" && (
                        connStatus?.connected ? (
                          <button onClick={() => handleDisconnect(ch.id)} className="px-3 py-1.5 text-[11px] font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors">
                            Desconectar
                          </button>
                        ) : (
                          <button onClick={() => handleConnect(ch.id)} className="px-3 py-1.5 text-[11px] font-medium text-emerald-700 bg-emerald-50 rounded-lg hover:bg-emerald-100 transition-colors">
                            Conectar
                          </button>
                        )
                      )}
                      <button onClick={() => handleEdit(ch)} className="px-3 py-1.5 text-[11px] font-medium text-[#5f6368] bg-[#f6f7ed] rounded-lg hover:bg-[#eef0dc] transition-colors">
                        Editar
                      </button>
                      <button onClick={() => handleDelete(ch.id)} className="px-3 py-1.5 text-[11px] font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 transition-colors">
                        Excluir
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            {channels.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-12 text-center text-[13px] text-[#8a8a8a]">
                  Nenhum canal configurado. Clique em &quot;+ Novo Canal&quot; para comecar.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => { setShowForm(false); setEditingId(null); }}>
          <div className="bg-white rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-[#1f1f1f] mb-5">
              {editingId ? "Editar Canal" : "Novo Canal"}
            </h2>

            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Nome</label>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                  placeholder="Ex: Atendimento Principal"
                />
              </div>

              {/* Provider */}
              <div>
                <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Provider</label>
                <select
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value as "meta_cloud" | "evolution" })}
                  className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                >
                  <option value="evolution">Evolution API</option>
                  <option value="meta_cloud">Meta Cloud API (Oficial)</option>
                </select>
              </div>

              {/* Evolution-specific fields */}
              {form.provider === "evolution" && (
                <>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">API URL</label>
                    <input
                      value={form.evo_api_url}
                      onChange={(e) => setForm({ ...form, evo_api_url: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      placeholder="https://evolution.seudominio.com"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">API Key</label>
                    <input
                      value={form.evo_api_key}
                      onChange={(e) => setForm({ ...form, evo_api_key: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Nome da Instancia</label>
                    <input
                      value={form.evo_instance}
                      onChange={(e) => setForm({ ...form, evo_instance: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      placeholder="minha-instancia"
                    />
                  </div>
                </>
              )}

              {/* Meta-specific fields */}
              {form.provider === "meta_cloud" && (
                <>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Telefone</label>
                    <input
                      value={form.phone}
                      onChange={(e) => setForm({ ...form, phone: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      placeholder="5534999999999"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Phone Number ID</label>
                    <input
                      value={form.meta_phone_number_id}
                      onChange={(e) => setForm({ ...form, meta_phone_number_id: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Access Token</label>
                    <input
                      value={form.meta_access_token}
                      onChange={(e) => setForm({ ...form, meta_access_token: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">App Secret</label>
                    <input
                      value={form.meta_app_secret}
                      onChange={(e) => setForm({ ...form, meta_app_secret: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                      type="password"
                    />
                  </div>
                  <div>
                    <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Verify Token</label>
                    <input
                      value={form.meta_verify_token}
                      onChange={(e) => setForm({ ...form, meta_verify_token: e.target.value })}
                      className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                    />
                  </div>
                </>
              )}

              {/* Agent Profile */}
              <div>
                <label className="block text-[12px] font-semibold text-[#5f6368] mb-1.5">Agente IA</label>
                <select
                  value={form.agent_profile_id}
                  onChange={(e) => setForm({ ...form, agent_profile_id: e.target.value })}
                  className="w-full px-4 py-2.5 text-[13px] border border-[#e5e7eb] rounded-xl focus:outline-none focus:ring-2 focus:ring-[#b8c97c]"
                >
                  <option value="">Nenhum (100% humano)</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </div>

              {/* Active toggle */}
              <div className="flex items-center justify-between">
                <label className="text-[12px] font-semibold text-[#5f6368]">Ativo</label>
                <button
                  type="button"
                  onClick={() => setForm({ ...form, is_active: !form.is_active })}
                  className={`relative w-10 h-5 rounded-full transition-colors ${form.is_active ? "bg-emerald-500" : "bg-gray-300"}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${form.is_active ? "translate-x-5" : ""}`} />
                </button>
              </div>
            </div>

            {/* Webhook info for Meta (only when editing) */}
            {editingId && form.provider === "meta_cloud" && (
              <div className="mt-5 p-4 bg-blue-50 rounded-xl">
                <p className="text-[12px] font-semibold text-blue-700 mb-2">Configuracao do Webhook no Meta</p>
                <div className="space-y-2">
                  <div>
                    <span className="text-[11px] text-blue-600">URL do Webhook:</span>
                    <code className="block text-[12px] bg-white px-3 py-1.5 rounded-lg mt-1 text-[#1f1f1f] select-all">
                      {backendUrl}/webhook/meta
                    </code>
                  </div>
                  <div>
                    <span className="text-[11px] text-blue-600">Verify Token:</span>
                    <code className="block text-[12px] bg-white px-3 py-1.5 rounded-lg mt-1 text-[#1f1f1f] select-all">
                      {form.meta_verify_token || "—"}
                    </code>
                  </div>
                </div>
              </div>
            )}

            <div className="flex justify-end gap-3 mt-6">
              <button
                onClick={() => { setShowForm(false); setEditingId(null); }}
                className="px-5 py-2.5 text-[13px] font-medium text-[#5f6368] bg-[#f6f7ed] rounded-xl hover:bg-[#eef0dc] transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !form.name}
                className="px-5 py-2.5 text-[13px] font-medium text-white rounded-xl transition-all hover:opacity-90 disabled:opacity-50"
                style={{ background: "var(--accent-olive)" }}
              >
                {saving ? "Salvando..." : editingId ? "Salvar" : "Criar"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* QR Code Modal */}
      {qrChannelId && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={closeQrModal}>
          <div className="bg-white rounded-2xl w-full max-w-sm p-6 text-center" onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-bold text-[#1f1f1f] mb-4">Conectar WhatsApp</h2>

            {qrStatus === "loading" && (
              <p className="text-[13px] text-[#8a8a8a] py-8">Gerando QR Code...</p>
            )}

            {qrStatus === "scanning" && qrCode && (
              <div>
                <img
                  src={qrCode.startsWith("data:") ? qrCode : `data:image/png;base64,${qrCode}`}
                  alt="QR Code"
                  className="mx-auto w-64 h-64 rounded-xl"
                />
                <p className="text-[12px] text-[#8a8a8a] mt-3">Escaneie o QR Code com o WhatsApp</p>
              </div>
            )}

            {qrStatus === "connected" && (
              <div className="py-8">
                <div className="w-16 h-16 mx-auto mb-3 rounded-full bg-emerald-100 flex items-center justify-center">
                  <svg className="w-8 h-8 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <p className="text-[14px] font-medium text-emerald-700">Conectado com sucesso!</p>
              </div>
            )}

            <button
              onClick={closeQrModal}
              className="mt-4 px-5 py-2.5 text-[13px] font-medium text-[#5f6368] bg-[#f6f7ed] rounded-xl hover:bg-[#eef0dc] transition-colors"
            >
              Fechar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add "crm/src/app/(authenticated)/canais/page.tsx"
git commit -m "feat: refactor Canais page as central hub with QR code and Meta support"
```

---

## Task 11: Update old client.py for backward compatibility

**Files:**
- Modify: `backend-evolution/app/whatsapp/client.py`

- [ ] **Step 1: Update client.py to delegate to EvolutionClient**

The old `client.py` is still imported by `campaign/worker.py` and other modules. Keep it working during transition by delegating to the new `EvolutionClient`:

```python
# backend-evolution/app/whatsapp/client.py
"""Backward-compatible module — delegates to EvolutionClient.

Used by campaign worker and other modules that still import from here.
"""
from app.config import settings
from app.whatsapp.evolution import EvolutionClient


def _get_legacy_client() -> EvolutionClient:
    return EvolutionClient(
        api_url=settings.evolution_api_url,
        api_key=settings.evolution_api_key,
        instance=settings.evolution_instance,
    )


async def send_text(to: str, body: str) -> dict:
    return await _get_legacy_client().send_text(to, body)


async def send_template(to: str, template_name: str, language: str = "pt_BR", components: list | None = None) -> dict:
    return await send_text(to, f"[Template: {template_name}]")


async def send_image(to: str, image_url: str, caption: str | None = None) -> dict:
    return await _get_legacy_client().send_image(to, image_url, caption)


async def send_image_base64(to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
    return await _get_legacy_client().send_image_base64(to, base64_data, mimetype, caption)


async def send_audio(to: str, audio_url: str) -> dict:
    return await _get_legacy_client().send_audio(to, audio_url)


async def mark_read(message_id: str, remote_jid: str) -> dict:
    return await _get_legacy_client().mark_read(message_id, remote_jid)
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/whatsapp/client.py
git commit -m "refactor: delegate legacy client.py to EvolutionClient for backward compat"
```

---

## Task 12: Add NEXT_PUBLIC_BACKEND_URL env var

**Files:**
- Modify: `crm/.env.local` (or `.env`)

- [ ] **Step 1: Add the env var**

The Canais page uses `NEXT_PUBLIC_BACKEND_URL` to display the webhook URL for Meta channels. Add it to the CRM environment:

```bash
echo "NEXT_PUBLIC_BACKEND_URL=http://localhost:8000" >> crm/.env.local
```

(In production this would be the public backend URL.)

- [ ] **Step 2: Commit**

```bash
git add crm/.env.local
git commit -m "chore: add NEXT_PUBLIC_BACKEND_URL env var for webhook URL display"
```

---

## Summary of Commits

1. `feat: add channel lookup service for multi-channel routing`
2. `feat: add multi-provider WhatsApp client abstraction (Evolution + Meta)`
3. `feat: add Meta Cloud API webhook payload parser`
4. `feat: pass channel_id through IncomingMessage and buffer pipeline`
5. `feat: refactor buffer processor for multi-channel with provider-aware sending`
6. `feat: orchestrator accepts channel context and agent_profile configuration`
7. `feat: add Meta Cloud webhook endpoint and channel-aware Evolution webhook`
8. `cleanup: remove /agentes page, WhatsApp config tab, and obsolete Evolution API routes`
9. `feat: add per-channel Evolution API proxy routes (connect/status/disconnect)`
10. `feat: refactor Canais page as central hub with QR code and Meta support`
11. `refactor: delegate legacy client.py to EvolutionClient for backward compat`
12. `chore: add NEXT_PUBLIC_BACKEND_URL env var for webhook URL display`
