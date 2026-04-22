# Backend Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidar `backend/`, `backend-evolution/` e `backend-recuperar-lead/` em um único `backend/` unificado, com multi-provedor WhatsApp, flusher automático com toggle Redis e migrações linearizadas idempotentes.

**Architecture:** `backend-recuperar-lead` é usado como base canônica. Módulos faltantes do `backend/` original são portados. A abstração de provider é unificada sob `whatsapp/registry.py`. O `flusher.py` corre como background task mas respeita a flag `config:buffer_enabled` do Redis. Infra Docker (`Dockerfile`, `docker-compose.yml`) permanece do `backend/` original (contém Traefik labels + Docker Swarm config).

**Tech Stack:** Python 3.12, FastAPI, Redis (asyncio), Supabase/PostgreSQL, OpenAI API, httpx, pydantic-settings, python-dateutil

---

## File Map

### Criados
- `backend/app/whatsapp/registry.py` — ponto único de resolução de provider
- `backend/migrations/001_initial.sql` — linearizado (idempotente)
- `backend/migrations/002_crm_enrichment.sql` — merge dos 3 conflitantes `002_*`
- `backend/migrations/003_cadence.sql`
- `backend/migrations/004_campaign_type.sql`
- `backend/migrations/005_token_usage.sql`
- `backend/migrations/006_lead_notes_events.sql`
- `backend/migrations/007_multi_channel.sql`
- `backend/migrations/008_agent_profile_seed.sql`
- `backend/migrations/009_deals.sql`
- `backend/migrations/010_campaigns_redesign.sql`

### Portados do `backend/` original
- `backend/app/agent_profiles/router.py` + `service.py`
- `backend/app/channels/router.py`
- `backend/app/buffer/flusher.py` (adaptado com check da flag Redis)

### Modificados
- `backend/app/whatsapp/base.py` — renomeia `WhatsAppClient` → `WhatsAppProvider`
- `backend/app/whatsapp/evolution.py` — herda `WhatsAppProvider`; constructor recebe `config: dict`
- `backend/app/whatsapp/meta.py` — herda `WhatsAppProvider`; constructor recebe `config: dict`
- `backend/app/outbound/dispatcher.py` — remove httpx direto; usa `get_provider(channel)`
- `backend/app/cadence/scheduler.py` — usa `get_provider(channel)` via helper
- `backend/app/broadcast/worker.py` — usa `get_provider(channel)` via broadcast.channel_id
- `backend/app/channels/service.py` — adiciona `get_channel_for_lead(lead_id)`
- `backend/app/channels/router.py` — corrige import `get_provider` para `app.whatsapp.registry`
- `backend/app/config.py` — merge: base original + vars novas do recuperar-lead
- `backend/requirements.txt` — merge: adiciona `python-dateutil`
- `backend/app/main.py` — registra todos os routers + flusher no lifespan + toggle endpoints

### Deletados
- `backend/app/whatsapp/factory.py`
- `backend/app/whatsapp/client.py`
- `backend/app/providers/` (diretório inteiro)
- `backend-evolution/` (ao final)
- `backend-recuperar-lead/` (ao final)

---

## Task 1: Criar a feature branch

**Files:** nenhum arquivo modificado

- [ ] **Step 1: Criar branch**

```bash
cd "~/Kelwin - Maquinadevendascanastra"
git checkout -b feat/backend-consolidation
```

Expected: `Switched to a new branch 'feat/backend-consolidation'`

---

## Task 2: Substituir `backend/app/` pelo conteúdo do `backend-recuperar-lead/`

Copia os módulos de negócio do `backend-recuperar-lead` para `backend/`, sobrescrevendo. Os arquivos de infra (`Dockerfile`, `docker-compose.yml`, `.env`, `.env.example`) são preservados — apenas o `app/` e arquivos Python são substituídos.

**Files:**
- Modify: `backend/app/` (conteúdo inteiro substituído)
- Modify: `backend/pytest.ini`

- [ ] **Step 1: Copiar `app/` do recuperar-lead para backend**

```bash
cp -r "backend-recuperar-lead/app/." "backend/app/"
```

- [ ] **Step 2: Copiar pytest.ini**

```bash
cp "backend-recuperar-lead/pytest.ini" "backend/pytest.ini"
```

