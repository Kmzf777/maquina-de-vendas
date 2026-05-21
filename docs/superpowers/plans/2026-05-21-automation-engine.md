# Automation Engine — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND RULE:** Qualquer task que toque arquivos em `frontend/` DEVE invocar a skill `frontend-design` antes de escrever código.

**Goal:** Unificar os módulos `cadence/` e `campaigns/` em um único motor de automação com triggers event-driven, retry, frequency cap e priority, usando todos os dados disponíveis no CRM (leads, deals, sales, tags).

**Architecture:** Novo módulo `backend/app/automation/` com engine, triggers e variables. Os triggers pontuais (venda criada, mudança de stage, tag adicionada) são event-driven via hooks nos endpoints existentes. Triggers de inatividade (sem mensagem, estagnação, ciclo de recompra) continuam em polling no `run_worker()`. O frontend recebe novos tipos de nó, trigger, condição e ação no flow builder.

**Tech Stack:** Python 3.12, FastAPI, Supabase Python client, pytest/unittest.mock, React 18, TypeScript, @xyflow/react

**Spec:** `docs/superpowers/specs/2026-05-21-automation-engine-design.md`

---

## FASE 1 — Banco de Dados

### Task 1: Migrations SQL

**Files:**
- Create: `supabase/migrations/20260521_automation_engine.sql`

**Contexto:** Execute este SQL no Supabase SQL Editor (Dashboard → SQL Editor). Não há CLI de migrations configurado no projeto.

- [ ] **Step 1: Criar o arquivo de migration**

```sql
-- supabase/migrations/20260521_automation_engine.sql

-- 1. Colunas novas em campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS priority      INT NOT NULL DEFAULT 5,
  ADD COLUMN IF NOT EXISTS frequency_cap INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS send_start_hour INT NOT NULL DEFAULT 7,
  ADD COLUMN IF NOT EXISTS send_end_hour   INT NOT NULL DEFAULT 18;

-- 2. Colunas novas em campaign_enrollments
ALTER TABLE campaign_enrollments
  ADD COLUMN IF NOT EXISTS retry_count    INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS last_error     TEXT,
  ADD COLUMN IF NOT EXISTS next_retry_at  TIMESTAMPTZ;

-- 3. Tabela de controle de frequência diária
CREATE TABLE IF NOT EXISTS lead_daily_sends (
  lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  date    DATE NOT NULL,
  count   INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (lead_id, date)
);

-- 4. Função para incremento atômico
CREATE OR REPLACE FUNCTION increment_daily_send(p_lead_id UUID, p_date DATE)
RETURNS VOID AS $$
BEGIN
  INSERT INTO lead_daily_sends (lead_id, date, count)
  VALUES (p_lead_id, p_date, 1)
  ON CONFLICT (lead_id, date)
  DO UPDATE SET count = lead_daily_sends.count + 1;
END;
$$ LANGUAGE plpgsql;

-- 5. Função para repurchase_window trigger (GROUP BY não disponível via PostgREST)
CREATE OR REPLACE FUNCTION get_leads_for_repurchase(cutoff_date TIMESTAMPTZ, p_env_tag TEXT)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.env_tag = p_env_tag
    AND l.ai_enabled = TRUE
  AND EXISTS (SELECT 1 FROM sales s WHERE s.lead_id = l.id)
  AND (
    SELECT MAX(s2.sold_at) FROM sales s2 WHERE s2.lead_id = l.id
  ) <= cutoff_date;
$$ LANGUAGE sql;

-- 6. Função para no_sale_in_stage trigger
CREATE OR REPLACE FUNCTION get_leads_no_sale_in_stage(
  p_stage TEXT,
  cutoff_date TIMESTAMPTZ,
  p_env_tag TEXT
)
RETURNS TABLE(id UUID, phone TEXT) AS $$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.env_tag = p_env_tag
    AND l.stage = p_stage
    AND l.ai_enabled = TRUE
    AND l.entered_stage_at IS NOT NULL
    AND l.entered_stage_at <= cutoff_date
    AND NOT EXISTS (
      SELECT 1 FROM sales s WHERE s.lead_id = l.id
    );
$$ LANGUAGE sql;
```

- [ ] **Step 2: Executar no Supabase SQL Editor**

Abrir Supabase Dashboard → SQL Editor → colar e executar o SQL acima.
Verificar que não há erros. As colunas e funções devem aparecer no schema.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260521_automation_engine.sql
git commit -m "feat(automation): add DB migrations — priority, frequency_cap, retry, lead_daily_sends"
```

---

## FASE 2 — Backend: Módulo `automation/`

### Task 2: `automation/variables.py` + testes

**Files:**
- Create: `backend/app/automation/__init__.py`
- Create: `backend/app/automation/variables.py`
- Create: `backend/tests/test_automation_variables.py`

**Contexto:** Substitui a função `_substitute_variables` do `cadence/scheduler.py`. Adiciona variáveis de sales, deals e vendedor. Variáveis ausentes viram string vazia — nunca lançam erro.

- [ ] **Step 1: Criar `__init__.py`**

```python
# backend/app/automation/__init__.py
```

- [ ] **Step 2: Escrever teste antes da implementação**

```python
# backend/tests/test_automation_variables.py
import pytest
from unittest.mock import patch, MagicMock
from app.automation.variables import substitute_variables

LEAD = {
    "id": "lead-001",
    "name": "João Silva",
    "company": "Empresa X",
    "phone": "5511999990000",
    "assigned_to": None,
}

ENROLLMENT = {"lead_id": "lead-001"}


