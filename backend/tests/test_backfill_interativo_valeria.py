"""scripts/backfill_interativo_valeria.py — a lógica pura de casamento (nunca o banco).

As linhas antigas da ValerIA de botões (v1) só têm o TEXTO no `content`. O backfill
reconstrói a tela casando esse texto com o corpo dos nós do registry (com os overrides
de `valeria_flow_content` aplicados, como o runner faz) e o nudge pela tela anterior
da mesma conversa.
"""
from app.button_flow import valeria_registry as reg
from scripts.backfill_interativo_valeria import casar_tela, inferir, montar_telas

TELAS = montar_telas(reg.NOS, reg.TERMINAIS)
NUDGES = {reg.CORPO_NUDGE}


def _linha(content, *, id="m1", conv="C1", meta=None, media_url=None, message_type=None):
    return {"id": id, "conversation_id": conv, "content": content, "metadata": meta,
            "media_url": media_url, "message_type": message_type}


def test_lista_da_entrada_casa_pelo_corpo_exato():
    [tela] = casar_tela(reg.NOS["N0"].corpo, TELAS)
    assert tela.no_id == "N0"
    assert tela.estrutura() == {
        "tipo": "lista", "botao": reg.ROTULO_BOTAO_LISTA,
        "linhas": [{"titulo": b.rotulo, "descricao": b.descricao} for b in reg.NOS["N0"].botoes],
    }


def test_no_com_preco_casa_com_o_preco_resolvido_e_com_a_linha_cortada():
    corpo = reg.NOS["N5"].corpo
    com_preco = corpo.replace("{preco}", "R$ 28,70")
    sem_linha = "\n".join(l for l in corpo.splitlines() if "{preco}" not in l)
    for content in (com_preco, sem_linha):
        casadas = casar_tela(content, TELAS)
        assert [t.no_id for t in casadas] == ["N5"], content


def test_foto_vem_do_media_url_da_linha():
    [tela] = casar_tela(reg.NOS["N5"].corpo.replace("{preco}", "R$ 28,70"), TELAS)
    assert tela.estrutura("https://storage.exemplo/n5.jpg")["imagem"] == "https://storage.exemplo/n5.jpg"
    assert tela.estrutura(None)["imagem"] is None


def test_terminal_de_adiamento_casa_com_a_folha_de_prazos():
    [tela] = casar_tela(reg.TERMINAIS["T_ADIAR"].corpo, TELAS)
    assert tela.estrutura()["botoes"] == [b.rotulo for b in reg.BOTOES_PRAZO]


def test_texto_qualquer_nao_casa():
    assert casar_tela("já chamei o João aqui", TELAS) == []
    assert casar_tela("", TELAS) == []


def test_override_de_corpo_e_rotulo_entra_no_casamento():
    from app.button_flow import valeria_content
    overrides = {"N1": {"corpo": "corpo novo do N1", "rotulos": {reg.NOS["N1"].botoes[0].id: "Rótulo novo"}}}
    telas = montar_telas(valeria_content.aplicar(reg.NOS, overrides), reg.TERMINAIS,
                         rotulo_lista="Escolher")
    [tela] = casar_tela("corpo novo do N1", telas)
    assert tela.estrutura()["botoes"][0] == "Rótulo novo"
    [lista] = casar_tela(reg.NOS["N0"].corpo, telas)
    assert lista.estrutura()["botao"] == "Escolher"


def test_inferir_casa_tela_e_nudge_pela_tela_anterior_da_conversa():
    corpo_n5 = reg.NOS["N5"].corpo.replace("{preco}", "R$ 28,70")
    linhas = [
        _linha(reg.NOS["N0"].corpo, id="a"),
        _linha(corpo_n5, id="b", media_url="https://s/n5.jpg", message_type="image"),
        _linha(reg.CORPO_NUDGE, id="c"),
        _linha(reg.CORPO_NUDGE, id="d"),
        _linha("tchau", id="e"),
    ]
    escritas, contagem = inferir(linhas, TELAS, NUDGES)
    por_id = dict(escritas)
    assert por_id["a"]["interativo"]["tipo"] == "lista"
    assert por_id["b"]["interativo"]["imagem"] == "https://s/n5.jpg"
    # O nudge reenvia os botões do MESMO nó, sem a foto.
    assert por_id["c"]["interativo"] == {"tipo": "botoes", "imagem": None,
                                         "botoes": [b.rotulo for b in reg.NOS["N5"].botoes]}
    assert por_id["d"] == por_id["c"]
    assert "e" not in por_id
    assert contagem["tela"] == 2 and contagem["nudge"] == 2 and contagem["sem_casamento"] == 1


def test_nudge_sem_tela_anterior_na_conversa_e_pulado():
    linhas = [_linha(reg.NOS["N1"].corpo, id="a", conv="C1"),
              _linha(reg.CORPO_NUDGE, id="b", conv="C2")]
    escritas, contagem = inferir(linhas, TELAS, NUDGES)
    assert [i for i, _ in escritas] == ["a"]
    assert contagem["nudge_sem_tela"] == 1


def test_linha_que_ja_tem_interativo_nao_e_reescrita_mas_serve_de_tela_para_o_nudge():
    ja = {"interativo": {"tipo": "botoes", "imagem": None, "botoes": ["X"]}, "outra": 1}
    linhas = [_linha("qualquer", id="a", meta=ja), _linha(reg.CORPO_NUDGE, id="b")]
    escritas, contagem = inferir(linhas, TELAS, NUDGES)
    assert dict(escritas) == {"b": {"interativo": {"tipo": "botoes", "imagem": None, "botoes": ["X"]}}}
    assert contagem["ja_tinha"] == 1


def test_metadata_existente_e_mesclado():
    linhas = [_linha(reg.NOS["N1"].corpo, id="a", meta={"auto": True})]
    [(_, meta)] = inferir(linhas, TELAS, NUDGES)[0]
    assert meta["auto"] is True and meta["interativo"]["tipo"] == "botoes"