- [ ] **Step 3: Copiar tests/**

```bash
cp -r "backend-recuperar-lead/tests/." "backend/tests/"
```

- [ ] **Step 4: Confirmar estrutura**

```bash
ls backend/app/
```

Expected: `agent  agent_profiles  broadcast  buffer  cadence  campaign  channels  config.py  conversations  db  humanizer  leads  main.py  outbound  providers  stats  webhook  whatsapp  __init__.py`

- [ ] **Step 5: Commit**

```bash
git add backend/app/ backend/tests/ backend/pytest.ini
git commit -m "chore: replace backend/app with backend-recuperar-lead as canonical base"
```

---

## Task 3: Restaurar arquivos de infraestrutura do `backend/` original

O `git checkout` recupera o estado do arquivo no commit anterior (antes do Task 2).

**Files:**
- Restore: `backend/Dockerfile`
- Restore: `backend/docker-compose.yml`

- [ ] **Step 1: Restaurar Dockerfile e docker-compose.yml do original**

```bash
git checkout HEAD~1 -- backend/Dockerfile backend/docker-compose.yml
```

- [ ] **Step 2: Verificar que Traefik labels estão presentes**

```bash
grep -n "traefik" backend/docker-compose.yml
```

Expected: linhas com `traefik.http.routers` visíveis.

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile backend/docker-compose.yml
git commit -m "chore: restore original infra files (Traefik labels + Swarm network)"
```

---

## Task 4: Portar `agent_profiles/` do `backend/` original

O `backend-recuperar-lead` não tinha `agent_profiles/router.py`. Portamos do original.

**Files:**
- Create: `backend/app/agent_profiles/router.py`
- Create: `backend/app/agent_profiles/service.py`
- Create: `backend/app/agent_profiles/__init__.py`

- [ ] **Step 1: Criar diretório**

```bash
mkdir -p backend/app/agent_profiles
```

- [ ] **Step 2: Criar os arquivos com o conteúdo abaixo**

```bash
touch backend/app/agent_profiles/__init__.py
```

**`backend/app/agent_profiles/__init__.py`** (conteúdo: vazio)

**`backend/app/agent_profiles/router.py`:**

```python
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
    result = sb.table("agent_profiles").update(data).eq("id", profile_id).execute()
    return result.data[0]


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    sb = get_supabase()
    sb.table("agent_profiles").delete().eq("id", profile_id).execute()
    return {"status": "deleted"}
```

**`backend/app/agent_profiles/service.py`:**

```python
from app.db.supabase import get_supabase


def get_agent_profile(profile_id: str) -> dict | None:
    sb = get_supabase()
    result = (
        sb.table("agent_profiles")
        .select("*")
        .eq("id", profile_id)
        .single()
        .execute()
    )
    return result.data
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent_profiles/
git commit -m "feat: port agent_profiles router and service from original backend"
```

---

## Task 5: Portar `channels/router.py` do `backend/` original

O `backend-recuperar-lead` tinha `channels/service.py` mas não tinha `channels/router.py`. Portamos o router do original (ele expõe os endpoints CRUD de channels + o endpoint `/send` que já chamava `get_provider` — apenas o import será corrigido no Task 9).

**Files:**
- Create: `backend/app/channels/router.py`

- [ ] **Step 1: Escrever `backend/app/channels/router.py`**

```python
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


class SendMessage(BaseModel):
    conversation_id: str | None = None
    to: str
    text: str


@router.post("/{channel_id}/send")
async def send_message(channel_id: str, body: SendMessage):
    """Send a message through a channel (used by CRM for human chat)."""
    from app.whatsapp.registry import get_provider  # updated import (Task 9)
    from app.conversations.service import save_message

    channel = get_channel(channel_id)
    provider = get_provider(channel)

    await provider.send_text(body.to, body.text)

    if body.conversation_id:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        conv = (
            sb.table("conversations")
            .select("lead_id, stage")
            .eq("id", body.conversation_id)
            .single()
            .execute()
            .data
        )
        save_message(body.conversation_id, conv["lead_id"], "assistant", body.text, conv.get("stage"))

    return {"status": "sent"}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/channels/router.py
git commit -m "feat: port channels router from original backend (updated get_provider import)"
```

---

## Task 6: Portar e adaptar `buffer/flusher.py`

O `flusher.py` do original não verificava a flag Redis. A versão consolidada verifica `config:buffer_enabled` a cada ciclo — se `"0"`, pula o flush mas continua o loop.

**Files:**
- Create: `backend/app/buffer/flusher.py`
- Test: `backend/tests/test_flusher.py`

- [ ] **Step 1: Escrever o teste primeiro**

```python
# backend/tests/test_flusher.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.buffer.flusher import flush_due_items, run_flusher


@pytest.mark.asyncio
async def test_flush_skipped_when_buffer_disabled():
    """Flusher should skip processing when config:buffer_enabled == '0'."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value="0")

    with patch("app.buffer.flusher.flush_due_items") as mock_flush:
        # Simulate one loop iteration then cancel
        async def fake_run(app):
            r = app.state.redis
            flag = await r.get("config:buffer_enabled")
            if flag != "0":
                await flush_due_items(r)

        app_mock = MagicMock()
        app_mock.state.redis = redis_mock

        await fake_run(app_mock)
        mock_flush.assert_not_called()


@pytest.mark.asyncio
async def test_flush_called_when_buffer_enabled():
    """Flusher should process when config:buffer_enabled == '1'."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value="1")
    redis_mock.zrangebyscore = AsyncMock(return_value=[])

    app_mock = MagicMock()
    app_mock.state.redis = redis_mock

    # One iteration: flag is "1", zrangebyscore returns empty (no work)
    await flush_due_items(redis_mock)
    redis_mock.zrangebyscore.assert_called_once()
```

- [ ] **Step 2: Executar o teste para confirmar que falha**

```bash
cd backend && python -m pytest tests/test_flusher.py -v 2>&1 | head -30
```

Expected: `FAILED` ou `ImportError` (flusher.py não tem check de flag ainda)

- [ ] **Step 3: Escrever `backend/app/buffer/flusher.py`**

```python
import asyncio
import logging
import time

import redis.asyncio as aioredis

from app.buffer.manager import FLUSH_QUEUE_KEY
from app.buffer.processor import process_buffered_messages
from app.channels.service import get_channel

logger = logging.getLogger(__name__)

BUFFER_FLAG_KEY = "config:buffer_enabled"


async def flush_due_items(r: aioredis.Redis) -> None:
    """Process all flush_queue items whose score (flush_at) has passed.

    Uses ZREM for atomic claiming: only the worker that successfully removes
    the member processes it. Safe across multiple uvicorn workers.
    """
    now = time.time()
    due_members = await r.zrangebyscore(FLUSH_QUEUE_KEY, "-inf", now)

    for member in due_members:
        removed = await r.zrem(FLUSH_QUEUE_KEY, member)
        if removed == 0:
            continue

        channel_id, phone = member.split(":", 1)
        buffer_key = f"buffer:{channel_id}:{phone}"
        lead_name_key = f"lead_name:{channel_id}:{phone}"

        async with r.pipeline(transaction=True) as pipe:
            pipe.lrange(buffer_key, 0, -1)
            pipe.delete(buffer_key)
            pipe.get(lead_name_key)
            results = await pipe.execute()

        raw_messages = results[0]
        if not raw_messages:
            continue

        push_name = results[2] if results[2] else None
        combined = "\n".join(raw_messages)
        logger.info(
            f"Flushing {len(raw_messages)} message(s) for {phone} on channel {channel_id}"
        )

        try:
            channel = get_channel(channel_id)
        except Exception as e:
            logger.error(
                f"Channel {channel_id} not found during flush, "
                f"dropping {len(raw_messages)} message(s): {e}"
            )
            continue

        await process_buffered_messages(phone, combined, channel, push_name=push_name)


async def run_flusher(app) -> None:
    """Background loop started by FastAPI lifespan.

    Checks config:buffer_enabled flag each cycle.
    Runs forever until the app shuts down (asyncio.CancelledError).
    """
    redis: aioredis.Redis = app.state.redis
    logger.info("Buffer flusher started")

    while True:
        try:
            flag = await redis.get(BUFFER_FLAG_KEY)
            if flag != "0":
                await flush_due_items(redis)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Flusher loop error: {e}", exc_info=True)

        await asyncio.sleep(0.5)
```

- [ ] **Step 4: Executar os testes**

```bash
cd backend && python -m pytest tests/test_flusher.py -v
```

Expected: `PASSED` nos dois testes

- [ ] **Step 5: Commit**

```bash
git add backend/app/buffer/flusher.py backend/tests/test_flusher.py
git commit -m "feat: port flusher with Redis toggle — skips flush when buffer_enabled=0"
```

---

## Task 7: Escrever testes para `whatsapp/registry` (TDD)

**Files:**
- Test: `backend/tests/test_whatsapp_registry.py`

- [ ] **Step 1: Escrever testes**

```python
# backend/tests/test_whatsapp_registry.py
import pytest
from unittest.mock import patch

from app.whatsapp.registry import get_provider
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient


def test_get_provider_returns_evolution_client():
    channel = {
        "provider": "evolution",
        "provider_config": {
            "api_url": "http://evolution.local",
            "api_key": "test-key",
            "instance": "test-instance",
        },
    }
    provider = get_provider(channel)
    assert isinstance(provider, EvolutionClient)


def test_get_provider_returns_meta_client():
    channel = {
        "provider": "meta_cloud",
        "provider_config": {
            "phone_number_id": "123456",
            "access_token": "EAAtest",
        },
    }
    provider = get_provider(channel)
    assert isinstance(provider, MetaCloudClient)


def test_get_provider_raises_for_unknown():
    channel = {
        "provider": "unknown_provider",
        "provider_config": {},
    }
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider(channel)


def test_evolution_client_stores_config():
    channel = {
        "provider": "evolution",
        "provider_config": {
            "api_url": "http://evo.local",
            "api_key": "my-key",
            "instance": "my-instance",
        },
    }
    client = get_provider(channel)
    assert client.base_url == "http://evo.local"
    assert client.api_key == "my-key"
    assert client.instance == "my-instance"


def test_meta_client_stores_config():
    channel = {
        "provider": "meta_cloud",
        "provider_config": {
            "phone_number_id": "9999",
            "access_token": "tok",
        },
    }
    client = get_provider(channel)
    assert client.phone_number_id == "9999"
    assert client.access_token == "tok"
```

- [ ] **Step 2: Executar testes para confirmar que falham**

```bash
cd backend && python -m pytest tests/test_whatsapp_registry.py -v 2>&1 | head -20
```

Expected: `ImportError` — `app.whatsapp.registry` ainda não existe

---

## Task 8: Implementar unificação do `whatsapp/`

**Files:**
- Modify: `backend/app/whatsapp/base.py`
- Modify: `backend/app/whatsapp/evolution.py`
- Modify: `backend/app/whatsapp/meta.py`
- Create: `backend/app/whatsapp/registry.py`

- [ ] **Step 1: Reescrever `backend/app/whatsapp/base.py`**

```python
from abc import ABC, abstractmethod


class WhatsAppProvider(ABC):
    """Abstract interface for WhatsApp message delivery."""

    @abstractmethod
    async def send_text(self, to: str, body: str) -> dict: ...

    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict: ...

    @abstractmethod
    async def send_audio(self, to: str, audio_url: str) -> dict: ...

    @abstractmethod
    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict: ...
```

- [ ] **Step 2: Reescrever `backend/app/whatsapp/evolution.py`**

Constructor agora aceita `config: dict` (padrão registry). Internamente extrai os campos.

```python
import httpx
from app.whatsapp.base import WhatsAppProvider


class EvolutionClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.base_url = config["api_url"].rstrip("/")
        self.api_key = config["api_key"]
        self.instance = config["instance"]

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

    async def send_image_base64(
        self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None
    ) -> dict:
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

- [ ] **Step 3: Reescrever `backend/app/whatsapp/meta.py`**

```python
import httpx
from app.whatsapp.base import WhatsAppProvider

META_API_BASE = "https://graph.facebook.com/v21.0"


class MetaCloudClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.phone_number_id = config["phone_number_id"]
        self.access_token = config["access_token"]

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

- [ ] **Step 4: Criar `backend/app/whatsapp/registry.py`**

```python
from app.whatsapp.base import WhatsAppProvider
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient

_PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    "evolution": EvolutionClient,
    "meta_cloud": MetaCloudClient,
}


def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve the correct WhatsAppProvider instance from a channel record.

    Args:
        channel: dict with keys 'provider' (str) and 'provider_config' (dict)

    Returns:
        Concrete WhatsAppProvider instance ready for use.
    """
    provider_type = channel["provider"]
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_type!r}. Expected one of: {list(_PROVIDERS)}")
    return provider_class(channel.get("provider_config", {}))
```

- [ ] **Step 5: Executar os testes do registry**

```bash
cd backend && python -m pytest tests/test_whatsapp_registry.py -v
```

Expected: todos os 5 testes `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/app/whatsapp/base.py backend/app/whatsapp/evolution.py \
        backend/app/whatsapp/meta.py backend/app/whatsapp/registry.py \
        backend/tests/test_whatsapp_registry.py
git commit -m "feat: unify WhatsApp provider abstraction under whatsapp/registry.py"
```

---

## Task 9: Deletar arquivos de abstração obsoletos

**Files:**
- Delete: `backend/app/whatsapp/factory.py`
- Delete: `backend/app/whatsapp/client.py`
- Delete: `backend/app/providers/` (diretório)

- [ ] **Step 1: Deletar**

```bash
rm -f backend/app/whatsapp/factory.py
rm -f backend/app/whatsapp/client.py
rm -rf backend/app/providers/
```

- [ ] **Step 2: Verificar que não há mais referências**

```bash
grep -r "from app.whatsapp.factory" backend/app/ 2>/dev/null && echo "FOUND — fix needed" || echo "OK"
grep -r "from app.whatsapp.client" backend/app/ 2>/dev/null && echo "FOUND — fix needed" || echo "OK"
grep -r "from app.providers" backend/app/ 2>/dev/null && echo "FOUND — fix needed" || echo "OK"
```

Expected: `OK` nos três. Se `FOUND`, identificar o arquivo e corrigir o import para `from app.whatsapp.registry import get_provider`.

- [ ] **Step 3: Commit**

```bash
git add -A backend/app/whatsapp/ backend/app/providers/
git commit -m "chore: remove obsolete factory.py, client.py and providers/ directory"
```

---

## Task 10: Refatorar `outbound/dispatcher.py`

Remove httpx direto; passa a usar `get_provider(channel)` para disparar via API correta.

**Files:**
- Modify: `backend/app/outbound/dispatcher.py`
- Test: `backend/tests/test_outbound_dispatcher.py`

- [ ] **Step 1: Escrever o teste**

```python
# backend/tests/test_outbound_dispatcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_dispatch_uses_provider_send_text():
    """dispatcher must call provider.send_text, not httpx directly."""
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]})

    mock_channel = {
        "id": "chan-001",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }

    with patch("app.outbound.dispatcher.get_provider", return_value=mock_provider), \
         patch("app.outbound.dispatcher.get_channel", return_value=mock_channel), \
         patch("app.outbound.dispatcher.get_or_create_lead", return_value={"id": "lead-001"}), \
         patch("app.outbound.dispatcher.update_lead"), \
         patch("app.outbound.dispatcher.get_or_create_conversation", return_value={"id": "conv-001"}), \
         patch("app.outbound.dispatcher.update_conversation"), \
         patch("app.outbound.dispatcher.save_message"):

        from app.outbound.dispatcher import dispatch_to_lead

        result = await dispatch_to_lead(
            phone="+5511999990000",
            lead_context={"channel_id": "chan-001"},
        )

    mock_provider.send_text.assert_called_once()
    assert result["status"] == "sent"
    assert result["phone"] == "+5511999990000"


@pytest.mark.asyncio
async def test_dispatch_raises_without_channel_id():
    from app.outbound.dispatcher import dispatch_to_lead
    with pytest.raises(ValueError, match="channel_id"):
        await dispatch_to_lead(phone="+5511999990000", lead_context={})
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd backend && python -m pytest tests/test_outbound_dispatcher.py -v 2>&1 | head -20
```

Expected: `FAILED` — função ainda usa httpx direto

- [ ] **Step 3: Reescrever `backend/app/outbound/dispatcher.py`**

```python
import logging

from app.config import settings
from app.channels.service import get_channel
from app.leads.service import get_or_create_lead, update_lead
from app.conversations.service import get_or_create_conversation, update_conversation, save_message
from app.whatsapp.registry import get_provider

logger = logging.getLogger(__name__)

TEMPLATE_TEXT = (
    "oi, tudo bem?\n\n"
    "aqui é a Valeria, do comercial da Café Canastra\n\n"
    "a gente trabalha com café especial — atacado, private label e exportação\n\n"
    "queria entender se faz sentido pra você, tem um minutinho?"
)


async def dispatch_to_lead(phone: str, lead_context: dict) -> dict:
    """
    Envia mensagem de re-engajamento para um lead via o provider configurado no channel.

    Args:
        phone: número no formato +5511999999999
        lead_context: deve conter 'channel_id' (obrigatório) e opcionalmente
                      name, company, previous_stage, notes.

    Returns:
        {"status": "sent", "phone": phone, "lead_id": str}
    """
    channel_id = lead_context.get("channel_id", "")
    if not channel_id:
        raise ValueError("channel_id is required in lead_context to dispatch a message")

    channel = get_channel(channel_id)
    provider = get_provider(channel)

    await provider.send_text(phone, TEMPLATE_TEXT)

    lead = get_or_create_lead(phone)
    lead_id = lead["id"]

    try:
        update_lead(lead_id, status="template_sent")
    except Exception as e:
        logger.error(f"[DISPATCH] Failed to update lead status for {lead_id}: {e}", exc_info=True)

    try:
        conversation = get_or_create_conversation(lead_id, channel_id)
        update_conversation(conversation["id"], status="template_sent")
        save_message(conversation["id"], lead_id, "assistant", TEMPLATE_TEXT, "secretaria")
    except Exception as e:
        logger.error(
            f"[DISPATCH] Failed to update conversation state for lead {lead_id}: {e}",
            exc_info=True,
        )

    logger.info(f"[DISPATCH] Message dispatched to {phone} (lead_id={lead_id})")
    return {"status": "sent", "phone": phone, "lead_id": lead_id}
```

- [ ] **Step 4: Rodar os testes**

```bash
cd backend && python -m pytest tests/test_outbound_dispatcher.py -v
```

Expected: `PASSED` nos dois testes

- [ ] **Step 5: Commit**

```bash
git add backend/app/outbound/dispatcher.py backend/tests/test_outbound_dispatcher.py
git commit -m "refactor: outbound dispatcher uses get_provider instead of direct httpx"
```

---

## Task 11: Adicionar `get_channel_for_lead` em `channels/service.py`

O `cadence/scheduler.py` precisa do channel associado ao lead para chamar `get_provider`. A forma mais direta: buscar a conversa ativa do lead e retornar o channel.

**Files:**
- Modify: `backend/app/channels/service.py`
- Test: `backend/tests/test_channels_service.py` (novo ou existing)

- [ ] **Step 1: Ler `backend/app/channels/service.py` atual**

```bash
cat backend/app/channels/service.py
```

- [ ] **Step 2: Adicionar `get_channel_for_lead` ao final do arquivo**

Abra `backend/app/channels/service.py` e adicione ao final:

```python
def get_channel_for_lead(lead_id: str) -> dict | None:
    """Return the channel associated with a lead's most recent active conversation.

    Returns None if no conversation or channel is found.
    """
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("channel_id, channels!inner(*)")
        .eq("lead_id", lead_id)
        .eq("status", "active")
        .order("last_msg_at", desc=True)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    return result.data[0]["channels"]
```

- [ ] **Step 3: Escrever teste**

```python
# Adicionar ao backend/tests/test_channels_service.py (ou criar)
from unittest.mock import MagicMock, patch


def test_get_channel_for_lead_returns_channel():
    mock_channel = {"id": "chan-001", "provider": "evolution", "provider_config": {}}
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value.data = [
        {"channel_id": "chan-001", "channels": mock_channel}
    ]

    with patch("app.channels.service.get_supabase", return_value=mock_sb):
        from app.channels.service import get_channel_for_lead
        result = get_channel_for_lead("lead-001")

    assert result == mock_channel


def test_get_channel_for_lead_returns_none_when_no_conversation():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.channels.service.get_supabase", return_value=mock_sb):
        from app.channels.service import get_channel_for_lead
        result = get_channel_for_lead("lead-no-conv")

    assert result is None
```

- [ ] **Step 4: Rodar os testes**

```bash
cd backend && python -m pytest tests/test_channels_service.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/app/channels/service.py backend/tests/test_channels_service.py
git commit -m "feat: add get_channel_for_lead helper for scheduler channel resolution"
```

---

## Task 12: Refatorar `cadence/scheduler.py`

Remove `send_text` importado de `whatsapp.client`. Usa `get_channel_for_lead` + `get_provider(channel)`.

**Files:**
- Modify: `backend/app/cadence/scheduler.py`

- [ ] **Step 1: Abrir `backend/app/cadence/scheduler.py` e localizar a linha do import**

```bash
head -25 backend/app/cadence/scheduler.py
```

A linha de import atual será:
```python
from app.whatsapp.client import send_text
```

- [ ] **Step 2: Substituir import e lógica de envio**

Remova a linha:
```python
from app.whatsapp.client import send_text
```

Adicione:
```python
from app.channels.service import get_channel_for_lead
from app.whatsapp.registry import get_provider
```

- [ ] **Step 3: Substituir a chamada `await send_text(...)` dentro de `process_due_cadences`**

Encontre o bloco (aprox. linha 84-85):
```python
        try:
            message = _substitute_variables(step["message_text"], lead)
            await send_text(lead["phone"], message)
```

Substitua por:
```python
        try:
            message = _substitute_variables(step["message_text"], lead)

            channel = get_channel_for_lead(enrollment["lead_id"])
            if channel is None:
                logger.warning(
                    f"[CADENCE] No channel found for lead {lead['phone']}, skipping step"
                )
                continue

            provider = get_provider(channel)
            await provider.send_text(lead["phone"], message)
```

- [ ] **Step 4: Rodar os testes existentes de cadence**

```bash
cd backend && python -m pytest tests/test_cadence_scheduler.py tests/test_cadence_service.py -v
```

Expected: todos `PASSED` (os testes existentes já fazem mock de `send_text` — adaptar mocks se necessário)

- [ ] **Step 5: Commit**

```bash
git add backend/app/cadence/scheduler.py
git commit -m "refactor: cadence scheduler uses get_provider(channel) instead of send_text"
```

---

## Task 13: Refatorar `broadcast/worker.py`

O `broadcast` tem `channel_id`. Carrega o channel e chama `get_provider`.

**Files:**
- Modify: `backend/app/broadcast/worker.py`

- [ ] **Step 1: Remover import de `send_template` de `whatsapp.client`**

Localize no topo do arquivo:
```python
from app.whatsapp.client import send_template
```

Substitua por:
```python
from app.channels.service import get_channel
from app.whatsapp.registry import get_provider
```

- [ ] **Step 2: Substituir a chamada `await send_template(...)` dentro de `process_single_broadcast`**

Localize:
```python
        try:
            await send_template(
                to=lead["phone"],
                template_name=broadcast["template_name"],
                components=broadcast.get("template_variables", {}).get("components"),
            )
```

Substitua por:
```python
        try:
            channel_id = broadcast.get("channel_id")
            if not channel_id:
                logger.warning(
                    f"[BROADCAST] broadcast {broadcast_id} has no channel_id, skipping lead {lead['phone']}"
                )
                mark_broadcast_lead_failed(bl["id"], "broadcast has no channel_id")
                increment_broadcast_failed(broadcast_id)
                continue

            channel = get_channel(channel_id)
            provider = get_provider(channel)
            await provider.send_text(lead["phone"], broadcast["template_name"])
```

- [ ] **Step 3: Rodar os testes existentes de broadcast**

```bash
cd backend && python -m pytest tests/ -k "broadcast" -v 2>&1 | tail -20
```

Expected: `PASSED`

- [ ] **Step 4: Commit**

```bash
git add backend/app/broadcast/worker.py
git commit -m "refactor: broadcast worker uses get_provider(channel) instead of send_template"
```

---

## Task 14: Atualizar `main.py`

Registra todos os routers, inicia o flusher no lifespan, adiciona buffer toggle endpoints e dashboard `/web`.

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Reescrever `backend/app/main.py`**

```python
import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.buffer.flusher import run_flusher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    # Start with buffer OFF; toggle via POST /api/buffer
    await app.state.redis.set("config:buffer_enabled", "0")

    flusher_task = asyncio.create_task(run_flusher(app))

    yield

    flusher_task.cancel()
    try:
        await flusher_task
    except asyncio.CancelledError:
        pass

    await app.state.redis.close()


app = FastAPI(title="ValerIA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
from app.webhook.router import router as webhook_router
from app.webhook.meta_router import router as meta_webhook_router
from app.leads.router import router as leads_router
from app.broadcast.router import router as broadcast_router
from app.cadence.router import router as cadence_router
from app.stats.router import router as stats_router
from app.stats.pricing_router import router as pricing_router
from app.outbound.router import router as outbound_router
from app.channels.router import router as channels_router
from app.agent_profiles.router import router as agent_profiles_router

app.include_router(webhook_router)
app.include_router(meta_webhook_router)
app.include_router(leads_router)
app.include_router(broadcast_router)
app.include_router(cadence_router)
app.include_router(stats_router)
app.include_router(pricing_router)
app.include_router(outbound_router)
app.include_router(channels_router)
app.include_router(agent_profiles_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Buffer toggle API ---

@app.get("/api/buffer")
async def get_buffer_status(request: Request):
    r = request.app.state.redis
    val = await r.get("config:buffer_enabled")
    enabled = val != "0"
    return {"enabled": enabled}


@app.post("/api/buffer")
async def set_buffer_status(request: Request):
    body = await request.json()
    r = request.app.state.redis
    enabled = body.get("enabled", True)
    await r.set("config:buffer_enabled", "1" if enabled else "0")
    return {"enabled": enabled}


# --- Web dashboard ---

@app.get("/web", response_class=HTMLResponse)
async def web_dashboard():
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ValerIA - Painel</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0a0a0a; color: #fafafa; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }
        .card { background: #18181b; border: 1px solid #27272a; border-radius: 16px;
                padding: 40px; width: 400px; text-align: center; }
        .logo { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
        .logo span { color: #22c55e; }
        .subtitle { color: #71717a; font-size: 14px; margin-bottom: 32px; }
        .toggle-section { display: flex; align-items: center; justify-content: space-between;
                          background: #09090b; border: 1px solid #27272a; border-radius: 12px;
                          padding: 20px 24px; margin-bottom: 16px; }
        .toggle-label { font-size: 16px; font-weight: 500; }
        .toggle-status { font-size: 13px; color: #71717a; margin-top: 4px; }
        .toggle-status.on { color: #22c55e; }
        .toggle-status.off { color: #ef4444; }
        .switch { position: relative; width: 56px; height: 30px; cursor: pointer; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                  background: #3f3f46; border-radius: 30px; transition: 0.3s; }
        .slider:before { content: ""; position: absolute; height: 22px; width: 22px;
                         left: 4px; bottom: 4px; background: white; border-radius: 50%; transition: 0.3s; }
        input:checked + .slider { background: #22c55e; }
        input:checked + .slider:before { transform: translateX(26px); }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const { useState, useEffect } = React;
        function App() {
            const [bufferOn, setBufferOn] = useState(false);
            const [loading, setLoading] = useState(true);
            useEffect(() => {
                fetch('/api/buffer').then(r => r.json())
                    .then(d => { setBufferOn(d.enabled); setLoading(false); })
                    .catch(() => setLoading(false));
            }, []);
            const toggle = async () => {
                const next = !bufferOn;
                setBufferOn(next);
                await fetch('/api/buffer', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({enabled: next}),
                });
            };
            if (loading) return <div className="card"><p>Carregando...</p></div>;
            return (
                <div className="card">
                    <div className="logo">Valer<span>IA</span></div>
                    <p className="subtitle">Painel de Controle</p>
                    <div className="toggle-section">
                        <div style={{textAlign: 'left'}}>
                            <div className="toggle-label">Buffer de Mensagens</div>
                            <div className={"toggle-status " + (bufferOn ? "on" : "off")}>
                                {bufferOn ? "Ativado — agrupa mensagens" : "Desativado — processa imediatamente"}
                            </div>
                        </div>
                        <label className="switch">
                            <input type="checkbox" checked={bufferOn} onChange={toggle} />
                            <span className="slider"></span>
                        </label>
                    </div>
                </div>
            );
        }
        ReactDOM.createRoot(document.getElementById('root')).render(<App />);
    </script>
</body>
</html>"""
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: consolidated main.py — all routers, flusher lifespan, buffer toggle, /web"
```

---

## Task 15: Mesclar `config.py` e `requirements.txt`

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Reescrever `backend/app/config.py`**

Base do original (preserva `gemini_api_key`, `openai_api_key`, `frontend_url: 5173`) + novas vars do recuperar-lead:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    gemini_api_key: str
    openai_api_key: str = ""

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

    # Evolution API (global fallback — per-channel config takes precedence)
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""

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

- [ ] **Step 2: Reescrever `backend/requirements.txt`**

```
fastapi>=0.115.0,<1.0
uvicorn[standard]>=0.34.0,<1.0
redis>=5.0.0,<6.0
supabase>=2.28.0,<3.0
openai>=1.50.0,<2.0
httpx>=0.28.0,<1.0
python-dotenv>=1.0.0,<2.0
python-multipart>=0.0.20,<1.0
pydantic-settings>=2.5.0,<3.0
python-dateutil>=2.9.0,<3.0
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/config.py backend/requirements.txt
git commit -m "chore: merge config.py and requirements.txt from all three backends"
```

---

## Task 16: Escrever migrações linearizadas idempotentes (001–010)

Deletar as migrações antigas e escrever a sequência limpa.

**Files:**
- Delete: `backend/migrations/001_initial.sql` (substituído)
- Delete: `backend/migrations/007_multi_channel.sql` (substituído)
- Create: `backend/migrations/001_initial.sql` até `010_campaigns_redesign.sql`

- [ ] **Step 1: Limpar diretório de migrações**

```bash
rm -f backend/migrations/*.sql
```

- [ ] **Step 2: Criar `backend/migrations/001_initial.sql`**

```sql
-- 001_initial.sql
-- Core tables. All statements are idempotent.

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

CREATE TABLE IF NOT EXISTS messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    stage text,
    created_at timestamptz DEFAULT now()
);

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

CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_campaign ON leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_messages_lead_id ON messages(lead_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);

CREATE OR REPLACE FUNCTION increment_campaign_sent(campaign_id_param uuid)
RETURNS void AS $$
BEGIN UPDATE campaigns SET sent = sent + 1 WHERE id = campaign_id_param; END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_campaign_replied(campaign_id_param uuid)
RETURNS void AS $$
BEGIN UPDATE campaigns SET replied = replied + 1 WHERE id = campaign_id_param; END;
$$ LANGUAGE plpgsql;
```

- [ ] **Step 3: Criar `backend/migrations/002_crm_enrichment.sql`**

Merge dos três `002_*` originais. Usa `ADD COLUMN IF NOT EXISTS`.

```sql
-- 002_crm_enrichment.sql
-- Merges: 002_crm_columns + 002_lead_enrichment + 002_tags

-- CRM control columns
DO $$ BEGIN ALTER TABLE leads ADD COLUMN human_control boolean DEFAULT false;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE leads ADD COLUMN assigned_to uuid;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE leads ADD COLUMN channel text DEFAULT 'evolution';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- B2B enrichment
DO $$ BEGIN ALTER TABLE leads ADD COLUMN cnpj text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN razao_social text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN nome_fantasia text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN endereco text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN telefone_comercial text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN email text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN instagram text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN inscricao_estadual text; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN sale_value numeric DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Stage tracking
DO $$ BEGIN ALTER TABLE leads ADD COLUMN seller_stage text DEFAULT 'novo'; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN entered_stage_at timestamptz DEFAULT now(); EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN first_response_at timestamptz; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE leads ADD COLUMN on_hold boolean DEFAULT false; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Messages tracking
DO $$ BEGIN ALTER TABLE messages ADD COLUMN sent_by text DEFAULT 'agent'; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_leads_seller_stage ON leads(seller_stage);
CREATE INDEX IF NOT EXISTS idx_leads_human_control ON leads(human_control);
CREATE INDEX IF NOT EXISTS idx_leads_entered_stage_at ON leads(entered_stage_at);

-- Trigger: auto-update entered_stage_at on stage change
CREATE OR REPLACE FUNCTION update_entered_stage_at()
RETURNS trigger AS $$
BEGIN
    IF OLD.stage IS DISTINCT FROM NEW.stage OR OLD.seller_stage IS DISTINCT FROM NEW.seller_stage THEN
        NEW.entered_stage_at = now();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_update_entered_stage_at ON leads;
CREATE TRIGGER trg_update_entered_stage_at
    BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION update_entered_stage_at();

-- Tags
CREATE TABLE IF NOT EXISTS tags (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    color text NOT NULL DEFAULT '#8b5cf6',
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lead_tags (
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    tag_id uuid REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (lead_id, tag_id)
);

-- Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE leads;
ALTER PUBLICATION supabase_realtime ADD TABLE messages;
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
```

- [ ] **Step 4: Criar `backend/migrations/003_cadence.sql`**

```sql
-- 003_cadence.sql
-- Legacy cadence columns on campaigns (migrated to new schema in 010).

DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_interval_hours int DEFAULT 24; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_send_start_hour int DEFAULT 7; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_send_end_hour int DEFAULT 18; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_cooldown_hours int DEFAULT 48; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_max_messages int DEFAULT 8; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_sent int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_responded int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_exhausted int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN cadence_cooled int DEFAULT 0; EXCEPTION WHEN duplicate_column THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    stage text NOT NULL,
    step_order int NOT NULL,
    message_text text NOT NULL,
    created_at timestamptz DEFAULT now(),
    UNIQUE(campaign_id, stage, step_order)
);

CREATE TABLE IF NOT EXISTS cadence_state (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE UNIQUE,
    campaign_id uuid REFERENCES campaigns(id) ON DELETE CASCADE,
    current_step int DEFAULT 0,
    status text DEFAULT 'active',
    total_messages_sent int DEFAULT 0,
    max_messages int DEFAULT 8,
    next_send_at timestamptz,
    cooldown_until timestamptz,
    responded_at timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cadence_steps_campaign ON cadence_steps(campaign_id);
CREATE INDEX IF NOT EXISTS idx_cadence_state_lead ON cadence_state(lead_id);
CREATE INDEX IF NOT EXISTS idx_cadence_state_status ON cadence_state(status);
CREATE INDEX IF NOT EXISTS idx_cadence_state_next_send ON cadence_state(next_send_at);

CREATE OR REPLACE FUNCTION increment_cadence_sent(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_sent = cadence_sent + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_cadence_responded(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_responded = cadence_responded + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_cadence_exhausted(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_exhausted = cadence_exhausted + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_cadence_cooled(campaign_id_param uuid)
RETURNS void AS $$ BEGIN UPDATE campaigns SET cadence_cooled = cadence_cooled + 1 WHERE id = campaign_id_param; END; $$ LANGUAGE plpgsql;
```

- [ ] **Step 5: Criar `backend/migrations/004_campaign_type.sql`**

```sql
-- 004_campaign_type.sql
DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN type text DEFAULT 'broadcast';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
```

- [ ] **Step 6: Criar `backend/migrations/005_token_usage.sql`**

Copiar diretamente do recuperar-lead (já correto, com `ON CONFLICT DO NOTHING`):

```bash
cp backend-recuperar-lead/migrations/005_token_usage.sql backend/migrations/005_token_usage.sql
```

- [ ] **Step 7: Criar `backend/migrations/006_lead_notes_events.sql`**

```bash
cp backend-recuperar-lead/migrations/006_lead_notes_events.sql backend/migrations/006_lead_notes_events.sql
```

- [ ] **Step 8: Criar `backend/migrations/007_multi_channel.sql`**

Copiar do original `backend/` (já existia) e adicionar `IF NOT EXISTS` nos dois índices que estavam faltando:

```sql
-- 007_multi_channel.sql
-- Multi-channel: agent_profiles, channels, conversations

CREATE TABLE IF NOT EXISTS agent_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    model text NOT NULL DEFAULT 'gpt-4.1',
    stages jsonb NOT NULL DEFAULT '{}',
    base_prompt text NOT NULL DEFAULT '',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

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

CREATE INDEX IF NOT EXISTS idx_channels_phone ON channels(phone);
CREATE INDEX IF NOT EXISTS idx_channels_provider ON channels(provider);

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

CREATE INDEX IF NOT EXISTS idx_conversations_channel ON conversations(channel_id);
CREATE INDEX IF NOT EXISTS idx_conversations_lead ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);

DO $$ BEGIN ALTER TABLE messages ADD COLUMN conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE templates ADD COLUMN channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE leads ADD COLUMN metadata jsonb DEFAULT '{}';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

ALTER PUBLICATION supabase_realtime ADD TABLE channels;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_profiles;
ALTER PUBLICATION supabase_realtime ADD TABLE conversations;
```

- [ ] **Step 9: Criar `backend/migrations/008_agent_profile_seed.sql`**

```bash
cp backend-recuperar-lead/migrations/008_seed_agent_profile.sql backend/migrations/008_agent_profile_seed.sql
```

- [ ] **Step 10: Criar `backend/migrations/009_deals.sql`**

```bash
cp backend-recuperar-lead/migrations/009_deals.sql backend/migrations/009_deals.sql
```

- [ ] **Step 11: Criar `backend/migrations/010_campaigns_redesign.sql`**

Escreva o arquivo completo abaixo (o bloco de migração de dados está envolvido em guard de existência — idempotente):

```sql
-- 010_campaigns_redesign.sql
-- Split campaigns into broadcasts + cadences. Fully idempotent.

-- 1. broadcasts table
CREATE TABLE IF NOT EXISTS broadcasts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    channel_id uuid REFERENCES channels(id),
    template_name text NOT NULL,
    template_preset_id uuid,
    template_variables jsonb DEFAULT '{}',
    total_leads int DEFAULT 0,
    sent int DEFAULT 0,
    failed int DEFAULT 0,
    delivered int DEFAULT 0,
    status text NOT NULL DEFAULT 'draft',
    scheduled_at timestamptz,
    send_interval_min int DEFAULT 3,
    send_interval_max int DEFAULT 8,
    cadence_id uuid,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON broadcasts(status);

-- 2. broadcast_leads table
CREATE TABLE IF NOT EXISTS broadcast_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    broadcast_id uuid NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending',
    sent_at timestamptz,
    error_message text,
    UNIQUE(broadcast_id, lead_id)
);
CREATE INDEX IF NOT EXISTS idx_broadcast_leads_broadcast ON broadcast_leads(broadcast_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_leads_status ON broadcast_leads(broadcast_id, status);

-- 3. cadences table
CREATE TABLE IF NOT EXISTS cadences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    target_type text NOT NULL DEFAULT 'manual',
    target_stage text,
    stagnation_days int,
    send_start_hour int DEFAULT 7,
    send_end_hour int DEFAULT 18,
    cooldown_hours int DEFAULT 48,
    max_messages int DEFAULT 5,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cadences_status ON cadences(status);
CREATE INDEX IF NOT EXISTS idx_cadences_target ON cadences(target_type, target_stage);

-- 4. FK broadcasts -> cadences
DO $$ BEGIN
  ALTER TABLE broadcasts ADD CONSTRAINT fk_broadcasts_cadence
      FOREIGN KEY (cadence_id) REFERENCES cadences(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- 5. Drop old cadence_steps and recreate with new schema
DROP TABLE IF EXISTS cadence_steps CASCADE;
CREATE TABLE cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence_id uuid NOT NULL REFERENCES cadences(id) ON DELETE CASCADE,
    step_order int NOT NULL,
    message_text text NOT NULL,
    delay_days int DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE(cadence_id, step_order)
);
CREATE INDEX IF NOT EXISTS idx_cadence_steps_cadence ON cadence_steps(cadence_id);

-- 6. cadence_enrollments table
CREATE TABLE IF NOT EXISTS cadence_enrollments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence_id uuid NOT NULL REFERENCES cadences(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    deal_id uuid REFERENCES deals(id) ON DELETE SET NULL,
    broadcast_id uuid REFERENCES broadcasts(id) ON DELETE SET NULL,
    current_step int DEFAULT 0,
    status text NOT NULL DEFAULT 'active',
    total_messages_sent int DEFAULT 0,
    next_send_at timestamptz,
    cooldown_until timestamptz,
    responded_at timestamptz,
    enrolled_at timestamptz DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(cadence_id, lead_id)
);
CREATE INDEX IF NOT EXISTS idx_enrollments_cadence ON cadence_enrollments(cadence_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_lead ON cadence_enrollments(lead_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_status ON cadence_enrollments(status);
CREATE INDEX IF NOT EXISTS idx_enrollments_next_send ON cadence_enrollments(status, next_send_at);

-- 7. template_presets table
CREATE TABLE IF NOT EXISTS template_presets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    template_name text NOT NULL,
    variables jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- 8. Data migration from campaigns (idempotency guard: only if table exists)
DO $$
DECLARE
    c RECORD;
    new_cadence_id uuid;
    new_broadcast_id uuid;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'campaigns'
    ) THEN
        RETURN;
    END IF;

    FOR c IN SELECT * FROM campaigns LOOP
        INSERT INTO cadences (name, description, target_type, send_start_hour, send_end_hour,
                              cooldown_hours, max_messages, status)
        VALUES (
            c.name || ' - Cadencia', 'Migrado da campanha: ' || c.name, 'manual',
            COALESCE(c.cadence_send_start_hour, 7), COALESCE(c.cadence_send_end_hour, 18),
            COALESCE(c.cadence_cooldown_hours, 48), COALESCE(c.cadence_max_messages, 8),
            CASE c.status WHEN 'completed' THEN 'archived' WHEN 'paused' THEN 'paused' ELSE 'active' END
        ) RETURNING id INTO new_cadence_id;

        INSERT INTO broadcasts (name, template_name, template_variables, total_leads, sent, failed,
                                status, send_interval_min, send_interval_max, cadence_id, created_at)
        VALUES (
            c.name, c.template_name, COALESCE(c.template_params, '{}'),
            c.total_leads, c.sent, c.failed, c.status,
            COALESCE(c.send_interval_min, 3), COALESCE(c.send_interval_max, 8),
            new_cadence_id, c.created_at
        ) RETURNING id INTO new_broadcast_id;

        INSERT INTO broadcast_leads (broadcast_id, lead_id, status)
        SELECT new_broadcast_id, id,
            CASE status WHEN 'imported' THEN 'pending' WHEN 'template_sent' THEN 'sent'
                        WHEN 'failed' THEN 'failed' ELSE 'sent' END
        FROM leads WHERE campaign_id = c.id;

        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'cadence_state') THEN
            INSERT INTO cadence_enrollments (cadence_id, lead_id, broadcast_id, current_step, status,
                                             total_messages_sent, next_send_at, cooldown_until, responded_at, enrolled_at)
            SELECT new_cadence_id, cs.lead_id, new_broadcast_id, cs.current_step,
                CASE cs.status WHEN 'cooled' THEN 'completed' ELSE cs.status END,
                cs.total_messages_sent, cs.next_send_at, cs.cooldown_until, cs.responded_at, cs.created_at
            FROM cadence_state cs WHERE cs.campaign_id = c.id;
        END IF;
    END LOOP;
END $$;

-- 9. Drop old tables
DROP TABLE IF EXISTS cadence_state CASCADE;
DROP TABLE IF EXISTS campaigns CASCADE;

-- 10. Remove campaign_id from leads
ALTER TABLE leads DROP COLUMN IF EXISTS campaign_id;

-- 11. Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE broadcasts;
ALTER PUBLICATION supabase_realtime ADD TABLE cadences;
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_enrollments;
ALTER PUBLICATION supabase_realtime ADD TABLE broadcast_leads;
```

- [ ] **Step 12: Verificar lista de migrações**

```bash
ls -1 backend/migrations/
```

Expected:
```
001_initial.sql
002_crm_enrichment.sql
003_cadence.sql
004_campaign_type.sql
005_token_usage.sql
006_lead_notes_events.sql
007_multi_channel.sql
008_agent_profile_seed.sql
009_deals.sql
010_campaigns_redesign.sql
```

- [ ] **Step 13: Commit**

```bash
git add backend/migrations/
git commit -m "feat: linearize migrations 001-010 — all idempotent (IF NOT EXISTS + exception guards)"
```

---

## Task 17: Atualizar `deploy.yml` — adicionar step de migração

**Files:**
- Modify: `.github/workflows/deploy.yml`

- [ ] **Step 1: Abrir `.github/workflows/deploy.yml` e localizar o job `deploy-backend`**

No step de SSH (`Deploy Backend via SSH`), após o `git pull origin master` e antes do `docker stack deploy`, adicionar a execução das migrações:

```yaml
          # Apply idempotent migrations before deploying
          for f in ~/Maquinadevendascanastra/backend/migrations/*.sql; do
            echo "Running migration: $f"
            PGPASSWORD=${{ secrets.DB_PASSWORD }} psql \
              -h ${{ secrets.DB_HOST }} \
              -U ${{ secrets.DB_USER }} \
              -d ${{ secrets.DB_NAME }} \
              -f "$f"
          done
```

> **Nota:** Adicione os secrets `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` no GitHub Actions secrets do repositório (correspondem às credenciais do Supabase postgres). Alternativamente, se o Supabase expõe a connection string como `DATABASE_URL`, use:
> ```bash
> for f in ~/Maquinadevendascanastra/backend/migrations/*.sql; do
>   psql "${{ secrets.DATABASE_URL }}" -f "$f"
> done
> ```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add idempotent migration step to deploy-backend job"
```

---

## Task 18: Verificação final — importações e testes

**Files:** nenhum modificado

- [ ] **Step 1: Verificar que não há imports quebrados para os módulos deletados**

```bash
grep -r "from app.whatsapp.factory" backend/app/ 2>/dev/null || echo "OK"
grep -r "from app.whatsapp.client" backend/app/ 2>/dev/null || echo "OK"
grep -r "from app.providers" backend/app/ 2>/dev/null || echo "OK"
grep -r "from app.whatsapp.base import WhatsAppClient" backend/app/ 2>/dev/null || echo "OK"
```

Expected: `OK` nas quatro linhas.

- [ ] **Step 2: Rodar toda a suite de testes**

```bash
cd backend && python -m pytest tests/ -v 2>&1 | tail -40
```

Expected: todos os testes passam. Investigar e corrigir qualquer falha antes de avançar.

- [ ] **Step 3: Verificar que o servidor sobe sem erros de import**

```bash
cd backend && python -c "from app.main import app; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 4: Commit de fixup se necessário**

```bash
git add -A backend/
git commit -m "fix: resolve any remaining import issues after consolidation"
```

---

## Task 19: Deletar os backends legados

Executar somente após a feature branch ter sido revisada, testada e aprovada para merge.

**Files:**
- Delete: `backend-evolution/`
- Delete: `backend-recuperar-lead/`

- [ ] **Step 1: Remover as pastas**

```bash
git rm -r backend-evolution/
git rm -r backend-recuperar-lead/
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove superseded backend forks after consolidation"
```

- [ ] **Step 3: Push da feature branch**

```bash
git push -u origin feat/backend-consolidation
```

- [ ] **Step 4: Abrir PR para master**

```bash
gh pr create \
  --title "feat: consolidate three backend forks into single unified backend" \
  --body "Closes the architectural fragmentation described in docs/superpowers/specs/2026-04-15-backend-consolidation-design.md"
```