class TestSubstituteVariables:
    def test_basic_lead_vars(self):
        result = substitute_variables("Olá {{nome}} da {{empresa}}", LEAD, ENROLLMENT)
        assert result == "Olá João Silva da Empresa X"

    def test_missing_name_becomes_empty(self):
        lead = {**LEAD, "name": None}
        result = substitute_variables("Olá {{nome}}!", lead, ENROLLMENT)
        assert result == "Olá !"

    def test_phone_var(self):
        result = substitute_variables("Seu telefone: {{telefone}}", LEAD, ENROLLMENT)
        assert result == "Seu telefone: 5511999990000"

    def test_sale_vars_with_sale(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"product": "Café Especial", "value": 150.50, "sold_at": "2026-05-10T10:00:00+00:00"}
        ]
        with patch("app.automation.variables.get_supabase", return_value=mock_sb):
            result = substitute_variables("Comprou {{produto}} por {{valor_ultima_venda}}", LEAD, ENROLLMENT)
        assert "Café Especial" in result
        assert "R$" in result

    def test_sale_vars_without_sale(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        with patch("app.automation.variables.get_supabase", return_value=mock_sb):
            result = substitute_variables("Produto: {{produto}}", LEAD, ENROLLMENT)
        assert result == "Produto: "

    def test_no_db_call_when_no_sale_vars(self):
        with patch("app.automation.variables.get_supabase") as mock_get_sb:
            substitute_variables("Olá {{nome}}", LEAD, ENROLLMENT)
        mock_get_sb.assert_not_called()
```

- [ ] **Step 3: Rodar teste para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_variables.py -v
```
Esperado: `ModuleNotFoundError` ou `ImportError` — módulo não existe ainda.

- [ ] **Step 4: Implementar `variables.py`**

```python
# backend/app/automation/variables.py
from datetime import datetime, timezone


def substitute_variables(text: str, lead: dict, enrollment: dict | None = None) -> str:
    """Replace {{var}} placeholders with CRM data. Missing data → empty string."""
    replacements: dict[str, str] = {
        "{{nome}}":     lead.get("name") or "",
        "{{empresa}}":  lead.get("company") or "",
        "{{telefone}}": lead.get("phone") or "",
    }

    _fill_sale_vars(text, lead, replacements)
    _fill_seller_var(text, lead, replacements)
    _fill_deal_vars(text, lead, replacements)

    for var, value in replacements.items():
        text = text.replace(var, value)
    return text


def _fill_sale_vars(text: str, lead: dict, out: dict) -> None:
    if not any(v in text for v in ("{{produto}}", "{{valor_ultima_venda}}", "{{dias_sem_compra}}")):
        return
    from app.db.supabase import get_supabase
    sb = get_supabase()
    rows = (
        sb.table("sales")
        .select("product, value, sold_at")
        .eq("lead_id", lead["id"])
        .order("sold_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if rows:
        s = rows[0]
        out["{{produto}}"] = s.get("product") or ""
        raw_val = float(s.get("value") or 0)
        out["{{valor_ultima_venda}}"] = (
            f"R$ {raw_val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        )
        from dateutil.parser import parse
        sold_at = parse(s["sold_at"]) if isinstance(s["sold_at"], str) else s["sold_at"]
        days = (datetime.now(timezone.utc) - sold_at).days
        out["{{dias_sem_compra}}"] = str(days)
    else:
        out["{{produto}}"] = ""
        out["{{valor_ultima_venda}}"] = ""
        out["{{dias_sem_compra}}"] = ""


def _fill_seller_var(text: str, lead: dict, out: dict) -> None:
    if "{{vendedor}}" not in text:
        return
    assigned = lead.get("assigned_to")
    if not assigned:
        out["{{vendedor}}"] = ""
        return
    from app.db.supabase import get_supabase
    sb = get_supabase()
    rows = sb.table("team_users").select("name").eq("id", assigned).limit(1).execute().data
    out["{{vendedor}}"] = rows[0]["name"] if rows else ""


def _fill_deal_vars(text: str, lead: dict, out: dict) -> None:
    if not any(v in text for v in ("{{deal_titulo}}", "{{pipeline}}")):
        return
    from app.db.supabase import get_supabase
    sb = get_supabase()
    rows = (
        sb.table("deals")
        .select("title, pipelines!inner(name)")
        .eq("lead_id", lead["id"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    if rows:
        d = rows[0]
        out["{{deal_titulo}}"] = d.get("title") or ""
        out["{{pipeline}}"] = (d.get("pipelines") or {}).get("name") or ""
    else:
        out["{{deal_titulo}}"] = ""
        out["{{pipeline}}"] = ""
```

- [ ] **Step 5: Rodar testes para confirmar passagem**

```bash
cd backend && python -m pytest tests/test_automation_variables.py -v
```
Esperado: todos os 6 testes PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/automation/ backend/tests/test_automation_variables.py
git commit -m "feat(automation): add variables.py with enriched template substitution"
```

---

### Task 3: `automation/retry.py` + testes

**Files:**
- Create: `backend/app/automation/retry.py`
- Create: `backend/tests/test_automation_retry.py`

- [ ] **Step 1: Escrever testes**

```python
# backend/tests/test_automation_retry.py
import pytest
from datetime import datetime, timezone, timedelta
from app.automation.retry import calculate_next_retry

NOW = datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc)


class TestCalculateNextRetry:
    def test_first_retry_is_1h(self):
        next_at, count, final = calculate_next_retry(0, NOW)
        assert next_at == NOW + timedelta(hours=1)
        assert count == 1
        assert final is False

    def test_second_retry_is_4h(self):
        next_at, count, final = calculate_next_retry(1, NOW)
        assert next_at == NOW + timedelta(hours=4)
        assert count == 2
        assert final is False

    def test_third_retry_is_24h(self):
        next_at, count, final = calculate_next_retry(2, NOW)
        assert next_at == NOW + timedelta(hours=24)
        assert count == 3
        assert final is False

    def test_after_max_retries_is_final(self):
        _, _, final = calculate_next_retry(3, NOW)
        assert final is True

    def test_after_max_retries_count_unchanged(self):
        _, count, _ = calculate_next_retry(3, NOW)
        assert count == 3
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_retry.py -v
```

- [ ] **Step 3: Implementar**

```python
# backend/app/automation/retry.py
from datetime import datetime, timedelta

_BACKOFF = [timedelta(hours=1), timedelta(hours=4), timedelta(hours=24)]
_MAX_RETRIES = len(_BACKOFF)


def calculate_next_retry(retry_count: int, now: datetime) -> tuple[datetime, int, bool]:
    """
    Returns (next_retry_at, new_retry_count, is_final_failure).
    is_final_failure=True when retry_count >= MAX_RETRIES.
    """
    if retry_count >= _MAX_RETRIES:
        return now, retry_count, True
    return now + _BACKOFF[retry_count], retry_count + 1, False
```

- [ ] **Step 4: Confirmar PASS**

```bash
cd backend && python -m pytest tests/test_automation_retry.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/retry.py backend/tests/test_automation_retry.py
git commit -m "feat(automation): add retry.py with exponential backoff"
```

---

### Task 4: `automation/engine.py`

**Files:**
- Create: `backend/app/automation/engine.py`
- Create: `backend/tests/test_automation_engine.py`

**Contexto:** Engine central. Substitui `process_campaign_enrollments()` de `campaigns/worker.py`. Adiciona frequency cap, priority ordering, retry, e suporte a `send_text`. Importa `_execute_send_node` do `campaigns/worker.py` para reuso (não duplicar lógica de template).

- [ ] **Step 1: Escrever testes**

```python
# backend/tests/test_automation_engine.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.automation.engine import check_frequency_cap, _compare

