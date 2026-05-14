# Channel Mode: Human vs AI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar campo `mode` ('ai' | 'human') na tabela `channels` e bloquear Valeria + follow-up automático em canais humanos em 3 pontos: processor, follow-up scheduler e broadcast worker.

**Architecture:** Um campo de canal (`mode`) funciona como gate de canal antes de qualquer lógica de IA. Canal `mode='human'` retorna cedo no processor (sem IA, sem follow-up), cancela jobs de follow-up no scheduler e impede que o broadcast worker sete `lead.ai_enabled=True`. Default `'ai'` mantém comportamento atual em todos os canais existentes.

**Tech Stack:** Python, FastAPI, Supabase (PostgreSQL), pytest + unittest.mock

---

## Mapa de Arquivos

| Arquivo | Ação | O que muda |
|---|---|---|
| `backend/app/buffer/processor.py` | Modificar | Gate de canal logo após resolver o canal |
| `backend/app/follow_up/service.py` | Modificar | Adicionar `mode` no select do join de canais |
| `backend/app/follow_up/scheduler.py` | Modificar | Guard de canal no loop de jobs |
| `backend/app/broadcast/worker.py` | Modificar | `_broadcast_ai_enabled` recebe `channel` opcional |
| `backend/tests/test_processor_channel_mode.py` | Criar | Testes do gate de canal no processor |
| `backend/tests/test_followup_channel_mode.py` | Criar | Testes do guard de canal no scheduler |
| `backend/tests/test_broadcast_worker.py` | Modificar | Testes existentes + novos casos de canal humano |

---

## Task 1: Criar branch de trabalho

**Files:**
- N/A (operação git)

- [ ] **Step 1: Criar e entrar na nova branch**

```bash
git checkout master
git checkout -b fix/channel-mode-human-ai
```

- [ ] **Step 2: Verificar ponto de partida**

```bash
git log --oneline -3
git status
```

Expected: branch limpa no topo de master.

---

## Task 2: Gate de canal no `processor.py`

**Files:**
- Modify: `backend/app/buffer/processor.py` — adicionar gate após resolver o canal
- Create: `backend/tests/test_processor_channel_mode.py`

### Spec do comportamento esperado

Canal `mode='human'`:
- Mensagem do usuário é salva normalmente
- `unread_count` é incrementado normalmente
- `run_agent` **nunca** é chamado
- Follow-up **nunca** é agendado
- `_update_last_msg` é chamado antes de retornar

Canal `mode='ai'` (ou sem `mode`):
- Comportamento atual, sem mudança

- [ ] **Step 1: Escrever os testes**

Criar `backend/tests/test_processor_channel_mode.py`:

```python
"""Tests for channel mode='human' gate in processor."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_lead(ai_enabled=True):
    return {
        "id": "lead-1",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "ai_enabled": ai_enabled,
        "name": "Teste",
    }


def _make_channel(mode="ai"):
    return {
        "id": "ch-1",
        "is_active": True,
        "mode": mode,
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }


def _make_conversation():
    return {
        "id": "conv-1",
        "lead_id": "lead-1",
        "channel_id": "ch-1",
        "stage": "atacado",
        "status": "active",
        "followup_enabled": True,
    }


@pytest.mark.asyncio
async def test_human_channel_skips_agent():
    """Canal mode='human': run_agent nunca é chamado."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel(mode="human")), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
            table=MagicMock(return_value=MagicMock(
                update=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))),
                )),
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        single=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))
                        ))
                    ))
                )),
            ))
        )
        mock_provider_fn.return_value = AsyncMock()

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi", "ch-1")

        mock_agent.assert_not_called()
        mock_followup.assert_not_called()


@pytest.mark.asyncio
async def test_human_channel_still_saves_user_message():
    """Canal mode='human': mensagem do usuário ainda é salva."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel(mode="human")), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent"), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
            table=MagicMock(return_value=MagicMock(
                update=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))),
                )),
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        single=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))
                        ))
                    ))
                )),
            ))
        )
        mock_provider_fn.return_value = AsyncMock()

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi tudo bem", "ch-1")

        assert mock_save.call_count == 1
        assert mock_save.call_args.args[2] == "user"


@pytest.mark.asyncio
async def test_ai_channel_runs_agent():
    """Canal mode='ai' (padrão): run_agent é chamado normalmente."""
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=_make_channel(mode="ai")), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Olá!") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
            table=MagicMock(return_value=MagicMock(
                update=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))),
                )),
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        single=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))
                        ))
                    ))
                )),
            ))
        )
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi", "ch-1")

        mock_agent.assert_called_once()


@pytest.mark.asyncio
async def test_channel_without_mode_runs_agent():
    """Canal sem campo mode (legado): funciona como 'ai'."""
    channel_without_mode = {
        "id": "ch-legado",
        "is_active": True,
        # sem 'mode'
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    with patch("app.buffer.processor.get_or_create_lead", return_value=_make_lead()), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_without_mode), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=_make_conversation()), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message"), \
         patch("app.buffer.processor.run_agent", return_value="Olá!") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup"), \
         patch("app.buffer.processor.get_supabase") as mock_sb:

        mock_sb.return_value = MagicMock(
            table=MagicMock(return_value=MagicMock(
                update=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))),
                )),
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        single=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))
                        ))
                    ))
                )),
            ))
        )
        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock(return_value={})
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages("+5511999999999", "oi", "ch-legado")

        mock_agent.assert_called_once()
```

