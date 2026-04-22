# Vendas ↔ CRM Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Frontend tasks:** OBRIGATÓRIO usar a skill `frontend-design` antes de escrever qualquer JSX, CSS ou Tailwind.

**Goal:** Conectar /vendas ao resto do CRM — bot cria deals automaticamente no funil certo, vendedor gerencia deals direto do chat em /conversas, e navegação bidirecional deal ↔ conversa.

**Architecture:** Conversas-first. ContactDetail em /conversas ganha painel completo de deals. Backend create_deal passa a ser pipeline-aware usando mapeamento category→pipeline. DealDetailSidebar ganha botão de deep-link para /conversas.

**Tech Stack:** Next.js 14 App Router, TypeScript, Supabase (Python SDK no backend), dnd-kit (já instalado), Tailwind CSS.

**Branch:** `feat/vendas-crm-integration`  
**Spec:** `docs/superpowers/specs/2026-04-22-vendas-crm-integration-design.md`

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `backend/app/leads/service.py` | Modificar | Adicionar `get_lead()`, tornar `create_deal()` pipeline-aware |
| `backend/app/agent/tools.py` | Modificar | `encaminhar_humano` passa `category=lead.stage` para `create_deal` |
| `frontend/src/app/api/leads/[id]/deals/route.ts` | Criar | GET todos os deals de um lead |
| `frontend/src/components/conversas/contact-detail.tsx` | Modificar | Seção "Oportunidades" completa |
| `frontend/src/components/deals/deal-detail-sidebar.tsx` | Modificar | Botão "Abrir conversa" |
| `frontend/src/app/(authenticated)/conversas/page.tsx` | Modificar | Deep-link via `?lead_id=` |

---

## Task 1 — DB: Seed 4 funis de setor

> Executado via Supabase MCP diretamente, não requer subagent.  
> **project_id:** `tshmvxxxyxgctrdkqvam`

- [ ] **Step 1: Aplicar migration via MCP**

```sql
WITH
  atacado AS (
    INSERT INTO public.pipelines (name, order_index)
    VALUES ('Atacado', 1) RETURNING id
  ),
  private_label AS (
    INSERT INTO public.pipelines (name, order_index)
    VALUES ('Private Label', 2) RETURNING id
  ),
  exportacao AS (
    INSERT INTO public.pipelines (name, order_index)
    VALUES ('Exportação', 3) RETURNING id
  ),
  consumo AS (
    INSERT INTO public.pipelines (name, order_index)
    VALUES ('Consumo', 4) RETURNING id
  )
INSERT INTO public.pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
SELECT p.id, s.label, s.key, s.dot_color, s.order_index, s.is_protected
FROM (
  SELECT id FROM atacado UNION ALL
  SELECT id FROM private_label UNION ALL
  SELECT id FROM exportacao UNION ALL
  SELECT id FROM consumo
) p,
(VALUES
  ('Novo',          NULL,               '#e07a7a', 0, false),
  ('Contato',       NULL,               '#d4a04a', 1, false),
  ('Proposta',      NULL,               '#9b7abf', 2, false),
  ('Negociação',    NULL,               '#5b8aad', 3, false),
  ('Fechado Ganho', 'fechado_ganho',    '#5aad65', 4, true),
  ('Perdido',       'fechado_perdido',  '#9ca3af', 5, true)
) AS s(label, key, dot_color, order_index, is_protected);
```

- [ ] **Step 2: Verificar resultado**

```sql
SELECT p.name, COUNT(ps.id) as stages
FROM pipelines p
JOIN pipeline_stages ps ON ps.pipeline_id = p.id
GROUP BY p.name ORDER BY p.name;
```

Resultado esperado: 5 linhas (Principal + 4 setoriais), cada uma com 6 stages.

---

## Task 2 — Backend: `get_lead` + `create_deal` pipeline-aware

**Files:**
- Modify: `backend/app/leads/service.py`
- Test: `backend/tests/test_agent_tools.py` (já existe, adicionar casos)

- [ ] **Step 1: Adicionar `get_lead` e constante de mapeamento em `service.py`**

Adicionar após os imports existentes:

```python
CATEGORY_PIPELINE_NAMES: dict[str, str] = {
    "atacado": "Atacado",
    "private_label": "Private Label",
    "exportacao": "Exportação",
    "consumo": "Consumo",
}
```

Adicionar função após `reset_lead`:

```python
def get_lead(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    return result.data[0] if result.data else None
```

- [ ] **Step 2: Substituir `create_deal` pela versão pipeline-aware**

Substituir a função inteira:

```python
def create_deal(lead_id: str, title: str, category: str | None = None) -> dict[str, Any]:
    sb = get_supabase()

    pipeline_id: str | None = None
    stage_id: str | None = None

    pipeline_name = CATEGORY_PIPELINE_NAMES.get(category or "")
    if pipeline_name:
        p = sb.table("pipelines").select("id").eq("name", pipeline_name).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if not pipeline_id:
        p = sb.table("pipelines").select("id").order("order_index", desc=False).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if pipeline_id:
        s = (
            sb.table("pipeline_stages")
            .select("id")
            .eq("pipeline_id", pipeline_id)
            .eq("is_protected", False)
            .order("order_index", desc=False)
            .limit(1)
            .execute()
        )
        if s.data:
            stage_id = s.data[0]["id"]

    deal = {
        "lead_id": lead_id,
        "title": title,
        "stage": "novo",
        "category": category,
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
    }
    return sb.table("deals").insert(deal).execute().data[0]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/leads/service.py
git commit -m "feat(backend): create_deal pipeline-aware + get_lead helper"
```

---

## Task 3 — Backend: `encaminhar_humano` passa categoria do lead

**Files:**
- Modify: `backend/app/agent/tools.py`

- [ ] **Step 1: Atualizar import em `tools.py`**

Linha 7, adicionar `get_lead`:

```python
from app.leads.service import update_lead, save_message, create_deal, get_lead
```

- [ ] **Step 2: Atualizar bloco `encaminhar_humano` em `execute_tool`**

Substituir o bloco `elif tool_name == "encaminhar_humano":` (linhas 190-195 atuais):

```python
    elif tool_name == "encaminhar_humano":
        update_lead(lead_id, status="converted", human_control=True)
        motivo = args.get("motivo", "lead qualificado")
        vendedor = args.get("vendedor", "Vendedor")
        lead = get_lead(lead_id)
        lead_stage = lead.get("stage") if lead else None
        create_deal(lead_id, title=f"{vendedor} - {motivo}", category=lead_stage)
        save_message(lead_id, "system", f"[encaminhar_humano] Lead encaminhado para {vendedor}: {motivo}", conversation_id=conversation_id)
        return f"Lead encaminhado para {vendedor}"
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/tools.py
git commit -m "feat(backend): encaminhar_humano roteia deal ao funil do setor do lead"
```

---

## Task 4 — Frontend: API `GET /api/leads/[id]/deals`

**Files:**
- Create: `frontend/src/app/api/leads/[id]/deals/route.ts`

- [ ] **Step 1: Criar o arquivo de rota**

```typescript
import { NextResponse } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("deals")
    .select(
      "id, title, value, category, stage_id, pipeline_id, updated_at, lost_reason, " +
      "pipeline_stages(id, label, dot_color, key, is_protected), " +
      "pipelines(id, name)"
    )
    .eq("lead_id", id)
    .order("updated_at", { ascending: false });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data ?? []);
}
```

- [ ] **Step 2: Verificar que o TypeScript compila**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/leads/[id]/deals/route.ts
git commit -m "feat(api): GET /api/leads/[id]/deals"
```

---

## Task 5 — Frontend: `ContactDetail` painel de Oportunidades

> **OBRIGATÓRIO:** Usar skill `frontend-design` antes de escrever qualquer JSX/CSS/Tailwind.

**Files:**
- Modify: `frontend/src/components/conversas/contact-detail.tsx`

**Contexto do arquivo atual:** 263 linhas. Já tem um bloco `activeDeal` (linha 23, useEffect linhas 32-46, renderização linhas 158-166) que mostra apenas 1 deal de forma estática usando o campo `stage` de texto (legado). Esse bloco será substituído pela seção nova.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Substituir state e fetch de deal**

Remover:
```typescript
const [activeDeal, setActiveDeal] = useState<{ title: string; value: number; stage: string } | null>(null);
```
e o useEffect que popula `activeDeal` (linhas 32-46).

Adicionar no lugar:

```typescript
const [deals, setDeals] = useState<LeadDeal[]>([]);
const [showDealCreate, setShowDealCreate] = useState(false);

async function fetchDeals() {
  if (!lead) return;
  const res = await fetch(`/api/leads/${lead.id}/deals`);
  if (res.ok) setDeals(await res.json());
}