NOW = datetime(2026, 5, 21, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT


class TestCheckFrequencyCap:
    def test_no_sends_today_allows(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            assert check_frequency_cap("lead-1", 1) is True

    def test_at_cap_blocks(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"count": 1}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            assert check_frequency_cap("lead-1", 1) is False

    def test_below_cap_allows(self):
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{"count": 1}]
        with patch("app.automation.engine.get_supabase", return_value=mock_sb):
            assert check_frequency_cap("lead-1", 2) is True


class TestCompare:
    def test_gte(self):
        assert _compare(5, "gte", 3) is True
        assert _compare(2, "gte", 3) is False

    def test_lte(self):
        assert _compare(2, "lte", 3) is True
        assert _compare(5, "lte", 3) is False

    def test_eq(self):
        assert _compare(3, "eq", 3) is True
        assert _compare(4, "eq", 3) is False

    def test_unknown_operator_returns_false(self):
        assert _compare(5, "unknown", 3) is False
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_engine.py -v
```

- [ ] **Step 3: Implementar `engine.py`**

```python
# backend/app/automation/engine.py
import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta, date

from app.db.supabase import get_supabase
from app.config import get_settings
from app.automation.variables import substitute_variables
from app.automation.retry import calculate_next_retry

logger = logging.getLogger(__name__)
_ENV_TAG = "dev" if get_settings().is_dev_env else "production"
BRT_OFFSET = timedelta(hours=-3)


def check_frequency_cap(lead_id: str, cap: int) -> bool:
    sb = get_supabase()
    today = date.today().isoformat()
    result = (
        sb.table("lead_daily_sends")
        .select("count")
        .eq("lead_id", lead_id)
        .eq("date", today)
        .execute()
    )
    current = result.data[0]["count"] if result.data else 0
    return current < cap


def record_daily_send(lead_id: str) -> None:
    sb = get_supabase()
    sb.rpc("increment_daily_send", {
        "p_lead_id": lead_id,
        "p_date": date.today().isoformat(),
    }).execute()


def _is_within_window(now_utc: datetime, start_hour: int = 7, end_hour: int = 18) -> bool:
    brt = now_utc + BRT_OFFSET
    return start_hour <= brt.hour < end_hour


def _next_window_start(now_utc: datetime, start_hour: int = 7) -> datetime:
    brt = now_utc + BRT_OFFSET
    if brt.hour < start_hour:
        target = brt.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    else:
        target = (brt + timedelta(days=1)).replace(hour=start_hour, minute=0, second=0, microsecond=0)
    return target - BRT_OFFSET


def _compare(actual: float, op: str, target: float) -> bool:
    return {
        "gte": actual >= target,
        "lte": actual <= target,
        "gt":  actual > target,
        "lt":  actual < target,
        "eq":  actual == target,
    }.get(op, False)


def get_due_enrollments(now: datetime, limit: int = 20) -> list[dict]:
    sb = get_supabase()
    return (
        sb.table("campaign_enrollments")
        .select(
            "*, "
            "leads!inner(id, phone, name, company, stage, ai_enabled, last_customer_message_at, assigned_to), "
            "campaign_nodes!campaign_enrollments_current_node_id_fkey(*), "
            "campaigns!inner(id, name, status, priority, frequency_cap, send_start_hour, send_end_hour)"
        )
        .eq("status", "active")
        .eq("env_tag", _ENV_TAG)
        .lte("next_execute_at", now.isoformat())
        .limit(limit)
        .execute()
        .data
    )


def _update(enrollment_id: str, **kwargs) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update(kwargs).eq("id", enrollment_id).execute()


def _complete(enrollment_id: str) -> None:
    sb = get_supabase()
    sb.table("campaign_enrollments").update({
        "status": "completed",
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", enrollment_id).execute()


def _fail_enrollment(enrollment_id: str, retry_count: int, error: str, now: datetime) -> None:
    next_retry, new_count, final = calculate_next_retry(retry_count, now)
    if final:
        _update(enrollment_id, status="failed", last_error=error[:500])
    else:
        _update(enrollment_id,
                retry_count=new_count,
                last_error=error[:500],
                next_execute_at=next_retry.isoformat(),
                next_retry_at=next_retry.isoformat())


async def process_due_enrollments(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    enrollments = get_due_enrollments(now)
    # Sort by campaign priority descending (highest priority first)
    enrollments.sort(key=lambda e: (e.get("campaigns") or {}).get("priority", 5), reverse=True)
    for enrollment in enrollments:
        await _process_one(enrollment, now)
        await asyncio.sleep(random.randint(1, 3))


async def _process_one(enrollment: dict, now: datetime) -> None:
    node = enrollment.get("campaign_nodes")
    lead = enrollment["leads"]
    campaign = enrollment.get("campaigns") or {}

    if not node or campaign.get("status") != "active":
        return
    if not lead.get("ai_enabled", True):
        return

    node_type = node["type"]
    cfg = node.get("config") or {}

    try:
        if node_type in ("send", "send_text"):
            start_h = campaign.get("send_start_hour", 7)
            end_h   = campaign.get("send_end_hour", 18)
            if not _is_within_window(now, start_h, end_h):
                _update(enrollment["id"], next_execute_at=_next_window_start(now, start_h).isoformat())
                return
            if not check_frequency_cap(lead["id"], campaign.get("frequency_cap", 1)):
                _update(enrollment["id"], next_execute_at=_next_window_start(now, start_h).isoformat())
                return
            if node_type == "send":
                await _execute_send(enrollment, node, lead, now)
            else:
                await _execute_send_text(enrollment, node, lead, now)
            record_daily_send(lead["id"])

        elif node_type == "wait":
            days    = cfg.get("days", 1)
            start_h = cfg.get("send_start_hour", 7)
            end_h   = cfg.get("send_end_hour", 18)
            target  = now + timedelta(days=days)
            if not _is_within_window(target, start_h, end_h):
                target = _next_window_start(target, start_h)
            _update(enrollment["id"], next_execute_at=target.isoformat())
            return

        elif node_type == "condition":
            _execute_condition(enrollment, node, lead, now)
            return

        elif node_type == "action":
            _execute_action(enrollment, node, lead)

        elif node_type == "end":
            _execute_end(enrollment, node, lead)
            _complete(enrollment["id"])
            return

        # Advance to next node
        next_id = node.get("next_node_id")
        if next_id:
            _update(enrollment["id"],
                    current_node_id=next_id,
                    next_execute_at=now.isoformat(),
                    retry_count=0,
                    last_error=None)
        else:
            _complete(enrollment["id"])

    except Exception as e:
        logger.error("[AUTOMATION] enrollment=%s node=%s error=%s",
                     enrollment["id"], node.get("id"), e, exc_info=True)
        _fail_enrollment(enrollment["id"], enrollment.get("retry_count", 0), str(e), now)


async def _execute_send(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.campaigns.worker import _execute_send_node
    await _execute_send_node(enrollment, node, lead, now)


async def _execute_send_text(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    from app.whatsapp.registry import get_provider
    from app.channels.service import get_channel_for_lead
    from app.leads.service import save_message

    cfg = node.get("config") or {}

    # Check 24h window using last_customer_message_at
    last_msg = lead.get("last_customer_message_at")
    if last_msg:
        from dateutil.parser import parse
        if isinstance(last_msg, str):
            last_msg = parse(last_msg)
        if (now - last_msg).total_seconds() > 86400:
            _update(enrollment["id"], last_error="24h_window_expired")
            return  # advance without failing

    message = substitute_variables(cfg.get("message_text", ""), lead, enrollment)
    channel = get_channel_for_lead(enrollment["lead_id"])
    if not channel:
        raise ValueError(f"No channel for lead {lead['phone']}")

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


def _execute_condition(enrollment: dict, node: dict, lead: dict, now: datetime) -> None:
    sb = get_supabase()
    cfg = node.get("config") or {}
    cond = cfg.get("condition_type", "replied_recently")
    result = False

    if cond == "replied_recently":
        cutoff = (now - timedelta(days=cfg.get("days", 5))).isoformat()
        msgs = sb.table("messages").select("id").eq("lead_id", enrollment["lead_id"]).eq("role", "user").gte("created_at", cutoff).limit(1).execute()
        result = len(msgs.data) > 0

    elif cond == "in_stage":
        fresh = sb.table("leads").select("stage").eq("id", enrollment["lead_id"]).single().execute().data
        result = (fresh or {}).get("stage") == cfg.get("stage")

    elif cond == "has_deal":
        result = bool(sb.table("deals").select("id").eq("lead_id", enrollment["lead_id"]).limit(1).execute().data)

    elif cond == "sale_count":
        res = sb.table("sales").select("id", count="exact").eq("lead_id", enrollment["lead_id"]).execute()
        result = _compare(res.count or 0, cfg.get("operator", "gte"), cfg.get("value", 1))

    elif cond == "total_spend":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).execute().data or []
        total = sum(float(r["value"]) for r in rows)
        result = _compare(total, cfg.get("operator", "gte"), cfg.get("value", 0))

    elif cond == "last_sale_value":
        rows = sb.table("sales").select("value").eq("lead_id", enrollment["lead_id"]).order("sold_at", desc=True).limit(1).execute().data
        val = float(rows[0]["value"]) if rows else 0
        result = _compare(val, cfg.get("operator", "gte"), cfg.get("value", 0))

    elif cond == "deal_value":
        rows = sb.table("deals").select("value").eq("lead_id", enrollment["lead_id"]).order("created_at", desc=True).limit(1).execute().data
        val = float(rows[0]["value"]) if rows else 0
        result = _compare(val, cfg.get("operator", "gte"), cfg.get("value", 0))

    elif cond == "has_tag":
        tag_name = cfg.get("tag_name", "")
        tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
        if tag_row:
            lt = sb.table("lead_tags").select("id").eq("lead_id", enrollment["lead_id"]).eq("tag_id", tag_row[0]["id"]).limit(1).execute()
            result = bool(lt.data)

    elif cond == "repurchase_days":
        rows = sb.table("sales").select("sold_at").eq("lead_id", enrollment["lead_id"]).order("sold_at", desc=True).limit(1).execute().data
        if rows:
            from dateutil.parser import parse
            sold_at = parse(rows[0]["sold_at"]) if isinstance(rows[0]["sold_at"], str) else rows[0]["sold_at"]
            days_since = (now - sold_at).days
            result = _compare(days_since, cfg.get("operator", "gte"), cfg.get("value", 30))

    next_node_id = node["yes_node_id"] if result else node["no_node_id"]
    if next_node_id:
        _update(enrollment["id"], current_node_id=next_node_id, next_execute_at=now.isoformat())
    else:
        _complete(enrollment["id"])
    logger.info("[AUTOMATION] condition '%s' → %s for %s", cond, "YES" if result else "NO", lead["phone"])


def _execute_action(enrollment: dict, node: dict, lead: dict) -> None:
    sb = get_supabase()
    cfg = node.get("config") or {}
    action_type = cfg.get("action_type")

    if action_type == "move_stage":
        stage_id = cfg.get("stage_id")
        if stage_id:
            sb.table("deals").update({"stage_id": stage_id}).eq("lead_id", enrollment["lead_id"]).execute()

    elif action_type == "activate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=True, human_control=False)

    elif action_type == "deactivate_agent":
        from app.leads.service import update_lead
        update_lead(enrollment["lead_id"], ai_enabled=False)

    elif action_type == "add_tag":
        tag_name = (cfg.get("tag_name") or "").strip()
        if tag_name:
            tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
            if tag_row:
                try:
                    sb.table("lead_tags").insert({"lead_id": enrollment["lead_id"], "tag_id": tag_row[0]["id"]}).execute()
                except Exception:
                    pass  # já tem essa tag

    elif action_type == "remove_tag":
        tag_name = (cfg.get("tag_name") or "").strip()
        if tag_name:
            tag_row = sb.table("tags").select("id").eq("name", tag_name).limit(1).execute().data
            if tag_row:
                sb.table("lead_tags").delete().eq("lead_id", enrollment["lead_id"]).eq("tag_id", tag_row[0]["id"]).execute()

    elif action_type == "create_deal":
        from app.leads.service import create_deal
        title = substitute_variables(cfg.get("title_template", "Deal automático"), lead, enrollment)
        create_deal(enrollment["lead_id"], title, cfg.get("category"))

    elif action_type == "assign_to":
        user_id = cfg.get("user_id")
        if user_id:
            from app.leads.service import update_lead
            update_lead(enrollment["lead_id"], assigned_to=user_id)

    logger.info("[AUTOMATION] action '%s' for %s", action_type, lead.get("phone"))


def _execute_end(enrollment: dict, node: dict, lead: dict) -> None:
    for action_cfg in (node.get("config") or {}).get("final_actions", []):
        fake_node = {"config": action_cfg, "type": "action"}
        _execute_action(enrollment, fake_node, lead)
```

- [ ] **Step 4: Rodar testes para confirmar PASS**

```bash
cd backend && python -m pytest tests/test_automation_engine.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/engine.py backend/tests/test_automation_engine.py
git commit -m "feat(automation): add engine.py — frequency cap, priority, retry, send_text, all conditions and actions"
```

---

### Task 5: `automation/triggers.py`

**Files:**
- Create: `backend/app/automation/triggers.py`
- Create: `backend/tests/test_automation_triggers.py`

**Contexto:** Dois modos: `fire_trigger()` para eventos pontuais (chamado via hooks), e `check_polling_triggers()` que substitui `check_campaign_triggers()` + `process_stagnation_triggers()`. Reutiliza `get_campaigns_with_trigger_type` e `is_already_enrolled` de `campaigns/service.py`.

- [ ] **Step 1: Escrever testes**

```python
# backend/tests/test_automation_triggers.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from app.automation.triggers import _passes_filter, fire_trigger


class TestPassesFilter:
    def test_stage_enter_matches(self):
        assert _passes_filter("stage_enter", {"stage_filter": "negociacao"}, {"stage": "negociacao"}) is True

    def test_stage_enter_no_match(self):
        assert _passes_filter("stage_enter", {"stage_filter": "proposta"}, {"stage": "negociacao"}) is False

    def test_stage_enter_no_filter_passes_all(self):
        assert _passes_filter("stage_enter", {}, {"stage": "qualquer"}) is True

    def test_sale_created_min_value_passes(self):
        assert _passes_filter("sale_created", {"min_value": 100}, {"value": 200}) is True

    def test_sale_created_min_value_blocks(self):
        assert _passes_filter("sale_created", {"min_value": 300}, {"value": 200}) is False

    def test_sale_created_product_filter_passes(self):
        assert _passes_filter("sale_created", {"product_filter": "café"}, {"product": "Café Especial"}) is True

    def test_sale_created_product_filter_blocks(self):
        assert _passes_filter("sale_created", {"product_filter": "café"}, {"product": "Chá"}) is False

    def test_tag_added_matches(self):
        assert _passes_filter("tag_added", {"tag_name": "VIP"}, {"tag_name": "VIP"}) is True

    def test_deal_closed_lost_always_passes(self):
        assert _passes_filter("deal_closed_lost", {}, {}) is True


@pytest.mark.asyncio
async def test_fire_trigger_enrolls_matching_lead():
    trigger_node = {
        "campaign_id": "camp-1",
        "next_node_id": "node-1",
        "config": {"stage_filter": "negociacao"},
    }
    with (
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[trigger_node]),
        patch("app.automation.triggers.is_already_enrolled", return_value=False),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await fire_trigger("stage_enter", "lead-1", {"stage": "negociacao"})
    mock_enroll.assert_called_once()


@pytest.mark.asyncio
async def test_fire_trigger_skips_already_enrolled():
    trigger_node = {
        "campaign_id": "camp-1",
        "next_node_id": "node-1",
        "config": {},
    }
    with (
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[trigger_node]),
        patch("app.automation.triggers.is_already_enrolled", return_value=True),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await fire_trigger("sale_created", "lead-1", {})
    mock_enroll.assert_not_called()
```

- [ ] **Step 2: Rodar para confirmar falha**

```bash
cd backend && python -m pytest tests/test_automation_triggers.py -v
```

- [ ] **Step 3: Implementar `triggers.py`**

```python
# backend/app/automation/triggers.py
import logging
from datetime import datetime, timezone, timedelta

from app.db.supabase import get_supabase
from app.config import get_settings
from app.campaigns.service import (
    get_campaigns_with_trigger_type,
    is_already_enrolled,
    create_enrollment,
)

logger = logging.getLogger(__name__)
_ENV_TAG = "dev" if get_settings().is_dev_env else "production"


async def fire_trigger(event_type: str, lead_id: str, data: dict | None = None) -> None:
    """Event-driven: enroll lead in all active campaigns with matching trigger."""
    data = data or {}
    now = datetime.now(timezone.utc)

    for trigger_node in get_campaigns_with_trigger_type(event_type):
        if not _passes_filter(event_type, trigger_node.get("config") or {}, data):
            continue
        if is_already_enrolled(trigger_node["campaign_id"], lead_id):
            continue
        if not trigger_node.get("next_node_id"):
            continue
        try:
            create_enrollment(
                campaign_id=trigger_node["campaign_id"],
                lead_id=lead_id,
                current_node_id=trigger_node["next_node_id"],
                next_execute_at=now,
                deal_id=data.get("deal_id"),
            )
            logger.info("[AUTOMATION] Enrolled %s via %s", lead_id, event_type)
        except Exception as e:
            logger.warning("[AUTOMATION] Failed to enroll %s via %s: %s", lead_id, event_type, e)


def _passes_filter(event_type: str, cfg: dict, data: dict) -> bool:
    if event_type in ("stage_enter", "deal_stage_enter"):
        stage_filter = cfg.get("stage_filter")
        return not stage_filter or data.get("stage") == stage_filter

    if event_type == "sale_created":
        if cfg.get("min_value") and float(data.get("value", 0)) < cfg["min_value"]:
            return False
        if cfg.get("product_filter"):
            if cfg["product_filter"].lower() not in (data.get("product") or "").lower():
                return False
        return True

    if event_type == "tag_added":
        tag_filter = cfg.get("tag_name")
        return not tag_filter or data.get("tag_name") == tag_filter

    return True  # deal_closed_lost, post_broadcast — sem filtro adicional


async def check_polling_triggers(now: datetime | None = None) -> None:
    """Polling: detect inactivity-based conditions and enroll leads."""
    now = now or datetime.now(timezone.utc)
    sb = get_supabase()

    # ── no_message ────────────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_message"):
        cfg = tn.get("config") or {}
        days, stage_filter = cfg.get("days", 30), cfg.get("stage_filter")
        cutoff = (now - timedelta(days=days)).isoformat()
        q = sb.table("leads").select("id, phone").eq("env_tag", _ENV_TAG).eq("ai_enabled", True).lte("last_msg_at", cutoff)
        if stage_filter:
            q = q.eq("stage", stage_filter)
        for lead in q.limit(20).execute().data:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── stage_stagnation ──────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("stage_stagnation"):
        cfg = tn.get("config") or {}
        stage, days = cfg.get("stage_filter"), cfg.get("days", 7)
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        leads = (
            sb.table("leads").select("id, phone")
            .eq("env_tag", _ENV_TAG).eq("ai_enabled", True).eq("stage", stage)
            .not_.is_("entered_stage_at", "null").lte("entered_stage_at", cutoff)
            .limit(20).execute().data
        )
        for lead in leads:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── repurchase_window ─────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("repurchase_window"):
        cfg = tn.get("config") or {}
        days = cfg.get("days", 30)
        cutoff = (now - timedelta(days=days)).isoformat()
        results = sb.rpc("get_leads_for_repurchase", {"cutoff_date": cutoff, "p_env_tag": _ENV_TAG}).execute().data or []
        for lead in results:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)

    # ── no_sale_in_stage ──────────────────────────────────────────────────────
    for tn in get_campaigns_with_trigger_type("no_sale_in_stage"):
        cfg = tn.get("config") or {}
        stage, days = cfg.get("stage_filter"), cfg.get("days", 7)
        if not stage:
            continue
        cutoff = (now - timedelta(days=days)).isoformat()
        results = sb.rpc("get_leads_no_sale_in_stage", {"p_stage": stage, "cutoff_date": cutoff, "p_env_tag": _ENV_TAG}).execute().data or []
        for lead in results:
            if not is_already_enrolled(tn["campaign_id"], lead["id"]) and tn.get("next_node_id"):
                _safe_enroll(tn, lead["id"], now)


def _safe_enroll(trigger_node: dict, lead_id: str, now: datetime) -> None:
    try:
        create_enrollment(trigger_node["campaign_id"], lead_id, trigger_node["next_node_id"], now)
        logger.info("[AUTOMATION] polling enrolled %s via %s", lead_id, trigger_node.get("type"))
    except Exception as e:
        logger.warning("[AUTOMATION] polling enroll failed: %s", e)
```

- [ ] **Step 4: Rodar testes**

```bash
cd backend && python -m pytest tests/test_automation_triggers.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/triggers.py backend/tests/test_automation_triggers.py
git commit -m "feat(automation): add triggers.py — event-driven fire_trigger + polling check"
```

---

### Task 6: `automation/router.py` + registrar em `main.py` + atualizar `run_worker()`

**Files:**
- Create: `backend/app/automation/router.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/broadcast/worker.py`

**Contexto:** O router expõe o endpoint `POST /api/automation/trigger` para hooks do Next.js. O `run_worker()` substitui as chamadas antigas por `process_due_enrollments()` + `check_polling_triggers()`. As rotas de cadências e campaigns são mantidas para não quebrar o frontend atual durante a transição.

- [ ] **Step 1: Criar `automation/router.py`**

```python
# backend/app/automation/router.py
from fastapi import APIRouter, BackgroundTasks
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
```

- [ ] **Step 2: Registrar em `main.py`**

Adicionar ao bloco de imports de routers em `backend/app/main.py` (após linha `from app.campaigns.router import router as campaigns_router`):

```python
from app.automation.router import router as automation_router
```

Adicionar ao bloco de `app.include_router(...)` (após `app.include_router(campaigns_router)`):

```python
app.include_router(automation_router)
```

- [ ] **Step 3: Atualizar `run_worker()` em `broadcast/worker.py`**

Localizar a função `run_worker()` (linha ~267) e substituir o bloco interno por:

```python
async def run_worker():
    """Main worker loop: broadcasts, automation engine, follow-ups."""
    logger.info("Worker started")

    while True:
        try:
            from app.automation.engine import process_due_enrollments
            from app.automation.triggers import check_polling_triggers
            await process_scheduled_broadcasts()
            await process_broadcasts()
            await check_polling_triggers()
            await process_due_enrollments()
            await process_due_followups()
            reconcile_broadcast_replies()
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)

        await asyncio.sleep(5)
```

Remover os imports no topo do arquivo `broadcast/worker.py` que não são mais usados:
- `from app.cadence.scheduler import process_due_cadences, process_reengagements, process_stagnation_triggers`

- [ ] **Step 4: Verificar que o backend inicia sem erro**

```bash
cd backend && python -m uvicorn app.main:app --port 8001 --reload
```
Esperado: servidor sobe sem `ImportError`. Verificar no log que `Worker started` aparece.

- [ ] **Step 5: Commit**

```bash
git add backend/app/automation/router.py backend/app/main.py backend/app/broadcast/worker.py
git commit -m "feat(automation): register automation router, replace worker with unified engine"
```

---

## FASE 3 — Event Hooks

### Task 7: Hooks de mudança de stage (leads e deals)

**Files:**
- Modify: `backend/app/leads/router.py`
- Modify: `frontend/src/app/api/deals/[id]/route.ts` ← **ler este arquivo antes de editar**

**Contexto:** Quando um lead muda de stage via PATCH, o hook dispara `stage_enter`. Quando um deal muda de stage, dispara `deal_stage_enter` e, se o novo stage for `fechado_perdido`, também `deal_closed_lost`. Os hooks são `BackgroundTasks` — não bloqueiam a resposta.

- [ ] **Step 1: Ler o arquivo de leads router para entender o padrão PATCH**

```bash
cat backend/app/leads/router.py
```

- [ ] **Step 2: Adicionar hook de stage no leads router**

Encontrar o endpoint `PATCH /api/leads/{lead_id}` em `backend/app/leads/router.py`. Após o update, adicionar:

```python
# Dentro do endpoint PATCH de leads, após o update bem-sucedido:
from fastapi import BackgroundTasks
# (adicionar background_tasks: BackgroundTasks ao parâmetro da função)

old_stage = lead_atual.get("stage")  # buscar o lead antes de atualizar
new_stage = body.get("stage")
if new_stage and new_stage != old_stage:
    from app.automation.triggers import fire_trigger
    background_tasks.add_task(fire_trigger, "stage_enter", lead_id, {"stage": new_stage})
```

**Atenção:** ler o arquivo primeiro e adaptar ao padrão existente (pode ser que o endpoint já retorne o lead atualizado e seja necessário buscar o anterior).

- [ ] **Step 3: Ler o arquivo de deals API route**

```bash
# Verificar se existe e qual é o padrão:
cat frontend/src/app/api/deals/[id]/route.ts 2>$null || echo "Arquivo não existe"
```

Se o arquivo existir e chamar o FastAPI backend: adicionar hook no lado Python (leads/router ou um deals router). Se chamar Supabase diretamente: adicionar `fire_trigger` via `POST /api/automation/trigger` após o update.

- [ ] **Step 4: Implementar hook de stage em deals**

No padrão correto (backend Python ou Next.js), após atualização de `stage_id` em deals:

```python
# Se Python — em app/leads/router.py ou equivalente deals router:
new_stage_key = body.get("stage_key")  # ou resolver da pipeline_stages
if new_stage_key:
    background_tasks.add_task(fire_trigger, "deal_stage_enter", lead_id, {"stage": new_stage_key, "deal_id": deal_id})
    if new_stage_key == "fechado_perdido":
        background_tasks.add_task(fire_trigger, "deal_closed_lost", lead_id, {"deal_id": deal_id})
```

```typescript
// Se Next.js — após supabase.from("deals").update(...):
await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/automation/trigger`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    event_type: "deal_stage_enter",
    lead_id: deal.lead_id,
    data: { stage: newStageKey, deal_id: dealId },
  }),
});
```

- [ ] **Step 5: Testar manualmente**

Mover um lead de stage no kanban do CRM. Verificar no log do backend:
```
[AUTOMATION] Enrolled <lead_id> via stage_enter
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/leads/router.py
# + outros arquivos modificados
git commit -m "feat(automation): add stage_enter and deal_stage_enter event hooks"
```

---

### Task 8: Hook de venda criada (`sale_created`)

**Files:**
- Modify: `frontend/src/app/api/sales/route.ts`

**Contexto:** O arquivo `sales/route.ts` já cria a venda diretamente no Supabase (não passa pelo FastAPI). Após o insert bem-sucedido, deve chamar `POST /api/automation/trigger` no FastAPI para disparar o evento.

- [ ] **Step 1: Ler o arquivo atual**

```bash
cat frontend/src/app/api/sales/route.ts
```

- [ ] **Step 2: Adicionar hook após o insert da venda**

No `POST` handler, após `const { data, error } = await supabase.from("sales").insert(...).select(...).single()` e antes do return de sucesso:

```typescript
// Após verificar que não há error e data foi criado:
try {
  const backendUrl = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_BACKEND_URL ?? "";
  if (backendUrl) {
    await fetch(`${backendUrl}/api/automation/trigger`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_type: "sale_created",
        lead_id: data.lead_id,
        data: {
          sale_id: data.id,
          value: data.value,
          product: data.product,
          deal_id: data.deal_id,
        },
      }),
    });
  }
} catch {
  // hook falhou — não interrompe a criação da venda
}
```

- [ ] **Step 3: Verificar variável de ambiente**

Confirmar que `BACKEND_URL` (ou `NEXT_PUBLIC_BACKEND_URL`) está definido no `.env.local`:
```
BACKEND_URL=http://127.0.0.1:8000
```
Em produção (Docker), deve usar o nome do serviço: `http://api:8000`.

- [ ] **Step 4: Testar manualmente**

Criar uma venda no CRM para um lead em campanha com trigger `sale_created`. Verificar no log do backend:
```
[AUTOMATION] Enrolled <lead_id> via sale_created
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/sales/route.ts
git commit -m "feat(automation): add sale_created event hook in Next.js sales route"
```

---

### Task 9: Hook de tag adicionada e pós-broadcast

**Files:**
- Identificar e modificar endpoint de tags (checar se existe em `backend/app/leads/router.py` ou frontend)
- Modify: `backend/app/broadcast/worker.py` (post_broadcast hook)

- [ ] **Step 1: Localizar endpoint de tags**

```bash
grep -r "lead_tags\|/tags" backend/app/leads/router.py
grep -r "lead_tags" frontend/src/app/api/ --include="*.ts" -l
```

- [ ] **Step 2: Adicionar hook de tag**

No endpoint que insere em `lead_tags` (backend ou frontend), após o insert bem-sucedido:

```python
# Python:
background_tasks.add_task(fire_trigger, "tag_added", lead_id, {"tag_name": tag_name})
```
```typescript
// Next.js (mesmo padrão do sales):
await fetch(`${backendUrl}/api/automation/trigger`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ event_type: "tag_added", lead_id, data: { tag_name } }),
});
```

- [ ] **Step 3: Adicionar hook de post_broadcast em `broadcast/worker.py`**

Localizar onde cada lead do broadcast tem seu status atualizado para `sent`. Após o send bem-sucedido para um lead (dentro de `process_broadcasts()`), adicionar:

```python
# Após enviar template para um lead individual no broadcast:
from app.automation.triggers import fire_trigger
import asyncio
asyncio.create_task(fire_trigger("post_broadcast", lead_id, {
    "broadcast_id": broadcast_id,
    "replied_only": False,
}))
```

**Nota:** O `replied_only` é verificado pela configuração do trigger_node. Se `replied_only=True`, o enrollment ocorre, mas o engine apenas prosseguirá se o lead responder (condição `replied_recently` no fluxo).

- [ ] **Step 4: Commit**

```bash
git add backend/app/leads/router.py backend/app/broadcast/worker.py
# + frontend files se aplicável
git commit -m "feat(automation): add tag_added and post_broadcast event hooks"
```

---

## FASE 4 — Migração e Deprecação

### Task 10: Migrar cadence enrollments + deprecar criação de cadências

**Files:**
- Modify: `backend/app/cadence/router.py`
- Criar script de migração (executar uma vez)

- [ ] **Step 1: Script de migração (executar no Supabase SQL Editor)**

```sql
-- Cancela cadence enrollments ativos (migração para o novo engine)
UPDATE cadence_enrollments
SET status = 'completed',
    completed_at = NOW(),
    last_error = 'migrated: unified automation engine'  -- coluna pode não existir
WHERE status IN ('active', 'responded');
-- Se a coluna last_error não existir em cadence_enrollments, omitir essa parte
```

- [ ] **Step 2: Deprecar endpoints de criação em `cadence/router.py`**

Substituir os handlers `POST` por:

```python
from fastapi import HTTPException

@router.post("")
async def create_cadence_deprecated():
    raise HTTPException(
        status_code=410,
        detail="Cadências simples foram unificadas ao motor de automação. Use /api/campaigns."
    )

@router.post("/{cadence_id}/steps")
async def create_step_deprecated(cadence_id: str):
    raise HTTPException(
        status_code=410,
        detail="Cadências simples foram unificadas ao motor de automação. Use /api/campaigns."
    )

@router.post("/{cadence_id}/enrollments")
async def enroll_deprecated(cadence_id: str):
    raise HTTPException(
        status_code=410,
        detail="Cadências simples foram unificadas ao motor de automação. Use /api/campaigns."
    )
```

Manter todos os `GET` e `DELETE` para histórico.

- [ ] **Step 3: Verificar que GET de cadências ainda funciona**

```bash
curl http://localhost:8000/api/cadences
```
Esperado: lista de cadências existentes (histórico).

- [ ] **Step 4: Commit**

```bash
git add backend/app/cadence/router.py
git commit -m "feat(automation): deprecate cadence creation endpoints (410 Gone)"
```

---

## FASE 5 — Frontend

> **OBRIGATÓRIO:** Todo agente que trabalhar nesta fase deve invocar a skill `frontend-design` antes de escrever qualquer código de componente.

### Task 11: Atualizar tipos TypeScript

**Files:**
- Modify: `frontend/src/lib/types.ts`

- [ ] **Step 1: Invocar `frontend-design` skill**

- [ ] **Step 2: Atualizar tipos em `types.ts`**

Localizar e modificar as seguintes definições:

```typescript
// Expandir CampaignNodeType
export type CampaignNodeType =
  | "trigger" | "send" | "send_text" | "wait" | "condition" | "action" | "end";

// Adicionar à interface Campaign (após status)
priority: number;
frequency_cap: number;
send_start_hour: number;
send_end_hour: number;
```

- [ ] **Step 3: Verificar que TypeScript compila sem erro**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "feat(automation): update TypeScript types for new node types and campaign fields"
```

---

### Task 12: Atualizar flow builder — novo nó `send_text` e novos triggers/condições/ações

**Files:**
- Modify: `frontend/src/components/campaigns/cadence-flow-builder.tsx`

**Contexto:** Este é o arquivo principal do flow builder visual (1140 linhas). As mudanças são:
1. Adicionar `send_text` ao NODE_META, PALETTE_ACTIONS, QUICK_ADD_ITEMS e `getDefaultConfig`
2. Expandir o Inspector para os novos tipos de trigger, condição e ação
3. Não alterar a lógica de React Flow, drag/drop, ou edge handling

- [ ] **Step 1: Invocar `frontend-design` skill**

- [ ] **Step 2: Adicionar `send_text` ao NODE_META**

Localizar `NODE_META` (linha ~53) e adicionar:

```typescript
send_text: { label: "Enviar texto", kicker: "TEXTO LIVRE", icon: "💬", color: "#0F766E", iconBg: "rgba(15,118,110,.1)" },
```

- [ ] **Step 3: Adicionar ao PALETTE_ACTIONS e QUICK_ADD_ITEMS**

Em `PALETTE_ACTIONS` (linha ~470), adicionar após o nó `send`:
```typescript
{ type: "send_text", subtype: "", icon: "💬", label: "Enviar texto", desc: "Texto livre (24h)" },
```

Em `QUICK_ADD_ITEMS` (linha ~456), adicionar após o nó `send`:
```typescript
{ type: "send_text", subtype: "", icon: "💬", label: "Enviar texto" },
```

- [ ] **Step 4: Atualizar `getDefaultConfig`**

Adicionar case em `getDefaultConfig`:
```typescript
case "send_text": return { message_text: "", on_reply: "pause" };
```

- [ ] **Step 5: Atualizar `nodeDetail` para send_text**

```typescript
case "send_text": return (config.message_text as string)?.slice(0, 40) || "texto não definido";
```

- [ ] **Step 6: Expandir o Inspector — novos campos de trigger**

No bloco `node.type === "trigger"` do Inspector (linha ~573), expandir o select de trigger_type e adicionar campos condicionais:

```typescript
// No select de trigger_type, adicionar:
<option value="sale_created">Venda criada</option>
<option value="repurchase_window">Janela de recompra</option>
<option value="no_sale_in_stage">Sem venda no stage</option>
<option value="tag_added">Tag adicionada</option>
<option value="deal_stage_enter">Entrou em stage (deal)</option>
<option value="deal_closed_lost">Deal perdido</option>

// Campos condicionais novos:
{c.trigger_type === "sale_created" && (
  <>
    <div style={field}><label style={label}>Valor mínimo (R$, opcional)</label>
      <input type="number" style={input} value={(c.min_value as number) ?? ""} onChange={e => set("min_value", e.target.value ? Number(e.target.value) : null)} placeholder="Ex: 500" /></div>
    <div style={field}><label style={label}>Filtro de produto (opcional)</label>
      <input type="text" style={input} value={(c.product_filter as string) ?? ""} onChange={e => set("product_filter", e.target.value || null)} placeholder="Ex: café" /></div>
  </>
)}
{(c.trigger_type === "repurchase_window" || c.trigger_type === "no_sale_in_stage") && (
  <div style={field}><label style={label}>Dias</label>
    <input type="number" style={input} value={(c.days as number) ?? 30} onChange={e => set("days", Number(e.target.value))} min={1} /></div>
)}
{(c.trigger_type === "no_sale_in_stage" || c.trigger_type === "deal_stage_enter") && (
  <div style={field}><label style={label}>Filtro de stage</label>
    <input type="text" style={input} value={(c.stage_filter as string) ?? ""} onChange={e => set("stage_filter", e.target.value)} placeholder="Ex: negociacao" /></div>
)}
{c.trigger_type === "tag_added" && (
  <div style={field}><label style={label}>Nome da tag</label>
    <input type="text" style={input} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)} placeholder="Ex: VIP" /></div>
)}
{c.trigger_type === "post_broadcast" && (
  <div style={field}>
    <label style={label}>Apenas quem respondeu?</label>
    <select style={{ ...input, appearance: "none" }} value={(c.replied_only as boolean) ? "true" : "false"} onChange={e => set("replied_only", e.target.value === "true")}>
      <option value="false">Todos os leads do disparo</option>
      <option value="true">Apenas quem respondeu</option>
    </select>
  </div>
)}
```

- [ ] **Step 7: Expandir Inspector — novos campos de condição**

No bloco `node.type === "condition"` do Inspector (linha ~608), expandir o select e adicionar campos:

```typescript
// No select de condition_type:
<option value="sale_count">Número de vendas</option>
<option value="total_spend">Gasto total (R$)</option>
<option value="last_sale_value">Valor da última venda</option>
<option value="deal_value">Valor do deal</option>
<option value="has_tag">Possui tag</option>
<option value="repurchase_days">Dias desde última compra</option>

// Campos condicionais para condições com operator + value:
{["sale_count","total_spend","last_sale_value","deal_value","repurchase_days"].includes(c.condition_type as string) && (
  <>
    <div style={field}>
      <label style={label}>Operador</label>
      <select style={{ ...input, appearance: "none" }} value={(c.operator as string) ?? "gte"} onChange={e => set("operator", e.target.value)}>
        <option value="gte">≥ (maior ou igual)</option>
        <option value="lte">≤ (menor ou igual)</option>
        <option value="gt">&gt; (maior)</option>
        <option value="lt">&lt; (menor)</option>
        <option value="eq">= (igual)</option>
      </select>
    </div>
    <div style={field}><label style={label}>Valor</label>
      <input type="number" style={input} value={(c.value as number) ?? 0} onChange={e => set("value", Number(e.target.value))} min={0} /></div>
  </>
)}
{c.condition_type === "has_tag" && (
  <div style={field}><label style={label}>Nome da tag</label>
    <input type="text" style={input} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)} placeholder="Ex: VIP" /></div>
)}
```

- [ ] **Step 8: Expandir Inspector — novos campos de ação + send_text**

No bloco `node.type === "action"` do Inspector, expandir o select e adicionar campos:

```typescript
// No select de action_type:
<option value="add_tag">Adicionar tag</option>
<option value="remove_tag">Remover tag</option>
<option value="create_deal">Criar deal</option>
<option value="assign_to">Atribuir a vendedor</option>

