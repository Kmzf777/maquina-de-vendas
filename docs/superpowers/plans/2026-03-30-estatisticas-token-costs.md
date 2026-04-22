# Estatisticas - Token Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add token cost tracking to the AI agent and create a statistics page in the CRM to visualize costs by period, stage, model, and lead.

**Architecture:** Backend (FastAPI) captures `response.usage` from every OpenAI call and stores it in a `token_usage` table with the current model price snapshotted from `model_pricing`. A new stats router exposes aggregated data. The CRM frontend gets a new `/estatisticas` page with KPI cards, line chart (daily costs), bar charts (by stage/model), and a top-leads table. Model prices are configurable via the existing `/config` page.

**Tech Stack:** FastAPI + Supabase (backend), Next.js 16 + React 19 + Recharts (frontend), Supabase JS client for data fetching.

---

### Task 1: Database Migration

**Files:**
- Create: `backend-evolution/migrations/005_token_usage.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- 005_token_usage.sql
-- Token usage tracking and model pricing tables

-- Model pricing configuration
CREATE TABLE IF NOT EXISTS model_pricing (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model text UNIQUE NOT NULL,
    price_per_input_token numeric NOT NULL,
    price_per_output_token numeric NOT NULL,
    updated_at timestamptz DEFAULT now()
);

-- Seed current OpenAI prices (per token, not per 1M)
-- gpt-4.1:      input $2.00/1M = 0.000002,  output $8.00/1M = 0.000008
-- gpt-4.1-mini: input $0.40/1M = 0.0000004, output $1.60/1M = 0.0000016
-- gpt-4o:       input $2.50/1M = 0.0000025, output $10.00/1M = 0.00001
-- whisper-1:    special — no per-token pricing, uses total_cost directly
INSERT INTO model_pricing (model, price_per_input_token, price_per_output_token) VALUES
    ('gpt-4.1',      0.000002,  0.000008),
    ('gpt-4.1-mini', 0.0000004, 0.0000016),
    ('gpt-4o',       0.0000025, 0.00001),
    ('whisper-1',    0,         0)
ON CONFLICT (model) DO NOTHING;

-- Token usage log
CREATE TABLE IF NOT EXISTS token_usage (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id),
    stage text NOT NULL,
    model text NOT NULL,
    call_type text NOT NULL,
    prompt_tokens integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    price_per_input_token numeric NOT NULL,
    price_per_output_token numeric NOT NULL,
    total_cost numeric NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_token_usage_lead_id ON token_usage(lead_id);
CREATE INDEX idx_token_usage_created_at ON token_usage(created_at);
CREATE INDEX idx_token_usage_stage ON token_usage(stage);
CREATE INDEX idx_token_usage_model ON token_usage(model);

ALTER PUBLICATION supabase_realtime ADD TABLE token_usage;
ALTER PUBLICATION supabase_realtime ADD TABLE model_pricing;
```

- [ ] **Step 2: Run the migration against Supabase**

Run this SQL in the Supabase SQL editor or via psql. Verify the tables exist:

```bash
# In Supabase SQL editor:
SELECT * FROM model_pricing;
-- Should return 4 rows: gpt-4.1, gpt-4.1-mini, gpt-4o, whisper-1
```

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/migrations/005_token_usage.sql
git commit -m "feat: add token_usage and model_pricing tables migration"
```

---

### Task 2: Token Tracker Module (Backend)

**Files:**
- Create: `backend-evolution/app/agent/token_tracker.py`

- [ ] **Step 1: Create the token tracker module**

```python
import logging
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# In-memory cache for model pricing (refreshed per call to avoid stale data in long-running process)
_pricing_cache: dict[str, dict] = {}
_pricing_loaded = False


def _load_pricing():
    global _pricing_cache, _pricing_loaded
    sb = get_supabase()
    result = sb.table("model_pricing").select("*").execute()
    _pricing_cache = {row["model"]: row for row in result.data}
    _pricing_loaded = True


def get_model_pricing(model: str) -> dict | None:
    if not _pricing_loaded:
        _load_pricing()
    return _pricing_cache.get(model)


def refresh_pricing():
    """Force refresh pricing cache. Call after price updates."""
    global _pricing_loaded
    _pricing_loaded = False


