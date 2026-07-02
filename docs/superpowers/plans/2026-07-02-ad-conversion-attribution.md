# Ad Conversion Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND RULE (non-negotiable):** Any task that touches `frontend/**` MUST first invoke the `frontend-design` skill AND use **shadcn** components. This applies to Task 8.

**Goal:** Fire multi-stage ad-conversion events (Lead/Qualificado/Oportunidade/Venda) to Meta (direct CAPI) and Google (via a Google Sheet), driven by Kanban stage moves, with dedup and fail-soft resilience.

**Architecture:** Kanban stage moves already POST `deal_stage_enter` to the FastAPI backend. We hook that event: resolve the stage's `conversion_event`/`conversion_value` (new columns on `pipeline_stages`), dedup via a new `conversion_events` table, then dispatch — Meta CAPI directly (generalizing the existing `capi_dispatcher`) and append a row to a Google Sheet for Data Manager import. All new code is env-gated and fail-soft: no credentials or a downstream failure never breaks a Kanban move.

**Tech Stack:** Python 3 / FastAPI, Supabase (postgres), httpx, google-api-python-client (Sheets), pytest. Frontend: Next.js App Router + shadcn.

---

## File Structure

**Backend — new files:**
- `backend/migrations/20260702_conversion_attribution.sql` — pipeline_stages columns + conversion_events table
- `backend/app/campaigns/conversion_log.py` — dedup + audit record for conversion_events
- `backend/app/campaigns/sheets_export.py` — Google Sheet append (env-gated, fail-soft)
- `backend/app/campaigns/conversions.py` — orchestrator: dedup → record → Meta → Sheet → flags
- `backend/tests/test_conversion_log.py`
- `backend/tests/test_sheets_export.py`
- `backend/tests/test_conversions_orchestrator.py`
- `backend/tests/test_stage_conversion_trigger.py`

**Backend — modified files:**
- `backend/app/campaigns/capi_dispatcher.py` — generalize to `dispatch_conversion(lead, event, ...)` + Meta event-name map
- `backend/app/automation/triggers.py` — `deal_stage_enter` branch fires stage conversion
- `backend/app/campaigns/sales.py` — `mark_deal_won` returns won `deal_id`
- `backend/app/leads/router.py` — `/won` routes purchase through the orchestrator (dedup)
- `backend/app/automation/engine.py` — `mark_deal_won` action routes through orchestrator
- `backend/requirements.txt` — add google-api-python-client + google-auth (if missing)

**Frontend — modified files:**
- `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` — accept `conversion_event`/`conversion_value`
- `frontend/src/components/deals/pipeline-edit-modal.tsx` — per-stage conversion config UI (shadcn)
- `frontend/src/lib/types.ts` — extend stage type

---

## Task 1: Database migration (pipeline_stages columns + conversion_events)

**Files:**
- Create: `backend/migrations/20260702_conversion_attribution.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 20260702_conversion_attribution.sql
-- Atribuição de conversões de anúncios (multi-etapa) — lado CRM.
--
-- 1) Marca, POR ETAPA de pipeline, qual evento de conversão de anúncio ela representa e o
--    valor a reportar. NULL = etapa não dispara conversão.
-- 2) Tabela de auditoria + DEDUP dos eventos disparados (único por deal+evento), fonte de
--    verdade p/ Meta CAPI (direto) e p/ a Planilha do Google (Data Manager).
--
-- Idempotente: seguro reaplicar. Aplicar em HOMOLOG e depois PROD (paridade de schema).

ALTER TABLE pipeline_stages
    ADD COLUMN IF NOT EXISTS conversion_event text NULL,
    ADD COLUMN IF NOT EXISTS conversion_value numeric NULL;

COMMENT ON COLUMN pipeline_stages.conversion_event IS
    'Evento de conversão de anúncio desta etapa: lead|qualified|opportunity|purchase. NULL = não dispara.';
COMMENT ON COLUMN pipeline_stages.conversion_value IS
    'Valor fixo (BRL) reportado ao entrar nesta etapa. Ignorado em purchase (usa valor real da venda).';

CREATE TABLE IF NOT EXISTS conversion_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id      uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    deal_id      uuid NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    event        text NOT NULL,
    value        numeric NULL,
    currency     text NOT NULL DEFAULT 'BRL',
    platform     text NOT NULL DEFAULT 'both',
    gclid        text NULL,
    ctwa_clid    text NULL,
    sent_meta    boolean NOT NULL DEFAULT false,
    sheet_synced boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversion_events_deal_event_unique UNIQUE (deal_id, event)
);

COMMENT ON TABLE conversion_events IS
    'Auditoria + dedup de eventos de conversão de anúncio. UNIQUE(deal_id,event) evita redisparo.';
```

- [ ] **Step 2: Commit**

```bash
git add backend/migrations/20260702_conversion_attribution.sql
git commit -m "feat(conversions): migration pipeline_stages conversion cols + conversion_events"
```