// Campos condicionais:
{["add_tag","remove_tag"].includes(c.action_type as string) && (
  <div style={field}><label style={label}>Nome da tag</label>
    <input type="text" style={input} value={(c.tag_name as string) ?? ""} onChange={e => set("tag_name", e.target.value)} placeholder="Ex: VIP" /></div>
)}
{c.action_type === "create_deal" && (
  <div style={field}><label style={label}>Título do deal (suporta {{nome}})</label>
    <input type="text" style={input} value={(c.title_template as string) ?? ""} onChange={e => set("title_template", e.target.value)} placeholder="Deal automático — {{empresa}}" /></div>
)}
{c.action_type === "assign_to" && (
  <div style={field}><label style={label}>ID do usuário</label>
    <input type="text" style={input} value={(c.user_id as string) ?? ""} onChange={e => set("user_id", e.target.value)} placeholder="UUID do vendedor" /></div>
)}
```

Para o nó `send_text`, adicionar bloco no Inspector (após o bloco `node.type === "send"`):

```typescript
{node.type === "send_text" && (
  <>
    <div style={field}>
      <label style={label}>Mensagem (vars: {`{{nome}}, {{empresa}}, {{produto}}`})</label>
      <textarea
        style={{ ...input, minHeight: 80, resize: "vertical" }}
        value={(c.message_text as string) ?? ""}
        onChange={e => set("message_text", e.target.value)}
        placeholder="Olá {{nome}}, tudo bem?"
      />
    </div>
    <div style={field}>
      <label style={label}>Ao responder</label>
      <select style={{ ...input, appearance: "none" }} value={(c.on_reply as string) ?? "pause"} onChange={e => set("on_reply", e.target.value)}>
        <option value="pause">Pausar campanha</option>
        <option value="cancel">Cancelar campanha</option>
        <option value="continue">Continuar campanha</option>
      </select>
    </div>
    <div style={{ ...field, padding: "8px 10px", background: "#fef9ed", borderRadius: 6, border: "1px solid #fde68a" }}>
      <p style={{ fontSize: 11, color: "#92400e", lineHeight: 1.5 }}>
        ⚠️ Texto livre — só enviado dentro da janela de 24h após o cliente responder. Se a janela estiver expirada, o nó é pulado automaticamente.
      </p>
    </div>
  </>
)}
```

- [ ] **Step 9: Verificar que TypeScript compila sem erro**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/campaigns/cadence-flow-builder.tsx
git commit -m "feat(automation): add send_text node and all new trigger/condition/action types to flow builder"
```

