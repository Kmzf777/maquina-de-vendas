# Conversas UX Redesign — Fase B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **PROJECT-SPECIFIC RULE:** Every task that touches frontend code (`frontend/src/**`) MUST invoke the `frontend-design` skill BEFORE writing any JSX/CSS/Tailwind. Each frontend task below repeats this requirement in its first step.

**Goal:** Redesenhar a página `/conversas` removendo a sensação "ciborg" — adicionar badge de não-lidas, unificar datetime e indicador de janela 24h, mover toggle Valéria para o header, e redesenhar o card selecionado.

**Architecture:** Backend FastAPI + Supabase (cliente Python) com migrations SQL puras (`backend/migrations/*.sql`). Frontend Next.js App Router + TypeScript + Tailwind. Sem ORM no backend; sem framework de testes pesado (validação majoritariamente manual conforme `CLAUDE.md`).

**Tech Stack:** Python 3.11+, FastAPI, Supabase Python client, Pydantic; TypeScript, Next.js 14+ App Router, Tailwind, Radix/shadcn, date-fns.

**Spec base:** `docs/superpowers/specs/2026-04-29-conversas-ux-redesign-b-design.md`
**Audit base:** `docs/superpowers/specs/2026-04-29-conversas-ux-audit.md`
**Branch:** `feat/conversas-ux-redesign-v2`

---

## File Structure

### Created
- `backend/migrations/20260429_conversations_unread_count.sql` — schema + backfill
- `frontend/src/lib/datetime.ts` — datetime helper único (3 funções)
- `frontend/src/components/conversas/whatsapp-window-indicator.tsx` — componente unificado

### Modified
- `backend/app/conversations/service.py` — `reset_unread_count`, expose computed `whatsapp_window_expires_at` em listings
- `backend/app/conversations/router.py` — endpoint `POST /api/conversations/{id}/mark-read`
- `backend/app/buffer/processor.py` — incremento de `unread_count` ao salvar mensagem inbound
- `frontend/src/lib/types.ts` — add `unread_count` + `whatsapp_window_expires_at` em `Conversation`
- `frontend/src/components/conversas/chat-list.tsx` — novo card (3 níveis tipográficos, badge, selected redesenhado, datetime helper, indicador compact)
- `frontend/src/components/conversas/chat-header.tsx` — toggle Valéria + indicador header
- `frontend/src/components/conversas/chat-view.tsx` — usar componente unificado, banner quando expired
- `frontend/src/components/conversas/contact-detail.tsx` — remover toggle Valéria
- `frontend/src/components/conversas/message-bubble.tsx` — `formatTimeOnly`
- `frontend/src/components/conversas/day-separator.tsx` — `formatDayLabel`
- `frontend/src/components/conversas/window-reactivate-panel.tsx` — header reusa indicador

---

## Phase 1 — Backend foundation

### Task 1: SQL migration — adicionar `unread_count`

**Files:**
- Create: `backend/migrations/20260429_conversations_unread_count.sql`

- [ ] **Step 1: Criar migration**

```sql
-- 20260429_conversations_unread_count.sql
-- Adiciona contador de mensagens não-lidas por conversa.
-- Incrementado a cada mensagem inbound (sent_by='user') e zerado via endpoint mark-read.

ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS unread_count INTEGER NOT NULL DEFAULT 0;

-- Backfill defensivo (DEFAULT já cobre, mas garante)
UPDATE conversations SET unread_count = 0 WHERE unread_count IS NULL;

-- Index opcional para sort/filter por não-lidas
CREATE INDEX IF NOT EXISTS idx_conversations_unread_count
  ON conversations (unread_count) WHERE unread_count > 0;
```

- [ ] **Step 2: Aplicar migration via Supabase**

A migration deve ser aplicada via MCP supabase OU manualmente pelo usuário no painel. **Não rodar automaticamente em produção** — apenas em dev/staging primeiro.

Verificar como migrations anteriores foram aplicadas inspecionando `backend/migrations/` em ordem cronológica e perguntando ao usuário se há um script wrapper. Se não houver, deixar a migration pronta no repositório e avisar o usuário para aplicar manualmente em dev.

Comando de verificação após aplicação:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'conversations' AND column_name = 'unread_count';
```

Esperado: `unread_count | integer | 0`

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/20260429_conversations_unread_count.sql
git commit -m "feat(db): add unread_count column to conversations"
```

---

### Task 2: Increment `unread_count` on inbound message

**Files:**
- Modify: `backend/app/buffer/processor.py:174-184` (logo após `save_message` para mensagem do usuário)

- [ ] **Step 1: Adicionar increment do `unread_count` após salvar mensagem inbound**

