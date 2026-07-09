"""Cartão de voz do follow-up (FinOps 08/07/2026).

O follow-up padrão pagava a PERSONA COMPLETA (~21K tokens: 32 regras de funil, circuit
breakers, regras de ferramenta numa chamada SEM ferramentas, tratamento de mídia,
checklist de 26 itens) para gerar 1-2 bolhas de reengajamento. O cartão de voz destila
APENAS o que muda o texto de um follow-up — identidade, voz/formato, blacklist, nome,
grounding — em ~2K tokens. Corte de ~90% do input desse fluxo.
"""
from app.follow_up.scheduler import _build_followup_system_prompt


def test_followup_system_prompt_e_leve():
    """A persona completa (~72K chars) não entra mais no follow-up — só o cartão de voz."""
    prompt = _build_followup_system_prompt(2, objetivo="reforco_valor", last_msg_age="hoje, há ~2 horas")
    assert len(prompt) < 10_000, (
        f"follow-up ainda carrega a persona completa ({len(prompt)} chars) — "
        "esperado cartão de voz (~4K chars)"
    )
    # e não é magro demais a ponto de ter perdido a identidade
    assert len(prompt) > 2_000


def test_voice_card_carrega_regras_criticas_de_voz():
    from app.agent.prompts.voice_card import VALERIA_VOICE_CARD
    low = VALERIA_VOICE_CARD.lower()
    # identidade
    assert "valeria" in low or "valéria" in low
    assert "cafe canastra" in low or "café canastra" in low
    # blacklist de automação (QA reprova conversas com essas palavras)
    for banida in ("entendo", "bacana", "show", "perfeito"):
        assert banida in low, f"blacklist sem a palavra banida '{banida}'"
    # formato WhatsApp humano
    assert "3 bolhas" in low
    assert "ponto final" in low
    assert "emoji" in low
    assert "minuscul" in low or "minúscul" in low
    assert "r$" in low
    # moderação de nome (o _FOLLOWUP_REENGAGE_INSTRUCTION referencia "a moderação de
    # nome da persona acima" — o cartão PRECISA carregar essa seção)
    assert "nome" in low and "consecutiv" in low
    # grounding: follow-up roda sem catálogo e sem tools — não pode inventar preço/produto
    assert "nunca invente" in low or "nao invente" in low or "não invente" in low


def test_followup_mantem_tom_por_objetivo_e_ancora_temporal():
    """Comportamentos pré-existentes preservados: tom segue o objetivo e a âncora entra."""
    normal = _build_followup_system_prompt(2, objetivo="reforco_valor", last_msg_age="ontem").lower()
    last = _build_followup_system_prompt(4, objetivo="ultima_chamada").lower()
    assert "ontem" in normal
    assert "última tentativa" not in normal and "ultima tentativa" not in normal
    assert "última tentativa" in last or "ultima tentativa" in last
