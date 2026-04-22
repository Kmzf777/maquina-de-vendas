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


def test_forbids_regex_returns_true_when_pattern_not_in_bot_messages():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "assistant", "content": "Ola, tudo bem?"},
            {"role": "user", "content": "quero pagar por pix"},  # user message ignorada
        ]
    }

    passed, reason = check(run_data)

    assert passed is True
    assert "PIX" in reason


def test_forbids_regex_returns_false_when_pattern_matches_bot_message():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "assistant", "content": "Pode pagar via pix tambem"},
        ]
    }

    passed, reason = check(run_data)

    assert passed is False
    assert "[VIOLATION:PIX]" in reason
    assert "menção PIX" in reason


def test_forbids_regex_ignores_user_messages_even_if_pattern_matches():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "user", "content": "voces aceitam pix?"},
            {"role": "assistant", "content": "Vou verificar com o supervisor"},
        ]
    }

    passed, reason = check(run_data)

    assert passed is True


def test_forbids_regex_is_case_insensitive():
    check = verifier.forbids_regex(r"\bpix\b", label="PIX", description="menção PIX")
    run_data = {
        "messages": [
            {"role": "assistant", "content": "Aceitamos PIX e cartao"},
        ]
    }

    passed, reason = check(run_data)

    assert passed is False
