"""Testes estruturais da Frente D (spec 2026-07-15): frete deterministico via tool,
casamento exato de linha de catalogo e politica de drip/capsula no private label.

Sao testes de PROMPT (assercoes sobre strings) + leitura de constante — sem LLM real.
"""

from app.agent.prompts import get_stage_prompts
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
from app.agent.orchestrator import _build_catalog_block


# ---------------------------------------------------------------------------
# STEP 1 — Frete deterministico no atacado inbound
# ---------------------------------------------------------------------------

def test_atacado_inbound_sem_tabela_de_frete_hardcoded():
    """A tabela de frete em prosa (valores regionais) foi removida do prompt."""
    # Marcadores exatos da tabela removida
    assert "valor do frete: R$55" not in ATACADO_PROMPT
    assert "valor do frete: R$65" not in ATACADO_PROMPT
    assert "valor do frete: R$75" not in ATACADO_PROMPT
    assert "valor do frete: R$85" not in ATACADO_PROMPT
    # O cabecalho "### Tabela de frete" nao existe mais
    assert "Tabela de frete" not in ATACADO_PROMPT
    # Limiares de frete gratis hardcoded tambem sairam
    assert "frete gratis acima de R$900" not in ATACADO_PROMPT


def test_atacado_inbound_frete_via_calcular_orcamento():
    """A diretriz nova manda calcular frete pela ferramenta, nunca de tabela/cabeca."""
    # Deve existir uma diretriz de frete apontando para a ferramenta
    assert "calcular_orcamento" in ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    # A secao de frete deve deixar claro que o valor vem da ferramenta, nao de tabela
    assert "frete" in prompt_lower
    assert ("nunca e citado" in prompt_lower or "nunca cite" in prompt_lower
            or "proibido citar valor de frete" in prompt_lower)


def test_atacado_inbound_mantem_cep_gating():
    """A regra de pedir o CEP antes de mencionar frete permanece."""
    assert "CEP" in ATACADO_PROMPT
    assert "nunca assuma regiao sem CEP" in ATACADO_PROMPT.lower() or \
           "qual o CEP de entrega?" in ATACADO_PROMPT


def test_atacado_inbound_mantem_kit_amostra_frete_incluso():
    """A excecao de preco fixo do Kit Amostra (frete incluso) nao foi removida."""
    prompt_lower = ATACADO_PROMPT.lower()
    assert "kit amostra" in prompt_lower
    assert "frete" in prompt_lower and "incluso" in prompt_lower


# ---------------------------------------------------------------------------
# pricing.py FREIGHT_TABLE intocada (import/leitura apenas)
# ---------------------------------------------------------------------------

def test_freight_table_pricing_intocada():
    """pricing.py continua sendo a fonte unica — sul_sudeste = R$55 (nao alterado)."""
    from app.agent.pricing import FREIGHT_TABLE
    assert FREIGHT_TABLE["sul_sudeste"].frete == 55.0
    assert FREIGHT_TABLE["centro_oeste"].frete == 65.0
    assert FREIGHT_TABLE["nordeste"].frete == 75.0
    assert FREIGHT_TABLE["norte"].frete == 85.0


# ---------------------------------------------------------------------------
# STEP 2 — Casamento exato de linha no private label
# ---------------------------------------------------------------------------

def test_private_label_regra_casamento_exato_de_linha():
    """Regra de casar produto + gramatura + embalagem exatos do item pedido."""
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert "casamento exato de linha" in prompt_lower
    assert "gramatura" in prompt_lower
    assert "embalagem" in prompt_lower
    # Nao trocar o valor de uma linha por outra (o bug do Bruno: Microlote no Classico)
    assert "microlote" in prompt_lower and "classico" in prompt_lower
    assert ("nao passe o valor do microlote" in prompt_lower
            or "outra linha como se fosse o item pedido" in prompt_lower)


# ---------------------------------------------------------------------------
# STEP 3 — Politica de drip/capsula no private label
# ---------------------------------------------------------------------------

def test_private_label_politica_drip_capsula():
    """Drip/capsula existem como produto pronto, mas nao em private label."""
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert "drip" in prompt_lower
    assert "capsula" in prompt_lower
    assert "private label" in prompt_lower
    # Existem como produto Canastra pronto — nao negar o produto
    assert "existem como produto" in prompt_lower
    # A restricao e sobre a personalizacao/marca propria, nao sobre a existencia
    assert "marca propria" in prompt_lower or "personalizacao" in prompt_lower


def test_private_label_nao_reintroduz_strings_de_produto_proibidas():
    """A politica de drip nao pode reintroduzir os marcadores removidos do catalogo
    estatico (guarda do test_base_prompt existente)."""
    assert "Drip Coffee" not in PRIVATE_LABEL_PROMPT
    assert "Capsulas Nespresso" not in PRIVATE_LABEL_PROMPT


# ---------------------------------------------------------------------------
# STEP 4 — Preambulo do bloco de catalogo (orchestrator)
# ---------------------------------------------------------------------------

def test_build_catalog_block_reforca_casamento_de_linha():
    """O preambulo do bloco de catalogo reforca que o preco vem da linha exata."""
    block = _build_catalog_block("- **Café Canastra 250g**\n  - Preço: R$ 26,70")
    assert "produto, gramatura e embalagem" in block
    assert "EXATAMENTE" in block
    assert "nunca substitua pelo valor de outra linha" in block
    # A estrutura da tag permanece intacta
    assert block.startswith("<catalogo_de_produtos>")
    assert block.rstrip().endswith("</catalogo_de_produtos>")


# ---------------------------------------------------------------------------
# Sanidade: prompts ainda carregam pelo registry
# ---------------------------------------------------------------------------

def test_prompts_carregam_pelo_registry():
    inbound = get_stage_prompts("valeria_inbound")
    assert inbound["atacado"] is ATACADO_PROMPT
    assert inbound["private_label"] is PRIVATE_LABEL_PROMPT
