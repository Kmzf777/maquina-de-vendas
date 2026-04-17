# WhatsApp Template Creation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar backend para criação de templates WhatsApp via Meta Cloud API, com fluxo de reclassificação de categoria (UTILITY → MARKETING detectada pela Meta).

**Architecture:** Novo módulo `app/templates/` com router, service e schemas. Cliente HTTP dedicado `app/whatsapp/meta_templates.py` usando `waba_id` do canal. Fluxo two-step: criação retorna `pending_category_review` se Meta mudar categoria; endpoint `/confirm` ou `DELETE` encerra o fluxo.

**Tech Stack:** FastAPI, Pydantic v2, httpx (já instalado), Supabase (já instalado), pytest com `asyncio_mode = auto`, `unittest.mock`.

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `backend/migrations/011_message_templates.sql` | Criar — tabela `message_templates` |
| `backend/app/whatsapp/meta_templates.py` | Criar — `MetaTemplateClient` |
| `backend/app/templates/__init__.py` | Criar — vazio |
| `backend/app/templates/schemas.py` | Criar — Pydantic models |
| `backend/app/templates/service.py` | Criar — lógica de negócio |
| `backend/app/templates/router.py` | Criar — FastAPI routes |
| `backend/app/main.py` | Modificar — registrar router |
| `backend/tests/test_templates_service.py` | Criar — testes unitários |

---

## Task 1: DB Migration

**Files:**
- Create: `backend/migrations/011_message_templates.sql`

- [ ] **Step 1: Criar o arquivo de migração**

```sql
-- 011_message_templates.sql
-- Tabela para templates de mensagem WhatsApp (Meta Cloud API)

CREATE TABLE IF NOT EXISTS message_templates (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id   uuid        NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    name         text        NOT NULL,
    language     text        NOT NULL DEFAULT 'pt_BR',
    requested_category text  NOT NULL,
    category     text        NOT NULL,
    components   jsonb       NOT NULL DEFAULT '[]',
    meta_template_id text,
    status       text        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'pending_category_review', 'cancelled')),
    created_at   timestamptz NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Aplicar a migração no Supabase**

Execute o SQL acima no SQL Editor do Supabase (ou via CLI se disponível). Verifique que a tabela `message_templates` aparece no schema.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/011_message_templates.sql
git commit -m "feat: add message_templates migration"
```

---

## Task 2: MetaTemplateClient + Schemas

**Files:**
- Create: `backend/app/whatsapp/meta_templates.py`
- Create: `backend/app/templates/__init__.py`
- Create: `backend/app/templates/schemas.py`

- [ ] **Step 1: Criar `meta_templates.py`**

```python
# backend/app/whatsapp/meta_templates.py
import logging
import httpx

META_API_BASE = "https://graph.facebook.com/v21.0"
logger = logging.getLogger(__name__)


class MetaTemplateClient:
    def __init__(self, waba_id: str, access_token: str):
        self.waba_id = waba_id
        self.access_token = access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def create_template(self, payload: dict) -> dict:
        url = f"{META_API_BASE}/{self.waba_id}/message_templates"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if not resp.is_success:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text
                logger.error(
                    "[Meta Templates] %s %s — payload: %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    payload,
                    error_body,
                )
            resp.raise_for_status()
            return resp.json()

    async def delete_template(self, meta_template_id: str) -> None:
        url = f"{META_API_BASE}/{meta_template_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, headers=self._headers())
            if not resp.is_success:
                logger.error(
                    "[Meta Templates] DELETE failed %s — template_id: %s",
                    resp.status_code,
                    meta_template_id,
                )
            resp.raise_for_status()
```

- [ ] **Step 2: Criar `app/templates/__init__.py`**

Arquivo vazio:
```python
```

- [ ] **Step 3: Criar `app/templates/schemas.py`**

```python
# backend/app/templates/schemas.py
from pydantic import BaseModel
from typing import Literal


class TemplateButton(BaseModel):
    type: str
    text: str
    url: str | None = None
    phone_number: str | None = None
    payload: str | None = None


class TemplateComponent(BaseModel):
    type: Literal["HEADER", "BODY", "FOOTER", "BUTTONS"]
    format: str | None = None
    text: str | None = None
    buttons: list[TemplateButton] | None = None


class TemplateCreate(BaseModel):
    name: str
    language: str = "pt_BR"
    category: Literal["UTILITY", "MARKETING"]
    components: list[TemplateComponent]
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/whatsapp/meta_templates.py backend/app/templates/__init__.py backend/app/templates/schemas.py
git commit -m "feat: add MetaTemplateClient and template schemas"
```

---

## Task 3: Service — create_template (TDD)

**Files:**
- Create: `backend/tests/test_templates_service.py`
- Create: `backend/app/templates/service.py`

