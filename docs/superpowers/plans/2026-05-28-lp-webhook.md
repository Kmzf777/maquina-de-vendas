# LP Webhook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Frontend agents:** OBRIGATÓRIO usar `superpowers:frontend-design` + shadcn/ui para qualquer componente novo.

**Goal:** Substituir o n8n por um endpoint nativo `/webhook/landing-page` no CRM, que salva leads de LPs no Supabase, cria conversa na inbox da Valéria, e dispara template WhatsApp após delay configurável.

**Architecture:** Novo módulo `backend/app/lp_webhook/` com router + service. Agendamento via tabela `follow_up_jobs` com `job_type='lp_welcome'`, processado pelo scheduler existente. Settings persistidos no Redis. Tab novo em Configurações no frontend.

**Tech Stack:** Python/FastAPI, Supabase (supabase-py), Redis (aioredis), Next.js App Router, shadcn/ui, TypeScript.

---

## File Map

### Criar
- `backend/app/lp_webhook/__init__.py` — módulo vazio
- `backend/app/lp_webhook/service.py` — `process_landing_page_lead`, `get_lp_config`, `save_lp_config`, `_schedule_lp_welcome`
- `backend/app/lp_webhook/router.py` — endpoints POST/GET/PUT
- `backend/tests/test_lp_webhook.py` — testes unitários
- `frontend/src/components/config/lp-webhook-tab.tsx` — tab de configurações

### Modificar
- `backend/app/follow_up/scheduler.py` — adicionar handler `_process_lp_welcome` e desvio no loop principal
- `backend/app/main.py` — registrar `lp_webhook_router`
- `frontend/src/app/(authenticated)/config/page.tsx` — adicionar tab "Landing Pages"

---

## Task 1: Backend — `lp_webhook` service

**Files:**
- Create: `backend/app/lp_webhook/__init__.py`
- Create: `backend/app/lp_webhook/service.py`

- [ ] **Step 1: Criar `__init__.py` vazio**

```bash
touch backend/app/lp_webhook/__init__.py
```

- [ ] **Step 2: Escrever o teste que falha**

Crie `backend/tests/test_lp_webhook.py`:

```python
"""Tests for LP webhook service."""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ── get_lp_config ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_lp_config_returns_defaults_when_redis_empty():
    from app.lp_webhook.service import get_lp_config

    redis = AsyncMock()
    redis.get.return_value = None

    config = await get_lp_config(redis)

    assert config["delay_minutes"] == 15
    assert config["language_code"] == "pt_BR"
    assert config["template_name"] == ""
    assert config["channel_id"] == ""


@pytest.mark.anyio
async def test_get_lp_config_merges_stored_values():
    from app.lp_webhook.service import get_lp_config

    redis = AsyncMock()
    redis.get.return_value = json.dumps({
        "channel_id": "abc-123",
        "template_name": "boas_vindas",
        "delay_minutes": 30,
    })

    config = await get_lp_config(redis)

    assert config["channel_id"] == "abc-123"
    assert config["template_name"] == "boas_vindas"
    assert config["delay_minutes"] == 30
    assert config["language_code"] == "pt_BR"  # default preserved


# ── process_landing_page_lead ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_process_lp_lead_invalid_phone_returns_error():
    from app.lp_webhook.service import process_landing_page_lead

    redis = AsyncMock()
    redis.get.return_value = None

    result = await process_landing_page_lead(
        {"nome": "João", "whatsapp": "", "email": "", "origem": "graocafeteria"},
        redis,
    )

    assert result["ok"] is False
    assert "Telefone" in result["error"]


@pytest.mark.anyio
async def test_process_lp_lead_creates_lead_and_conversation():
    from app.lp_webhook.service import process_landing_page_lead

    redis = AsyncMock()
    redis.get.return_value = json.dumps({
        "channel_id": "ch-1",
        "template_name": "boas_vindas",
        "language_code": "pt_BR",
        "delay_minutes": 15,
    })

    mock_lead = {"id": "lead-uuid-1", "phone": "5534999999999", "metadata": {}}
    mock_conv = {"id": "conv-uuid-1"}

    with patch("app.lp_webhook.service.get_or_create_lead", return_value=mock_lead) as mock_get_lead, \
         patch("app.lp_webhook.service.get_or_create_conversation", return_value=mock_conv) as mock_get_conv, \
         patch("app.lp_webhook.service.get_supabase") as mock_sb_fn, \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule:

        mock_sb = MagicMock()
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        mock_sb_fn.return_value = mock_sb

        result = await process_landing_page_lead(
            {
                "nome": "João Silva",
                "whatsapp": "5534999999999",
                "email": "joao@email.com",
                "origem": "graocafeteria",
            },
            redis,
        )

    assert result["ok"] is True
    assert result["lead_id"] == "lead-uuid-1"
    assert result["conversation_id"] == "conv-uuid-1"
    mock_get_lead.assert_called_once_with("5534999999999", name="João Silva")
    mock_get_conv.assert_called_once_with("lead-uuid-1", "ch-1")
    mock_schedule.assert_called_once()


@pytest.mark.anyio
async def test_process_lp_lead_skips_job_when_config_incomplete():
    from app.lp_webhook.service import process_landing_page_lead

    redis = AsyncMock()
    redis.get.return_value = None  # empty config → no channel_id or template

    mock_lead = {"id": "lead-uuid-2", "phone": "5534999999999", "metadata": {}}

    with patch("app.lp_webhook.service.get_or_create_lead", return_value=mock_lead), \
         patch("app.lp_webhook.service.get_supabase") as mock_sb_fn, \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule:

        mock_sb_fn.return_value = MagicMock()

        result = await process_landing_page_lead(
            {"nome": "Ana", "whatsapp": "5534999999998", "email": "", "origem": ""},
            redis,
        )

    assert result["ok"] is True
    mock_schedule.assert_not_called()


# ── _schedule_lp_welcome ──────────────────────────────────────────────────────

def test_schedule_lp_welcome_inserts_correct_job():
    from app.lp_webhook.service import _schedule_lp_welcome

    inserted = []
    mock_insert = MagicMock()
    mock_insert.return_value.execute.side_effect = lambda: inserted.append(
        mock_insert.call_args[0][0]
    ) or MagicMock(data=[{"id": "job-1"}])

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now = datetime(2026, 5, 28, 10, 0, 0, tzinfo=timezone.utc)

    with patch("app.lp_webhook.service.get_supabase", return_value=mock_sb), \
         patch("app.lp_webhook.service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        _schedule_lp_welcome(
            conversation_id="conv-1",
            lead_id="lead-1",
            channel_id="ch-1",
            lead_phone="5534999999999",
            template_name="boas_vindas",
            language_code="pt_BR",
            delay_minutes=15,
        )

    assert len(inserted) == 1
    job = inserted[0]
    assert job["job_type"] == "lp_welcome"
    assert job["sequence"] == 1
    assert job["status"] == "pending"
    assert job["lead_id"] == "lead-1"
    assert job["conversation_id"] == "conv-1"
    assert job["channel_id"] == "ch-1"
    assert job["metadata"]["lead_phone"] == "5534999999999"
    assert job["metadata"]["template_name"] == "boas_vindas"
    assert job["metadata"]["language_code"] == "pt_BR"

    from datetime import timedelta
    fire_at = datetime.fromisoformat(job["fire_at"])
    assert abs((fire_at - (now + timedelta(minutes=15))).total_seconds()) < 2
```

- [ ] **Step 3: Rodar o teste — confirmar que falha com `ModuleNotFoundError`**

```bash
cd backend && python -m pytest tests/test_lp_webhook.py -v 2>&1 | head -20
```

Esperado: `ModuleNotFoundError: No module named 'app.lp_webhook'`

- [ ] **Step 4: Criar `backend/app/lp_webhook/service.py`**