- [ ] **Step 2: Rodar os testes para ver falhar**

```bash
cd backend && python -m pytest tests/test_processor_channel_mode.py -v
```

Expected: `FAILED` em `test_human_channel_skips_agent` e `test_human_channel_still_saves_user_message` (gate ainda não existe).

- [ ] **Step 3: Implementar o gate em `processor.py`**

Abrir `backend/app/buffer/processor.py`. Localizar este bloco (linha ~219):

```python
    # If AI is disabled globally, skip agent
    if not VALERIA_ENABLED:
```

Inserir o gate de canal **antes** desse bloco:

```python
    # Channel-level gate: human channels never run AI or schedule follow-ups
    if channel.get("mode", "ai") == "human":
        logger.info(
            f"[HUMAN CHANNEL] mode=human — IA e follow-up desativados "
            f"channel_id={channel_id} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # If AI is disabled globally, skip agent
    if not VALERIA_ENABLED:
```

- [ ] **Step 4: Rodar os testes para ver passar**

```bash
cd backend && python -m pytest tests/test_processor_channel_mode.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Garantir que testes existentes continuam passando**

```bash
cd backend && python -m pytest tests/test_processor_human_control.py tests/test_24h_window_processor.py -v
```

Expected: todos passam (o gate novo não afeta canais `mode='ai'`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/buffer/processor.py backend/tests/test_processor_channel_mode.py
git commit -m "feat(processor): gate de canal mode=human desativa IA e follow-up"
```

---

## Task 3: Guard de canal no `follow_up/scheduler.py` e `service.py`

**Files:**
- Modify: `backend/app/follow_up/service.py:175-177` — adicionar `mode` no select
- Modify: `backend/app/follow_up/scheduler.py:70-77` — inserir guard de canal
- Create: `backend/tests/test_followup_channel_mode.py`

### Spec do comportamento esperado

Ao processar um job de follow-up para um canal `mode='human'`:
- Job é cancelado com razão `"human_channel"`
- Mensagem **não** é enviada
- `get_due_followups` retorna o campo `mode` no canal

- [ ] **Step 1: Escrever os testes**

Criar `backend/tests/test_followup_channel_mode.py`:

```python
"""Tests for channel mode='human' guard in follow_up scheduler."""
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
import pytest


def _make_job(channel_mode="ai"):
    return {
        "id": "job-1",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "leads": {
            "id": "lead-1",
            "phone": "+5511999999999",
            "last_customer_message_at": datetime.now(timezone.utc).isoformat(),
        },
        "channels": {
            "id": "ch-1",
            "name": "Canal Comercial",
            "provider": "meta_cloud",
            "provider_config": {"phone_number_id": "123", "access_token": "tok"},
            "mode": channel_mode,
        },
        "conversations": {
            "id": "conv-1",
            "stage": "atacado",
            "followup_enabled": True,
        },
    }


@pytest.mark.asyncio
async def test_human_channel_cancels_followup_job():
    """Canal mode='human': job é cancelado com razão human_channel."""
    job = _make_job(channel_mode="human")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"):

        mock_provider_fn.return_value = AsyncMock()

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_called_once_with("job-1", "human_channel")
        mock_sent.assert_not_called()


@pytest.mark.asyncio
async def test_ai_channel_processes_followup_job():
    """Canal mode='ai': job segue normalmente."""
    job = _make_job(channel_mode="ai")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value="Oi, tudo bem?"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_not_called()
        mock_sent.assert_called_once_with("job-1")


@pytest.mark.asyncio
async def test_channel_without_mode_processes_followup_job():
    """Canal sem campo mode (legado): funciona como 'ai'."""
    job = _make_job()
    del job["channels"]["mode"]  # simula canal legado sem o campo

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler.get_provider") as mock_provider_fn, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.save_message"), \
         patch("app.follow_up.scheduler._generate_followup_message", return_value="Oi!"):

        mock_provider = AsyncMock()
        mock_provider.send_text = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.follow_up.scheduler import process_due_followups
        await process_due_followups(now=datetime.now(timezone.utc))

        mock_cancel.assert_not_called()
        mock_sent.assert_called_once_with("job-1")
```

