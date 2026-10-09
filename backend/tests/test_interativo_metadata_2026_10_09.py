"""`messages.metadata.interativo`: a forma que a bolha do CRM lê — 2026-10-09.

O vendedor via no /conversas só o TEXTO das telas da ValerIA: os botões, o menu de
lista e o carrossel que o lead recebeu não chegavam ao CRM. Este módulo é o único
lugar que monta a estrutura gravada junto da mensagem, e a forma é CONTRATO com o
frontend (frontend/src/lib/message-interativo.ts) — mudar uma chave aqui apaga a tela
do vendedor em silêncio.
"""
import logging

from app.button_flow import interativo


def test_botoes_com_imagem():
    assert interativo.botoes(["Fazer pedido", "Provar antes"], imagem="https://x/f.jpg") == {
        "tipo": "botoes", "imagem": "https://x/f.jpg",
        "botoes": ["Fazer pedido", "Provar antes"],
    }


def test_botoes_sem_imagem_grava_null():
    assert interativo.botoes(["Sim"]) == {"tipo": "botoes", "imagem": None, "botoes": ["Sim"]}


def test_lista_com_descricao_vazia():
    assert interativo.lista("Ver opções", [("Pro meu negócio", "revenda"), ("Pra casa", "")]) == {
        "tipo": "lista", "botao": "Ver opções",
        "linhas": [{"titulo": "Pro meu negócio", "descricao": "revenda"},
                   {"titulo": "Pra casa", "descricao": ""}],
    }


def test_carrossel():
    assert interativo.carrossel([("https://x/1.jpg", "Clássico\nR$ 28,70", ["Quero esse"])]) == {
        "tipo": "carrossel",
        "cards": [{"imagem": "https://x/1.jpg", "texto": "Clássico\nR$ 28,70",
                   "botoes": ["Quero esse"]}],
    }


def test_metadata_poe_a_estrutura_na_chave_interativo():
    meta = interativo.metadata(lambda: interativo.botoes(["Sim"]))
    assert meta == {"interativo": {"tipo": "botoes", "imagem": None, "botoes": ["Sim"]}}


def test_metadata_mescla_com_o_que_a_chamada_ja_grava():
    base = {"origem": "teste"}
    meta = interativo.metadata(lambda: interativo.botoes(["Sim"]), base=base)
    assert meta["origem"] == "teste"
    assert meta["interativo"]["botoes"] == ["Sim"]
    assert base == {"origem": "teste"}, "não pode mutar o dict do chamador"


def test_erro_ao_montar_e_fail_soft(caplog):
    """Montar a estrutura nunca pode custar o registro da mensagem (nem o envio)."""
    def explode():
        raise AttributeError("botão sem rótulo")

    with caplog.at_level(logging.WARNING):
        assert interativo.metadata(explode) is None
        assert interativo.metadata(explode, base={"a": 1}) == {"a": 1}
    assert "interativo" in caplog.text


def test_sem_estrutura_devolve_a_base():
    assert interativo.metadata(lambda: None) is None
    assert interativo.metadata(lambda: None, base={"a": 1}) == {"a": 1}
