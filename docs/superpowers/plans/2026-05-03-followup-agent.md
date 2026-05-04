# Follow-up Automático WhatsApp — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enviar mensagens de follow-up geradas por LLM (1h e 23h) quando o cliente não responde ao vendedor, com toggle por conversa e cancelamento automático ao receber resposta.

**Architecture:** Nova tabela `follow_up_jobs` no Supabase armazena os jobs com `fire_at`. O worker existente (`broadcast/worker.py`) executa `process_due_followups()` a cada 5s. Triggers de agendamento ficam em `buffer/processor.py` (Valéria) e no send route do Next.js (João). Cancelamento acontece em `meta_router.py` quando o cliente responde.

**Tech Stack:** Python 3.12 / FastAPI / Supabase (postgrest-py) / OpenAI gpt-4.1-mini / Next.js 15 App Router / TypeScript

---

## Mapa de Arquivos

| Ação | Arquivo |
|---|---|
| CREATE | `backend/app/follow_up/__init__.py` |
| CREATE | `backend/app/follow_up/service.py` |
| CREATE | `backend/app/follow_up/scheduler.py` |
| CREATE | `backend/app/follow_up/router.py` |
| MODIFY | `backend/app/main.py` |
| MODIFY | `backend/app/buffer/processor.py` |
| MODIFY | `backend/app/webhook/meta_router.py` |
| MODIFY | `backend/app/broadcast/worker.py` |
| CREATE | `frontend/src/app/api/conversations/[id]/followup/route.ts` |
| MODIFY | `frontend/src/app/api/conversations/[id]/send/route.ts` |
| MODIFY | `frontend/src/components/conversas/chat-header.tsx` |
| MODIFY | `frontend/src/components/conversas/chat-view.tsx` |
| MODIFY | `frontend/src/app/(authenticated)/conversas/page.tsx` |

---

## Task 1: Migração do Banco de Dados (Supabase MCP)

**Files:**
- Supabase project: `tshmvxxxyxgctrdkqvam`

- [ ] **Step 1: Aplicar migração via Supabase MCP**

Use a ferramenta `mcp__supabase__apply_migration` com o seguinte SQL:

```sql
-- Nova tabela para jobs de follow-up
CREATE TABLE follow_up_jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id),
  lead_id         UUID NOT NULL REFERENCES leads(id),
  channel_id      UUID NOT NULL REFERENCES channels(id),
  sequence        INTEGER NOT NULL CHECK (sequence IN (1, 2)),
  fire_at         TIMESTAMPTZ NOT NULL,
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'sent', 'cancelled')),
  cancel_reason   TEXT,
  sent_at         TIMESTAMPTZ,
  env_tag         TEXT NOT NULL DEFAULT 'production',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_followup_jobs_due
  ON follow_up_jobs (status, fire_at)
  WHERE status = 'pending';

CREATE INDEX idx_followup_jobs_conversation
  ON follow_up_jobs (conversation_id, status);

-- Coluna de toggle por conversa
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS followup_enabled BOOLEAN NOT NULL DEFAULT true;
```

- [ ] **Step 2: Verificar via Supabase MCP**

Use `mcp__supabase__execute_sql` com:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'follow_up_jobs';
```
Esperado: retorna as colunas criadas.

```sql
SELECT column_name FROM information_schema.columns
WHERE table_name = 'conversations' AND column_name = 'followup_enabled';
```
Esperado: retorna 1 linha.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat(db): add follow_up_jobs table and followup_enabled to conversations"
```

---

## Task 2: `follow_up/service.py` — CRUD

**Files:**
- Create: `backend/app/follow_up/__init__.py`
- Create: `backend/app/follow_up/service.py`

- [ ] **Step 1: Criar `__init__.py`**

Conteúdo: arquivo vazio.

```bash
touch backend/app/follow_up/__init__.py
```

- [ ] **Step 2: Criar `service.py`**

