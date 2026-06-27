# Multi-touch Cadence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the 2-touch follow-up engine into a 4-touch state-based cadence that, on a closed 24h window, fires an approved Meta template + schedules resumption instead of canceling.

**Architecture:** Config-as-code cadence (`follow_up/cadence.py`) with per-touch objectives; `schedule_followup` builds 4 monotonically-spaced jobs; `process_due_followups`'s generic branch decides per touch by live 24h-window state (open→objective-aware free-text; closed→template+`awaiting_reopen`, or context-refresh if a reopen is already live). The closed-window template logic is extracted from `_process_ai_scheduled_return` into a shared `fire_reopen_template` helper. Resumption reuses the existing `consume_reopen_context` (already wired on every inbound).

**Tech Stack:** Python 3.11, FastAPI, Supabase (supabase-py), pytest (`asyncio_mode=auto`). Spec: `docs/superpowers/specs/2026-06-26-multitouch-cadence-design.md` (READ for full detail).

## Global Constraints

- **Scope:** evolve ONLY `backend/app/follow_up/`. Do NOT touch `backend/app/automation/`. No schema migration (`follow_up_jobs.metadata` jsonb + `sequence` int already exist). No frontend.
- **Cadence (config-as-code), clamped to 09:00–16:00 Mon–Fri America/Sao_Paulo:**
  - T1 sequence=1, offset 0 + jitter 90–210 min, objective `reengajar`
  - T2 sequence=2, offset `timedelta(days=1)`, objective `reforco_valor`
  - T3 sequence=3, offset `timedelta(days=3)`, objective `prova_social`
  - T4 sequence=4, offset `timedelta(days=6, hours=20)`, objective `ultima_chamada`
- **R2 monotonic spacing:** `MIN_GAP = timedelta(hours=2)`; after clamping Tn, if `fire_at(Tn) <= fire_at(Tn-1) + MIN_GAP` then `fire_at(Tn) = _clamp_to_business_window(fire_at(Tn-1) + MIN_GAP)`. Strict order, spacing ≥ MIN_GAP.
- **Per-touch window decision (live):** no touch is hardwired to a modality; each reads `conversations.last_customer_message_at` at fire time. The first template may go out at T1, T2, or T3.
- **R1 closed-window with an existing `awaiting_reopen`:** overwrite that job's `metadata.contexto` AND `metadata.motivo` with this touch's objective; end this touch with `status="cancelled", cancel_reason="reopen_context_refreshed"`. Do NOT fire a 2nd template (max 1 reopen template alive per conversation).
- **Closed-window, no existing `awaiting_reopen`:** fire approved template `continuar_conversa` (named param `{{primeiro_nome}}`, `language_code="pt_BR"`); persist the dispatch (`sent_by="followup"`, `metadata=dispatch_metadata("continuar_conversa")`); mark the job `awaiting_reopen` with `metadata.motivo`/`contexto` = touch objective. Meta error handling identical to `_process_ai_scheduled_return`: httpx 4xx → `cancel_reason="reopen_template_error_<status>"`; `RuntimeError` rejection → `reopen_template_rejected`; 5xx/transient → return (retry next tick).
- **Fail-soft:** never raise into the worker loop; existing guardrails (deferral marker, `finish_reason=="length"`, meta-comment, literal-newline sanitize) preserved on the open-window path.
- Reuse the approved template only — create NO new Meta template.

---

### Task 1: Cadence config + job builder (`cadence.py`)

**Files:**
- Create: `backend/app/follow_up/cadence.py`
- Test: `backend/tests/test_multitouch_cadence.py`

