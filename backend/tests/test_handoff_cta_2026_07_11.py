"""Auditoria inbound de abandono (2026-07-11) — Cat. 2 e Cat. 3.

Cat. 2 (handoff responde antes): o lead faz a pergunta mais quente da conversa
(preço/lote mínimo/prazo) e recebe o cartão do João no lugar da resposta. A correção
é de LINGUAGEM (descrição da tool + prompts) + telemetria log-only [HANDOFF SEM RESPOSTA].

Cat. 3 (CTA obrigatório pós-preço): o turno entrega preço e termina SEM pergunta de
fechamento (caso Sandro). Correção de LINGUAGEM (regra no base.py + checklist) +
telemetria log-only [PRECO SEM CTA] via função pura price_without_cta.

Diretriz: NENHUM bloqueio/mutação de resposta ou handoff — telemetria é warning puro,
fail-open. Estes testes provam a detecção pura e que os warnings do orchestrator NÃO
alteram a resposta nem o handoff.
"""
import logging

import pytest
from unittest.mock import AsyncMock, patch

from app.agent.adherence import price_without_cta, handoff_without_answer
from tests.gemini_fakes import fake_text, fake_tool_call


# ===========================================================================
# 1. price_without_cta — função pura (spec 2c)
# ===========================================================================

def test_price_without_cta_price_no_question_is_true():
    assert price_without_cta("o 250g sai R$26,70 a unidade") is True


def test_price_without_cta_price_with_closing_question_is_false():
    assert price_without_cta("o 250g sai R$26,70 a unidade\n\nfaz sentido começar com 100 unidades?") is False


def test_price_without_cta_no_price_is_false():
    assert price_without_cta("me conta o que você precisa?") is False
    assert price_without_cta("opa, me embolei aqui, deixa eu ver isso direitinho") is False


def test_price_without_cta_multi_bubble_question_only_in_last_is_false():
    # Preço na 1ª bolha, pergunta na última → NÃO dispara (o check é sobre o turno todo).
    text = "o 250g sai R$26,70 a unidade\n\no lote mínimo é de 100 unidades\n\nquer que eu já simule o pedido?"
    assert price_without_cta(text) is False


def test_price_without_cta_thousand_separator_does_not_confuse():
    # R$1.000 (ponto = separador de milhar) segue sendo preço; com CTA no fim → False.
    assert price_without_cta("o fardo fechado fica R$1.000\n\nquer que eu simule?") is False
    # Sem CTA → True (o milhar não atrapalha a detecção de preço).
    assert price_without_cta("o fardo fechado fica R$1.000 a caixa") is True


def test_price_without_cta_empty_is_false():
    assert price_without_cta("") is False
    assert price_without_cta(None) is False  # type: ignore[arg-type]


def test_price_without_cta_price_with_space_is_detected():
    assert price_without_cta("sai por R$ 23,90 a unidade") is True


# ===========================================================================
# 2. handoff_without_answer — função pura (spec 1d)
# ===========================================================================

def test_handoff_without_answer_question_and_no_number_is_true():
    assert handoff_without_answer("qual o pedido mínimo?", "o João Bras te ajuda com isso, é só chamar ele") is True


def test_handoff_without_answer_farewell_with_price_is_false():
    assert handoff_without_answer(
        "qual o preço?",
        "o 250g fica R$25,70 com lote mínimo de 100 unidades, e pra detalhar tudo o João te chama",
    ) is False


def test_handoff_without_answer_farewell_with_digit_is_false():
    assert handoff_without_answer("qual o lote mínimo?", "o lote mínimo é de 100 unidades, o João fecha contigo") is False


def test_handoff_without_answer_lead_without_question_is_false():
    assert handoff_without_answer("beleza, obrigado", "o João Bras assume daqui, é só chamar ele") is False


def test_handoff_without_answer_farewell_none_with_question_is_true():
    assert handoff_without_answer("qual o prazo de entrega?", None) is True


def test_handoff_without_answer_empty_lead_is_false():
    assert handoff_without_answer("", "qualquer coisa chama o João") is False
    assert handoff_without_answer(None, "qualquer coisa chama o João") is False  # type: ignore[arg-type]


# ===========================================================================
# 3. Orchestrator — telemetria log-only, prova de não-mutação (spec 1d / 2c)
# ===========================================================================

def _conversation(stage: str = "private_label") -> dict:
    return {
        "id": "conv-cta-001",
        "stage": stage,
        "leads": {
            "id": "lead-cta-001",
            "name": "Fulano",
            "phone": "5511900000099",
            "ai_enabled": True,
        },
    }