---

### Task 13: Adicionar priority e frequency_cap nas configurações de campanha

**Files:**
- Ler e modificar: `frontend/src/components/campaigns/cadence-list.tsx` (ou onde campanhas são criadas/editadas)

**Contexto:** Ler o arquivo antes de editar para entender o padrão existente de criação/edição de campanhas.

- [ ] **Step 1: Invocar `frontend-design` skill**

- [ ] **Step 2: Identificar onde campanhas são criadas**

```bash
grep -r "POST.*campaigns\|create.*campaign\|name.*description" frontend/src/components/campaigns/ --include="*.tsx" -l
```

- [ ] **Step 3: Ler o arquivo identificado**

- [ ] **Step 4: Adicionar campos priority e frequency_cap ao formulário de criação/edição**

Dentro do formulário (modal ou página), após o campo `description`:

```tsx
{/* Priority */}
<div>
  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
    Prioridade (1 = baixa · 10 = alta)
  </label>
  <input
    type="number"
    min={1}
    max={10}
    value={priority}
    onChange={e => setPriority(Number(e.target.value))}
    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
  />
</div>

{/* Frequency cap */}
<div>
  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
    Máx. mensagens por lead por dia
  </label>
  <input
    type="number"
    min={1}
    max={10}
    value={frequencyCap}
    onChange={e => setFrequencyCap(Number(e.target.value))}
    className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none w-full"
  />
</div>
```

