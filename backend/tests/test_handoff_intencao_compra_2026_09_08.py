"""Auditoria QA 08/09 (conversa 5534988861441) — intencao de compra vai pro vendedor.

O que aconteceu em producao: a Valeria passou os precos, ofereceu "quer que eu ja simule
um pedido pra voce com esses itens?", o lead respondeu "pode ser sim" — e em vez de
transbordar pro Joao ela pediu o CEP, entrou no fluxo de montar pedido e repetiu a MESMA
mensagem duas vezes seguidas mesmo com o lead confirmando "sim". Nenhum encaminhar_humano
foi chamado na conversa inteira.

Causas raiz (duas, ambas de prompt):
1. `base.py` — a "REGRA DO PRECO NUNCA SOLTO" trazia literalmente
   "quer que eu ja simule o pedido?" como exemplo de pergunta de fechamento. O "pode ser
   sim" do lead virou consentimento pra simular, nao intencao de compra.
2. `valeria_inbound/atacado.py` — a secao de frete mandava pedir CEP antes de qualquer
   valor. Pior: `calcular_orcamento` nao tem parametro `cep` (so `itens`/`estado`/`cidade`),
   entao o CEP coletado era jogado fora.

Estes guardas impedem que qualquer uma das duas volte numa edicao futura.
"""
from app.agent.prompts.base import BASE_STATIC as BASE_PROMPT
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
from app.agent.tools import TOOL_DECLARATIONS


# ---------------------------------------------------------------------------
# 1. O CTA que semeou o bug nao pode voltar
# ---------------------------------------------------------------------------

def test_base_nao_sugere_simular_pedido_como_fechamento():
    """A frase exata que a Valeria copiou em producao esta banida como EXEMPLO."""
    regra = BASE_PROMPT[BASE_PROMPT.index("REGRA DO PRECO NUNCA SOLTO"):]
    regra = regra[: regra.index("---")]
    # A frase so pode aparecer na lista de PROIBIDO, nunca como exemplo aprovado.
    exemplos_aprovados = regra[: regra.index("PROIBIDO usar como fechamento")]
    assert "simule o pedido" not in exemplos_aprovados
    assert "monte seu pedido" not in exemplos_aprovados


def test_base_proibe_explicitamente_oferta_de_montar_pedido():
    assert "PROIBIDO usar como fechamento qualquer oferta de MONTAR PEDIDO" in BASE_PROMPT
    assert "quer que eu ja simule o pedido?" in BASE_PROMPT  # citada como proibida
    assert "encaminhar_humano" in BASE_PROMPT


# ---------------------------------------------------------------------------
# 2. Atacado inbound: nao pede CEP, nao monta pedido
# ---------------------------------------------------------------------------

def test_atacado_proibe_pedir_cep():
    assert "PROIBIDO pedir CEP" in ATACADO_PROMPT
    # A instrucao antiga mandava pedir o CEP de entrega — nao pode voltar.
    assert "qual o CEP de entrega?" not in ATACADO_PROMPT
    assert "pergunte o CEP antes" not in ATACADO_PROMPT


def test_atacado_proibe_montar_pedido():
    assert "PROIBIDO simular, montar, separar ou fechar pedido com o lead" in ATACADO_PROMPT


def test_calcular_orcamento_nao_recebe_cep():
    """Prova de que pedir CEP era inutil: a ferramenta nunca teve esse parametro."""
    decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "calcular_orcamento")
    props = decl["parameters"]["properties"]
    assert "cep" not in props
    assert set(props) == {"itens", "estado", "cidade"}


def test_atacado_pede_estado_ou_cidade_no_lugar_do_cep():
    assert "pergunte o ESTADO (UF) ou a CIDADE" in ATACADO_PROMPT


# ---------------------------------------------------------------------------
# 3. Gatilhos de handoff que faltavam
# ---------------------------------------------------------------------------

def _etapa_handoff() -> str:
    inicio = ATACADO_PROMPT.index("## Etapa de handoff para fechamento")
    return ATACADO_PROMPT[inicio : ATACADO_PROMPT.index("</instructions>")]


def test_escolha_de_produto_apos_preco_e_intencao_de_compra():
    """"o microlote e capsulas" (fala real do lead) tem que disparar handoff."""
    etapa = _etapa_handoff()
    assert "ESCOLHA DE PRODUTO depois de ver preco" in etapa
    assert "nao e mais uma etapa de descoberta" in etapa


def test_confirmacao_afirmativa_e_intencao_de_compra():
    """"pode ser sim" (fala real do lead) tem que disparar handoff, nao simulacao."""
    etapa = _etapa_handoff()
    assert "pode ser sim" in etapa
    assert "nao autoriza voce a montar pedido" in etapa


def test_handoff_qualifica_antes_de_transbordar():
    """O Joao recebe o lead qualificado — nao um contato cru."""
    etapa = _etapa_handoff()
    assert "qualificar_lead" in etapa
    assert 'encaminhar_humano(vendedor="Joao Bras"' in etapa


def test_handoff_tem_precedencia_e_ocorre_no_mesmo_turno():
    etapa = _etapa_handoff()
    assert "TEM PRECEDENCIA" in etapa
    assert "MESMO turno" in etapa


def test_etapa_handoff_proibe_cep_e_carrinho():
    etapa = _etapa_handoff()
    assert "PROIBIDO nesta etapa: pedir CEP, montar carrinho" in etapa


# ---------------------------------------------------------------------------
# 4. O loop: mesma mensagem repetida apos o lead confirmar
# ---------------------------------------------------------------------------

def test_atacado_proibe_repetir_pergunta_ja_respondida():
    """19:26:33 e 19:27:15 sairam identicas com um "sim" do lead no meio."""
    assert "NUNCA repita a mesma pergunta duas vezes seguidas" in ATACADO_PROMPT
    assert "essa pergunta esta RESPONDIDA" in ATACADO_PROMPT


def test_exemplo_8_nao_ensina_mais_a_montar_pedido():
    """O few-shot ensinava 'mantenho as 4 unidades?' — agora e exemplo NEGATIVO."""
    inicio = ATACADO_PROMPT.index("## Exemplo 8")
    exemplo = ATACADO_PROMPT[inicio : ATACADO_PROMPT.index("## Exemplo 9")]
    montagem = exemplo.index("mantenho as 4 unidades de 250g")
    # A linha da montagem tem que estar marcada com ❌, nunca com ✅.
    assert exemplo.rindex("❌", 0, montagem) > exemplo.rfind("✅", 0, montagem)
    assert "encaminhar_humano" in exemplo