- [ ] **Step 1: Escrever os testes de criação (arquivo completo)**

```python
# backend/tests/test_templates_service.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Fixtures de dados reutilizáveis
CHANNEL_META = {
    "id": "chan-1",
    "provider": "meta_cloud",
    "provider_config": {
        "phone_number_id": "111",
        "access_token": "tok-test",
        "waba_id": "waba-123",
    },
}

TEMPLATE_DATA = {
    "name": "order_update_v1",
    "language": "pt_BR",
    "category": "UTILITY",
    "components": [
        {"type": "BODY", "text": "Olá {{1}}, seu pedido foi atualizado."}
    ],
}

DB_RECORD_PENDING = {
    "id": "tpl-1",
    "channel_id": "chan-1",
    "name": "order_update_v1",
    "language": "pt_BR",
    "requested_category": "UTILITY",
    "category": "UTILITY",
    "status": "pending",
    "meta_template_id": "meta-tpl-1",
    "components": TEMPLATE_DATA["components"],
}

DB_RECORD_REVIEW = {
    **DB_RECORD_PENDING,
    "id": "tpl-2",
    "category": "MARKETING",
    "status": "pending_category_review",
    "meta_template_id": "meta-tpl-2",
}


# --- create_template ---

async def test_create_template_no_category_divergence():
    """Meta retorna mesma categoria → status pending, HTTP 201."""
    meta_resp = {"id": "meta-tpl-1", "status": "PENDING", "category": "UTILITY"}

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [DB_RECORD_PENDING]

    with patch("app.templates.service.get_channel", return_value=CHANNEL_META), \
         patch("app.templates.service.get_supabase", return_value=mock_sb), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        MockClient.return_value.create_template = AsyncMock(return_value=meta_resp)

        from app.templates.service import create_template
        result, status = await create_template("chan-1", TEMPLATE_DATA)

    assert status == "pending"
    assert result["status"] == "pending"
    assert "suggested_category" not in result


async def test_create_template_category_divergence():
    """Meta muda UTILITY → MARKETING → status pending_category_review, HTTP 202."""
    meta_resp = {"id": "meta-tpl-2", "status": "PENDING", "category": "MARKETING"}

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [DB_RECORD_REVIEW]

    with patch("app.templates.service.get_channel", return_value=CHANNEL_META), \
         patch("app.templates.service.get_supabase", return_value=mock_sb), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        MockClient.return_value.create_template = AsyncMock(return_value=meta_resp)

        from app.templates.service import create_template
        result, status = await create_template("chan-1", TEMPLATE_DATA)

    assert status == "pending_category_review"
    assert result["suggested_category"] == "MARKETING"
    assert result["template"]["status"] == "pending_category_review"
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
cd backend && pytest tests/test_templates_service.py::test_create_template_no_category_divergence tests/test_templates_service.py::test_create_template_category_divergence -v
```

Esperado: `ModuleNotFoundError` ou `ImportError` — `service.py` ainda não existe.

- [ ] **Step 3: Criar `app/templates/service.py` com create_template**

```python
# backend/app/templates/service.py
import logging
from fastapi import HTTPException
from app.db.supabase import get_supabase
from app.channels.service import get_channel
from app.whatsapp.meta_templates import MetaTemplateClient

logger = logging.getLogger(__name__)


def _get_meta_client(channel: dict) -> MetaTemplateClient:
    if channel.get("provider") != "meta_cloud":
        raise HTTPException(400, "Templates are only supported for meta_cloud channels")
    config = channel.get("provider_config", {})
    waba_id = config.get("waba_id")
    if not waba_id:
        raise HTTPException(400, "Channel provider_config is missing 'waba_id'")
    return MetaTemplateClient(waba_id=waba_id, access_token=config["access_token"])


async def create_template(channel_id: str, data: dict) -> tuple[dict, str]:
    channel = get_channel(channel_id)
    meta_client = _get_meta_client(channel)

    requested_category = data["category"]
    payload = {
        "name": data["name"],
        "language": data["language"],
        "category": requested_category,
        "components": data["components"],
    }

    try:
        meta_response = await meta_client.create_template(payload)
    except Exception:
        raise HTTPException(502, "Failed to create template on Meta")

    meta_category = meta_response.get("category", requested_category)
    meta_template_id = meta_response.get("id")
    category_changed = meta_category != requested_category
    status = "pending_category_review" if category_changed else "pending"

    sb = get_supabase()
    record = (
        sb.table("message_templates")
        .insert({
            "channel_id": channel_id,
            "name": data["name"],
            "language": data["language"],
            "requested_category": requested_category,
            "category": meta_category,
            "components": data["components"],
            "meta_template_id": meta_template_id,
            "status": status,
        })
        .execute()
        .data[0]
    )

    result: dict = {"status": status, "template": record}
    if category_changed:
        result["suggested_category"] = meta_category
    return result, status


async def confirm_template(channel_id: str, template_id: str) -> dict:
    pass


async def delete_template(channel_id: str, template_id: str) -> dict:
    pass
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
cd backend && pytest tests/test_templates_service.py::test_create_template_no_category_divergence tests/test_templates_service.py::test_create_template_category_divergence -v
```

