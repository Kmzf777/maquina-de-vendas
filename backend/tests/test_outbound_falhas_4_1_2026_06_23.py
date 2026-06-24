"""Regressao das falhas #4 e #1 da auditoria do lead 5519997774170 (2026-06-23).

#4 (atacado): sinal de compra ("tenho fornecedor mas procuro outro") NAO pode ser
   tratado como objeção/confronto — deve ancorar e avancar pro produto.
#1 (secretaria): o pivô pos-"Sim" deve construir PONTE DE VALOR antes da pergunta,
   sem saltar do "cadastro confirmado" direto pra qualificacao (Regra de Ouro 0).
"""


# --- Falha #4: sinal de compra != objeção ---------------------------------

def test_atacado_distingue_sinal_de_compra_de_objecao():
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    assert "SINAL DE COMPRA" in ATACADO_PROMPT
    low = ATACADO_PROMPT.lower()
    # O lead que busca outro fornecedor e tratado como sinal de compra, nao objeção
    assert "procuro outro" in low or "busco outros" in low or "to aberto a trocar" in low
    # Instrucao explicita de NAO confrontar quem ja quer comprar
    assert "nao confronte" in low or "não confronte" in low


def test_atacado_etapa_1_1_so_para_lead_satisfeito():
    """A ETAPA 1.1 (rebatidas) so vale pra lead acomodado/satisfeito, nunca pro que quer trocar."""
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    # O gatilho da 1.1 passou a exigir lead SATISFEITO
    assert "SATISFEITO com o fornecedor" in ATACADO_PROMPT, (
        "ETAPA 1.1 deve disparar apenas para lead satisfeito"
    )


# --- Falha #1: ponte de valor no pivô pos-"Sim" ---------------------------

def test_secretaria_pivo_constroi_ponte_de_valor():
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    assert "PONTE DE VALOR" in SECRETARIA_PROMPT
    # A Regra de Ouro 0 continua presente (consistencia com test_audit_fixes)
    assert "AQUECER ANTES DE QUALIFICAR" in SECRETARIA_PROMPT


def test_secretaria_confirmou_nao_salta_direto_pra_qualificacao():
    """O exemplo abrupto antigo (confirma + qualifica na bolha seguinte, sem ponte) saiu."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT
    # O salto direto da auditoria foi removido
    assert "aproveitando, voce ja toma cafe especial no dia a dia" not in SECRETARIA_PROMPT
    # O exemplo do pivô agora situa a Cafe Canastra antes da pergunta
    assert "torrefacao de cafe especial da Serra da Canastra" in SECRETARIA_PROMPT
