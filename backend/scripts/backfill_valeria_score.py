"""Paginated ValerIA score backfill. Dry-run is the default."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent.gemini_client import generate, user_content
from app.config import settings
from app.db.supabase import get_supabase
from app.lead_score.repository import save_score_evidence
from app.leads.service import get_history

logger = logging.getLogger(__name__)
_PAGE_SIZE = 100
_FIELDS = {
    "segment": {"cafeteria", "emporio", "specialty_store", "wine_shop", "cheese_shop", "natural_products_store", "bulk_store", "artisan_store", "colonial_store", "rural_store", "supermarket", "hotel", "restaurant", "bakery", "other"},
    "supplier_reason": {"replace", "second_supplier", "expand_mix", "start_specialty_coffee", "research", "other"},
    "purchase_timing": {"within_15_days", "days_16_30", "months_1_3", "more_than_3_months", "no_timeline"},
    "purchase_intent": {"clear", "unclear"},
}
_PROMPT = """Extract only objective criteria explicitly stated by the lead. Return JSON:
{"updates": {criterion: normalized_value}, "evidence": {criterion: {"text": literal_quote}}}.
Allowed values: segment=cafeteria|emporio|specialty_store|wine_shop|cheese_shop|natural_products_store|bulk_store|artisan_store|colonial_store|rural_store|supermarket|hotel|restaurant|bakery|other; monthly_volume_kg=non-negative number; supplier_reason=replace|second_supplier|expand_mix|start_specialty_coffee|research|other; purchase_timing=within_15_days|days_16_30|months_1_3|more_than_3_months|no_timeline; purchase_intent=clear|unclear.
Every non-null value needs a nonblank literal quote from the lead. Never infer. Ambiguous volume or timing stays absent. Agent messages may contextualize but never prove a criterion."""


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower().split())


def _valid_value(field: str, value) -> bool:
    if field == "monthly_volume_kg":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0
    return field in _FIELDS and value in _FIELDS[field]


def _validated_payload(payload: dict, history: list[dict]) -> dict:
    users = [row for row in history if row.get("role") == "user" and row.get("content")]
    updates, evidence = {}, {}
    for field, value in (payload.get("updates") or {}).items():
        if not _valid_value(field, value):
            continue
        supplied = (payload.get("evidence") or {}).get(field)
        text = supplied.get("text") if isinstance(supplied, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue
        normalized_text = _normalized(text)
        if not normalized_text:
            continue
        source = next((row for row in users if normalized_text in _normalized(row["content"])), None)
        if source is None:
            continue
        item = {"text": text.strip()}
        for key in ("id", "wamid", "created_at"):
            if source.get(key):
                item["message_id" if key == "id" else key] = source[key]
        item["message_ref"] = item.get("message_id") or item.get("wamid") or item.get("created_at")
        updates[field], evidence[field] = value, item
    return {"updates": updates, "evidence": evidence}


async def _extract(history: list[dict]) -> dict:
    users = [row for row in history if row.get("role") == "user" and (row.get("content") or "").strip()]
    if not users:
        return {"updates": {}, "evidence": {}}
    result = await generate(settings.summary_model, contents=[user_content("\n".join(f"[Lead] {row['content']}" for row in users))], system_instruction=_PROMPT, temperature=0, max_output_tokens=600, thinking_off=True, json_mode=True)
    try:
        return _validated_payload(json.loads(result.text or "{}"), users)
    except json.JSONDecodeError:
        logger.warning("backfill_valeria_score: invalid structured response")
        return {"updates": {}, "evidence": {}}


def extract_score_evidence(history: list[dict]) -> dict:
    return asyncio.run(_extract(history))


def _parse_cursor(after: str | None) -> tuple[str, str] | None:
    if not after:
        return None
    timestamp, separator, lead_id = after.partition("|")
    if not separator or not timestamp or not lead_id:
        raise ValueError("after must be '<last_interaction_at>|<lead_id>'")
    return timestamp, lead_id


def _read_checkpoint(path: Path) -> str | None:
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    _parse_cursor(value)
    return value


def _write_checkpoint(path: Path, cursor: str) -> None:
    """Atomically persist progress so an interrupt resumes after this lead."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(cursor, encoding="utf-8")
    os.replace(temporary, path)


def run_backfill(
    days: int = 60,
    dry_run: bool = True,
    limit: int | None = None,
    after: str | None = None,
    checkpoint: str | Path | None = None,
) -> dict:
    """Score leads in the recent-conversations view and return a keyset cursor."""
    checkpoint_path = Path(checkpoint) if checkpoint and not dry_run else None
    if after is None and checkpoint_path:
        after = _read_checkpoint(checkpoint_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cursor = _parse_cursor(after)
    db, scanned, updated, errors, next_cursor = get_supabase(), 0, 0, 0, after
    checkpoint_healthy = True
    while limit is None or scanned < limit:
        query = db.table("valeria_score_recent_leads").select("lead_id,last_interaction_at").gte("last_interaction_at", cutoff)
        if cursor:
            timestamp, lead_id = cursor
            query = query.or_(f"last_interaction_at.lt.{timestamp},and(last_interaction_at.eq.{timestamp},lead_id.lt.{lead_id})")
        rows = query.order("last_interaction_at", desc=True).order("lead_id", desc=True).limit(_PAGE_SIZE).execute().data or []
        if not rows:
            break
        for lead in rows:
            if limit is not None and scanned >= limit:
                break
            lead_id, timestamp = lead["lead_id"], lead["last_interaction_at"]
            scanned += 1
            try:
                extracted = extract_score_evidence(get_history(lead_id, limit=500, latest=True) or [])
                if extracted["updates"] and not dry_run:
                    save_score_evidence(lead_id, extracted["updates"], extracted["evidence"], source="backfill")
                    updated += 1
            except Exception as exc:
                errors += 1
                checkpoint_healthy = False
                logger.exception("backfill_valeria_score: lead %s failed: %s", lead_id, exc)
            next_cursor = f"{timestamp}|{lead_id}"
            if checkpoint_path and checkpoint_healthy:
                _write_checkpoint(checkpoint_path, next_cursor)
        if len(rows) < _PAGE_SIZE or (limit is not None and scanned >= limit):
            break
        cursor = _parse_cursor(next_cursor)
    return {"scanned": scanned, "updated": updated, "errors": errors, "dry_run": dry_run, "next_cursor": next_cursor}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--after", help="resume cursor from a prior run")
    parser.add_argument("--checkpoint", default=".valeria-score-backfill.cursor", help="checkpoint file (default: .valeria-score-backfill.cursor)")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    logger.info("%s", run_backfill(days=args.days, dry_run=not args.write, limit=args.limit, after=args.after, checkpoint=args.checkpoint))


if __name__ == "__main__":
    main()
