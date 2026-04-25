import json

from scripts.rehearsal import logger as rehearsal_logger
from scripts.rehearsal.archetypes import T1 as R1


def test_write_artifacts_creates_expected_files(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()

    messages = [
        {"role": "user", "content": "oi", "created_at": "2026-04-20T10:00:00Z"},
        {"role": "assistant", "content": "oi, em que posso ajudar?", "created_at": "2026-04-20T10:00:02Z"},
    ]
    events = [
        {"content": "stage alterado para atacado", "created_at": "2026-04-20T10:00:03Z"},
    ]
    verification = {"status": "passed", "archetype_id": "R1"}

    archetype_dir = rehearsal_logger.write_archetype_artifacts(
        run_dir=run_dir,
        archetype=R1,
        messages=messages,
        events=events,
        verification=verification,
    )

    assert archetype_dir.name == "T1-b2b-revenda"
    assert (archetype_dir / "transcript.md").exists()
    assert (archetype_dir / "events.jsonl").exists()
    assert (archetype_dir / "messages.json").exists()
    assert (archetype_dir / "verification.json").exists()
    assert (archetype_dir / "archetype-prompt.md").exists()

    transcript = (archetype_dir / "transcript.md").read_text()
    assert "oi" in transcript
    assert "em que posso ajudar" in transcript

    events_content = (archetype_dir / "events.jsonl").read_text().splitlines()
    assert len(events_content) == 1
    assert json.loads(events_content[0])["content"] == "stage alterado para atacado"

    v = json.loads((archetype_dir / "verification.json").read_text())
    assert v["status"] == "passed"
