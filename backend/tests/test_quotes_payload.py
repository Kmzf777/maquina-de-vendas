"""`build_proposal_payload` — o corpo do POST/PUT /propostas-comerciais.

O que este arquivo guarda é o formato do que sai daqui para o ERP. A proposta
comercial NÃO é o pedido de venda com outro nome, e as diferenças são todas
armadilhas silenciosas: um campo `readOnly` enviado, o desconto no formato do
pedido, o frete em `outrasDespesas` — nenhum desses erros aparece como recusa,
eles aparecem como número errado dentro do Bling.

Referência: `docs/reference/bling-propostas-comerciais.openapi.json`.
"""
from decimal import Decimal

import pytest

from app.bling.errors import BlingValidationError
from app.quotes import proposals

ITENS = [{
    "bling_product_id": 777,
    "codigo": "CAF250",
    "descricao": "Cafe Classico 250g",
    "unidade": "UN",
    "quantidade": 2,
    "valor_unitario": "50.00",
    "desconto_percentual": 0,
}]


def payload(**over) -> dict:
    base = dict(
        contact_id=555,
        quoted_at="2026-08-25",
        itens=ITENS,
        discount_value=Decimal("0"),
        freight=Decimal("0"),
        freight_mode=None,
        method_id=45,
        terms=[0],
        seller_id=None,
        store_id=None,
        situacao="Rascunho",
        notes="",
        internal_notes="",
        aos_cuidados_de="",
    )
    base.update(over)
    return proposals.build_proposal_payload(**base)


# ---------------------------------------------------------------------------
# Obrigatórios
# ---------------------------------------------------------------------------
def test_itens_e_parcelas_sao_obrigatorios_no_corpo():
    """Os dois únicos `required` do POST segundo a spec do Bling."""
    corpo = payload()
    assert corpo["itens"], "itens[] é obrigatório"
    assert corpo["parcelas"], "parcelas[] é obrigatório"


def test_contato_data_e_situacao_viajam():
    corpo = payload()
    assert corpo["contato"] == {"id": 555}
    assert corpo["data"] == "2026-08-25"
    assert corpo["situacao"] == "Rascunho"


def test_situacao_inicial_e_rascunho():
    """Decisão 2: o orçamento nasce como Rascunho no Bling. É o que impede uma
    proposta em negociação de aparecer como pendente de faturamento no ERP."""
    assert proposals.SITUACAO_INICIAL == "Rascunho"
    assert payload()["situacao"] == "Rascunho"


def test_sem_itens_e_recusado_com_mensagem_propria():
    with pytest.raises(BlingValidationError) as exc:
        payload(itens=[])
    assert "item" in str(exc.value).lower()


def test_item_sem_vinculo_no_bling_e_recusado_citando_a_descricao():
    """int(None) lá embaixo viraria 500 opaco. A mensagem cita a descrição
    porque o vendedor precisa saber QUAL produto está sem vínculo."""
    with pytest.raises(BlingValidationError) as exc:
        payload(itens=[{**ITENS[0], "bling_product_id": None,
                        "descricao": "Cafe Especial 1kg"}])
    assert "Cafe Especial 1kg" in str(exc.value)


# ---------------------------------------------------------------------------
# readOnly
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("campo", ["id", "total", "totalProdutos"])
def test_campos_readonly_nunca_vao_no_corpo(campo):
    """`id`, `total` e `totalProdutos` são `readOnly` na spec. Mandar `total`
    é o mais tentador e o mais perigoso: o Bling calcula o dele a partir dos
    itens, e um valor nosso ou é ignorado (dando a falsa impressão de que foi
    aceito) ou entra em conflito com a soma das parcelas."""
    corpo = payload(discount_value=Decimal("10.00"), freight=Decimal("5.00"))
    assert campo not in corpo


def test_numero_nao_e_enviado():
    """Quem numera a proposta é o Bling. Mandar `numero` reivindicaria uma
    numeração que já pode existir — e é justamente esse número que a gente vai
    LER de volta no GET para imprimir no PDF."""
    assert "numero" not in payload()


