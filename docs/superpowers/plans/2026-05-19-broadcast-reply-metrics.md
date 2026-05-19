# Broadcast Reply Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **FRONTEND RULE:** Any task that touches frontend files MUST invoke the `superpowers:frontend-design` skill before writing any code.

**Goal:** Rastrear `first_replied_at` por lead disparado e expor métricas agregadas (taxa de resposta, tempo médio) na página de detalhe do disparo.

**Architecture:** Webhook hook (tempo real) + catch-up periódico no worker (resiliência). Métricas computadas via RPC Postgres sob demanda. Frontend exibe 2 novos cards e coluna "Respondeu em" na tabela de leads.

**Tech Stack:** FastAPI + supabase-py (backend), Next.js 15 App Router + Supabase JS v2 (frontend), PostgreSQL functions via RPC.

---

## File Map

| Arquivo | Ação |
|---------|------|
| `backend/migrations/20260519_broadcast_leads_first_replied_at.sql` | CREATE — coluna + índice |
| `backend/migrations/20260519_broadcast_reply_metrics_rpc.sql` | CREATE — função RPC Postgres |
| `backend/app/broadcast/service.py` | MODIFY — add `record_broadcast_reply()` |
| `backend/tests/test_broadcast_reply_metrics.py` | CREATE — testes das novas funções |
| `backend/app/buffer/processor.py` | MODIFY — hook após save_message |
| `backend/app/broadcast/worker.py` | MODIFY — add `reconcile_broadcast_replies()` + chamar no loop |
| `frontend/src/app/api/broadcasts/[id]/metrics/route.ts` | CREATE — GET endpoint que chama RPC |
| `frontend/src/lib/types.ts` | MODIFY — add `BroadcastMetrics`, update `BroadcastLead` |
| `frontend/src/components/campaigns/broadcast-detail.tsx` | MODIFY — fetch metrics, cards, coluna |

---

## Task 1: Migrations SQL (rodar manualmente no Supabase SQL Editor)

**Files:**
- Create: `backend/migrations/20260519_broadcast_leads_first_replied_at.sql`
- Create: `backend/migrations/20260519_broadcast_reply_metrics_rpc.sql`

- [ ] **Step 1: Criar arquivo da migration da coluna**

Conteúdo exato do arquivo `backend/migrations/20260519_broadcast_leads_first_replied_at.sql`:

```sql
-- Rastreia quando o lead respondeu ao disparo pela primeira vez (dentro da janela de 48h)
ALTER TABLE broadcast_leads
  ADD COLUMN IF NOT EXISTS first_replied_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_replied
  ON broadcast_leads(broadcast_id, first_replied_at)
  WHERE first_replied_at IS NOT NULL;
```

- [ ] **Step 2: Criar arquivo da migration do RPC**

Conteúdo exato do arquivo `backend/migrations/20260519_broadcast_reply_metrics_rpc.sql`:

```sql
CREATE OR REPLACE FUNCTION get_broadcast_reply_metrics(p_broadcast_id uuid)
RETURNS TABLE(
  replied_count     bigint,
  reply_rate        numeric,
  avg_reply_secs    numeric,
  median_reply_secs numeric
)
LANGUAGE sql STABLE AS $$
  SELECT
    COUNT(*) FILTER (WHERE first_replied_at IS NOT NULL)
      AS replied_count,
    ROUND(
      COUNT(*) FILTER (WHERE first_replied_at IS NOT NULL)::numeric
      / NULLIF(COUNT(*) FILTER (WHERE status IN ('sent','delivered')), 0) * 100,
      1
    ) AS reply_rate,
    ROUND(
      AVG(EXTRACT(EPOCH FROM (first_replied_at - sent_at)))
        FILTER (WHERE first_replied_at IS NOT NULL),
      0
    ) AS avg_reply_secs,
    ROUND(
      PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (first_replied_at - sent_at))
      ) FILTER (WHERE first_replied_at IS NOT NULL),
      0
    ) AS median_reply_secs
  FROM broadcast_leads
  WHERE broadcast_id = p_broadcast_id
    AND status IN ('sent', 'delivered');
$$;
```