Logo após o bloco `save_message(...)` que persiste a mensagem do usuário (linhas ~174-184 do `processor.py`), adicionar:

```python
    # Incrementa contador de não-lidas para o vendedor (resetado quando ele abre a conversa)
    try:
        sb = get_supabase()
        sb.rpc(
            "increment_conversation_unread",
            {"conv_id": conversation["id"]},
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to increment unread_count for {conversation['id']}: {e}")
```

Mas como o projeto usa Supabase client e RPCs precisam ser criadas separadamente, **alternativa sem RPC** (mais simples e suficiente):

```python
    # Incrementa contador de não-lidas para o vendedor (resetado quando ele abre a conversa)
    try:
        sb = get_supabase()
        current = (
            sb.table("conversations")
            .select("unread_count")
            .eq("id", conversation["id"])
            .single()
            .execute()
        )
        new_count = (current.data.get("unread_count") or 0) + 1
        sb.table("conversations").update({"unread_count": new_count}).eq("id", conversation["id"]).execute()
    except Exception as e:
        logger.warning(f"Failed to increment unread_count for {conversation['id']}: {e}")
```

Posicionar **DEPOIS** do `save_message` da mensagem `user` e **ANTES** dos blocos de `human_control` / `ai_enabled` checks. A intenção é: toda mensagem inbound que chega aumenta o contador, independente de quem vai responder (vendedor ou IA).

- [ ] **Step 2: Verificação manual**

Sem framework de teste pesado no backend, verificar manualmente em dev:

1. Subir backend dev (`Run All Dev (CRM & Backend)` task)
2. Enviar mensagem WhatsApp de número de teste
3. Verificar no banco:

```sql
SELECT id, unread_count FROM conversations WHERE lead_id = '<lead-id>';
```

Esperado: `unread_count` incrementa em 1 a cada mensagem recebida.

- [ ] **Step 3: Commit**

```bash
git add backend/app/buffer/processor.py
git commit -m "feat(conversations): increment unread_count on inbound message"
```

---

### Task 3: Endpoint `POST /mark-read` + função no service

**Files:**
- Modify: `backend/app/conversations/service.py` (adicionar função `reset_unread_count`)
- Modify: `backend/app/conversations/router.py` (adicionar endpoint)

- [ ] **Step 1: Adicionar `reset_unread_count` em `service.py`**

Adicionar no final de `backend/app/conversations/service.py`:

```python
def reset_unread_count(conversation_id: str) -> dict[str, Any]:
    """Zera o contador de mensagens não-lidas. Chamado quando o vendedor abre a conversa."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .update({"unread_count": 0})
        .eq("id", conversation_id)
        .select("id, unread_count")
        .execute()
    )
    if not result.data:
        return {}
    return result.data[0]
```

- [ ] **Step 2: Adicionar endpoint em `router.py`**

Adicionar no final de `backend/app/conversations/router.py`:

```python
from fastapi import Response

from app.conversations.service import reset_unread_count


@router.post("/{conversation_id}/mark-read", status_code=204)
async def mark_conversation_read(conversation_id: str):
    """Zera unread_count da conversa (chamado quando o vendedor abre a conversa)."""
    result = reset_unread_count(conversation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)
```

⚠️ Atenção ao import existente: o arquivo já tem `from fastapi import APIRouter, HTTPException`. Trocar para `from fastapi import APIRouter, HTTPException, Response` (mesma linha).

E o import do service: `from app.db.supabase import get_supabase` é a única linha hoje. Adicionar abaixo: `from app.conversations.service import reset_unread_count`.

- [ ] **Step 3: Verificação manual**

```bash
# Em dev, com backend rodando:
curl -X POST http://127.0.0.1:8000/api/conversations/<conv-id>/mark-read -i
# Esperado: HTTP/1.1 204 No Content
```

E SQL após o curl:

```sql
SELECT unread_count FROM conversations WHERE id = '<conv-id>';
```