```python
# backend/app/follow_up/service.py
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.config import get_settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


def schedule_followup(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
) -> None:
    """Cancela jobs pendentes anteriores e cria 2 novos (1h e 23h)."""
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    # Cancela pending da mesma conversa (idempotência)
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": "rescheduled",
    }).eq("conversation_id", conversation_id).eq("status", "pending").execute()

    jobs = [
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 1,
            "fire_at": (now + timedelta(hours=1)).isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
        {
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": 2,
            "fire_at": (now + timedelta(hours=23)).isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
        },
    ]
    sb.table("follow_up_jobs").insert(jobs).execute()
    logger.info(f"[FOLLOWUP] Agendado seq=1 e seq=2 conversation={conversation_id}")


def cancel_followups(conversation_id: str, reason: str) -> None:
    """Cancela todos os jobs pending de uma conversa."""
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).eq("conversation_id", conversation_id).eq("status", "pending").execute()
    logger.info(f"[FOLLOWUP] Cancelado reason={reason} conversation={conversation_id}")


def cancel_followups_by_phone(phone: str, reason: str) -> None:
    """Cancela follow-ups pending de todas as conversas de um lead pelo phone."""
    sb = get_supabase()

    lead_result = (
        sb.table("leads")
        .select("id")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    if not lead_result.data:
        return

    lead_id = lead_result.data[0]["id"]

    conversations = (
        sb.table("conversations")
        .select("id")
        .eq("lead_id", lead_id)
        .execute()
    )
    if not conversations.data:
        return

    conv_ids = [c["id"] for c in conversations.data]
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).in_("conversation_id", conv_ids).eq("status", "pending").execute()
    logger.info(f"[FOLLOWUP] Cancelado reason={reason} phone={phone}")


def get_due_followups(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    """Retorna jobs pending cujo fire_at já passou."""
    sb = get_supabase()
    result = (
        sb.table("follow_up_jobs")
        .select(
            "*, "
            "leads!inner(id, phone, last_customer_message_at), "
            "channels!inner(id, name, provider, provider_config), "
            "conversations!inner(id, stage, followup_enabled)"
        )
        .eq("status", "pending")
        .eq("env_tag", _ENV_TAG)
        .lte("fire_at", now.isoformat())
        .order("fire_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data
```

- [ ] **Step 3: Verificar importação**

```bash
cd backend && python -c "from app.follow_up.service import schedule_followup, cancel_followups, cancel_followups_by_phone, get_due_followups; print('OK')"
```
Esperado: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/follow_up/
git commit -m "feat(followup): add follow_up service CRUD"
```

---

## Task 3: `follow_up/scheduler.py` — Lógica de Disparo

**Files:**
- Create: `backend/app/follow_up/scheduler.py`

- [ ] **Step 1: Criar `scheduler.py`**

```python
# backend/app/follow_up/scheduler.py
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.follow_up.service import get_due_followups, cancel_followups
from app.conversations.service import get_history, save_message
from app.whatsapp.registry import get_provider
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