Incluir `priority` e `frequency_cap` no payload do `POST /api/campaigns`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/
git commit -m "feat(automation): add priority and frequency_cap fields to campaign creation form"
```

---

### Task 14: Remover aba de cadências simples da UI

**Files:**
- Modify: `frontend/src/components/campaigns/campaigns-tabs.tsx`
- Ler: `frontend/src/app/(authenticated)/campanhas/cadencias/[id]/page.tsx`

**Contexto:** A aba "Cadências" simples deve ser removida do menu de campanhas. A página de detalhe `/campanhas/cadencias/[id]` pode ser mantida somente leitura para histórico.

- [ ] **Step 1: Invocar `frontend-design` skill**

- [ ] **Step 2: Ler `campaigns-tabs.tsx`**

```bash
cat frontend/src/components/campaigns/campaigns-tabs.tsx
```

- [ ] **Step 3: Remover a aba de cadências simples**

Localizar o item de tab que leva para a listagem de cadências simples (aquelas do sistema antigo, não o flow builder) e remover do array de tabs. Manter a aba de "Campanhas" (flow builder) e "Broadcasts".

- [ ] **Step 4: Verificar que a navegação para /campanhas ainda funciona**

```bash
cd frontend && npm run dev
```
Navegar para `/campanhas`. Confirmar que a aba de cadências simples não aparece mais e que as outras abas funcionam normalmente.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/campaigns/campaigns-tabs.tsx
git commit -m "feat(automation): remove simple cadences tab from campaigns UI"
```