def track_token_usage(
    lead_id: str,
    stage: str,
    model: str,
    call_type: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_cost_override: float | None = None,
):
    """Record a single API call's token usage and cost.

    Args:
        lead_id: UUID of the lead
        stage: Agent stage at time of call
        model: Model name (e.g. 'gpt-4.1')
        call_type: One of 'classification', 'response', 'media_description', 'media_transcription'
        prompt_tokens: Input tokens from response.usage
        completion_tokens: Output tokens from response.usage
        total_cost_override: If set, use this instead of calculating from tokens (for Whisper)
    """
    pricing = get_model_pricing(model)

    if pricing:
        price_in = pricing["price_per_input_token"]
        price_out = pricing["price_per_output_token"]
    else:
        logger.warning(f"No pricing found for model {model}, using 0")
        price_in = 0
        price_out = 0

    if total_cost_override is not None:
        total_cost = total_cost_override
    else:
        total_cost = (prompt_tokens * float(price_in)) + (completion_tokens * float(price_out))

    try:
        sb = get_supabase()
        sb.table("token_usage").insert({
            "lead_id": lead_id,
            "stage": stage,
            "model": model,
            "call_type": call_type,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "price_per_input_token": float(price_in),
            "price_per_output_token": float(price_out),
            "total_cost": float(total_cost),
        }).execute()
    except Exception as e:
        logger.error(f"Failed to track token usage: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add backend-evolution/app/agent/token_tracker.py
git commit -m "feat: add token_tracker module for recording API usage costs"
```

---

### Task 3: Integrate Token Tracking into Orchestrator

**Files:**
- Modify: `backend-evolution/app/agent/orchestrator.py`

The orchestrator has 3 OpenAI calls to instrument:
1. Main response call (line 91-97) — `call_type: response`
2. Tool-loop follow-up calls (line 121-127) — `call_type: response`
3. Guardrail classification call (line 181-186) — `call_type: classification`

- [ ] **Step 1: Add import at top of orchestrator.py**

After the existing imports (after line 16), add:

```python
from app.agent.token_tracker import track_token_usage
```

- [ ] **Step 2: Track the main response call**

After line 97 (`max_tokens=500,` + closing paren), before `message = response.choices[0].message`, add tracking:

Replace this block in `run_agent` (lines 91-99):
```python
    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    message = response.choices[0].message
```

With:
```python
    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    # Track token usage
    if response.usage:
        track_token_usage(
            lead_id=lead["id"],
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message
```

- [ ] **Step 3: Track the tool-loop follow-up calls**

Replace the tool-loop OpenAI call block (lines 121-128):
```python
        # Call again to get the text response after tool execution
        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )
        message = response.choices[0].message
```

With:
```python
        # Call again to get the text response after tool execution
        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )

        # Track token usage for tool follow-up
        if response.usage:
            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        message = response.choices[0].message
```

- [ ] **Step 4: Track the guardrail classification call**

In `_guardrail_secretaria`, after the classification OpenAI call (line 181-186), add tracking.

Replace:
```python
    try:
        response = await _get_openai().chat.completions.create(
            model="gpt-4.1-mini",
            messages=classify_messages,
            temperature=0,
            max_tokens=20,
        )
        classification = (response.choices[0].message.content or "").strip().lower()