```python
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.db.supabase import get_supabase
from app.leads.service import get_or_create_lead, normalize_phone
from app.conversations.service import get_or_create_conversation

logger = logging.getLogger(__name__)

REDIS_CONFIG_KEY = "lp_webhook:config"

_DEFAULT_CONFIG: dict[str, Any] = {
    "channel_id": "",
    "template_name": "",
    "language_code": "pt_BR",
    "delay_minutes": 15,
}

from app.config import get_settings as _get_settings

_ENV_TAG = "dev" if _get_settings().is_dev_env else "production"


async def get_lp_config(redis) -> dict[str, Any]:
    raw = await redis.get(REDIS_CONFIG_KEY)
    if not raw:
        return dict(_DEFAULT_CONFIG)
    try:
        stored = json.loads(raw)
        return {**_DEFAULT_CONFIG, **stored}
    except Exception:
        return dict(_DEFAULT_CONFIG)


async def save_lp_config(redis, config: dict[str, Any]) -> None:
    await redis.set(REDIS_CONFIG_KEY, json.dumps(config))


async def process_landing_page_lead(payload: dict[str, Any], redis) -> dict[str, Any]:
    raw_phone = payload.get("whatsapp") or ""
    name = payload.get("nome") or None
    email = payload.get("email") or None
    origem = payload.get("origem") or None

    phone = normalize_phone(raw_phone)
    if not phone:
        logger.warning("[LP_WEBHOOK] Telefone inválido: %r", raw_phone)
        return {"ok": False, "error": "Telefone inválido"}

    try:
        lead = get_or_create_lead(phone, name=name)
        lead_id = lead["id"]
    except Exception as exc:
        logger.error("[LP_WEBHOOK] Falha ao criar lead phone=%s: %s", phone, exc)
        return {"ok": False, "error": "Falha ao salvar lead"}

    try:
        sb = get_supabase()
        updates: dict[str, Any] = {}
        if email:
            updates["email"] = email
        if origem:
            existing = lead.get("metadata") or {}
            updates["metadata"] = {**existing, "origem": origem}
        if updates:
            sb.table("leads").update(updates).eq("id", lead_id).execute()
    except Exception as exc:
        logger.warning("[LP_WEBHOOK] Falha ao atualizar campos do lead %s: %s", lead_id, exc)

    config = await get_lp_config(redis)
    channel_id = config.get("channel_id", "")
    template_name = config.get("template_name", "")
    language_code = config.get("language_code", "pt_BR")
    delay_minutes = int(config.get("delay_minutes", 15))

    conversation_id: str | None = None
    if channel_id:
        try:
            conv = get_or_create_conversation(lead_id, channel_id)
            conversation_id = conv["id"]
        except Exception as exc:
            logger.error("[LP_WEBHOOK] Falha ao criar conversa lead=%s: %s", lead_id, exc)

    if channel_id and template_name and conversation_id:
        try:
            _schedule_lp_welcome(
                conversation_id=conversation_id,
                lead_id=lead_id,
                channel_id=channel_id,
                lead_phone=phone,
                template_name=template_name,
                language_code=language_code,
                delay_minutes=delay_minutes,
            )
        except Exception as exc:
            logger.error("[LP_WEBHOOK] Falha ao agendar job lead=%s: %s", lead_id, exc)
    else:
        logger.info(
            "[LP_WEBHOOK] Job não agendado — config incompleta channel_id=%r template=%r conversation=%r",
            channel_id, template_name, conversation_id,
        )

    return {"ok": True, "lead_id": lead_id, "conversation_id": conversation_id}


def _schedule_lp_welcome(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    lead_phone: str,
    template_name: str,
    language_code: str,
    delay_minutes: int,
) -> None:
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    job: dict[str, Any] = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": (now + timedelta(minutes=delay_minutes)).isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "lp_welcome",
        "metadata": {
            "lead_phone": lead_phone,
            "template_name": template_name,
            "language_code": language_code,
        },
    }
    result = sb.table("follow_up_jobs").insert(job).execute()
    if not result.data:
        raise RuntimeError(f"DB insert retornou vazio para lp_welcome job lead={lead_id}")
    logger.info(
        "[LP_WEBHOOK] Job agendado em %dmin lead=%s conversation=%s",
        delay_minutes, lead_id, conversation_id,
    )
```

- [ ] **Step 5: Rodar os testes — confirmar que passam**

```bash
cd backend && python -m pytest tests/test_lp_webhook.py -v
```

Esperado: todos os testes passam (6 testes).

- [ ] **Step 6: Commit**

```bash
git add backend/app/lp_webhook/__init__.py backend/app/lp_webhook/service.py backend/tests/test_lp_webhook.py
git commit -m "feat(lp-webhook): service para salvar lead, conversa e agendar job lp_welcome"
```

---

## Task 2: Backend — `lp_webhook` router

**Files:**
- Create: `backend/app/lp_webhook/router.py`

- [ ] **Step 1: Criar `backend/app/lp_webhook/router.py`**