> **NOTE (manual):** This migration must be applied in Supabase HOMOLOG then PROD. Flag it to the user at execution end — do not assume it is applied.

---

## Task 2: Generalize the CAPI dispatcher to arbitrary events

**Files:**
- Modify: `backend/app/campaigns/capi_dispatcher.py`
- Test: `backend/tests/test_capi_dispatcher.py`

- [ ] **Step 1: Write failing tests for the Meta event-name map and `dispatch_conversion`**

Add to `backend/tests/test_capi_dispatcher.py`:

```python
from app.campaigns.capi_dispatcher import meta_event_name, dispatch_conversion


def test_meta_event_name_defaults():
    assert meta_event_name("purchase") == "Purchase"
    assert meta_event_name("qualified") == "Lead"
    assert meta_event_name("opportunity") == "Oportunidade_Criada"
    assert meta_event_name("lead") == "Lead"


def test_meta_event_name_env_override():
    with patch.dict("os.environ", {"META_EVENT_NAME_OPPORTUNITY": "MQL"}, clear=True):
        assert meta_event_name("opportunity") == "MQL"


def test_dispatch_conversion_sends_event_name_to_meta():
    lead = {"id": "L1", "ctwa_clid": "clid", "phone": "5534996652412"}
    env = {"META_CAPI_PIXEL_ID": "PIX1", "META_CAPI_ACCESS_TOKEN": "TOK1"}
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.raise_for_status.return_value = None
        result = dispatch_conversion(lead, "opportunity", value=150.0)
    assert result["meta"]["sent"] is True
    _, kwargs = client.post.call_args
    assert kwargs["json"]["data"][0]["event_name"] == "Oportunidade_Criada"


def test_dispatch_purchase_conversion_still_uses_purchase_event():
    lead = {"id": "L2", "ctwa_clid": "clid", "phone": "5534996652412"}
    env = {"META_CAPI_PIXEL_ID": "PIX1", "META_CAPI_ACCESS_TOKEN": "TOK1"}
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.raise_for_status.return_value = None
        dispatch_purchase_conversion(lead, value=99.0)
        _, kwargs = client.post.call_args
    assert kwargs["json"]["data"][0]["event_name"] == "Purchase"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_capi_dispatcher.py -k "event_name or dispatch_conversion or still_uses_purchase" -v`
Expected: FAIL with `ImportError`/`cannot import name 'meta_event_name'`.

- [ ] **Step 3: Implement the map and generalized dispatch**

In `backend/app/campaigns/capi_dispatcher.py`, add near the top after the constants:

```python
# Mapa canônico → nome de evento na Meta. Override por env META_EVENT_NAME_<EVENTO>.
_DEFAULT_META_EVENT_NAMES = {
    "lead": "Lead",
    "qualified": "Lead",
    "opportunity": "Oportunidade_Criada",
    "purchase": "Purchase",
}


def meta_event_name(event: str) -> str:
    """Nome do evento na Meta para um evento canônico do funil (env-overridable)."""
    default = _DEFAULT_META_EVENT_NAMES.get(event, event)
    return os.environ.get(f"META_EVENT_NAME_{event.upper()}", default)
```

Refactor `_send_meta_capi` to accept an `event_name`:

```python
def _send_meta_capi(lead: dict[str, Any], value: float | None, currency: str,
                    event_name: str = "Purchase") -> dict[str, Any]:
    """Envia o evento para a Meta CAPI se houver credenciais. Fail-soft."""
    creds = _meta_credentials()
    if not creds:
        logger.info("[CAPI] Meta sem credenciais — disparo ignorado")
        return {"sent": False, "reason": "no_credentials"}
    if not (lead.get("ctwa_clid") or lead.get("fbclid")):
        logger.info("[CAPI] Lead %s sem ctwa_clid nem fbclid — nada a atribuir na Meta", lead.get("id"))
        return {"sent": False, "reason": "no_click_id"}
    pixel_id, access_token, api_version = creds
    url = f"{META_API_BASE}/{api_version}/{pixel_id}/events"
    payload = build_meta_capi_payload(lead, value, currency, event_name=event_name)
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.post(url, params={"access_token": access_token}, json=payload)
            resp.raise_for_status()
        logger.info("[CAPI] Meta %s enviado para lead %s (HTTP %s)", event_name, lead.get("id"), resp.status_code)
        return {"sent": True, "status_code": resp.status_code}
    except Exception as exc:
        logger.error("[CAPI] Falha ao enviar evento Meta para lead %s: %s", lead.get("id"), exc, exc_info=True)
        return {"sent": False, "reason": "http_error", "error": str(exc)}
```

Add the generalized dispatcher and keep the purchase wrapper:

```python
def dispatch_conversion(lead: dict[str, Any], event: str, value: float | None = None,
                        currency: str = "BRL") -> dict[str, Any]:
    """Dispara UM evento de conversão canônico (lead|qualified|opportunity|purchase) p/ Meta+Google.

    Fail-soft de ponta a ponta. Retorna {"meta": {...}, "google": {...}}.
    """
    if not lead:
        return {"meta": {"sent": False, "reason": "no_lead"}, "google": {"sent": False, "reason": "no_lead"}}
    meta_result = _send_meta_capi(lead, value, currency, event_name=meta_event_name(event))
    google_result = _send_google_conversion(lead, value, currency)
    return {"meta": meta_result, "google": google_result}


def dispatch_purchase_conversion(lead: dict[str, Any], value: float | None = None,
                                 currency: str = "BRL") -> dict[str, Any]:
    """Compat: dispara a conversão de COMPRA (event='purchase')."""
    return dispatch_conversion(lead, "purchase", value, currency)
```

Update `build_meta_capi_payload` signature to thread `event_name` (default `"Purchase"`), passing it into `build_meta_capi_event(... event_name=event_name)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_capi_dispatcher.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/capi_dispatcher.py backend/tests/test_capi_dispatcher.py
git commit -m "feat(conversions): generalize CAPI dispatcher to arbitrary funnel events"
```

---

## Task 3: Dedup + audit log (`conversion_log.py`)

**Files:**
- Create: `backend/app/campaigns/conversion_log.py`
- Test: `backend/tests/test_conversion_log.py`

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock, patch
from app.campaigns import conversion_log


def _fake_sb():
    sb = MagicMock()
    return sb


def test_already_fired_true_when_row_exists():
    sb = _fake_sb()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "x"}]
    with patch("app.campaigns.conversion_log.get_supabase", return_value=sb):
        assert conversion_log.already_fired("deal1", "qualified") is True


def test_already_fired_false_when_no_row():
    sb = _fake_sb()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    with patch("app.campaigns.conversion_log.get_supabase", return_value=sb):
        assert conversion_log.already_fired("deal1", "qualified") is False