---

## FASE 6 — Verificação Final

### Task 15: Smoke test do fluxo completo

**Objetivo:** Confirmar que o sistema completo funciona end-to-end.

- [ ] **Step 1: Criar campanha de teste com trigger `sale_created`**

No flow builder, criar uma campanha com:
- Trigger: `sale_created`, sem filtros
- Nó: `send_text` com mensagem "Olá {{nome}}, sua compra de {{produto}} foi registrada!"
- Nó: `wait` 1 dia
- Nó: `end`
- Priority: 8, frequency_cap: 1

Ativar a campanha.

- [ ] **Step 2: Criar uma venda para um lead de teste**

Via CRM → Sales, registrar uma venda para um lead de teste.

- [ ] **Step 3: Verificar enrollment no log**

```bash
docker service logs <service_name> 2>&1 | grep "AUTOMATION"
# ou em dev:
# verificar terminal do backend
```
Esperado: `[AUTOMATION] Enrolled <lead_id> via sale_created`

- [ ] **Step 4: Verificar que o enrollment está em `campaign_enrollments`**

No Supabase Dashboard → Table Editor → `campaign_enrollments`. Confirmar que há uma entrada com `status = active` para o lead e a campanha criada.

- [ ] **Step 5: Rodar todos os testes do backend**