Esperado: `0`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/conversations/service.py backend/app/conversations/router.py
git commit -m "feat(conversations): add mark-read endpoint to reset unread_count"
```

---

### Task 4: Expor `whatsapp_window_expires_at` no payload de listagem

**Files:**
- Modify: `backend/app/conversations/service.py` (funções `list_conversations` e `get_conversation`)

**Contexto:** O backend já rastreia `leads.last_customer_message_at` (atualizado em `processor.py:188-191`). A janela 24h é computada como `last_customer_message_at + 24h`. Em vez de criar coluna nova, expomos o valor computado nas respostas da API.

- [ ] **Step 1: Modificar `list_conversations` para incluir o campo `last_customer_message_at` do lead**

No `backend/app/conversations/service.py`, na função `list_conversations` (linhas 46-68), trocar o `.select(...)` para incluir `last_customer_message_at`:

```python
def list_conversations(
    channel_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sb = get_supabase()
    query = (
        sb.table("conversations")
        .select(
            "*, "
            "leads(id, phone, name, company, last_customer_message_at), "
            "channels(id, name, phone, provider)"
        )
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
    rows = result.data or []
    for row in rows:
        row["whatsapp_window_expires_at"] = _compute_window_expiration(row)
    return rows
```

E no `get_conversation` (linhas 34-43):

```python
def get_conversation(conversation_id: str) -> dict[str, Any]:
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select(
            "*, "
            "leads(*), "
            "channels(id, name, phone, provider)"
        )
        .eq("id", conversation_id)
        .single()
        .execute()
    )
    data = result.data
    if data:
        data["whatsapp_window_expires_at"] = _compute_window_expiration(data)
    return data
```

E adicionar a função helper no topo do arquivo (logo após os imports):

```python
from datetime import timedelta

def _compute_window_expiration(conversation: dict[str, Any]) -> str | None:
    """Retorna ISO da expiração da janela 24h ou None se nunca houve inbound."""
    leads = conversation.get("leads")
    if not leads:
        return None
    last = leads.get("last_customer_message_at")
    if not last:
        return None
    try:
        # last vem como ISO string do Postgres
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except Exception:
        return None
    return (last_dt + timedelta(hours=24)).isoformat()
```

⚠️ O `datetime` já é importado no arquivo (linha 2). Adicionar `timedelta` no mesmo import: `from datetime import datetime, timezone, timedelta`.

- [ ] **Step 2: Verificar que `unread_count` já vem no payload**

`select("*")` retorna todas as colunas — o `unread_count` adicionado na Task 1 já está incluído automaticamente. Nenhuma mudança adicional necessária.

- [ ] **Step 3: Verificação manual**

```bash
curl http://127.0.0.1:8000/api/conversations | jq '.[0] | {id, unread_count, whatsapp_window_expires_at}'
```

Esperado:
```json
{
  "id": "...",
  "unread_count": 0,
  "whatsapp_window_expires_at": "2026-04-30T..." // ou null se nunca houve inbound
}
```

⚠️ Verificar antes se existe um endpoint `GET /api/conversations` (lista). Se a lista está sendo lida direto do Supabase pelo frontend (via `frontend/src/lib/supabase`), pular este step e apenas garantir que o serviço backend está correto — o frontend pode precisar de ajuste paralelo. Decisão delegada ao agent: inspecionar `frontend/src/app/(authenticated)/conversas/page.tsx` para confirmar a fonte de dados.

- [ ] **Step 4: Commit**

```bash
git add backend/app/conversations/service.py
git commit -m "feat(conversations): expose computed whatsapp_window_expires_at in payload"
```

---

## Phase 2 — Frontend foundations

### Task 5: Atualizar tipos TypeScript

**Files:**
- Modify: `frontend/src/lib/types.ts:251-265` (interface `Conversation`)

- [ ] **Step 1: Invocar skill `frontend-design`**

Antes de qualquer mudança no frontend, invocar `frontend-design` skill via Skill tool. Mesmo para edição de tipos — alinha o agent com o design system antes do trabalho visual subsequente.

- [ ] **Step 2: Adicionar campos ao tipo `Conversation`**

No `frontend/src/lib/types.ts`, modificar a interface `Conversation` (linhas 251-265) para:

```typescript
export interface Conversation {
  id: string;
  lead_id: string;
  channel_id: string;
  stage: string;
  status: string;
  last_msg_at: string | null;
  created_at: string;
  agent_profile_id: string | null;
  ai_enabled: boolean;
  last_message_text: string | null;
  unread_count: number;
  whatsapp_window_expires_at: string | null;
  leads?: Lead;
  channels?: { id: string; name: string; phone: string; provider: string; agent_profile_id: string | null } | null;
  agent_profiles?: { id: string; name: string } | null;
}
```

- [ ] **Step 3: Verificar TypeScript compila**

```bash
cd frontend && npm run type-check 2>&1 | tail -20
```

Esperado: 0 erros novos. Erros existentes não relacionados podem ser ignorados.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(types): add unread_count and whatsapp_window_expires_at to Conversation"
```

---

### Task 6: Criar `lib/datetime.ts`

**Files:**
- Create: `frontend/src/lib/datetime.ts`

- [ ] **Step 1: Invocar skill `frontend-design`**

Antes de escrever o helper, invocar `frontend-design` para confirmar tokens tipográficos e padrões do design system.

- [ ] **Step 2: Criar `frontend/src/lib/datetime.ts`**

```typescript
import {
  differenceInCalendarDays,
  differenceInMinutes,
  format,
  isToday,
  isYesterday,
  parseISO,
} from "date-fns";
import { ptBR } from "date-fns/locale";

const safeParse = (iso: string): Date | null => {
  try {
    const d = parseISO(iso);
    if (isNaN(d.getTime())) return null;
    return d;
  } catch {
    return null;
  }
};

/**
 * Para timestamps em cards da lista de conversas.
 * Regras: <1min "agora"; <60min "Nmin"; mesmo dia "HH:mm"; ontem "Ontem";
 * <7d nome curto do dia; >7d "dd/MM/yyyy".
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = safeParse(iso);
  if (!d) return "";

  const now = new Date();
  const minutes = differenceInMinutes(now, d);

  if (minutes < 1) return "agora";
  if (minutes < 60) return `${minutes}min`;
  if (isToday(d)) return format(d, "HH:mm");
  if (isYesterday(d)) return "Ontem";

  const days = differenceInCalendarDays(now, d);
  if (days >= 0 && days < 7) return format(d, "EEE", { locale: ptBR });

  return format(d, "dd/MM/yyyy", { locale: ptBR });
}

/**
 * Para timestamps em bolhas de mensagem. Sempre HH:mm.
 */
export function formatTimeOnly(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = safeParse(iso);
  if (!d) return "";
  return format(d, "HH:mm");
}

/**
 * Para separadores de dia no MessageList.
 * Hoje / Ontem / nome do dia (<7d) / "dd 'de' MMMM" / com ano se diferente.
 */
export function formatDayLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = safeParse(iso);
  if (!d) return "";

  if (isToday(d)) return "Hoje";
  if (isYesterday(d)) return "Ontem";

  const now = new Date();
  const days = differenceInCalendarDays(now, d);
  if (days >= 0 && days < 7) return format(d, "EEEE", { locale: ptBR });

  const sameYear = d.getFullYear() === now.getFullYear();
  return sameYear
    ? format(d, "dd 'de' MMMM", { locale: ptBR })
    : format(d, "dd 'de' MMMM 'de' yyyy", { locale: ptBR });
}
```

- [ ] **Step 3: Verificar `date-fns` está instalado**

```bash
cd frontend && grep -E '"date-fns"' package.json
```

Esperado: linha com `"date-fns": "..."`. Se ausente, instalar: `npm install date-fns`.

- [ ] **Step 4: Verificar TypeScript compila**

```bash
cd frontend && npm run type-check 2>&1 | tail -10
```

Esperado: 0 erros novos.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/datetime.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(lib): add unified datetime helpers (formatRelativeTime, formatTimeOnly, formatDayLabel)"
```

---

## Phase 3 — Frontend component (foundation)

### Task 7: Criar `WhatsappWindowIndicator`

**Files:**
- Create: `frontend/src/components/conversas/whatsapp-window-indicator.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`**

OBRIGATÓRIO antes de escrever JSX/Tailwind. Carregar tokens (Fin Orange, warm neutrals), padrões de Tooltip e estilos do design system.

- [ ] **Step 2: Criar componente**

```tsx
"use client";

import { useEffect, useState } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type Variant = "compact" | "header" | "banner";
type State = "active" | "warning" | "critical" | "expired" | "none";

interface Props {
  expiresAt: string | null;
  variant: Variant;
  className?: string;
}

const TOOLTIP_TEXT =
  "Após 24h sem nova mensagem do lead, só é possível enviar templates aprovados pela Meta. Aguarde resposta ou use a aba de reativação.";

const computeState = (expiresAt: string | null): { state: State; minutesLeft: number } => {
  if (!expiresAt) return { state: "none", minutesLeft: 0 };
  const exp = new Date(expiresAt).getTime();
  if (isNaN(exp)) return { state: "none", minutesLeft: 0 };
  const minutesLeft = Math.floor((exp - Date.now()) / 60000);
  if (minutesLeft <= 0) return { state: "expired", minutesLeft: 0 };
  if (minutesLeft < 60) return { state: "critical", minutesLeft };
  if (minutesLeft < 240) return { state: "warning", minutesLeft };
  return { state: "active", minutesLeft };
};

const labelFor = (state: State, minutesLeft: number): string => {
  if (state === "expired") return "Janela expirada";
  if (state === "critical") return `${minutesLeft}min restantes`;
  if (state === "warning" || state === "active") {
    const hours = Math.floor(minutesLeft / 60);
    return `${hours}h restantes`;
  }
  return "";
};

const dotClassFor = (state: State): string => {
  switch (state) {
    case "active":
      return "bg-stone-400";
    case "warning":
      return "bg-amber-500";
    case "critical":
      return "bg-orange-500 animate-pulse";
    case "expired":
      return "bg-stone-500";
    default:
      return "bg-stone-300";
  }
};

const pillClassFor = (state: State): string => {
  switch (state) {
    case "active":
      return "bg-stone-100 text-stone-700 border-stone-200";
    case "warning":
      return "bg-amber-50 text-amber-800 border-amber-200";
    case "critical":
      return "bg-orange-50 text-orange-700 border-orange-200";
    case "expired":
      return "bg-stone-100 text-stone-600 border-stone-300";
    default:
      return "bg-stone-50 text-stone-500 border-stone-200";
  }
};

export function WhatsappWindowIndicator({ expiresAt, variant, className }: Props) {
  // Re-render a cada minuto para o countdown ficar vivo
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  const { state, minutesLeft } = computeState(expiresAt);

  if (state === "none" && variant !== "banner") return null;

  if (variant === "compact") {
    return (
      <span className={cn("inline-flex items-center gap-1 text-xs text-stone-500", className)}>
        <span
          className={cn("inline-block h-1.5 w-1.5 rounded-full", dotClassFor(state))}
          aria-hidden
        />
        {state !== "active" && state !== "none" && (
          <span>{labelFor(state, minutesLeft)}</span>
        )}
      </span>
    );
  }

  if (variant === "header") {
    return (
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
                pillClassFor(state),
                className,
              )}
            >
              <span
                className={cn("inline-block h-1.5 w-1.5 rounded-full", dotClassFor(state))}
                aria-hidden
              />
              <span>{labelFor(state, minutesLeft) || "Janela 24h"}</span>
            </span>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            <p className="text-xs leading-relaxed">{TOOLTIP_TEXT}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  // banner — usado quando expired
  if (state !== "expired") return null;
  return (
    <div
      className={cn(
        "flex items-center gap-2 border-b border-stone-200 bg-stone-50 px-4 py-2 text-sm text-stone-700",
        className,
      )}
      role="status"
    >
      <span className={cn("inline-block h-2 w-2 rounded-full", dotClassFor(state))} aria-hidden />
      <span className="font-medium">Janela 24h expirada</span>
      <span className="text-stone-500">— só é possível enviar templates aprovados.</span>
    </div>
  );
}
```

- [ ] **Step 3: Verificar imports do shadcn Tooltip existem**

```bash
ls frontend/src/components/ui/tooltip.tsx 2>&1
```

Esperado: arquivo existe. Se não, instalar via shadcn CLI (`npx shadcn-ui@latest add tooltip` no diretório `frontend/`) ou alertar o usuário.

Verificar também `cn` em `lib/utils.ts`:

```bash
ls frontend/src/lib/utils.ts 2>&1
```

Se não existir, criar `frontend/src/lib/utils.ts` com:
```typescript
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 4: Verificar TypeScript compila**

```bash
cd frontend && npm run type-check 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/whatsapp-window-indicator.tsx
git commit -m "feat(conversas): add unified WhatsappWindowIndicator component"
```

---

## Phase 4 — Frontend components (parallelizable after Task 7)

> Tasks 8–13 podem ser executadas em paralelo por subagents diferentes — não compartilham state. Cada uma DEVE invocar `frontend-design` antes de escrever código.

### Task 8: Refazer `chat-list.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`** (OBRIGATÓRIO)

- [ ] **Step 2: Ler arquivo atual**

```bash
# Use Read tool em frontend/src/components/conversas/chat-list.tsx
# Mapear: como recebe conversas, como renderiza cada card, como sinaliza selected,
# de onde vem cor de stage, como formata tempo, como chama o handler de seleção.
```

- [ ] **Step 3: Reescrever o card de conversa aplicando o design**

Mudanças no card de conversa (preservar o restante do componente — header, busca, tabs, scroll):

**Estado selected (substituir):**
- Remover qualquer `bg-[#111111]` ou fundo preto sólido.
- Aplicar: `bg-orange-50 border-l-[3px] border-l-orange-500` quando `isSelected`.
- Hover: `hover:bg-stone-50`.
- Focus visible: `focus-visible:ring-2 focus-visible:ring-orange-400 focus-visible:ring-offset-1 outline-none`.
- Texto preserva cores normais (NÃO inverter para `text-white/*`).

**3 níveis tipográficos:**
- **L1** (nome do lead): `text-sm font-semibold text-stone-900` em estado normal; `font-bold` quando `conversation.unread_count > 0`. Truncate.
- **L2** (preview): `text-sm text-stone-600 truncate` — usa `conversation.last_message_text` (já existe no tipo).
- **L3** (meta): `text-xs text-stone-500` em flex container com gap-2: timestamp via `formatRelativeTime(conversation.last_msg_at)` + stage pill (mantém componente atual de stage pill se existir, ou `<span>` simples) + `<WhatsappWindowIndicator expiresAt={conversation.whatsapp_window_expires_at} variant="compact" />`.

**Badge de não-lidas:**
Posicionado no canto superior direito do card, alinhado com L1:

```tsx
{conversation.unread_count > 0 && (
  <span
    className="ml-auto inline-flex min-w-[20px] items-center justify-center rounded-full bg-orange-500 px-1.5 py-0.5 text-[10px] font-semibold text-white animate-pulse"
    aria-label={`${conversation.unread_count} mensagens não lidas`}
  >
    {conversation.unread_count > 9 ? "9+" : conversation.unread_count}
  </span>
)}
```

**Imports a adicionar no topo:**
```tsx
import { formatRelativeTime } from "@/lib/datetime";
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
```

**Remover:**
- Função `formatTime` interna (substituir todas as chamadas por `formatRelativeTime`)
- Emojis ⏳/⏱/🔒/🔴 e lógica ad-hoc de janela 24h (substituir pelo `<WhatsappWindowIndicator variant="compact" />`)

- [ ] **Step 4: Chamar `mark-read` ao selecionar conversa**

No handler de click do card (que define `selectedConversationId`), após o setState, fazer fetch:

```tsx
// dentro do onClick handler do card, após setSelectedConversation(conversation.id)
fetch(`/api/conversations/${conversation.id}/mark-read`, { method: "POST" })
  .then((res) => {
    if (res.ok) {
      // atualiza state local zerando o counter da conversa selecionada
      setConversations((prev) =>
        prev.map((c) => (c.id === conversation.id ? { ...c, unread_count: 0 } : c)),
      );
    }
  })
  .catch((err) => console.warn("[mark-read] failed:", err));
```

⚠️ Se o componente busca conversas via Supabase direto (sem proxy do backend FastAPI), trocar a URL para a do backend conforme padrão do projeto (`process.env.NEXT_PUBLIC_API_URL` + path, ou rota interna de proxy `/api/...`). O agent deve inspecionar como outras chamadas a `/api/conversations/...` são feitas no projeto e seguir o mesmo padrão.

- [ ] **Step 5: Verificação visual no dev server**

```bash
# Subir Run All Dev (CRM & Backend) e abrir /conversas no browser
# Verificar:
# - Card sem mensagens novas: nome em font-semibold, sem badge
# - Card com mensagens novas: nome em font-bold, badge laranja com número, animação pulse
# - Selected: borda esquerda laranja 3px, fundo warm leve, texto preto-stone (legível)
# - Hover: fundo stone-50
# - Indicator 24h compact: dot colorido visível à direita do timestamp
# - Datas: formato consistente (agora / 5min / 14:30 / Ontem / qua / 12/03/2025)
# - Click em uma conversa com unread > 0: badge desaparece após o request
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/chat-list.tsx
git commit -m "feat(conversas): redesign chat-list — 3 typo levels, unread badge, new selected state, unified indicator"
```

---

### Task 9: Refazer `chat-header.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/chat-header.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`** (OBRIGATÓRIO)

- [ ] **Step 2: Ler arquivo atual**

```bash
# Use Read tool em frontend/src/components/conversas/chat-header.tsx
```

- [ ] **Step 3: Adicionar toggle Valéria + indicador**

**Imports:**
```tsx
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
```

**Toggle Valéria (pill-switch):**

Posicionar à direita do header, antes de qualquer ação de "fechar". Receber `aiEnabled: boolean` e `onToggleAi: () => Promise<void>` via props (se já existem no componente, reutilizar; se não, adicionar à interface de Props).

```tsx
<button
  type="button"
  onClick={() => onToggleAi()}
  disabled={togglingAi}
  className={cn(
    "inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium transition-colors",
    aiEnabled
      ? "bg-orange-500 text-white hover:bg-orange-600"
      : "bg-stone-100 text-stone-700 hover:bg-stone-200",
    togglingAi && "opacity-60 cursor-not-allowed",
  )}
  aria-pressed={aiEnabled}
>
  <span
    className={cn(
      "inline-block h-1.5 w-1.5 rounded-full",
      aiEnabled ? "bg-white animate-pulse" : "bg-stone-400",
    )}
    aria-hidden
  />
  Valéria IA · {aiEnabled ? "Ativa" : "Pausada"}
</button>
```

**Indicador 24h (header variant):**

Posicionar entre o nome/info do lead e o toggle Valéria. Recebe `expiresAt={conversation.whatsapp_window_expires_at}`:

```tsx
<WhatsappWindowIndicator
  expiresAt={conversation.whatsapp_window_expires_at}
  variant="header"
/>
```

- [ ] **Step 4: Garantir que o handler de toggle vive aqui (ou no parent)**

Se hoje o toggle e seu handler (`handleAiToggle` etc.) ainda estão em `contact-detail.tsx`, mover a lógica de fetch para o parent comum (provavelmente `page.tsx` em `(authenticated)/conversas/`) e passar via props para o ChatHeader. **Manter idempotência de race condition já resolvida no commit `c93d889`** — repetir o padrão (não regrediar).

- [ ] **Step 5: Verificação visual no dev**

- Conversa com IA ativa: pill laranja com dot pulsando, label "Valéria IA · Ativa"
- Click: pill vira cinza, label "Valéria IA · Pausada", request enviado, sem race
- Indicador 24h: pill warm com countdown, tooltip ao hover explicando regra Meta

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/chat-header.tsx frontend/src/app/\(authenticated\)/conversas/page.tsx
git commit -m "feat(conversas): move Valéria toggle to ChatHeader + integrate window indicator"
```

---

### Task 10: Atualizar `chat-view.tsx` — banner expired

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`** (OBRIGATÓRIO)

- [ ] **Step 2: Substituir indicadores ad-hoc por componente unificado**

Adicionar:
```tsx
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
```

Posicionar `<WhatsappWindowIndicator variant="banner" expiresAt={conversation.whatsapp_window_expires_at} />` no topo do chat, logo abaixo do header e acima da MessageList. O componente já se auto-esconde quando state ≠ expired, então pode ser deixado lá sempre.

Remover qualquer outro indicador/pill duplicado de janela 24h que estava em `chat-view.tsx`.

- [ ] **Step 3: Verificação visual no dev**

- Conversa ativa (não expirada): banner não aparece
- Conversa expirada: banner cinza no topo com texto "Janela 24h expirada — só é possível enviar templates aprovados."

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "refactor(conversas): use unified window indicator banner in chat-view"
```

---

### Task 11: Limpar `contact-detail.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/contact-detail.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`** (OBRIGATÓRIO)

- [ ] **Step 2: Remover seção do toggle Valéria**

Identificar o bloco que renderiza o toggle de Pausar/Ativar IA na sidebar direita e removê-lo. Limpar imports/estados/handlers que ficarem órfãos. Se o handler agora vive no parent (Task 9), remover daqui também.

A sidebar deve ficar com: dados do lead (nome, telefone, empresa), tags, notas, eventos — sem o toggle.

- [ ] **Step 3: Verificação visual no dev**

- Sidebar direita não mostra mais toggle de IA
- Não há erros de console
- Toggle continua funcionando no header (Task 9)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/contact-detail.tsx
git commit -m "refactor(conversas): remove Valéria toggle from contact-detail (moved to header)"
```

---

### Task 12: Atualizar `message-bubble.tsx` e `day-separator.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`
- Modify: `frontend/src/components/conversas/day-separator.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`** (OBRIGATÓRIO)

- [ ] **Step 2: Em `message-bubble.tsx`**

Adicionar import:
```tsx
import { formatTimeOnly } from "@/lib/datetime";
```

Localizar a função `formatTime` interna (ou chamada `format(...)` ad-hoc) e substituir todas as chamadas por `formatTimeOnly(message.created_at)`. Remover a função interna se ficar órfã.

Garantir que o timestamp da bolha tem `text-xs text-stone-500` (ou equivalente warm-neutral do design system) — se hoje tem `text-white/50` ou cor fria, ajustar.

- [ ] **Step 3: Em `day-separator.tsx`**

Adicionar import:
```tsx
import { formatDayLabel } from "@/lib/datetime";
```

Substituir a função interna `formatDayLabel` (se existir com mesmo nome) ou qualquer formatação ad-hoc por chamada ao novo helper. Remover lógica duplicada.

- [ ] **Step 4: Verificação visual no dev**

- Bolhas mostram timestamps em "HH:mm" consistente
- Separadores: "Hoje" / "Ontem" / "quarta-feira" / "12 de março"
- Cores warm, contraste legível

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx frontend/src/components/conversas/day-separator.tsx
git commit -m "refactor(conversas): use unified datetime helpers in message-bubble and day-separator"
```

---

### Task 13: Atualizar `window-reactivate-panel.tsx`

**Files:**
- Modify: `frontend/src/components/conversas/window-reactivate-panel.tsx`

- [ ] **Step 1: Invocar skill `frontend-design`** (OBRIGATÓRIO)

- [ ] **Step 2: Trocar o cabeçalho do painel pelo indicador unificado**

Identificar o header/topo do painel onde tem indicador atual (texto "Janela expirada" ou similar) e substituir por:

```tsx
import { WhatsappWindowIndicator } from "@/components/conversas/whatsapp-window-indicator";
// ...
<WhatsappWindowIndicator
  expiresAt={conversation.whatsapp_window_expires_at}
  variant="header"
/>
```

Manter o resto do painel (formulário de seleção de template, botões de envio, etc.) intacto.

- [ ] **Step 3: Verificação visual no dev**

- Painel de reativação mostra indicador unificado consistente com o resto da página
- Lógica de envio de template segue funcionando

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/window-reactivate-panel.tsx
git commit -m "refactor(conversas): use unified window indicator in reactivate panel"
```

---

## Phase 5 — Final verification

### Task 14: Smoke test completo + checklist

**Files:** nenhum

- [ ] **Step 1: Subir ambiente dev completo**

Via VS Code task: `Run All Dev (CRM & Backend)`. Verificar que backend e frontend sobem sem erro.

- [ ] **Step 2: Checklist visual e funcional na página `/conversas`**

Abrir `http://localhost:3000/conversas` (ou porta do projeto). Para cada item, marcar [PASS] / [FAIL]:

- [ ] Lista de conversas carrega
- [ ] Card sem unread: nome `font-semibold`, sem badge laranja
- [ ] Card com unread > 0: nome `font-bold`, badge laranja com contador correto, animação pulse
- [ ] Card com unread > 9: badge mostra "9+"
- [ ] Click em card abre conversa, badge zera após request `mark-read`
- [ ] Card selecionado: borda esquerda laranja 3px, fundo warm leve, texto stone preto, legível
- [ ] Card hover: fundo stone-50
- [ ] Card focus (keyboard tab): ring laranja visível
- [ ] Timestamp do card: formato esperado (`agora` / `5min` / `14:30` / `Ontem` / `qua` / `12/03/2025`)
- [ ] Indicador compact 24h no card: dot colorido conforme estado
- [ ] ChatHeader: toggle Valéria pill laranja quando ativa, cinza quando pausada
- [ ] Click no toggle Valéria: muda estado, sem race, sem flicker
- [ ] ChatHeader: indicador header com pill warm + tooltip educativo ao hover
- [ ] ChatView: banner expired aparece somente em conversa com janela passada
- [ ] MessageList: timestamps em `HH:mm` consistente, separadores `Hoje`/`Ontem`/etc.
- [ ] Sidebar direita (contact-detail): SEM toggle Valéria
- [ ] Painel de reativação: usa indicador unificado no topo
- [ ] Envio de mensagem inbound de número de teste: badge surge na lista, contador incrementa por mensagem
- [ ] Reabertura da mesma conversa: badge zera novamente
- [ ] Console do browser: sem erros não relacionados

- [ ] **Step 3: Validar tipos e build**

```bash
cd frontend && npm run type-check 2>&1 | tail -20
cd frontend && npm run build 2>&1 | tail -20
```

Esperado: 0 erros novos, build passa.

- [ ] **Step 4: Confirmação ao usuário**

PARAR e reportar o estado ao usuário com:
- Lista de checks PASS/FAIL
- Screenshots se possível (ou descrição textual)
- Aguardar autorização expressa para `git push origin feat/conversas-ux-redesign-v2:master` (regra do CLAUDE.md)

⚠️ **NÃO fazer push automático.** Conforme `CLAUDE.md`: o usuário precisa testar em dev e dar autorização expressa para push.

---

## Self-Review Checklist (writing-plans skill)

**1. Spec coverage:**
- ✅ R1 (unread_count + badge): Tasks 1, 2, 3, 4, 5, 8
- ✅ R6+R7 (datetime único): Tasks 6, 8, 12
- ✅ R3 (WhatsappWindowIndicator unificado): Tasks 7, 8, 9, 10, 13
- ✅ R2 (toggle Valéria no header): Tasks 9, 11
- ✅ R5 (card selecionado redesenhado): Task 8
- ✅ R7 (3 níveis tipográficos): Task 8

**2. Placeholder scan:** todos os steps de código têm código completo ou rationale claro com paths/commands. Steps que delegam decisão local ao agent (ex: encontrar fonte de dados em chat-list — Supabase direto vs backend) explicitam exatamente o que inspecionar.

**3. Type consistency:** `Conversation.unread_count: number`, `Conversation.whatsapp_window_expires_at: string | null` — usados consistentemente em backend service, payloads, types.ts e componentes.

---

## Execution Order

**Sequencial (foundation):** Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7

**Paralelizável (após Task 7):** Tasks 8, 9, 10, 11, 12, 13 podem rodar em subagents paralelos — não compartilham state.

**Final:** Task 14 (verificação manual completa).

**Push para master:** apenas após autorização expressa do usuário (CLAUDE.md).
