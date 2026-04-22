# Multi-Channel CRM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the backend into a multi-number, multi-provider WhatsApp CRM with channels, agent profiles, and per-channel conversations.

**Architecture:** Provider abstraction layer with `MetaCloudProvider` and `EvolutionProvider` implementations. Each WhatsApp number is a "channel" with its own provider config and optional agent profile. Leads are global; conversations are per lead+channel.

**Tech Stack:** FastAPI, Supabase (PostgreSQL), Redis, OpenAI, httpx, Next.js 15, TypeScript, Tailwind CSS

---

## File Structure

### New files (Backend)
- `backend/app/providers/__init__.py` — Package init
- `backend/app/providers/base.py` — Abstract WhatsAppProvider interface
- `backend/app/providers/meta_cloud.py` — Meta Cloud API implementation
- `backend/app/providers/evolution.py` — Evolution API implementation
- `backend/app/providers/registry.py` — Provider resolution by channel
- `backend/app/channels/__init__.py` — Package init
- `backend/app/channels/router.py` — Channel CRUD API endpoints
- `backend/app/channels/service.py` ��� Channel business logic
- `backend/app/agent_profiles/__init__.py` — Package init
- `backend/app/agent_profiles/router.py` — Agent profile CRUD API endpoints
- `backend/app/conversations/__init__.py` — Package init
- `backend/app/conversations/service.py` — Conversation CRUD + messaging
- `backend/migrations/007_multi_channel.sql` — Database migration

### Modified files (Backend)
- `backend/app/config.py` — Remove hardcoded Meta credentials, add openai_api_key only
- `backend/app/main.py` — Register new routers, remove old Meta-specific startup
- `backend/app/webhook/router.py` — Split into meta + evolution endpoints with channel routing
- `backend/app/webhook/parser.py` — Add channel_id to IncomingMessage
- `backend/app/buffer/manager.py` — Key by channel_id+phone instead of just phone
- `backend/app/buffer/processor.py` — Use conversations, resolve provider per channel
- `backend/app/agent/orchestrator.py` — Load prompts from agent_profile instead of hardcoded
- `backend/app/agent/tools.py` — Operate on conversation instead of lead
- `backend/app/leads/service.py` — Remove stage/status ops, simplify to global lead
- `backend/app/leads/router.py` — Adjust queries for new schema
- `backend/app/campaign/router.py` — Add channel_id, validate meta_cloud only
- `backend/app/campaign/worker.py` — Use provider from campaign's channel
- `backend/app/campaign/importer.py` — Create conversations on import

### New files (Frontend)
- `crm/src/app/(authenticated)/canais/page.tsx` — Channels management page
- `crm/src/app/(authenticated)/agentes/page.tsx` — Agent profiles management page
- `crm/src/app/api/channels/route.ts` — Channels API proxy
- `crm/src/app/api/channels/[id]/route.ts` — Single channel API proxy
- `crm/src/app/api/agent-profiles/route.ts` — Agent profiles API proxy
- `crm/src/app/api/agent-profiles/[id]/route.ts` — Single agent profile API proxy
- `crm/src/app/api/conversations/route.ts` — Conversations API proxy
- `crm/src/app/api/conversations/[id]/messages/route.ts` — Conversation messages API proxy

### Modified files (Frontend)
- `crm/src/lib/types.ts` — Add Channel, AgentProfile, Conversation types
- `crm/src/components/sidebar.tsx` — Add Canais and Agentes nav items
- `crm/src/app/(authenticated)/campanhas/page.tsx` — Channel selector
- `crm/src/app/(authenticated)/conversas/page.tsx` — Filter by channel
- `crm/src/app/(authenticated)/leads/page.tsx` — Show conversations per lead

---

## Task 1: Database Migration

**Files:**
- Create: `backend/migrations/007_multi_channel.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 007_multi_channel.sql
-- Multi-channel CRM: channels, agent_profiles, conversations

-- Agent profiles (must come before channels due to FK)
CREATE TABLE IF NOT EXISTS agent_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    model text NOT NULL DEFAULT 'gpt-4.1',
    stages jsonb NOT NULL DEFAULT '{}',
    base_prompt text NOT NULL DEFAULT '',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- Channels (WhatsApp numbers)
CREATE TABLE IF NOT EXISTS channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    phone text NOT NULL UNIQUE,
    provider text NOT NULL CHECK (provider IN ('meta_cloud', 'evolution')),
    provider_config jsonb NOT NULL DEFAULT '{}',
    agent_profile_id uuid REFERENCES agent_profiles(id) ON DELETE SET NULL,
    is_active boolean DEFAULT true,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_channels_phone ON channels(phone);
CREATE INDEX idx_channels_provider ON channels(provider);

-- Conversations (lead + channel)
CREATE TABLE IF NOT EXISTS conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    channel_id uuid REFERENCES channels(id) ON DELETE CASCADE,
    stage text DEFAULT 'secretaria',
    status text DEFAULT 'active',
    campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
    last_msg_at timestamptz,
    created_at timestamptz DEFAULT now(),
    UNIQUE(lead_id, channel_id)
);

CREATE INDEX idx_conversations_channel ON conversations(channel_id);
CREATE INDEX idx_conversations_lead ON conversations(lead_id);
CREATE INDEX idx_conversations_status ON conversations(status);

-- Add conversation_id to messages
ALTER TABLE messages ADD COLUMN IF NOT EXISTS conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

-- Add channel_id to campaigns
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;

-- Add channel_id to templates
ALTER TABLE templates ADD COLUMN IF NOT EXISTS channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;

-- Add metadata to leads
ALTER TABLE leads ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}';

-- Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE channels;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_profiles;
ALTER PUBLICATION supabase_realtime ADD TABLE conversations;
```

- [ ] **Step 2: Run the migration in Supabase**

Run via Supabase SQL editor or CLI. Verify tables exist:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
AND table_name IN ('channels', 'agent_profiles', 'conversations');
```
Expected: 3 rows returned.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/007_multi_channel.sql
git commit -m "feat: add multi-channel database migration (channels, agent_profiles, conversations)"
```

---

## Task 2: Provider Abstraction Layer

**Files:**
- Create: `backend/app/providers/__init__.py`
- Create: `backend/app/providers/base.py`
- Create: `backend/app/providers/meta_cloud.py`
- Create: `backend/app/providers/evolution.py`
- Create: `backend/app/providers/registry.py`

- [ ] **Step 1: Create providers package init**

```python
# backend/app/providers/__init__.py
from app.providers.base import WhatsAppProvider
from app.providers.registry import get_provider

__all__ = ["WhatsAppProvider", "get_provider"]
```

- [ ] **Step 2: Create abstract base provider**