**Interfaces:**
- Consumes: `app.follow_up.service._clamp_to_business_window(dt: datetime) -> datetime` (existing).
- Produces:
  - `Touch` dataclass: `sequence:int, offset:timedelta, jitter_minutes:tuple[int,int]|None, objective:str, objective_prompt:str`
  - `CADENCE: tuple[Touch, ...]` (the 4 touches above)
  - `MIN_GAP: timedelta` (2h)
  - `build_touch_jobs(now:datetime, conversation_id:str, lead_id:str, channel_id:str, env_tag:str, rng=random) -> list[dict]` — returns 4 job dicts ready for insert; each dict has keys: `conversation_id, lead_id, channel_id, sequence, fire_at` (ISO str), `status="pending"`, `env_tag`, `metadata={"objetivo":..., "objective_prompt":..., "contexto":...}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_multitouch_cadence.py
from datetime import datetime, timezone, timedelta
import importlib


def _utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


def test_build_touch_jobs_creates_four_sequential_jobs():
    from app.follow_up.cadence import build_touch_jobs, CADENCE
    assert len(CADENCE) == 4
    # Monday 12:00 UTC = 09:00 BRT (inside window)
    now = _utc(2026, 6, 29, 12, 0)
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    assert [j["sequence"] for j in jobs] == [1, 2, 3, 4]
    assert all(j["status"] == "pending" for j in jobs)
    assert all(j["env_tag"] == "dev" for j in jobs)
    assert all(j["conversation_id"] == "conv-1" for j in jobs)
    # objectives carried in metadata, in order
    assert [j["metadata"]["objetivo"] for j in jobs] == [
        "reengajar", "reforco_valor", "prova_social", "ultima_chamada"
    ]
    # contexto mirrors objective (for reopen reuse), objective_prompt present
    for j in jobs:
        assert j["metadata"]["contexto"] == j["metadata"]["objetivo"]
        assert j["metadata"]["objective_prompt"]


def test_build_touch_jobs_fire_at_monotonic_and_in_business_window():
    from app.follow_up.cadence import build_touch_jobs, MIN_GAP
    from app.follow_up.service import is_within_business_window
    # Friday 23:00 BRT = Saturday 02:00 UTC — the collision scenario (R2)
    now = _utc(2026, 6, 27, 2, 0)  # Sat 02:00 UTC = Fri 23:00 BRT
    jobs = build_touch_jobs(now, "conv-1", "lead-1", "chan-1", "dev")
    fires = [datetime.fromisoformat(j["fire_at"]) for j in jobs]
    # strictly increasing with >= MIN_GAP spacing, all inside business window
    for earlier, later in zip(fires, fires[1:]):
        assert later >= earlier + MIN_GAP
    for f in fires:
        assert is_within_business_window(f)


def test_build_touch_jobs_t1_jitter_within_range():
    from app.follow_up.cadence import build_touch_jobs

    class _FixedRng:
        def randint(self, a, b):
            return a  # lower bound -> 90 min
    now = _utc(2026, 6, 29, 12, 0)  # Mon 09:00 BRT
    jobs = build_touch_jobs(now, "c", "l", "ch", "dev", rng=_FixedRng())
    t1_fire = datetime.fromisoformat(jobs[0]["fire_at"])
    # 09:00 BRT + 90 min = 10:30 BRT = 13:30 UTC, still in window
    assert t1_fire == _utc(2026, 6, 29, 13, 30)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.follow_up.cadence'`

- [ ] **Step 3: Implement `cadence.py`**