```

With:
```python
    try:
        response = await _get_openai().chat.completions.create(
            model="gpt-4.1-mini",
            messages=classify_messages,
            temperature=0,
            max_tokens=20,
        )

        # Track classification token usage
        if response.usage:
            track_token_usage(
                lead_id=lead["id"],
                stage="secretaria",
                model="gpt-4.1-mini",
                call_type="classification",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        classification = (response.choices[0].message.content or "").strip().lower()
```

- [ ] **Step 5: Commit**

```bash
git add backend-evolution/app/agent/orchestrator.py
git commit -m "feat: integrate token tracking into orchestrator OpenAI calls"
```

---

### Task 4: Integrate Token Tracking into Media Processing

**Files:**
- Modify: `backend-evolution/app/whatsapp/media.py`
- Modify: `backend-evolution/app/buffer/processor.py`

The media module has 2 OpenAI calls:
1. `transcribe_audio` — Whisper (no tokens, cost by duration)
2. `describe_image` — GPT-4o vision (has tokens)

The challenge: media.py doesn't know the `lead_id` or `stage`. We need to pass them through or track from the processor.

The cleanest approach: have `media.py` return usage info alongside content, and let `processor.py` do the tracking (since it knows the lead).

- [ ] **Step 1: Modify media.py to return usage info**

Replace the full content of `backend-evolution/app/whatsapp/media.py`:

```python
import httpx
from openai import AsyncOpenAI

from app.config import settings

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


async def download_media(media_url: str) -> tuple[bytes, str]:
    """Download media from URL. Returns (bytes, content_type)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(media_url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")


async def transcribe_audio(media_url: str) -> tuple[str, dict]:
    """Download audio and transcribe with Whisper.

    Returns (transcription_text, usage_info).
    usage_info has keys: model, prompt_tokens, completion_tokens, estimated_cost
    """
    audio_bytes, content_type = await download_media(media_url)

    ext = "ogg" if "ogg" in content_type else "mp4"
    transcript = await _get_openai().audio.transcriptions.create(
        model="whisper-1",
        file=(f"audio.{ext}", audio_bytes, content_type),
    )

    # Whisper charges ~$0.006/min. Estimate 30s average per message.
    estimated_cost = 0.003

    usage_info = {
        "model": "whisper-1",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "estimated_cost": estimated_cost,
    }

    return transcript.text, usage_info


async def describe_image(media_url: str) -> tuple[str, dict]:
    """Download image and describe with GPT-4o Vision.

    Returns (description_text, usage_info).
    usage_info has keys: model, prompt_tokens, completion_tokens
    """
    import base64

    image_bytes, content_type = await download_media(media_url)
    b64 = base64.b64encode(image_bytes).decode()

    response = await _get_openai().chat.completions.create(
        model="gpt-4o",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Descreva esta imagem em uma frase curta em portugues. Se for uma foto de produto, descreva o produto."},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
            ],
        }],
        max_tokens=150,
    )

    usage_info = {
        "model": "gpt-4o",
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
    }

    return response.choices[0].message.content, usage_info
```

- [ ] **Step 2: Update processor.py to track media usage**

Replace the full content of `backend-evolution/app/buffer/processor.py`:

```python
import asyncio
import logging

from app.leads.service import get_or_create_lead, activate_lead, update_lead
from app.agent.orchestrator import run_agent
from app.humanizer.splitter import split_into_bubbles
from app.humanizer.typing import calculate_typing_delay
from app.whatsapp.client import send_text
from app.whatsapp.media import transcribe_audio, describe_image
from app.cadence.service import get_cadence_state, pause_cadence
from app.agent.token_tracker import track_token_usage
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


async def process_buffered_messages(phone: str, combined_text: str):
    """Process accumulated buffer messages: resolve media, run agent, humanize, send."""
    try:
        # Get or create lead (need lead_id for media tracking)
        lead = get_or_create_lead(phone)

        # Resolve any media placeholders (with usage tracking)
        resolved_text = await _resolve_media(combined_text, lead)

        # Pause cadence if active
        cadence = get_cadence_state(lead["id"])
        if cadence:
            pause_cadence(cadence["id"])
            sb = get_supabase()
            sb.rpc("increment_cadence_responded", {"campaign_id_param": cadence["campaign_id"]}).execute()
            logger.info(f"[CADENCE] Lead {phone} responded — pausing cadence")

        # Activate lead if pending/template_sent
        if lead.get("status") in ("imported", "template_sent"):
            lead = activate_lead(lead["id"])

        # Run agent
        response = await run_agent(lead, resolved_text)

        # Humanize and send
        bubbles = split_into_bubbles(response)
        for bubble in bubbles:
            delay = calculate_typing_delay(bubble)
            await asyncio.sleep(delay)
            await send_text(phone, bubble)

        # Update last_msg timestamp
        from datetime import datetime, timezone
        update_lead(lead["id"], last_msg_at=datetime.now(timezone.utc).isoformat())

    except Exception as e:
        logger.error(f"Error processing messages for {phone}: {e}", exc_info=True)


async def _resolve_media(text: str, lead: dict) -> str:
    """Replace media placeholders with actual content and track usage."""
    import re

    stage = lead.get("stage", "secretaria")

    # Pattern: [audio: media_url=xxx] or [image: media_url=xxx]
    audio_pattern = r"\[audio: media_url=(\S+)\]"
    image_pattern = r"\[image: media_url=(\S+)\]"

    for match in re.finditer(audio_pattern, text):
        media_url = match.group(1)
        try:
            transcription, usage_info = await transcribe_audio(media_url)
            text = text.replace(match.group(0), f"[audio transcrito: {transcription}]")

            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=usage_info["model"],
                call_type="media_transcription",
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
                total_cost_override=usage_info.get("estimated_cost"),
            )
        except Exception as e:
            logger.warning(f"Failed to transcribe audio: {e}")
            text = text.replace(match.group(0), "[audio: nao foi possivel transcrever]")

    for match in re.finditer(image_pattern, text):
        media_url = match.group(1)
        try:
            description, usage_info = await describe_image(media_url)
            text = text.replace(match.group(0), f"[imagem recebida: {description}]")

            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=usage_info["model"],
                call_type="media_description",
                prompt_tokens=usage_info["prompt_tokens"],
                completion_tokens=usage_info["completion_tokens"],
            )
        except Exception as e:
            logger.warning(f"Failed to describe image: {e}")
            text = text.replace(match.group(0), "[imagem: nao foi possivel descrever]")

    return text
```

- [ ] **Step 3: Commit**

```bash
git add backend-evolution/app/whatsapp/media.py backend-evolution/app/buffer/processor.py
git commit -m "feat: integrate token tracking into media processing (whisper + vision)"
```

---

### Task 5: Stats API Router (Backend)

**Files:**
- Create: `backend-evolution/app/stats/router.py`
- Modify: `backend-evolution/app/main.py`

- [ ] **Step 1: Create the stats router**

```python
from fastapi import APIRouter, Query
from datetime import date, timedelta
from app.db.supabase import get_supabase
from app.agent.token_tracker import refresh_pricing

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/costs")
async def get_costs(
    start_date: date | None = None,
    end_date: date | None = None,
    stage: str | None = None,
    model: str | None = None,
    lead_id: str | None = None,
):
    """Get aggregated cost metrics for the given filters."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    query = (
        sb.table("token_usage")
        .select("total_cost, prompt_tokens, completion_tokens, lead_id")
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
    )

    if stage:
        query = query.eq("stage", stage)
    if model:
        query = query.eq("model", model)
    if lead_id:
        query = query.eq("lead_id", lead_id)

    result = query.execute()
    rows = result.data

    total_cost = sum(float(r["total_cost"]) for r in rows)
    total_calls = len(rows)
    total_prompt_tokens = sum(r["prompt_tokens"] for r in rows)
    total_completion_tokens = sum(r["completion_tokens"] for r in rows)
    unique_leads = len(set(r["lead_id"] for r in rows if r["lead_id"]))
    avg_cost_per_lead = total_cost / unique_leads if unique_leads > 0 else 0

    return {
        "total_cost": round(total_cost, 6),
        "total_calls": total_calls,
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "unique_leads": unique_leads,
        "avg_cost_per_lead": round(avg_cost_per_lead, 6),
    }