async def _generate_followup_message(history: list[dict], sequence: int) -> str:
    """Gera mensagem contextualizada via LLM para o follow-up."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    sequence_context = (
        "Esta é a primeira tentativa de retomar contato (1 hora após o último envio do vendedor). "
        "Seja leve, curioso e natural. Não pressione. Apenas demonstre interesse genuíno."
        if sequence == 1
        else
        "Esta é a última tentativa antes da janela de atendimento expirar (23 horas após o último envio). "
        "Seja mais direto, crie senso de oportunidade, mas sem ser agressivo."
    )

    messages_text = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Vendedor'}: {m['content']}"
        for m in history[-15:]
    )

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um assistente de vendas do Café Canastra. "
                    "Com base no histórico da conversa, escreva uma mensagem de follow-up para WhatsApp. "
                    f"{sequence_context} "
                    "Use linguagem informal brasileira, sem emojis excessivos. "
                    "Máximo 3 linhas. Não use saudações formais como 'Olá' ou 'Bom dia'. "
                    "Seja contextual — faça referência ao que foi discutido."
                ),
            },
            {
                "role": "user",
                "content": f"Histórico da conversa:\n{messages_text}\n\nEscreva o follow-up:",
            },
        ],
        max_tokens=200,
        temperature=0.8,
    )
    return (resp.choices[0].message.content or "").strip()


async def process_due_followups(now: datetime | None = None) -> None:
    """Processa jobs de follow-up vencidos. Chamado pelo worker a cada tick."""
    now = now or datetime.now(timezone.utc)
    jobs = get_due_followups(now)

    for job in jobs:
        conversation_id = job["conversation_id"]
        lead = job["leads"]
        channel = job["channels"]
        conversation = job["conversations"]
        sequence = job["sequence"]

        # Guard: toggle desativado
        if not conversation.get("followup_enabled", True):
            _cancel_job(job["id"], "followup_disabled")
            logger.info(
                f"[FOLLOWUP] followup_enabled=false — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Guard: janela de 24h
        last_msg_str = lead.get("last_customer_message_at")
        if not last_msg_str:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Sem last_customer_message_at — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
        if last_msg + timedelta(hours=24) <= now:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Janela expirada — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Gera mensagem via LLM
        try:
            history = get_history(conversation_id, limit=20)
            message = await _generate_followup_message(history, sequence)
        except Exception as e:
            logger.error(f"[FOLLOWUP] Erro ao gerar mensagem seq={sequence} conversation={conversation_id}: {e}", exc_info=True)
            continue

        if not message:
            _cancel_job(job["id"], "empty_response")
            logger.warning(
                f"[FOLLOWUP] LLM retornou vazio — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Envia via WhatsApp
        try:
            provider = get_provider(channel)
            await provider.send_text(lead["phone"], message)
        except Exception as e:
            logger.error(
                f"[FOLLOWUP] Falha ao enviar seq={sequence} lead={lead['phone']}: {e}",
                exc_info=True,
            )
            # Não cancela — job fica pending para retentativa
            continue

        # Persiste mensagem e marca job como enviado
        try:
            save_message(
                conversation_id=conversation_id,
                lead_id=job["lead_id"],
                role="assistant",
                content=message,
                stage=conversation.get("stage"),
                sent_by="followup",
            )
        except Exception as e:
            logger.warning(f"[FOLLOWUP] Falha ao salvar mensagem seq={sequence}: {e}")

        _mark_sent(job["id"])
        logger.info(f"[FOLLOWUP] Enviado seq={sequence} lead={lead['phone']}")


def _cancel_job(job_id: str, reason: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).eq("id", job_id).execute()


def _mark_sent(job_id: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()
```

- [ ] **Step 2: Verificar importação**

```bash
cd backend && python -c "from app.follow_up.scheduler import process_due_followups; print('OK')"
```
Esperado: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/follow_up/scheduler.py
git commit -m "feat(followup): add follow-up scheduler with LLM generation"
```

---

## Task 4: `follow_up/router.py` + Registro em `main.py`

**Files:**
- Create: `backend/app/follow_up/router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Criar `router.py`**

```python
# backend/app/follow_up/router.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.follow_up.service import schedule_followup, cancel_followups
from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/conversations", tags=["follow_up"])


class FollowupToggle(BaseModel):
    enabled: bool


class FollowupScheduleRequest(BaseModel):
    conversation_id: str


@router.patch("/{conversation_id}/followup")
async def toggle_followup(conversation_id: str, body: FollowupToggle):
    """Ativa/desativa follow-up automático para a conversa."""
    sb = get_supabase()

    result = (
        sb.table("conversations")
        .update({"followup_enabled": body.enabled})
        .eq("id", conversation_id)
        .select("id, followup_enabled")
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not body.enabled:
        cancel_followups(conversation_id, reason="manual")

    return result.data[0]


@router.post("/{conversation_id}/followup/schedule")
async def schedule_followup_for_conversation(conversation_id: str):
    """Agenda follow-ups para a conversa (chamado após vendedor humano enviar mensagem)."""
    sb = get_supabase()

    conv = (
        sb.table("conversations")
        .select("id, lead_id, channel_id, followup_enabled")
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    data = conv.data
    if not data.get("followup_enabled", True):
        return {"status": "skipped", "reason": "followup_disabled"}

    schedule_followup(
        conversation_id=conversation_id,
        lead_id=data["lead_id"],
        channel_id=data["channel_id"],
    )
    return {"status": "scheduled"}
```

- [ ] **Step 2: Registrar router em `main.py`**

Adicionar após a linha `from app.templates.router import router as templates_router`:

```python
from app.follow_up.router import router as follow_up_router
```

Adicionar após `app.include_router(templates_router)`:

```python
app.include_router(follow_up_router)
```

- [ ] **Step 3: Verificar servidor sobe sem erro**

```bash
cd backend && uvicorn app.main:app --port 8001 --host 0.0.0.0 &
sleep 3
curl -s http://localhost:8001/health
kill %1
```
Esperado: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add backend/app/follow_up/router.py backend/app/main.py
git commit -m "feat(followup): add follow-up router and register in main"
```

---

## Task 5: Trigger em `buffer/processor.py` (Valéria IA)

**Files:**
- Modify: `backend/app/buffer/processor.py`

- [ ] **Step 1: Adicionar import ao topo de `processor.py`**

Após a linha `from app.cadence.service import get_active_enrollment, pause_enrollment`, adicionar:

```python
from app.follow_up.service import schedule_followup
```

- [ ] **Step 2: Adicionar trigger após `save_message` do assistente**

Localizar o bloco "Save assistant response" (aproximadamente linha 257):

```python
    # Save assistant response
    try:
        save_message(
            conversation["id"], lead["id"], "assistant",
            response, conversation.get("stage"),
        )
    except Exception as e:
        logger.error(f"Failed to save assistant message for {phone}: {e}", exc_info=True)
```

Adicionar imediatamente APÓS esse bloco (antes de "Send bubbles"):

```python
    # Agenda follow-up se habilitado para a conversa
    if conversation.get("followup_enabled", True) and channel:
        try:
            schedule_followup(
                conversation_id=conversation["id"],
                lead_id=lead["id"],
                channel_id=channel["id"],
            )
        except Exception as e:
            logger.warning(f"[FOLLOWUP] Falha ao agendar follow-up para {phone}: {e}")
```

- [ ] **Step 3: Verificar importação**

```bash
cd backend && python -c "from app.buffer.processor import process_buffered_messages; print('OK')"
```
Esperado: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/buffer/processor.py
git commit -m "feat(followup): trigger follow-up scheduling after Valéria sends message"
```

---

## Task 6: Cancelamento em `meta_router.py` (Cliente Responde)

**Files:**
- Modify: `backend/app/webhook/meta_router.py`

- [ ] **Step 1: Localizar `_track_inbound_message_time`**

A função está por volta da linha 21. Ela termina com um `except` que faz `logger.warning`. Adicionar um segundo bloco `try/except` depois do primeiro:

```python
def _track_inbound_message_time(phone: str) -> None:
    """Update last_customer_message_at so the 24h window status stays current."""
    try:
        sb = get_supabase()
        normalized = normalize_phone(phone)
        sb.table("leads").update(
            {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
        ).eq("phone", normalized).execute()
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {normalized}: {e}")

    # Cancela follow-ups pendentes pois cliente respondeu
    try:
        from app.follow_up.service import cancel_followups_by_phone
        normalized_for_cancel = normalize_phone(phone)
        cancel_followups_by_phone(normalized_for_cancel, reason="client_replied")
    except Exception as e:
        logger.warning(f"[FOLLOWUP] Failed to cancel follow-ups for {phone}: {e}")
```

- [ ] **Step 2: Verificar importação**

```bash
cd backend && python -c "from app.webhook.meta_router import router; print('OK')"
```
Esperado: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/webhook/meta_router.py
git commit -m "feat(followup): cancel pending follow-ups when client replies"
```

---

## Task 7: Integração no Worker (`broadcast/worker.py`)

**Files:**
- Modify: `backend/app/broadcast/worker.py`

- [ ] **Step 1: Adicionar import**

Após a linha:
```python
from app.cadence.scheduler import (
    process_due_cadences,
    process_reengagements,
    process_stagnation_triggers,
    calculate_next_send_at,
)
```

Adicionar:
```python
from app.follow_up.scheduler import process_due_followups
```

- [ ] **Step 2: Adicionar chamada ao loop `run_worker`**

Localizar a função `run_worker()`:

```python
async def run_worker():
    """Main worker loop: processes broadcasts, cadences, and stagnation triggers."""
    logger.info("Broadcast + Cadence worker started")

    while True:
        try:
            await process_broadcasts()
            await process_due_cadences()
            await process_reengagements()
            await process_stagnation_triggers()
            await process_due_followups()          # ← adicionar aqui
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)
```

- [ ] **Step 3: Verificar importação**

```bash
cd backend && python -c "from app.broadcast.worker import run_worker; print('OK')"
```
Esperado: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/broadcast/worker.py
git commit -m "feat(followup): add process_due_followups to worker loop"
```

---

## Task 8: Next.js API Route — Toggle do Follow-up

**Files:**
- Create: `frontend/src/app/api/conversations/[id]/followup/route.ts`

- [ ] **Step 1: Criar route**

```typescript
// frontend/src/app/api/conversations/[id]/followup/route.ts
import { NextResponse, type NextRequest } from "next/server";

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id: conversationId } = await params;
  const body = await request.json();

  const backendUrl = (
    process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000"
  ).replace(/\/+$/, "");

  try {
    const res = await fetch(
      `${backendUrl}/api/conversations/${conversationId}/followup`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: body.enabled }),
        signal: AbortSignal.timeout(10_000),
      }
    );

    if (!res.ok) {
      const text = await res.text();
      return NextResponse.json(
        { error: text },
        { status: res.status }
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Request failed";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
```

- [ ] **Step 2: Verificar build TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```
Esperado: sem erros relacionados ao arquivo criado.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/conversations/[id]/followup/"
git commit -m "feat(followup): add Next.js API route for followup toggle"
```

---

## Task 9: Trigger em `/send/route.ts` (João — Vendedor Humano)

**Files:**
- Modify: `frontend/src/app/api/conversations/[id]/send/route.ts`

- [ ] **Step 1: Localizar o ponto de inserção**

No bloco "Regular DB conversation" (linha ~117), logo após `return NextResponse.json({ status: "sent" })` — adicionar um fire-and-forget ANTES do return:

Substituir o bloco final da função POST para regular conversations (linhas ~102–121):

```typescript
    // Save message to DB
    await supabase.from("messages").insert({
      lead_id: lead.id,
      conversation_id: conversationId,
      role: "assistant",
      content: text.trim(),
      stage: conv.stage || "secretaria",
    });

    // Update conversation last_msg_at
    await supabase
      .from("conversations")
      .update({ last_msg_at: new Date().toISOString() })
      .eq("id", conversationId);

    // Agenda follow-up no backend Python (fire-and-forget)
    const backendUrl = (
      process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000"
    ).replace(/\/+$/, "");
    fetch(
      `${backendUrl}/api/conversations/${conversationId}/followup/schedule`,
      { method: "POST", signal: AbortSignal.timeout(5_000) }
    ).catch(() => {/* ignorado intencionalmente */});

    return NextResponse.json({ status: "sent" });
```

- [ ] **Step 2: Verificar build TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```
Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/conversations/[id]/send/route.ts"
git commit -m "feat(followup): trigger follow-up schedule after human vendor send"
```

---

## Task 10: Toggle no `ChatHeader`

**Files:**
- Modify: `frontend/src/components/conversas/chat-header.tsx`

- [ ] **Step 1: Adicionar props e botão**

Substituir o arquivo inteiro:

```typescript
"use client";

import type { Conversation, Tag } from "@/lib/types";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";

interface ChatHeaderProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
}

function getStageColor(stage: string | undefined): string {
  const map: Record<string, string> = {
    secretaria: "#8a8a80",
    atacado: "#5b8aad",
    private_label: "#8b6bab",
    exportacao: "#5aad65",
    consumo: "#ad9c4a",
  };
  return map[stage ?? ""] ?? "#8a8a80";
}

export function ChatHeader({
  conversation,
  tags,
  aiEnabled,
  togglingAi,
  onToggleAi,
  followupEnabled,
  togglingFollowup,
  onToggleFollowup,
}: ChatHeaderProps) {
  const lead = conversation.leads;
  const channel = conversation.channels;

  const displayName = lead?.name || lead?.phone || "Desconhecido";
  const initial = displayName.charAt(0).toUpperCase();
  const avatarColor = getStageColor(lead?.stage);

  const tagIdsRaw = (lead as unknown as Record<string, unknown>)?.tag_ids;
  const tagIds = Array.isArray(tagIdsRaw) ? (tagIdsRaw as string[]) : [];
  const leadTags = tags.filter((t) => tagIds.includes(t.id));

  return (
    <div className="border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-3 flex items-center gap-3 flex-shrink-0">
      {/* Avatar */}
      <div
        className="w-9 h-9 rounded-full flex items-center justify-center text-white font-medium text-sm flex-shrink-0"
        style={{ backgroundColor: avatarColor }}
      >
        {initial}
      </div>

      {/* Name + phone */}
      <div className="flex-1 min-w-0">
        <h2 className="text-[#111111] font-medium text-[14px] truncate">
          {displayName}
        </h2>
        <p className="text-[#7b7b78] text-[12px]">{lead?.phone || ""}</p>
      </div>

      {/* Tags */}
      {leadTags.length > 0 && (
        <div className="flex gap-1 flex-shrink-0">
          {leadTags.map((tag) => (
            <span
              key={tag.id}
              className="px-2 py-0.5 rounded-[4px] text-[11px] text-white"
              style={{ backgroundColor: tag.color }}
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}

      {/* Channel badge */}
      {channel && (
        <span className="text-[11px] px-2 py-0.5 rounded-[4px] bg-[#dedbd6]/60 text-[#7b7b78] flex-shrink-0">
          {channel.name}
        </span>
      )}

      {/* WhatsApp 24h window indicator */}
      <WhatsappWindowIndicator
        expiresAt={conversation.whatsapp_window_expires_at ?? null}
        variant="header"
        className="flex-shrink-0"
      />

      {/* Valéria IA toggle */}
      <button
        type="button"
        onClick={() => onToggleAi()}
        disabled={togglingAi}
        className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1 text-xs font-medium transition-colors flex-shrink-0 ${
          aiEnabled
            ? "bg-[#ff5600] text-white hover:bg-[#e64e00]"
            : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
        } ${togglingAi ? "opacity-60 cursor-not-allowed" : ""}`}
        aria-pressed={aiEnabled}
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            aiEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"
          }`}
          aria-hidden
        />
        Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
      </button>

      {/* Follow-up toggle */}
      <button
        type="button"
        onClick={() => onToggleFollowup()}
        disabled={togglingFollowup}
        className={`inline-flex items-center gap-2 rounded-[4px] px-3 py-1 text-xs font-medium transition-colors flex-shrink-0 ${
          followupEnabled
            ? "bg-[#1e6ee8] text-white hover:bg-[#1a5ec8]"
            : "bg-[#dedbd6] text-[#111111] hover:bg-[#cbc7c0]"
        } ${togglingFollowup ? "opacity-60 cursor-not-allowed" : ""}`}
        aria-pressed={followupEnabled}
      >
        <span
          className={`inline-block h-1.5 w-1.5 rounded-full ${
            followupEnabled ? "bg-white animate-pulse" : "bg-[#7b7b78]"
          }`}
          aria-hidden
        />
        Follow-up · {followupEnabled ? "Ativo" : "Pausado"}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verificar build TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep chat-header
```
Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/chat-header.tsx
git commit -m "feat(followup): add follow-up toggle button to ChatHeader"
```

---

## Task 11: Props em `chat-view.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Adicionar props à interface e passagem ao ChatHeader**

Localizar a interface de props (em torno da linha 14):

```typescript
interface ChatViewProps {
  conversation: Conversation;
  tags: Tag[];
  aiEnabled: boolean;
  togglingAi?: boolean;
  onToggleAi: () => void | Promise<void>;
  followupEnabled: boolean;
  togglingFollowup?: boolean;
  onToggleFollowup: () => void | Promise<void>;
}
```

Atualizar a desestruturação da função:

```typescript
export function ChatView({
  conversation,
  tags,
  aiEnabled,
  togglingAi,
  onToggleAi,
  followupEnabled,
  togglingFollowup,
  onToggleFollowup,
}: ChatViewProps) {
```

Atualizar o uso de `<ChatHeader>` (em torno da linha 102):

```typescript
<ChatHeader
  conversation={conversation}
  tags={tags}
  aiEnabled={aiEnabled}
  togglingAi={togglingAi}
  onToggleAi={onToggleAi}
  followupEnabled={followupEnabled}
  togglingFollowup={togglingFollowup}
  onToggleFollowup={onToggleFollowup}
/>
```

- [ ] **Step 2: Verificar build TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep chat-view
```
Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "feat(followup): pass followup props through ChatView to ChatHeader"
```

---

## Task 12: Estado e Handler em `conversas/page.tsx`

**Files:**
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`

- [ ] **Step 1: Adicionar state de follow-up**

Localizar onde `togglingAi` é declarado (em torno da linha 24):

```typescript
const [togglingAi, setTogglingAi] = useState(false);
```

Adicionar logo abaixo:

```typescript
const [togglingFollowup, setTogglingFollowup] = useState(false);
```

- [ ] **Step 2: Adicionar handler `handleToggleFollowup`**

Adicionar imediatamente após a função `handleToggleAi` (após o seu `}` de fechamento):

```typescript
async function handleToggleFollowup() {
  if (!selectedConversation || togglingFollowup) return;
  const current = (selectedConversation as any)?.followup_enabled ?? true;
  const next = !current;
  setTogglingFollowup(true);

  // Optimistic update
  const patch = { followup_enabled: next };
  setConversations((prev) =>
    prev.map((c) => (c.id === selectedConversation.id ? { ...c, ...patch } : c))
  );
  setSelectedConversation((prev) =>
    prev && prev.id === selectedConversation.id ? { ...prev, ...patch } : prev
  );

  try {
    const res = await fetch(
      `/api/conversations/${selectedConversation.id}/followup`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
        signal: AbortSignal.timeout(10_000),
      }
    );
    if (!res.ok) throw new Error(`status ${res.status}`);
  } catch (err) {
    console.warn("[toggle-followup] failed:", err);
    // Rollback
    const rollback = { followup_enabled: current };
    setConversations((prev) =>
      prev.map((c) =>
        c.id === selectedConversation.id ? { ...c, ...rollback } : c
      )
    );
    setSelectedConversation((prev) =>
      prev && prev.id === selectedConversation.id
        ? { ...prev, ...rollback }
        : prev
    );
  } finally {
    setTogglingFollowup(false);
  }
}
```

- [ ] **Step 3: Passar props ao `<ChatView>`**

Localizar onde `<ChatView>` é renderizado (em torno da linha 316):

```tsx
<ChatView
  conversation={selectedConversation}
  tags={tags}
  aiEnabled={(selectedConversation.leads as any)?.ai_enabled ?? true}
  togglingAi={togglingAi}
  onToggleAi={handleToggleAi}
  followupEnabled={(selectedConversation as any)?.followup_enabled ?? true}
  togglingFollowup={togglingFollowup}
  onToggleFollowup={handleToggleFollowup}
/>
```

- [ ] **Step 4: Verificar build TypeScript**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```
Esperado: sem erros de TypeScript.

- [ ] **Step 5: Verificar no browser**

1. Abrir `/conversas` no browser
2. Selecionar uma conversa
3. Confirmar que dois botões aparecem no header: "Valéria IA · Ativa" (laranja) e "Follow-up · Ativo" (azul)
4. Clicar em "Follow-up · Ativo" — deve mudar para "Follow-up · Pausado" (cinza)
5. Recarregar página — estado deve persistir (vem do Supabase via `followup_enabled`)

- [ ] **Step 6: Commit**

```bash
git add "frontend/src/app/(authenticated)/conversas/page.tsx"
git commit -m "feat(followup): add follow-up toggle state and handler to conversas page"
```

---

## Verificação End-to-End

Após todas as tasks:

- [ ] **Subir ambiente de desenvolvimento** com VS Code task `Run All Dev (CRM & Backend)`
- [ ] **Simular envio da Valéria:** enviar mensagem de cliente para uma conversa ativa → Valéria responde → verificar no Supabase que 2 jobs foram criados em `follow_up_jobs` com `status=pending`
- [ ] **Simular resposta do cliente:** enviar nova mensagem do cliente → verificar que os 2 jobs mudam para `status=cancelled, cancel_reason=client_replied`
- [ ] **Simular disparo:** via Supabase MCP, atualizar `fire_at` de um job para `now() - interval '1 minute'` → aguardar 5s → verificar que job muda para `status=sent` e mensagem aparece na conversa
- [ ] **Verificar toggle manual:** desligar Follow-up no browser → jobs pendentes cancelados com `cancel_reason=manual`