```python
# backend/app/providers/base.py
from abc import ABC, abstractmethod


class WhatsAppProvider(ABC):
    """Abstract interface for WhatsApp messaging providers."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict:
        """Send a text message. Returns provider response."""

    @abstractmethod
    async def send_template(self, to: str, template_name: str,
                            language: str = "pt_BR",
                            components: list | None = None) -> dict:
        """Send a template message. Only supported by MetaCloudProvider."""

    @abstractmethod
    async def send_image(self, to: str, image_url: str,
                         caption: str | None = None) -> dict:
        """Send an image message."""

    @abstractmethod
    async def mark_read(self, message_id: str, **kwargs) -> dict:
        """Mark a message as read."""

    @abstractmethod
    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """Download media. Returns (bytes, content_type).
        media_ref is media_id for Meta, URL for Evolution.
        """
```

- [ ] **Step 3: Create Meta Cloud provider**

```python
# backend/app/providers/meta_cloud.py
import httpx

from app.providers.base import WhatsAppProvider


class MetaCloudProvider(WhatsAppProvider):
    """Meta WhatsApp Cloud API provider."""

    def _base_url(self) -> str:
        version = self.config.get("api_version", "v21.0")
        phone_number_id = self.config["phone_number_id"]
        return f"https://graph.facebook.com/{version}/{phone_number_id}/messages"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config['access_token']}",
            "Content-Type": "application/json",
        }

    def _media_base_url(self) -> str:
        version = self.config.get("api_version", "v21.0")
        return f"https://graph.facebook.com/{version}"

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._base_url(), json=payload, headers=self._headers()
            )
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        })

    async def send_template(self, to: str, template_name: str,
                            language: str = "pt_BR",
                            components: list | None = None) -> dict:
        template = {
            "name": template_name,
            "language": {"code": language},
        }
        if components:
            template["components"] = components

        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        })

    async def send_image(self, to: str, image_url: str,
                         caption: str | None = None) -> dict:
        image = {"link": image_url}
        if caption:
            image["caption"] = caption

        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": image,
        })

    async def mark_read(self, message_id: str, **kwargs) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """Download media from Meta. media_ref is the media_id."""
        async with httpx.AsyncClient() as client:
            # Step 1: get media URL
            resp = await client.get(
                f"{self._media_base_url()}/{media_ref}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            media_url = resp.json()["url"]

            # Step 2: download the file
            resp = await client.get(media_url, headers=self._headers())
            resp.raise_for_status()
            return resp.content, resp.headers.get(
                "content-type", "application/octet-stream"
            )
```

- [ ] **Step 4: Create Evolution provider**

```python
# backend/app/providers/evolution.py
import httpx

from app.providers.base import WhatsAppProvider


class EvolutionProvider(WhatsAppProvider):
    """Evolution API provider."""

    def _base_url(self) -> str:
        return self.config["api_url"].rstrip("/")

    def _headers(self) -> dict:
        return {
            "apikey": self.config["api_key"],
            "Content-Type": "application/json",
        }

    def _instance(self) -> str:
        return self.config["instance"]

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url()}{path}/{self._instance()}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post("/message/sendText", {
            "number": to,
            "text": body,
        })

    async def send_template(self, to: str, template_name: str,
                            language: str = "pt_BR",
                            components: list | None = None) -> dict:
        raise NotImplementedError(
            "Evolution API does not support Meta-style templates. "
            "Campaigns require a Meta Cloud API channel."
        )

    async def send_image(self, to: str, image_url: str,
                         caption: str | None = None) -> dict:
        return await self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "caption": caption or "",
            "media": image_url,
            "fileName": "image.jpg",
        })

    async def mark_read(self, message_id: str, **kwargs) -> dict:
        remote_jid = kwargs.get("remote_jid", "")
        return await self._post("/chat/markMessageAsRead", {
            "readMessages": [{
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }],
        })

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """Download media from URL. media_ref is the direct URL for Evolution."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(media_ref)
            resp.raise_for_status()
            return resp.content, resp.headers.get(
                "content-type", "application/octet-stream"
            )
```

- [ ] **Step 5: Create provider registry**

```python
# backend/app/providers/registry.py
from app.providers.base import WhatsAppProvider
from app.providers.meta_cloud import MetaCloudProvider
from app.providers.evolution import EvolutionProvider

_PROVIDERS = {
    "meta_cloud": MetaCloudProvider,
    "evolution": EvolutionProvider,
}


def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve a WhatsAppProvider instance from a channel record."""
    provider_type = channel["provider"]
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_type}")
    return provider_class(channel["provider_config"])
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/providers/
git commit -m "feat: add WhatsApp provider abstraction layer (MetaCloud + Evolution)"
```

---

## Task 3: Channel Service & API

**Files:**
- Create: `backend/app/channels/__init__.py`
- Create: `backend/app/channels/service.py`
- Create: `backend/app/channels/router.py`

- [ ] **Step 1: Create channels package init**

```python
# backend/app/channels/__init__.py
```

- [ ] **Step 2: Create channel service**

```python
# backend/app/channels/service.py
from typing import Any

from app.db.supabase import get_supabase


def list_channels() -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("channels")
        .select("*, agent_profiles(id, name)")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


def get_channel(channel_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("channels")
        .select("*, agent_profiles(id, name)")
        .eq("id", channel_id)
        .single()
        .execute()
    )
    return result.data


def get_channel_by_phone(phone: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("channels").select("*").eq("phone", phone).execute()
    return result.data[0] if result.data else None


def get_channel_by_provider_config(key: str, value: str) -> dict[str, Any] | None:
    """Find channel by a field in provider_config JSONB.
    Used to resolve Meta webhook by phone_number_id.
    """
    sb = get_supabase()
    result = (
        sb.table("channels")
        .select("*")
        .filter("provider_config->>{}".format(key), "eq", value)
        .execute()
    )
    return result.data[0] if result.data else None


def create_channel(data: dict) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("channels").insert(data).execute()
    return result.data[0]


def update_channel(channel_id: str, data: dict) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("channels").update(data).eq("id", channel_id).execute()
    return result.data[0]


def delete_channel(channel_id: str) -> None:
    sb = get_supabase()
    sb.table("channels").delete().eq("id", channel_id).execute()
```

- [ ] **Step 3: Create channel router**

```python
# backend/app/channels/router.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.channels.service import (
    list_channels, get_channel, create_channel, update_channel, delete_channel,
)

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelCreate(BaseModel):
    name: str
    phone: str
    provider: str  # "meta_cloud" | "evolution"
    provider_config: dict
    agent_profile_id: str | None = None


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider_config: dict | None = None
    agent_profile_id: str | None = None
    is_active: bool | None = None


@router.get("")
async def api_list_channels():
    return {"data": list_channels()}


@router.get("/{channel_id}")
async def api_get_channel(channel_id: str):
    return get_channel(channel_id)


@router.post("")
async def api_create_channel(body: ChannelCreate):
    if body.provider not in ("meta_cloud", "evolution"):
        raise HTTPException(400, "Provider must be 'meta_cloud' or 'evolution'")
    return create_channel(body.model_dump(exclude_none=True))


@router.put("/{channel_id}")
async def api_update_channel(channel_id: str, body: ChannelUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    return update_channel(channel_id, data)


@router.delete("/{channel_id}")
async def api_delete_channel(channel_id: str):
    delete_channel(channel_id)
    return {"status": "deleted"}
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/channels/
git commit -m "feat: add channels CRUD service and API"
```

