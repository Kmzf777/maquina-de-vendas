# Backend Recuperar Lead — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sincronizar `backend-recuperar-lead` com os padrões arquiteturais do `backend/` (produção) e finalizar os componentes que divergiram durante o desenvolvimento paralelo.

**Architecture:** `backend-recuperar-lead` foi criado antes de o `backend/` evoluir para: (a) provider registry em vez de whatsapp factory, (b) Gemini em vez de OpenAI, (c) histórico de mensagens scoped por `conversation_id` em vez de `lead_id`. Este plano sincroniza essas divergências sem alterar a lógica SDR exclusiva do serviço (human_control, lead_context, prompt secretaria outbound).

**Tech Stack:** FastAPI, Python 3.12, Supabase (shared DB), Redis, Gemini via OpenAI-compatible API, Meta Cloud API, Docker Swarm + Traefik.

---

## Mapa de Arquivos

### Criar
- `backend-recuperar-lead/app/providers/__init__.py`
- `backend-recuperar-lead/app/providers/base.py` — interface abstrata WhatsAppProvider
- `backend-recuperar-lead/app/providers/meta_cloud.py` — MetaCloudProvider
- `backend-recuperar-lead/app/providers/evolution.py` — EvolutionProvider
- `backend-recuperar-lead/app/providers/registry.py` — `get_provider(channel)`

### Modificar
- `backend-recuperar-lead/app/config.py` — trocar `openai_api_key` por `gemini_api_key`
- `backend-recuperar-lead/app/buffer/processor.py` — provider registry, dedup, activate_conversation, salvar user message antes do agent
- `backend-recuperar-lead/app/agent/orchestrator.py` — Gemini model, conversations.service para histórico/save, remover save de user message (passa para processor)
- `backend-recuperar-lead/app/outbound/dispatcher.py` — set `lead.status=template_sent`, criar conversation com `status=template_sent`
- `backend-recuperar-lead/docker-compose.yml` — Swarm-ready com Traefik labels e rede externa
- `backend-recuperar-lead/tests/test_processor_human_control.py` — atualizar mocks para novo processor
- `backend-recuperar-lead/tests/test_dispatcher.py` — atualizar para verificar status update + conversation

---

## Task 1: Criar Provider Registry

**Contexto:** O `backend/` (produção) substituiu o `app/whatsapp/factory.py` por um registry de providers (`app/providers/`). O processor precisa usar `get_provider(channel)` em vez de `get_whatsapp_client(channel)`.

**Files:**
- Create: `backend-recuperar-lead/app/providers/__init__.py`
- Create: `backend-recuperar-lead/app/providers/base.py`
- Create: `backend-recuperar-lead/app/providers/meta_cloud.py`
- Create: `backend-recuperar-lead/app/providers/evolution.py`
- Create: `backend-recuperar-lead/app/providers/registry.py`

- [ ] **Step 1: Criar `app/providers/__init__.py`**

```python
# backend-recuperar-lead/app/providers/__init__.py
```
(arquivo vazio)

- [ ] **Step 2: Criar `app/providers/base.py`**

```python
# backend-recuperar-lead/app/providers/base.py
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

- [ ] **Step 3: Criar `app/providers/meta_cloud.py`**

```python
# backend-recuperar-lead/app/providers/meta_cloud.py
import httpx

from app.providers.base import WhatsAppProvider

HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


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
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
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
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.get(
                f"{self._media_base_url()}/{media_ref}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            media_url = resp.json()["url"]

            resp = await client.get(media_url)
            resp.raise_for_status()
            return resp.content, resp.headers.get(
                "content-type", "application/octet-stream"
            )
```

- [ ] **Step 4: Criar `app/providers/evolution.py`**

```python
# backend-recuperar-lead/app/providers/evolution.py
import httpx

from app.providers.base import WhatsAppProvider

HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


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
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
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
            "Evolution API does not support Meta-style templates."
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
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.get(media_ref)
            resp.raise_for_status()
            return resp.content, resp.headers.get(
                "content-type", "application/octet-stream"
            )
```

- [ ] **Step 5: Criar `app/providers/registry.py`**

```python
# backend-recuperar-lead/app/providers/registry.py
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

- [ ] **Step 6: Verificar que os imports estão corretos**

```bash
cd backend-recuperar-lead && python -c "from app.providers.registry import get_provider; print('OK')"
```
Esperado: `OK`

- [ ] **Step 7: Commit**

```bash
git add backend-recuperar-lead/app/providers/
git commit -m "feat(recuperar-lead): add providers registry (sync with production backend)"
```

---

## Task 2: Atualizar Config para Gemini

**Contexto:** O `backend/` trocou OpenAI por Gemini (via API OpenAI-compatible). O `backend-recuperar-lead` precisa usar `GEMINI_API_KEY`. A `openai_api_key` é removida do config.

**Files:**
- Modify: `backend-recuperar-lead/app/config.py`
- Modify: `backend-recuperar-lead/.env.example`

- [ ] **Step 1: Escrever o teste que falhará**

```python
# Em backend-recuperar-lead/tests/test_config.py — adicionar ao final:
def test_gemini_api_key_configured():
    from app.config import Settings
    s = Settings(
        gemini_api_key="test-gemini",
        supabase_url="http://test",
        supabase_service_key="test",
    )
    assert s.gemini_api_key == "test-gemini"
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_config.py::test_gemini_api_key_configured -v
```
Esperado: `FAILED` — `ValidationError: openai_api_key field required` ou similar.

- [ ] **Step 3: Atualizar `app/config.py`**

Substituir o campo `openai_api_key` por `gemini_api_key`:

```python
# backend-recuperar-lead/app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Evolution API (optional — per-channel config used instead)
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""

    # Gemini (via OpenAI-compatible API)
    gemini_api_key: str

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

    # Meta Cloud API — used by outbound dispatcher
    meta_access_token: str = ""
    meta_phone_number_id: str = ""

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

- [ ] **Step 4: Atualizar `.env.example`**

```
GEMINI_API_KEY=your-gemini-api-key
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key
REDIS_URL=redis://redis:6379
META_ACCESS_TOKEN=your-meta-access-token
META_PHONE_NUMBER_ID=your-phone-number-id
FRONTEND_URL=https://canastrainteligencia.com
API_BASE_URL=https://sdr.canastrainteligencia.com
```

- [ ] **Step 5: Rodar o teste para confirmar que passa**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_config.py::test_gemini_api_key_configured -v
```
Esperado: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend-recuperar-lead/app/config.py backend-recuperar-lead/.env.example
git commit -m "feat(recuperar-lead): switch to Gemini API key (sync with production)"
```

---

## Task 3: Reescrever Buffer Processor

**Contexto:** O `backend/app/buffer/processor.py` (produção) evoluiu muito. O recuperar-lead precisa:
1. Usar `get_provider(channel)` em vez de `get_whatsapp_client`
2. Adicionar dedup (`_is_recent_duplicate`) para evitar duplo-processamento
3. Usar `activate_conversation` (conversations.service) em vez de `activate_lead` (leads.service)
4. Salvar a mensagem do user ANTES de rodar o agent (o orchestrator não deve mais salvar o user message)
5. Manter o check de `human_control` (exclusivo do recuperar-lead)
6. Manter a pausa de cadência quando o lead responde

**Files:**
- Modify: `backend-recuperar-lead/app/buffer/processor.py`
- Test: `backend-recuperar-lead/tests/test_processor_human_control.py`

- [ ] **Step 1: Escrever o teste que falhará**

Substituir o conteúdo de `tests/test_processor_human_control.py`:

```python
# backend-recuperar-lead/tests/test_processor_human_control.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.mark.asyncio
async def test_human_control_skips_agent():
    """When lead.human_control is True, agent should NOT be called."""
    lead = {
        "id": "lead-123",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "human_control": True,
        "name": "João",
    }
    channel = {
        "id": "channel-1",
        "is_active": True,
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    conversation = {
        "id": "conv-1",
        "lead_id": "lead-123",
        "channel_id": "channel-1",
        "stage": "atacado",
        "status": "active",
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conversation), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"):

        mock_provider = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi quero comprar", "channel-1")

        mock_agent.assert_not_called()
        # user message saved even under human_control
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert args[2] == "user"  # role is "user"


@pytest.mark.asyncio
async def test_agent_called_when_no_human_control():
    """When lead.human_control is False and agent_profile present, agent runs."""
    lead = {
        "id": "lead-456",
        "phone": "+5511888888888",
        "stage": "secretaria",
        "status": "active",
        "human_control": False,
        "name": None,
    }
    channel = {
        "id": "channel-2",
        "is_active": True,
        "agent_profiles": {"id": "p2", "stages": {"secretaria": {"prompt": "test", "model": "gemini-2.0-flash", "tools": []}}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    conversation = {
        "id": "conv-2",
        "lead_id": "lead-456",
        "channel_id": "channel-2",
        "stage": "secretaria",
        "status": "active",
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conversation), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent", return_value="Oi! Como posso ajudar?") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511888888888", "oi", "channel-2")

        mock_agent.assert_called_once()
        # user message saved before agent
        assert mock_save.call_count >= 1
        first_save_args = mock_save.call_args_list[0][0]
        assert first_save_args[2] == "user"
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_processor_human_control.py -v
```
Esperado: `FAILED` — `ImportError` ou `AssertionError` porque o processor ainda usa o factory antigo.

- [ ] **Step 3: Reescrever `app/buffer/processor.py`**

```python
# backend-recuperar-lead/app/buffer/processor.py
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI

from app.config import settings
from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.conversations.service import (
    get_or_create_conversation, activate_conversation,
    update_conversation, save_message,
)
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.providers.registry import get_provider
from app.channels.service import get_channel_by_id
from app.cadence.service import get_active_enrollment, pause_enrollment
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def _is_recent_duplicate(
    conversation_id: str, content: str, role: str, window_seconds: int = 30
) -> bool:
    """Return True if an identical message was saved in this conversation within the last N seconds."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("id")
        .eq("conversation_id", conversation_id)
        .eq("role", role)
        .eq("content", content)
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


async def process_buffered_messages(
    phone: str, combined_text: str, channel_id: str = ""
):
    """Process accumulated buffer messages for a lead on a specific channel."""
    try:
        lead = get_or_create_lead(phone)
        channel = get_channel_by_id(channel_id) if channel_id else None
        if not channel:
            logger.warning(f"No channel found for {phone} (channel_id={channel_id}), skipping")
            return

        provider = get_provider(channel)
        conversation = get_or_create_conversation(lead["id"], channel_id)
    except Exception as e:
        logger.error(f"Fatal setup error for {phone}: {e}", exc_info=True)
        return

    # Activate conversation when lead first responds after template dispatch
    if conversation.get("status") in ("imported", "template_sent"):
        try:
            conversation = activate_conversation(conversation["id"])
        except Exception as e:
            logger.warning(f"Failed to activate conversation {conversation['id']}: {e}")

    # Resolve media placeholders
    try:
        resolved_text = await _resolve_media(combined_text, provider)
    except Exception as e:
        logger.warning(f"Failed to resolve media for {phone}: {e}")
        resolved_text = combined_text

    # Dedup: skip if this exact message was already processed recently
    if _is_recent_duplicate(conversation["id"], resolved_text, "user"):
        logger.warning(f"Duplicate user message detected for {phone}, skipping")
        return

    # Pause cadence if lead is enrolled in one
    try:
        enrollment = get_active_enrollment(lead["id"])
        if enrollment:
            pause_enrollment(enrollment["id"])
            logger.info(f"[CADENCE] Lead {phone} responded — pausing enrollment")
    except Exception as e:
        logger.warning(f"Failed to pause cadence for {phone}: {e}")

    # Always save the incoming user message
    try:
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save user message for {phone}: {e}", exc_info=True)
        return

    # If human already took control, stop here — message is saved, agent skipped
    if lead.get("human_control"):
        logger.info(f"[HUMAN CONTROL] Lead {phone} is under human control — agent skipped")
        _update_last_msg(conversation["id"])
        return

    # Check if channel has an agent profile
    agent_profile = channel.get("agent_profiles")
    if not agent_profile:
        logger.info(f"No agent profile for channel {channel_id}, human-only mode")
        _update_last_msg(conversation["id"])
        return

    # Run AI agent
    try:
        conversation["leads"] = lead
        response = await run_agent(conversation, resolved_text)
    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        _update_last_msg(conversation["id"])
        return

    # Save assistant response
    try:
        save_message(
            conversation["id"], lead["id"], "assistant",
            response, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save assistant message for {phone}: {e}", exc_info=True)

    # Send bubbles
    bubbles = split_into_bubbles(response)
    for bubble in bubbles:
        delay = calculate_typing_delay(bubble)
        await asyncio.sleep(delay)
        try:
            await provider.send_text(phone, bubble)
        except Exception as e:
            logger.error(f"Failed to send bubble to {phone}: {e}", exc_info=True)
            break

    _update_last_msg(conversation["id"])


def _update_last_msg(conversation_id: str) -> None:
    try:
        update_conversation(
            conversation_id,
            last_msg_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.warning(f"Failed to update last_msg_at for {conversation_id}: {e}")


async def _resolve_media(text: str, provider) -> str:
    """Replace media placeholders with actual content using Gemini."""
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
                    model="gemini-3-flash-preview",
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
                    model="gemini-3-flash-preview",
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

- [ ] **Step 4: Rodar os testes para confirmar que passam**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_processor_human_control.py -v
```
Esperado: `PASSED` (ambos os testes)

- [ ] **Step 5: Commit**

```bash
git add backend-recuperar-lead/app/buffer/processor.py backend-recuperar-lead/tests/test_processor_human_control.py
git commit -m "feat(recuperar-lead): rewrite processor — provider registry, dedup, human_control, activate_conversation"
```

---

## Task 4: Atualizar Orchestrator para Gemini + Conversations Service

**Contexto:** O `backend/` usa Gemini via API compatível com OpenAI. O orchestrator do recuperar-lead usa OpenAI. Além disso, o histórico de mensagens deve ser scoped por `conversation_id` (não `lead_id`) e o orchestrator NÃO deve mais salvar o user message (o processor já faz isso).

**Files:**
- Modify: `backend-recuperar-lead/app/agent/orchestrator.py`
- Test: `backend-recuperar-lead/tests/test_base_prompt.py` (apenas verificar que não quebra)

- [ ] **Step 1: Verificar o teste existente**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_base_prompt.py -v
```
Anotar se passa ou falha antes de modificar.

- [ ] **Step 2: Reescrever `app/agent/orchestrator.py`**

```python
# backend-recuperar-lead/app/agent/orchestrator.py
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
from app.conversations.service import get_history
from app.agent.token_tracker import track_token_usage

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

TZ_BR = timezone(timedelta(hours=-3))

STAGE_PROMPTS = {
    "secretaria": SECRETARIA_PROMPT,
    "atacado": ATACADO_PROMPT,
    "private_label": PRIVATE_LABEL_PROMPT,
    "exportacao": EXPORTACAO_PROMPT,
    "consumo": CONSUMO_PROMPT,
}

STAGE_MODELS = {
    "secretaria": "gemini-2.5-flash-preview-04-17",
    "atacado": "gemini-2.5-flash-preview-04-17",
    "private_label": "gemini-2.5-flash-preview-04-17",
    "exportacao": "gemini-2.0-flash",
    "consumo": "gemini-2.0-flash",
}


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def build_system_prompt(
    lead: dict, stage: str, lead_context: dict | None = None
) -> str:
    now = datetime.now(TZ_BR)
    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
        lead_context=lead_context,
    )
    stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)
    return base + "\n\n" + stage_prompt


async def run_agent(
    conversation: dict,
    user_text: str,
    lead_context: dict | None = None,
) -> str:
    """Run the SDR AI agent for a conversation and return the response text.

    NOTE: The caller (processor) is responsible for saving the user message
    BEFORE calling run_agent. This function only saves the assistant message.
    """
    stage = conversation.get("stage", "secretaria")
    lead = conversation.get("leads", {}) or {}
    lead_id = lead.get("id") or conversation.get("lead_id")
    conversation_id = conversation["id"]

    model = STAGE_MODELS.get(stage, "gemini-2.0-flash")
    tools = get_tools_for_stage(stage)
    system_prompt = build_system_prompt(lead, stage, lead_context=lead_context)

    # Build message history scoped by conversation_id (not lead_id)
    history = get_history(conversation_id, limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    # Call Gemini via OpenAI-compatible API
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=1024,
    )

    if response.usage:
        track_token_usage(
            lead_id=lead_id,
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message

    # Process tool calls
    while message.tool_calls:
        messages.append(message.model_dump())
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)
            result = await execute_tool(
                func_name, func_args, lead_id, lead.get("phone", "")
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
            max_tokens=1024,
        )
        if response.usage:
            track_token_usage(
                lead_id=lead_id,
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        message = response.choices[0].message

    assistant_text = message.content or ""
    logger.info(
        f"SDR agent response for conv {conversation_id} (stage={stage}): {assistant_text[:100]}..."
    )
    return assistant_text
```

- [ ] **Step 3: Verificar que o teste de base_prompt ainda passa**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_base_prompt.py -v
```
Esperado: `PASSED`

- [ ] **Step 4: Verificar importação**

```bash
cd backend-recuperar-lead && python -c "from app.agent.orchestrator import run_agent; print('OK')"
```
Esperado: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend-recuperar-lead/app/agent/orchestrator.py
git commit -m "feat(recuperar-lead): align orchestrator — Gemini model, conversation-scoped history"
```

---

## Task 5: Corrigir Dispatcher — Status `template_sent`

**Contexto:** Quando o dispatcher envia o template, precisa atualizar o lead para `status=template_sent` e criar um registro de conversation com `status=template_sent`. O processor verifica esse status para chamar `activate_conversation` quando o lead responde.

**Files:**
- Modify: `backend-recuperar-lead/app/outbound/dispatcher.py`
- Modify: `backend-recuperar-lead/tests/test_dispatcher.py`

- [ ] **Step 1: Escrever o teste que falhará**

Substituir `tests/test_dispatcher.py`:

```python
# backend-recuperar-lead/tests/test_dispatcher.py
from unittest.mock import AsyncMock, patch, MagicMock
import pytest


@pytest.mark.asyncio
async def test_dispatch_sends_template_saves_message_and_sets_status():
    """dispatch_to_lead should POST to Meta API, save message, and set lead+conversation status."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"messages": [{"id": "wamid.123"}]}

    mock_lead = {
        "id": "lead-abc",
        "phone": "+5511999999999",
        "stage": "secretaria",
        "status": "imported",
        "name": None,
    }
    mock_conversation = {
        "id": "conv-xyz",
        "lead_id": "lead-abc",
        "channel_id": "channel-1",
        "status": "template_sent",
        "stage": "secretaria",
    }

    with patch("app.outbound.dispatcher.settings") as mock_settings, \
         patch("app.outbound.dispatcher.get_or_create_lead", return_value=mock_lead), \
         patch("app.outbound.dispatcher.update_lead") as mock_update_lead, \
         patch("app.outbound.dispatcher.get_or_create_conversation", return_value=mock_conversation) as mock_get_conv, \
         patch("app.outbound.dispatcher.update_conversation") as mock_update_conv, \
         patch("app.outbound.dispatcher.save_message") as mock_save, \
         patch("httpx.AsyncClient") as mock_client_class:

        mock_settings.meta_access_token = "test-token"
        mock_settings.meta_phone_number_id = "123456"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_class.return_value = mock_client

        from app.outbound.dispatcher import dispatch_to_lead
        result = await dispatch_to_lead("+5511999999999", {"channel_id": "channel-1"})

        assert result["status"] == "sent"
        assert result["phone"] == "+5511999999999"
        mock_client.post.assert_called_once()
        mock_save.assert_called_once()
        # Lead status updated to template_sent
        mock_update_lead.assert_called_once_with("lead-abc", status="template_sent")
        # Conversation status updated to template_sent
        mock_update_conv.assert_called_once_with("conv-xyz", status="template_sent")


@pytest.mark.asyncio
async def test_dispatch_missing_token_raises():
    """dispatch_to_lead should raise ValueError when META_ACCESS_TOKEN is not set."""
    with patch("app.outbound.dispatcher.settings") as mock_settings:
        mock_settings.meta_access_token = ""
        mock_settings.meta_phone_number_id = "123456"

        from app.outbound.dispatcher import dispatch_to_lead
        with pytest.raises(ValueError, match="META_ACCESS_TOKEN"):
            await dispatch_to_lead("+5511999999999", {})
```

- [ ] **Step 2: Rodar o teste para confirmar que falha**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_dispatcher.py -v
```
Esperado: `FAILED` — `AssertionError` porque `update_lead` e `update_conversation` não são chamados.

- [ ] **Step 3: Atualizar `app/outbound/dispatcher.py`**

```python
# backend-recuperar-lead/app/outbound/dispatcher.py
import logging

import httpx

from app.config import settings
from app.leads.service import get_or_create_lead, update_lead
from app.conversations.service import get_or_create_conversation, update_conversation, save_message

logger = logging.getLogger(__name__)

META_API_BASE = "https://graph.facebook.com/v21.0"

# ---------------------------------------------------------------------------
# Template hardcoded — primeiro contato ativo com o lead
# Substituir pelo template aprovado pela Meta antes de ir a producao.
# NOTA: a Meta só aceita type="template" para contatos fora da janela de 24h.
# Para testes com janela aberta, pode usar type="text" comentando o payload abaixo.
# ---------------------------------------------------------------------------
TEMPLATE_NAME = "recuperar_lead_v1"  # nome do template aprovado na Meta

TEMPLATE_TEXT = (
    "oi, tudo bem?\n\n"
    "aqui é a Valeria, do comercial da Café Canastra\n\n"
    "a gente trabalha com café especial — atacado, private label e exportação\n\n"
    "queria entender se faz sentido pra você, tem um minutinho?"
)


async def dispatch_to_lead(phone: str, lead_context: dict) -> dict:
    """
    Envia o template de re-engajamento para um lead via Meta Cloud API.

    - Salva a mensagem no histórico como role=assistant para o agent ter contexto.
    - Atualiza lead.status = template_sent.
    - Cria/atualiza conversation.status = template_sent para o processor
      chamar activate_conversation quando o lead responder.

    Args:
        phone: número no formato +5511999999999
        lead_context: dados opcionais do CRM: name, company, previous_stage,
                      notes, channel_id (obrigatório para criar conversation)

    Returns:
        {"status": "sent", "phone": phone, "lead_id": str}
    """
    if not settings.meta_access_token:
        raise ValueError("META_ACCESS_TOKEN nao configurado")
    if not settings.meta_phone_number_id:
        raise ValueError("META_PHONE_NUMBER_ID nao configurado")

    url = f"{META_API_BASE}/{settings.meta_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }
    # Use text for now (works within 24h window); swap to template payload for cold leads
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": TEMPLATE_TEXT},
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        result = resp.json()

    # Resolve or create lead
    lead = get_or_create_lead(phone)
    lead_id = lead["id"]

    # Save dispatcher message as assistant so agent has full context
    channel_id = lead_context.get("channel_id", "")
    if channel_id:
        conversation = get_or_create_conversation(lead_id, channel_id)
        # Mark conversation as template_sent so processor activates it on first reply
        update_conversation(conversation["id"], status="template_sent")
        save_message(lead_id, channel_id, "assistant", TEMPLATE_TEXT, "secretaria")
    else:
        # Fallback: save without conversation_id (channel_id required for full flow)
        from app.db.supabase import get_supabase
        sb = get_supabase()
        sb.table("messages").insert({
            "lead_id": lead_id,
            "role": "assistant",
            "content": TEMPLATE_TEXT,
            "stage": "secretaria",
        }).execute()

    # Mark lead as template_sent so the processor knows to activate on first reply
    update_lead(lead_id, status="template_sent")

    logger.info(f"[DISPATCH] Template sent to {phone} (lead_id={lead_id}), wamid={result}")
    return {"status": "sent", "phone": phone, "lead_id": lead_id}
```

**NOTA:** A assinatura de `save_message` nas conversations.service é
`save_message(conversation_id, lead_id, role, content, stage)`. No bloco acima,
o segundo argumento é `channel_id` — isso está errado. Corrigir:

```python
    if channel_id:
        conversation = get_or_create_conversation(lead_id, channel_id)
        update_conversation(conversation["id"], status="template_sent")
        save_message(conversation["id"], lead_id, "assistant", TEMPLATE_TEXT, "secretaria")
```

O código final correto de `dispatch_to_lead` (bloco `if channel_id:`):

```python
    if channel_id:
        conversation = get_or_create_conversation(lead_id, channel_id)
        update_conversation(conversation["id"], status="template_sent")
        save_message(conversation["id"], lead_id, "assistant", TEMPLATE_TEXT, "secretaria")
    else:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        sb.table("messages").insert({
            "lead_id": lead_id,
            "role": "assistant",
            "content": TEMPLATE_TEXT,
            "stage": "secretaria",
        }).execute()
```

- [ ] **Step 4: Rodar os testes para confirmar que passam**

```bash
cd backend-recuperar-lead && python -m pytest tests/test_dispatcher.py -v
```
Esperado: `PASSED` (ambos os testes)

- [ ] **Step 5: Commit**

```bash
git add backend-recuperar-lead/app/outbound/dispatcher.py backend-recuperar-lead/tests/test_dispatcher.py
git commit -m "feat(recuperar-lead): dispatcher sets template_sent status on lead and conversation"
```

---

## Task 6: Docker Compose Swarm-Ready

**Contexto:** O `backend-recuperar-lead` precisa de um `docker-compose.yml` compatível com Docker Swarm que:
- Exponha a API via Traefik em `sdr.canastrainteligencia.com`
- Use a rede overlay `canastrainteligencia` (a mesma do CRM e do backend principal)
- Não exponha portas diretamente (Traefik faz o roteamento)
- O Redis fica interno ao stack

**Files:**
- Modify: `backend-recuperar-lead/docker-compose.yml`

- [ ] **Step 1: Substituir `docker-compose.yml`**

```yaml
# backend-recuperar-lead/docker-compose.yml
services:
  api:
    image: canastra-sdr:latest
    networks:
      - canastrainteligencia
    env_file: .env
    depends_on:
      - redis
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 10s
        max_attempts: 3
      update_config:
        order: start-first
        failure_action: rollback
      labels:
        - "traefik.enable=true"
        - "traefik.docker.network=canastrainteligencia"
        - "traefik.http.routers.sdr.rule=Host(`sdr.canastrainteligencia.com`)"
        - "traefik.http.routers.sdr.entrypoints=websecure"
        - "traefik.http.routers.sdr.tls.certresolver=letsencryptresolver"
        - "traefik.http.services.sdr.loadbalancer.server.port=8000"

  worker:
    image: canastra-sdr:latest
    command: python -m app.campaign.worker
    networks:
      - canastrainteligencia
    env_file: .env
    depends_on:
      - redis
    deploy:
      replicas: 1
      restart_policy:
        condition: on-failure
        delay: 10s
        max_attempts: 3

  redis:
    image: redis:7-alpine
    networks:
      - canastrainteligencia
    volumes:
      - sdr_redis_data:/data
    deploy:
      restart_policy:
        condition: on-failure

networks:
  canastrainteligencia:
    external: true

volumes:
  sdr_redis_data:
```

- [ ] **Step 2: Verificar sintaxe do compose**

```bash
cd backend-recuperar-lead && docker compose config --quiet 2>&1 || echo "Syntax error"
```
Esperado: sem erros (ou aviso sobre variáveis não definidas — OK)

- [ ] **Step 3: Commit**

```bash
git add backend-recuperar-lead/docker-compose.yml
git commit -m "feat(recuperar-lead): Swarm-ready docker-compose with Traefik on sdr.canastrainteligencia.com"
```

---

## Task 7: Rodar Suite de Testes Completa

**Contexto:** Verificar que nenhum teste foi quebrado pelas mudanças anteriores.

**Files:**
- Test: `backend-recuperar-lead/tests/`

- [ ] **Step 1: Rodar todos os testes**

```bash
cd backend-recuperar-lead && python -m pytest tests/ -v 2>&1 | tail -30
```

- [ ] **Step 2: Se houver falhas, identificar quais testes quebrou**

Checar cada falha:
- `test_buffer.py` — pode precisar atualizar mocks de `get_whatsapp_client` → `get_provider`
- `test_agent_tools.py` — verificar se `execute_tool` signature mudou
- `test_cadence_*` — não devem ter sido afetados

Para cada falha em `test_buffer.py` causada por `get_whatsapp_client`:

```python
# Substituir em test_buffer.py qualquer patch de:
patch("app.buffer.processor.get_whatsapp_client")
# por:
patch("app.buffer.processor.get_provider")
```

- [ ] **Step 3: Re-rodar após correções**

```bash
cd backend-recuperar-lead && python -m pytest tests/ -v 2>&1 | tail -20
```
Esperado: todos `PASSED`

- [ ] **Step 4: Commit (se houve correções)**

```bash
git add backend-recuperar-lead/tests/
git commit -m "test(recuperar-lead): fix test mocks after processor and orchestrator refactor"
```

---

## Self-Review

### Cobertura de spec
- ✅ `app/outbound/dispatcher.py` — envia template, salva mensagem, atualiza status
- ✅ `app/outbound/router.py` — endpoint POST /api/outbound/dispatch (não modificado — já existe)
- ✅ `app/buffer/processor.py` — check human_control, activate_conversation, dedup
- ✅ `app/agent/orchestrator.py` — prompts SDR, lead_context, Gemini model
- ✅ `app/agent/prompts/secretaria.py` — não modificado (já existe no repo)
- ✅ `docker-compose.yml` — Swarm-ready com Traefik
- ⚠️ **Template real Meta** — dispatcher ainda usa `type: "text"` (funciona para testes dentro da janela de 24h). Para cold leads fora da janela, é preciso ter um template aprovado na Meta e trocar para `type: "template"`. Documentado no código.
- ⚠️ **Auth no endpoint** — spec diz "sem auth por enquanto". Manter assim.

### Sem placeholders
- Task 3: código completo do processor ✅
- Task 4: código completo do orchestrator ✅
- Task 5: código completo do dispatcher (com a correção inline anotada) ✅

### Consistência de tipos
- `save_message` em `conversations.service`: `(conversation_id, lead_id, role, content, stage)` — usado corretamente em processor (Task 3) e dispatcher (Task 5, após a correção) ✅
- `run_agent` signature: `(conversation, user_text, lead_context=None)` — alinhado entre processor e orchestrator ✅
- `get_provider(channel)` retorna `WhatsAppProvider` — usado em processor e disponível via `app.providers.registry` ✅