- [ ] **Step 3: Rodar ambas as SQLs no Supabase SQL Editor do projeto**

Execute a SQL do Step 1 e depois a SQL do Step 2 no Supabase dashboard.
Verifique: `broadcast_leads` deve ter coluna `first_replied_at`. A função `get_broadcast_reply_metrics` deve aparecer em Database → Functions.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/20260519_broadcast_leads_first_replied_at.sql \
        backend/migrations/20260519_broadcast_reply_metrics_rpc.sql
git commit -m "chore: migrations broadcast reply metrics (run in Supabase)"
```

---

## Task 2: Backend — `record_broadcast_reply()` no service + testes

**Files:**
- Modify: `backend/app/broadcast/service.py`
- Create: `backend/tests/test_broadcast_reply_metrics.py`

- [ ] **Step 1: Ler o estado atual de `backend/app/broadcast/service.py`**

Verificar os imports existentes e o final do arquivo para saber onde adicionar.

- [ ] **Step 2: Escrever o teste que falha primeiro**

Criar `backend/tests/test_broadcast_reply_metrics.py`:

```python
"""Tests for broadcast reply tracking."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


# ─── Helpers ────────────────────────────────────────────────────────────────

def _reply_sb_with_match():
    """Mock: SELECT retorna um broadcast_lead pendente."""
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .is_.return_value
        .gte.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = [{"id": "bl-uuid-123"}]
    return mock


def _reply_sb_no_match():
    """Mock: SELECT não encontra broadcast_lead na janela."""
    mock = MagicMock()
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .is_.return_value
        .gte.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = []
    return mock


# ─── record_broadcast_reply ──────────────────────────────────────────────────

def test_record_reply_updates_first_replied_at_when_lead_found():
    """Quando há broadcast_lead dentro da janela de 48h, deve setar first_replied_at."""
    mock_sb = _reply_sb_with_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    update_call = mock_sb.table.return_value.update.call_args
    assert update_call is not None, "update() deve ter sido chamado"
    payload = update_call[0][0]
    assert "first_replied_at" in payload, "Payload do update deve ter first_replied_at"


def test_record_reply_no_op_when_no_broadcast_lead_found():
    """Se nenhum broadcast_lead ativo for encontrado, não deve chamar update()."""
    mock_sb = _reply_sb_no_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    mock_sb.table.return_value.update.assert_not_called()


def test_record_reply_queries_only_sent_or_delivered_leads():
    """A query deve filtrar status IN ('sent', 'delivered') — não 'pending' ou 'failed'."""
    mock_sb = _reply_sb_no_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    # Verificar que .in_() foi chamado com os status corretos
    in_call = mock_sb.table.return_value.select.return_value.eq.return_value.in_.call_args
    assert in_call is not None
    statuses = in_call[0][1]
    assert set(statuses) == {"sent", "delivered"}


def test_record_reply_only_updates_null_first_replied_at():
    """A query deve filtrar first_replied_at IS NULL — não deve sobrescrever resposta já gravada."""
    mock_sb = _reply_sb_no_match()

    with patch("app.broadcast.service.get_supabase", return_value=mock_sb):
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply("lead-uuid")

    is_call = (
        mock_sb.table.return_value
        .select.return_value
        .eq.return_value
        .in_.return_value
        .is_.call_args
    )
    assert is_call is not None
    col, val = is_call[0]
    assert col == "first_replied_at"
    assert val == "null"


# ─── reconcile_broadcast_replies ─────────────────────────────────────────────

def _reconcile_sb(bl_rows, msg_rows):
    """Mock com table side-effect: broadcast_leads vs messages."""
    mock_bl = MagicMock()
    mock_msg = MagicMock()

    # SELECT pending broadcast_leads
    (
        mock_bl.select.return_value
        .in_.return_value
        .is_.return_value
        .gte.return_value
        .lte.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = bl_rows

    # SELECT messages
    (
        mock_msg.select.return_value
        .eq.return_value
        .eq.return_value
        .gt.return_value
        .lte.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
        .data
    ) = msg_rows

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: mock_msg if name == "messages" else mock_bl
    return mock_sb, mock_bl, mock_msg


def test_reconcile_updates_first_replied_at_when_message_exists():
    """Leads com mensagem inbound dentro da janela devem ter first_replied_at preenchido."""
    now = datetime.now(timezone.utc)
    sent_at = (now - timedelta(hours=5)).isoformat()
    msg_created_at = (now - timedelta(hours=4)).isoformat()

    bl = {"id": "bl-uuid", "lead_id": "lead-uuid", "sent_at": sent_at}
    message = {"id": "msg-uuid", "created_at": msg_created_at}

    mock_sb, mock_bl, _ = _reconcile_sb([bl], [message])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    update_call = mock_bl.update.call_args
    assert update_call is not None, "update() deve ter sido chamado para o lead com mensagem"
    payload = update_call[0][0]
    assert payload["first_replied_at"] == msg_created_at


def test_reconcile_skips_leads_without_message():
    """Leads sem mensagem inbound na janela não devem ser atualizados."""
    now = datetime.now(timezone.utc)
    sent_at = (now - timedelta(hours=5)).isoformat()
    bl = {"id": "bl-uuid", "lead_id": "lead-uuid", "sent_at": sent_at}

    mock_sb, mock_bl, _ = _reconcile_sb([bl], [])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    mock_bl.update.assert_not_called()


def test_reconcile_no_op_when_no_pending_leads():
    """Quando não há leads pendentes de reconciliação, não deve fazer queries de messages."""
    mock_sb, _, mock_msg = _reconcile_sb([], [])

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        from app.broadcast.worker import reconcile_broadcast_replies
        reconcile_broadcast_replies()

    mock_msg.select.assert_not_called()
```

- [ ] **Step 3: Rodar testes e confirmar que todos falham**

```bash
cd backend
python -m pytest tests/test_broadcast_reply_metrics.py -v
```

Esperado: `ImportError` ou `AttributeError` — funções ainda não existem.

- [ ] **Step 4: Implementar `record_broadcast_reply` em `backend/app/broadcast/service.py`**

Adicionar no início do arquivo (após os imports existentes):

```python
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)
```

Adicionar ao final do arquivo:

```python
def record_broadcast_reply(lead_id: str) -> None:
    """Marca o broadcast_lead mais recente deste lead como respondido (janela de 48h).

    Idempotente: se já tiver first_replied_at preenchido, a query não retorna
    nenhuma linha e nenhuma atualização é feita.
    """
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    result = (
        sb.table("broadcast_leads")
        .select("id")
        .eq("lead_id", lead_id)
        .in_("status", ["sent", "delivered"])
        .is_("first_replied_at", "null")
        .gte("sent_at", cutoff)
        .order("sent_at", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        bl_id = result.data[0]["id"]
        sb.table("broadcast_leads").update({
            "first_replied_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bl_id).execute()
        logger.info(
            "[BROADCAST] Resposta registrada: lead=%s broadcast_lead=%s",
            lead_id, bl_id,
        )
    else:
        logger.debug(
            "[BROADCAST] Nenhum broadcast_lead ativo encontrado para resposta do lead=%s",
            lead_id,
        )
```

- [ ] **Step 5: Implementar `reconcile_broadcast_replies` em `backend/app/broadcast/worker.py`**

Adicionar a função antes de `run_worker()` (linha ~212):

```python
def reconcile_broadcast_replies() -> None:
    """Catch-up job: preenche first_replied_at para leads que responderam mas o webhook falhou.

    Varre broadcast_leads enviados nas últimas 48h (menos os 2min mais recentes
    para evitar corrida com o webhook). Limite de 200 leads por tick.
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    window_start = (now - timedelta(hours=48)).isoformat()
    window_end = (now - timedelta(minutes=2)).isoformat()

    pending = (
        sb.table("broadcast_leads")
        .select("id, lead_id, sent_at")
        .in_("status", ["sent", "delivered"])
        .is_("first_replied_at", "null")
        .gte("sent_at", window_start)
        .lte("sent_at", window_end)
        .limit(200)
        .execute()
    )
    if not pending.data:
        return

    reconciled = 0
    for bl in pending.data:
        sent_at_dt = datetime.fromisoformat(bl["sent_at"].replace("Z", "+00:00"))
        reply_window_end = (sent_at_dt + timedelta(hours=48)).isoformat()
        reply = (
            sb.table("messages")
            .select("id, created_at")
            .eq("lead_id", bl["lead_id"])
            .eq("role", "user")
            .gt("created_at", bl["sent_at"])
            .lte("created_at", reply_window_end)
            .order("created_at")
            .limit(1)
            .execute()
        )
        if reply.data:
            sb.table("broadcast_leads").update({
                "first_replied_at": reply.data[0]["created_at"],
            }).eq("id", bl["id"]).execute()
            reconciled += 1

    if reconciled:
        logger.info(
            "[BROADCAST] reconcile_broadcast_replies: %d leads atualizados",
            reconciled,
        )