---

## Task 4: Agent Profiles Service & API

**Files:**
- Create: `backend/app/agent_profiles/__init__.py`
- Create: `backend/app/agent_profiles/router.py`

- [ ] **Step 1: Create agent_profiles package init**

```python
# backend/app/agent_profiles/__init__.py
```

- [ ] **Step 2: Create agent profiles router**

```python
# backend/app/agent_profiles/router.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/agent-profiles", tags=["agent_profiles"])


class ProfileCreate(BaseModel):
    name: str
    model: str = "gpt-4.1"
    stages: dict
    base_prompt: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    stages: dict | None = None
    base_prompt: str | None = None


@router.get("")
async def list_profiles():
    sb = get_supabase()
    result = sb.table("agent_profiles").select("*").order("created_at", desc=True).execute()
    return {"data": result.data}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    sb = get_supabase()
    result = sb.table("agent_profiles").select("*").eq("id", profile_id).single().execute()
    return result.data


@router.post("")
async def create_profile(body: ProfileCreate):
    sb = get_supabase()
    result = sb.table("agent_profiles").insert(body.model_dump()).execute()
    return result.data[0]


@router.put("/{profile_id}")
async def update_profile(profile_id: str, body: ProfileUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    sb = get_supabase()
    data["updated_at"] = "now()"
    result = sb.table("agent_profiles").update(data).eq("id", profile_id).execute()
    return result.data[0]


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    sb = get_supabase()
    sb.table("agent_profiles").delete().eq("id", profile_id).execute()
    return {"status": "deleted"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent_profiles/
git commit -m "feat: add agent profiles CRUD API"
```

---

## Task 5: Conversations Service

**Files:**
- Create: `backend/app/conversations/__init__.py`
- Create: `backend/app/conversations/service.py`

- [ ] **Step 1: Create conversations package init**

```python
# backend/app/conversations/__init__.py
```

- [ ] **Step 2: Create conversations service**

```python
# backend/app/conversations/service.py
from datetime import datetime, timezone
from typing import Any

from app.db.supabase import get_supabase


def get_or_create_conversation(lead_id: str, channel_id: str) -> dict[str, Any]:
    """Get existing conversation or create new one for lead+channel pair."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .execute()
    )

    if result.data:
        return result.data[0]

    new_conv = {
        "lead_id": lead_id,
        "channel_id": channel_id,
        "stage": "secretaria",
        "status": "active",
    }
    result = sb.table("conversations").insert(new_conv).execute()
    return result.data[0]


def get_conversation(conversation_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*, leads(*), channels(id, name, phone, provider)")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    return result.data


def list_conversations(
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("conversations")
        .select("*, leads(id, phone, name, company), channels(id, name, phone, provider)")
    )

    if channel_id:
        query = query.eq("channel_id", channel_id)
    if status:
        query = query.eq("status", status)

    result = (
        query.order("last_msg_at", desc=True, nullsfirst=False)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data


def update_conversation(conversation_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .update(fields)
        .eq("id", conversation_id)
        .execute()
    )
    return result.data[0]


def activate_conversation(conversation_id: str) -> dict[str, Any]:
    """Activate a conversation (when lead first responds)."""
    return update_conversation(
        conversation_id,
        status="active",
        stage="secretaria",
        last_msg_at=datetime.now(timezone.utc).isoformat(),
    )


def save_message(
    conversation_id: str,
    lead_id: str,
    role: str,
    content: str,
    stage: str | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
    }
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


def get_history(conversation_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/conversations/
git commit -m "feat: add conversations service (per lead+channel)"
```

---

## Task 6: Refactor Agent Orchestrator

**Files:**
- Modify: `backend/app/agent/orchestrator.py`
- Modify: `backend/app/agent/tools.py`

- [ ] **Step 1: Rewrite orchestrator to load from agent_profile**

Replace the entire content of `backend/app/agent/orchestrator.py`:

```python
# backend/app/agent/orchestrator.py
import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.tools import get_tools_for_stage, execute_tool
from app.conversations.service import get_history, save_message

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None

# Brazil timezone
TZ_BR = timezone(timedelta(hours=-3))


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def build_system_prompt(conversation: dict, agent_profile: dict) -> str:
    """Build system prompt from agent_profile + conversation stage."""
    now = datetime.now(TZ_BR)
    stage = conversation.get("stage", "secretaria")

    base_prompt = agent_profile.get("base_prompt", "")
    stages = agent_profile.get("stages", {})
    stage_config = stages.get(stage, {})
    stage_prompt = stage_config.get("prompt", "")

    # Inject lead context
    lead = conversation.get("leads", {}) or {}
    lead_name = lead.get("name")
    lead_company = lead.get("company")

    context_lines = [f"Data/hora atual: {now.strftime('%d/%m/%Y %H:%M')}"]
    if lead_name:
        context_lines.append(f"Nome do lead: {lead_name}")
    if lead_company:
        context_lines.append(f"Empresa: {lead_company}")

    context = "\n".join(context_lines)

    return f"{base_prompt}\n\n--- CONTEXTO ---\n{context}\n\n--- STAGE: {stage} ---\n{stage_prompt}"


def build_messages(conversation: dict, agent_profile: dict, user_text: str) -> list[dict]:
    """Build the messages array for OpenAI from conversation history."""
    system_prompt = build_system_prompt(conversation, agent_profile)
    history = get_history(conversation["id"], limit=30)

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_text})

    return messages


async def run_agent(conversation: dict, agent_profile: dict, user_text: str) -> str:
    """Run the AI agent for a conversation and return the response text."""
    stage = conversation.get("stage", "secretaria")
    lead = conversation.get("leads", {}) or {}
    lead_id = lead.get("id") or conversation.get("lead_id")
    conversation_id = conversation["id"]

    # Get model and tools from agent_profile stage config
    stages = agent_profile.get("stages", {})
    stage_config = stages.get(stage, {})
    model = stage_config.get("model", agent_profile.get("model", "gpt-4.1"))
    tool_names = stage_config.get("tools", [])
    tools = get_tools_for_stage(tool_names)

    messages = build_messages(conversation, agent_profile, user_text)

    # Save user message
    save_message(conversation_id, lead_id, "user", user_text, stage)

    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    message = response.choices[0].message

    # Process tool calls if any
    while message.tool_calls:
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            result = await execute_tool(
                func_name, func_args, conversation_id, lead_id,
            )

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
        message = response.choices[0].message

    assistant_text = message.content or ""

    # Save assistant message
    save_message(conversation_id, lead_id, "assistant", assistant_text, stage)

    logger.info(f"Agent response for conversation {conversation_id} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
```

- [ ] **Step 2: Rewrite tools.py to operate on conversation**

Replace the entire content of `backend/app/agent/tools.py`:

```python
# backend/app/agent/tools.py
import logging
from typing import Any

from app.conversations.service import update_conversation, save_message
from app.leads.service import update_lead

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
                        "description": "Categoria do catalogo",
                    }
                },
                "required": ["categoria"],
            },
        },
    },
]

_TOOLS_BY_NAME = {t["function"]["name"]: t for t in TOOLS_SCHEMA}


def get_tools_for_stage(tool_names: list[str]) -> list[dict]:
    """Return tool schemas for the given tool names."""
    return [_TOOLS_BY_NAME[name] for name in tool_names if name in _TOOLS_BY_NAME]


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    conversation_id: str,
    lead_id: str,
) -> str:
    """Execute a tool call and return a result string for the AI."""
    logger.info(f"Executing tool {tool_name} with args {args} for conversation {conversation_id}")

    if tool_name == "salvar_nome":
        update_lead(lead_id, name=args["name"])
        return f"Nome salvo: {args['name']}"

    elif tool_name == "mudar_stage":
        new_stage = args["stage"]
        update_conversation(conversation_id, stage=new_stage)
        return f"Stage alterado para: {new_stage}"

    elif tool_name == "encaminhar_humano":
        update_conversation(conversation_id, status="converted")
        save_message(
            conversation_id, lead_id, "system",
            f"Lead encaminhado para {args['vendedor']}: {args['motivo']}",
        )
        return f"Lead encaminhado para {args['vendedor']}"

    elif tool_name == "enviar_fotos":
        categoria = args["categoria"]
        save_message(
            conversation_id, lead_id, "system",
            f"Fotos de {categoria} enviadas",
        )
        return f"Fotos de {categoria} enviadas ao lead"

    return f"Tool {tool_name} nao reconhecida"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/app/agent/tools.py
git commit -m "refactor: agent orchestrator loads from agent_profile, tools operate on conversation"
```

---

## Task 7: Refactor Webhook Routing

**Files:**
- Modify: `backend/app/webhook/router.py`
- Modify: `backend/app/webhook/parser.py`

- [ ] **Step 1: Update parser to include channel_id**

Replace the entire content of `backend/app/webhook/parser.py`:

```python
# backend/app/webhook/parser.py
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    from_number: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, interactive, button, video, document
    channel_id: str = ""
    text: str | None = None
    media_id: str | None = None
    media_url: str | None = None
    media_mime: str | None = None
    remote_jid: str | None = None
    push_name: str | None = None


def parse_meta_webhook(payload: dict) -> tuple[list[IncomingMessage], str | None]:
    """Parse Meta Cloud API webhook payload.
    Returns (messages, phone_number_id) so caller can resolve channel.
    """
    messages = []
    phone_number_id = None

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")

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

    return messages, phone_number_id


def parse_evolution_webhook(payload: dict) -> list[IncomingMessage]:
    """Parse Evolution API v2 MESSAGES_UPSERT webhook payload."""
    messages = []

    event = payload.get("event", "")
    if event != "messages.upsert":
        return messages

    data = payload.get("data", {})
    key = data.get("key", {})

    if key.get("fromMe", False):
        return messages

    remote_jid = key.get("remoteJid", "")
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

    if message_type == "conversation":
        text = message_data.get("conversation")
    elif message_type == "extendedTextMessage":
        text = message_data.get("extendedTextMessage", {}).get("text")
    elif message_type == "audioMessage":
        msg_type = "audio"
        audio = message_data.get("audioMessage", {})
        media_url = audio.get("url")
        media_mime = audio.get("mimetype")
    elif message_type == "imageMessage":
        msg_type = "image"
        image = message_data.get("imageMessage", {})
        media_url = image.get("url")
        media_mime = image.get("mimetype")
        text = image.get("caption")
    elif message_type == "videoMessage":
        msg_type = "video"
        video = message_data.get("videoMessage", {})
        media_url = video.get("url")
        media_mime = video.get("mimetype")
        text = video.get("caption")
    elif message_type == "documentMessage":
        msg_type = "document"
        doc = message_data.get("documentMessage", {})
        media_url = doc.get("url")
        media_mime = doc.get("mimetype")
        text = doc.get("caption")
    else:
        text = (
            message_data.get("conversation")
            or message_data.get("extendedTextMessage", {}).get("text")
        )
        if not text:
            return messages

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

- [ ] **Step 2: Rewrite webhook router with dual endpoints**

Replace the entire content of `backend/app/webhook/router.py`:

```python
# backend/app/webhook/router.py
import logging

from fastapi import APIRouter, Request, Query, Response, HTTPException