useEffect(() => { fetchDeals(); }, [lead?.id]);
```

Adicionar tipo no topo do arquivo (antes do componente):

```typescript
interface LeadDeal {
  id: string;
  title: string;
  value: number;
  category: string | null;
  stage_id: string | null;
  pipeline_id: string | null;
  pipeline_stages: { id: string; label: string; dot_color: string; key: string | null; is_protected: boolean } | null;
  pipelines: { id: string; name: string } | null;
}
```

- [ ] **Step 3: Substituir renderização do `activeDeal` (linhas 158-166) pela seção nova**

Substituir o bloco `{activeDeal && (...)}` por:

```tsx
{/* Oportunidades */}
<div className="border-t border-[#dedbd6] pt-4">
  <div className="flex items-center justify-between mb-2">
    <span className="text-[11px] uppercase tracking-[0.6px] text-[#7b7b78]">Oportunidades</span>
    <button
      onClick={() => setShowDealCreate(true)}
      className="flex items-center gap-1 text-[11px] text-[#7b7b78] hover:text-[#111111] transition-colors"
    >
      <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <line x1="8" y1="3" x2="8" y2="13" /><line x1="3" y1="8" x2="13" y2="8" />
      </svg>
      Nova
    </button>
  </div>
  {deals.length === 0 ? (
    <p className="text-[12px] text-[#7b7b78]">Nenhuma oportunidade</p>
  ) : (
    <div className="space-y-2">
      {deals.map((deal) => {
        const stage = deal.pipeline_stages;
        const isProtected = stage?.is_protected ?? false;
        return (
          <div
            key={deal.id}
            className={`bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] p-2.5 ${isProtected ? "opacity-50" : ""}`}
          >
            <div className="flex items-center gap-1.5 mb-1">
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: stage?.dot_color ?? "#dedbd6" }} />
              <span className="text-[12px] font-medium text-[#111111] truncate flex-1">{deal.title}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-[#7b7b78]">
                {deal.pipelines?.name ?? "—"} · {stage?.label ?? "—"}
              </span>
              {(deal.value ?? 0) > 0 && (
                <span className="text-[11px] text-[#111111]">
                  R$ {deal.value.toLocaleString("pt-BR")}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  )}
</div>
```

- [ ] **Step 4: Adicionar imports e modal no final do return**

Adicionar import no topo:
```typescript
import { DealCreateModal } from "@/components/deals/deal-create-modal";
```

Adicionar antes do `</div>` final do componente:
```tsx
{showDealCreate && lead && (
  <DealCreateModal
    leads={[lead as import("@/lib/types").Lead]}
    preselectedLead={lead as import("@/lib/types").Lead}
    onClose={() => setShowDealCreate(false)}
    onCreate={async (data) => {
      const res = await fetch("/api/deals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...data, pipeline_id: data.pipeline_id }),
      });
      if (res.ok) fetchDeals();
    }}
  />
)}
```

> **Nota:** `DealCreateModal` atualmente não tem campo de seleção de pipeline. Isso é limitação aceitável para V1 — o deal será criado no pipeline correto pelo backend via `category`. Se precisar de seleção de pipeline no modal, isso é Task futura.

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/contact-detail.tsx
git commit -m "feat(conversas): painel de oportunidades no ContactDetail"
```

---

## Task 6 — Frontend: `DealDetailSidebar` botão "Abrir conversa"

> **OBRIGATÓRIO:** Usar skill `frontend-design` antes de escrever qualquer JSX/CSS/Tailwind.

**Files:**
- Modify: `frontend/src/components/deals/deal-detail-sidebar.tsx`

**Contexto:** Arquivo tem 165 linhas. Header do sidebar está nas linhas 59-75. O `deal.lead_id` é sempre disponível.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar `useRouter` import**

```typescript
import { useRouter } from "next/navigation";
```

- [ ] **Step 3: Instanciar router dentro do componente**

Adicionar após os `useState` existentes:

```typescript
const router = useRouter();
```

- [ ] **Step 4: Adicionar botão no header**

No bloco `<div className="flex items-center gap-2">` do header (que já tem "Editar", lixeira e fechar), adicionar antes do botão "Editar":

```tsx
<button
  onClick={() => router.push(`/conversas?lead_id=${deal.lead_id}`)}
  className="w-8 h-8 flex items-center justify-center rounded-[4px] border border-[#dedbd6] text-[#7b7b78] hover:border-[#111111] hover:text-[#111111] transition-colors"
  title="Abrir conversa"
>
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
  </svg>
</button>
```

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/deals/deal-detail-sidebar.tsx
git commit -m "feat(vendas): botão abrir conversa no DealDetailSidebar"
```

---

## Task 7 — Frontend: `/conversas` deep-link via `?lead_id=`

> **OBRIGATÓRIO:** Usar skill `frontend-design` antes de escrever qualquer JSX/CSS/Tailwind.

**Files:**
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`

**Contexto:** Arquivo usa `useState` e `useEffect`. Conversas são carregadas em `conversations` state. `selectedConversation` é setado por `setSelectedConversation`. 

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar imports de roteamento**

```typescript
import { useSearchParams, useRouter } from "next/navigation";
```

- [ ] **Step 3: Instanciar hooks dentro do componente**

Adicionar após os useState existentes:

```typescript
const searchParams = useSearchParams();
const router = useRouter();
const targetLeadId = searchParams.get("lead_id");
```

- [ ] **Step 4: Adicionar useEffect para deep-link**

Adicionar após o useEffect existente de `fetchConversations`:

```typescript
useEffect(() => {
  if (!targetLeadId || conversations.length === 0) return;
  const target = conversations.find((c) => c.lead_id === targetLeadId);
  if (target) {
    setSelectedConversation(target);
    router.replace("/conversas");
  }
}, [targetLeadId, conversations]);
```

- [ ] **Step 5: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/(authenticated)/conversas/page.tsx
git commit -m "feat(conversas): deep-link via ?lead_id= param"
```

---

## Task 8 — Verificação final e push

- [ ] **Step 1: TypeScript geral**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 2: Push da branch**

```bash
git push origin feat/vendas-crm-integration
```

- [ ] **Step 3: Merge para master**

```bash
git checkout master && git pull origin master
git merge feat/vendas-crm-integration --no-ff -m "feat: integração /vendas ↔ CRM conversas-first"
git push origin master
```
