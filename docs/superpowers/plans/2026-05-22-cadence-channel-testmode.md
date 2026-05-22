# Canal por Cadência + Modo de Teste SSE — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND RULE:** Qualquer task que toque arquivos em `frontend/` DEVE invocar a skill `frontend-design` antes de escrever código de componente.

**Goal:** Adicionar canal padrão por cadência (com override por nó) e modo de teste SSE que envia mensagens reais nó a nó com animação ao vivo no flow builder.

**Architecture:** DB recebe `channel_id` em `campaigns`. O engine resolve canal na ordem nó → campanha → erro. O modo de teste usa `GET /api/automation/campaigns/{id}/test` com SSE (`StreamingResponse`); frontend escuta com `EventSource` e anima cada nó em tempo real.

**Tech Stack:** Python 3.12, FastAPI StreamingResponse, Supabase Python client, React 18, TypeScript, @xyflow/react

**Spec:** `docs/superpowers/specs/2026-05-22-cadence-channel-testmode-design.md`

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `supabase/migrations/20260522_campaign_channel.sql` | CRIAR | Adiciona channel_id em campaigns, limpa cadências existentes |
| `frontend/src/app/api/campaigns/route.ts` | MODIFICAR | Aceitar e persistir channel_id no POST |
| `frontend/src/lib/types.ts` | MODIFICAR | Adicionar channel_id ao tipo Campaign |
| `frontend/src/app/(authenticated)/campanhas/page.tsx` | MODIFICAR | Dropdown de canal no modal "Nova Cadência" |
| `frontend/src/components/campaigns/cadence-flow-builder.tsx` | MODIFICAR | Override de canal no Inspector + botão Testar + painel de execução |
| `backend/app/automation/engine.py` | MODIFICAR | Resolução canal nó→campanha→erro + include channel_id no select |
| `backend/app/automation/router.py` | MODIFICAR | Adicionar endpoint GET /campaigns/{id}/test SSE |
| `backend/app/automation/test_runner.py` | CRIAR | Lógica de execução SSE do teste |
| `backend/tests/test_automation_test_runner.py` | CRIAR | Testes do test_runner |

---

## FASE 1 — Banco de Dados

### Task 1: Migration SQL — channel_id + limpar cadências existentes

**Files:**
- Create: `supabase/migrations/20260522_campaign_channel.sql`

- [ ] **Step 1: Criar o arquivo de migration**

```sql
-- supabase/migrations/20260522_campaign_channel.sql

-- 1. Limpar cadências de desenvolvimento
DELETE FROM campaign_enrollments;
DELETE FROM campaign_nodes;
DELETE FROM campaigns;

-- 2. Adicionar channel_id à tabela campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS channel_id UUID REFERENCES channels(id) ON DELETE SET NULL;
```

- [ ] **Step 2: Executar no Supabase SQL Editor**

Abrir Supabase Dashboard → SQL Editor → colar e executar.
Verificar que a coluna `channel_id` aparece em `campaigns` e que a tabela está vazia.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260522_campaign_channel.sql
git commit -m "feat(cadence): add channel_id to campaigns, clear dev cadences"
```

---

## FASE 2 — Backend

### Task 2: `automation/engine.py` — resolução de canal nó→campanha→erro

**Files:**
- Modify: `backend/app/automation/engine.py`

**Contexto:** `get_due_enrollments` precisa incluir `channel_id` no select de campaigns. `_execute_send_text` precisa usar canal do nó ou campanha em vez de `get_channel_for_lead`. `_execute_send` já usa `_execute_send_node` de `campaigns/worker.py` que já faz resolução por nó — só precisa do fallback para `campaign.channel_id`.

- [ ] **Step 1: Escrever teste**

```python
# backend/tests/test_automation_engine_channel.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.automation.engine import _resolve_channel

class TestResolveChannel:
    def test_node_channel_takes_priority(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "ch-node"}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            result = _resolve_channel(
                node_cfg={"channel_id": "ch-node"},
                campaign={"channel_id": "ch-campaign"},
            )
        assert result["id"] == "ch-node"

    def test_falls_back_to_campaign_channel(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "ch-campaign"}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            result = _resolve_channel(
                node_cfg={},
                campaign={"channel_id": "ch-campaign"},
            )
        assert result["id"] == "ch-campaign"

    def test_raises_when_no_channel(self):
        with pytest.raises(ValueError, match="Nenhum canal"):
            _resolve_channel(node_cfg={}, campaign={})
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_engine_channel.py -v
```

Esperado: `ImportError` — `_resolve_channel` não existe ainda.

- [ ] **Step 3: Adicionar `_resolve_channel` em `engine.py`**

Adicionar após a função `_compare` (linha ~65):

```python
def _resolve_channel(node_cfg: dict, campaign: dict) -> dict:
    """Resolve channel: node override → campaign default → raise."""
    from app.channels.service import get_channel_by_id
    channel_id = node_cfg.get("channel_id") or campaign.get("channel_id")
    if not channel_id:
        raise ValueError("Nenhum canal configurado para este nó nem para a campanha")
    channel = get_channel_by_id(channel_id)
    if not channel:
        raise ValueError(f"Canal {channel_id} não encontrado")
    return channel
