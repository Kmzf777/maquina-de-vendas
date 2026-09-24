"""Private Label: "com a minha logo" nao escolhe a linha "embalagem do cliente" (24/09/2026).

Todo Private Label sai com a logo/marca do cliente, mas o roteiro nunca dizia o que cada
linha de embalagem do catalogo significa. O modelo lia "sua logo" como "embalagem do
cliente" e passava o preco mais barato: em producao (90 dias), frases que so falavam
"com a sua logo/marca" trocaram a linha 23 de 38 vezes (20 leads, ultimo 22/09), enquanto
frases que diziam de quem e a embalagem acertaram 382 de ~387.
"""
from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT


def _secao_casamento() -> str:
    inicio = PRIVATE_LABEL_PROMPT.index("### Casamento exato de linha do catalogo")
    fim = PRIVATE_LABEL_PROMPT.index("### Sabores Disponiveis")
    return PRIVATE_LABEL_PROMPT[inicio:fim]


def test_define_a_linha_padrao_embalagem_canastra():
    secao = _secao_casamento()
    assert '"c/ embalagem Canastra"' in secao
    assert "linha PADRAO" in secao


def test_embalagem_do_cliente_so_quando_o_lead_tem_a_propria():
    secao = _secao_casamento()
    assert '"embalagem do cliente"' in secao
    assert "ja TEM a embalagem pronta" in secao


def test_logo_ou_marca_nao_escolhe_linha():
    assert "NAO escolhem linha" in _secao_casamento()


def test_exemplo_de_preco_diz_de_quem_e_a_embalagem():
    assert '"o 250g sai R$X a unidade na nossa embalagem, ja com o silk da sua logo"' in PRIVATE_LABEL_PROMPT
    assert '"o 250g sai R$X a unidade, ja com embalagem e silk da sua logo"' not in PRIVATE_LABEL_PROMPT