- [ ] **Step 2: Rodar os testes para ver falhar**

```bash
cd backend && python -m pytest tests/test_followup_channel_mode.py -v
```

Expected: `FAILED test_human_channel_cancels_followup_job` (guard não existe ainda).

- [ ] **Step 3: Adicionar `mode` no select de `get_due_followups`**

Abrir `backend/app/follow_up/service.py`. Localizar linha ~176:

```python
                "channels!inner(id, name, provider, provider_config), "
```

Substituir por:

```python
                "channels!inner(id, name, provider, provider_config, mode), "
```

- [ ] **Step 4: Inserir guard de canal no `scheduler.py`**

Abrir `backend/app/follow_up/scheduler.py`. Localizar o bloco existente (linha ~71):

```python
        # Guard: toggle desativado
        if not conversation.get("followup_enabled", True):
            _cancel_job(job["id"], "followup_disabled")
            logger.info(
                f"[FOLLOWUP] followup_enabled=false — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue
```

Inserir **depois** desse bloco:

```python
        # Guard: canal humano nunca executa follow-up
        if channel.get("mode", "ai") == "human":
            _cancel_job(job["id"], "human_channel")
            logger.info(
                f"[FOLLOWUP] mode=human — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue
```

- [ ] **Step 5: Rodar os testes para ver passar**

```bash
cd backend && python -m pytest tests/test_followup_channel_mode.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/follow_up/service.py backend/app/follow_up/scheduler.py backend/tests/test_followup_channel_mode.py
git commit -m "feat(follow-up): cancelar jobs em canal mode=human"
```

---

## Task 4: Broadcast worker — canal humano nunca seta `ai_enabled=True`

**Files:**
- Modify: `backend/app/broadcast/worker.py:202-207` — `_broadcast_ai_enabled` recebe `channel` opcional
- Modify: `backend/app/broadcast/worker.py:398` — passar `channel` na chamada
- Modify: `backend/tests/test_broadcast_worker.py` — atualizar testes existentes + novos casos

### Spec do comportamento esperado

`_broadcast_ai_enabled(broadcast, channel=None)`:
- `channel=None` ou `channel.mode='ai'` → comportamento atual (True se broadcast tem agent)
- `channel.mode='human'` → sempre False, independente do broadcast ter agent ou não

- [ ] **Step 1: Adicionar testes novos em `test_broadcast_worker.py`**

Abrir `backend/tests/test_broadcast_worker.py`. Adicionar ao final do arquivo:

```python
def test_broadcast_ai_enabled_human_channel_without_agent():
    """Canal humano sem agente → False (comportamento esperado mesmo sem agent)."""
    channel = {"mode": "human"}
    assert _broadcast_ai_enabled({"agent_profile_id": None}, channel=channel) is False


def test_broadcast_ai_enabled_human_channel_with_agent():
    """Canal humano COM agente configurado → ainda False (canal humano tem precedência)."""
    channel = {"mode": "human"}
    assert _broadcast_ai_enabled({"agent_profile_id": "some-uuid"}, channel=channel) is False


def test_broadcast_ai_enabled_ai_channel_with_agent():
    """Canal IA com agente → True."""
    channel = {"mode": "ai"}
    assert _broadcast_ai_enabled({"agent_profile_id": "some-uuid"}, channel=channel) is True


def test_broadcast_ai_enabled_ai_channel_without_agent():
    """Canal IA sem agente → False."""
    channel = {"mode": "ai"}
    assert _broadcast_ai_enabled({"agent_profile_id": None}, channel=channel) is False


def test_broadcast_ai_enabled_no_channel_arg_backwards_compat():
    """Sem channel (arg omitido) → comportamento legado inalterado."""
    assert _broadcast_ai_enabled({"agent_profile_id": "uuid"}) is True
    assert _broadcast_ai_enabled({"agent_profile_id": None}) is False
```

