# Cadence Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND RULE:** Qualquer task que toque `frontend/` DEVE invocar a skill `frontend-design` antes de escrever código de componente.

**Goal:** Unificar o sistema de cadência num único pipeline (campaigns + grafo), deletar o legado, validar o modo teste SSE, e expandir os blocos com nós CRM-aware.

**Architecture:** Engine único em `app/automation/` opera sobre `campaigns`/`campaign_nodes`/`campaign_enrollments`. Frontend usa `cadence-flow-builder.tsx` como builder estilo n8n. Modo teste roda via SSE (`StreamingResponse` no FastAPI ↔ `EventSource` no browser via proxy Next).

**Tech Stack:** Python 3.12, FastAPI, Supabase Python client, React 18, TypeScript, Next.js 14 App Router, @xyflow/react, framer-motion

**Spec:** `docs/superpowers/specs/2026-05-22-cadence-rebuild-design.md`

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `supabase/migrations/20260522_cadence_unify_drop_legacy.sql` | CRIAR | Drop tabelas legadas, idempotência `channel_id`, coluna `last_assigned_index` |
| `backend/app/automation/engine.py` | MODIFICAR | Adicionar action_types `mark_deal_won/lost`, `move_deal_stage`, `add_note`, `assign_round_robin` |
| `backend/app/automation/triggers.py` | MODIFICAR | Adicionar `keyword_received` |
| `backend/app/automation/test_runner.py` | MODIFICAR | Suportar novos action_types em modo simulado |
| `backend/app/webhook/whatsapp.py` (ou equivalente) | MODIFICAR | Disparar `keyword_received` ao receber mensagem |
| `backend/app/main.py` | MODIFICAR | Remover import e include de `cadence_router` |
| `backend/app/cadence/` | DELETAR | Diretório inteiro |
| `backend/tests/test_automation_engine_actions.py` | CRIAR | Testes dos novos action_types |
| `backend/tests/test_automation_triggers_keyword.py` | CRIAR | Testes do `keyword_received` |
| `frontend/src/proxy.ts` | MODIFICAR | Adicionar `/api/automation/:path*` ao matcher |
| `frontend/src/app/api/automation/[...path]/route.ts` | CRIAR | Proxy GET/POST → FastAPI, com suporte a SSE |
| `frontend/src/app/api/campaigns/[id]/enrollments/route.ts` | CRIAR | Lista enrollments de uma campaign |
| `frontend/src/app/api/campaigns/[id]/enrollments/[enrollId]/route.ts` | CRIAR | PATCH/DELETE enrollment |
| `frontend/src/app/api/leads/[id]/campaign-enrollments/route.ts` | CRIAR | Lista campaigns de um lead |
| `frontend/src/lib/types.ts` | MODIFICAR | Adicionar tipos `CampaignEnrollment`; remover `Cadence`, `CadenceEnrollment`, `CadenceStep` |
| `frontend/src/components/campaigns/cadence-enrollments-table.tsx` | MODIFICAR | Apontar para novas rotas/tabelas |
| `frontend/src/components/campaigns/cadence-flow-builder.tsx` | MODIFICAR | Inspector com novos action_types e trigger_types + validação |
| `frontend/src/components/leads/lead-detail-modal.tsx` | MODIFICAR | Trocar `cadence_enrollments` por `campaign_enrollments` |
| `frontend/src/components/conversas/window-reactivate-panel.tsx` | MODIFICAR | Idem |
| `frontend/src/hooks/use-realtime-cadences.ts` | DELETAR | Legado |
| `frontend/src/components/campaigns/cadence-steps-table.tsx` | DELETAR | Legado |
| `frontend/src/app/api/cadences/` | DELETAR | Árvore inteira legada |
| `frontend/src/app/api/leads/[id]/cadence-enrollments/` | DELETAR | Legado |
| `frontend/src/app/(authenticated)/campanhas/[id]/page.tsx` | DELETAR | Página legada (substituída por `/cadencias/[id]`) |

---

## FASE 1 — Backend: Engine + novos action_types

### Task 1: Migration de cleanup do banco

**Files:**
- Create: `supabase/migrations/20260522_cadence_unify_drop_legacy.sql`

- [ ] **Step 1: Criar a migration**

```sql
-- supabase/migrations/20260522_cadence_unify_drop_legacy.sql
-- Unifica o sistema de cadência: drop do legado, garante colunas no novo.

-- 1. Idempotência: channel_id em campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS channel_id UUID REFERENCES channels(id) ON DELETE SET NULL;

-- 2. Estado do round-robin
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS last_assigned_index INT NOT NULL DEFAULT -1;

-- 3. Drop tabelas legadas (já esvaziadas pela migration 20260521_migrate_cadence_enrollments.sql)
DROP TABLE IF EXISTS cadence_enrollments CASCADE;
DROP TABLE IF EXISTS cadence_steps CASCADE;
DROP TABLE IF EXISTS cadences CASCADE;
```

- [ ] **Step 2: Executar no Supabase SQL Editor**

Abrir Supabase Dashboard → SQL Editor → colar e executar. Verificar:
- `campaigns` tem colunas `channel_id` e `last_assigned_index`
- Tabelas `cadences`, `cadence_steps`, `cadence_enrollments` não existem mais

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260522_cadence_unify_drop_legacy.sql
git commit -m "feat(cadence): unify migration — drop legacy tables, add channel_id + last_assigned_index"
```

---

### Task 2: Engine — `mark_deal_won` e `mark_deal_lost`

**Files:**
- Modify: `backend/app/automation/engine.py`
- Create: `backend/tests/test_automation_engine_actions.py`

**Contexto:** `_execute_action` em engine.py já tem `move_stage`, `add_tag` etc. Adicionar dois branches que pegam o último deal do lead e atualizam seu `stage_id`. O ID do stage "ganho" e "perdido" vem do config do nó (selecionado pelo Inspector).

- [ ] **Step 1: Escrever o teste**

```python
# backend/tests/test_automation_engine_actions.py
import pytest
from unittest.mock import patch, MagicMock
from app.automation.engine import _execute_action