```python
# backend/app/follow_up/cadence.py
"""Config-as-code da cadência multi-touch (Feature 3).

Esqueleto determinístico (offset + objetivo por toque); o TEXTO de cada toque é
gerado pelo LLM em runtime a partir do objetivo (Next Best Action). Ver
docs/superpowers/specs/2026-06-26-multitouch-cadence-design.md
"""
from __future__ import annotations

import random as _random
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.follow_up.service import _clamp_to_business_window


@dataclass(frozen=True)
class Touch:
    sequence: int
    offset: timedelta
    jitter_minutes: tuple[int, int] | None
    objective: str
    objective_prompt: str


# Espaçamento mínimo entre toques consecutivos (R2): impede encavalamento quando o
# clamp empurra vários toques para a mesma abertura comercial (ex.: seg 09h pós fim de semana).
MIN_GAP = timedelta(hours=2)

CADENCE: tuple[Touch, ...] = (
    Touch(
        1, timedelta(0), (90, 210), "reengajar",
        "Este é o 1º toque (REENGAJAR): retome o assunto com leveza e desperte curiosidade. "
        "Uma única pergunta aberta; não repita o que já foi dito; não pressione.",
    ),
    Touch(
        2, timedelta(days=1), None, "reforco_valor",
        "Este é o toque de REFORÇO DE VALOR (WIIFM): conecte o nosso diferencial à realidade "
        "do lead (o que ele ganha). Uma pergunta de reflexão; nada de tabela de preço.",
    ),
    Touch(
        3, timedelta(days=3), None, "prova_social",
        "Este é o toque de PROVA SOCIAL / quebra de objeção: traga um caso real curto de outro "
        "parceiro e uma pergunta que ajude o lead a se ver no exemplo. Sem repetir toques anteriores.",
    ),
    Touch(
        4, timedelta(days=6, hours=20), None, "ultima_chamada",
        "Este é o toque de ÚLTIMA CHAMADA: sinalize com elegância que vai pausar o contato e "
        "deixe a porta aberta. Tom respeitoso, sem culpa nem urgência artificial.",
    ),
)


def build_touch_jobs(
    now: datetime,
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    env_tag: str,
    rng=_random,
) -> list[dict]:
    """Constrói os 4 jobs da cadência com fire_at monotônico (>= MIN_GAP) e clampado.

    Função pura: sem I/O. `rng` injetável para teste do jitter do T1.
    """
    jobs: list[dict] = []
    prev_fire: datetime | None = None
    for touch in CADENCE:
        offset = touch.offset
        if touch.jitter_minutes:
            lo, hi = touch.jitter_minutes
            offset = offset + timedelta(minutes=rng.randint(lo, hi))
        fire_at = _clamp_to_business_window(now + offset)
        if prev_fire is not None and fire_at <= prev_fire + MIN_GAP:
            fire_at = _clamp_to_business_window(prev_fire + MIN_GAP)
        prev_fire = fire_at
        jobs.append({
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": channel_id,
            "sequence": touch.sequence,
            "fire_at": fire_at.isoformat(),
            "status": "pending",
            "env_tag": env_tag,
            "metadata": {
                "objetivo": touch.objective,
                "objective_prompt": touch.objective_prompt,
                "contexto": touch.objective,
            },
        })
    return jobs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow_up/cadence.py backend/tests/test_multitouch_cadence.py
git commit -m "feat(cadence): config-as-code 4-touch ladder with monotonic spacing"
```

---

### Task 2: `schedule_followup` builds 4 touches

**Files:**
- Modify: `backend/app/follow_up/service.py` (function `schedule_followup`, lines ~56-141)
- Test: `backend/tests/test_multitouch_cadence.py` (append)

**Interfaces:**
- Consumes: `app.follow_up.cadence.build_touch_jobs` (Task 1).
- Produces: `schedule_followup(conversation_id, lead_id, channel_id) -> None` now inserts the 4 cadence jobs (was 2). Same signature; same idempotent cancel of prior pending (preserving `handoff_rescue`/`lp_welcome`).

- [ ] **Step 1: Write the failing test (append to test_multitouch_cadence.py)**

```python
def test_schedule_followup_inserts_four_jobs(monkeypatch):
    from app.follow_up import service

    inserted = {}

    class _Tbl:
        def __init__(self, name): self.name = name; self._payload = None; self._upd = None
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def not_(self): return self
        def in_(self, *a, **k): return self
        def update(self, payload): self._upd = payload; return self
        def insert(self, payload): inserted["rows"] = payload; return self
        def execute(self):
            if self.name == "conversations" and self._upd is None:
                return type("R", (), {"data": [{"id": "conv-1"}]})()
            return type("R", (), {"data": []})()

    class _SB:
        def table(self, name): return _Tbl(name)

    monkeypatch.setattr(service, "get_supabase", lambda: _SB())
    service.schedule_followup("conv-1", "lead-1", "chan-1")
    assert len(inserted["rows"]) == 4
    assert [r["sequence"] for r in inserted["rows"]] == [1, 2, 3, 4]
    assert inserted["rows"][3]["metadata"]["objetivo"] == "ultima_chamada"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py::test_schedule_followup_inserts_four_jobs -q`
Expected: FAIL — assertion `len(inserted["rows"]) == 4` fails (currently inserts 2).

- [ ] **Step 3: Replace the job-building block in `schedule_followup`**