from app.webhook.parser import parse_meta_webhook, parse_evolution_webhook
from app.channels.service import get_channel, get_channel_by_provider_config
from app.providers.registry import get_provider
from app.buffer.manager import push_to_buffer

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/webhook/meta")
async def verify_meta_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification. Checks verify_token against all meta_cloud channels."""
    if hub_mode != "subscribe":
        return Response(status_code=403)

    # Find channel with matching verify_token
    from app.db.supabase import get_supabase
    sb = get_supabase()
    channels = sb.table("channels").select("*").eq("provider", "meta_cloud").execute().data

    for ch in channels:
        config = ch.get("provider_config", {})
        if config.get("verify_token") == hub_verify_token:
            return Response(content=hub_challenge, media_type="text/plain")

    return Response(status_code=403)


@router.post("/webhook/meta")
async def receive_meta_webhook(request: Request):
    """Receive messages from Meta Cloud API. Resolves channel by phone_number_id."""
    payload = await request.json()
    messages, phone_number_id = parse_meta_webhook(payload)

    if not messages or not phone_number_id:
        return {"status": "ok"}

    # Resolve channel
    channel = get_channel_by_provider_config("phone_number_id", phone_number_id)
    if not channel:
        logger.warning(f"No channel found for phone_number_id={phone_number_id}")
        return {"status": "ok"}

    provider = get_provider(channel)

    for msg in messages:
        msg.channel_id = channel["id"]
        logger.info(f"[Meta] Message from {msg.from_number} on channel {channel['name']}: type={msg.type}")

        # Mark as read
        try:
            await provider.mark_read(msg.message_id)
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Push to buffer
        redis = request.app.state.redis
        await push_to_buffer(redis, msg, channel)

    return {"status": "ok"}


@router.post("/webhook/evolution/{channel_id}")
async def receive_evolution_webhook(channel_id: str, request: Request):
    """Receive messages from Evolution API. Channel identified by URL path."""
    payload = await request.json()
    messages = parse_evolution_webhook(payload)

    if not messages:
        return {"status": "ok"}

    try:
        channel = get_channel(channel_id)
    except Exception:
        logger.warning(f"No channel found for id={channel_id}")
        return {"status": "ok"}

    provider = get_provider(channel)

    for msg in messages:
        msg.channel_id = channel_id
        logger.info(f"[Evolution] Message from {msg.from_number} on channel {channel['name']}: type={msg.type}")

        # Mark as read
        try:
            await provider.mark_read(msg.message_id, remote_jid=msg.remote_jid or "")
        except Exception as e:
            logger.warning(f"Failed to mark read: {e}")

        # Push to buffer
        redis = request.app.state.redis
        await push_to_buffer(redis, msg, channel)

    return {"status": "ok"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/webhook/
git commit -m "refactor: dual webhook endpoints (meta + evolution) with channel routing"
```

---

## Task 8: Refactor Buffer System

**Files:**
- Modify: `backend/app/buffer/manager.py`
- Modify: `backend/app/buffer/processor.py`

- [ ] **Step 1: Update buffer manager to key by channel+phone**

Replace the entire content of `backend/app/buffer/manager.py`:

```python
# backend/app/buffer/manager.py
import asyncio
import logging

import redis.asyncio as aioredis

from app.config import settings
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)

_active_timers: dict[str, asyncio.Task] = {}


async def push_to_buffer(r: aioredis.Redis, msg: IncomingMessage, channel: dict):
    """Push a message to the buffer. Key includes channel_id for isolation."""
    phone = msg.from_number
    channel_id = channel["id"]
    buffer_key = f"buffer:{channel_id}:{phone}"
    lock_key = f"buffer:{channel_id}:{phone}:lock"
    timer_key = f"{channel_id}:{phone}"

    # Build text content (media resolved later)
    if msg.media_id:
        text = msg.text or f"[{msg.type}: media_id={msg.media_id}]"
    elif msg.media_url:
        text = msg.text or f"[{msg.type}: media_url={msg.media_url}]"
    else:
        text = msg.text or ""

    await r.rpush(buffer_key, text)

    has_lock = await r.exists(lock_key)

    if has_lock:
        current_ttl = await r.ttl(lock_key)
        new_ttl = min(
            current_ttl + settings.buffer_extend_timeout,
            settings.buffer_max_timeout,
        )
        await r.expire(lock_key, new_ttl)
        logger.info(f"Buffer extended for {phone} on channel {channel['name']}: TTL now {new_ttl}s")
    else:
        await r.set(lock_key, "1", ex=settings.buffer_base_timeout)
        logger.info(f"Buffer started for {phone} on channel {channel['name']}: {settings.buffer_base_timeout}s")

        if timer_key in _active_timers:
            _active_timers[timer_key].cancel()

        _active_timers[timer_key] = asyncio.create_task(
            _wait_and_flush(r, phone, channel)
        )


async def _wait_and_flush(r: aioredis.Redis, phone: str, channel: dict):
    """Wait for the buffer to expire, then flush."""
    from app.buffer.processor import process_buffered_messages

    channel_id = channel["id"]
    lock_key = f"buffer:{channel_id}:{phone}:lock"
    buffer_key = f"buffer:{channel_id}:{phone}"
    timer_key = f"{channel_id}:{phone}"

    while True:
        await asyncio.sleep(1)
        exists = await r.exists(lock_key)
        if not exists:
            break

    messages = await r.lrange(buffer_key, 0, -1)
    await r.delete(buffer_key)

    _active_timers.pop(timer_key, None)

    if messages:
        combined = "\n".join(messages)
        logger.info(f"Buffer flushed for {phone} on channel {channel['name']}: {len(messages)} messages")
        await process_buffered_messages(phone, combined, channel)
```

- [ ] **Step 2: Update processor to use conversations and providers**

Replace the entire content of `backend/app/buffer/processor.py`:

```python
# backend/app/buffer/processor.py
import asyncio
import logging
import re
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.config import settings
from app.leads.service import get_or_create_lead
from app.conversations.service import (
    get_or_create_conversation, activate_conversation,
    update_conversation, save_message,
)
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.providers.registry import get_provider

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def process_buffered_messages(phone: str, combined_text: str, channel: dict):
    """Process accumulated buffer messages for a specific channel."""
    try:
        provider = get_provider(channel)

        # Resolve any media placeholders
        resolved_text = await _resolve_media(combined_text, provider)

        # Get or create lead (global by phone)
        lead = get_or_create_lead(phone)

        # Get or create conversation (per lead+channel)
        conversation = get_or_create_conversation(lead["id"], channel["id"])

        # Activate conversation if imported/template_sent
        if conversation.get("status") in ("imported", "template_sent"):
            conversation = activate_conversation(conversation["id"])

        # Check if channel has an agent profile
        agent_profile_id = channel.get("agent_profile_id")

        if agent_profile_id:
            # Load agent profile
            from app.db.supabase import get_supabase
            sb = get_supabase()
            profile = (
                sb.table("agent_profiles")
                .select("*")
                .eq("id", agent_profile_id)
                .single()
                .execute()
                .data
            )

            # Enrich conversation with lead data for the agent
            conversation["leads"] = lead

            # Run agent
            response = await run_agent(conversation, profile, resolved_text)

            # Humanize and send
            bubbles = split_into_bubbles(response)
            for bubble in bubbles:
                delay = calculate_typing_delay(bubble)
                await asyncio.sleep(delay)
                await provider.send_text(phone, bubble)
        else:
            # No agent — human-only channel. Save message, no auto-reply.
            save_message(
                conversation["id"], lead["id"], "user", resolved_text,
                conversation.get("stage"),
            )

        # Update last_msg timestamp
        update_conversation(
            conversation["id"],
            last_msg_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.error(f"Error processing messages for {phone} on channel {channel.get('name')}: {e}", exc_info=True)


async def _resolve_media(text: str, provider) -> str:
    """Replace media placeholders with actual content."""
    # Meta-style: [audio: media_id=xxx]
    audio_id_pattern = r"\[audio: media_id=(\S+)\]"
    image_id_pattern = r"\[image: media_id=(\S+)\]"

    # Evolution-style: [audio: media_url=xxx]
    audio_url_pattern = r"\[audio: media_url=(\S+)\]"
    image_url_pattern = r"\[image: media_url=(\S+)\]"

    for pattern in [audio_id_pattern, audio_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            try:
                audio_bytes, content_type = await provider.download_media(media_ref)
                ext = "ogg" if "ogg" in content_type else "mp4"
                transcript = await _get_openai().audio.transcriptions.create(
                    model="whisper-1",
                    file=(f"audio.{ext}", audio_bytes, content_type),
                )
                text = text.replace(match.group(0), f"[audio transcrito: {transcript.text}]")
            except Exception as e:
                logger.warning(f"Failed to transcribe audio {media_ref}: {e}")
                text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for pattern in [image_id_pattern, image_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            try:
                import base64
                image_bytes, content_type = await provider.download_media(media_ref)
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
                description = response.choices[0].message.content
                text = text.replace(match.group(0), f"[imagem recebida: {description}]")
            except Exception as e:
                logger.warning(f"Failed to describe image {media_ref}: {e}")
                text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/buffer/
git commit -m "refactor: buffer keyed by channel+phone, processor uses providers and conversations"
```

---

## Task 9: Simplify Leads Service

**Files:**
- Modify: `backend/app/leads/service.py`
- Modify: `backend/app/leads/router.py`

- [ ] **Step 1: Simplify leads service (remove stage/status ops)**

Replace the entire content of `backend/app/leads/service.py`:

```python
# backend/app/leads/service.py
from typing import Any

from app.db.supabase import get_supabase


def get_or_create_lead(phone: str) -> dict[str, Any]:
    """Get or create a global lead by phone."""
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("phone", phone).execute()

    if result.data:
        return result.data[0]

    new_lead = {"phone": phone}
    result = sb.table("leads").insert(new_lead).execute()
    return result.data[0]


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").update(fields).eq("id", lead_id).execute()
    return result.data[0]


def get_lead(lead_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).single().execute()
    return result.data
```

- [ ] **Step 2: Update leads router to show conversations**

Replace the entire content of `backend/app/leads/router.py`:

```python
# backend/app/leads/router.py
from fastapi import APIRouter, Query

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/leads", tags=["leads"])


@router.get("")
async def list_leads(
    limit: int = Query(50, le=200),
    offset: int = 0,
    search: str | None = None,
):
    sb = get_supabase()
    query = sb.table("leads").select("*")

    if search:
        query = query.or_(f"phone.ilike.%{search}%,name.ilike.%{search}%")

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"data": result.data, "count": len(result.data)}


@router.get("/{lead_id}")
async def get_lead(lead_id: str):
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).single().execute()
    return result.data


@router.get("/{lead_id}/conversations")
async def get_lead_conversations(lead_id: str):
    """Get all conversations for a lead across all channels."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*, channels(id, name, phone, provider)")
        .eq("lead_id", lead_id)
        .order("last_msg_at", desc=True, nullsfirst=False)
        .execute()
    )
    return {"data": result.data}