```

- [ ] **Step 4: Atualizar `get_due_enrollments` para incluir `channel_id`**

Localizar `get_due_enrollments` e atualizar o select de campaigns:

```python
def get_due_enrollments(now: datetime, limit: int = 20) -> list[dict]:
    sb = get_supabase()
    env_tag = _get_env_tag()
    return (
        sb.table("campaign_enrollments")
        .select(
            "*, "
            "leads!inner(id, phone, name, company, stage, ai_enabled, last_customer_message_at, assigned_to), "
            "campaign_nodes!campaign_enrollments_current_node_id_fkey(*), "
            "campaigns!inner(id, name, status, priority, frequency_cap, send_start_hour, send_end_hour, channel_id)"
        )
        .eq("status", "active")
        .eq("env_tag", env_tag)
        .lte("next_execute_at", now.isoformat())
        .limit(limit)
        .execute()
        .data
    )
```

- [ ] **Step 5: Atualizar `_execute_send_text` para usar `_resolve_channel`**

Substituir a parte de resolução de canal em `_execute_send_text`:

```python
async def _execute_send_text(enrollment: dict, node: dict, lead: dict, now: datetime, campaign: dict | None = None) -> None:
    from app.whatsapp.registry import get_provider
    from app.leads.service import save_message

    cfg = node.get("config") or {}
    campaign = campaign or {}

    last_msg = lead.get("last_customer_message_at")
    if last_msg:
        from dateutil.parser import parse
        if isinstance(last_msg, str):
            last_msg = parse(last_msg)
        if (now - last_msg).total_seconds() > 86400:
            _update(enrollment["id"], last_error="24h_window_expired")
            return

    message = substitute_variables(cfg.get("message_text", ""), lead, enrollment)
    channel = _resolve_channel(cfg, campaign)

    provider = get_provider(channel)
    await provider.send_text(lead["phone"], message)

    save_message(
        lead_id=enrollment["lead_id"],
        role="assistant",
        content=message,
        stage=lead.get("stage"),
        sent_by="automation",
    )
    logger.info("[AUTOMATION] send_text → %s", lead["phone"])
```

- [ ] **Step 6: Atualizar `_process_one` para passar `campaign` para `_execute_send_text`**

Na chamada de `_execute_send_text` dentro de `_process_one`, adicionar `campaign`:

```python
            if node_type == "send":
                await _execute_send(enrollment, node, lead, now)
            else:
                await _execute_send_text(enrollment, node, lead, now, campaign)
```

- [ ] **Step 7: Atualizar `_execute_send` para passar `channel_id` da campanha ao worker**

```python
async def _execute_send(enrollment: dict, node: dict, lead: dict, now: datetime, campaign: dict | None = None) -> None:
    from app.campaigns.worker import _execute_send_node
    # Injetar channel_id da campanha no config do nó se o nó não tiver override
    campaign = campaign or {}
    node_with_channel = dict(node)
    cfg = dict(node_with_channel.get("config") or {})
    if not cfg.get("channel_id") and campaign.get("channel_id"):
        cfg["channel_id"] = campaign["channel_id"]
    node_with_channel["config"] = cfg
    await _execute_send_node(enrollment, node_with_channel, lead, now)
```

Atualizar a chamada em `_process_one`:
```python
            if node_type == "send":
                await _execute_send(enrollment, node, lead, now, campaign)
            else:
                await _execute_send_text(enrollment, node, lead, now, campaign)
```

- [ ] **Step 8: Rodar todos os testes de automação**

```bash
cd backend && python -m pytest tests/test_automation_engine_channel.py tests/test_automation_engine.py tests/test_automation_variables.py tests/test_automation_retry.py -v
```

Esperado: todos PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_automation_engine_channel.py
git commit -m "feat(automation): resolve channel via node→campaign→error in engine"
```

---

### Task 3: `automation/test_runner.py` — execução SSE do teste

**Files:**
- Create: `backend/app/automation/test_runner.py`
- Create: `backend/tests/test_automation_test_runner.py`

**Contexto:** Executa os nós de uma campanha em sequência para um número de telefone de teste. Emite eventos SSE `data: {...}\n\n`. Se o lead não existir pelo telefone, cria um temporário e deleta ao final. `skip_delays=True` faz nós `wait` durarem 800ms.

- [ ] **Step 1: Escrever testes**