In `backend/app/follow_up/service.py`, replace the `seq1_minutes ... jobs = [ ... ]` block (the `fire_at_seq1`/`fire_at_seq2` construction and the two-element `jobs` list, lines ~104-130) with:

```python
    # Cadência multi-touch (4 toques) — config-as-code em follow_up/cadence.py.
    # fire_at monotônico (espaçado >= MIN_GAP) e clampado à janela comercial.
    from app.follow_up.cadence import build_touch_jobs
    jobs = build_touch_jobs(now, conversation_id, lead_id, channel_id, _ENV_TAG)
```

Leave the conversation-existence check, the prior-pending cancel, and the `sb.table("follow_up_jobs").insert(jobs).execute()` exactly as they are. Update the final log line to:

```python
    logger.info(f"[FOLLOWUP] Agendados {len(jobs)} toques de cadência conversation={conversation_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow_up/service.py backend/tests/test_multitouch_cadence.py
git commit -m "feat(followup): schedule_followup builds the 4-touch cadence"
```

---

### Task 3: Extract `fire_reopen_template` helper (no behavior change)

**Files:**
- Modify: `backend/app/follow_up/scheduler.py` (extract from `_process_ai_scheduled_return`, lines ~1083-1132; add helper near `_mark_awaiting_reopen` ~1217)
- Test: `backend/tests/test_multitouch_cadence.py` (append)

**Interfaces:**
- Consumes: existing module globals in `scheduler.py` — `_REOPEN_TEMPLATE_NAME`, `MetaCloudClient`, `extract_wamid`, `save_message`, `dispatch_metadata`, `_cancel_job`, `_mark_awaiting_reopen`, `resolve_send_target`.
- Produces:
  `async def fire_reopen_template(job: dict, lead: dict, channel: dict, conversation_id: str, *, motivo: str = "", contexto: str = "") -> bool`
  Fires `continuar_conversa`; on success persists the dispatch, stores `motivo`/`contexto` into the job's `metadata` (so resumption sees the objective), marks the job `awaiting_reopen`, returns `True`. On Meta 4xx → `_cancel_job(reopen_template_error_<status>)`, returns `False`. On `RuntimeError` rejection → `_cancel_job(reopen_template_rejected)`, returns `False`. On transient/5xx → returns `False` WITHOUT canceling (retry next tick).

- [ ] **Step 1: Write the failing tests (append)**

```python
import pytest


def _reopen_job():
    return {"id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1", "metadata": {}}


@pytest.mark.asyncio
async def test_fire_reopen_template_success_marks_awaiting_reopen(monkeypatch):
    from app.follow_up import scheduler

    calls = {"awaiting": None, "saved": None, "meta": None}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            calls["meta"] = (to, name, language_code)
            return {"messages": [{"id": "wamid-x"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "save_message", lambda **kw: calls.__setitem__("saved", kw))
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: calls.__setitem__("awaiting", jid))
    monkeypatch.setattr(scheduler, "extract_wamid", lambda r: "wamid-x")
    # store-metadata helper writes to DB; stub it to capture
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda jid, motivo, contexto: calls.__setitem__("ctx", (jid, motivo, contexto)))

    lead = {"id": "lead-1", "name": "Ana Silva", "phone": "5511999999999"}
    channel = {"provider_config": {}}
    ok = await scheduler.fire_reopen_template(
        _reopen_job(), lead, channel, "conv-1", motivo="ultima_chamada", contexto="ultima_chamada"
    )
    assert ok is True
    assert calls["awaiting"] == "job-1"
    assert calls["meta"][1] == scheduler._REOPEN_TEMPLATE_NAME
    assert calls["meta"][2] == "pt_BR"
    assert calls["ctx"] == ("job-1", "ultima_chamada", "ultima_chamada")


@pytest.mark.asyncio
async def test_fire_reopen_template_4xx_cancels(monkeypatch):
    import httpx
    from app.follow_up import scheduler

    cancelled = {}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            req = httpx.Request("POST", "https://graph.facebook.com")
            resp = httpx.Response(400, request=req)
            raise httpx.HTTPStatusError("bad", request=req, response=resp)

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancelled.update({"id": jid, "reason": reason}))

    lead = {"id": "lead-1", "name": "Ana", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(_reopen_job(), lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x")
    assert ok is False
    assert cancelled["reason"] == "reopen_template_error_400"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py -k fire_reopen_template -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'fire_reopen_template'`

