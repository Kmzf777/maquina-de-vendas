# Handoff Rescue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando `encaminhar_humano` é invocada, enviar mensagem de redirecionamento imediata pelo canal da IA e agendar um job de resgate de 15 min que dispara o template `rabubens` pelo número do João se o lead não o contatar.

**Architecture:** Estende a tabela `follow_up_jobs` existente com duas colunas (`job_type`, `metadata`) para distinguir jobs de resgate de handoff dos follow-ups padrão. O worker que já roda a cada 5 s roteia jobs `job_type='handoff_rescue'` para um handler dedicado sem tocar na lógica padrão.

**Tech Stack:** Python 3.12, FastAPI, Supabase (PostgreSQL via supabase-py), pytest + pytest-asyncio, unittest.mock

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `backend/migrations/20260523_handoff_rescue_job_type.sql` | CRIAR | Adiciona `job_type` e `metadata` na `follow_up_jobs` |
| `backend/app/agent/tools.py` | MODIFICAR | `encaminhar_humano`: envia texto de handoff + agenda rescue |
| `backend/app/follow_up/service.py` | MODIFICAR | Adiciona `schedule_handoff_rescue()` |
| `backend/app/follow_up/scheduler.py` | MODIFICAR | Roteia `handoff_rescue`, adiciona `_process_handoff_rescue()` |
| `backend/tests/test_encaminhar_humano_pipeline.py` | MODIFICAR | Atualiza testes existentes + adiciona casos do novo comportamento |
| `backend/tests/test_handoff_rescue.py` | CRIAR | Testes de `schedule_handoff_rescue` e `_process_handoff_rescue` |

---

## Task 1: Criar branch e migration SQL

**Files:**
- Create: `backend/migrations/20260523_handoff_rescue_job_type.sql`

- [ ] **Step 1: Criar branch**

```bash
git checkout -b feat/handoff-rescue
```

- [ ] **Step 2: Criar arquivo de migration**

Criar `backend/migrations/20260523_handoff_rescue_job_type.sql` com o conteúdo:

```sql
-- 20260523_handoff_rescue_job_type.sql
-- Adiciona job_type e metadata à follow_up_jobs para suportar jobs de resgate de handoff.
-- job_type='standard' é o default; registros existentes não são afetados.
ALTER TABLE follow_up_jobs
  ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'standard',
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_followup_jobs_type
  ON follow_up_jobs (job_type, status)
  WHERE status = 'pending';
```

- [ ] **Step 3: Aplicar migration no Supabase via MCP**

Usar a ferramenta `mcp__plugin_supabase_supabase__apply_migration` com:
- `name`: `20260523_handoff_rescue_job_type`
- `query`: conteúdo do SQL acima

- [ ] **Step 4: Verificar colunas no Supabase**

Usar `mcp__plugin_supabase_supabase__execute_sql` com:
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'follow_up_jobs'
  AND column_name IN ('job_type', 'metadata')
ORDER BY column_name;
```

Resultado esperado: 2 linhas com `job_type` (text, default 'standard') e `metadata` (jsonb, default '{}').

- [ ] **Step 5: Commit da migration**

```bash
git add backend/migrations/20260523_handoff_rescue_job_type.sql
git commit -m "feat(db): add job_type and metadata columns to follow_up_jobs"
```

---

## Task 2: Testes para o novo comportamento de `encaminhar_humano`

**Files:**
- Modify: `backend/tests/test_encaminhar_humano_pipeline.py`

- [ ] **Step 1: Atualizar os dois testes existentes com mocks obrigatórios**

Os testes existentes começarão a falhar porque o handler agora chama `get_channel_for_lead` e `schedule_handoff_rescue`. Adicionar mocks a ambos os testes em `test_encaminhar_humano_pipeline.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock

from app.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_encaminhar_humano_atacado_usa_category_correta(monkeypatch):
    calls = []

    def fake_create_deal(lead_id, title, **kwargs):
        calls.append({"lead_id": lead_id, "title": title, **kwargs})
        return {"id": "deal-fake"}

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado", "phone": "+5511999999999"})
    monkeypatch.setattr("app.agent.tools.create_deal", fake_create_deal)
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kwargs: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="+5511999999999",
            conversation_id="conv-1",
        )

    assert len(calls) == 1
    assert calls[0]["category"] == "atacado"