def test_record_conversion_event_inserts_row():
    sb = _fake_sb()
    with patch("app.campaigns.conversion_log.get_supabase", return_value=sb):
        conversion_log.record_conversion_event(
            lead_id="L1", deal_id="D1", event="qualified", value=50.0,
            currency="BRL", gclid="g", ctwa_clid="c", sent_meta=True, sheet_synced=False,
        )
    args = sb.table.return_value.insert.call_args[0][0]
    assert args["deal_id"] == "D1" and args["event"] == "qualified"
    assert args["sent_meta"] is True and args["sheet_synced"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_conversion_log.py -v`
Expected: FAIL with `ModuleNotFoundError: app.campaigns.conversion_log`.

- [ ] **Step 3: Implement `conversion_log.py`**

```python
"""Dedup + auditoria dos eventos de conversão de anúncio (tabela conversion_events).

UNIQUE(deal_id, event) na base garante idempotência; aqui checamos antes p/ evitar disparo
duplicado à Meta/Planilha quando o card é movido de volta e de novo. Fail-soft: erros de I/O
nunca propagam (o disparo é acessório ao fluxo de venda).
"""
import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


def already_fired(deal_id: str, event: str) -> bool:
    """True se já existe um evento (deal_id, event) registrado."""
    try:
        sb = get_supabase()
        res = (
            sb.table("conversion_events").select("id")
            .eq("deal_id", deal_id).eq("event", event).limit(1).execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.error("conversion_log.already_fired(%s,%s) falhou: %s", deal_id, event, exc)
        return False  # fail-open: melhor tentar disparar do que engolir a conversão


def record_conversion_event(*, lead_id: str, deal_id: str, event: str, value: float | None,
                            currency: str, gclid: str | None, ctwa_clid: str | None,
                            sent_meta: bool, sheet_synced: bool) -> None:
    """Grava a linha de auditoria. Fail-soft."""
    row: dict[str, Any] = {
        "lead_id": lead_id, "deal_id": deal_id, "event": event, "value": value,
        "currency": currency, "gclid": gclid, "ctwa_clid": ctwa_clid,
        "sent_meta": sent_meta, "sheet_synced": sheet_synced,
    }
    try:
        get_supabase().table("conversion_events").insert(row).execute()
    except Exception as exc:
        logger.error("conversion_log.record_conversion_event(%s,%s) falhou: %s", deal_id, event, exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_conversion_log.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/conversion_log.py backend/tests/test_conversion_log.py
git commit -m "feat(conversions): dedup + audit log for conversion_events"
```

---

## Task 4: Google Sheet writer (`sheets_export.py`)

**Files:**
- Create: `backend/app/campaigns/sheets_export.py`
- Test: `backend/tests/test_sheets_export.py`
- Modify: `backend/requirements.txt` (add deps if missing)

- [ ] **Step 1: Ensure Sheets deps present**

Run: `cd backend && python -c "import googleapiclient, google.oauth2.service_account" 2>&1 | head -1`
If it errors, append to `backend/requirements.txt`:

```
google-api-python-client>=2.0
google-auth>=2.0
```

Then: `cd backend && pip install -r requirements.txt`

- [ ] **Step 2: Write the failing test**

```python
from unittest.mock import MagicMock, patch
from app.campaigns import sheets_export


def test_build_sheet_row_matches_contract():
    lead = {"name": "João", "gclid": "g123", "email": "j@x.com", "phone": "5534996652412"}
    row = sheets_export.build_sheet_row(lead, "qualified", value=50.0, currency="BRL",
                                        when="2026-07-02 16:00:00")
    # [name, gclid, email, telefone_hash, conversion_name, conversion_date,
    #  conversion_currency, conversion_value, status_funil]
    assert row[0] == "João"
    assert row[1] == "g123"
    assert row[2] == "j@x.com"
    assert len(row[3]) == 64  # sha256 hex do telefone
    assert row[4] == "Lead_Qualificado"
    assert row[5] == "2026-07-02 16:00:00"
    assert row[6] == "BRL"
    assert row[7] == 50.0
    assert row[8] == "qualificado"


def test_append_conversion_row_noop_without_config():
    with patch.dict("os.environ", {}, clear=True):
        result = sheets_export.append_conversion_row(["a"])
    assert result["synced"] is False
    assert result["reason"] == "no_config"


def test_append_conversion_row_calls_sheets_api_when_configured():
    env = {"GOOGLE_SHEETS_CONV_ID": "SHEET1", "GOOGLE_SA_JSON": '{"type":"service_account"}'}
    fake_service = MagicMock()
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.sheets_export._build_service", return_value=fake_service):
        result = sheets_export.append_conversion_row(["a", "b"])
    assert result["synced"] is True
    fake_service.spreadsheets.return_value.values.return_value.append.assert_called_once()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_sheets_export.py -v`
Expected: FAIL with `ModuleNotFoundError: app.campaigns.sheets_export`.

- [ ] **Step 4: Implement `sheets_export.py`**

```python
"""Escreve 1 linha por evento de conversão numa Planilha Google (Data Manager / Make importam).

Env-gated e fail-soft: sem GOOGLE_SHEETS_CONV_ID / credencial de service account, é no-op
logado. A planilha é a ponte p/ o Google (evita dev-token do Google Ads API). O service
account precisa estar COMPARTILHADO como editor na planilha alvo.
"""
import json
import logging
import os
from typing import Any

from app.campaigns.capi_dispatcher import hash_phone

logger = logging.getLogger(__name__)

_SHEET_RANGE = "A:I"

# canônico → (conversion_name p/ Google Ads, status_funil legível)
_CONVERSION_NAMES = {
    "lead": ("Lead_Captado", "Lead_captado"),
    "qualified": ("Lead_Qualificado", "qualificado"),
    "opportunity": ("Oportunidade_Criada", "oportunidade"),
    "purchase": ("Venda_Fechada", "vendido"),
}


def build_sheet_row(lead: dict[str, Any], event: str, value: float | None,
                    currency: str, when: str) -> list[Any]:
    """Monta a linha na ordem-contrato do doc (9 colunas)."""
    conversion_name, status_funil = _CONVERSION_NAMES.get(event, (event, event))
    return [
        lead.get("name") or "",
        lead.get("gclid") or "",
        lead.get("email") or "",
        hash_phone(lead.get("wa_id") or lead.get("phone")) or "",
        conversion_name,
        when,
        currency,
        value,
        status_funil,
    ]


def _build_service():  # pragma: no cover - I/O real, mockado nos testes
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds_json = os.environ["GOOGLE_SA_JSON"]
    info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def append_conversion_row(row: list[Any]) -> dict[str, Any]:
    """Append da linha na planilha. Fail-soft. Retorna {"synced": bool, "reason"?: str}."""
    sheet_id = os.environ.get("GOOGLE_SHEETS_CONV_ID")
    if not sheet_id or not os.environ.get("GOOGLE_SA_JSON"):
        logger.info("[SHEETS] Sem GOOGLE_SHEETS_CONV_ID/GOOGLE_SA_JSON — append ignorado")
        return {"synced": False, "reason": "no_config"}
    try:
        service = _build_service()
        service.spreadsheets().values().append(
            spreadsheetId=sheet_id, range=_SHEET_RANGE,
            valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        logger.info("[SHEETS] Linha de conversão anexada (%s)", row[4] if len(row) > 4 else "?")
        return {"synced": True}
    except Exception as exc:
        logger.error("[SHEETS] Falha ao anexar linha: %s", exc, exc_info=True)
        return {"synced": False, "reason": "http_error", "error": str(exc)}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_sheets_export.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/sheets_export.py backend/tests/test_sheets_export.py backend/requirements.txt
git commit -m "feat(conversions): Google Sheet append writer (env-gated, fail-soft)"
```

---

## Task 5: Orchestrator (`conversions.py`) — dedup → record → Meta → Sheet

**Files:**
- Create: `backend/app/campaigns/conversions.py`
- Test: `backend/tests/test_conversions_orchestrator.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone
from unittest.mock import patch
from app.campaigns import conversions


LEAD = {"id": "L1", "name": "João", "phone": "5534996652412", "gclid": "g", "ctwa_clid": "c",
        "email": "j@x.com"}


def test_fire_stage_conversion_dedups():
    with patch("app.campaigns.conversions.already_fired", return_value=True), \
         patch("app.campaigns.conversions.dispatch_conversion") as disp, \
         patch("app.campaigns.conversions.append_conversion_row") as sheet:
        result = conversions.fire_stage_conversion(LEAD, "D1", "qualified", value=50.0)
    disp.assert_not_called()
    sheet.assert_not_called()
    assert result["skipped"] == "already_fired"


def test_fire_stage_conversion_dispatches_meta_and_sheet_then_records():
    with patch("app.campaigns.conversions.already_fired", return_value=False), \
         patch("app.campaigns.conversions.dispatch_conversion", return_value={"meta": {"sent": True}, "google": {}}) as disp, \
         patch("app.campaigns.conversions.append_conversion_row", return_value={"synced": True}) as sheet, \
         patch("app.campaigns.conversions.record_conversion_event") as record:
        conversions.fire_stage_conversion(LEAD, "D1", "qualified", value=50.0, currency="BRL")
    disp.assert_called_once_with(LEAD, "qualified", 50.0, "BRL")
    sheet.assert_called_once()
    kw = record.call_args.kwargs
    assert kw["deal_id"] == "D1" and kw["event"] == "qualified"
    assert kw["sent_meta"] is True and kw["sheet_synced"] is True


def test_fire_stage_conversion_records_even_when_meta_fails():
    with patch("app.campaigns.conversions.already_fired", return_value=False), \
         patch("app.campaigns.conversions.dispatch_conversion", return_value={"meta": {"sent": False}, "google": {}}), \
         patch("app.campaigns.conversions.append_conversion_row", return_value={"synced": False}), \
         patch("app.campaigns.conversions.record_conversion_event") as record:
        conversions.fire_stage_conversion(LEAD, "D1", "purchase", value=500.0)
    kw = record.call_args.kwargs
    assert kw["sent_meta"] is False and kw["sheet_synced"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_conversions_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: app.campaigns.conversions`.

- [ ] **Step 3: Implement `conversions.py`**

```python
"""Orquestra o disparo de UMA conversão de etapa: dedup → Meta (direto) → Planilha → auditoria.

Fail-soft: nenhuma etapa levanta. Usado tanto pelo gancho de mudança de etapa do Kanban
(deal_stage_enter) quanto pelo caminho de venda (purchase). A dedup por (deal_id, event)
garante que mover o card ida-e-volta — ou o purchase chegar por dois caminhos — não redispara.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from app.campaigns.capi_dispatcher import dispatch_conversion
from app.campaigns.conversion_log import already_fired, record_conversion_event
from app.campaigns.sheets_export import append_conversion_row, build_sheet_row

logger = logging.getLogger(__name__)


def fire_stage_conversion(lead: dict[str, Any], deal_id: str, event: str,
                          value: float | None = None, currency: str = "BRL") -> dict[str, Any]:
    """Dispara a conversão canônica p/ um (deal, event). Idempotente e fail-soft."""
    if not lead or not deal_id or not event:
        return {"skipped": "missing_args"}
    if already_fired(deal_id, event):
        logger.info("[CONV] (%s,%s) já disparado — skip", deal_id, event)
        return {"skipped": "already_fired"}

    meta_sent = False
    sheet_synced = False
    try:
        result = dispatch_conversion(lead, event, value, currency)
        meta_sent = bool(result.get("meta", {}).get("sent"))
    except Exception as exc:  # pragma: no cover - defensivo
        logger.error("[CONV] dispatch_conversion(%s,%s) falhou: %s", deal_id, event, exc)

    try:
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        row = build_sheet_row(lead, event, value, currency, when)
        sheet_synced = bool(append_conversion_row(row).get("synced"))
    except Exception as exc:  # pragma: no cover - defensivo
        logger.error("[CONV] append_conversion_row(%s,%s) falhou: %s", deal_id, event, exc)

    record_conversion_event(
        lead_id=lead.get("id"), deal_id=deal_id, event=event, value=value, currency=currency,
        gclid=lead.get("gclid"), ctwa_clid=lead.get("ctwa_clid"),
        sent_meta=meta_sent, sheet_synced=sheet_synced,
    )
    return {"sent_meta": meta_sent, "sheet_synced": sheet_synced}


def fire_stage_conversion_background(lead: dict[str, Any], deal_id: str, event: str,
                                     value: float | None = None, currency: str = "BRL") -> None:
    """Versão não-bloqueante (daemon thread) p/ chamadores síncronos (worker de automação)."""
    def _run() -> None:
        try:
            fire_stage_conversion(lead, deal_id, event, value, currency)
        except Exception as exc:  # pragma: no cover - defensivo
            logger.error("[CONV] erro no disparo em background (%s,%s): %s", deal_id, event, exc)
    threading.Thread(target=_run, name="conv-dispatch", daemon=True).start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_conversions_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/campaigns/conversions.py backend/tests/test_conversions_orchestrator.py
git commit -m "feat(conversions): stage-conversion orchestrator (dedup+Meta+Sheet+audit)"
```

---

## Task 6: Hook the Kanban stage-enter event

**Files:**
- Modify: `backend/app/automation/triggers.py`
- Test: `backend/tests/test_stage_conversion_trigger.py`

**Context:** `frontend/src/app/api/deals/[id]/route.ts` already POSTs `deal_stage_enter` with `{stage: <key>, deal_id}` to `/api/automation/trigger` → `fire_trigger`. We add a branch that resolves the stage's `conversion_event`/`conversion_value` from the DB and fires the orchestrator. Enrollment logic for `deal_stage_enter` must remain unchanged.

- [ ] **Step 1: Write the failing test**

```python
from unittest.mock import MagicMock, patch
import asyncio
from app.automation import triggers


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_deal_stage_enter_fires_stage_conversion_when_stage_mapped():
    deal_row = {"id": "D1", "lead_id": "L1", "stage_id": "S1"}
    stage_row = {"conversion_event": "qualified", "conversion_value": 50}
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [deal_row]
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = stage_row
    with patch("app.automation.triggers.get_supabase", return_value=sb), \
         patch("app.automation.triggers.get_lead", return_value={"id": "L1"}), \
         patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]), \
         patch("app.automation.triggers.fire_stage_conversion_background") as fire:
        _run(triggers.fire_trigger("deal_stage_enter", "L1", {"stage": "qualificado", "deal_id": "D1"}))
    fire.assert_called_once()
    args, kwargs = fire.call_args
    assert args[1] == "D1" and args[2] == "qualified"


def test_deal_stage_enter_no_fire_when_stage_unmapped():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "D1", "lead_id": "L1", "stage_id": "S1"}]
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"conversion_event": None, "conversion_value": None}
    with patch("app.automation.triggers.get_supabase", return_value=sb), \
         patch("app.automation.triggers.get_lead", return_value={"id": "L1"}), \
         patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]), \
         patch("app.automation.triggers.fire_stage_conversion_background") as fire:
        _run(triggers.fire_trigger("deal_stage_enter", "L1", {"stage": "x", "deal_id": "D1"}))
    fire.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_stage_conversion_trigger.py -v`
Expected: FAIL (`AttributeError`/import: `fire_stage_conversion_background`, `get_supabase`, `get_lead` not in triggers).

- [ ] **Step 3: Implement the hook**

In `backend/app/automation/triggers.py`, add imports near the top:

```python
from app.db.supabase import get_supabase
from app.leads.service import get_lead
from app.campaigns.conversions import fire_stage_conversion_background
```

Add a helper above `fire_trigger`:

```python
def _maybe_fire_stage_conversion(lead_id: str, data: dict) -> None:
    """Se a etapa que o deal entrou estiver marcada com conversion_event, dispara a conversão.

    Resolve o evento/valor pelo stage_id ATUAL do deal (autoritativo), não pela key do payload.
    purchase usa o valor real do deal; demais usam conversion_value fixo da etapa. Fail-soft.
    """
    deal_id = data.get("deal_id")
    if not deal_id:
        return
    try:
        sb = get_supabase()
        rows = sb.table("deals").select("id, lead_id, stage_id, value").eq("id", deal_id).limit(1).execute().data
        if not rows:
            return
        deal = rows[0]
        stage = (
            sb.table("pipeline_stages").select("conversion_event, conversion_value")
            .eq("id", deal.get("stage_id")).single().execute().data
        )
        event = (stage or {}).get("conversion_event")
        if not event:
            return
        if event == "purchase":
            value = deal.get("value") if deal.get("value") is not None else (stage or {}).get("conversion_value")
        else:
            value = (stage or {}).get("conversion_value")
        lead = get_lead(lead_id) or {"id": lead_id}
        fire_stage_conversion_background(lead, deal_id, event, value=value)
    except Exception as exc:
        logger.error("[CONV] _maybe_fire_stage_conversion(lead=%s, deal=%s) falhou: %s", lead_id, deal_id, exc)
```

Inside `fire_trigger`, at the very start of the `try` (before the enrollment loops), add:

```python
        if event_type == "deal_stage_enter":
            _maybe_fire_stage_conversion(lead_id, data)
```

(Do NOT `return` — enrollment for `deal_stage_enter` campaigns must still run afterward.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_stage_conversion_trigger.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend conversion suite**

Run: `cd backend && python -m pytest tests/test_capi_dispatcher.py tests/test_conversion_log.py tests/test_sheets_export.py tests/test_conversions_orchestrator.py tests/test_stage_conversion_trigger.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/automation/triggers.py backend/tests/test_stage_conversion_trigger.py
git commit -m "feat(conversions): fire stage conversion on deal_stage_enter (Kanban move)"
```

---

## Task 7: Route the explicit "won" paths through the orchestrator (dedup-safe purchase)

**Files:**
- Modify: `backend/app/campaigns/sales.py` (return won `deal_id`)
- Modify: `backend/app/leads/router.py` (`/won` endpoint)
- Modify: `backend/app/automation/engine.py` (`mark_deal_won` action)
- Test: `backend/tests/test_won_sale.py`

**Context:** The `/won` endpoint and the automation `mark_deal_won` action currently call `dispatch_purchase_conversion` directly (no dedup, no Sheet). Since moving a card to "Ganho" also fires `deal_stage_enter` (Task 6), purchase could be attempted twice. Routing these through `fire_stage_conversion` makes them dedup-safe and adds the Sheet row.

- [ ] **Step 1: Make `mark_deal_won` return the won deal id**

In `backend/app/campaigns/sales.py`, track the last updated deal id and include it in the return dict:

```python
    deals_updated = 0
    won_deal_id: str | None = None
    ...
        for deal in (deals or []):
            ...
            sb.table("deals").update(update).eq("id", deal["id"]).execute()
            won_deal_id = deal["id"]
            deals_updated += 1
    ...
    lead = get_lead(lead_id) or {}
    return {"lead": lead, "deals_updated": deals_updated, "value": value,
            "currency": currency, "deal_id": won_deal_id}
```

- [ ] **Step 2: Update `/won` endpoint to use the orchestrator**

In `backend/app/leads/router.py`, replace the import and dispatch in `mark_lead_won`:

```python
    from app.leads.service import get_lead
    from app.campaigns.sales import mark_deal_won
    from app.campaigns.conversions import fire_stage_conversion

    if not get_lead(lead_id):
        raise HTTPException(status_code=404, detail="Lead not found")

    result = mark_deal_won(lead_id, value=body.value, currency=body.currency, deal_id=body.deal_id)

    if result.get("deal_id"):
        background_tasks.add_task(
            fire_stage_conversion, result["lead"], result["deal_id"], "purchase",
            body.value, body.currency,
        )
```

- [ ] **Step 3: Update automation `mark_deal_won` action**

In `backend/app/automation/engine.py`, in the `mark_deal_won` branch (currently calling `dispatch_purchase_conversion_background`), replace with:

```python
            if action_type == "mark_deal_won":
                try:
                    from app.campaigns.conversions import fire_stage_conversion_background
                    from app.leads.service import get_lead
                    lead_row = get_lead(enrollment["lead_id"]) or {}
                    fire_stage_conversion_background(
                        lead_row, rows[0]["id"], "purchase", value=cfg.get("value")
                    )
                except Exception as exc:
                    logger.warning("[AUTOMATION] mark_deal_won: falha ao disparar conversão: %s", exc)
```

- [ ] **Step 4: Update/extend `test_won_sale.py`**

Read `backend/tests/test_won_sale.py` first. Adjust any assertion that patches/asserts `dispatch_purchase_conversion` on the `/won` path to instead assert `fire_stage_conversion` is scheduled with `event="purchase"` and the won `deal_id`. Add:

```python
def test_won_endpoint_fires_purchase_via_orchestrator(monkeypatch):
    # mark_deal_won returns a deal_id → /won schedules fire_stage_conversion("purchase")
    from app.campaigns import sales
    monkeypatch.setattr(sales, "mark_deal_won", lambda *a, **k: {
        "lead": {"id": "L1"}, "deals_updated": 1, "value": 500.0, "currency": "BRL", "deal_id": "D1",
    })
    # ... call the endpoint via TestClient and assert BackgroundTasks scheduled with ("purchase","D1")
```

(Match the existing test's TestClient/monkeypatch style in that file.)

- [ ] **Step 5: Run the won-sale + orchestrator tests**

Run: `cd backend && python -m pytest tests/test_won_sale.py tests/test_conversions_orchestrator.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/campaigns/sales.py backend/app/leads/router.py backend/app/automation/engine.py backend/tests/test_won_sale.py
git commit -m "feat(conversions): route won-sale purchase through dedup-safe orchestrator"
```

---

## Task 8: Frontend — per-stage conversion config in the pipeline editor

> **REQUIRED:** Invoke the `frontend-design` skill BEFORE writing any code in this task, and use **shadcn** components (Select, Input, Label). Match the existing modal's visual language.

**Files:**
- Modify: `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts` (accept new fields)
- Modify: `frontend/src/lib/types.ts` (extend stage type)
- Modify: `frontend/src/components/deals/pipeline-edit-modal.tsx` (UI + include fields in dirty save)

- [ ] **Step 1: Accept `conversion_event`/`conversion_value` in the stage PATCH route**

In `frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts`, extend the `updates` builder (after the `order_index` line):

```typescript
  if (body.conversion_event !== undefined) {
    const allowed = ["lead", "qualified", "opportunity", "purchase", null, ""];
    if (!allowed.includes(body.conversion_event)) {
      return NextResponse.json({ error: "conversion_event inválido." }, { status: 400 });
    }
    updates.conversion_event = body.conversion_event || null;
  }
  if (body.conversion_value !== undefined) {
    updates.conversion_value =
      body.conversion_value === "" || body.conversion_value === null
        ? null
        : Number(body.conversion_value);
  }
```

- [ ] **Step 2: Extend the stage type**

In `frontend/src/lib/types.ts`, add to the `PipelineStage`/`EditableStage` shape (find the interface with `stage_id`/`label`/`key`):

```typescript
  conversion_event?: "lead" | "qualified" | "opportunity" | "purchase" | null;
  conversion_value?: number | null;
```

- [ ] **Step 3: Invoke frontend-design skill, then add the UI**

Invoke `frontend-design`. Then, in `frontend/src/components/deals/pipeline-edit-modal.tsx`, inside `SortableStageRow` (below the label input), add a shadcn `Select` for the event and an `Input` for the value. Wire both through the existing `onChange(stage.id, field, value)` mechanism and mark `_dirty`. Include them in the dirty-save body:

```typescript
body: JSON.stringify({
  label: s.label,
  dot_color: s.dot_color,
  order_index: s.order_index,
  conversion_event: s.conversion_event ?? null,
  conversion_value: s.conversion_value ?? null,
}),
```

Select options: `Nenhum` (null), `Lead Captado` (lead), `Qualificado` (qualified), `Oportunidade` (opportunity), `Venda` (purchase). Show the value input only when an event ≠ null is selected (purchase can leave value empty → uses real sale value; show helper text "Venda usa o valor real").

- [ ] **Step 4: Verify build + lint**

Run: `cd frontend && npm run lint && npm run build`
Expected: no type errors; build succeeds.

- [ ] **Step 5: Manual smoke (describe for reviewer)**

Open a pipeline in the Kanban editor → each stage now has an "Evento de conversão" select + value field → save → reload → values persist.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/api/pipelines/[id]/stages/[stageId]/route.ts frontend/src/lib/types.ts frontend/src/components/deals/pipeline-edit-modal.tsx
git commit -m "feat(conversions): per-stage conversion event/value config in pipeline editor"
```

---

## Task 9 (optional): Capture `ad_id` from the CTWA referral

**Files:**
- Modify: `backend/app/webhook/meta_parser.py`
- Modify: `backend/app/webhook/meta_router.py` (persist onto lead, like `ctwa_clid`)
- Test: `backend/tests/test_ctwa_clid_tracking.py`

**Context:** Meta's `referral` object may include `source_id` (the ad id). Capturing it is reporting-only (CAPI attribution already works via `ctwa_clid`). Only do this task if the referral payload in `test_ctwa_clid_tracking.py` fixtures shows a `source_id`. Otherwise SKIP and note it.

- [ ] **Step 1: Confirm the field exists**

Read `backend/tests/test_ctwa_clid_tracking.py` and `meta_parser.py` around the `referral` extraction. If `source_id` is present in fixtures, proceed; else mark this task skipped in the final report.

- [ ] **Step 2..N:** Mirror the existing `ctwa_clid` capture path for `ad_id` (parse in `meta_parser.py`, thread through `ParsedMessage`, persist in `meta_router.py::_register_lead`/`update_lead`), with a test asserting `ad_id` lands on the lead. Requires a `leads.ad_id` column — add to the Task 1 migration if pursuing.

---

## Final verification & handoff

- [ ] **Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (no regressions).

- [ ] **Report to user (do NOT auto-push):**
  1. Migration `20260702_conversion_attribution.sql` is **PENDING in Supabase** (HOMOLOG → PROD).
  2. New env vars needed in PROD to activate: `GOOGLE_SHEETS_CONV_ID`, `GOOGLE_SA_JSON` (service account JSON, shared as editor on the sheet). Meta side reuses existing `META_CAPI_*`. Optional per-event overrides: `META_EVENT_NAME_QUALIFIED/OPPORTUNITY/...`.
  3. Manual Meta step: create Custom Conversions in Events Manager for `Oportunidade_Criada` (and any non-standard event names).
  4. Google import: connect the Sheet in Ads Data Manager (or Make) → Enhanced Conversions for Leads.
  5. Hand the §9 prompts from the spec to the LP repos.
  6. Push to `master` only on user authorization (per CLAUDE.md git flow).

---

## Self-Review notes (author)

- **Spec coverage:** §4 arch → Tasks 5–7; §5 components → Tasks 1–8; §6 values/event-names → Tasks 2,4,6; §7 dedup/fail-soft/env → Tasks 3,5; §8 tests → every task; §9 LP prompts → handoff step; optional ad_id → Task 9.
- **Types consistency:** `dispatch_conversion(lead, event, value, currency)`, `fire_stage_conversion(lead, deal_id, event, value, currency)`, `already_fired(deal_id, event)`, `build_sheet_row(lead, event, value, currency, when)`, `append_conversion_row(row)` — signatures match across tasks.
- **No placeholders:** all code steps contain full code; commands have expected output.
