"""P6 / Task 6.3 — o que conta como venda de KIT DE DEGUSTAÇÃO."""
import pytest

from app.follow_up import kit as K


def test_skus_de_kit_das_duas_contas_bling():
    assert K.SKUS_KIT["default"] == frozenset(
        {16536419853, 16637692216, 16658150270, 9256328993})
    assert K.SKUS_KIT["secundaria"] == frozenset({16697411791, 16701798396})
    assert K.SKUS_KIT_TODOS == K.SKUS_KIT["default"] | K.SKUS_KIT["secundaria"]


@pytest.mark.parametrize("sku", [16536419853, 16637692216, 16658150270, 9256328993,
                                 16697411791, 16701798396])
def test_sku_de_kit_e_kit_mesmo_com_descricao_qualquer(sku):
    assert K.venda_e_kit([{"bling_product_id": sku, "descricao": "Pedido 123"}])


def test_sku_em_texto_tambem_casa():
    assert K.venda_e_kit([{"bling_product_id": "16536419853", "descricao": None}])


@pytest.mark.parametrize("descricao", [
    "Kit Degustação", "KIT DEGUSTAÇÃO 1°", "kit degustacao", "Kit  Degustação 2",
    "Meu KIT degust. especial",
])
def test_descricao_kit_degust_casa_sem_acento_sem_caixa(descricao):
    assert K.venda_e_kit([{"bling_product_id": 0, "descricao": descricao}])


@pytest.mark.parametrize("descricao", [
    "Kit Café Filtrado Drip Coffee Canastra Suave 30un",  # existe em produção: NÃO é kit
    "Café Clássico Moído 250g", "", None,
])
def test_o_que_nao_e_kit(descricao):
    assert not K.venda_e_kit([{"bling_product_id": 0, "descricao": descricao}])


def test_venda_com_kit_e_outro_produto_e_kit():
    assert K.venda_e_kit([
        {"bling_product_id": 1, "descricao": "Café Clássico"},
        {"bling_product_id": 9256328993, "descricao": "KIT DEGUSTAÇÃO"},
    ])


def test_venda_sem_itens_nao_e_kit():
    assert not K.venda_e_kit([])
    assert not K.venda_e_kit(None)