# ---------------------------------------------------------------------------
# Itens
# ---------------------------------------------------------------------------
def test_descricao_do_item_vai_dentro_de_produto():
    """Diferença real para o pedido de venda: lá a descrição é um campo do item
    (`itens[].descricao`); aqui ela é `itens[].produto.descricao`. Mandar no
    lugar do pedido faz o item chegar sem descrição no ERP."""
    item = payload()["itens"][0]
    assert item["produto"] == {"id": 777, "descricao": "Cafe Classico 250g"}
    assert "descricao" not in item


def test_item_leva_codigo_unidade_quantidade_valor_e_desconto():
    item = payload()["itens"][0]
    assert item["codigo"] == "CAF250"
    assert item["unidade"] == "UN"
    assert item["quantidade"] == 2.0
    assert item["valor"] == 50.0
    assert item["desconto"] == 0.0


def test_unidade_ausente_cai_em_un():
    item = payload(itens=[{**ITENS[0], "unidade": None}])["itens"][0]
    assert item["unidade"] == "UN"


def test_desconto_do_item_e_percentual_e_nao_reais():
    """No item o Bling recebe PERCENTUAL; no cabeçalho, reais. Trocar os dois
    transformaria 10% em R$ 10,00 (ou o contrário) sem erro nenhum."""
    item = payload(itens=[{**ITENS[0], "desconto_percentual": "12.5"}])["itens"][0]
    assert item["desconto"] == 12.5


# ---------------------------------------------------------------------------
# Desconto de cabeçalho
# ---------------------------------------------------------------------------
def test_desconto_de_cabecalho_e_numero_puro_em_reais():
    """Risco 1 da spec: na proposta comercial `desconto` é `number`, sem o par
    `{valor, unidade}` do pedido de venda. Já mandamos convertido para reais."""
    corpo = payload(discount_value=Decimal("26.70"))
    assert corpo["desconto"] == 26.7
    assert not isinstance(corpo["desconto"], dict)


def test_desconto_zerado_nao_viaja():
    """Campo ausente e campo com zero não são a mesma coisa para um ERP que
    registra histórico de alteração da proposta."""
    assert "desconto" not in payload(discount_value=Decimal("0"))


# ---------------------------------------------------------------------------
# Frete
# ---------------------------------------------------------------------------
def test_frete_viaja_em_transporte_e_nunca_em_outras_despesas():
    """`outrasDespesas` existe no schema e seria o caminho preguiçoso. O frete
    tem modalidade (CIF/FOB/terceiros) e é isso que o ERP precisa saber para
    emitir a nota — despesa genérica perde essa informação."""
    corpo = payload(freight=Decimal("35.50"), freight_mode=1)
    assert corpo["transporte"]["frete"] == 35.5
    assert corpo["transporte"]["freteModalidade"] == 1
    assert "outrasDespesas" not in corpo


def test_sem_frete_nao_ha_bloco_de_transporte():
    assert "transporte" not in payload()


def test_frete_entra_no_total_e_e_parcelado_junto():
    """O frete é dinheiro que o cliente paga. Fora do parcelamento, a soma das
    parcelas não fecharia com o total da proposta — recusa do Bling."""
    corpo = payload(freight=Decimal("30.00"), freight_mode=0,
                    itens=[{**ITENS[0], "quantidade": 1, "valor_unitario": "70.00"}])
    assert sum(Decimal(str(p["valor"])) for p in corpo["parcelas"]) == Decimal("100.00")


def test_modalidade_de_frete_invalida_e_recusada():
    """O enum do Bling é 0,1,2,3,4,9 — o 5 não existe. Recusar aqui dá uma
    mensagem que cita a modalidade; o Bling devolveria um erro de campo cru."""
    with pytest.raises(BlingValidationError):
        payload(freight=Decimal("10.00"), freight_mode=5)


