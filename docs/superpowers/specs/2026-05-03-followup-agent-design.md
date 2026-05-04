# Follow-up Automático (WhatsApp) — Design Spec

**Data:** 2026-05-03  
**Status:** Aprovado  
**Escopo:** Conversas onde o cliente já respondeu ao menos uma vez (janela de 24h ativa). Não cobre prospecção fria.

---

## 1. Objetivo

Enviar mensagens de follow-up personalizadas e geradas por LLM quando o cliente não responde ao vendedor (Valéria IA ou João) dentro de 1h e 23h. O sistema cancela automaticamente os follow-ups pendentes quando o cliente responde ou o usuário desativa o toggle.

---

## 2. Regras de Negócio

- **Gatilho:** qualquer mensagem outbound do vendedor (role=`assistant`) registrada para uma conversa com `followup_enabled=true`
- **Disparos:** 1h após o envio do vendedor (follow-up leve) e 23h após (urgente/última tentativa)
- **Cancelamento automático:** cliente responde → cancela todos os jobs pendentes da conversa
- **Cancelamento manual:** usuário desliga toggle → cancela todos os jobs pendentes da conversa
- **Guard de janela:** ao disparar, verificar se `last_customer_message_at + 24h > now`; se não, cancelar com `reason='window_expired'` sem enviar
- **Guard de toggle:** ao disparar, re-verificar `followup_enabled` na conversa; se false, cancelar
- **Idempotência:** `schedule_followup()` cancela jobs pendentes anteriores da mesma conversa antes de criar novos

---

## 3. Banco de Dados

### 3.1 Nova tabela: `follow_up_jobs`

```sql
CREATE TABLE follow_up_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  lead_id         UUID NOT NULL REFERENCES leads(id),
  channel_id      UUID NOT NULL REFERENCES channels(id),
  sequence        INTEGER NOT NULL,           -- 1 = 1h, 2 = 23h
  fire_at         TIMESTAMPTZ NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'cancelled')),
  cancel_reason   TEXT,                       -- 'client_replied' | 'manual' | 'window_expired' | 'empty_response' | 'followup_disabled'
  sent_at         TIMESTAMPTZ,
  env_tag         TEXT NOT NULL DEFAULT 'production',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_followup_jobs_due
  ON follow_up_jobs (status, fire_at)
  WHERE status = 'pending';

CREATE INDEX idx_followup_jobs_conversation
  ON follow_up_jobs (conversation_id, status);
```

### 3.2 Alteração em `conversations`

```sql
ALTER TABLE conversations
  ADD COLUMN followup_enabled BOOLEAN NOT NULL DEFAULT true;
```

---

## 4. Módulo Backend: `backend/app/follow_up/`

### 4.1 `service.py` — CRUD puro

| Função | Descrição |
|---|---|
| `schedule_followup(conversation_id, lead_id, channel_id)` | Cancela jobs pendentes anteriores; cria 2 jobs com `fire_at = now+1h` e `now+23h`; respeita `env_tag` |
| `cancel_followups(conversation_id, reason)` | Atualiza `status='cancelled'` em todos os jobs `pending` da conversa |
| `get_due_followups(now) → list` | Busca jobs `status=pending AND fire_at <= now` com join em `leads` e `channels` |

### 4.2 `scheduler.py` — lógica de disparo

Função `process_due_followups(now)`:

1. Chama `get_due_followups(now)`
2. Para cada job:
   a. Busca conversa — re-verifica `followup_enabled`; se false → cancela com `reason='followup_disabled'`
   b. Verifica janela de 24h: `lead.last_customer_message_at + 24h > now`; se não → cancela com `reason='window_expired'`
   c. Busca últimas 20 mensagens da conversa (`messages` table)
   d. Chama LLM com prompt específico por sequence:
      - seq=1: follow-up leve, curiosidade natural, sem pressão
      - seq=2: urgente, última tentativa, gera senso de oportunidade
   e. Se LLM retornar vazio → cancela com `reason='empty_response'`, loga warning
   f. Envia via `provider.send_text(lead.phone, message)`
   g. Salva mensagem com `sent_by='followup'` em `messages`
   h. Marca job `status='sent'`, preenche `sent_at`
3. Em caso de exceção no envio: loga erro, **não** atualiza status (job retentado no próximo tick)