def _mock_sb_with_deals(deal_id="d1"):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": deal_id, "lead_id": "lead1"}
    ]
    return sb


class TestMarkDealWon:
    def test_updates_latest_deal_to_won_stage(self):
        sb = _mock_sb_with_deals()
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "mark_deal_won", "stage_id": "stage-won"}}
            lead = {"id": "lead1", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        # Espera-se 2 chamadas: select para pegar o deal, update no deal
        sb.table.assert_any_call("deals")
        update_calls = [c for c in sb.table.return_value.update.call_args_list]
        assert any(call[0][0].get("stage_id") == "stage-won" for call in update_calls)


class TestMarkDealLost:
    def test_updates_latest_deal_to_lost_stage(self):
        sb = _mock_sb_with_deals()
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "mark_deal_lost", "stage_id": "stage-lost"}}
            lead = {"id": "lead1", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        update_calls = [c for c in sb.table.return_value.update.call_args_list]
        assert any(call[0][0].get("stage_id") == "stage-lost" for call in update_calls)


class TestMarkDealNoDeal:
    def test_noop_when_no_deal_exists(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "mark_deal_won", "stage_id": "stage-won"}}
            lead = {"id": "lead1", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        # Não deve chamar update se não houver deal
        sb.table.return_value.update.assert_not_called()
```

- [ ] **Step 2: Rodar o teste para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_engine_actions.py -v
```

Esperado: FAIL — action_types desconhecidos no engine.

- [ ] **Step 3: Implementar os branches em `_execute_action`**

Em `backend/app/automation/engine.py`, dentro da função `_execute_action`, adicionar após o branch `move_stage` (e antes do `activate_agent`):

```python
    elif action_type in ("mark_deal_won", "mark_deal_lost", "move_deal_stage"):
        stage_id = cfg.get("stage_id")
        if not stage_id:
            return
        rows = (
            sb.table("deals")
            .select("id")
            .eq("lead_id", enrollment["lead_id"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            sb.table("deals").update({"stage_id": stage_id}).eq("id", rows[0]["id"]).execute()
```

- [ ] **Step 4: Rodar testes — devem passar**

```bash
cd backend && python -m pytest tests/test_automation_engine_actions.py -v
```

Esperado: 3 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_automation_engine_actions.py
git commit -m "feat(automation): add mark_deal_won, mark_deal_lost, move_deal_stage actions"
```

---

### Task 3: Engine — `add_note`

**Files:**
- Modify: `backend/app/automation/engine.py`
- Modify: `backend/tests/test_automation_engine_actions.py`

**Contexto:** Insere uma linha em `lead_notes` (tabela existe — referenciada em `LeadNote` type). Suporta `{{lead.name}}` no template.

- [ ] **Step 1: Adicionar teste**

Adicionar ao final de `backend/tests/test_automation_engine_actions.py`:

```python
class TestAddNote:
    def test_inserts_note_with_substituted_text(self):
        sb = MagicMock()
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1"}
            node = {"config": {"action_type": "add_note", "note_template": "Cliente {{lead.name}} respondeu"}}
            lead = {"id": "lead1", "name": "João", "phone": "5511999"}
            _execute_action(enrollment, node, lead)
        sb.table.assert_any_call("lead_notes")
        insert_call = sb.table.return_value.insert.call_args
        assert insert_call is not None
        payload = insert_call[0][0]
        assert payload["lead_id"] == "lead1"
        assert "João" in payload["content"]
```

- [ ] **Step 2: Rodar — deve falhar**

```bash
cd backend && python -m pytest tests/test_automation_engine_actions.py::TestAddNote -v
```

- [ ] **Step 3: Implementar `add_note`**

No `_execute_action` em `engine.py`, adicionar após o branch `assign_to`:

```python
    elif action_type == "add_note":
        template = cfg.get("note_template") or ""
        if template:
            content = substitute_variables(template, lead, enrollment)
            sb.table("lead_notes").insert({
                "lead_id": enrollment["lead_id"],
                "content": content,
            }).execute()
```

- [ ] **Step 4: Rodar — deve passar**

```bash
cd backend && python -m pytest tests/test_automation_engine_actions.py::TestAddNote -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_automation_engine_actions.py
git commit -m "feat(automation): add add_note action with variable substitution"
```

---

### Task 4: Engine — `assign_round_robin`

**Files:**
- Modify: `backend/app/automation/engine.py`
- Modify: `backend/tests/test_automation_engine_actions.py`

**Contexto:** `cfg.user_ids[]` é a lista de vendedores. `last_assigned_index` é coluna em `campaigns` (criada na migration). O próximo índice = `(last + 1) % len(user_ids)`. Atualiza `leads.assigned_to` e incrementa `campaigns.last_assigned_index`.

- [ ] **Step 1: Adicionar teste**

```python
class TestAssignRoundRobin:
    def test_assigns_next_user_in_list_and_increments_index(self):
        sb = MagicMock()
        # Mock pegar a campaign para ler last_assigned_index
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "camp1",
            "last_assigned_index": 0,
        }
        with patch("app.automation.engine.get_supabase", return_value=sb):
            enrollment = {"id": "e1", "lead_id": "lead1", "campaign_id": "camp1"}
            node = {"config": {
                "action_type": "assign_round_robin",
                "user_ids": ["u1", "u2", "u3"],
            }}
            lead = {"id": "lead1"}
            _execute_action(enrollment, node, lead)
        # Espera: lead atualizado com assigned_to=u2 (índice 1), campaign atualizada com last_assigned_index=1
        sb.table.assert_any_call("leads")
        sb.table.assert_any_call("campaigns")