@router.get("/costs/daily")
async def get_daily_costs(
    start_date: date | None = None,
    end_date: date | None = None,
    stage: str | None = None,
    model: str | None = None,
):
    """Get costs grouped by day for chart rendering."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    query = (
        sb.table("token_usage")
        .select("total_cost, created_at")
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
    )

    if stage:
        query = query.eq("stage", stage)
    if model:
        query = query.eq("model", model)

    result = query.execute()

    # Group by date
    daily: dict[str, float] = {}
    for row in result.data:
        day = row["created_at"][:10]  # YYYY-MM-DD
        daily[day] = daily.get(day, 0) + float(row["total_cost"])

    # Fill gaps with zeros
    data = []
    current = start_date
    while current < end_date:
        day_str = current.isoformat()
        data.append({"date": day_str, "cost": round(daily.get(day_str, 0), 6)})
        current += timedelta(days=1)

    return {"data": data}


@router.get("/costs/breakdown")
async def get_cost_breakdown(
    start_date: date | None = None,
    end_date: date | None = None,
    group_by: str = Query("stage", pattern="^(stage|model|lead)$"),
):
    """Get costs grouped by stage, model, or lead."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    select_fields = "total_cost, prompt_tokens, completion_tokens, stage, model, lead_id"
    query = (
        sb.table("token_usage")
        .select(select_fields)
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
    )

    result = query.execute()

    groups: dict[str, dict] = {}
    for row in result.data:
        if group_by == "lead":
            key = row["lead_id"] or "unknown"
        else:
            key = row[group_by]

        if key not in groups:
            groups[key] = {"key": key, "cost": 0, "calls": 0, "tokens": 0}

        groups[key]["cost"] += float(row["total_cost"])
        groups[key]["calls"] += 1
        groups[key]["tokens"] += row["prompt_tokens"] + row["completion_tokens"]

    data = sorted(groups.values(), key=lambda x: x["cost"], reverse=True)

    # Round costs
    for item in data:
        item["cost"] = round(item["cost"], 6)

    return {"data": data}


@router.get("/costs/top-leads")
async def get_top_leads(
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(20, le=100),
):
    """Get top leads by cost with lead details."""
    sb = get_supabase()

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today() + timedelta(days=1)

    result = (
        sb.table("token_usage")
        .select("total_cost, prompt_tokens, completion_tokens, lead_id, stage")
        .gte("created_at", start_date.isoformat())
        .lt("created_at", end_date.isoformat())
        .execute()
    )

    # Aggregate by lead
    leads_data: dict[str, dict] = {}
    for row in result.data:
        lid = row["lead_id"]
        if not lid:
            continue
        if lid not in leads_data:
            leads_data[lid] = {"lead_id": lid, "cost": 0, "calls": 0, "tokens": 0, "stage": row["stage"]}
        leads_data[lid]["cost"] += float(row["total_cost"])
        leads_data[lid]["calls"] += 1
        leads_data[lid]["tokens"] += row["prompt_tokens"] + row["completion_tokens"]
        leads_data[lid]["stage"] = row["stage"]  # latest stage

    sorted_leads = sorted(leads_data.values(), key=lambda x: x["cost"], reverse=True)[:limit]

    # Fetch lead names
    if sorted_leads:
        lead_ids = [l["lead_id"] for l in sorted_leads]
        lead_info = sb.table("leads").select("id, name, phone").in_("id", lead_ids).execute()
        lead_map = {l["id"]: l for l in lead_info.data}

        for item in sorted_leads:
            info = lead_map.get(item["lead_id"], {})
            item["name"] = info.get("name") or info.get("phone", "Desconhecido")
            item["phone"] = info.get("phone", "")
            item["cost"] = round(item["cost"], 6)

    return {"data": sorted_leads}