@pytest.mark.asyncio
async def test_encaminhar_humano_private_label_usa_category_correta(monkeypatch):
    calls = []

    def fake_create_deal(lead_id, title, **kwargs):
        calls.append({"lead_id": lead_id, "title": title, **kwargs})
        return {"id": "deal-fake"}

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-2", "stage": "private_label", "phone": "+5511999999999"})
    monkeypatch.setattr("app.agent.tools.create_deal", fake_create_deal)
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kwargs: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "qualificado"},
            lead_id="lead-2",
            phone="+5511999999999",
            conversation_id="conv-1",
        )

    assert len(calls) == 1
    assert calls[0]["category"] == "private_label"
```

- [ ] **Step 2: Adicionar 3 novos testes ao mesmo arquivo**

```python
@pytest.mark.asyncio
async def test_encaminhar_humano_sends_handoff_text_via_ai_channel(monkeypatch):
    """encaminhar_humano envia mensagem de redirecionamento pelo canal da IA."""
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.123"}]})

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    mock_provider.send_text.assert_called_once()
    _, sent_msg = mock_provider.send_text.call_args[0]
    assert "wa.me/553491461669" in sent_msg
    assert "João" in sent_msg


@pytest.mark.asyncio
async def test_encaminhar_humano_schedules_rescue_job(monkeypatch):
    """encaminhar_humano chama schedule_handoff_rescue com lead_id, phone e conv_id."""
    rescue_calls = []
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.123"}]})

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-ai-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: rescue_calls.append(kw))

    with patch("app.agent.tools.save_message"):
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    assert len(rescue_calls) == 1
    assert rescue_calls[0]["lead_id"] == "lead-1"
    assert rescue_calls[0]["lead_phone"] == "5511999999999"
    assert rescue_calls[0]["conversation_id"] == "conv-1"
    assert rescue_calls[0]["channel_id"] == "ch-ai-1"


@pytest.mark.asyncio
async def test_encaminhar_humano_schedules_rescue_even_if_send_text_fails(monkeypatch):
    """Falha no send_text não impede agendamento do job de resgate."""
    rescue_calls = []
    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(side_effect=RuntimeError("network error"))

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: {"id": "lead-1", "stage": "atacado"})
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: {
        "id": "ch-ai-1", "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "111", "access_token": "tok"},
    })
    monkeypatch.setattr("app.agent.tools.get_provider", lambda channel: mock_provider)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: rescue_calls.append(kw))

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "João", "motivo": "qualificado"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    assert len(rescue_calls) == 1
    assert "encaminhado" in result.lower()
```

- [ ] **Step 3: Rodar os testes e confirmar que falham (arquivo ainda não foi modificado)**

```bash
cd backend
python -m pytest tests/test_encaminhar_humano_pipeline.py -v 2>&1 | tail -20
```

Esperado: falhas em `test_encaminhar_humano_sends_handoff_text_via_ai_channel`, `test_encaminhar_humano_schedules_rescue_job` e `test_encaminhar_humano_schedules_rescue_even_if_send_text_fails` por `ImportError` ou `AttributeError` (funções ainda não existem em tools.py).

---

## Task 3: Implementar mudanças em `tools.py`

**Files:**
- Modify: `backend/app/agent/tools.py`

- [ ] **Step 1: Atualizar imports no topo do arquivo**

No topo de `backend/app/agent/tools.py`, alterar a linha de import de `app.channels.service`:

```python
# Antes:
from app.channels.service import get_active_channel