```

- [ ] **Step 2: Rodar — deve falhar**

```bash
cd backend && python -m pytest tests/test_automation_engine_actions.py::TestAssignRoundRobin -v
```

- [ ] **Step 3: Implementar**

Adicionar ao `_execute_action`:

```python
    elif action_type == "assign_round_robin":
        user_ids = cfg.get("user_ids") or []
        campaign_id = enrollment.get("campaign_id")
        if not user_ids or not campaign_id:
            return
        camp = (
            sb.table("campaigns")
            .select("last_assigned_index")
            .eq("id", campaign_id)
            .single()
            .execute()
            .data
        ) or {}
        last_idx = camp.get("last_assigned_index", -1)
        next_idx = (last_idx + 1) % len(user_ids)
        next_user = user_ids[next_idx]
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], assigned_to=next_user)
        sb.table("campaigns").update({"last_assigned_index": next_idx}).eq("id", campaign_id).execute()
```

- [ ] **Step 4: Rodar — deve passar**

```bash
cd backend && python -m pytest tests/test_automation_engine_actions.py::TestAssignRoundRobin -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_automation_engine_actions.py
git commit -m "feat(automation): add assign_round_robin action"
```

---

### Task 5: Trigger novo — `keyword_received`

**Files:**
- Modify: `backend/app/automation/triggers.py`
- Create: `backend/tests/test_automation_triggers_keyword.py`

**Contexto:** Quando uma mensagem do tipo `user` é salva (vinda do webhook), se houver uma campaign ativa com trigger `keyword_received` configurada, e a mensagem contiver qualquer keyword (case-insensitive), criar enrollment para esse lead.

- [ ] **Step 1: Ler `triggers.py` atual para entender padrão**

```bash
cat backend/app/automation/triggers.py | head -100
```

Localizar `fire_trigger(event_type, lead_id, data)` e identificar como outros triggers se ramificam.

- [ ] **Step 2: Escrever teste**

```python
# backend/tests/test_automation_triggers_keyword.py
import pytest
from unittest.mock import patch, MagicMock
from app.automation.triggers import _match_keyword_campaigns


class TestKeywordMatching:
    def test_matches_when_message_contains_keyword(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "node1",
                "campaign_id": "camp1",
                "config": {"trigger_type": "keyword_received", "keywords": ["preço", "valor"]},
            }
        ]
        with patch("app.automation.triggers.get_supabase", return_value=sb):
            result = _match_keyword_campaigns(message_body="Qual o PREÇO disso?")
        assert "camp1" in result

    def test_no_match_when_keyword_absent(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "node1",
                "campaign_id": "camp1",
                "config": {"trigger_type": "keyword_received", "keywords": ["preço"]},
            }
        ]
        with patch("app.automation.triggers.get_supabase", return_value=sb):
            result = _match_keyword_campaigns(message_body="Olá tudo bem")
        assert result == []
```

- [ ] **Step 3: Rodar — deve falhar**

```bash
cd backend && python -m pytest tests/test_automation_triggers_keyword.py -v
```

- [ ] **Step 4: Implementar `_match_keyword_campaigns` em `triggers.py`**

Adicionar ao final de `backend/app/automation/triggers.py`:

```python
def _match_keyword_campaigns(message_body: str) -> list[str]:
    """Retorna campaign_ids cujo nó trigger keyword_received bate com a mensagem."""
    sb = get_supabase()
    rows = (
        sb.table("campaign_nodes")
        .select("campaign_id, config")
        .eq("type", "trigger")
        .execute()
        .data
    ) or []
    body_lower = message_body.lower()
    matches = []
    for row in rows:
        cfg = row.get("config") or {}
        if cfg.get("trigger_type") != "keyword_received":
            continue
        keywords = cfg.get("keywords") or []
        if any(k.lower() in body_lower for k in keywords if k):
            matches.append(row["campaign_id"])
    return matches
```

E no `fire_trigger`, adicionar branch:

```python
    if event_type == "message_received":
        message_body = data.get("body") or ""
        campaign_ids = _match_keyword_campaigns(message_body)
        for cid in campaign_ids:
            _create_enrollment_if_eligible(cid, lead_id)
        return
```

(Se `_create_enrollment_if_eligible` não existir com esse nome, usar o helper interno que já cria enrollments em outros branches — copiar o padrão.)

- [ ] **Step 5: Rodar — deve passar**

```bash
cd backend && python -m pytest tests/test_automation_triggers_keyword.py -v
```

- [ ] **Step 6: Acionar `message_received` ao salvar mensagem do user**

Localizar onde mensagens de usuário são salvas (provavelmente em `backend/app/webhook/whatsapp.py` ou `backend/app/leads/service.py:save_message`). Após salvar uma mensagem com `role == "user"`, fazer:

```python
from app.automation.triggers import fire_trigger
fire_trigger("message_received", lead_id=lead_id, data={"body": content})
```

(Tornar fire-and-forget se a infra existir; senão chamada direta.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/automation/triggers.py backend/tests/test_automation_triggers_keyword.py backend/app/webhook/
git commit -m "feat(automation): add keyword_received trigger fired on user messages"
```

---

### Task 6: test_runner — suportar novos action_types em modo simulado

**Files:**
- Modify: `backend/app/automation/test_runner.py`