```

- [ ] **Step 2: Create model pricing endpoints**

Create `backend-evolution/app/stats/pricing_router.py`:

```python
from fastapi import APIRouter
from pydantic import BaseModel
from app.db.supabase import get_supabase
from app.agent.token_tracker import refresh_pricing

router = APIRouter(prefix="/api/model-pricing", tags=["pricing"])


class PricingUpdate(BaseModel):
    price_per_input_token: float
    price_per_output_token: float


@router.get("")
async def list_pricing():
    sb = get_supabase()
    result = sb.table("model_pricing").select("*").order("model").execute()
    return {"data": result.data}


@router.put("/{model}")
async def update_pricing(model: str, body: PricingUpdate):
    sb = get_supabase()
    result = (
        sb.table("model_pricing")
        .update({
            "price_per_input_token": body.price_per_input_token,
            "price_per_output_token": body.price_per_output_token,
            "updated_at": "now()",
        })
        .eq("model", model)
        .execute()
    )
    refresh_pricing()
    return {"data": result.data}
```

- [ ] **Step 3: Register both routers in main.py**

In `backend-evolution/app/main.py`, after the existing router imports (after line 43 `from app.cadence.router ...`), add:

```python
from app.stats.router import router as stats_router
from app.stats.pricing_router import router as pricing_router
```

After the existing `app.include_router` calls (after line 48), add:

```python
app.include_router(stats_router)
app.include_router(pricing_router)
```

- [ ] **Step 4: Create the stats __init__.py**

Create `backend-evolution/app/stats/__init__.py` (empty file).

- [ ] **Step 5: Commit**

```bash
git add backend-evolution/app/stats/ backend-evolution/app/main.py
git commit -m "feat: add stats API endpoints for costs, daily, breakdown, and pricing"
```

---

### Task 6: Add Sidebar Navigation Item (Frontend)

**Files:**
- Modify: `crm/src/components/sidebar.tsx`

- [ ] **Step 1: Add Estatisticas nav item to sidebar.tsx**

In the `NAV_ITEMS` array, add a new entry BEFORE the last item (Configuracoes). Insert between the Campanhas entry (ending around line 51) and the Configuracoes entry (starting at line 52):

```typescript
  {
    href: "/estatisticas",
    label: "Estatisticas",
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
```

- [ ] **Step 2: Commit**

```bash
git add crm/src/components/sidebar.tsx
git commit -m "feat: add Estatisticas item to sidebar navigation"
```

---

### Task 7: Statistics Page (Frontend)

**Files:**
- Create: `crm/src/app/(authenticated)/estatisticas/page.tsx`

- [ ] **Step 1: Install Recharts**

```bash
cd crm && npm install recharts
```

- [ ] **Step 2: Create the statistics page**

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { KpiCard } from "@/components/kpi-card";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell,
} from "recharts";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const PERIOD_OPTIONS = [
  { label: "Hoje", days: 1 },
  { label: "7 dias", days: 7 },
  { label: "30 dias", days: 30 },
];

const STAGE_COLORS: Record<string, string> = {
  secretaria: "#c8cc8e",
  atacado: "#5b8aad",
  private_label: "#9b7abf",
  exportacao: "#5aad65",
  consumo: "#d4b84a",
};

const MODEL_COLORS: Record<string, string> = {
  "gpt-4.1": "#5b8aad",
  "gpt-4.1-mini": "#c8cc8e",
  "gpt-4o": "#9b7abf",
  "whisper-1": "#d4b84a",
};

const DollarIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M10 2v16M14 5.5H8.5a2.5 2.5 0 000 5h3a2.5 2.5 0 010 5H6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const CallsIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const TokensIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.8" />
    <path d="M8 8h4M8 12h4M10 6v8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
);
const AvgIcon = (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="7.5" cy="7" r="2.5" stroke="currentColor" strokeWidth="1.8" />
    <path d="M2.5 16c0-2.5 2-4.5 5-4.5s5 2 5 4.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    <path d="M15 6v6M12 9h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

function formatUSD(value: number): string {
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return `${d.getDate()}/${d.getMonth() + 1}`;
}

interface CostSummary {
  total_cost: number;
  total_calls: number;
  total_tokens: number;
  avg_cost_per_lead: number;
  unique_leads: number;
}

interface DailyData {
  date: string;
  cost: number;
}

interface BreakdownItem {
  key: string;
  cost: number;
  calls: number;
  tokens: number;
}

interface TopLead {
  lead_id: string;
  name: string;
  phone: string;
  stage: string;
  cost: number;
  calls: number;
  tokens: number;
}

export default function EstatisticasPage() {
  const [selectedPeriod, setSelectedPeriod] = useState(30);
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [daily, setDaily] = useState<DailyData[]>([]);
  const [byStage, setByStage] = useState<BreakdownItem[]>([]);
  const [byModel, setByModel] = useState<BreakdownItem[]>([]);
  const [topLeads, setTopLeads] = useState<TopLead[]>([]);
  const [loading, setLoading] = useState(true);

  const getDateRange = useCallback(() => {
    if (customStart && customEnd) {
      return { start_date: customStart, end_date: customEnd };
    }
    const end = new Date();
    end.setDate(end.getDate() + 1);
    const start = new Date();
    start.setDate(start.getDate() - selectedPeriod);
    return {
      start_date: start.toISOString().slice(0, 10),
      end_date: end.toISOString().slice(0, 10),
    };
  }, [selectedPeriod, customStart, customEnd]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    const { start_date, end_date } = getDateRange();
    const params = `start_date=${start_date}&end_date=${end_date}`;

    try {
      const [summaryRes, dailyRes, stageRes, modelRes, leadsRes] = await Promise.all([
        fetch(`${API_BASE}/api/stats/costs?${params}`),
        fetch(`${API_BASE}/api/stats/costs/daily?${params}`),
        fetch(`${API_BASE}/api/stats/costs/breakdown?${params}&group_by=stage`),
        fetch(`${API_BASE}/api/stats/costs/breakdown?${params}&group_by=model`),
        fetch(`${API_BASE}/api/stats/costs/top-leads?${params}&limit=20`),
      ]);

      const [summaryData, dailyData, stageData, modelData, leadsData] = await Promise.all([
        summaryRes.json(),
        dailyRes.json(),
        stageRes.json(),
        modelRes.json(),
        leadsRes.json(),
      ]);

      setSummary(summaryData);
      setDaily(dailyData.data);
      setByStage(stageData.data);
      setByModel(modelData.data);
      setTopLeads(leadsData.data);
    } catch (e) {
      console.error("Failed to fetch stats:", e);
    } finally {
      setLoading(false);
    }
  }, [getDateRange]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <div className="h-8 w-48 rounded-lg animate-pulse" style={{ backgroundColor: "#e5e5dc" }} />
          <div className="h-4 w-72 rounded-lg animate-pulse mt-2" style={{ backgroundColor: "#e5e5dc" }} />
        </div>
        <div className="grid grid-cols-4 gap-5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-[28px] font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
            Estatisticas
          </h1>
          <p className="text-[14px] mt-1" style={{ color: "var(--text-muted)" }}>
            Custos e consumo do agente de IA
          </p>
        </div>

        {/* Period Filter */}
        <div className="flex items-center gap-2">
          <nav className="inline-flex gap-1 p-1 bg-[#f6f7ed] rounded-xl">
            {PERIOD_OPTIONS.map((opt) => (
              <button
                key={opt.days}
                onClick={() => { setSelectedPeriod(opt.days); setCustomStart(""); setCustomEnd(""); }}
                className={`px-4 py-2 text-[13px] font-medium rounded-lg transition-all ${
                  selectedPeriod === opt.days && !customStart
                    ? "bg-[#1f1f1f] text-white shadow-sm"
                    : "text-[#5f6368] hover:text-[#1f1f1f] hover:bg-white/60"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </nav>
          <div className="flex items-center gap-1.5 ml-2">
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white"
            />
            <span className="text-[13px] text-[#5f6368]">a</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white"
            />
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-4 gap-5 mb-8">
        <KpiCard label="Custo Total" value={formatUSD(summary?.total_cost ?? 0)} icon={DollarIcon} />
        <KpiCard label="Chamadas API" value={summary?.total_calls ?? 0} icon={CallsIcon} />
        <KpiCard label="Tokens Consumidos" value={(summary?.total_tokens ?? 0).toLocaleString()} icon={TokensIcon} />
        <KpiCard
          label="Custo Medio/Lead"
          value={formatUSD(summary?.avg_cost_per_lead ?? 0)}
          subtitle={`${summary?.unique_leads ?? 0} leads`}
          icon={AvgIcon}
        />
      </div>

      {/* Daily Cost Line Chart */}
      <div className="card p-6 mb-8">
        <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          Custo Diario (USD)
        </h2>
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={daily}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e5dc" />
            <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 12, fill: "#8a8a8a" }} />
            <YAxis tick={{ fontSize: 12, fill: "#8a8a8a" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
            <Tooltip
              formatter={(value: number) => [`$${value.toFixed(4)}`, "Custo"]}
              labelFormatter={(label: string) => formatDate(label)}
            />
            <Line type="monotone" dataKey="cost" stroke="#6b8e5a" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Breakdown Charts */}
      <div className="grid grid-cols-2 gap-5 mb-8">
        {/* By Stage */}
        <div className="card p-6">
          <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Custo por Stage
          </h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={byStage}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5dc" />
              <XAxis dataKey="key" tick={{ fontSize: 12, fill: "#8a8a8a" }} />
              <YAxis tick={{ fontSize: 12, fill: "#8a8a8a" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
              <Tooltip formatter={(value: number) => [`$${value.toFixed(4)}`, "Custo"]} />
              <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                {byStage.map((entry) => (
                  <Cell key={entry.key} fill={STAGE_COLORS[entry.key] || "#8a8a8a"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* By Model */}
        <div className="card p-6">
          <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
            Custo por Modelo
          </h2>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={byModel}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e5dc" />
              <XAxis dataKey="key" tick={{ fontSize: 12, fill: "#8a8a8a" }} />
              <YAxis tick={{ fontSize: 12, fill: "#8a8a8a" }} tickFormatter={(v: number) => `$${v.toFixed(2)}`} />
              <Tooltip formatter={(value: number) => [`$${value.toFixed(4)}`, "Custo"]} />
              <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                {byModel.map((entry) => (
                  <Cell key={entry.key} fill={MODEL_COLORS[entry.key] || "#8a8a8a"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Leads Table */}
      <div className="card p-6">
        <h2 className="text-[15px] font-semibold mb-4" style={{ color: "var(--text-primary)" }}>
          Top Leads por Custo
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#e5e5dc]">
                <th className="text-left text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3 pl-2">Lead</th>
                <th className="text-left text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3">Stage</th>
                <th className="text-right text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3">Chamadas</th>
                <th className="text-right text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3">Tokens</th>
                <th className="text-right text-[12px] font-medium text-[#8a8a8a] uppercase tracking-wider pb-3 pr-2">Custo</th>
              </tr>
            </thead>
            <tbody>
              {topLeads.map((lead) => (
                <tr key={lead.lead_id} className="border-b border-[#f0f0e8] hover:bg-[#fafaf5] transition-colors">
                  <td className="py-3 pl-2">
                    <div className="text-[13px] font-medium" style={{ color: "var(--text-primary)" }}>{lead.name}</div>
                    {lead.phone && (
                      <div className="text-[12px]" style={{ color: "var(--text-muted)" }}>{lead.phone}</div>
                    )}
                  </td>
                  <td className="py-3">
                    <span className="text-[12px] font-medium px-2.5 py-1 rounded-full" style={{
                      backgroundColor: `${STAGE_COLORS[lead.stage] || "#8a8a8a"}20`,
                      color: STAGE_COLORS[lead.stage] || "#8a8a8a",
                    }}>
                      {lead.stage}
                    </span>
                  </td>
                  <td className="py-3 text-right text-[13px]" style={{ color: "var(--text-secondary)" }}>{lead.calls}</td>
                  <td className="py-3 text-right text-[13px]" style={{ color: "var(--text-secondary)" }}>{lead.tokens.toLocaleString()}</td>
                  <td className="py-3 text-right text-[13px] font-medium pr-2" style={{ color: "var(--text-primary)" }}>{formatUSD(lead.cost)}</td>
                </tr>
              ))}
              {topLeads.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-[13px]" style={{ color: "var(--text-muted)" }}>
                    Nenhum dado de custo encontrado para o periodo selecionado
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/app/\(authenticated\)/estatisticas/page.tsx
git commit -m "feat: add Estatisticas page with cost KPIs, charts, and top leads table"
```

---

### Task 8: Model Pricing Config Tab (Frontend)

**Files:**
- Create: `crm/src/components/config/pricing-tab.tsx`
- Modify: `crm/src/app/(authenticated)/config/page.tsx`

- [ ] **Step 1: Create the pricing tab component**

```tsx
"use client";

import { useState, useEffect } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ModelPrice {
  id: string;
  model: string;
  price_per_input_token: number;
  price_per_output_token: number;
  updated_at: string;
}

export function PricingTab() {
  const [models, setModels] = useState<ModelPrice[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [editValues, setEditValues] = useState<Record<string, { input: string; output: string }>>({});

  useEffect(() => {
    fetch(`${API_BASE}/api/model-pricing`)
      .then((r) => r.json())
      .then((data) => {
        setModels(data.data);
        const initial: Record<string, { input: string; output: string }> = {};
        for (const m of data.data) {
          // Display as price per 1M tokens for readability
          initial[m.model] = {
            input: (m.price_per_input_token * 1_000_000).toFixed(2),
            output: (m.price_per_output_token * 1_000_000).toFixed(2),
          };
        }
        setEditValues(initial);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const handleSave = async (model: string) => {
    const vals = editValues[model];
    if (!vals) return;

    setSaving(model);
    try {
      await fetch(`${API_BASE}/api/model-pricing/${model}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          price_per_input_token: parseFloat(vals.input) / 1_000_000,
          price_per_output_token: parseFloat(vals.output) / 1_000_000,
        }),
      });
      // Refresh
      const res = await fetch(`${API_BASE}/api/model-pricing`);
      const data = await res.json();
      setModels(data.data);
    } catch (e) {
      console.error("Failed to save pricing:", e);
    } finally {
      setSaving(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-20 rounded-xl animate-pulse" style={{ backgroundColor: "rgba(229,229,220,0.3)" }} />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-[13px] mb-4" style={{ color: "var(--text-muted)" }}>
        Precos por 1M tokens (USD). Estes valores sao usados para calcular o custo de cada chamada ao agente.
      </p>

      {models.map((m) => (
        <div key={m.model} className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-[14px] font-semibold" style={{ color: "var(--text-primary)" }}>
              {m.model}
            </h3>
            <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>
              Atualizado: {new Date(m.updated_at).toLocaleDateString("pt-BR")}
            </span>
          </div>

          <div className="flex items-end gap-4">
            <div className="flex-1">
              <label className="block text-[12px] font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                Input ($/1M tokens)
              </label>
              <input
                type="number"
                step="0.01"
                value={editValues[m.model]?.input ?? ""}
                onChange={(e) =>
                  setEditValues((prev) => ({
                    ...prev,
                    [m.model]: { ...prev[m.model], input: e.target.value },
                  }))
                }
                className="w-full px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white focus:outline-none focus:ring-2 focus:ring-[#c8cc8e]"
              />
            </div>
            <div className="flex-1">
              <label className="block text-[12px] font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
                Output ($/1M tokens)
              </label>
              <input
                type="number"
                step="0.01"
                value={editValues[m.model]?.output ?? ""}
                onChange={(e) =>
                  setEditValues((prev) => ({
                    ...prev,
                    [m.model]: { ...prev[m.model], output: e.target.value },
                  }))
                }
                className="w-full px-3 py-2 text-[13px] rounded-lg border border-[#e0e0d8] bg-white focus:outline-none focus:ring-2 focus:ring-[#c8cc8e]"
              />
            </div>
            <button
              onClick={() => handleSave(m.model)}
              disabled={saving === m.model}
              className="px-5 py-2 text-[13px] font-medium rounded-lg text-white transition-all disabled:opacity-50"
              style={{ backgroundColor: "var(--accent-olive)" }}
            >
              {saving === m.model ? "Salvando..." : "Salvar"}
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Add the pricing tab to config page**

In `crm/src/app/(authenticated)/config/page.tsx`:

Add import:
```tsx
import { PricingTab } from "@/components/config/pricing-tab";
```

Update TABS array to add the new tab:
```tsx
const TABS = [
  { key: "whatsapp", label: "WhatsApp" },
  { key: "tags", label: "Tags" },
  { key: "pricing", label: "Precos IA" },
] as const;
```

Add the tab render after the tags conditional (after `{activeTab === "tags" && <TagsTab />}`):
```tsx
      {activeTab === "pricing" && <PricingTab />}
```

- [ ] **Step 3: Commit**

```bash
git add crm/src/components/config/pricing-tab.tsx crm/src/app/\(authenticated\)/config/page.tsx
git commit -m "feat: add model pricing configuration tab to settings page"
```

---

### Task 9: Verify and Test End-to-End

- [ ] **Step 1: Run the migration SQL in Supabase**

Verify tables exist:
```sql
SELECT * FROM model_pricing;
SELECT * FROM token_usage LIMIT 1;
```

- [ ] **Step 2: Start the backend and verify new endpoints**

```bash
cd backend-evolution
uvicorn app.main:app --reload
```

Test endpoints:
```bash
curl http://localhost:8000/api/model-pricing
curl http://localhost:8000/api/stats/costs
curl http://localhost:8000/api/stats/costs/daily
curl "http://localhost:8000/api/stats/costs/breakdown?group_by=stage"
curl http://localhost:8000/api/stats/costs/top-leads
```

- [ ] **Step 3: Start the frontend and verify the page**

```bash
cd crm
npm run dev
```

Navigate to `/estatisticas` and verify:
- Page loads without errors
- KPI cards show zeros (no data yet)
- Charts render empty states
- Table shows "Nenhum dado" message
- Navigate to `/config` and verify "Precos IA" tab shows model prices

- [ ] **Step 4: Test token tracking**

Send a test message through WhatsApp to trigger the agent. Then:
```sql
SELECT * FROM token_usage ORDER BY created_at DESC LIMIT 5;
```

Verify rows are being created with correct model, stage, tokens, and cost values.

- [ ] **Step 5: Verify the statistics page shows data**

After sending test messages, refresh `/estatisticas`:
- KPI cards should show non-zero values
- Line chart should show a data point for today
- Bar charts should show breakdown by stage/model
- Table should list the lead(s)

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete token cost tracking and statistics page"
```