```

- [ ] **Step 6: Chamar `reconcile_broadcast_replies` no loop principal de `run_worker()`**

Localizar a função `run_worker()` (linha ~212) e adicionar a chamada:

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
            await process_due_followups()
            reconcile_broadcast_replies()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)
```

- [ ] **Step 7: Rodar testes e confirmar que todos passam**

```bash
cd backend
python -m pytest tests/test_broadcast_reply_metrics.py -v
```

Esperado: todos os 8 testes PASS.

- [ ] **Step 8: Rodar suite completa para verificar que nada quebrou**

```bash
cd backend
python -m pytest tests/ -v
```

Esperado: todos os testes existentes continuam passando.

- [ ] **Step 9: Commit**

```bash
git add backend/app/broadcast/service.py \
        backend/app/broadcast/worker.py \
        backend/tests/test_broadcast_reply_metrics.py
git commit -m "feat(broadcast): record_broadcast_reply e reconcile_broadcast_replies"
```

---

## Task 3: Webhook hook — chamar `record_broadcast_reply` no processor

**Files:**
- Modify: `backend/app/buffer/processor.py` (linhas ~180–193)

Nenhum teste novo — o comportamento já é coberto pelos testes de `record_broadcast_reply`. O hook é intencionalmentefire-and-forget, envolto em `try/except`.