- [ ] **Step 2: Rodar os testes para ver falhar**

```bash
cd backend && python -m pytest tests/test_broadcast_worker.py -v
```

Expected: os 5 novos testes falham com `TypeError: _broadcast_ai_enabled() got an unexpected keyword argument 'channel'`.

- [ ] **Step 3: Atualizar `_broadcast_ai_enabled` no `worker.py`**

Abrir `backend/app/broadcast/worker.py`. Substituir a função `_broadcast_ai_enabled` (linhas 202-207):

```python
def _broadcast_ai_enabled(broadcast: dict) -> bool:
    """Returns the ai_enabled value to set on the lead for this broadcast.

    Invariant: broadcast with agent → ai_enabled=True; without → ai_enabled=False.
    """
    return bool(broadcast.get("agent_profile_id"))
```

Por:

```python
def _broadcast_ai_enabled(broadcast: dict, channel: dict | None = None) -> bool:
    """Returns the ai_enabled value to set on the lead for this broadcast.

    Invariant: human channel → always False; ai channel with agent → True.
    """
    if channel and channel.get("mode", "ai") == "human":
        return False
    return bool(broadcast.get("agent_profile_id"))
```

- [ ] **Step 4: Passar `channel` na chamada existente**

No mesmo arquivo, localizar (linha ~398):

```python
                ai_enabled = _broadcast_ai_enabled(broadcast)
```

Substituir por:

```python
                ai_enabled = _broadcast_ai_enabled(broadcast, channel=channel)
```

O `channel` já está disponível nesse escopo (foi resolvido em `process_single_broadcast` na linha ~302).

- [ ] **Step 5: Rodar os testes para ver passar**

```bash
cd backend && python -m pytest tests/test_broadcast_worker.py -v
```

Expected: todos os testes passam (incluindo os pré-existentes, pois `channel=None` é o default).

- [ ] **Step 6: Rodar toda a suite para garantir nenhuma regressão**

```bash
cd backend && python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: sem falhas.

- [ ] **Step 7: Commit**

```bash
git add backend/app/broadcast/worker.py backend/tests/test_broadcast_worker.py
git commit -m "feat(broadcast): canal mode=human nunca seta ai_enabled=True no lead"
```

---

## Task 5: Migration SQL e atualização do canal atual

Esta task é executada pelo usuário via **Supabase MCP ou Dashboard** — não é código no repositório.

**Instruções para o usuário:**

- [ ] **Step 1: Aplicar migration via Supabase MCP**

```sql
ALTER TABLE channels
  ADD COLUMN mode TEXT NOT NULL DEFAULT 'ai'
  CHECK (mode IN ('ai', 'human'));
```

- [ ] **Step 2: Identificar o ID do canal comercial atual**

```sql
SELECT id, name, phone, provider_config->>'phone_number_id' AS phone_number_id
FROM channels
WHERE is_active = true;
```

Anotar o `id` do canal que corresponde ao número comercial atual.

- [ ] **Step 3: Atualizar o canal para mode='human'**

```sql
UPDATE channels
SET mode = 'human'
WHERE id = '<id-do-canal-atual>';
```

- [ ] **Step 4: Verificar**

```sql
SELECT id, name, mode FROM channels;
```

Expected: canal comercial com `mode='human'`, demais com `mode='ai'`.

---

## Task 6: Cancelar follow-up jobs pendentes do canal humano

Após a migration, jobs pendentes criados antes da mudança de modo não serão automaticamente cancelados até o próximo tick do worker. Para limpar imediatamente:

**Instruções para o usuário (via Supabase MCP ou Dashboard):**

- [ ] **Step 1: Cancelar jobs pendentes do canal humano**

```sql
UPDATE follow_up_jobs
SET status = 'cancelled', cancel_reason = 'human_channel'
WHERE status = 'pending'
  AND channel_id = '<id-do-canal-atual>';
```

---

## Checklist Final

- [ ] `python -m pytest tests/ -v` — todos os testes passam
- [ ] Processor: canal `mode='human'` não chama `run_agent`
- [ ] Processor: canal `mode='human'` não agenda follow-up
- [ ] Scheduler: jobs de canal `mode='human'` são cancelados
- [ ] Worker: broadcast em canal `mode='human'` seta `lead.ai_enabled=False`
- [ ] Migration aplicada via Supabase MCP
- [ ] Canal comercial atualizado para `mode='human'`
- [ ] Jobs pendentes do canal humano cancelados