@router.get("/{lead_id}/messages")
async def get_lead_messages(lead_id: str, limit: int = Query(50, le=200)):
    """Get all messages for a lead (across all conversations)."""
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("*, conversations(channel_id, stage)")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return {"data": result.data}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/leads/
git commit -m "refactor: simplify leads service, add conversations endpoint"
```

---

## Task 10: Refactor Campaign System

**Files:**
- Modify: `backend/app/campaign/router.py`
- Modify: `backend/app/campaign/worker.py`
- Modify: `backend/app/campaign/importer.py`

- [ ] **Step 1: Update campaign router with channel_id validation**

Replace the entire content of `backend/app/campaign/router.py`:

```python
# backend/app/campaign/router.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase
from app.campaign.importer import parse_csv
from app.channels.service import get_channel

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    channel_id: str
    template_name: str
    template_params: dict | None = None
    send_interval_min: int = 3
    send_interval_max: int = 8


@router.get("")
async def list_campaigns():
    sb = get_supabase()
    result = (
        sb.table("campaigns")
        .select("*, channels(id, name, phone)")
        .order("created_at", desc=True)
        .execute()
    )
    return {"data": result.data}


@router.post("")
async def create_campaign(campaign: CampaignCreate):
    # Validate channel is meta_cloud
    channel = get_channel(campaign.channel_id)
    if channel["provider"] != "meta_cloud":
        raise HTTPException(400, "Campanhas so podem ser criadas em channels Meta Cloud API")

    sb = get_supabase()
    result = sb.table("campaigns").insert(campaign.model_dump()).execute()
    return result.data[0]


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str):
    sb = get_supabase()
    result = (
        sb.table("campaigns")
        .select("*, channels(id, name, phone)")
        .eq("id", campaign_id)
        .single()
        .execute()
    )
    return result.data


@router.post("/{campaign_id}/import")
async def import_leads(campaign_id: str, file: UploadFile = File(...)):
    content = await file.read()
    result = parse_csv(content)

    if not result.valid:
        raise HTTPException(400, "Nenhum numero valido encontrado no CSV")

    sb = get_supabase()

    # Get campaign to know the channel_id
    campaign = sb.table("campaigns").select("channel_id").eq("id", campaign_id).single().execute().data
    channel_id = campaign["channel_id"]

    created = 0
    for phone in result.valid:
        try:
            # Create global lead
            lead_result = sb.table("leads").select("id").eq("phone", phone).execute()
            if lead_result.data:
                lead_id = lead_result.data[0]["id"]
            else:
                lead_result = sb.table("leads").insert({"phone": phone}).execute()
                lead_id = lead_result.data[0]["id"]

            # Create conversation for this lead+channel
            sb.table("conversations").insert({
                "lead_id": lead_id,
                "channel_id": channel_id,
                "campaign_id": campaign_id,
                "status": "imported",
                "stage": "pending",
            }).execute()
            created += 1

        except Exception:
            # Duplicate lead+channel pair, skip
            pass

    sb.table("campaigns").update({"total_leads": created}).eq("id", campaign_id).execute()

    return {
        "imported": created,
        "invalid": len(result.invalid),
        "invalid_numbers": result.invalid[:20],
    }


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str):
    sb = get_supabase()

    campaign = sb.table("campaigns").select("*").eq("id", campaign_id).single().execute().data

    if campaign["status"] == "running":
        raise HTTPException(400, "Campanha ja esta rodando")

    # Get conversations for this campaign that haven't been sent
    convs = (
        sb.table("conversations")
        .select("id")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .execute()
        .data
    )

    if not convs:
        raise HTTPException(400, "Nenhum lead pendente para envio")

    sb.table("campaigns").update({"status": "running"}).eq("id", campaign_id).execute()

    return {"status": "started", "leads_queued": len(convs)}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str):
    sb = get_supabase()
    sb.table("campaigns").update({"status": "paused"}).eq("id", campaign_id).execute()
    return {"status": "paused"}
```

- [ ] **Step 2: Update campaign worker to use providers**

Replace the entire content of `backend/app/campaign/worker.py`:

```python
# backend/app/campaign/worker.py
import asyncio
import logging
import random

from app.db.supabase import get_supabase
from app.channels.service import get_channel
from app.providers.registry import get_provider

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
    sb = get_supabase()

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
    sb = get_supabase()
    campaign_id = campaign["id"]
    channel_id = campaign.get("channel_id")

    if not channel_id:
        logger.error(f"Campaign {campaign_id} has no channel_id")
        return

    channel = get_channel(channel_id)
    provider = get_provider(channel)

    # Get next batch of conversations to send
    convs = (
        sb.table("conversations")
        .select("id, lead_id, leads(id, phone)")
        .eq("campaign_id", campaign_id)
        .eq("status", "imported")
        .limit(10)
        .execute()
        .data
    )

    if not convs:
        sb.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute()
        logger.info(f"Campaign {campaign_id} completed")
        return

    for conv in convs:
        # Check if campaign is still running
        current = sb.table("campaigns").select("status").eq("id", campaign_id).single().execute().data
        if current["status"] != "running":
            logger.info(f"Campaign {campaign_id} paused, stopping")
            return

        lead = conv.get("leads", {})
        phone = lead.get("phone") if lead else None
        if not phone:
            continue

        try:
            await provider.send_template(
                to=phone,
                template_name=campaign["template_name"],
                components=campaign.get("template_params", {}).get("components") if campaign.get("template_params") else None,
            )
            sb.table("conversations").update({"status": "template_sent"}).eq("id", conv["id"]).execute()
            sb.rpc("increment_campaign_sent", {"campaign_id_param": campaign_id}).execute()
            logger.info(f"Template sent to {phone}")

        except Exception as e:
            logger.error(f"Failed to send to {phone}: {e}")
            sb.table("conversations").update({"status": "failed"}).eq("id", conv["id"]).execute()

        interval = random.randint(
            campaign.get("send_interval_min", 3),
            campaign.get("send_interval_max", 8),
        )
        await asyncio.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/campaign/