```python
import logging
from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

from app.lp_webhook.service import process_landing_page_lead, get_lp_config, save_lp_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lp_webhook"])


class LandingPagePayload(BaseModel):
    nome: str = ""
    whatsapp: str = ""
    email: str = ""
    timestamp: str = ""
    origem: str = ""


class LpWebhookSettings(BaseModel):
    channel_id: str = ""
    template_name: str = ""
    language_code: str = "pt_BR"
    delay_minutes: int = 15


@router.post("/webhook/landing-page")
async def landing_page_webhook(payload: LandingPagePayload, request: Request):
    """Recebe lead de landing page. Sem auth — sempre retorna HTTP 200."""
    redis = request.app.state.redis
    data = {
        "nome": payload.nome,
        "whatsapp": payload.whatsapp,
        "email": payload.email,
        "timestamp": payload.timestamp,
        "origem": payload.origem,
    }
    return await process_landing_page_lead(data, redis)


@router.get("/api/lp-webhook/settings")
async def get_settings(request: Request):
    """Retorna configuração atual do webhook de LP."""
    redis = request.app.state.redis
    return await get_lp_config(redis)


@router.put("/api/lp-webhook/settings")
async def update_settings(body: LpWebhookSettings, request: Request):
    """Salva configuração do webhook de LP."""
    redis = request.app.state.redis
    config = {
        "channel_id": body.channel_id,
        "template_name": body.template_name,
        "language_code": body.language_code,
        "delay_minutes": body.delay_minutes,
    }
    await save_lp_config(redis, config)
    return await get_lp_config(redis)
```

- [ ] **Step 2: Registrar o router em `backend/app/main.py`**

Adicione após os outros imports de router (linha ~66):
```python
from app.lp_webhook.router import router as lp_webhook_router
```

Adicione após os outros `app.include_router(...)` (linha ~83):
```python
app.include_router(lp_webhook_router)
```

- [ ] **Step 3: Verificar que o backend sobe sem erro**

```bash
cd backend && python -m uvicorn app.main:app --reload --port 8000 2>&1 | head -20
```

Esperado: `Application startup complete.` sem erros de import.

- [ ] **Step 4: Testar o endpoint manualmente (health check rápido)**

```bash
curl -s -X POST http://localhost:8000/webhook/landing-page \
  -H "Content-Type: application/json" \
  -d '{"nome":"Teste","whatsapp":"","email":"","origem":"graocafeteria"}' | python -m json.tool
```

Esperado: `{"ok": false, "error": "Telefone inválido"}`

```bash
curl -s http://localhost:8000/api/lp-webhook/settings | python -m json.tool
```

Esperado: `{"channel_id": "", "template_name": "", "language_code": "pt_BR", "delay_minutes": 15}`

- [ ] **Step 5: Commit**

```bash
git add backend/app/lp_webhook/router.py backend/app/main.py
git commit -m "feat(lp-webhook): router POST /webhook/landing-page + GET/PUT /api/lp-webhook/settings"
```

---

## Task 3: Backend — scheduler handler `lp_welcome`

**Files:**
- Modify: `backend/app/follow_up/scheduler.py`

- [ ] **Step 1: Escrever o teste que falha**

Adicione ao final de `backend/tests/test_lp_webhook.py`:

```python
# ── _process_lp_welcome (scheduler) ──────────────────────────────────────────

@pytest.mark.anyio
async def test_process_lp_welcome_dispatches_template_and_marks_sent():
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-1",
        "lead_id": "lead-1",
        "conversation_id": "conv-1",
        "channel_id": "ch-1",
        "channels": {"id": "ch-1", "provider": "meta_cloud", "provider_config": {"access_token": "tok"}},
        "metadata": {
            "lead_phone": "5534999999999",
            "template_name": "boas_vindas",
            "language_code": "pt_BR",
        },
    }

    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock()

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider) as mock_meta, \
         patch("app.follow_up.scheduler._mark_sent") as mock_mark_sent:

        await _process_lp_welcome(job, now)

    mock_provider.send_template.assert_awaited_once_with(
        "5534999999999", "boas_vindas", language_code="pt_BR"
    )
    mock_mark_sent.assert_called_once_with("job-lp-1")


@pytest.mark.anyio
async def test_process_lp_welcome_cancels_when_metadata_missing():
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-2",
        "lead_id": "lead-1",
        "channels": {"provider_config": {}},
        "metadata": {},  # sem lead_phone nem template_name
    }

    with patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler.MetaCloudClient") as mock_meta:

        await _process_lp_welcome(job, now)

    mock_cancel.assert_called_once_with("job-lp-2", "missing_metadata")
    mock_meta.assert_not_called()


@pytest.mark.anyio
async def test_process_lp_welcome_does_not_mark_sent_on_send_failure():
    from app.follow_up.scheduler import _process_lp_welcome

    now = datetime(2026, 5, 28, 10, 15, 0, tzinfo=timezone.utc)

    job = {
        "id": "job-lp-3",
        "lead_id": "lead-1",
        "channels": {"provider_config": {}},
        "metadata": {
            "lead_phone": "5534999999999",
            "template_name": "boas_vindas",
            "language_code": "pt_BR",
        },
    }

    mock_provider = AsyncMock()
    mock_provider.send_template.side_effect = Exception("Meta API down")

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider), \
         patch("app.follow_up.scheduler._mark_sent") as mock_mark_sent:

        await _process_lp_welcome(job, now)

    mock_mark_sent.assert_not_called()
```

- [ ] **Step 2: Rodar — confirmar que falha com `ImportError`**

```bash
cd backend && python -m pytest tests/test_lp_webhook.py::test_process_lp_welcome_dispatches_template_and_marks_sent -v 2>&1 | head -10
```

Esperado: `ImportError: cannot import name '_process_lp_welcome'`

- [ ] **Step 3: Adicionar `_process_lp_welcome` em `backend/app/follow_up/scheduler.py`**

Adicione a função após `_process_handoff_rescue` (antes de `_cancel_job`):

```python
async def _process_lp_welcome(job: dict, now: datetime) -> None:
    """Dispara template de boas-vindas para lead capturado por landing page."""
    metadata = job.get("metadata") or {}
    lead_phone = metadata.get("lead_phone")
    template_name = metadata.get("template_name")
    language_code = metadata.get("language_code", "pt_BR")
    channel = job["channels"]

    if not lead_phone or not template_name:
        _cancel_job(job["id"], "missing_metadata")
        logger.error(
            "[LP_WELCOME] Job %s sem lead_phone ou template_name no metadata", job["id"]
        )
        return

    try:
        provider = MetaCloudClient(channel["provider_config"])
        await provider.send_template(lead_phone, template_name, language_code=language_code)
        logger.info("[LP_WELCOME] Template '%s' enviado para %s", template_name, lead_phone)
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Falha ao enviar template para %s: %s", lead_phone, exc, exc_info=True
        )
        return  # Não marca sent → retry automático no próximo tick

    _mark_sent(job["id"])
```

- [ ] **Step 4: Adicionar desvio no loop de `process_due_followups`**

Em `process_due_followups`, após o bloco `if job.get("job_type") == "handoff_rescue":` (linha ~69), adicione:

```python
        if job.get("job_type") == "lp_welcome":
            await _process_lp_welcome(job, now)
            continue
```

O bloco completo deve ficar assim:
```python
    for job in jobs:
        # Rota jobs de resgate de handoff para handler dedicado (antes de qualquer guard padrão)
        if job.get("job_type") == "handoff_rescue":
            await _process_handoff_rescue(job, now)
            continue

        if job.get("job_type") == "lp_welcome":
            await _process_lp_welcome(job, now)
            continue

        conversation_id = job["conversation_id"]
        # ... resto do loop existente
```

- [ ] **Step 5: Rodar todos os testes do arquivo**

```bash
cd backend && python -m pytest tests/test_lp_webhook.py -v
```

Esperado: todos os 9 testes passam.

- [ ] **Step 6: Rodar a suite completa para garantir sem regressões**

```bash
cd backend && python -m pytest tests/ -x -q 2>&1 | tail -10
```

Esperado: suite passa sem falhas novas.

- [ ] **Step 7: Commit**

```bash
git add backend/app/follow_up/scheduler.py backend/tests/test_lp_webhook.py
git commit -m "feat(lp-webhook): handler lp_welcome no scheduler para disparar template WhatsApp"
```

---

## Task 4: Frontend — tab de configurações

