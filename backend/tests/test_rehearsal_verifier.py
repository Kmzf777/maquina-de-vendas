from unittest.mock import patch

from scripts.rehearsal import verifier
from scripts.rehearsal.archetypes import A1


def test_hard_checks_all_pass_returns_passed():
    run_data = {
        "events": [{"content": "stage alterado para atacado"}, {"content": "enviar_foto classico executada"}],
        "messages": [{"content": "quero 10kg"}],
        "turns_count": 12,
        "stages_visited": {"atacado"},
    }

    result = verifier.run_hard_checks(A1, run_data)

    assert result["status"] == "passed"
    assert all(c["passed"] for c in result["checks"])


def test_hard_checks_fail_if_any_missing():
    run_data = {
        "events": [],
        "messages": [],
        "turns_count": 1,
        "stages_visited": set(),
    }

    result = verifier.run_hard_checks(A1, run_data)

    assert result["status"] == "failed"
    assert any(not c["passed"] for c in result["checks"])


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_combines_hard_and_soft(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 7, "veredito_curto": "bom"}
    run_data = {
        "events": [{"content": "stage alterado para atacado"}, {"content": "enviar_foto classico executada"}],
        "messages": [{"content": "quero 10kg por favor"}],
        "turns_count": 10,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(A1, run_data, transcript="conversa aqui")

    assert result["status"] == "passed"
    assert result["soft_check"]["bot_score_1_10"] == 7
    assert result["archetype_id"] == "A1"
    assert result["turns_count"] == 10