```python
# backend/tests/test_automation_test_runner.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.automation.test_runner import _build_node_sequence, _format_sse

class TestBuildNodeSequence:
    def test_linear_sequence(self):
        nodes = [
            {"id": "a", "type": "trigger", "next_node_id": "b", "yes_node_id": None, "no_node_id": None},
            {"id": "b", "type": "send",    "next_node_id": "c", "yes_node_id": None, "no_node_id": None},
            {"id": "c", "type": "end",     "next_node_id": None, "yes_node_id": None, "no_node_id": None},
        ]
        result = _build_node_sequence(nodes)
        assert [n["id"] for n in result] == ["b", "c"]  # trigger é pulado

    def test_empty_when_only_trigger(self):
        nodes = [{"id": "a", "type": "trigger", "next_node_id": None, "yes_node_id": None, "no_node_id": None}]
        assert _build_node_sequence(nodes) == []

class TestFormatSSE:
    def test_format(self):
        result = _format_sse({"node_id": "abc", "status": "running"})
        assert result == 'data: {"node_id": "abc", "status": "running"}\n\n'
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_test_runner.py -v
```

- [ ] **Step 3: Implementar `test_runner.py`**

```python
# backend/app/automation/test_runner.py
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator

from app.db.supabase import get_supabase
from app.config import get_settings

logger = logging.getLogger(__name__)


def _format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_node_sequence(nodes: list[dict]) -> list[dict]:
    """Return nodes in execution order, skipping the trigger node."""
    by_id = {n["id"]: n for n in nodes}
    # Find trigger node
    trigger = next((n for n in nodes if n["type"] == "trigger"), None)
    if not trigger or not trigger.get("next_node_id"):
        return []
    sequence = []
    seen = set()
    current_id = trigger["next_node_id"]
    while current_id and current_id not in seen:
        seen.add(current_id)
        node = by_id.get(current_id)
        if not node:
            break
        sequence.append(node)
        current_id = node.get("next_node_id")
    return sequence


def _get_or_create_test_lead(phone: str) -> tuple[dict, bool]:
    """Return (lead, was_created). Creates a temporary lead if not found."""
    sb = get_supabase()
    settings = get_settings()
    env_tag = "dev" if settings.is_dev_env else "production"
    rows = sb.table("leads").select("*").eq("phone", phone).limit(1).execute().data
    if rows:
        return rows[0], False
    created = sb.table("leads").insert({
        "name": "Teste",
        "phone": phone,
        "env_tag": env_tag,
        "ai_enabled": False,
        "stage": "Novo",
    }).select().single().execute().data
    return created, True


def _delete_test_lead(lead_id: str) -> None:
    sb = get_supabase()
    sb.table("leads").delete().eq("id", lead_id).execute()


async def run_test_campaign(
    campaign_id: str,
    phone: str,
    skip_delays: bool = True,
) -> AsyncGenerator[str, None]:
    """SSE generator: executes campaign nodes for a test phone number."""
    sb = get_supabase()

    # Load campaign + nodes
    camp_data = sb.table("campaigns").select("*, campaign_nodes(*)").eq("id", campaign_id).single().execute().data
    if not camp_data:
        yield _format_sse({"node_id": None, "status": "failed", "log": "Campanha não encontrada"})
        yield _format_sse({"node_id": None, "status": "finished"})
        return

    campaign = camp_data
    nodes: list[dict] = camp_data.get("campaign_nodes") or []
    sequence = _build_node_sequence(nodes)

    if not sequence:
        yield _format_sse({"node_id": None, "status": "failed", "log": "Nenhum nó executável encontrado (adicione nós após o gatilho)"})
        yield _format_sse({"node_id": None, "status": "finished"})
        return

    lead, was_created = _get_or_create_test_lead(phone)
    now = datetime.now(timezone.utc)

    # Fake enrollment for variable substitution
    fake_enrollment = {"lead_id": lead["id"], "campaign_id": campaign_id}

    try:
        # Track which node_id to follow (for conditions)
        next_node_id: str | None = sequence[0]["id"]
        nodes_by_id = {n["id"]: n for n in nodes}

        while next_node_id:
            node = nodes_by_id.get(next_node_id)
            if not node:
                break
            if node["type"] == "trigger":
                next_node_id = node.get("next_node_id")
                continue

            node_id = node["id"]
            yield _format_sse({"node_id": node_id, "status": "running"})
            t_start = asyncio.get_event_loop().time()

            try:
                result_log, branch = await _execute_test_node(node, lead, fake_enrollment, campaign, now, skip_delays)
                duration_ms = int((asyncio.get_event_loop().time() - t_start) * 1000)
                yield _format_sse({"node_id": node_id, "status": "done", "log": result_log, "duration_ms": duration_ms})

                # Follow branch (condition) or next
                if branch == "yes":
                    next_node_id = node.get("yes_node_id")
                elif branch == "no":
                    next_node_id = node.get("no_node_id")
                else:
                    next_node_id = node.get("next_node_id")

                if node["type"] == "end":
                    break

            except Exception as e:
                duration_ms = int((asyncio.get_event_loop().time() - t_start) * 1000)
                yield _format_sse({"node_id": node_id, "status": "failed", "log": str(e), "duration_ms": duration_ms})
                break

    finally:
        if was_created:
            _delete_test_lead(lead["id"])

    yield _format_sse({"node_id": None, "status": "finished"})


async def _execute_test_node(
    node: dict,
    lead: dict,
    enrollment: dict,
    campaign: dict,
    now: datetime,
    skip_delays: bool,
) -> tuple[str, str | None]:
    """Execute a single node. Returns (log_message, branch) where branch is 'yes'|'no'|None."""
    from app.automation.engine import _resolve_channel
    node_type = node["type"]
    cfg = node.get("config") or {}

    if node_type == "send":
        from app.whatsapp.registry import get_provider
        from app.broadcast.worker import _build_template_components
        channel = _resolve_channel(cfg, campaign)
        provider = get_provider(channel)
        template_name = cfg.get("template_name", "")
        components = _build_template_components(cfg.get("template_variables", {}), lead)
        await provider.send_template(
            to=lead["phone"],
            template_name=template_name,
            components=components,
            language_code=cfg.get("template_language", "pt_BR"),
        )
        return f"Template '{template_name}' enviado via {channel.get('name', channel.get('id'))}", None

    if node_type == "send_text":
        from app.whatsapp.registry import get_provider
        from app.automation.variables import substitute_variables
        channel = _resolve_channel(cfg, campaign)
        provider = get_provider(channel)
        message = substitute_variables(cfg.get("message_text", ""), lead, enrollment)
        await provider.send_text(lead["phone"], message)
        return f"Texto enviado: \"{message[:60]}{'...' if len(message) > 60 else ''}\"", None

    if node_type == "wait":
        days = cfg.get("days", 1)
        if skip_delays:
            await asyncio.sleep(0.8)
            return f"Aguardar {days} dia(s) — pulado no teste", None
        await asyncio.sleep(days * 86400)
        return f"Aguardou {days} dia(s)", None

    if node_type == "condition":
        from app.automation.engine import _execute_condition
        from unittest.mock import MagicMock
        # Execute condition logic to get the branch
        cond_type = cfg.get("condition_type", "replied_recently")
        branch = _eval_condition(cfg, lead, enrollment, now)
        return f"Condição '{cond_type}' → {'SIM' if branch == 'yes' else 'NÃO'}", branch

    if node_type == "action":
        action_type = cfg.get("action_type", "")
        return f"Ação '{action_type}' executada (modo teste — sem efeito real)", None

    if node_type == "end":
        return "Fluxo encerrado", None

    return f"Nó tipo '{node_type}' processado", None


def _eval_condition(cfg: dict, lead: dict, enrollment: dict, now: datetime) -> str:
    """Evaluate condition and return 'yes' or 'no'."""
    from datetime import timedelta
    from app.db.supabase import get_supabase
    sb = get_supabase()
    cond = cfg.get("condition_type", "replied_recently")

    if cond == "replied_recently":
        cutoff = (now - timedelta(days=cfg.get("days", 5))).isoformat()
        msgs = sb.table("messages").select("id").eq("lead_id", enrollment["lead_id"]).eq("role", "user").gte("created_at", cutoff).limit(1).execute()
        return "yes" if msgs.data else "no"

    if cond == "in_stage":
        return "yes" if lead.get("stage") == cfg.get("stage") else "no"

    if cond == "has_deal":
        rows = sb.table("deals").select("id").eq("lead_id", enrollment["lead_id"]).limit(1).execute()
        return "yes" if rows.data else "no"

    if cond == "has_tag":
        tag_name = cfg.get("tag_name", "")
        tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
        if tag_row:
            lt = sb.table("lead_tags").select("id").eq("lead_id", enrollment["lead_id"]).eq("tag_id", tag_row[0]["id"]).limit(1).execute()
            return "yes" if lt.data else "no"
        return "no"

    # Numeric conditions: sale_count, total_spend, last_sale_value, deal_value, repurchase_days
    from app.automation.engine import _compare
    op = cfg.get("operator", "gte")
    target = cfg.get("value", 0)

    if cond == "sale_count":
        res = sb.table("sales").select("id", count="exact").eq("lead_id", enrollment["lead_id"]).execute()
        return "yes" if _compare(res.count or 0, op, target) else "no"

    if cond == "total_spend":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).execute().data or []
        total = sum(float(r["value"]) for r in rows)
        return "yes" if _compare(total, op, target) else "no"

    if cond == "last_sale_value":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).order("sold_at", desc=True).limit(1).execute().data
        val = float(rows[0]["value"]) if rows else 0
        return "yes" if _compare(val, op, target) else "no"

    if cond == "repurchase_days":
        rows = sb.table("sales").select("sold_at").eq("lead_id", enrollment["lead_id"]).order("sold_at", desc=True).limit(1).execute().data
        if rows:
            from dateutil.parser import parse
            sold_at = parse(rows[0]["sold_at"]) if isinstance(rows[0]["sold_at"], str) else rows[0]["sold_at"]
            days_since = (now - sold_at).days
            return "yes" if _compare(days_since, op, target) else "no"
        return "no"

    return "yes"  # condições desconhecidas passam por padrão
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_automation_test_runner.py -v
```

