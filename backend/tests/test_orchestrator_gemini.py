"""Roteamento de modelo no orchestrator (migração Gemini 100% nativo, 09/07/2026).

Nota de conversão: os testes antigos de `_get_client`/`_get_gemini` (fachada OpenAI)
perderam o assunto — não existe mais cliente roteável; o orchestrator chama
`gemini_client.generate` diretamente. A intenção original ("todo modelo acaba num
Gemini; o model do profile chega na chamada") foi re-apontada para o contrato novo:
run_agent chama `generate` com kwargs["model"] correto (passthrough p/ gemini-*;
coerção p/ DEFAULT_MODEL nos demais).
"""
from unittest.mock import AsyncMock, patch
import pytest

from tests.gemini_fakes import fake_text


def test_is_gemini_model_verdadeiro_para_prefixo_gemini():
    from app.agent.orchestrator import _is_gemini_model
    assert _is_gemini_model("gemini-2.5-flash") is True
    assert _is_gemini_model("gemini-1.5-pro") is True
    assert _is_gemini_model("gpt-4.1-mini") is False
    assert _is_gemini_model("o4-mini") is False


def _conversation(conv_id: str = "conv-gemini-1") -> dict:
    return {
        "id": conv_id,
        "lead_id": "lead-1",
        "stage": "secretaria",
        "leads": {"id": "lead-1", "phone": "5511999990000"},
    }


def _base_patches(profile_model: str):
    """Patches comuns: lead/profile/history/tools/prompt + tracking neutralizado."""
    return [
        patch("app.agent.orchestrator.get_lead", return_value={"id": "lead-1", "phone": "5511999990000"}),
        patch("app.agent.orchestrator.get_agent_profile", return_value={
            "model": profile_model,
            "prompt_key": "valeria_inbound",
        }),
        patch("app.agent.orchestrator.get_history", return_value=[]),
        patch("app.agent.orchestrator.get_tools_for_stage", return_value=[]),
        patch("app.agent.orchestrator.build_system_prompt", return_value="system"),
        patch("app.agent.orchestrator.track_token_usage"),
    ]


@pytest.mark.asyncio
async def test_run_agent_passa_model_gemini_do_profile_para_generate():
    """Re-apontado de test_get_client_roteia_gemini_para_cliente_gemini: modelo gemini-*
    do profile chega intacto em generate(kwargs['model'])."""
    from app.agent.orchestrator import run_agent

    patches = _base_patches("gemini-2.5-flash")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text("Olá!"))) as m_gen:
        result = await run_agent(_conversation(), "oi", agent_profile_id="profile-1")

    assert m_gen.await_count == 1
    assert m_gen.call_args_list[0].kwargs["model"] == "gemini-2.5-flash"
    assert result == "Olá!"


@pytest.mark.asyncio
async def test_run_agent_roteia_qualquer_modelo_para_um_gemini():
    """Re-apontado de test_get_client_roteia_qualquer_modelo_para_gemini: qualquer modelo
    de profile acaba numa chamada generate com um modelo Gemini — passthrough p/ gemini-*,
    coerção p/ DEFAULT_MODEL nos demais."""
    from app.agent.orchestrator import run_agent, DEFAULT_MODEL

    expected = {
        "gpt-4.1-mini": DEFAULT_MODEL,
        "modelo-desconhecido": DEFAULT_MODEL,
        "gemini-2.5-flash": "gemini-2.5-flash",
    }
    for profile_model, expected_model in expected.items():
        patches = _base_patches(profile_model)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
             patch("app.agent.orchestrator.generate",
                   new=AsyncMock(return_value=fake_text("Olá!"))) as m_gen:
            await run_agent(_conversation(), "oi", agent_profile_id="profile-1")

        used_model = m_gen.call_args_list[0].kwargs["model"]
        assert used_model == expected_model, (
            f"profile model {profile_model!r} deveria virar {expected_model!r}, got {used_model!r}"
        )
        assert used_model.startswith("gemini-"), "toda chamada deve ir para um modelo Gemini"


@pytest.mark.asyncio
async def test_run_agent_usa_gemini_quando_profile_usa_gemini():
    conversation = _conversation("conv-gemini-1")

    patches = _base_patches("gemini-2.5-flash")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text("Olá!"))) as m_gen:
        from app.agent.orchestrator import run_agent
        result = await run_agent(conversation, "oi", agent_profile_id="profile-1")

    assert m_gen.call_args_list[-1].kwargs["model"] == "gemini-2.5-flash"
    assert result == "Olá!"


@pytest.mark.asyncio
async def test_run_agent_coage_modelo_nao_gemini_para_gemini_flash():
    conversation = _conversation("conv-gemini-2")

    patches = _base_patches("gpt-4.1")
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patch("app.agent.orchestrator.generate",
               new=AsyncMock(return_value=fake_text("Olá!"))) as m_gen:
        from app.agent.orchestrator import run_agent
        result = await run_agent(conversation, "oi", agent_profile_id="profile-1")

    assert m_gen.call_args_list[-1].kwargs["model"] == "gemini-2.5-flash"
    assert result == "Olá!"