# Depois:
from app.channels.service import get_active_channel, get_channel_for_lead
```

E adicionar import de `schedule_handoff_rescue` logo após os imports existentes de `app`:

```python
from app.follow_up.service import schedule_handoff_rescue
```

- [ ] **Step 2: Definir constante da mensagem de handoff**

Após as definições de `PRODUTO_PHOTO_MAP` (antes de `TOOLS_SCHEMA`), adicionar:

```python
_HANDOFF_MSG = (
    "Perfeito! Seu atendimento agora será continuado pelo João, um dos nossos especialistas.\n\n"
    "👉 Clique no link abaixo e envie uma mensagem para ele agora mesmo para dar continuidade "
    "no seu atendimento com prioridade:\n"
    "http://wa.me/553491461669\n\n"
    "Assim que você chamar, ele já receberá seu contato e continuará seu atendimento."
)
```

- [ ] **Step 3: Substituir o bloco `elif tool_name == "encaminhar_humano":`**

Localizar o bloco que começa em `elif tool_name == "encaminhar_humano":` (termina em `return f"Lead encaminhado para {vendedor}"`) e substituir por:

```python
    elif tool_name == "encaminhar_humano":
        motivo = args.get("motivo", "lead qualificado")
        vendedor = args.get("vendedor", "Vendedor")
        try:
            update_lead(lead_id, status="converted", human_control=True, ai_enabled=False)
        except Exception as exc:
            logger.error(
                "CRITICAL: encaminhar_humano failed to set ai_enabled=False for lead %s: %s",
                lead_id, exc, exc_info=True,
            )
            save_message(
                lead_id, "system",
                f"[encaminhar_humano][ERRO] nao foi possivel desativar AI: {exc}",
                conversation_id=conversation_id,
            )
            return f"CRITICAL: erro ao encaminhar para {vendedor} — humano precisa verificar lead manualmente"
        try:
            lead = get_lead(lead_id)
            lead_stage = lead.get("stage") if lead else None
            create_deal(lead_id, title=f"{vendedor} - {motivo}", category=lead_stage)
        except Exception as exc:
            logger.error(
                "encaminhar_humano failed to create deal for lead %s: %s",
                lead_id, exc, exc_info=True,
            )
        save_message(lead_id, "system", f"[encaminhar_humano] Lead encaminhado para {vendedor}: {motivo}", conversation_id=conversation_id)
        channel = get_channel_for_lead(lead_id)
        if channel:
            try:
                await get_provider(channel).send_text(phone, _HANDOFF_MSG)
                save_message(lead_id, "assistant", _HANDOFF_MSG, sent_by="handoff", conversation_id=conversation_id)
            except Exception as exc:
                logger.error(
                    "encaminhar_humano: falha ao enviar mensagem de handoff para lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
            try:
                schedule_handoff_rescue(
                    lead_id=lead_id,
                    lead_phone=phone,
                    conversation_id=conversation_id,
                    channel_id=channel["id"],
                )
            except Exception as exc:
                logger.error(
                    "encaminhar_humano: falha ao agendar rescue job para lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
        else:
            logger.warning(
                "encaminhar_humano: nenhum canal ativo para lead %s — mensagem de handoff e rescue job ignorados",
                lead_id,
            )
        return f"Lead encaminhado para {vendedor}"
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
cd backend
python -m pytest tests/test_encaminhar_humano_pipeline.py -v 2>&1 | tail -20
```

Esperado: todos os 5 testes passando (`PASSED`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/test_encaminhar_humano_pipeline.py
git commit -m "feat(tools): encaminhar_humano sends handoff message and schedules rescue job"
```

---

## Task 4: `schedule_handoff_rescue` — testes e implementação

**Files:**
- Modify: `backend/app/follow_up/service.py`
- Create: `backend/tests/test_handoff_rescue.py`

- [ ] **Step 1: Escrever testes para `schedule_handoff_rescue`**

Criar `backend/tests/test_handoff_rescue.py`:

```python
"""Tests for handoff rescue: schedule_handoff_rescue and _process_handoff_rescue."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
import pytest


# ─── schedule_handoff_rescue ────────────────────────────────────────────────

def test_schedule_handoff_rescue_inserts_job_with_correct_fields():
    """Insere job com job_type='handoff_rescue', sequence=0, fire_at=now+15min."""
    from app.follow_up.service import schedule_handoff_rescue

    inserted = []
    mock_insert = MagicMock()
    mock_insert.execute.side_effect = lambda: inserted.append(
        mock_insert.call_args[0][0]
    ) or MagicMock()

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert = mock_insert

    now = datetime(2026, 5, 23, 12, 0, 0, tzinfo=timezone.utc)

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.service.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        schedule_handoff_rescue(
            lead_id="lead-1",
            lead_phone="5511999999999",
            conversation_id="conv-1",
            channel_id="ch-1",
        )

    assert len(inserted) == 1
    job = inserted[0]
    assert job["job_type"] == "handoff_rescue"
    assert job["sequence"] == 0
    assert job["status"] == "pending"
    assert job["lead_id"] == "lead-1"
    assert job["conversation_id"] == "conv-1"
    assert job["channel_id"] == "ch-1"
    assert job["metadata"]["lead_phone"] == "5511999999999"
    assert job["metadata"]["joao_phone_number_id"] == "1049315514934778"
    assert job["metadata"]["template_name"] == "rabubens"

    fire_at = datetime.fromisoformat(job["fire_at"])
    expected = now + timedelta(minutes=15)
    assert abs((fire_at - expected).total_seconds()) < 2


def test_schedule_handoff_rescue_raises_on_db_error():
    """Erro no insert é propagado como RuntimeError."""
    from app.follow_up.service import schedule_handoff_rescue

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception("db down")

    with patch("app.follow_up.service.get_supabase", return_value=mock_sb):
        with pytest.raises(RuntimeError, match="Falha ao agendar"):
            schedule_handoff_rescue(
                lead_id="lead-1",
                lead_phone="5511999999999",
                conversation_id="conv-1",
                channel_id="ch-1",
            )
```

- [ ] **Step 2: Rodar para confirmar que falham**

```bash
cd backend
python -m pytest tests/test_handoff_rescue.py::test_schedule_handoff_rescue_inserts_job_with_correct_fields tests/test_handoff_rescue.py::test_schedule_handoff_rescue_raises_on_db_error -v 2>&1 | tail -15
```

Esperado: `ImportError` ou `AttributeError` — `schedule_handoff_rescue` ainda não existe.

- [ ] **Step 3: Implementar `schedule_handoff_rescue` em `service.py`**

No final de `backend/app/follow_up/service.py`, adicionar as constantes e a função (manter todos os imports existentes):

```python
_JOAO_PHONE_NUMBER_ID = "1049315514934778"
_HANDOFF_RESCUE_TEMPLATE = "rabubens"
_HANDOFF_RESCUE_DELAY_MINUTES = 15


def schedule_handoff_rescue(
    lead_id: str,
    lead_phone: str,
    conversation_id: str,
    channel_id: str,
) -> None:
    """Agenda job de resgate de handoff (fire_at = now + 15 min)."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 0,
        "job_type": "handoff_rescue",
        "fire_at": (now + timedelta(minutes=_HANDOFF_RESCUE_DELAY_MINUTES)).isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "metadata": {
            "lead_phone": lead_phone,
            "joao_phone_number_id": _JOAO_PHONE_NUMBER_ID,
            "template_name": _HANDOFF_RESCUE_TEMPLATE,
        },
    }
    try:
        sb.table("follow_up_jobs").insert(job).execute()
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Erro ao agendar job de resgate para lead {lead_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao agendar job de resgate para lead {lead_id}"
        ) from exc
    logger.info(
        f"[HANDOFF_RESCUE] Agendado resgate em {_HANDOFF_RESCUE_DELAY_MINUTES} min — lead={lead_id}"
    )
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
cd backend
python -m pytest tests/test_handoff_rescue.py::test_schedule_handoff_rescue_inserts_job_with_correct_fields tests/test_handoff_rescue.py::test_schedule_handoff_rescue_raises_on_db_error -v 2>&1 | tail -15
```

Esperado: 2 testes `PASSED`.

---

## Task 5: `_process_handoff_rescue` — testes e implementação

**Files:**
- Modify: `backend/app/follow_up/scheduler.py`
- Modify: `backend/tests/test_handoff_rescue.py`

- [ ] **Step 1: Adicionar testes de `_process_handoff_rescue` em `test_handoff_rescue.py`**

Adicionar ao final do arquivo `backend/tests/test_handoff_rescue.py`:

```python
# ─── _process_handoff_rescue (via process_due_followups) ────────────────────

def _make_rescue_job():
    return {
        "id": "job-rescue-1",
        "conversation_id": "conv-ai-1",
        "lead_id": "lead-1",
        "channel_id": "ch-ai-1",
        "sequence": 0,
        "job_type": "handoff_rescue",
        "leads": {
            "id": "lead-1",
            "phone": "5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-ai-1",
            "name": "Canal IA",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "111", "access_token": "tok"},
            "mode": "ai",
        },
        "conversations": {"id": "conv-ai-1", "stage": "atacado", "followup_enabled": True},
        "metadata": {
            "lead_phone": "5511999999999",
            "joao_phone_number_id": "1049315514934778",
            "template_name": "rabubens",
        },
    }


@pytest.mark.asyncio
async def test_handoff_rescue_sends_template_when_lead_has_not_contacted_joao():
    """Lead sem nenhuma conversa com canal do João → dispara template rabubens."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    # Sem conversas entre lead e canal do João
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.456"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_meta.send_template.assert_called_once_with("5511999999999", "rabubens")
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_skips_template_when_lead_already_replied_to_joao():
    """Lead que já enviou msg para João nos últimos 15 min → sem template, job marcado sent."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    conv_result = MagicMock()
    conv_result.data = [{"id": "conv-joao-1"}]
    msg_result = MagicMock()
    msg_result.data = [{"id": "msg-user-1"}]

    def _table(name):
        tbl = MagicMock()
        if name == "conversations":
            tbl.select.return_value.eq.return_value.eq.return_value.execute.return_value = conv_result
        elif name == "messages":
            tbl.select.return_value.in_.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = msg_result
        return tbl

    mock_sb.table.side_effect = _table
    mock_meta = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_meta.send_template.assert_not_called()
    mock_sent.assert_called_once_with("job-rescue-1")
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_cancels_when_joao_channel_not_found():
    """Canal do João inexistente → job cancelado com razão joao_channel_not_found."""
    job = _make_rescue_job()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=None), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_cancel.assert_called_once_with("job-rescue-1", "joao_channel_not_found")
    mock_sent.assert_not_called()


@pytest.mark.asyncio
async def test_handoff_rescue_does_not_mark_sent_if_template_send_fails():
    """Falha no send_template → job NÃO é marcado sent (será retentado no próximo tick)."""
    job = _make_rescue_job()
    joao_channel = {
        "id": "ch-joao-1",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "1049315514934778", "access_token": "joao_tok"},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []

    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(side_effect=RuntimeError("Meta API error"))

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=joao_channel), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_meta), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_sent.assert_not_called()
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_standard_jobs_not_affected_by_handoff_rescue_routing():
    """Jobs job_type='standard' continuam sendo processados pelo caminho existente."""
    standard_job = {
        "id": "job-std-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "job_type": "standard",
        "leads": {
            "id": "lead-1",
            "phone": "5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-1",
            "mode": "ai",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "111", "access_token": "tok"},
        },
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True},
        "metadata": {},
    }

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[standard_job]), \
         patch("app.follow_up.scheduler.get_supabase", return_value=mock_sb), \
         patch("app.follow_up.scheduler.get_provider", return_value=mock_provider), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value="Oi, tudo bem?"), \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

    mock_provider.send_text.assert_called_once()
    mock_sent.assert_called_once_with("job-std-1")
    mock_cancel.assert_not_called()
```

- [ ] **Step 2: Rodar para confirmar que falham**

```bash
cd backend
python -m pytest tests/test_handoff_rescue.py -k "rescue" -v 2>&1 | tail -20
```

Esperado: falhas por `AttributeError` — `get_channel_by_provider_config` e `MetaCloudClient` não estão importados em `scheduler.py`.

- [ ] **Step 3: Adicionar imports em `scheduler.py`**

No topo de `backend/app/follow_up/scheduler.py`, adicionar após os imports existentes:

```python
from app.channels.service import get_channel_by_provider_config
from app.whatsapp.meta import MetaCloudClient
```

- [ ] **Step 4: Adicionar `_process_handoff_rescue()` em `scheduler.py`**

Adicionar antes da função `_cancel_job` (final do arquivo):

```python
async def _process_handoff_rescue(job: dict, now: datetime) -> None:
    """Verifica se lead contatou João nos últimos 15 min. Se não, dispara template de resgate."""
    metadata = job.get("metadata") or {}
    lead_phone = metadata.get("lead_phone")
    joao_phone_number_id = metadata.get("joao_phone_number_id", "1049315514934778")
    template_name = metadata.get("template_name", "rabubens")

    if not lead_phone:
        _cancel_job(job["id"], "missing_lead_phone")
        logger.error(f"[HANDOFF_RESCUE] Job {job['id']} sem lead_phone no metadata")
        return

    joao_channel = get_channel_by_provider_config("phone_number_id", joao_phone_number_id, "meta_cloud")
    if not joao_channel:
        _cancel_job(job["id"], "joao_channel_not_found")
        logger.error(
            f"[HANDOFF_RESCUE] Canal do João (phone_number_id={joao_phone_number_id}) não encontrado"
        )
        return

    sb = get_supabase()
    cutoff = (now - timedelta(minutes=15)).isoformat()

    try:
        conv_result = (
            sb.table("conversations")
            .select("id")
            .eq("lead_id", job["lead_id"])
            .eq("channel_id", joao_channel["id"])
            .execute()
        )
        if conv_result.data:
            conv_ids = [c["id"] for c in conv_result.data]
            msg_result = (
                sb.table("messages")
                .select("id")
                .in_("conversation_id", conv_ids)
                .eq("role", "user")
                .gte("created_at", cutoff)
                .limit(1)
                .execute()
            )
            if msg_result.data:
                logger.info(
                    f"[HANDOFF_RESCUE] Lead {job['lead_id']} já contatou João — resgate desnecessário"
                )
                _mark_sent(job["id"])
                return
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Erro ao verificar contato do lead {job['lead_id']}: {exc}",
            exc_info=True,
        )
        # Segurança: se falhou a verificação, envia o template (falso negativo > falso positivo)

    try:
        provider = MetaCloudClient(joao_channel["provider_config"])
        await provider.send_template(lead_phone, template_name)
        logger.info(f"[HANDOFF_RESCUE] Template '{template_name}' enviado para {lead_phone}")
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Falha ao enviar template para {lead_phone}: {exc}",
            exc_info=True,
        )
        return  # Não marca sent → job será retentado no próximo tick do worker

    _mark_sent(job["id"])
```

- [ ] **Step 5: Adicionar roteamento no início de `process_due_followups()`**

No início do loop `for job in jobs:` em `process_due_followups()`, adicionar o branch antes de qualquer outra lógica:

```python
    for job in jobs:
        # Rota jobs de resgate de handoff para handler dedicado (antes de qualquer guard padrão)
        if job.get("job_type") == "handoff_rescue":
            await _process_handoff_rescue(job, now)
            continue

        conversation_id = job["conversation_id"]
        # ... resto do código existente inalterado
```

- [ ] **Step 6: Rodar todos os testes do arquivo e confirmar que passam**

```bash
cd backend
python -m pytest tests/test_handoff_rescue.py -v 2>&1 | tail -20
```

Esperado: todos os testes `PASSED`.

- [ ] **Step 7: Rodar suite completa para verificar regressões**

```bash
cd backend
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Esperado: todos os testes passando. Se houver falha em `test_followup_channel_mode.py`, verificar se os jobs naqueles testes têm `job_type` ausente — o `job.get("job_type")` retorna `None` quando ausente, então o branch `if job_type == 'handoff_rescue'` não é ativado e o comportamento é idêntico ao anterior.

- [ ] **Step 8: Commit final**

```bash
git add backend/app/follow_up/service.py \
        backend/app/follow_up/scheduler.py \
        backend/tests/test_handoff_rescue.py
git commit -m "feat(handoff): add rescue job scheduling and 15-min follow-up via template rabubens"
```

---

## Self-Review

**Spec coverage:**

| Requisito do spec | Task que implementa |
|---|---|
| Migration `job_type` + `metadata` | Task 1 |
| Enviar mensagem de redirecionamento pelo canal da IA | Task 3 |
| Agendar job de resgate 15 min | Task 3 + 4 |
| Verificar mensagens do lead para o canal do João | Task 5 |
| Disparar template `rabubens` se sem contato | Task 5 |
| Não disparar se lead já contatou João | Task 5 |
| Falha no `send_text` não bloqueia agendamento | Task 3 |
| Falha no `send_template` → job não marcado sent (retry) | Task 5 |
| Canal do João não encontrado → cancelar job | Task 5 |
| Jobs `standard` inalterados | Task 5 |

**Placeholder scan:** Nenhum TBD ou "implement later" presente.

**Type consistency:**
- `schedule_handoff_rescue(lead_id, lead_phone, conversation_id, channel_id)` definido em Task 4 e chamado em Task 3 — assinatura consistente.
- `_process_handoff_rescue(job, now)` definido em Task 5 e chamado em Task 5 — consistente.
- `_cancel_job`, `_mark_sent` — funções existentes, usadas com mesma assinatura em todos os tasks.