Esperado: 3 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/test_runner.py backend/tests/test_automation_test_runner.py
git commit -m "feat(automation): add test_runner SSE for campaign test mode"
```

---

### Task 4: `automation/router.py` — endpoint SSE de teste

**Files:**
- Modify: `backend/app/automation/router.py`

- [ ] **Step 1: Adicionar endpoint SSE**

Substituir o conteúdo de `backend/app/automation/router.py`:

```python
# backend/app/automation/router.py
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.automation.triggers import fire_trigger

router = APIRouter(prefix="/api/automation", tags=["automation"])


class TriggerEvent(BaseModel):
    event_type: str
    lead_id: str
    data: dict = {}


@router.post("/trigger")
async def fire_automation_trigger(event: TriggerEvent, background_tasks: BackgroundTasks):
    """Called by event hooks (Next.js routes) to fire automation triggers asynchronously."""
    background_tasks.add_task(fire_trigger, event.event_type, event.lead_id, event.data)
    return {"ok": True}


@router.get("/campaigns/{campaign_id}/test")
async def test_campaign_sse(campaign_id: str, phone: str, skip_delays: bool = True):
    """SSE endpoint: executes campaign nodes for a test phone, emitting events per node."""
    from app.automation.test_runner import run_test_campaign

    return StreamingResponse(
        run_test_campaign(campaign_id, phone, skip_delays),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

- [ ] **Step 2: Verificar que o backend compila**

```bash
cd backend && python -m compileall app/automation/router.py app/automation/test_runner.py
```

Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add backend/app/automation/router.py
git commit -m "feat(automation): add SSE test endpoint GET /api/automation/campaigns/{id}/test"
```

---

## FASE 3 — Frontend

### Task 5: Tipos TypeScript + API de campanhas

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/app/api/campaigns/route.ts`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de qualquer código de componente nesta fase.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar `channel_id` ao tipo `Campaign` em `types.ts`**

Localizar a interface `Campaign` e adicionar:

```typescript
channel_id: string | null;
```

- [ ] **Step 3: Atualizar `POST /api/campaigns` para aceitar `channel_id`**

Em `frontend/src/app/api/campaigns/route.ts`, alterar o handler POST:

```typescript
export async function POST(request: NextRequest) {
  const body = await request.json();
  const supabase = await getServiceSupabase();
  const { data, error } = await supabase
    .from("campaigns")
    .insert({
      name: body.name,
      description: body.description ?? null,
      status: "draft",
      env_tag: APP_ENV,
      priority: body.priority ?? 5,
      frequency_cap: body.frequency_cap ?? 1,
      channel_id: body.channel_id ?? null,
    })
    .select()
    .single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
```

- [ ] **Step 4: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: sem erros.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/app/api/campaigns/route.ts
git commit -m "feat(cadence): add channel_id to Campaign type and campaigns POST"
```

---

### Task 6: Modal "Nova Cadência" — dropdown de canal obrigatório

**Files:**
- Modify: `frontend/src/app/(authenticated)/campanhas/page.tsx`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar estado `channelId` e carregar canais**

No componente `CampanhasPageInner`, adicionar estado e fetch de canais:

```typescript
const [channelId, setChannelId] = useState("");
const [channels, setChannels] = useState<{ id: string; name: string; status: string }[]>([]);

useEffect(() => {
  fetch("/api/channels")
    .then(r => r.json())
    .then((data: { id: string; name: string; status: string }[]) => {
      setChannels(Array.isArray(data) ? data.filter(c => c.status === "connected") : []);
    })
    .catch(() => {});
}, []);
```

- [ ] **Step 3: Atualizar `handleCreateCadence` para enviar `channel_id`**

```typescript
body: JSON.stringify({ name: cadenceName.trim(), priority, frequency_cap: frequencyCap, channel_id: channelId || null }),
```

- [ ] **Step 4: Resetar `channelId` ao fechar o modal**

Em todos os lugares onde o modal é fechado e o estado é limpo, adicionar `setChannelId("")`.

- [ ] **Step 5: Adicionar dropdown de canal no modal**

No modal "Nova Cadencia", após o campo de nome e antes dos campos de prioridade:

```tsx
{/* Canal padrão */}
<div>
  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
    Canal padrão <span className="text-red-500">*</span>
  </label>
  <select
    value={channelId}
    onChange={(e) => setChannelId(e.target.value)}
    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
  >
    <option value="">— Selecione um canal —</option>
    {channels.map(c => (
      <option key={c.id} value={c.id}>{c.name}</option>
    ))}
  </select>
  {channels.length === 0 && (
    <p className="text-[11px] text-[#7b7b78] mt-1">Nenhum canal conectado encontrado</p>
  )}
</div>
```

- [ ] **Step 6: Desabilitar botão "Criar" quando canal não selecionado**

```typescript
disabled={!cadenceName.trim() || !channelId || creatingSaving}
```

- [ ] **Step 7: Verificar TypeScript e commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/app/\(authenticated\)/campanhas/page.tsx
git commit -m "feat(cadence): require channel selection when creating cadence"
```

---

### Task 7: Flow Builder — override de canal no Inspector + botão Testar + painel SSE

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

**Contexto:** Este arquivo tem ~1300 linhas. As mudanças são:
1. Inspector: adicionar campo "Canal (override)" em nós `send` e `send_text`
2. Topbar: adicionar botão "⚡ Testar"
3. Modal de teste: input de telefone + checkbox "Pular delays"
4. Painel de execução: substitui Inspector durante o teste, com estados visuais nos nós
5. Nós (`CampaignFlowNode`): receber e exibir `testState` via `data`

> **OBRIGATÓRIO:** Invocar skill `frontend-design` antes de escrever código.

- [ ] **Step 1: Invocar skill `frontend-design`**

- [ ] **Step 2: Adicionar tipos de estado de teste**

No topo do arquivo, após as interfaces existentes:

```typescript
type TestNodeState = "running" | "done" | "failed";

interface TestEvent {
  node_id: string | null;
  status: "running" | "done" | "failed" | "finished";
  log?: string;
  duration_ms?: number;
}

interface TestLogEntry extends TestEvent {
  node_label: string;
}
```

- [ ] **Step 3: Adicionar campo de canal no `FlowBuilderData` e carregá-lo**

Em `FlowBuilderData` (já existe), garantir que `channels` esteja disponível — já carregamos em `flowData`. Nenhuma mudança necessária pois o `allStages` já existe. Adicionar `channels` a `FlowBuilderData`:

```typescript
interface FlowBuilderData {
  templates: FlowTemplate[];
  allStages: FlowStage[];
  tags: FlowTag[];
  users: FlowUser[];
  channels: { id: string; name: string; status: string }[];
}
```

No `useEffect` que carrega dados em `FlowBuilderInner`, adicionar `channels` ao `Promise.all`:

```typescript
const [templatesRes, pipelinesRes, tagsRes, usersRes, channelsRes] = await Promise.all([
  fetch("/api/templates"),
  fetch("/api/pipelines"),
  fetch("/api/tags"),
  fetch("/api/users"),
  fetch("/api/channels"),
]);
const channelsData = channelsRes.ok ? await channelsRes.json() : [];

setFlowData({
  templates: templatesData as FlowTemplate[],
  allStages: stageResults.flat(),
  tags: tagsData as FlowTag[],
  users: usersData as FlowUser[],
  channels: (channelsData as { id: string; name: string; status: string }[]).filter(c => c.status === "connected"),
});
```

- [ ] **Step 4: Adicionar override de canal no Inspector**

No bloco `node.type === "send"` do Inspector, após o campo "Ao responder":

```tsx
<div style={field}>
  <label style={label}>Canal (override)</label>
  <select style={{ ...input, appearance: "none" } as React.CSSProperties}
    value={(c.channel_id as string) ?? ""}
    onChange={e => set("channel_id", e.target.value || null)}
  >
    <option value="">— Usar padrão da cadência —</option>
    {channels.map(ch => <option key={ch.id} value={ch.id}>{ch.name}</option>)}
  </select>
</div>
```

Repetir o mesmo bloco no nó `send_text`, após o campo "Ao responder".

- [ ] **Step 5: Adicionar estado de teste em `FlowBuilderInner`**

```typescript
const [testNodeStates, setTestNodeStates] = useState<Record<string, TestNodeState>>({});
const [testLog, setTestLog] = useState<TestLogEntry[]>([]);
const [testRunning, setTestRunning] = useState(false);
const [testFinished, setTestFinished] = useState(false);
const [showTestModal, setShowTestModal] = useState(false);
const [testPhone, setTestPhone] = useState("");
const [testSkipDelays, setTestSkipDelays] = useState(true);
const eventSourceRef = useRef<EventSource | null>(null);
```

- [ ] **Step 6: Implementar `startTest`**

```typescript
const startTest = useCallback(() => {
  if (!testPhone.trim()) return;
  setShowTestModal(false);
  setTestNodeStates({});
  setTestLog([]);
  setTestRunning(true);
  setTestFinished(false);
  setSelectedNodeId(null);

  const url = `/api/automation/campaigns/${campaignId}/test?phone=${encodeURIComponent(testPhone)}&skip_delays=${testSkipDelays}`;
  const es = new EventSource(url);
  eventSourceRef.current = es;

  es.onmessage = (e) => {
    const evt: TestEvent = JSON.parse(e.data);
    if (evt.status === "finished") {
      setTestRunning(false);
      setTestFinished(true);
      es.close();
      return;
    }
    if (!evt.node_id) return;
    setTestNodeStates(prev => ({ ...prev, [evt.node_id!]: evt.status as TestNodeState }));
    if (evt.status !== "running") {
      const node = dbNodes.find(n => n.id === evt.node_id);
      const meta = node ? NODE_META[node.type] : null;
      setTestLog(prev => [...prev, {
        ...evt,
        node_label: meta ? `${meta.icon} ${meta.label}` : evt.node_id ?? "",
      }]);
    }
  };
  es.onerror = () => {
    setTestRunning(false);
    es.close();
  };
}, [testPhone, testSkipDelays, campaignId, dbNodes]);

const closeTest = useCallback(() => {
  eventSourceRef.current?.close();
  setTestNodeStates({});
  setTestLog([]);
  setTestRunning(false);
  setTestFinished(false);
}, []);
```

- [ ] **Step 7: Passar `testState` para os nós no canvas**

Os nós React Flow recebem `data` do `rfNodes`. Atualizar `toRFNode` para incluir `testState` não é possível diretamente (é estático). Em vez disso, atualizar `rfNodes` quando `testNodeStates` muda:

```typescript
useEffect(() => {
  setRFNodes(prev => prev.map(n => ({
    ...n,
    data: { ...n.data, testState: testNodeStates[n.id] ?? null },
  })));
}, [testNodeStates, setRFNodes]);
```

- [ ] **Step 8: Exibir overlay de teste nos nós `CampaignFlowNode`**

Na função `CampaignFlowNode`, ler `testState` de `data` e renderizar overlay:

```tsx
const testState = (data.testState as TestNodeState | null) ?? null;
```

Dentro do JSX do nó, após o div principal, adicionar:

```tsx
{testState && (
  <div style={{
    position: "absolute", top: -8, right: -8,
    width: 22, height: 22, borderRadius: "50%",
    background: testState === "running" ? "#E85D26" : testState === "done" ? "#1A9B6C" : "#ef4444",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 11, color: "#fff",
    boxShadow: "0 2px 6px rgba(0,0,0,.2)",
    animation: testState === "running" ? "pulse 1s infinite" : "none",
  }}>
    {testState === "running" ? "⟳" : testState === "done" ? "✓" : "✗"}
  </div>
)}
```

Adicionar ao `FONT_STYLE`:
```css
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
```

E bordas coloridas por estado. No div raiz do nó, adicionar estilo condicional:

```tsx
boxShadow: testState === "running"
  ? "0 0 0 2px #E85D26, 0 4px 14px rgba(232,93,38,.3)"
  : testState === "done"
  ? "0 0 0 2px #1A9B6C, 0 4px 14px rgba(26,155,108,.2)"
  : testState === "failed"
  ? "0 0 0 2px #ef4444, 0 4px 14px rgba(239,68,68,.2)"
  : undefined,
```

- [ ] **Step 9: Adicionar botão "⚡ Testar" no topbar**

Após o botão "▶ Ativar campanha" no topbar de `FlowBuilderInner`:

```tsx
<button
  onClick={() => setShowTestModal(true)}
  style={{
    height: 34, padding: "0 16px", borderRadius: 7,
    background: "#fff", border: "1px solid #e0dbd4",
    color: "#555", fontFamily: "'Outfit', sans-serif",
    fontSize: 13, fontWeight: 500, cursor: "pointer",
    display: "flex", alignItems: "center", gap: 6,
  }}
>
  ⚡ Testar
</button>
```

- [ ] **Step 10: Modal de teste**

No JSX de `FlowBuilderInner`, antes do fechamento do `div` principal:

```tsx
{showTestModal && (
  <div style={{ position: "fixed", inset: 0, background: "rgba(17,17,17,.45)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }}>
    <div style={{ background: "#fff", borderRadius: 12, padding: 28, width: 380, boxShadow: "0 8px 32px rgba(0,0,0,.2)" }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 18, color: "#111" }}>⚡ Testar cadência</div>

      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".5px", color: "#b0a8a0", marginBottom: 5 }}>
          Número de teste (com DDI, ex: 5511999990000)
        </label>
        <input
          type="text"
          value={testPhone}
          onChange={e => setTestPhone(e.target.value)}
          placeholder="5511999990000"
          style={{ width: "100%", padding: "8px 11px", border: "1px solid #e0dbd4", borderRadius: 7, fontFamily: "'Outfit', sans-serif", fontSize: 13, color: "#111", background: "#faf9f6", outline: "none" }}
        />
      </div>

      <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", marginBottom: 20 }}>
        <input
          type="checkbox"
          checked={testSkipDelays}
          onChange={e => setTestSkipDelays(e.target.checked)}
        />
        <span style={{ fontSize: 13, color: "#444" }}>Pular delays ⏱ (recomendado)</span>
      </label>

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button
          onClick={() => setShowTestModal(false)}
          style={{ height: 34, padding: "0 14px", borderRadius: 7, border: "1px solid #e0dbd4", background: "#fff", color: "#555", fontFamily: "'Outfit', sans-serif", fontSize: 13, cursor: "pointer" }}
        >
          Cancelar
        </button>
        <button
          onClick={startTest}
          disabled={!testPhone.trim()}
          style={{ height: 34, padding: "0 16px", borderRadius: 7, border: "none", background: testPhone.trim() ? "#111" : "#ccc", color: "#fff", fontFamily: "'Outfit', sans-serif", fontSize: 13, cursor: testPhone.trim() ? "pointer" : "default" }}
        >
          ▶ Executar
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 11: Painel de execução (substitui Inspector durante teste)**

No lugar do `{selectedDbNode && <Inspector ... />}`, adicionar:

```tsx
{(testRunning || testFinished) ? (
  <div style={{ width: 256, flexShrink: 0, background: "#fff", borderLeft: "1px solid #e8e4df", display: "flex", flexDirection: "column", fontFamily: "'Outfit', sans-serif" }}>
    {/* Header */}
    <div style={{ padding: "14px 16px 12px", borderBottom: "1px solid #ede9e3", display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: "#111", flex: 1 }}>⚡ Execução de Teste</div>
      <button onClick={closeTest} style={{ width: 24, height: 24, borderRadius: 6, border: "1px solid #e0dbd4", background: "#faf9f6", cursor: "pointer", fontSize: 13, color: "#888" }}>✕</button>
    </div>

    {/* Log entries */}
    <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
      {testLog.length === 0 && testRunning && (
        <div style={{ fontSize: 13, color: "#9b9590", textAlign: "center", paddingTop: 24 }}>Iniciando execução...</div>
      )}
      {testLog.map((entry, i) => (
        <div key={i} style={{ marginBottom: 10, padding: "8px 10px", borderRadius: 7, background: entry.status === "failed" ? "#fff5f5" : "#f5faf7", border: `1px solid ${entry.status === "failed" ? "#fecaca" : "#d1fae5"}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
            <span style={{ fontSize: 12 }}>{entry.status === "done" ? "✅" : "❌"}</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#111" }}>{entry.node_label}</span>
            {entry.duration_ms !== undefined && (
              <span style={{ fontSize: 10, color: "#9b9590", marginLeft: "auto" }}>{entry.duration_ms}ms</span>
            )}
          </div>
          {entry.log && (
            <div style={{ fontSize: 11, color: entry.status === "failed" ? "#dc2626" : "#555", lineHeight: 1.5, wordBreak: "break-word" }}>
              {entry.log}
            </div>
          )}
        </div>
      ))}
      {testFinished && (
        <div style={{ textAlign: "center", paddingTop: 8 }}>
          <button
            onClick={() => { setShowTestModal(true); setTestFinished(false); setTestNodeStates({}); setTestLog([]); }}
            style={{ height: 30, padding: "0 14px", borderRadius: 7, border: "1px solid #e0dbd4", background: "#fff", color: "#555", fontFamily: "'Outfit', sans-serif", fontSize: 12, cursor: "pointer" }}
          >
            ↺ Testar novamente
          </button>
        </div>
      )}
    </div>
  </div>
) : selectedDbNode ? (
  <Inspector
    key={selectedDbNode.id}
    node={selectedDbNode}
    saving={saving}
    data={flowData}
    onSave={saveNode}
    onDelete={deleteNode}
    onClose={() => setSelectedNodeId(null)}
  />
) : null}
```

- [ ] **Step 12: Verificar TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Esperado: sem erros.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(flow-builder): add channel override per node, test mode SSE with n8n-style live execution"
```

---

## FASE 4 — Verificação Final

### Task 8: Smoke test e push

- [ ] **Step 1: Rodar todos os testes do backend**

```bash
cd backend && python -m pytest tests/test_automation_variables.py tests/test_automation_retry.py tests/test_automation_engine.py tests/test_automation_triggers.py tests/test_automation_test_runner.py tests/test_automation_engine_channel.py -v
```

Esperado: todos PASS.

- [ ] **Step 2: Build do frontend**

```bash
cd frontend && NEXT_PUBLIC_SUPABASE_URL=https://placeholder.supabase.co NEXT_PUBLIC_SUPABASE_ANON_KEY=placeholder NEXT_PUBLIC_FASTAPI_URL=http://placeholder.api.local npm run build
```

Esperado: build sem erros.

- [ ] **Step 3: Testar manualmente (checklist)**

- [ ] Criar nova cadência → modal pede canal → selecionado → criada
- [ ] Abrir cadência → adicionar nó `send` → Inspector mostra campo "Canal (override)"
- [ ] Clicar "⚡ Testar" → modal aparece com input de telefone + checkbox pular delays
- [ ] Executar teste → nós animam (laranja running → verde done ou vermelho failed)
- [ ] Painel direito mostra log por nó com duração
- [ ] Botão "↺ Testar novamente" aparece ao final
- [ ] Botão "✕ Fechar" restaura flow builder normal

- [ ] **Step 4: Push para produção**

```bash
git push origin master
```
