"""Smoke test: com um run_data contendo mensagens da bot que violam todas as
proibicoes universais, o verifier reprova e lista cada violacao."""
from unittest.mock import patch

from scripts.rehearsal import verifier
from scripts.rehearsal.archetypes import R1


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_fails_when_bot_violates_all_universal_forbids(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 0}
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao"},
        ],
        "messages": [
            {"role": "assistant", "content": "te mando a chave pix no final"},
            {"role": "assistant", "content": "o investimento inicial fica em torno de R$ 2.500"},
            {"role": "assistant", "content": "entrego em 7 dias uteis"},
            {"role": "assistant", "content": "posso fazer por R$19,90 pra voce"},
            {"role": "assistant", "content": "vou passar voce pro comercial"},
        ],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(R1, run_data, transcript="x")

    assert result["status"] == "failed"
    labels = {c["name"] for c in result["forbids"] if not c["passed"]}
    assert labels == {"forbid_pix", "forbid_preco_frete", "forbid_prazo", "forbid_desconto", "forbid_papel"}


@patch("scripts.rehearsal.verifier.judge_conversation")
def test_verify_passes_when_bot_behaves(mock_judge):
    mock_judge.return_value = {"bot_score_1_10": 8}
    run_data = {
        "events": [
            {"content": "stage alterado para atacado"},
            {"content": "[encaminhar_humano] Lead encaminhado para Joao Bras"},
        ],
        "messages": [
            {"role": "user", "content": "quanto sai o classico?"},
            {"role": "assistant", "content": "o classico 250g sai R$27,70"},
            {"role": "assistant", "content": "vou passar voce pro supervisor Joao Bras"},
        ],
        "turns_count": 6,
        "stages_visited": {"atacado"},
    }

    result = verifier.verify(R1, run_data, transcript="x")

    assert result["status"] == "passed"
    assert all(c["passed"] for c in result["forbids"])