- [ ] **Step 1: Ler linhas 175–200 de `backend/app/buffer/processor.py`**

Confirmar que o bloco `save_message(... "user" ...)` está nas linhas ~181–192.

- [ ] **Step 2: Adicionar hook logo após o bloco `save_message`**

Inserir **após** o bloco `except` do `save_message` (após a linha `return` do abort), antes de "Track last inbound message time":

```python
    # Registrar resposta ao disparo se o lead tiver um broadcast_lead ativo
    try:
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply(lead["id"])
    except Exception as e:
        logger.warning("Failed to record broadcast reply for %s: %s", phone, e)
```

O bloco completo resultante nessa região deve ficar:

```python
    # Always save the incoming user message
    try:
        save_message(
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
        )
    except Exception as e:
        logger.error(f"Failed to save user message for {phone}: {e}", exc_info=True)
        # Abort: do not run agent without persistence — avoids unlogged AI responses
        return

    # Registrar resposta ao disparo se o lead tiver um broadcast_lead ativo
    try:
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply(lead["id"])
    except Exception as e:
        logger.warning("Failed to record broadcast reply for %s: %s", phone, e)

    # Track last inbound message time for WhatsApp 24h window enforcement
    try:
        sb = get_supabase()
        ...
```

- [ ] **Step 3: Rodar testes existentes para confirmar que o processor não quebrou**

```bash
cd backend
python -m pytest tests/ -v
```

Esperado: todos os testes passando.

- [ ] **Step 4: Commit**

```bash
git add backend/app/buffer/processor.py
git commit -m "feat(broadcast): registrar resposta ao disparo no processor de mensagens"
```

---

## Task 4: Frontend API — `GET /api/broadcasts/[id]/metrics`

> **REQUIRED:** Antes de escrever qualquer código nesta task, invoque a skill `superpowers:frontend-design`.

**Files:**
- Create: `frontend/src/app/api/broadcasts/[id]/metrics/route.ts`

- [ ] **Step 1: Criar o arquivo da rota**

Conteúdo completo de `frontend/src/app/api/broadcasts/[id]/metrics/route.ts`:

```typescript
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();

  const { data, error } = await supabase.rpc("get_broadcast_reply_metrics", {
    p_broadcast_id: id,
  });

  if (error) {
    console.error("[broadcast-metrics] RPC error:", error.message);
    return NextResponse.json(
      { replied_count: 0, reply_rate: 0, avg_reply_secs: null, median_reply_secs: null },
      { status: 200 }
    );
  }

  const row = Array.isArray(data) ? data[0] : data;
  return NextResponse.json({
    replied_count: Number(row?.replied_count ?? 0),
    reply_rate: Number(row?.reply_rate ?? 0),
    avg_reply_secs: row?.avg_reply_secs != null ? Number(row.avg_reply_secs) : null,
    median_reply_secs: row?.median_reply_secs != null ? Number(row.median_reply_secs) : null,
  });
}
```

- [ ] **Step 2: Confirmar que a rota funciona com `tsc --noEmit`**

```bash
cd frontend
npx tsc --noEmit
```

Esperado: sem erros TypeScript.

- [ ] **Step 3: Commit**

```bash
git add "frontend/src/app/api/broadcasts/[id]/metrics/route.ts"
git commit -m "feat(broadcast): rota API de métricas de resposta por disparo"
```

---

## Task 5: Frontend — types + broadcast-detail

