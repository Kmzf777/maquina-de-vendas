"""Persists artifacts from a rehearsal run to disk."""
import json
from pathlib import Path

from scripts.rehearsal.archetypes import Archetype


def _render_transcript(messages: list[dict], archetype: Archetype) -> str:
    lines = [f"# Transcript — {archetype.id} ({archetype.slug})", ""]
    for i, msg in enumerate(messages, 1):
        role = msg.get("role", "?")
        content = msg.get("content", "").strip()
        ts = msg.get("created_at", "")
        if role == "user":
            lines.append(f"### Turno {i} — Lead ({ts})")
        elif role == "assistant":
            lines.append(f"### Turno {i} — Valeria ({ts})")
        elif role == "system":
            lines.append(f"### [system] ({ts})")
        else:
            lines.append(f"### {role} ({ts})")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


def write_archetype_artifacts(
    run_dir: Path,
    archetype: Archetype,
    messages: list[dict],
    events: list[dict],
    verification: dict,
) -> Path:
    archetype_dir = run_dir / f"{archetype.id}-{archetype.slug}"
    archetype_dir.mkdir(parents=True, exist_ok=True)

    (archetype_dir / "transcript.md").write_text(_render_transcript(messages, archetype), encoding="utf-8")

    with (archetype_dir / "events.jsonl").open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")

    (archetype_dir / "messages.json").write_text(
        json.dumps(messages, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    (archetype_dir / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    (archetype_dir / "archetype-prompt.md").write_text(archetype.persona_prompt, encoding="utf-8")

    return archetype_dir