def test_frete_sem_modalidade_ainda_viaja():
    """Modalidade é opcional no schema; frete sem ela é melhor do que frete
    nenhum (o valor é o que entra no total que o cliente vai pagar)."""
    corpo = payload(freight=Decimal("12.00"))
    assert corpo["transporte"] == {"frete": 12.0}


def test_frete_negativo_e_zerado():
    """Frete negativo seria desconto disfarçado — e furaria a garantia de que o
    total nunca fica abaixo de zero, já que a saturação do desconto só olha o
    subtotal. Mesma regra do `buildQuotePayload` no TS."""
    assert "transporte" not in payload(freight=Decimal("-5.00"))


# ---------------------------------------------------------------------------
# Opcionais
# ---------------------------------------------------------------------------
def test_loja_so_viaja_quando_configurada():
    """`BLING_STORE_ID` não existe no `.env` hoje (risco 4 da spec). `loja` é
    opcional no POST, então `{"id": None}` seria pior do que campo ausente."""
    assert "loja" not in payload(store_id=None)
    assert payload(store_id=203605517)["loja"] == {"id": 203605517}


def test_vendedor_so_viaja_quando_mapeado():
    """Vendedor sem linha em `bling_seller_map` não bloqueia o orçamento — a
    proposta sai sem vendedor, como já acontece no pedido de venda."""
    assert "vendedor" not in payload(seller_id=None)
    assert payload(seller_id=12)["vendedor"] == {"id": 12}


def test_observacoes_e_observacao_interna_usam_as_chaves_da_proposta():
    """Na proposta comercial as chaves são `observacoes` e `observacaoInterna`
    (singular!). No pedido de venda a segunda é `observacoesInternas`. Copiar do
    pedido faria a observação interna ser descartada em silêncio."""
    corpo = payload(notes="Entrega em duas remessas",
                    internal_notes="margem 18%")
    assert corpo["observacoes"] == "Entrega em duas remessas"
    assert corpo["observacaoInterna"] == "margem 18%"
    assert "observacoesInternas" not in corpo


def test_observacoes_vazias_nao_viajam():
    corpo = payload(notes="", internal_notes="")
    assert "observacoes" not in corpo
    assert "observacaoInterna" not in corpo


def test_aos_cuidados_de_so_viaja_quando_preenchido():
    assert "aosCuidadosDe" not in payload()
    assert payload(aos_cuidados_de="Dona Maria")["aosCuidadosDe"] == "Dona Maria"


def test_campos_fora_de_escopo_nao_sao_enviados():
    """§11: garantia, prazo de entrega, introdução, próximo contato e
    transportadora ficaram de fora. O teste existe para que acrescentá-los seja
    uma decisão, não um efeito colateral de alguém copiando o schema inteiro."""
    corpo = payload(freight=Decimal("10.00"), freight_mode=0)
    for campo in ("garantia", "prazoEntrega", "introducao", "dataProximoContato",
                  "totalOutrosItens", "outrasDespesas"):
        assert campo not in corpo
    assert "contato" not in corpo["transporte"]
    assert "volumes" not in corpo["transporte"]


# ---------------------------------------------------------------------------
# Parcelas
# ---------------------------------------------------------------------------
def test_parcelas_carregam_vencimento_valor_e_forma():
    corpo = payload(terms=[30, 60])
    assert [p["dataVencimento"] for p in corpo["parcelas"]] == [
        "2026-09-24", "2026-10-24"]
    assert all(p["formaPagamento"] == {"id": 45} for p in corpo["parcelas"])


def test_sem_forma_de_pagamento_e_recusado():
    """`parcelas[]` é obrigatório e cada parcela carrega a forma — sem ela não
    há o que enviar. A recusa vem de `build_installments`, a mesma da venda."""
    with pytest.raises(BlingValidationError):
        payload(method_id=None)


def test_prazos_vazios_caem_em_a_vista():
    corpo = payload(terms=[])
    assert len(corpo["parcelas"]) == 1
    assert corpo["parcelas"][0]["dataVencimento"] == "2026-08-25"