- [ ] **Step 3: Add the helper + `_store_reopen_context`, and refactor `_process_ai_scheduled_return` to call it**

Add near `_mark_awaiting_reopen` in `scheduler.py`:

```python
def _store_reopen_context(job_id: str, motivo: str, contexto: str) -> None:
    """Grava motivo/contexto no metadata do job (origem do <retorno_agendado> na retomada)."""
    sb = get_supabase()
    try:
        cur = sb.table("follow_up_jobs").select("metadata").eq("id", job_id).limit(1).execute()
        md = (cur.data[0].get("metadata") if cur.data else None) or {}
        md = {**md, "motivo": motivo, "contexto": contexto}
        sb.table("follow_up_jobs").update({"metadata": md}).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("[REOPEN] falha ao gravar contexto no job %s: %s", job_id, exc)


async def fire_reopen_template(
    job: dict, lead: dict, channel: dict, conversation_id: str, *, motivo: str = "", contexto: str = "",
) -> bool:
    """Janela fechada → dispara o template aprovado de reabertura e marca awaiting_reopen.

    Helper compartilhado por _process_ai_scheduled_return e pelo follow-up multi-touch.
    Retorna True quando o template foi disparado e o job ficou awaiting_reopen; False em erro
    (4xx/rejeição → cancela o job; transitório → não cancela, retry no próximo tick).
    """
    send_to = resolve_send_target(lead, lead.get("phone", ""))
    first_name = (lead.get("name") or "").split()[0] if lead.get("name") else ""
    components = (
        [{"type": "body",
          "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": first_name}]}]
        if first_name else None
    )
    try:
        provider_meta = MetaCloudClient(channel["provider_config"])
        send_result = await provider_meta.send_template(
            send_to, _REOPEN_TEMPLATE_NAME, components=components, language_code="pt_BR"
        )
    except httpx.HTTPStatusError as http_exc:
        status = http_exc.response.status_code
        if 400 <= status < 500:
            _cancel_job(job["id"], f"reopen_template_error_{status}")
            logger.error("[REOPEN] erro permanente Meta %s conv=%s", status, conversation_id)
        else:
            logger.error("[REOPEN] erro transitório Meta %s conv=%s — retry", status, conversation_id)
        return False
    except RuntimeError as exc:
        _cancel_job(job["id"], "reopen_template_rejected")
        logger.error("[REOPEN] rejeição permanente conv=%s: %s", conversation_id, exc)
        return False
    except Exception as exc:
        logger.error("[REOPEN] falha ao enviar template conv=%s: %s", conversation_id, exc, exc_info=True)
        return False

    try:
        save_message(
            lead_id=job["lead_id"],
            role="assistant",
            content="continuar a conversa de onde paramos",
            sent_by="followup",
            conversation_id=conversation_id,
            wamid=extract_wamid(send_result),
            metadata=dispatch_metadata(_REOPEN_TEMPLATE_NAME),
        )
    except Exception as exc:
        logger.error("[REOPEN] falha ao persistir disparo conv=%s: %s", conversation_id, exc)

    _store_reopen_context(job["id"], motivo, contexto)
    _mark_awaiting_reopen(job["id"])
    logger.info("[REOPEN] template '%s' disparado, awaiting_reopen conv=%s", _REOPEN_TEMPLATE_NAME, conversation_id)
    return True
```

Then, in `_process_ai_scheduled_return`, replace the inline closed-window block (the `if not window_open:` body that builds components, calls `send_template`, persists, and calls `_mark_awaiting_reopen`, lines ~1083-1132) with:

```python
    if not window_open:
        motivo = (metadata.get("motivo") or "").strip()
        contexto = (metadata.get("contexto") or "").strip()
        await fire_reopen_template(job, lead, channel, conversation_id, motivo=motivo, contexto=contexto)
        return
```