Esperado: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_templates_service.py backend/app/templates/service.py
git commit -m "feat: implement create_template with category divergence detection"
```

---

## Task 4: Service — confirm_template e delete_template (TDD)

**Files:**
- Modify: `backend/tests/test_templates_service.py` (adicionar testes)
- Modify: `backend/app/templates/service.py` (implementar funções)

- [ ] **Step 1: Adicionar testes de confirm e delete ao arquivo de testes**

Adicione ao final de `backend/tests/test_templates_service.py`:

```python
# --- confirm_template ---

async def test_confirm_template_updates_status_to_pending():
    """Confirm aceita categoria sugerida → status vira pending."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .limit.return_value.execute.return_value.data = [DB_RECORD_REVIEW]
    mock_sb.table.return_value.update.return_value.eq.return_value \
        .execute.return_value.data = [{**DB_RECORD_REVIEW, "status": "pending"}]

    with patch("app.templates.service.get_supabase", return_value=mock_sb):
        from app.templates.service import confirm_template
        result = await confirm_template("chan-1", "tpl-2")

    assert result["status"] == "pending"
    assert result["template"]["status"] == "pending"


async def test_confirm_template_wrong_status_raises_409():
    """Confirm em template que não está em pending_category_review → 409."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .limit.return_value.execute.return_value.data = [DB_RECORD_PENDING]  # status = "pending"

    with patch("app.templates.service.get_supabase", return_value=mock_sb):
        from app.templates.service import confirm_template
        with pytest.raises(HTTPException) as exc:
            await confirm_template("chan-1", "tpl-1")
        assert exc.value.status_code == 409


# --- delete_template ---

async def test_delete_template_calls_meta_and_cancels():
    """Delete chama Meta DELETE e muda status para cancelled."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .limit.return_value.execute.return_value.data = [DB_RECORD_REVIEW]

    with patch("app.templates.service.get_channel", return_value=CHANNEL_META), \
         patch("app.templates.service.get_supabase", return_value=mock_sb), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        MockClient.return_value.delete_template = AsyncMock()
        from app.templates.service import delete_template
        result = await delete_template("chan-1", "tpl-2")

        MockClient.return_value.delete_template.assert_called_once_with("meta-tpl-2")

    assert result["status"] == "cancelled"


async def test_delete_template_cancels_even_if_meta_fails():
    """Se DELETE na Meta falhar, Supabase ainda é atualizado para cancelled."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .limit.return_value.execute.return_value.data = [DB_RECORD_REVIEW]

    with patch("app.templates.service.get_channel", return_value=CHANNEL_META), \
         patch("app.templates.service.get_supabase", return_value=mock_sb), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        MockClient.return_value.delete_template = AsyncMock(side_effect=Exception("Meta error"))
        from app.templates.service import delete_template
        result = await delete_template("chan-1", "tpl-2")

    assert result["status"] == "cancelled"