git commit -m "refactor: campaigns use channel_id, worker resolves provider per channel"
```

---

## Task 11: Update Config & Main

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Simplify config (remove hardcoded Meta credentials)**

Replace the entire content of `backend/app/config.py`:

```python
# backend/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


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

- [ ] **Step 2: Update main.py to register all new routers**

Replace the entire content of `backend/app/main.py`:

```python
# backend/app/main.py
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
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.campaign.router import router as campaign_router
from app.channels.router import router as channels_router
from app.agent_profiles.router import router as agent_profiles_router

app.include_router(webhook_router)
app.include_router(leads_router)
app.include_router(campaign_router)
app.include_router(channels_router)
app.include_router(agent_profiles_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py backend/app/main.py
git commit -m "refactor: simplify config, register all new routers in main"
```

---

## Task 12: Seed ValerIA Agent Profile

**Files:**
- Create: `backend/migrations/008_seed_valeria_profile.sql`

This task creates the initial agent profile from the current hardcoded ValerIA prompts so existing behavior is preserved.

- [ ] **Step 1: Create seed script**

Create `backend/scripts/seed_valeria_profile.py`:

```python
"""Seed the default ValerIA agent profile from existing prompts."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.supabase import get_supabase
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.secretaria import SECRETARIA_PROMPT
from app.agent.prompts.atacado import ATACADO_PROMPT
from app.agent.prompts.private_label import PRIVATE_LABEL_PROMPT
from app.agent.prompts.exportacao import EXPORTACAO_PROMPT
from app.agent.prompts.consumo import CONSUMO_PROMPT

# Read base prompt template (without lead-specific data)
from datetime import datetime, timezone, timedelta
TZ_BR = timezone(timedelta(hours=-3))
base_prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(TZ_BR))

stages = {
    "secretaria": {
        "prompt": SECRETARIA_PROMPT,
        "model": "gpt-4.1",
        "tools": ["salvar_nome", "mudar_stage"],
    },
    "atacado": {
        "prompt": ATACADO_PROMPT,
        "model": "gpt-4.1",
        "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
    },
    "private_label": {
        "prompt": PRIVATE_LABEL_PROMPT,
        "model": "gpt-4.1",
        "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
    },
    "exportacao": {
        "prompt": EXPORTACAO_PROMPT,
        "model": "gpt-4.1-mini",
        "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano"],
    },
    "consumo": {
        "prompt": CONSUMO_PROMPT,
        "model": "gpt-4.1-mini",
        "tools": ["salvar_nome"],
    },
}

sb = get_supabase()
result = sb.table("agent_profiles").insert({
    "name": "ValerIA Cafe Canastra",
    "model": "gpt-4.1",
    "stages": stages,
    "base_prompt": base_prompt,
}).execute()

print(f"Created agent profile: {result.data[0]['id']}")
print("Now create a channel and assign this profile ID to it.")
```

- [ ] **Step 2: Run the seed script**

```bash
cd backend && python scripts/seed_valeria_profile.py
```

Expected: Prints the created profile ID.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/seed_valeria_profile.py
git commit -m "feat: add seed script for ValerIA agent profile"
```

---

## Task 13: Frontend — TypeScript Types

**Files:**
- Modify: `crm/src/lib/types.ts`

- [ ] **Step 1: Add Channel, AgentProfile, Conversation types**

Add to the end of `crm/src/lib/types.ts`:

```typescript
export interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profiles?: { id: string; name: string } | null;
  is_active: boolean;
  created_at: string;
}

export interface AgentProfile {
  id: string;
  name: string;
  model: string;
  stages: Record<string, {
    prompt: string;
    model: string;
    tools: string[];
  }>;
  base_prompt: string;
  created_at: string;
  updated_at: string;
}

export interface Conversation {
  id: string;
  lead_id: string;
  channel_id: string;
  stage: string;
  status: string;
  campaign_id: string | null;
  last_msg_at: string | null;
  created_at: string;
  leads?: Lead;
  channels?: { id: string; name: string; phone: string; provider: string };
}
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/lib/types.ts
git commit -m "feat: add Channel, AgentProfile, Conversation TypeScript types"
```

---

## Task 14: Frontend — API Routes for Channels & Profiles

**Files:**
- Create: `crm/src/app/api/channels/route.ts`
- Create: `crm/src/app/api/channels/[id]/route.ts`
- Create: `crm/src/app/api/agent-profiles/route.ts`
- Create: `crm/src/app/api/agent-profiles/[id]/route.ts`

- [ ] **Step 1: Check Next.js docs for API route conventions**

Read: `crm/node_modules/next/dist/docs/` for any route handler conventions.

- [ ] **Step 2: Create channels API route**

```typescript
// crm/src/app/api/channels/route.ts
import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET() {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("channels")
    .select("*, agent_profiles(id, name)")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}

export async function POST(request: Request) {
  const body = await request.json();
  const supabase = await createClient();
  const { data, error } = await supabase.from("channels").insert(body).select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}
```

- [ ] **Step 3: Create channels/[id] API route**

```typescript
// crm/src/app/api/channels/[id]/route.ts
import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("channels")
    .select("*, agent_profiles(id, name)")
    .eq("id", id)
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 404 });
  return NextResponse.json(data);
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await createClient();
  const { data, error } = await supabase.from("channels").update(body).eq("id", id).select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { error } = await supabase.from("channels").delete().eq("id", id);

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ status: "deleted" });
}
```

- [ ] **Step 4: Create agent-profiles API route**

```typescript
// crm/src/app/api/agent-profiles/route.ts
import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET() {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("agent_profiles")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ data });
}

export async function POST(request: Request) {
  const body = await request.json();
  const supabase = await createClient();
  const { data, error } = await supabase.from("agent_profiles").insert(body).select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}
```

- [ ] **Step 5: Create agent-profiles/[id] API route**

```typescript
// crm/src/app/api/agent-profiles/[id]/route.ts
import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { data, error } = await supabase.from("agent_profiles").select("*").eq("id", id).single();

  if (error) return NextResponse.json({ error: error.message }, { status: 404 });
  return NextResponse.json(data);
}

export async function PUT(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await request.json();
  const supabase = await createClient();
  const { data, error } = await supabase.from("agent_profiles").update(body).eq("id", id).select().single();

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json(data);
}

