import json

from scripts.rehearsal import logger as rehearsal_logger
from scripts.rehearsal.archetypes import R1


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

    assert archetype_dir.name == "R1-representante-portfolio"
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


def test_write_run_summary(tmp_path):
    run_dir = tmp_path / "run1"
    run_dir.mkdir()

    verifications = [
        {"archetype_id": "A1", "archetype_slug": "cafeteria-atacado", "status": "passed",
         "turns_count": 10, "terminated_by": "encaminhar_humano",
         "soft_check": {"bot_score_1_10": 7, "veredito_curto": "bom"}},
        {"archetype_id": "A2", "archetype_slug": "private-label", "status": "failed",
         "turns_count": 5, "terminated_by": "max_turns",
         "soft_check": {"bot_score_1_10": 4, "veredito_curto": "travou"}},
    ]

    rehearsal_logger.write_run_summary(run_dir, verifications, run_meta={"started_at": "2026-04-20T10:00:00Z"})

    summary = (run_dir / "summary.md").read_text()
    assert "A1" in summary
    assert "A2" in summary
    assert "passed" in summary
    assert "failed" in summary

    run_json = json.loads((run_dir / "run.json").read_text())
    assert run_json["started_at"] == "2026-04-20T10:00:00Z"
    assert len(run_json["verifications"]) == 2


def test_run_summary_shows_forbid_violations(tmp_path):
    from scripts.rehearsal import logger as rlogger

    run_dir = tmp_path / "run"
    run_dir.mkdir()

    verifications = [
        {
            "archetype_id": "R1",
            "archetype_slug": "representante-portfolio",
            "status": "failed",
            "hard_checks": [{"name": "min_5_turns", "passed": True, "reason": "ok"}],
            "forbids": [
                {"name": "forbid_pix", "passed": True, "reason": "PIX: sem violação"},
                {"name": "forbid_papel", "passed": False, "reason": "[VIOLATION:PAPEL] ..."},
            ],
            "soft_check": {"bot_score_1_10": 4, "veredito_curto": "ruim"},
            "turns_count": 10,
            "terminated_by": "encaminhar_humano",
            "stages_visited": ["atacado"],
        }
    ]

    rlogger.write_run_summary(run_dir, verifications, {"started_at": "x", "finished_at": "y"})

    summary_text = (run_dir / "summary.md").read_text()

    assert "PAPEL" in summary_text
    assert "Violações" in summary_text or "Violacoes" in summary_text
