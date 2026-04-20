"""Verification for a single archetype run. Hard checks (deterministic) +
soft check (LLM-as-judge)."""
from scripts.rehearsal.archetypes import Archetype
from scripts.rehearsal.gemini_actor import judge_conversation


def run_hard_checks(archetype: Archetype, run_data: dict) -> dict:
    results = []
    for check in archetype.hard_checks:
        passed, reason = check(run_data)
        results.append({"name": check.__name__, "passed": passed, "reason": reason})
    status = "passed" if all(r["passed"] for r in results) else "failed"
    return {"status": status, "checks": results}


def _criteria_summary(archetype: Archetype) -> str:
    names = [c.__name__ for c in archetype.hard_checks]
    return f"Checks: {', '.join(names)}"


def verify(archetype: Archetype, run_data: dict, transcript: str) -> dict:
    hard = run_hard_checks(archetype, run_data)
    soft = judge_conversation(
        transcript=transcript,
        archetype_id=archetype.id,
        criteria_description=_criteria_summary(archetype),
    )
    return {
        "archetype_id": archetype.id,
        "archetype_slug": archetype.slug,
        "status": hard["status"],
        "hard_checks": hard["checks"],
        "soft_check": soft,
        "turns_count": run_data.get("turns_count", 0),
        "terminated_by": run_data.get("terminated_by", "unknown"),
        "stages_visited": sorted(run_data.get("stages_visited", set())),
    }
