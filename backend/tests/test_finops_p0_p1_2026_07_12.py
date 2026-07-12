"""FinOps P0+P1 (12/07/2026) — guardas estruturais do pacote de corte de custo LLM.

Contexto (diagnostico_completo_custos_llm.md): hit-rate de implicit caching medido em
9,9% porque o bloco volátil <context> ficava no MEIO do system prompt (stage+catálogo+
FINAL_INSTRUCTION vinham DEPOIS dele, fora do prefixo cacheável cross-lead); thoughts
eram 78% do output das respostas e ~10% das iniciais voltavam vazias (thinking-burn).

Este arquivo trava os três invariantes do fix:
  1. ORDEM CACHE-FIRST: o prefixo do system prompt é byte-idêntico entre leads
     diferentes até o FIM do catálogo; <context> é o único bloco volátil e fica no fim,
     seguido apenas de <final_instruction> (que permanece a última tag).
  2. build_base_prompt continua byte-compatível (estático + contexto) para os
     chamadores legados.
  3. FALLBACK CONDICIONAL DE THINKING: 1ª chamada sem thinking (default novo); se ela
     vier VAZIA, o retry silencioso roda COM thinking (política oposta). Com
     LLM_INITIAL_THINKING=on (rollback), inicial pensa e retry roda thinking-off.
"""
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.gemini_fakes import fake_text

CATALOG = "## Cafe Classico 250g\nPreco: R$28,70"


def _build(lead: dict, lead_context: dict | None = None) -> str:
    from app.agent.orchestrator import build_system_prompt
    return build_system_prompt(
        lead, "atacado", prompt_key="valeria_inbound",
        lead_context=lead_context, catalog_text=CATALOG,
    )


# ---------------------------------------------------------------------------
# 1. Ordem cache-first do system prompt
# ---------------------------------------------------------------------------

def test_prefixo_cross_lead_cobre_ate_o_fim_do_catalogo():
    """Leads diferentes (nome/empresa/dossiê distintos) compartilham prefixo byte-idêntico
    que inclui base + stage + catálogo inteiro — é ele que o implicit caching desconta."""
    p1 = _build({"name": "Maria", "company": "Cafeteria X"},
                {"name": "Maria", "rolling_summary": "dossie da maria"})
    p2 = _build({"name": None, "company": None})
    common_len = 0
    for a, b in zip(p1, p2):
        if a != b:
            break
        common_len += 1
    common = p1[:common_len]
    assert "</catalogo_de_produtos>" in common, (
        "prefixo comum cross-lead parou antes do fim do catálogo — conteúdo volátil "
        "vazou para antes do <context> e quebrou o cache"
    )


# Âncora do INÍCIO REAL do bloco volátil — os prompts de stage citam "<context>"
# textualmente ("use a saudacao do <context>"), então a tag sozinha não é única.
_CONTEXT_BLOCK_ANCHOR = "<context>\n# CONTEXTO TEMPORAL"


def test_context_e_o_ultimo_bloco_antes_da_final_instruction():
    prompt = _build({"name": "Maria", "company": "Cafeteria X"})
    i_catalogo = prompt.index("</catalogo_de_produtos>")
    i_context = prompt.index(_CONTEXT_BLOCK_ANCHOR)
    i_final = prompt.index("<final_instruction>")
    assert i_catalogo < i_context < i_final
    assert prompt.rstrip().endswith("</final_instruction>")


def test_nada_volatil_antes_do_context():
    """Nome do lead e data só podem aparecer DENTRO/DEPOIS do <context>."""
    prompt = _build({"name": "Maria", "company": "Cafeteria Copacabana"})
    i_context = prompt.index(_CONTEXT_BLOCK_ANCHOR)
    assert prompt.index("Maria") > i_context
    assert prompt.index("Cafeteria Copacabana") > i_context
    assert prompt.index("Hoje e:") > i_context


# ---------------------------------------------------------------------------
# 2. Compat do formato legado
# ---------------------------------------------------------------------------

def test_build_base_prompt_continua_estatico_mais_contexto():
    from app.agent.prompts.base import BASE_STATIC, build_base_prompt, build_context_block
    now = datetime(2026, 7, 12, 15, 30)
    esperado = BASE_STATIC + "\n\n" + build_context_block(
        lead_name="Maria", lead_company=None, now=now, lead_context=None)
    assert build_base_prompt("Maria", None, now) == esperado
    assert BASE_STATIC.startswith("<role>")
    assert BASE_STATIC.rstrip().endswith("</examples>")


# ---------------------------------------------------------------------------
# 3. Fallback condicional de thinking no retry-on-empty
# ---------------------------------------------------------------------------

def _hermetic_patches(call_responses):
    return [
        patch("app.agent.orchestrator.get_history", return_value=[
            {"role": "user", "content": "quero saber do cafe", "stage": "secretaria",
             "created_at": "2026-07-12T13:30:00Z", "wamid": "w", "quoted_wamid": None,
             "message_type": "text", "metadata": None}
        ]),
        patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-f01", "phone": "5565996414453", "ai_enabled": True}),
        patch("app.agent.orchestrator.update_lead", new=MagicMock()),
        patch("app.agent.orchestrator._schedule_memory_refresh", new=MagicMock()),
        patch("app.agent.orchestrator.execute_tool", new=AsyncMock(return_value="ok")),
        patch("app.agent.orchestrator.track_token_usage"),
        patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=call_responses)),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "env_value, initial_off, retry_off",
    [
        (None, True, False),   # default novo: inicial sem thinking → retry PENSA (fallback)
        ("on", False, True),   # rollback: inicial pensa → retry thinking-off (histórico)
    ],
)
async def test_retry_on_empty_usa_politica_oposta_de_thinking(
    monkeypatch, env_value, initial_off, retry_off
):
    from app.agent.orchestrator import run_agent

    if env_value is None:
        monkeypatch.delenv("LLM_INITIAL_THINKING", raising=False)
    else:
        monkeypatch.setenv("LLM_INITIAL_THINKING", env_value)

    conversation = {
        "id": "conv-finops-001",
        "stage": "secretaria",
        "leads": {"id": "lead-f01", "name": "Renato", "phone": "5565996414453",
                  "ai_enabled": True},
    }
    # inicial vazia (0 tokens visíveis) → retry silencioso devolve o texto real
    call_responses = [fake_text(""), fake_text("opa, posso te explicar sim")]

    patches = _hermetic_patches(call_responses)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
            patches[6] as m_gen:
        await run_agent(conversation, "quero saber do cafe")

    assert m_gen.await_count == 2
    assert m_gen.await_args_list[0].kwargs["thinking_off"] is initial_off
    assert m_gen.await_args_list[1].kwargs["thinking_off"] is retry_off