**Contexto:** O test_runner já tem branch genérico para `action` que apenas loga. Vamos refinar para mostrar logs específicos por action_type sem executar de verdade.

- [ ] **Step 1: Modificar branch `action` em `_execute_test_node`**

Em `backend/app/automation/test_runner.py`, substituir o branch `if node_type == "action":` por:

```python
    if node_type == "action":
        action_type = cfg.get("action_type", "")
        action_labels = {
            "move_stage": "Mover estágio do lead",
            "mark_deal_won": "Marcar deal como ganho",
            "mark_deal_lost": "Marcar deal como perdido",
            "move_deal_stage": "Mover deal de estágio",
            "activate_agent": "Ativar agente AI",
            "deactivate_agent": "Desativar agente AI",
            "add_tag": "Adicionar tag",
            "remove_tag": "Remover tag",
            "create_deal": "Criar deal",
            "assign_to": "Atribuir vendedor",
            "assign_round_robin": "Atribuir via round-robin",
            "add_note": "Adicionar nota",
        }
        label = action_labels.get(action_type, action_type or "ação")
        return f"[Simulado] {label} — sem efeito real no modo teste", None
```

- [ ] **Step 2: Atualizar test do test_runner se existir**

```bash
cd backend && python -m pytest tests/test_automation_test_runner.py -v
```

Esperado: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/app/automation/test_runner.py
git commit -m "feat(automation): refine test_runner action logs per action_type"
```

---

## FASE 2 — Backend: Cleanup do legado

### Task 7: Remover `cadence_router` de `main.py`

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Editar `main.py`**

Remover linha `93`:
```python
from app.cadence.router import router as cadence_router
```

Remover linha `110`:
```python
app.include_router(cadence_router)
```

- [ ] **Step 2: Verificar que o backend ainda compila**

```bash
cd backend && python -m compileall app/main.py
```

Esperado: sem erros.

- [ ] **Step 3: Buscar outros usos de `app.cadence.*`**

```bash
cd backend && grep -rn "from app.cadence" app/ tests/ || true
```

Se houver outros imports, removê-los ou substituir por equivalentes em `app/automation/` ou `app/campaigns/`.

- [ ] **Step 4: Deletar diretório `backend/app/cadence/`**

```bash
rm -rf backend/app/cadence/
```

- [ ] **Step 5: Rodar todos os testes do backend para garantir que nada quebrou**

```bash
cd backend && python -m pytest tests/ -v 2>&1 | tail -30
```

Esperado: todos PASS (testes específicos de cadence legacy devem ter sido deletados junto se existiam).

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py
git add -A backend/app/cadence/ 2>/dev/null || true
git commit -m "chore(cadence): remove legacy app/cadence/ module and router"
```

---

## FASE 3 — Frontend: Proxy SSE + rotas novas

### Task 8: Proxy `/api/automation/:path*` no Next

**Files:**
- Modify: `frontend/src/proxy.ts`
- Create: `frontend/src/app/api/automation/[...path]/route.ts`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar matcher `/api/automation/:path*` em `proxy.ts`**

No `frontend/src/proxy.ts`, no array `config.matcher`, adicionar uma nova entrada após `"/api/cadences/:path*"` (que será removida depois):

```typescript
    "/api/automation/:path*",
```

- [ ] **Step 3: Criar route handler de proxy SSE**

Criar `frontend/src/app/api/automation/[...path]/route.ts`:

```typescript
import { NextRequest } from "next/server";

const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || process.env.FASTAPI_URL || "http://api:8000";

async function forward(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const url = `${FASTAPI_URL}/api/automation/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("connection");

  const init: RequestInit = {
    method: req.method,
    headers,
    body: ["GET", "HEAD"].includes(req.method) ? undefined : await req.text(),
    // @ts-expect-error duplex not in TS lib yet
    duplex: "half",
  };

  const upstream = await fetch(url, init);

  // Stream-friendly response (SSE)
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("Content-Type") || "application/json",
      "Cache-Control": "no-cache",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, ctx);
}
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/proxy.ts frontend/src/app/api/automation/
git commit -m "feat(frontend): add /api/automation proxy with SSE streaming support"
```

---

### Task 9: Rotas novas de enrollments

**Files:**
- Create: `frontend/src/app/api/campaigns/[id]/enrollments/route.ts`
- Create: `frontend/src/app/api/campaigns/[id]/enrollments/[enrollId]/route.ts`
- Create: `frontend/src/app/api/leads/[id]/campaign-enrollments/route.ts`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Criar `campaigns/[id]/enrollments/route.ts`**

```typescript
// frontend/src/app/api/campaigns/[id]/enrollments/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { APP_ENV } from "@/lib/env";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("campaign_enrollments")
    .select(
      "*, " +
      "leads:lead_id(id, name, phone, company, stage), " +
      "current_node:current_node_id(id, type, config)"
    )
    .eq("campaign_id", id)
    .eq("env_tag", APP_ENV)
    .order("enrolled_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
```

- [ ] **Step 3: Criar `campaigns/[id]/enrollments/[enrollId]/route.ts`**

```typescript
// frontend/src/app/api/campaigns/[id]/enrollments/[enrollId]/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const body = await req.json();
  const action = body.action as "pause" | "resume";
  const newStatus = action === "pause" ? "paused" : "active";
  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("campaign_enrollments")
    .update({ status: newStatus })
    .eq("id", enrollId)
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function DELETE(
  _req: NextRequest,
  { params }: { params: Promise<{ id: string; enrollId: string }> }
) {
  const { enrollId } = await params;
  const sb = await getServiceSupabase();
  const { error } = await sb.from("campaign_enrollments").delete().eq("id", enrollId);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
```

- [ ] **Step 4: Criar `leads/[id]/campaign-enrollments/route.ts`**

```typescript
// frontend/src/app/api/leads/[id]/campaign-enrollments/route.ts
import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const sb = await getServiceSupabase();
  const { data, error } = await sb
    .from("campaign_enrollments")
    .select("*, campaigns:campaign_id(id, name, status, created_at)")
    .eq("lead_id", id)
    .order("enrolled_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
```

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/api/campaigns/\[id\]/enrollments/ frontend/src/app/api/leads/\[id\]/campaign-enrollments/
git commit -m "feat(frontend): add campaign enrollments API routes (list, pause/resume, delete)"
```

---

### Task 10: Tipos novos em `lib/types.ts`

**Files:**
- Modify: `frontend/src/lib/types.ts`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar tipo `CampaignEnrollment`**

Em `frontend/src/lib/types.ts`, adicionar:

```typescript
export interface CampaignEnrollment {
  id: string;
  campaign_id: string;
  lead_id: string;
  current_node_id: string | null;
  status: "active" | "paused" | "completed" | "failed" | "removed";
  next_execute_at: string | null;
  enrolled_at: string;
  completed_at: string | null;
  retry_count: number;
  last_error: string | null;
  leads?: {
    id: string;
    name: string | null;
    phone: string;
    company: string | null;
    stage: string | null;
  } | null;
  current_node?: {
    id: string;
    type: string;
    config: Record<string, unknown>;
  } | null;
}
```

- [ ] **Step 3: Remover tipos legados**

Remover do mesmo arquivo, se existirem: `Cadence`, `CadenceEnrollment`, `CadenceStep`, e qualquer subtipo relacionado.

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: ERROS — vários arquivos ainda referenciam os tipos removidos. Anotar a lista para tasks subsequentes.

- [ ] **Step 5: Commit (sem fix dos erros ainda — eles serão resolvidos nas próximas tasks)**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(frontend): add CampaignEnrollment type, remove legacy Cadence types"
```

---

## FASE 4 — Frontend: Reescrita do painel de inscritos + cleanup

### Task 11: Reescrever `cadence-enrollments-table.tsx`

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-enrollments-table.tsx`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Reescrever o componente**

Substituir o conteúdo do arquivo por:

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";
import type { CampaignEnrollment } from "@/lib/types";

interface CampaignEnrollmentsTableProps {
  campaignId: string;
}

const STATUS_LABELS: Record<string, { style: string; label: string }> = {
  active:    { style: "bg-[#ff5600]/10 text-[#ff5600] border-[#ff5600]/20", label: "Ativo" },
  paused:    { style: "bg-[#fe4c02]/10 text-[#fe4c02] border-[#fe4c02]/20", label: "Pausado" },
  completed: { style: "bg-[#0bdf50]/10 text-[#0bdf50] border-[#0bdf50]/20", label: "Completo" },
  failed:    { style: "bg-[#c41c1c]/10 text-[#c41c1c] border-[#c41c1c]/20", label: "Falhou" },
  removed:   { style: "bg-[#f0ede8] text-[#7b7b78] border-[#dedbd6]", label: "Removido" },
};

function StatusBadge({ status }: { status: string }) {
  const entry = STATUS_LABELS[status] ?? STATUS_LABELS.active;
  return (
    <span className={`inline-flex items-center text-[10px] font-medium uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border ${entry.style}`}>
      {entry.label}
    </span>
  );
}

export function CampaignEnrollmentsTable({ campaignId }: CampaignEnrollmentsTableProps) {
  const [enrollments, setEnrollments] = useState<CampaignEnrollment[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const fetchEnrollments = useCallback(async () => {
    const res = await fetch(`/api/campaigns/${campaignId}/enrollments`);
    if (res.ok) {
      const data = await res.json();
      setEnrollments(Array.isArray(data) ? data : []);
    }
    setLoading(false);
  }, [campaignId]);

  useEffect(() => {
    fetchEnrollments();

    const supabase = createClient();
    const channel = supabase
      .channel(`campaign-enrollments-${campaignId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "campaign_enrollments", filter: `campaign_id=eq.${campaignId}` },
        () => fetchEnrollments()
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [campaignId, fetchEnrollments]);

  const handleAction = async (enrollId: string, action: "pause" | "resume" | "remove") => {
    if (action === "remove") {
      await fetch(`/api/campaigns/${campaignId}/enrollments/${enrollId}`, { method: "DELETE" });
    } else {
      await fetch(`/api/campaigns/${campaignId}/enrollments/${enrollId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
    }
    fetchEnrollments();
  };

  const filtered = enrollments.filter((e) => {
    if (filter !== "all" && e.status !== filter) return false;
    if (search) {
      const lead = e.leads;
      if (!lead) return false;
      const text = `${lead.name ?? ""} ${lead.phone} ${lead.company ?? ""}`.toLowerCase();
      if (!text.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const filters = ["all", "active", "paused", "completed", "failed"];

  if (loading) return <div className="py-8 text-center text-[#7b7b78] text-[14px]">Carregando...</div>;

  return (
    <div>
      <div className="bg-white border border-[#dedbd6] rounded-[8px] overflow-hidden">
        <div className="p-4 border-b border-[#dedbd6] bg-[#f7f5f1] flex gap-3 items-center">
          <input
            type="text"
            placeholder="Buscar lead..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-64"
          />
          <div className="flex gap-1">
            {filters.map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={filter === f
                  ? "bg-[#111111] text-white px-3 py-1.5 rounded-[4px] text-[13px]"
                  : "border border-[#dedbd6] text-[#7b7b78] px-3 py-1.5 rounded-[4px] text-[13px] hover:border-[#111111] hover:text-[#111111]"}
              >
                {f === "all" ? "Todos" : STATUS_LABELS[f]?.label ?? f}
              </button>
            ))}
          </div>
        </div>

        {filtered.length === 0 ? (
          <p className="text-[14px] text-[#7b7b78] text-center py-8">Nenhum lead nesta cadência</p>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#dedbd6] bg-[#f7f5f1]">
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Lead</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Status</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Nó atual</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Próxima execução</th>
                <th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Ações</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id} className="border-b border-[#dedbd6] hover:bg-[#faf9f6] transition-colors">
                  <td className="px-4 py-3">
                    <p className="text-[14px] font-medium text-[#111111]">{e.leads?.name ?? "—"}</p>
                    <p className="text-[12px] text-[#7b7b78]">{e.leads?.phone}</p>
                  </td>
                  <td className="px-4 py-3"><StatusBadge status={e.status} /></td>
                  <td className="px-4 py-3">
                    <span className="text-[13px] text-[#111111]">{e.current_node?.type ?? "—"}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-[13px] text-[#7b7b78]">
                      {e.next_execute_at
                        ? new Date(e.next_execute_at).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
                        : "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {e.status === "active" && (
                        <button onClick={() => handleAction(e.id, "pause")} className="text-[13px] text-[#7b7b78] hover:text-[#111111] transition-colors">Pausar</button>
                      )}
                      {e.status === "paused" && (
                        <button onClick={() => handleAction(e.id, "resume")} className="text-[13px] text-[#0bdf50] hover:text-[#0bdf50]/70 transition-colors">Retomar</button>
                      )}
                      <button onClick={() => handleAction(e.id, "remove")} className="text-[13px] text-[#c41c1c] hover:text-[#c41c1c]/70 transition-colors">Remover</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Atualizar consumidores do componente**

Buscar quem importa `CadenceEnrollmentsTable`:

```bash
cd frontend && grep -rn "CadenceEnrollmentsTable" src/ || true
```

Renomear chamadas para `CampaignEnrollmentsTable` e prop `cadenceId` → `campaignId`. **NOTA:** o componente foi exportado como `CampaignEnrollmentsTable` no novo arquivo. Manter o arquivo no mesmo path mas atualizar imports.

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/cadence-enrollments-table.tsx
git commit -m "feat(frontend): rewrite enrollments table to use campaign_enrollments"
```

---

### Task 12: Atualizar `lead-detail-modal.tsx` e `window-reactivate-panel.tsx`

**Files:**
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx`
- Modify: `frontend/src/components/conversas/window-reactivate-panel.tsx`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: `lead-detail-modal.tsx` — trocar tabela e nome de campos**

No `frontend/src/components/leads/lead-detail-modal.tsx`:

- Substituir `cadence_enrollments` → `campaign_enrollments` no `.from()`
- Substituir o select `"*, cadences(name, created_at, max_messages)"` por `"*, campaigns(id, name, created_at)"`
- Renomear todas as referências locais `cadence_name`, `cadence_created_at`, `cadences` para suas contrapartes `campaign_name`, `campaign_created_at`, `campaigns`
- Manter os case strings `cadence_enrolled` e `cadence_unenrolled` em `lead_events` (são eventos históricos, não mudam)

- [ ] **Step 3: `window-reactivate-panel.tsx` — trocar endpoint**

Buscar a chamada `/api/cadences/...` ou `cadence_enrollments` e trocar pelos equivalentes `campaign`. Se o componente lista cadências disponíveis para reativação, trocar para listar `campaigns` ativas.

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/leads/lead-detail-modal.tsx frontend/src/components/conversas/window-reactivate-panel.tsx
git commit -m "feat(frontend): point lead-detail-modal and reactivate-panel to campaign_enrollments"
```

---

### Task 13: Deletar arquivos do legado no frontend

**Files:**
- Delete: `frontend/src/hooks/use-realtime-cadences.ts`
- Delete: `frontend/src/components/campaigns/cadence-steps-table.tsx`
- Delete: `frontend/src/app/api/cadences/` (árvore)
- Delete: `frontend/src/app/api/leads/[id]/cadence-enrollments/`
- Delete: `frontend/src/app/(authenticated)/campanhas/[id]/page.tsx`
- Modify: `frontend/src/proxy.ts` (remover matcher legado)

- [ ] **Step 1: Confirmar que ninguém usa esses arquivos**

```bash
cd frontend && grep -rn "use-realtime-cadences\|cadence-steps-table\|/api/cadences\|/api/leads/.*cadence-enrollments" src/ --include="*.ts" --include="*.tsx" || true
```

Esperado: zero matches (após Tasks 11-12). Se houver matches, voltar e corrigir antes.

- [ ] **Step 2: Deletar arquivos**

```bash
rm -rf frontend/src/hooks/use-realtime-cadences.ts
rm -rf frontend/src/components/campaigns/cadence-steps-table.tsx
rm -rf frontend/src/app/api/cadences/
rm -rf frontend/src/app/api/leads/\[id\]/cadence-enrollments/
rm -rf "frontend/src/app/(authenticated)/campanhas/[id]/page.tsx"
```

- [ ] **Step 3: Remover matcher `/api/cadences/:path*` de `proxy.ts`**

Em `frontend/src/proxy.ts`, remover a linha:
```typescript
    "/api/cadences/:path*",
```

- [ ] **Step 4: Verificar TypeScript e build**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: limpo.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "chore(cadence): remove legacy cadence API routes, hooks, components"
```

---

## FASE 5 — Frontend: Inspector do builder com novos blocos

### Task 14: Builder — novos action_types no Inspector

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

**Contexto:** Adicionar entradas em `ACTION_LABELS` e `ACTION_ICONS`, opções no Inspector para `mark_deal_won`, `mark_deal_lost`, `move_deal_stage`, `add_note`, `assign_round_robin`.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Expandir `ACTION_LABELS` e `ACTION_ICONS`**

No topo do `cadence-flow-builder.tsx`, atualizar:

```typescript
const ACTION_LABELS: Record<string, string> = {
  move_stage: "Mover stage do lead",
  activate_agent: "Ativar agente",
  deactivate_agent: "Desativar agente",
  add_tag: "Adicionar tag",
  remove_tag: "Remover tag",
  mark_deal_won: "Marcar deal como ganho",
  mark_deal_lost: "Marcar deal como perdido",
  move_deal_stage: "Mover deal de estágio",
  add_note: "Adicionar nota",
  assign_round_robin: "Atribuir (round-robin)",
};

const ACTION_ICONS: Record<string, string> = {
  move_stage: "📋",
  activate_agent: "🤖",
  deactivate_agent: "🤖",
  add_tag: "🏷️",
  remove_tag: "🏷️",
  mark_deal_won: "🏆",
  mark_deal_lost: "💔",
  move_deal_stage: "🔀",
  add_note: "📝",
  assign_round_robin: "🎯",
};
```

- [ ] **Step 3: Adicionar opções no quick-add menu se houver lista de action_types**

Buscar `QUICK_ADD_ITEMS` no arquivo. Se há entradas para action subtypes, adicionar novas:

```typescript
{ type: "action", subtype: "mark_deal_won", icon: "🏆", label: "Marcar deal ganho" },
{ type: "action", subtype: "mark_deal_lost", icon: "💔", label: "Marcar deal perdido" },
{ type: "action", subtype: "add_note", icon: "📝", label: "Adicionar nota" },
{ type: "action", subtype: "assign_round_robin", icon: "🎯", label: "Atribuir round-robin" },
```

- [ ] **Step 4: Expandir Inspector para configurar cada novo action_type**

Localizar o bloco do Inspector que renderiza configuração para `node.type === "action"`. Atualmente provavelmente só tem `move_stage` e similares. Substituir o switch interno por:

```tsx
{node.type === "action" && (() => {
  const at = c.action_type as string;
  return (
    <>
      <div style={field}>
        <label style={label}>Tipo de ação</label>
        <select
          style={{ ...input, appearance: "none" } as React.CSSProperties}
          value={at ?? ""}
          onChange={(e) => set("action_type", e.target.value)}
        >
          {Object.entries(ACTION_LABELS).map(([key, val]) => (
            <option key={key} value={key}>{val}</option>
          ))}
        </select>
      </div>

      {(at === "move_stage") && (
        <div style={field}>
          <label style={label}>Estágio do lead</label>
          <select
            style={{ ...input, appearance: "none" } as React.CSSProperties}
            value={(c.stage_id as string) ?? ""}
            onChange={(e) => set("stage_id", e.target.value)}
          >
            <option value="">— selecione —</option>
            {data.allStages.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
      )}

      {(at === "mark_deal_won" || at === "mark_deal_lost" || at === "move_deal_stage") && (
        <div style={field}>
          <label style={label}>Estágio do deal (pipeline)</label>
          <select
            style={{ ...input, appearance: "none" } as React.CSSProperties}
            value={(c.stage_id as string) ?? ""}
            onChange={(e) => set("stage_id", e.target.value)}
          >
            <option value="">— selecione —</option>
            {data.allStages.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
      )}

      {(at === "add_tag" || at === "remove_tag") && (
        <div style={field}>
          <label style={label}>Nome da tag</label>
          <select
            style={{ ...input, appearance: "none" } as React.CSSProperties}
            value={(c.tag_name as string) ?? ""}
            onChange={(e) => set("tag_name", e.target.value)}
          >
            <option value="">— selecione —</option>
            {data.tags.map((t) => (
              <option key={t.id} value={t.name}>{t.name}</option>
            ))}
          </select>
        </div>
      )}

      {at === "add_note" && (
        <div style={field}>
          <label style={label}>Texto da nota (suporta {`{{lead.name}}`})</label>
          <textarea
            style={{ ...input, minHeight: 70, resize: "vertical" } as React.CSSProperties}
            value={(c.note_template as string) ?? ""}
            onChange={(e) => set("note_template", e.target.value)}
            placeholder="Ex: Lead {{lead.name}} chegou no nó X"
          />
        </div>
      )}

      {at === "assign_to" && (
        <div style={field}>
          <label style={label}>Vendedor</label>
          <select
            style={{ ...input, appearance: "none" } as React.CSSProperties}
            value={(c.user_id as string) ?? ""}
            onChange={(e) => set("user_id", e.target.value)}
          >
            <option value="">— selecione —</option>
            {data.users.map((u) => (
              <option key={u.id} value={u.id}>{u.name || u.email}</option>
            ))}
          </select>
        </div>
      )}

      {at === "assign_round_robin" && (
        <div style={field}>
          <label style={label}>Vendedores no rodízio</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {data.users.map((u) => {
              const selected = ((c.user_ids as string[]) ?? []).includes(u.id);
              return (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => {
                    const arr = ((c.user_ids as string[]) ?? []).slice();
                    const idx = arr.indexOf(u.id);
                    if (idx >= 0) arr.splice(idx, 1); else arr.push(u.id);
                    set("user_ids", arr);
                  }}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 6,
                    border: `1px solid ${selected ? "#E85D26" : "#e0dbd4"}`,
                    background: selected ? "rgba(232,93,38,.08)" : "#fff",
                    color: selected ? "#E85D26" : "#555",
                    fontSize: 12,
                    cursor: "pointer",
                  }}
                >
                  {u.name || u.email}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
})()}
```

(Se `data.users` ou `data.tags` não existir no `FlowBuilderData`, adicionar — eles já devem existir conforme spec.)

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): expand Inspector with new action_types (deal won/lost, add_note, round-robin)"
```

---

### Task 15: Builder — trigger `keyword_received` no Inspector

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar `keyword_received` em `TRIGGER_LABELS` e `TRIGGER_ICONS`**

```typescript
const TRIGGER_LABELS: Record<string, string> = {
  no_message: "Sem mensagem",
  stage_stagnation: "Estagnação",
  stage_enter: "Entrada em stage",
  post_broadcast: "Pós-disparo",
  sale_created: "Venda criada",
  repurchase_window: "Janela de recompra",
  no_sale_in_stage: "Sem venda no stage",
  tag_added: "Tag adicionada",
  deal_stage_enter: "Entrou em stage (deal)",
  deal_closed_lost: "Deal perdido",
  keyword_received: "Palavra-chave recebida",
};

const TRIGGER_ICONS: Record<string, string> = {
  /* ... existentes ... */
  keyword_received: "🔍",
};
```

- [ ] **Step 3: Inspector — campo de keywords para trigger**

No bloco do Inspector que renderiza config para `node.type === "trigger"`, adicionar condicional:

```tsx
{(c.trigger_type as string) === "keyword_received" && (
  <div style={field}>
    <label style={label}>Palavras-chave (separadas por vírgula)</label>
    <input
      style={input as React.CSSProperties}
      type="text"
      value={((c.keywords as string[]) ?? []).join(", ")}
      onChange={(e) =>
        set(
          "keywords",
          e.target.value
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
        )
      }
      placeholder="Ex: preço, valor, quanto custa"
    />
    <p style={{ fontSize: 11, color: "#9b9590", marginTop: 4 }}>
      Quando o lead enviar uma mensagem contendo qualquer uma destas palavras (case-insensitive), a cadência será disparada.
    </p>
  </div>
)}
```

- [ ] **Step 4: Quick-add menu**

Adicionar item:
```typescript
{ type: "trigger", subtype: "keyword_received", icon: "🔍", label: "Palavra-chave" },
```

- [ ] **Step 5: getDefaultConfig**

Atualizar `getDefaultConfig` no início do arquivo:

```typescript
case "trigger":
  if (subtype === "keyword_received") return { trigger_type: "keyword_received", keywords: [] };
  return { trigger_type: subtype || "no_message", days: 30 };
```

- [ ] **Step 6: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): add keyword_received trigger config in Inspector"
```

---

## FASE 6 — Verificação e smoke E2E

### Task 16: Verificação final — rodar TODOS os testes e build

- [ ] **Step 1: Rodar todos os testes do backend**

```bash
cd backend && python -m pytest tests/ -v 2>&1 | tail -50
```

Esperado: todos PASS.

- [ ] **Step 2: Build do frontend**

```bash
cd frontend && NEXT_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder NEXT_PUBLIC_FASTAPI_URL=http://placeholder.api.local npm run build
```

Esperado: build sem erros.

- [ ] **Step 3: Confirmar zero referências ao legado**

```bash
git grep -E "from app\.cadence|/api/cadences|cadence_enrollments|cadence_steps|use-realtime-cadences|CadenceEnrollment|CadenceStep" -- ':!supabase/migrations' ':!docs/' ':!*.md' || echo "OK: zero referências"
```

Esperado: imprime "OK: zero referências" (linhas em migrations e docs são esperadas).

- [ ] **Step 4: Commit (se houver pequenas correções)**

```bash
git status
# se houver mudanças:
git add -A && git commit -m "chore(cadence): final cleanup pass"
```

---

### Task 17: Smoke E2E manual (executado pelo usuário em dev)

**Este task NÃO é executado pelo subagente.** Após Task 16, parar e avisar o usuário para validar:

- [ ] **Step 1: Avisar o usuário**

Mensagem:
> "Implementação completa, todos os testes passam. Por favor valide em dev:
> 1. Rodar a migration `20260522_cadence_unify_drop_legacy.sql` no Supabase
> 2. Subir backend + frontend dev
> 3. Criar cadência com canal selecionado
> 4. Adicionar nós trigger → send_text → wait → condition → action(add_note) → end
> 5. Configurar todos os nós; nenhum erro visual
> 6. Clicar '⚡ Testar' com seu número → ver cores ao vivo e log
> 7. Painel de inscritos vazio mas funcional (sem erros no console)
> 8. Conferir que `/campanhas/cadencias/[id]` carrega normalmente
>
> Após validar, autorize o `git push origin master`."

---

## Self-Review Notes (para o agente que executa)

- Tasks são **independentes por fase** mas devem rodar em ordem (fase 2 depende de fase 1, etc.)
- Cada commit é independente — se um falhar, o anterior está estável
- Backend tests usam mocks pesados (MagicMock) — não precisam de Supabase real
- Frontend não tem testes unitários neste plano — confiamos em `tsc --noEmit` + build + smoke E2E
- O smoke E2E (Task 17) é manual, executado pelo usuário, NÃO pelo agente
- Sempre invocar skill `frontend-design` antes de mexer em `frontend/src/components/**` ou criar componente novo
- Se algum import quebrar durante deleção do legado, verificar se o componente foi renomeado (ex: `CadenceEnrollmentsTable` → `CampaignEnrollmentsTable`) e atualizar consumidores