def _history(content: str) -> list:
    return [
        {
            "role": "user",
            "content": content,
            "stage": "private_label",
            "created_at": "2026-07-11T12:00:00Z",
            "wamid": "wamid-cta-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


@pytest.mark.asyncio
async def test_preco_sem_cta_logs_warning_and_does_not_mutate_response(caplog):
    from app.agent.orchestrator import run_agent

    price_text = "o 250g sai R$26,70 a unidade"

    async def fake_generate(**kwargs):
        return fake_text(price_text)

    with patch("app.agent.orchestrator.get_history", return_value=_history("quanto custa o 250g?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cta-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=fake_generate)):
        with caplog.at_level(logging.WARNING):
            result = await run_agent(_conversation(), "quanto custa o 250g?")

    assert "[PRECO SEM CTA]" in caplog.text
    # A resposta NÃO é mutada pela telemetria.
    assert result == price_text


@pytest.mark.asyncio
async def test_preco_com_cta_does_not_log_warning(caplog):
    from app.agent.orchestrator import run_agent

    price_text = "o 250g sai R$26,70 a unidade\n\nfaz sentido começar com 100 unidades?"

    async def fake_generate(**kwargs):
        return fake_text(price_text)

    with patch("app.agent.orchestrator.get_history", return_value=_history("quanto custa o 250g?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cta-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=fake_generate)):
        with caplog.at_level(logging.WARNING):
            result = await run_agent(_conversation(), "quanto custa o 250g?")

    assert "[PRECO SEM CTA]" not in caplog.text
    assert result == price_text


@pytest.mark.asyncio
async def test_handoff_farewell_with_price_does_not_trigger_preco_sem_cta(caplog):
    """Isenção: turno encerrado via encaminhar_humano não dispara [PRECO SEM CTA]
    (a despedida é enviada dentro do execute_tool; run_agent retorna None)."""
    from app.agent.orchestrator import run_agent

    async def fake_generate(**kwargs):
        return fake_tool_call(
            "encaminhar_humano",
            {"mensagem_despedida": "o 250g fica R$26,70, o João Bras fecha contigo", "motivo": "qualificado"},
        )

    with patch("app.agent.orchestrator.get_history", return_value=_history("qual o preço?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cta-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="handoff enviado"), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=fake_generate)):
        with caplog.at_level(logging.WARNING):
            result = await run_agent(_conversation(), "qual o preço?")

    assert "[PRECO SEM CTA]" not in caplog.text
    assert result is None  # handoff sentinel intacto


@pytest.mark.asyncio
async def test_handoff_sem_resposta_logs_warning_and_keeps_handoff(caplog):
    from app.agent.orchestrator import run_agent

    async def fake_generate(**kwargs):
        return fake_tool_call(
            "encaminhar_humano",
            {"mensagem_despedida": "o João Bras te ajuda com isso, é só chamar ele", "motivo": "qualificado"},
        )

    with patch("app.agent.orchestrator.get_history", return_value=_history("qual o pedido mínimo?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cta-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="handoff enviado") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=fake_generate)):
        with caplog.at_level(logging.WARNING):
            result = await run_agent(_conversation(), "qual o pedido mínimo?")

    assert "[HANDOFF SEM RESPOSTA]" in caplog.text
    # Handoff INTACTO: execute_tool chamado, run_agent retorna None (sentinel).
    assert result is None
    assert mock_exec.called
    assert mock_exec.call_args.args[0] == "encaminhar_humano"


@pytest.mark.asyncio
async def test_handoff_com_resposta_numerica_nao_loga(caplog):
    from app.agent.orchestrator import run_agent

    async def fake_generate(**kwargs):
        return fake_tool_call(
            "encaminhar_humano",
            {"mensagem_despedida": "o lote mínimo é de 100 unidades, o João Bras fecha contigo", "motivo": "qualificado"},
        )

    with patch("app.agent.orchestrator.get_history", return_value=_history("qual o pedido mínimo?")), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cta-001", "phone": "5511900000099", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool", new_callable=AsyncMock, return_value="handoff enviado"), \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=fake_generate)):
        with caplog.at_level(logging.WARNING):
            result = await run_agent(_conversation(), "qual o pedido mínimo?")

    assert "[HANDOFF SEM RESPOSTA]" not in caplog.text
    assert result is None


# ===========================================================================
# 4. Guardas de linguagem — as frases novas não podem ser removidas em silêncio
# ===========================================================================

def _encaminhar_humano_declaration() -> dict:
    from app.agent.tools import TOOL_DECLARATIONS
    return next(d for d in TOOL_DECLARATIONS if d["name"] == "encaminhar_humano")


def test_tool_description_manda_responder_pergunta_antes_do_transbordo():
    desc = _encaminhar_humano_declaration()["description"]
    low = desc.lower()
    assert "pergunta" in low
    # A despedida responde a pergunta ANTES do transbordo.
    assert "responder" in low or "responda" in low or "resposta" in low


def test_mensagem_despedida_param_orienta_responder_preco_primeiro():
    param = _encaminhar_humano_declaration()["parameters"]["properties"]["mensagem_despedida"]["description"]
    assert "PRIMEIRO" in param or "primeiro" in param


def test_inbound_prompts_dizem_que_a_pergunta_e_respondida_na_despedida():
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    for prompt in (PRIVATE_LABEL_PROMPT, ATACADO_PROMPT):
        assert "cartao no lugar da resposta" in prompt


def test_base_prompt_tem_regra_do_preco_nunca_solto():
    from datetime import datetime
    from app.agent.prompts.base import build_base_prompt
    text = build_base_prompt("Fulano", None, datetime(2026, 7, 11, 10, 0, 0))
    assert "PRECO NUNCA SOLTO" in text
    assert "pergunta de fechamento" in text