```bash
cd backend && python -m pytest tests/ -v
```
Esperado: todos os testes PASS (incluindo os existentes de cadência que ainda são válidos para referência).

- [ ] **Step 6: Commit final**

```bash
git add -A
git commit -m "feat(automation): unified automation engine complete — smoke test passed"
```

---

## Gaps Conhecidos (Fora do Escopo deste Plano)

- **`notify_seller`** — ação que envia WhatsApp ao vendedor (não ao lead). Está no spec mas requer seleção de canal e lógica de envio mais complexa. Implementar como Task futura separada. O backend tem `elif action_type == "notify_seller": pass` como placeholder seguro.
- **Histórico de cadências simples** — as páginas `/campanhas/cadencias/[id]` de leitura histórica são mantidas funcionais mas não redesenhadas.

---

## Referência Rápida de Arquivos

| Arquivo | Status | Responsabilidade |
|---|---|---|
| `supabase/migrations/20260521_automation_engine.sql` | CRIAR | Schema: priority, frequency_cap, retry, lead_daily_sends, RPCs |
| `backend/app/automation/__init__.py` | CRIAR | Module marker |
| `backend/app/automation/variables.py` | CRIAR | Template variable substitution |
| `backend/app/automation/retry.py` | CRIAR | Backoff exponential |
| `backend/app/automation/engine.py` | CRIAR | Node execution, frequency cap, priority |
| `backend/app/automation/triggers.py` | CRIAR | fire_trigger + check_polling_triggers |
| `backend/app/automation/router.py` | CRIAR | POST /api/automation/trigger |
| `backend/app/main.py` | MODIFICAR | Registrar automation router |
| `backend/app/broadcast/worker.py` | MODIFICAR | Substituir chamadas antigas no run_worker() |
| `backend/app/cadence/router.py` | MODIFICAR | Deprecar endpoints de criação (410) |
| `backend/app/leads/router.py` | MODIFICAR | Hook stage_enter |
| `frontend/src/app/api/sales/route.ts` | MODIFICAR | Hook sale_created |
| `frontend/src/lib/types.ts` | MODIFICAR | Tipos novos |
| `frontend/src/components/campaigns/cadence-flow-builder.tsx` | MODIFICAR | send_text, novos triggers/condições/ações |
| `frontend/src/components/campaigns/campaigns-tabs.tsx` | MODIFICAR | Remover aba cadências simples |
| `frontend/src/components/campaigns/cadence-list.tsx` | MODIFICAR | Campos priority + frequency_cap |
| `backend/tests/test_automation_variables.py` | CRIAR | Testes de variables.py |
| `backend/tests/test_automation_retry.py` | CRIAR | Testes de retry.py |
| `backend/tests/test_automation_engine.py` | CRIAR | Testes de engine.py |
| `backend/tests/test_automation_triggers.py` | CRIAR | Testes de triggers.py |