> **REQUIRED:** Antes de escrever qualquer código nesta task, invoque a skill `superpowers:frontend-design`.

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/components/campaigns/broadcast-detail.tsx`

- [ ] **Step 1: Adicionar `BroadcastMetrics` e atualizar `BroadcastLead` em `frontend/src/lib/types.ts`**

Adicionar **antes** da interface `Cadence` (após `BroadcastLead`):

```typescript
export interface BroadcastMetrics {
  replied_count: number;
  reply_rate: number;        // 0–100
  avg_reply_secs: number | null;
  median_reply_secs: number | null;
}
```

Adicionar `first_replied_at` à interface `BroadcastLead` existente:

```typescript
export interface BroadcastLead {
  id: string;
  broadcast_id: string;
  lead_id: string;
  status: "pending" | "sent" | "failed" | "delivered";
  sent_at: string | null;
  error_message: string | null;
  deal_moved_at: string | null;
  first_replied_at: string | null;    // ← adicionar esta linha
  leads?: { id: string; name: string | null; phone: string };
}
```

- [ ] **Step 2: Atualizar `frontend/src/components/campaigns/broadcast-detail.tsx`**

Ler o arquivo completo antes de editar.

**2a — Adicionar import do tipo:**

```typescript
import type { Broadcast, BroadcastLead, BroadcastMetrics } from "@/lib/types";
```

**2b — Adicionar estado de métricas após `const [activeFilter, ...]`:**

```typescript
const [metrics, setMetrics] = useState<BroadcastMetrics | null>(null);
```

**2c — Atualizar o `useEffect` de fetch para incluir métricas:**

```typescript
useEffect(() => {
    Promise.all([
      fetch(`/api/broadcasts/${broadcastId}`).then((r) => r.json()),
      fetch(`/api/broadcasts/${broadcastId}/leads`).then((r) => r.json()),
      fetch(`/api/broadcasts/${broadcastId}/metrics`).then((r) => r.json()),
    ]).then(([broadcastData, leadsData, metricsData]) => {
      setBroadcast(broadcastData as Broadcast);
      setLeads(Array.isArray(leadsData) ? (leadsData as BroadcastLead[]) : []);
      setMetrics(metricsData as BroadcastMetrics);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [broadcastId]);
```

**2d — Adicionar helper `formatSeconds` antes do `return` do componente:**

```typescript
  const formatSeconds = (secs: number | null): string => {
    if (secs == null) return "—";
    if (secs < 60) return "< 1 min";
    if (secs < 3600) return `${Math.round(secs / 60)} min`;
    if (secs < 86400) {
      const h = Math.floor(secs / 3600);
      const m = Math.round((secs % 3600) / 60);
      return m > 0 ? `${h}h ${m}min` : `${h}h`;
    }
    const d = Math.floor(secs / 86400);
    const h = Math.floor((secs % 86400) / 3600);
    return h > 0 ? `${d}d ${h}h` : `${d}d`;
  };
```

**2e — Adicionar 2 cards de métricas após os 5 cards existentes, condicionais a `broadcast.status !== "draft"`:**

Localizar o bloco `{/* Metric cards */}` e logo após o `</div>` que fecha a grade de 5 cards, adicionar:

```tsx
        {/* Reply metrics — only visible after dispatch started */}
        {broadcast.status !== "draft" && metrics && (
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-col items-center justify-center text-center">
              <span
                className="text-[36px] font-normal leading-none"
                style={{ color: "#111111", letterSpacing: "-0.5px" }}
              >
                {metrics.reply_rate > 0 ? `${metrics.reply_rate}%` : "—"}
              </span>
              <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mt-2">
                Taxa de Resposta
              </span>
              {metrics.replied_count > 0 && (
                <span className="text-[11px] text-[#7b7b78] mt-1">
                  {metrics.replied_count} lead{metrics.replied_count !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <div className="bg-white border border-[#dedbd6] rounded-[8px] p-4 flex flex-col items-center justify-center text-center">
              <span
                className="text-[36px] font-normal leading-none"
                style={{ color: "#111111", letterSpacing: "-0.5px" }}
              >
                {formatSeconds(metrics.avg_reply_secs)}
              </span>
              <span className="text-[10px] uppercase tracking-[0.6px] text-[#7b7b78] mt-2">
                Tempo Médio de Resposta
              </span>
              {metrics.median_reply_secs != null && (
                <span className="text-[11px] text-[#7b7b78] mt-1">
                  mediana {formatSeconds(metrics.median_reply_secs)}
                </span>
              )}
            </div>
          </div>
        )}
```

**2f — Adicionar coluna "Respondeu em" no header da tabela de leads:**

Localizar o array `["Nome", "Telefone", "Status", "Enviado em", ...]` e atualizar para:

```tsx
{["Nome", "Telefone", "Status", "Enviado em", "Respondeu em", ...(moveStageLabel ? ["Kanban"] : []), "Erro"].map((col) => (
```

**2g — Adicionar célula "Respondeu em" na linha de cada lead, após a célula de "Enviado em":**

Localizar a célula de `sent_at` na `<tr>` de cada lead e adicionar após ela:

```tsx
                      <td className="px-5 py-3 text-[13px] text-[#7b7b78]">
                        {lead.first_replied_at
                          ? new Date(lead.first_replied_at).toLocaleString("pt-BR", {
                              day: "2-digit",
                              month: "2-digit",
                              hour: "2-digit",
                              minute: "2-digit",
                            })
                          : <span className="text-[#dedbd6]">—</span>}
                      </td>
```

**2h — Atualizar `colSpan` do "Nenhum lead encontrado" para incluir a nova coluna:**

```tsx
<td colSpan={moveStageLabel ? 7 : 6} className="px-5 py-10 text-center text-[14px] text-[#7b7b78]">
```

- [ ] **Step 3: Verificar TypeScript**

```bash
cd frontend
npx tsc --noEmit
```

Esperado: zero erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts \
        frontend/src/components/campaigns/broadcast-detail.tsx
git commit -m "feat(broadcast): cards de taxa de resposta e coluna 'Respondeu em' no detalhe"
```

---

## Task 6: Verificação final

- [ ] **Step 1: Rodar todos os testes do backend**

```bash
cd backend
python -m pytest tests/ -v
```

Esperado: todos os testes passando (incluindo os 8 novos de `test_broadcast_reply_metrics.py`).

- [ ] **Step 2: Verificar TypeScript do frontend**

```bash
cd frontend
npx tsc --noEmit
```

Esperado: zero erros.

- [ ] **Step 3: Confirmar que as 2 migrations foram rodadas no Supabase**

No Supabase:
- `broadcast_leads` tem coluna `first_replied_at` (nullable TIMESTAMPTZ)
- Existe função `get_broadcast_reply_metrics` em Database → Functions

- [ ] **Step 4: Commit final**

```bash
git add -A
git commit -m "chore: verificação final broadcast reply metrics" --allow-empty
```
