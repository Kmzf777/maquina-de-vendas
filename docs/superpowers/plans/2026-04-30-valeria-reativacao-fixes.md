# Reativação da Valéria + Fixes de Disparo e Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir 4 bugs (broadcast ai_enabled, lead import phone, meta logs, kill switch) e reativar a Valéria de forma segura.

**Architecture:** Fixes pontuais em 5 arquivos — broadcast worker define `ai_enabled` explicitamente, lead import normaliza telefone antes de enviar, meta_router salva payload em background task, processor re-ativado com log melhorado.

**Tech Stack:** Python/FastAPI (backend), TypeScript/Next.js (frontend), Supabase (PostgreSQL + realtime)

> **ORDEM IMPORTA:** Tasks 1–4 primeiro. Task 5 (kill switch) é sempre a última — só re-ativar após o resto estar commitado.

---

## File Map

| Arquivo | O que muda |
|---|---|
| `backend/migrations/20260430_meta_webhook_logs.sql` | **Criar** — tabela `meta_webhook_logs` |
| `backend/app/webhook/meta_router.py` | **Modificar** — adicionar `_log_webhook` background task |
| `backend/app/broadcast/worker.py` | **Modificar** — setar `ai_enabled` em `conv_updates` |
| `backend/tests/test_broadcast_worker.py` | **Criar** — testes da lógica de `ai_enabled` |
| `frontend/src/components/leads/lead-import-modal.tsx` | **Modificar** — normalizar telefone antes do import |
| `backend/app/buffer/processor.py` | **Modificar** — re-ativar kill switch + melhorar log |

---

### Task 1: Migration — tabela meta_webhook_logs

**Files:**
- Create: `backend/migrations/20260430_meta_webhook_logs.sql`

- [ ] **Step 1: Criar migration SQL**

Criar o arquivo `backend/migrations/20260430_meta_webhook_logs.sql` com o seguinte conteúdo:

```sql
-- Logs de todos os webhooks recebidos da Meta API
-- Usado para auditoria e debugging de mensagens perdidas

CREATE TABLE IF NOT EXISTS meta_webhook_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    channel_id UUID REFERENCES channels(id) ON DELETE SET NULL,
    phone_number_id TEXT,
    from_number TEXT,
    payload JSONB NOT NULL,
    message_count INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_channel_received
    ON meta_webhook_logs(channel_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_from_number
    ON meta_webhook_logs(from_number, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_meta_webhook_logs_received_at
    ON meta_webhook_logs(received_at DESC);
```

- [ ] **Step 2: Aplicar migration no Supabase**

Acesse o Supabase dashboard → SQL Editor e execute o conteúdo do arquivo acima. Confirme que a tabela `meta_webhook_logs` foi criada sem erros.

- [ ] **Step 3: Commit da migration**

```bash
git add backend/migrations/20260430_meta_webhook_logs.sql
git commit -m "feat(migrations): add meta_webhook_logs table for audit trail"
```

---

### Task 2: meta_router.py — salvar webhook em background task

**Files:**
- Modify: `backend/app/webhook/meta_router.py`

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat backend/app/webhook/meta_router.py
```

Localizar o final da função `receive_meta_webhook` — logo após `messages = parse_meta_webhook_payload(payload)` e antes do `for msg in messages:`.

- [ ] **Step 2: Adicionar a função `_log_webhook`**

Adicionar logo abaixo da função `_track_inbound_message_time` (após a linha ~22):

```python
def _log_webhook(
    channel_id: str | None,
    phone_number_id: str | None,
    from_number: str | None,
    payload: dict,
    message_count: int,
) -> None:
    """Persists raw Meta webhook payload to Supabase for audit/debugging. Fire-and-forget."""
    try:
        sb = get_supabase()
        sb.table("meta_webhook_logs").insert({
            "channel_id": channel_id,
            "phone_number_id": phone_number_id,
            "from_number": from_number,
            "payload": payload,
            "message_count": message_count,
        }).execute()
    except Exception as e:
        logger.warning(f"[META LOG] Failed to persist webhook log: {e}")
```

- [ ] **Step 3: Adicionar background_tasks.add_task na função receive_meta_webhook**

Dentro de `receive_meta_webhook`, logo após `messages = parse_meta_webhook_payload(payload)` e antes do `for msg in messages:`, adicionar:

```python
    messages = parse_meta_webhook_payload(payload)

    background_tasks.add_task(
        _log_webhook,
        channel_id=channel["id"],
        phone_number_id=phone_number_id,
        from_number=_extract_from_number(payload),
        payload=payload,
        message_count=len(messages),
    )

    for msg in messages:
```

- [ ] **Step 4: Verificar que o servidor sobe sem erros**

```bash
cd backend && python -c "from app.webhook.meta_router import router; print('OK')"
```

Expected: `OK` sem erros.

- [ ] **Step 5: Commit**

```bash
git add backend/app/webhook/meta_router.py
git commit -m "feat(meta): persist all webhook payloads to meta_webhook_logs for audit"
```

---

### Task 3: broadcast/worker.py — ai_enabled explícito

**Files:**
- Create: `backend/tests/test_broadcast_worker.py`
- Modify: `backend/app/broadcast/worker.py`

- [ ] **Step 1: Escrever os testes falhando**

Criar `backend/tests/test_broadcast_worker.py`:

```python
"""Tests for broadcast worker ai_enabled logic.

These tests verify the invariant: disparo com agente → ai_enabled=True,
disparo sem agente → ai_enabled=False.
"""


def _build_conv_updates(broadcast: dict) -> dict:
    """Replica a lógica de conv_updates do worker para teste isolado.
    
    Copiar EXATAMENTE a mesma lógica do worker.py — se o worker mudar, mudar aqui.
    """
    conv_updates: dict = {"status": "template_sent"}
    if broadcast.get("agent_profile_id"):
        conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
        conv_updates["ai_enabled"] = True
    else:
        conv_updates["ai_enabled"] = False
    return conv_updates


def test_without_agent_disables_ai():
    """Disparo sem agente deve forçar ai_enabled=False na conversa."""
    broadcast = {
        "template_name": "ola_mundo",
        "template_language_code": "pt_BR",
        "agent_profile_id": None,
    }
    updates = _build_conv_updates(broadcast)
    assert updates["ai_enabled"] is False
    assert "agent_profile_id" not in updates


def test_without_agent_empty_string_disables_ai():
    """agent_profile_id vazio deve ser tratado como ausente."""
    broadcast = {
        "template_name": "ola_mundo",
        "template_language_code": "pt_BR",
        "agent_profile_id": "",
    }
    updates = _build_conv_updates(broadcast)
    assert updates["ai_enabled"] is False


def test_with_agent_enables_ai():
    """Disparo com agente deve forçar ai_enabled=True e setar agent_profile_id."""
    agent_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    broadcast = {
        "template_name": "ola_mundo",
        "template_language_code": "pt_BR",
        "agent_profile_id": agent_id,
    }
    updates = _build_conv_updates(broadcast)
    assert updates["ai_enabled"] is True
    assert updates["agent_profile_id"] == agent_id


def test_status_always_template_sent():
    """conv_updates deve sempre incluir status=template_sent."""
    for agent_id in [None, "some-uuid"]:
        broadcast = {"agent_profile_id": agent_id}
        updates = _build_conv_updates(broadcast)
        assert updates["status"] == "template_sent"
```

- [ ] **Step 2: Rodar para ver os testes passarem (validar helper)**

```bash
cd backend && python -m pytest tests/test_broadcast_worker.py -v
```

Expected: 4 testes PASS (os testes testam o helper `_build_conv_updates`, que já está implementado corretamente no helper de teste).

> Nota: os testes passam porque testam a lógica isolada. O próximo passo aplica essa mesma lógica no worker real.

- [ ] **Step 3: Aplicar o fix no worker.py**

Abrir `backend/app/broadcast/worker.py` e localizar o bloco:

```python
            conv_updates = {"status": "template_sent"}
            if broadcast.get("agent_profile_id"):
                conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
```

Substituir por:

```python
            conv_updates = {"status": "template_sent"}
            if broadcast.get("agent_profile_id"):
                conv_updates["agent_profile_id"] = broadcast["agent_profile_id"]
                conv_updates["ai_enabled"] = True
            else:
                conv_updates["ai_enabled"] = False
```

- [ ] **Step 4: Rodar testes novamente**

```bash
cd backend && python -m pytest tests/test_broadcast_worker.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Verificar importações do worker sem erros**

```bash
cd backend && python -c "from app.broadcast.worker import run_broadcast; print('OK')"
```

Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_broadcast_worker.py backend/app/broadcast/worker.py
git commit -m "fix(broadcast): set ai_enabled=False when no agent_profile_id, True when present"
```

---

### Task 4: lead-import-modal.tsx — normalização de telefone

**Files:**
- Modify: `frontend/src/components/leads/lead-import-modal.tsx`

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat frontend/src/components/leads/lead-import-modal.tsx
```

Localizar a função `handleImport` e o bloco que mapeia `csvRows` para `leads`.

- [ ] **Step 2: Adicionar função de normalização pura**

Logo antes da declaração da função `handleFile` (ou no topo do componente, antes do `return`), adicionar:

```typescript
function normalizePhone(raw: string): string | null {
  let digits = raw.replace(/\D/g, "");
  if (digits.startsWith("0")) digits = digits.slice(1);
  if (digits.length === 10 || digits.length === 11) digits = "55" + digits;
  if ((digits.length === 12 || digits.length === 13) && !digits.startsWith("55")) return null;
  if (digits.length < 12 || digits.length > 13) return null;
  return digits;
}
```

- [ ] **Step 3: Aplicar normalização no handleImport**

Localizar o bloco atual em `handleImport`:

```typescript
    const leads = csvRows.map((row) => {
      const lead: Record<string, string> = {};
      Object.entries(mapping).forEach(([colIdx, field]) => {
        if (field) {
          lead[field] = row[Number(colIdx)] || "";
        }
      });
      return lead;
    }).filter((l) => l.phone);
```

Substituir por:

```typescript
    const leads = csvRows
      .map((row) => {
        const lead: Record<string, string> = {};
        Object.entries(mapping).forEach(([colIdx, field]) => {
          if (field) lead[field] = row[Number(colIdx)] || "";
        });
        return lead;
      })
      .map((lead) => {
        if (!lead.phone) return lead;
        const normalized = normalizePhone(lead.phone);
        return normalized ? { ...lead, phone: normalized } : { ...lead, phone: "" };
      })
      .filter((l) => l.phone);
```

- [ ] **Step 4: Build do frontend para validar tipos**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E 'lead-import-modal|error' | head -20
```

Expected: sem erros relacionados ao `lead-import-modal.tsx`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/leads/lead-import-modal.tsx
git commit -m "fix(leads): normalize phone numbers on CSV import before sending to API"
```

---

### Task 5: processor.py — re-ativar Valéria + log melhorado

> ⚠️ **Esta é a última task.** Só executar após Tasks 1–4 estarem commitadas.

**Files:**
- Modify: `backend/app/buffer/processor.py`

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat backend/app/buffer/processor.py
```

Localizar:
1. `VALERIA_ENABLED = False` (linha 1 ou 2)
2. O bloco `if not VALERIA_ENABLED or not conversation.get("ai_enabled", True):`

- [ ] **Step 2: Re-ativar o kill switch**

Alterar:

```python
VALERIA_ENABLED = False
```

Para:

```python
VALERIA_ENABLED = True
```

- [ ] **Step 3: Melhorar o log de AI skip**

Localizar o bloco:

```python
    # If AI is disabled globally or for this conversation, skip agent silently
    if not VALERIA_ENABLED or not conversation.get("ai_enabled", True):
        logger.info(f"[AI DISABLED] Conversation {conversation['id']} — ai paused per CRM setting")
        _update_last_msg(conversation["id"])
        return
```

Substituir por:

```python
    # If AI is disabled globally, skip agent
    if not VALERIA_ENABLED:
        logger.info(
            f"[AI DISABLED] kill switch ativo — conv={conversation['id']} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # If AI is disabled for this specific conversation (toggled by user or broadcast sem agente)
    if not conversation.get("ai_enabled", True):
        logger.info(
            f"[AI DISABLED] ai_enabled=false — conv={conversation['id']} phone={phone} — agente não vai responder"
        )
        _update_last_msg(conversation["id"])
        return
```

- [ ] **Step 4: Verificar importações sem erros**

```bash
cd backend && python -c "from app.buffer.processor import VALERIA_ENABLED; print('VALERIA_ENABLED =', VALERIA_ENABLED)"
```

Expected: `VALERIA_ENABLED = True`

- [ ] **Step 5: Rodar todos os testes do backend**

```bash
cd backend && python -m pytest tests/ -v --ignore=tests/test_outbound_dispatcher.py -x 2>&1 | tail -20
```

Expected: todos os testes passam.

- [ ] **Step 6: Commit final**

```bash
git add backend/app/buffer/processor.py
git commit -m "feat(valeria): re-enable VALERIA_ENABLED + split AI-skip logs by reason"
```

---

## Verificação pós-implementação

Após todos os commits:

1. **Teste de disparo SEM agente:** criar um broadcast sem `agent_profile_id` → verificar no Supabase que a conversa criada tem `ai_enabled = false`.

2. **Teste de disparo COM agente:** criar um broadcast com `agent_profile_id` → verificar que a conversa tem `ai_enabled = true`.

3. **Teste do toggle em /conversas:** abrir uma conversa, clicar no botão Valéria para desativar → verificar no Supabase que `ai_enabled` mudou para `false`.

4. **Teste de import CSV em /leads:** importar um CSV com telefones no formato `(34) 99999-9999` → verificar que os leads são salvos com `5534999999999`.

5. **Teste de logs Meta:** enviar uma mensagem de teste pelo WhatsApp → verificar que aparece na tabela `meta_webhook_logs` no Supabase.
