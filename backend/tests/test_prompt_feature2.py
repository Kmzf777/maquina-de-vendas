"""TDD — Task 4: limpar tabela de frete estática do atacado outbound e instruir tools de pricing/percepção.

RED phase: estes testes devem falhar antes das edições em atacado.py e base.py.
GREEN phase: devem passar após as edições.
"""
from datetime import datetime, timezone, timedelta

TZ_BR = timezone(timedelta(hours=-3))


def _now():
    return datetime.now(TZ_BR)


# ===========================================================================
# atacado.py (outbound) — tabela estática de frete REMOVIDA
# ===========================================================================

def test_atacado_outbound_frete_table_removido():
    """A seção FRETE com a tabela estática deve ter sido removida do prompt de atacado outbound."""
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    low = ATACADO_PROMPT.lower()
    assert "frete gratis acima" not in low, (
        "Tabela de frete estática (frete gratis acima) ainda presente — deve ser removida"
    )
    assert "### sul e sudeste" not in low, (
        "Header da tabela '### Sul e Sudeste' ainda presente"
    )
    assert "### nordeste" not in low, (
        "Header da tabela '### Nordeste' ainda presente"
    )
    assert "### norte" not in low, (
        "Header da tabela '### Norte' ainda presente"
    )


def test_atacado_outbound_sem_valores_fixos_de_frete():
    """Valores de frete hardcoded não devem existir no prompt."""
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    # R$55 (Sul/Sudeste) e R$85 (Norte) eram os valores hardcoded da tabela
    assert "valor do frete: R$55" not in ATACADO_PROMPT, (
        "Valor de frete R$55 (Sul/Sudeste) ainda presente — tabela deve ser removida"
    )
    assert "valor do frete: R$85" not in ATACADO_PROMPT, (
        "Valor de frete R$85 (Norte) ainda presente — tabela deve ser removida"
    )


def test_atacado_outbound_sem_bloco_apresentar_precos():
    """O bloco COMO APRESENTAR PRECOS com instruções de composição manual deve ter sido removido."""
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    assert "COMO APRESENTAR PRECOS" not in ATACADO_PROMPT, (
        "Bloco 'COMO APRESENTAR PRECOS' ainda presente — deve ser removido/substituído"
    )


def test_atacado_outbound_usa_calcular_orcamento():
    """O prompt de atacado deve instruir a chamar calcular_orcamento para qualquer pergunta de preço/frete."""
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    assert "calcular_orcamento" in ATACADO_PROMPT, (
        "Regra de chamar calcular_orcamento não encontrada no prompt de atacado outbound"
    )


def test_atacado_outbound_proibe_calculo_de_cabeca():
    """O prompt deve proibir explicitamente o cálculo manual de preços."""
    from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
    low = ATACADO_PROMPT.lower()
    assert "proibido" in low or "proibida" in low, (
        "Proibição explícita de cálculo manual não encontrada no prompt de atacado outbound"
    )


# ===========================================================================
# base.py — B3: gatilho de percepção (consultar_relacionamento) + reforço de pricing tool
# ===========================================================================

def test_base_prompt_contem_consultar_relacionamento():
    """base_prompt deve instruir a chamar consultar_relacionamento para percepção de cliente."""
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "consultar_relacionamento" in prompt, (
        "Regra B3 (consultar_relacionamento) não encontrada no base_prompt"
    )


def test_base_prompt_contem_termos_de_recompra():
    """base_prompt deve listar os termos de recompra que disparam consultar_relacionamento."""
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    # "repor" é o termo-chave de recompra da spec (B3)
    assert "repor" in prompt, (
        "Termo de recompra 'repor' não encontrado no base_prompt (B3)"
    )
    # outros termos do spec B3
    assert "novo pedido" in prompt, (
        "Termo de recompra 'novo pedido' não encontrado no base_prompt (B3)"
    )


def test_base_prompt_b3_calcular_orcamento():
    """base_prompt deve reforçar que cálculo de preço é sempre via calcular_orcamento."""
    from app.agent.prompts.base import build_base_prompt
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "calcular_orcamento" in prompt, (
        "Reforço de calcular_orcamento ausente no base_prompt — deve conter instrução B3"
    )
