"""Verification for a single archetype run. Hard checks (deterministic) +
soft check (LLM-as-judge)."""
import re

from scripts.rehearsal.archetypes import Archetype
from scripts.rehearsal.gemini_actor import judge_conversation


def forbids_regex(pattern: str, label: str, description: str):
    """Factory de verificador anti-alucinação.

    Retorna (True, reason) se o padrão NAO aparecer em nenhuma mensagem com
    role='assistant'. Retorna (False, "[VIOLATION:LABEL] ...") ao primeiro match.
    """
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(run_data: dict) -> tuple[bool, str]:
        messages = run_data.get("messages", [])
        for m in messages:
            if m.get("role") != "assistant":
                continue
            content = m.get("content", "")
            match = compiled.search(content)
            if match:
                start = max(0, match.start() - 20)
                end = min(len(content), match.end() + 20)
                snippet = content[start:end].replace("\n", " ")
                return False, f"[VIOLATION:{label}] {description} — trecho: '{snippet}'"
        return True, f"{label}: sem violação"

    check.__name__ = f"forbid_{label.lower()}"
    return check


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