- [ ] **Step 4: Run tests to verify they pass + no regression**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py tests/test_agendar_retorno_2026_06_25.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow_up/scheduler.py backend/tests/test_multitouch_cadence.py
git commit -m "refactor(followup): extract fire_reopen_template shared helper"
```

---

### Task 4: Multi-touch generic branch (objective free-text + closed-window template/refresh)

**Files:**
- Modify: `backend/app/follow_up/scheduler.py` (generic branch in `process_due_followups` lines ~509-625; `_generate_followup_message` signature ~398)
- Test: `backend/tests/test_multitouch_cadence.py` (append)

**Interfaces:**
- Consumes: `fire_reopen_template` (Task 3); `_generate_followup_message` (extended).
- Produces:
  - `_generate_followup_message(history, sequence, lead_id=None, stage=None, objective_prompt=None) -> tuple[str,str]` — when `objective_prompt` is set, it is injected as the touch's Next Best Action; else unchanged.
  - `_pending_reopen_job(conversation_id: str) -> dict | None` — returns the live `awaiting_reopen` job for the conversation (or None).
  - generic branch behavior: window OPEN → objective-aware free-text; window CLOSED → if a pending `awaiting_reopen` exists, overwrite its `metadata.contexto`/`motivo` with this touch's objective and `_cancel_job(reopen_context_refreshed)`; else `fire_reopen_template`.

- [ ] **Step 1: Write the failing tests (append)**

```python
@pytest.mark.asyncio
async def test_closed_window_no_reopen_fires_template(monkeypatch):
    from app.follow_up import scheduler

    fired = {}
    monkeypatch.setattr(scheduler, "get_due_followups", lambda now, limit=10: [{
        "id": "job-2", "conversation_id": "conv-1", "lead_id": "lead-1", "sequence": 2,
        "job_type": None, "metadata": {"objetivo": "reforco_valor", "objective_prompt": "p"},
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Ana",
                  "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
        "channels": {"id": "chan-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
    }])
    monkeypatch.setattr(scheduler, "_pending_reopen_job", lambda cid: None)
    async def _fake_fire(job, lead, channel, conv, *, motivo="", contexto=""):
        fired.update({"job": job["id"], "contexto": contexto}); return True
    monkeypatch.setattr(scheduler, "fire_reopen_template", _fake_fire)

    await scheduler.process_due_followups(now=__import__("datetime").datetime(2026, 6, 29, 12, tzinfo=__import__("datetime").timezone.utc))
    assert fired["job"] == "job-2"
    assert fired["contexto"] == "reforco_valor"


@pytest.mark.asyncio
async def test_closed_window_with_pending_reopen_refreshes_context(monkeypatch):
    from app.follow_up import scheduler

    refreshed, cancelled, fired = {}, {}, {"called": False}
    monkeypatch.setattr(scheduler, "get_due_followups", lambda now, limit=10: [{
        "id": "job-3", "conversation_id": "conv-1", "lead_id": "lead-1", "sequence": 3,
        "job_type": None, "metadata": {"objetivo": "prova_social", "objective_prompt": "p"},
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Ana",
                  "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
        "channels": {"id": "chan-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": "2026-06-01T00:00:00+00:00"},
    }])
    monkeypatch.setattr(scheduler, "_pending_reopen_job", lambda cid: {"id": "job-2"})
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda jid, motivo, contexto: refreshed.update({"id": jid, "contexto": contexto}))
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancelled.update({"id": jid, "reason": reason}))
    async def _fake_fire(*a, **k):
        fired["called"] = True; return True
    monkeypatch.setattr(scheduler, "fire_reopen_template", _fake_fire)

    await scheduler.process_due_followups(now=__import__("datetime").datetime(2026, 6, 29, 12, tzinfo=__import__("datetime").timezone.utc))
    assert refreshed == {"id": "job-2", "contexto": "prova_social"}
    assert cancelled == {"id": "job-3", "reason": "reopen_context_refreshed"}
    assert fired["called"] is False  # no 2nd template
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py -k "closed_window" -q`
Expected: FAIL — `_pending_reopen_job` missing / closed window currently cancels with `window_expired`.

- [ ] **Step 3: Add `_pending_reopen_job`, extend `_generate_followup_message`, rewrite the closed-window branch**

Add helper near `_store_reopen_context`:

```python
def _pending_reopen_job(conversation_id: str) -> dict | None:
    """Job awaiting_reopen vivo desta conversa (R1), ou None. Fail-open: None em erro."""
    try:
        res = (
            get_supabase().table("follow_up_jobs")
            .select("id, metadata")
            .eq("conversation_id", conversation_id)
            .eq("status", "awaiting_reopen")
            .order("fire_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("[FOLLOWUP] falha ao buscar awaiting_reopen conv=%s: %s", conversation_id, exc)
        return None
```

Extend `_generate_followup_message` signature to accept `objective_prompt: str | None = None` and inject it. Locate the system-prompt construction inside `_generate_followup_message` and append the objective when present. Minimal change — add the parameter and, right before the prompt is sent, prepend the objective directive:

```python
async def _generate_followup_message(
    history, sequence, lead_id=None, stage=None, objective_prompt: str | None = None
):
    ...
    # (existing system prompt construction assembles `system_prompt`)
    if objective_prompt:
        system_prompt = f"{system_prompt}\n\nOBJETIVO DESTE TOQUE (Next Best Action): {objective_prompt}"
    ...
```

In the generic branch of `process_due_followups`, replace the closed-window cancel block (the `last_msg + timedelta(hours=24) <= now` → `_cancel_job(window_expired)` block, lines ~519-525) with:

```python
        last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
        window_closed = last_msg + timedelta(hours=24) <= now
        if window_closed:
            objetivo = (job.get("metadata") or {}).get("objetivo", "")
            existing = _pending_reopen_job(conversation_id)
            if existing:
                # R1: não empilha template — escala o contexto do reopen vivo e encerra este toque.
                _store_reopen_context(existing["id"], objetivo, objetivo)
                _cancel_job(job["id"], "reopen_context_refreshed")
                logger.info(
                    "[FOLLOWUP] janela fechada + reopen vivo → contexto atualizado p/ '%s' "
                    "seq=%s conv=%s", objetivo, sequence, conversation_id,
                )
            else:
                await fire_reopen_template(
                    job, lead, channel, conversation_id, motivo=objetivo, contexto=objetivo
                )
            continue
```

Then, where the open-window path calls `_generate_followup_message(history, sequence, lead_id=..., stage=...)`, pass the objective:

```python
            objective_prompt = (job.get("metadata") or {}).get("objective_prompt")
            message, finish_reason = await _generate_followup_message(
                history, sequence, lead_id=job["lead_id"], stage=conversation.get("stage"),
                objective_prompt=objective_prompt,
            )
```

- [ ] **Step 4: Run the cadence tests + full suite**

Run: `cd backend && python -m pytest tests/test_multitouch_cadence.py -q`
Expected: PASS (all)

Run: `cd backend && python -m pytest -q`
Expected: PASS (no regressions; pre-existing skips ok)

- [ ] **Step 5: Commit**

```bash
git add backend/app/follow_up/scheduler.py backend/tests/test_multitouch_cadence.py
git commit -m "feat(followup): multi-touch generic branch (objective free-text; closed-window template/refresh)"
```

---

## Notes for the implementer

- `_clamp_to_business_window` and `is_within_business_window` already exist in `service.py` — import, don't reimplement.
- The reopen TTL + resumption (`consume_reopen_context`) is already wired in `processor.py:782` for ALL `awaiting_reopen` jobs regardless of `job_type` — do NOT add resumption code; it works for these touches automatically.
- Inbound already cancels pending follow-ups (`meta_router.py`) — do NOT add cancel-on-reply logic.
- Keep all existing open-window guardrails (deferral marker, `finish_reason=="length"`, meta-comment, `_normalize_literal_newlines`) intact — only the closed-window branch and the generator's objective injection change.
- `dispatch_metadata`, `MetaCloudClient`, `extract_wamid`, `resolve_send_target`, `save_message`, `_cancel_job`, `_mark_awaiting_reopen`, `_REOPEN_TEMPLATE_NAME` are already imported/defined in `scheduler.py`.