### 4.3 `router.py` — toggle endpoint

```
PATCH /api/conversations/{conversation_id}/followup
Body: { "enabled": bool }
```

- Atualiza `followup_enabled` na conversa
- Se `enabled=false` → chama `cancel_followups(conversation_id, reason='manual')`

---

## 5. Pontos de Gatilho (Agendamento)

### 5.1 Valéria IA → `buffer/processor.py`

Após `run_agent()` retornar com sucesso (resposta não vazia), verificar:
```python
if conversation.get("followup_enabled", True):
    schedule_followup(conversation_id, lead_id, channel_id)
```

### 5.2 João (humano) → endpoint de envio humano

No endpoint que João usa para enviar mensagens manualmente (`POST /api/conversations/{id}/send`), após persistir a mensagem:
```python
if conversation.get("followup_enabled", True):
    schedule_followup(conversation_id, lead_id, channel_id)
```

### 5.3 Cancelamento por resposta do cliente → `meta_router.py`

Em `_track_inbound_message_time(phone)`, após atualizar `last_customer_message_at`:
```python
# Cancela follow-ups pendentes do lead
cancel_followups_by_phone(phone, reason='client_replied')
```

`cancel_followups_by_phone(phone, reason)` em `service.py`:
- Busca lead pelo phone → busca conversations ativas → cancela jobs pending

---

## 6. Integração no Worker

Em `backend/app/broadcast/worker.py`, função `run_worker()`:

```python
from app.follow_up.scheduler import process_due_followups

async def run_worker():
    while True:
        try:
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
            await process_due_followups()   # ← nova linha
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
        await asyncio.sleep(5)
```

---

## 7. Frontend

### 7.1 Componente `ChatHeader`

Novo botão toggle ao lado do existente "Valéria IA":

- **Ativo:** fundo `#1e6ee8` (azul), texto branco, dot `animate-pulse bg-white`
- **Inativo:** fundo `#dedbd6`, texto `#111111`, dot `bg-[#7b7b78]`
- **Texto:** `Follow-up · Ativo` / `Follow-up · Pausado`
- **Estilo:** `rounded-[4px] px-3 py-1 text-xs font-medium` (idêntico ao toggle de IA)
- **Props adicionais:** `followupEnabled: boolean`, `togglingFollowup?: boolean`, `onToggleFollowup: () => void | Promise<void>`

### 7.2 API Route Next.js

`frontend/src/app/api/conversations/[id]/followup/route.ts`

- Método `PATCH`: repassa `{ enabled: bool }` para `BACKEND_URL/api/conversations/{id}/followup`

### 7.3 Estado no pai (`conversas/page.tsx`)

- Optimistic update idêntico ao toggle da Valéria IA
- Reverte em caso de erro do backend

---

## 8. Tratamento de Erros

| Situação | Comportamento |
|---|---|
| Janela 24h expirada | Cancela com `reason='window_expired'`, sem envio |
| LLM retorna vazio | Cancela com `reason='empty_response'`, loga warning |
| `provider.send_text` lança exceção | Loga erro, job permanece `pending` (retentado) |
| `followup_enabled` desativado entre agendamento e disparo | Cancela com `reason='followup_disabled'` |
| Race condition: cliente responde ao mesmo tempo que job dispara | Aceita — mensagem enviada ainda é válida (janela ativa) |

---

## 9. Logs

Prefixo `[FOLLOWUP]` em todos os logs do módulo:

```
[FOLLOWUP] Agendado seq=1 fire_at=<iso> conversation=<id>
[FOLLOWUP] Agendado seq=2 fire_at=<iso> conversation=<id>
[FOLLOWUP] Enviado seq=1 lead=<phone>
[FOLLOWUP] Cancelado reason=client_replied conversation=<id>
[FOLLOWUP] Janela expirada — cancelando seq=2 conversation=<id>
[FOLLOWUP] LLM retornou vazio — cancelando seq=1 conversation=<id>
```

---

## 10. Fora de Escopo

- Prospecção fria (sem janela de 24h ativa)
- Templates aprovados pela Meta
- Follow-ups para outros canais além de WhatsApp
- Mais de 2 follow-ups por ciclo
- UI de histórico/auditoria dos jobs enviados