export async function DELETE(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await createClient();
  const { error } = await supabase.from("agent_profiles").delete().eq("id", id);

  if (error) return NextResponse.json({ error: error.message }, { status: 400 });
  return NextResponse.json({ status: "deleted" });
}
```

- [ ] **Step 6: Commit**

```bash
git add crm/src/app/api/channels/ crm/src/app/api/agent-profiles/
git commit -m "feat: add API routes for channels and agent profiles"
```

---

## Task 15: Frontend — Channels Page

**Files:**
- Create: `crm/src/app/(authenticated)/canais/page.tsx`
- Modify: `crm/src/components/sidebar.tsx`

- [ ] **Step 1: Add Canais and Agentes to sidebar navigation**

In `crm/src/components/sidebar.tsx`, add two new entries to `NAV_ITEMS` array after the "Configuracoes" entry. Add "Canais" with a phone icon and "Agentes" with a CPU/bot icon. The `href` values should be `/canais` and `/agentes` respectively.

- [ ] **Step 2: Create the Canais page**

Create `crm/src/app/(authenticated)/canais/page.tsx` with:
- List all channels in a table/card grid
- Each channel shows: name, phone, provider badge (meta_cloud=green, evolution=blue), agent profile name or "Humano", status toggle
- "Novo Canal" button opens a modal/form with: name, phone, provider select, provider_config fields (dynamic based on provider), agent profile dropdown
- Edit and delete actions per channel
- Provider config fields:
  - meta_cloud: phone_number_id, access_token, app_secret, verify_token
  - evolution: api_url, api_key, instance

Follow existing CRM styling patterns (dark theme, olive accent, same font sizes and spacing as other pages).

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/(authenticated)/canais/ crm/src/components/sidebar.tsx
git commit -m "feat: add channels management page (canais)"
```

---

## Task 16: Frontend — Agent Profiles Page

**Files:**
- Create: `crm/src/app/(authenticated)/agentes/page.tsx`

- [ ] **Step 1: Create the Agentes page**

Create `crm/src/app/(authenticated)/agentes/page.tsx` with:
- List all agent profiles in cards
- Each card shows: name, model, number of stages, "Usado por X canais"
- "Novo Perfil" button opens form with: name, base model, base prompt textarea
- Stage editor: add/remove stages, each stage has name, prompt textarea, model select, tools checkboxes
- Edit and delete actions
- Follow existing CRM styling patterns

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/(authenticated)/agentes/
git commit -m "feat: add agent profiles management page (agentes)"
```

---

## Task 17: Frontend — Update Conversations Page

**Files:**
- Modify: `crm/src/app/(authenticated)/conversas/page.tsx`

- [ ] **Step 1: Add channel filter to conversations page**

Update the conversations page to:
- Fetch channels list and show a channel filter dropdown at the top
- Load conversations from Supabase `conversations` table (with leads and channels joins) instead of Evolution-specific API
- Show channel name/phone badge on each conversation in the list
- Chat view sends messages through the backend API (which resolves the correct provider)
- For human-only channels (no agent profile), the chat works as a manual messaging interface

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/(authenticated)/conversas/
git commit -m "feat: update conversations page with channel filter and multi-provider support"
```

---

## Task 18: Frontend — Update Campaigns Page

**Files:**
- Modify: `crm/src/app/(authenticated)/campanhas/page.tsx`
- Modify: `crm/src/components/create-campaign-modal.tsx` (if exists)

- [ ] **Step 1: Add channel selector to campaign creation**

Update campaign creation flow to:
- Fetch channels list (filter to `provider = 'meta_cloud'` only)
- Add a channel selector dropdown as the first field in campaign creation
- Pass `channel_id` when creating campaign
- Show channel name in campaign cards/table

- [ ] **Step 2: Commit**

```bash
git add crm/src/app/(authenticated)/campanhas/ crm/src/components/create-campaign-modal.tsx
git commit -m "feat: add channel selector to campaign creation (meta_cloud only)"
```

---

## Task 19: Add Conversations API Route (Chat Send)

**Files:**
- Create: `crm/src/app/api/conversations/[id]/send/route.ts`

- [ ] **Step 1: Create send message endpoint**

This endpoint allows the CRM user (seller) to send a message through a channel manually.

```typescript
// crm/src/app/api/conversations/[id]/send/route.ts
import { createClient } from "@/lib/supabase/server";
import { NextResponse } from "next/server";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id: conversationId } = await params;
  const { text } = await request.json();

  if (!text?.trim()) {
    return NextResponse.json({ error: "text is required" }, { status: 400 });
  }

  const supabase = await createClient();

  // Get conversation with channel and lead
  const { data: conv, error: convError } = await supabase
    .from("conversations")
    .select("*, leads(id, phone), channels(id, provider, provider_config)")
    .eq("id", conversationId)
    .single();

  if (convError || !conv) {
    return NextResponse.json({ error: "Conversation not found" }, { status: 404 });
  }

  // Call backend to send (backend resolves provider)
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
  const response = await fetch(`${backendUrl}/api/channels/${conv.channel_id}/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      conversation_id: conversationId,
      to: conv.leads?.phone,
      text,
    }),
  });

  if (!response.ok) {
    return NextResponse.json({ error: "Failed to send" }, { status: 500 });
  }

  return NextResponse.json({ status: "sent" });
}
```

- [ ] **Step 2: Add send endpoint to backend channels router**

Add to `backend/app/channels/router.py`:

```python
@router.post("/{channel_id}/send")
async def send_message(channel_id: str, body: dict):
    """Send a message through a channel (used by CRM for human chat)."""
    from app.providers.registry import get_provider
    from app.conversations.service import save_message

    channel = get_channel(channel_id)
    provider = get_provider(channel)

    to = body["to"]
    text = body["text"]
    conversation_id = body.get("conversation_id")

    await provider.send_text(to, text)

    if conversation_id:
        # Save as assistant message with sent_by=seller
        from app.db.supabase import get_supabase
        sb = get_supabase()
        conv = sb.table("conversations").select("lead_id, stage").eq("id", conversation_id).single().execute().data
        save_message(conversation_id, conv["lead_id"], "assistant", text, conv.get("stage"))

    return {"status": "sent"}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/api/conversations/ backend/app/channels/router.py
git commit -m "feat: add send message endpoint for CRM human chat"
```

---

## Task 20: Final Integration Test

- [ ] **Step 1: Start the backend and verify health**

```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

Visit: `http://localhost:8000/health`
Expected: `{"status": "ok"}`

- [ ] **Step 2: Test channels CRUD via API**

```bash
# Create a channel
curl -X POST http://localhost:8000/api/channels \
  -H "Content-Type: application/json" \
  -d '{"name":"ValerIA","phone":"5534999999999","provider":"meta_cloud","provider_config":{"phone_number_id":"123","access_token":"test","verify_token":"test"}}'

# List channels
curl http://localhost:8000/api/channels
```

- [ ] **Step 3: Test agent profiles CRUD via API**

```bash
# List profiles
curl http://localhost:8000/api/agent-profiles

# Expected: ValerIA Cafe Canastra profile from seed
```

- [ ] **Step 4: Start CRM and verify pages**

```bash
cd crm && npm run dev
```

Visit: `http://localhost:3000/canais` — Should show channels page
Visit: `http://localhost:3000/agentes` — Should show agent profiles page

- [ ] **Step 5: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration fixes for multi-channel CRM"
```
