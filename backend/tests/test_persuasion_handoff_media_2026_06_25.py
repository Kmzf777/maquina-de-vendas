"""Categoria A (persuasão/objeção) + B3 (cegueira de imagem) do dossiê outbound, 2026-06-25.

A1/A2 — objeção de concorrência: o prompt agora exige sondagem WIIFM antes de catálogo quando o
        lead já tem fornecedor, e turnaround ativo (não passivo) quando ele está comparando
        orçamentos / "falo depois". Sem prometer amostra grátis (isso é decisão do João).
A3   — limitador de handoff: o CTA de passar pro supervisor não pode virar spam enquanto o lead
        está no meio de uma tarefa (mandando a arte, tirando dúvida).
B3   — graceful degradation: mídia visual sem texto vira um marcador legível ([imagem]) para o
        agente reconhecer o envio em vez de ignorá-lo / dizer "chegou cortada".
"""
from datetime import datetime

import pytest


def _base_prompt() -> str:
    from app.agent.prompts.base import build_base_prompt
    return build_base_prompt(lead_name=None, lead_company=None, now=datetime(2026, 6, 25, 10, 0))


# ============================ A1/A2 — objeção de concorrência ============================

def test_competitor_objection_rule_present_with_wiifm():
    prompt = _base_prompt()
    assert "OBJECAO DE CONCORRENCIA" in prompt
    assert "WIIFM" in prompt
    # sonda a dor ANTES de mostrar produto/preço
    assert "ANTES DE MOSTRAR PRODUTO" in prompt
    assert "o que voce mais valoriza hoje no seu fornecedor" in prompt
    # exceção: sinal de compra explícito não recebe sondagem
    assert "SINAL DE COMPRA" in prompt


def test_budget_comparison_turnaround_is_active_not_passive():
    prompt = _base_prompt()
    assert "TURNAROUND ATIVO" in prompt
    assert "PROIBIDA de aceitar passivamente" in prompt
    # diferencia com valor real e mantém na disputa
    assert "torra sob demanda" in prompt


def test_does_not_promise_free_sample_itself():
    """Compliance comercial: a IA NUNCA promete amostra grátis — amostra é decisão do João."""
    prompt = _base_prompt()
    assert "PROIBIDO prometer amostra gratis" in prompt
    # caminho correto: quem quer provar/testar é encaminhado ao João
    assert "encaminhar_humano" in prompt


# ============================ A3 — limitador de handoff ============================

def test_handoff_limiter_rule_present():
    prompt = _base_prompt()
    assert "LIMITADOR DE HANDOFF" in prompt
    assert "UMA UNICA VEZ" in prompt
    # não atravessar o lead enquanto ele está numa tarefa (mandando a arte)
    assert "NO MEIO DE UMA TAREFA" in prompt


def test_handoff_limiter_reinforced_in_outbound_files():
    from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT as pl
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT as ata
    assert "LIMITADOR DE HANDOFF" in pl
    assert "LIMITADOR DE HANDOFF" in ata
    # turnaround de comparação de orçamento reforçado no private label
    assert "comparando orcamentos" in pl.lower() or "comparando orçamentos" in pl.lower()


# ============================ B3 — graceful degradation de mídia ============================

def test_media_section_acknowledges_instead_of_cortada():
    prompt = _base_prompt()
    # a instrução de reconhecer a mídia substituiu o velho "chegou cortada"
    assert "RECONHECA, NUNCA IGNORE" in prompt
    assert "[imagem]" in prompt
    assert "recebi aqui sua arte" in prompt
    # a frase que causava o bug não pode ser mais o caminho para mídia com intenção
    assert "NUNCA diga que a mensagem" in prompt


def test_apply_media_signal_injects_marker_for_visual_media():
    from app.buffer.processor import _apply_media_signal
    assert _apply_media_signal("", "image") == "[imagem]"
    assert _apply_media_signal("", "document") == "[documento]"
    assert _apply_media_signal("", "video") == "[vídeo]"
    assert _apply_media_signal("", "sticker") == "[figurinha]"


def test_apply_media_signal_preserves_existing_text_and_audio():
    from app.buffer.processor import _apply_media_signal
    # caption presente → não sobrescreve
    assert _apply_media_signal("olha essa arte", "image") == "olha essa arte"
    # áudio tem fluxo próprio → não é tratado aqui (tipo desconhecido devolve o texto original)
    assert _apply_media_signal("", "audio") == ""
    assert _apply_media_signal("", None) == ""


# ============================ Compliance (gemini-prompting-strategies) ============================

def test_new_rules_have_no_blacklisted_filler_words():
    """As 4 muletas banidas (entendo/bacana/show/perfeito) não podem entrar nos novos exemplos."""
    prompt = _base_prompt()
    # isola o trecho das novas regras (30..31 + seção de mídia) para não pegar ocorrências
    # legítimas como a própria black-list que LISTA as palavras proibidas.
    start = prompt.index("OBJECAO DE CONCORRENCIA")
    end = prompt.index("# CIRCUIT BREAKER")
    novas_regras = prompt[start:end]
    for banido in ("bacana", "perfeito", " show", "entendo"):
        assert banido not in novas_regras, f"palavra banida {banido!r} nas novas regras"