```

Também adicione o import que faltará nos testes:
```python
# Adicione ao topo do arquivo, após os imports existentes:
from fastapi import HTTPException
```

- [ ] **Step 2: Rodar os novos testes e confirmar que falham**

```bash
cd backend && pytest tests/test_templates_service.py::test_confirm_template_updates_status_to_pending tests/test_templates_service.py::test_confirm_template_wrong_status_raises_409 tests/test_templates_service.py::test_delete_template_calls_meta_and_cancels tests/test_templates_service.py::test_delete_template_cancels_even_if_meta_fails -v
```

Esperado: 4 falhas — `confirm_template` e `delete_template` retornam `None`.

- [ ] **Step 3: Implementar confirm_template e delete_template em `service.py`**

Substitua as funções `confirm_template` e `delete_template` no final de `backend/app/templates/service.py`:

```python
async def confirm_template(channel_id: str, template_id: str) -> dict:
    sb = get_supabase()
    res = (
        sb.table("message_templates")
        .select("*")
        .eq("id", template_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Template not found")
    template = res.data[0]
    if template["status"] != "pending_category_review":
        raise HTTPException(409, "Template is not in pending_category_review state")

    updated = (
        sb.table("message_templates")
        .update({"status": "pending"})
        .eq("id", template_id)
        .execute()
        .data[0]
    )
    return {"status": "pending", "template": updated}


async def delete_template(channel_id: str, template_id: str) -> dict:
    channel = get_channel(channel_id)
    meta_client = _get_meta_client(channel)

    sb = get_supabase()
    res = (
        sb.table("message_templates")
        .select("*")
        .eq("id", template_id)
        .eq("channel_id", channel_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Template not found")
    template = res.data[0]

    meta_template_id = template.get("meta_template_id")
    if meta_template_id:
        try:
            await meta_client.delete_template(meta_template_id)
        except Exception:
            logger.warning(
                "Failed to delete template %s from Meta, proceeding with local cancellation",
                meta_template_id,
            )

    sb.table("message_templates").update({"status": "cancelled"}).eq("id", template_id).execute()
    return {"status": "cancelled"}
```

- [ ] **Step 4: Rodar todos os testes do arquivo**

```bash
cd backend && pytest tests/test_templates_service.py -v
```

Esperado: 6 testes passando.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_templates_service.py backend/app/templates/service.py
git commit -m "feat: implement confirm_template and delete_template"
```

---

## Task 5: Service — error cases (TDD)

**Files:**
- Modify: `backend/tests/test_templates_service.py` (adicionar testes)
- (service.py já implementado — os testes devem passar sem mudanças)

- [ ] **Step 1: Adicionar testes de erro ao arquivo de testes**

Adicione ao final de `backend/tests/test_templates_service.py`:

```python
# --- error cases ---

async def test_create_template_evolution_channel_raises_400():
    """Canal evolution não suporta templates → 400 sem chamar Meta."""
    evolution_channel = {
        "id": "chan-2",
        "provider": "evolution",
        "provider_config": {},
    }

    with patch("app.templates.service.get_channel", return_value=evolution_channel), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        from app.templates.service import create_template
        with pytest.raises(HTTPException) as exc:
            await create_template("chan-2", TEMPLATE_DATA)

        assert exc.value.status_code == 400
        MockClient.assert_not_called()


async def test_create_template_missing_waba_id_raises_400():
    """provider_config sem waba_id → 400 sem chamar Meta."""
    channel_no_waba = {
        "id": "chan-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    }

    with patch("app.templates.service.get_channel", return_value=channel_no_waba), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        from app.templates.service import create_template
        with pytest.raises(HTTPException) as exc:
            await create_template("chan-1", TEMPLATE_DATA)

        assert exc.value.status_code == 400
        MockClient.assert_not_called()
```

- [ ] **Step 2: Rodar os novos testes**

```bash
cd backend && pytest tests/test_templates_service.py::test_create_template_evolution_channel_raises_400 tests/test_templates_service.py::test_create_template_missing_waba_id_raises_400 -v
```

Esperado: `2 passed` — a lógica já está em `_get_meta_client`.

- [ ] **Step 3: Rodar a suite completa**

```bash
cd backend && pytest tests/test_templates_service.py -v
```

Esperado: `8 passed`

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_templates_service.py
git commit -m "test: add error case coverage for template service"
```

---

## Task 6: Router + registrar em main.py

**Files:**
- Create: `backend/app/templates/router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Criar `app/templates/router.py`**

```python
# backend/app/templates/router.py
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.templates.schemas import TemplateCreate
from app.templates import service

router = APIRouter(prefix="/api/channels/{channel_id}/templates", tags=["templates"])


@router.post("")
async def create_template(channel_id: str, body: TemplateCreate):
    result, status = await service.create_template(
        channel_id, body.model_dump(exclude_none=True)
    )
    code = 202 if status == "pending_category_review" else 201
    return JSONResponse(content=result, status_code=code)


@router.post("/{template_id}/confirm")
async def confirm_template(channel_id: str, template_id: str):
    return await service.confirm_template(channel_id, template_id)


@router.delete("/{template_id}")
async def delete_template(channel_id: str, template_id: str):
    return await service.delete_template(channel_id, template_id)
```

- [ ] **Step 2: Registrar o router em `main.py`**

No bloco `# --- Routers ---` de `backend/app/main.py`, adicione após a linha do `dev_router`:

```python
from app.templates.router import router as templates_router
```

E logo abaixo, após `app.include_router(dev_router)`:

```python
app.include_router(templates_router)
```

- [ ] **Step 3: Rodar toda a suite de testes**

```bash
cd backend && pytest -v
```

Esperado: todos os testes passando, sem regressões.

- [ ] **Step 4: Commit final**

```bash
git add backend/app/templates/router.py backend/app/main.py
git commit -m "feat: add templates router and register in app"
```

---

## Verificação manual pós-implementação

Antes de considerar a feature completa, certifique-se de que:

1. O `provider_config` de pelo menos um canal `meta_cloud` no Supabase inclui o campo `waba_id`
2. O endpoint responde com `201` para templates sem divergência e `202` para divergência detectada
3. O fluxo confirm → `pending` funciona via `POST /{template_id}/confirm`
4. O fluxo cancel → `cancelled` funciona via `DELETE /{template_id}`
