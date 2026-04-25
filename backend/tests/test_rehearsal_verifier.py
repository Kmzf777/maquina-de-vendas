from unittest.mock import patch

from scripts.rehearsal import verifier
from scripts.rehearsal.archetypes import T1 as R1


def test_hard_checks_all_pass_returns_passed():
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao Bras"},
        ],
        "messages": [{"content": "10kg por mes"}],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.run_hard_checks(R1, run_data)

    assert result["status"] == "passed"
    assert all(c["passed"] for c in result["checks"])


def test_hard_checks_fail_if_any_missing():
    run_data = {
        "events": [],
        "messages": [],
        "turns_count": 1,
        "stages_visited": set(),
    }

    result = verifier.run_hard_checks(R1, run_data)

    assert result["status"] == "failed"
    assert any(not c["passed"] for c in result["checks"])


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_combines_hard_and_soft(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 7, "veredito_curto": "bom"}
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao Bras"},
        ],
        "messages": [{"role": "user", "content": "10kg por mes"}, {"role": "assistant", "content": "certo, aguarde o supervisor"}],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(R1, run_data, transcript="conversa aqui")

    assert result["status"] == "passed"
    assert result["soft_check"]["bot_score_1_10"] == 7
    assert result["archetype_id"] == "T1"
    assert result["turns_count"] == 6


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


def test_universal_forbids_contains_five_forbids():
    assert len(verifier.UNIVERSAL_FORBIDS) == 5
    labels = [f.__name__ for f in verifier.UNIVERSAL_FORBIDS]
    assert "forbid_pix" in labels
    assert "forbid_preco_frete" in labels
    assert "forbid_prazo" in labels
    assert "forbid_desconto" in labels
    assert "forbid_papel" in labels


def test_forbid_pix_catches_pix_mention():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_pix")
    run_data = {"messages": [{"role": "assistant", "content": "te mando a chave pix"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_pix_allows_non_pix_text():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_pix")
    run_data = {"messages": [{"role": "assistant", "content": "aceitamos cartao e boleto"}]}
    passed, _ = check(run_data)
    assert passed is True


def test_forbid_preco_frete_catches_total_with_freight():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_preco_frete")
    run_data = {"messages": [{
        "role": "assistant",
        "content": "O investimento inicial fica em torno de R$ 2.540"
    }]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_preco_frete_allows_individual_product_prices():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_preco_frete")
    run_data = {"messages": [{
        "role": "assistant",
        "content": "o classico 250g sai R$ 27,70"
    }]}
    passed, _ = check(run_data)
    assert passed is True


def test_forbid_prazo_catches_delivery_promise():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_prazo")
    run_data = {"messages": [{"role": "assistant", "content": "entrego em 7 dias uteis"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_desconto_catches_improvised_discount():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_desconto")
    run_data = {"messages": [{"role": "assistant", "content": "posso fazer por R$20 pra voce"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_papel_catches_commercial_contradiction():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_papel")
    run_data = {"messages": [{"role": "assistant", "content": "vou passar voce pro comercial"}]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_papel_allows_supervisor_handoff():
    check = next(f for f in verifier.UNIVERSAL_FORBIDS if f.__name__ == "forbid_papel")
    run_data = {"messages": [{"role": "assistant", "content": "vou passar voce pro supervisor Joao Bras"}]}
    passed, _ = check(run_data)
    assert passed is True


def test_forbid_ponto_venda_fisico_catches_rs_location():
    check = verifier.FORBID_PONTO_VENDA_FISICO
    run_data = {"messages": [{
        "role": "assistant",
        "content": "voce encontra em porto alegre, na loja parceira"
    }]}
    passed, _ = check(run_data)
    assert passed is False


def test_forbid_ponto_venda_fisico_allows_generic_mentions():
    check = verifier.FORBID_PONTO_VENDA_FISICO
    run_data = {"messages": [{
        "role": "assistant",
        "content": "nossa venda é direta, sem pontos de venda físicos no momento"
    }]}
    passed, _ = check(run_data)
    assert passed is True


def test_run_forbids_passes_when_no_violations():
    from scripts.rehearsal.archetypes import Archetype
    arch = Archetype(
        id="TEST",
        slug="test",
        persona_prompt="test",
        first_message="oi",
        hard_checks=[],
        forbids=[verifier.FORBID_PIX],
    )
    run_data = {"messages": [{"role": "assistant", "content": "ok"}]}

    result = verifier.run_forbids(arch, run_data)

    assert result["status"] == "passed"
    assert len(result["checks"]) == 1
    assert result["checks"][0]["passed"] is True


def test_run_forbids_fails_when_any_violation():
    from scripts.rehearsal.archetypes import Archetype
    arch = Archetype(
        id="TEST",
        slug="test",
        persona_prompt="test",
        first_message="oi",
        hard_checks=[],
        forbids=[verifier.FORBID_PIX, verifier.FORBID_PRAZO],
    )
    run_data = {"messages": [{"role": "assistant", "content": "te mando chave pix"}]}

    result = verifier.run_forbids(arch, run_data)

    assert result["status"] == "failed"
    assert any("[VIOLATION:PIX]" in c["reason"] for c in result["checks"])


def test_verify_overall_status_considers_forbids():
    from scripts.rehearsal.archetypes import Archetype
    from unittest.mock import patch

    arch = Archetype(
        id="TEST",
        slug="test",
        persona_prompt="test",
        first_message="oi",
        hard_checks=[],  # nenhum hard check
        forbids=[verifier.FORBID_PIX],
    )
    run_data = {
        "messages": [{"role": "assistant", "content": "chave pix aqui"}],
        "turns_count": 1,
        "stages_visited": set(),
    }

    with patch("scripts.rehearsal.verifier.judge_conversation") as mock_judge:
        mock_judge.return_value = {"bot_score_1_10": 5}
        result = verifier.verify(arch, run_data, transcript="x")

    assert result["status"] == "failed"  # falhou por forbid, não por hard_check
    assert "forbids" in result
    assert len(result["forbids"]) == 1
    assert result["forbids"][0]["passed"] is False


def test_reached_any_stage_returns_true_if_any_stage_visited():
    from scripts.rehearsal.archetypes import reached_any_stage
    check = reached_any_stage(["atacado", "private_label"])
    run_data = {"stages_visited": {"private_label"}}

    passed, reason = check(run_data)

    assert passed is True
    assert "private_label" in reason


def test_reached_any_stage_returns_false_if_none_visited():
    from scripts.rehearsal.archetypes import reached_any_stage
    check = reached_any_stage(["atacado", "private_label"])
    run_data = {"stages_visited": {"consumo"}}

    passed, reason = check(run_data)

    assert passed is False
    assert "nenhum" in reason.lower()


def test_reached_any_stage_check_name_lists_stages():
    from scripts.rehearsal.archetypes import reached_any_stage
    check = reached_any_stage(["atacado", "private_label"])

    assert check.__name__ == "reached_any_atacado_private_label"
