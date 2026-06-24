"""Regra 16 (ENCAMINHAR_HUMANO) — enquadramento Tool-First — auditoria lead 5547984004911.

Handoff fantasma: a Regra 16 era "texto-first" (1. escreva a despedida; 2. chame a tool).
O gemini-2.5-flash executava o passo 1 (gerava a despedida como TEXTO de resposta, ecoando
o exemplo verbatim) e abortava o passo 2 (o tool_call). Resultado: a IA prometia o João
mas o cartão de contato nunca era enviado (encaminhar_humano nunca rodava).

Correção: Tool-First — a AÇÃO (chamar a tool) vem primeiro; a despedida é EXCLUSIVAMENTE
o argumento `mensagem_despedida`, nunca texto solto na resposta.
"""
from datetime import datetime


def _p():
    from app.agent.prompts.base import build_base_prompt
    return build_base_prompt(None, None, datetime(2026, 6, 24, 15, 0))


def _rule16_block(prompt: str) -> str:
    """Isola o corpo da Regra 16 (até o início da Regra 17)."""
    start = prompt.index("16. ENCAMINHAR_HUMANO")
    end = prompt.index("17.", start)
    return prompt[start:end]


def test_rule16_e_tool_first():
    bloco = _rule16_block(_p())
    low = bloco.lower()
    # Comando imperativo de chamar a ferramenta IMEDIATAMENTE
    assert "chame" in low and "imediatamente" in low
    assert "obrigatorio" in low or "obrigatório" in low
    # Proíbe escrever texto comum na resposta (a causa do handoff fantasma)
    assert "nao escreva texto" in low or "não escreva texto" in low
    # A despedida vai EXCLUSIVAMENTE no argumento mensagem_despedida
    assert "mensagem_despedida" in low
    assert "exclusivamente" in low


def test_rule16_nao_tem_passo_isolado_de_escrever_despedida():
    """O enquadramento texto-first (passo '1. Escreva uma despedida' separado do passo
    '2. Chame encaminhar_humano') foi REMOVIDO — era o que fazia o LLM parar no texto."""
    bloco = _rule16_block(_p())
    assert "1. Escreva uma despedida" not in bloco
    # Não pode haver um passo numerado '2. Chame encaminhar_humano' (estrutura de 2 etapas)
    assert "2. Chame encaminhar_humano" not in bloco


def test_rule16_preserva_cta_e_proibicao_passiva():
    """Regressão: o CTA imperativo de exemplo e a proibição de linguagem passiva
    (cobertos por test_base_handoff_cta_imperativo) seguem presentes."""
    low = _p().lower()
    assert "da um oi pra ele agora" in low
    assert "quando fizer sentido" in low and "proibido" in low
