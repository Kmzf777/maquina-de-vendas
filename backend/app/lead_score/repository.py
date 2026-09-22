"""Persistence boundary for lead-score snapshots."""

from typing import Any

from app.db.supabase import get_supabase

from .model import CRITERIA_FIELDS, calculate_score


_TABLE = "lead_qualification_scores"
_SOURCES = frozenset({"live", "backfill"})
_MAX_WRITE_ATTEMPTS = 3


class ScoreWriteConflictError(RuntimeError):
    """Another writer changed a score snapshot throughout all CAS attempts."""


def _is_unique_violation(error: Exception) -> bool:
    """Recognize Postgres's unique-violation signal without hiding other failures."""
    return getattr(error, "code", None) == "23505" or "23505" in str(error)


def _first_data(response: Any) -> dict | None:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) else None


def _get_existing(lead_id: str) -> dict | None:
    response = (
        get_supabase()
        .table(_TABLE)
        .select("*")
        .eq("lead_id", lead_id)
        .maybe_single()
        .execute()
    )
    return _first_data(response)


def _validate_evidence_shape(evidence: dict | None) -> dict:
    if evidence is None:
        return {}
    if not isinstance(evidence, dict):
        raise ValueError("Score evidence must be a dictionary")
    unknown = set(evidence) - set(CRITERIA_FIELDS)
    if unknown:
        raise ValueError(f"Unknown score evidence: {', '.join(sorted(unknown))}")
    for field, item in evidence.items():
        if not isinstance(item, dict):
            raise ValueError(f"Evidence for {field} must be a dictionary")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"Evidence for {field} requires a non-empty text")
        for reference_key in ("message_id", "message_ref"):
            if reference_key in item and (not isinstance(item[reference_key], str) or not item[reference_key].strip()):
                raise ValueError(f"Evidence {reference_key} for {field} must be a non-empty string")
    return evidence


def save_score_evidence(
    lead_id: str,
    updates: dict,
    evidence: dict | None = None,
    source: str = "live",
) -> dict:
    """Merge supported criteria, recalculate their snapshot, and save it.

    A retrospective backfill never replaces a snapshot already established by
    the live conversation. Omitting a field leaves its stored value untouched;
    passing ``None`` explicitly records that the criterion is unknown.
    """
    if source not in _SOURCES:
        raise ValueError(f"Invalid score source: {source!r}")
    unknown = set(updates) - set(CRITERIA_FIELDS)
    if unknown:
        raise ValueError(f"Unknown score criteria: {', '.join(sorted(unknown))}")
    evidence = _validate_evidence_shape(evidence)

    for _attempt in range(_MAX_WRITE_ATTEMPTS):
        existing = _get_existing(lead_id)
        criteria = {field: (existing or {}).get(field) for field in CRITERIA_FIELDS}
        accepted_updates = updates
        if existing and source == "backfill" and existing.get("source") == "live":
            accepted_updates = {
                field: value for field, value in updates.items()
                if existing.get(field) is None
            }
        elif existing and source == "backfill":
            accepted_updates = {
                field: value for field, value in updates.items()
                if existing.get(field) != value
            }
        for field, value in accepted_updates.items():
            if value is not None and field not in evidence:
                raise ValueError(f"Evidence for {field} is required for a known criterion")

        criteria.update(accepted_updates)
        score = calculate_score(criteria)
        merged_evidence = dict((existing or {}).get("evidence") or {})
        merged_evidence.update({field: value for field, value in evidence.items() if field in accepted_updates})
        snapshot = {
            "lead_id": lead_id,
            **criteria,
            "evidence": merged_evidence,
            **score,
            "source": existing.get("source") if existing and source == "backfill" and existing.get("source") == "live" else source,
            "rule_version": "2026-09-21",
        }
        if existing and all(existing.get(key) == snapshot.get(key) for key in snapshot if key != "rule_version"):
            return existing

        if existing:
            response = (
                get_supabase().table(_TABLE).update(snapshot)
                .eq("lead_id", lead_id).eq("updated_at", existing.get("updated_at")).execute()
            )
        else:
            try:
                response = get_supabase().table(_TABLE).insert(snapshot).execute()
            except Exception as error:
                if _is_unique_violation(error):
                    continue
                raise
        saved = _first_data(response)
        if saved:
            return {**snapshot, **saved}

    raise ScoreWriteConflictError(f"Could not save score snapshot for lead {lead_id}")
