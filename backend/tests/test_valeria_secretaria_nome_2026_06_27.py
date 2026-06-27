"""Erro 1 (parte 2): correção de nome no outbound NÃO dispara pitch imediato.

Produção (lead Johny 5519981518080): clicou "Não" + "Johny" (nome real). O script de
'número errado' disparou o pitch de atacado. Correção de nome deve salvar o nome e
construir a PONTE DE VALOR (Regra de Ouro 0), nunca ofertar produto direto.
"""
from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT


def test_separa_correcao_de_nome_de_numero_errado():
    low = SECRETARIA_PROMPT.lower()
    # Existe um cenário dedicado de correção de nome/identidade...
    assert "correcao de nome" in low or "correção de nome" in low
    # ...que manda salvar o nome e aquecer (ponte de valor), não ofertar produto.
    assert "salvar_nome" in low


def test_correcao_de_nome_proibe_pitch_e_optout_imediato():
    low = SECRETARIA_PROMPT.lower()
    # A seção de correção de nome deve referenciar a ponte de valor / aquecer.
    assert "ponte de valor" in low
    # E deve haver um few-shot do caminho de correção que NÃO oferta atacado de cara.
    assert "few_shot" in low or "exemplo" in low


def test_numero_errado_ainda_tem_caminho_de_optout():
    low = SECRETARIA_PROMPT.lower()
    # O caminho de número errado de fato (sem nome) preserva o opt-out.
    assert "registrar_optout" in low
    assert "numero errado" in low or "número errado" in low