> **OBRIGATÓRIO:** Antes de escrever qualquer código frontend, invocar a skill `superpowers:frontend-design`. Usar shadcn/ui para todos os componentes (Select, Input, Button, Card, Label).

**Files:**
- Create: `frontend/src/components/config/lp-webhook-tab.tsx`
- Modify: `frontend/src/app/(authenticated)/config/page.tsx`

- [ ] **Step 1: Invocar skill `superpowers:frontend-design` antes de escrever código**

(Obrigatório — não pule este passo)

- [ ] **Step 2: Instalar componentes shadcn faltantes**

Os componentes `Input` e `Label` não existem ainda. Instalá-los:

```bash
cd frontend && npx shadcn@latest add input label
```

Confirmar que os arquivos foram criados:
```bash
ls frontend/src/components/ui/input.tsx frontend/src/components/ui/label.tsx
```

- [ ] **Step 3: Criar `frontend/src/components/config/lp-webhook-tab.tsx`**

O componente usa shadcn/ui (`Select`, `Input`, `Button`, `Label`, `Card`). Segue o padrão visual da página de config existente (fundo `#faf9f6`, borda `#dedbd6`, texto `#111111`).

```tsx
"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface LpWebhookSettings {
  channel_id: string;
  template_name: string;
  language_code: string;
  delay_minutes: number;
}

interface Channel {
  id: string;
  name: string;
  phone: string;
}

const API_BASE = "";

export function LpWebhookTab() {
  const [settings, setSettings] = useState<LpWebhookSettings>({
    channel_id: "",
    template_name: "",
    language_code: "pt_BR",
    delay_minutes: 15,
  });
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/lp-webhook/settings`).then((r) => r.json()),
      fetch(`${API_BASE}/api/channels`).then((r) => r.json()),
    ])
      .then(([cfg, chs]) => {
        setSettings(cfg);
        setChannels(Array.isArray(chs) ? chs : (chs.data ?? []));
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`${API_BASE}/api/lp-webhook/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (res.ok) {
        const updated = await res.json();
        setSettings(updated);
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch (e) {
      console.error("Failed to save LP webhook settings:", e);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] h-16 animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-[14px] text-[#7b7b78]">
        Configure o canal, template e delay para boas-vindas automáticas de leads capturados pelas landing pages.
      </p>

      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-5 space-y-5">
        {/* Canal */}
        <div className="space-y-1.5">
          <Label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Canal (número da Valéria)
          </Label>
          <Select
            value={settings.channel_id}
            onValueChange={(v) => setSettings((s) => ({ ...s, channel_id: v }))}
          >
            <SelectTrigger className="bg-white border-[#dedbd6] text-[14px] text-[#111111] focus:border-[#111111] focus:ring-0">
              <SelectValue placeholder="Selecione um canal..." />
            </SelectTrigger>
            <SelectContent>
              {channels.map((ch) => (
                <SelectItem key={ch.id} value={ch.id}>
                  {ch.name} — {ch.phone}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Template */}
        <div className="space-y-1.5">
          <Label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Nome do template (Meta)
          </Label>
          <Input
            value={settings.template_name}
            onChange={(e) =>
              setSettings((s) => ({ ...s, template_name: e.target.value }))
            }
            placeholder="ex: boas_vindas_lp"
            className="bg-white border-[#dedbd6] text-[14px] text-[#111111] focus-visible:ring-0 focus-visible:border-[#111111]"
          />
        </div>

        {/* Language code */}
        <div className="space-y-1.5">
          <Label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Language code
          </Label>
          <Input
            value={settings.language_code}
            onChange={(e) =>
              setSettings((s) => ({ ...s, language_code: e.target.value }))
            }
            placeholder="pt_BR"
            className="bg-white border-[#dedbd6] text-[14px] text-[#111111] focus-visible:ring-0 focus-visible:border-[#111111]"
          />
        </div>

        {/* Delay */}
        <div className="space-y-1.5">
          <Label className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">
            Delay (minutos)
          </Label>
          <Input
            type="number"
            min={1}
            max={1440}
            value={settings.delay_minutes}
            onChange={(e) =>
              setSettings((s) => ({
                ...s,
                delay_minutes: parseInt(e.target.value) || 15,
              }))
            }
            className="bg-white border-[#dedbd6] text-[14px] text-[#111111] focus-visible:ring-0 focus-visible:border-[#111111] w-32"
          />
          <p className="text-[11px] text-[#7b7b78]">
            Tempo de espera após o lead submeter o formulário antes de disparar o template.
          </p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button
          onClick={handleSave}
          disabled={saving}
          className="bg-[#111111] text-white px-[14px] py-2 rounded-[4px] text-[14px] transition-transform hover:scale-110 hover:bg-white hover:text-[#111111] hover:border hover:border-[#111111] active:scale-[0.85] disabled:opacity-50"
        >
          {saving ? "Salvando..." : "Salvar"}
        </Button>
        {saved && (
          <span className="text-[13px] text-green-600">Configurações salvas.</span>
        )}
      </div>

      {/* Endpoint info */}
      <div className="bg-[#faf9f6] border border-[#dedbd6] rounded-[8px] p-4">
        <p className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-2">
          Endpoint para as Landing Pages
        </p>
        <code className="text-[13px] text-[#111111] font-mono break-all">
          POST https://crm.canastrainteligencia.com/webhook/landing-page
        </code>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verificar que o TypeScript compila sem erros**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "error|Error" | head -20
```

Esperado: sem erros de tipo.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/input.tsx frontend/src/components/ui/label.tsx frontend/src/components/config/lp-webhook-tab.tsx frontend/src/app/\(authenticated\)/config/page.tsx
git commit -m "feat(lp-webhook): tab Landing Pages em Configuracoes com selecao de canal, template e delay"
```

---

Nota: os steps abaixo (Step 5 e Step 6 originais) foram renumerados acima.

Substituir o conteúdo completo do arquivo:

```tsx
"use client";

import { useState } from "react";
import { TagsTab } from "@/components/config/tags-tab";
import { PricingTab } from "@/components/config/pricing-tab";
import { LpWebhookTab } from "@/components/config/lp-webhook-tab";

const TABS = [
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
  { key: "lp-webhook", label: "Landing Pages" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export default function ConfigPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("tags");

  return (
    <div className="flex flex-col h-full">
      {/* Page Header */}
      <div className="border-b border-[#dedbd6] bg-white px-8 py-5 flex-shrink-0">
        <h1 style={{ letterSpacing: "-0.96px", lineHeight: "1.00" }} className="text-[32px] font-normal text-[#111111]">Configurações</h1>
        <p className="text-[14px] text-[#7b7b78] mt-0.5">Preferências e integrações</p>
      </div>

      <div className="px-4 md:px-8 py-4 md:py-8 overflow-auto flex-1 bg-[#faf9f6]">
        <div className="max-w-3xl">
          <div className="flex border-b border-[#dedbd6] mb-8">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={activeTab === tab.key
                  ? "border-b-2 border-[#111111] text-[#111111] px-4 py-2 text-[14px] font-normal"
                  : "border-b-2 border-transparent text-[#7b7b78] px-4 py-2 text-[14px] font-normal hover:text-[#111111] transition-colors"}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === "tags" && <TagsTab />}
          {activeTab === "pricing" && <PricingTab />}
          {activeTab === "lp-webhook" && <LpWebhookTab />}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Adicionar a tab em `frontend/src/app/(authenticated)/config/page.tsx`**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "error|Error" | head -20
```

Esperado: sem erros de tipo.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config/lp-webhook-tab.tsx frontend/src/app/\(authenticated\)/config/page.tsx
git commit -m "feat(lp-webhook): tab Landing Pages em Configuracoes com selecao de canal, template e delay"
```

---

## Checklist final

- [ ] Endpoint `/webhook/landing-page` aceita payload das LPs e retorna HTTP 200 sempre
- [ ] Lead é criado/atualizado com `email` e `metadata.origem`
- [ ] Conversa é criada na inbox da Valéria
- [ ] Job `lp_welcome` é agendado em `follow_up_jobs` com `fire_at = now + delay_minutes`
- [ ] Scheduler processa `lp_welcome` e envia template via Meta API
- [ ] GET/PUT `/api/lp-webhook/settings` persiste config no Redis
- [ ] Tab "Landing Pages" aparece em Configurações e salva corretamente
- [ ] Todos os testes passam (`python -m pytest tests/ -q`)
- [ ] TypeScript compila sem erros (`npx tsc --noEmit`)
