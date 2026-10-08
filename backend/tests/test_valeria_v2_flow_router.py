"""`/api/valeria-flow` por `flow_id` (contrato C7 do plano da v2).

Toda rota aceita `?flow_id=` (`valeria_botoes_v1` default | `valeria_botoes_v2`). A v1
sem o parâmetro tem de responder exatamente como antes — quem garante o detalhe é
tests/test_valeria_flow_router_2026_09_30.py, que roda sem `flow_id` nenhum; aqui
fica o que é novo:

  • GET da v2 traz os `cards` dos nós de carrossel e a lista `textos` (regras,
    como-funciona, cada FAQ, nudge, rótulo da lista);
  • PUT de card valida DEPOIS de resolver os preços contra o catálogo atual
    (≤ 160 caracteres, ≤ 2 quebras) e responde 422 quando o card não cabe;
  • `flow_id` desconhecido é 400, em toda rota;
  • o "Ativar" grava o `flow_id` escolhido no perfil novo.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.button_flow import valeria_content as conteudo
from app.button_flow import valeria_flow_router as rotas
from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_registry_v2 as r2
from tests.test_valeria_flow_router_2026_09_30 import (  # banco de mentira já estabelecido
    CANAL_VALERIA,
    _Banco,
    cliente,  # noqa: F401 — fixture
)

_URL = "/api/valeria-flow"
V2 = {"flow_id": "valeria_botoes_v2"}


# ── catálogo de mentira (o formato de `agent.catalog._fetch_active_products`) ──
def _produto(nome, preco, setor="Atacado", min_lot=None):
    return {"sector": setor, "name": nome, "price_formatted": preco,
            "min_lot": min_lot, "is_active": True}


def _catalogo():
    atacado = [
        _produto(sku, "R$ 28,70")
        for card in r2.CARDS_ATACADO for sku in card.skus
    ]
    pl = [
        _produto(sku, "R$ 26,70", setor="Private Label", min_lot="100 un")
        for card in r2.CARDS_PL for sku in card.skus
    ]
    return atacado + pl


@pytest.fixture
def banco(monkeypatch):
    b = _Banco(valeria_flow_content=[], agent_profiles=[], channels=[])
    monkeypatch.setattr(conteudo, "get_supabase", lambda: b)
    monkeypatch.setattr(rotas, "get_supabase", lambda: b)
    monkeypatch.setattr(rotas, "_fetch_active_products", _catalogo)
    return b


def _linha_v2(node_id, corpo):
    return {"id": f"row-{node_id}", "flow_id": r2.FLOW_ID, "node_id": node_id,
            "corpo": corpo, "rotulos": None, "rotulos_antigos": []}


def _no(payload, node_id):
    return next(n for n in payload["nos"] if n["id"] == node_id)


# ═══════════════════════════════════════════════════════════════════════════════
# GET
# ═══════════════════════════════════════════════════════════════════════════════
def test_get_v2_traz_o_registry_da_v2(cliente, banco):
    payload = cliente.get(_URL, params=V2).json()
    assert payload["flow_id"] == r2.FLOW_ID
    assert {n["id"] for n in payload["nos"]} == set(r2.NOS)
    assert {t["id"] for t in payload["terminais"]} == set(r2.TERMINAIS)


def test_get_v2_traz_os_3_cards_da_vitrine_atacado(cliente, banco):
    va = _no(cliente.get(_URL, params=V2).json(), "VA")
    assert [c["id"] for c in va["cards"]] == ["classico", "suave", "microlote"]
    classico = va["cards"][0]
    assert classico["corpo"] == r2.CARDS_ATACADO[0].corpo
    assert classico["corpo_default"] == r2.CARDS_ATACADO[0].corpo
    assert classico["chave"] == "card:VA:classico"
    assert classico["editado"] is False


def test_get_v2_aplica_o_override_do_card(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha_v2("card:VA:suave", "Suave editado")]
    va = _no(cliente.get(_URL, params=V2).json(), "VA")
    suave = next(c for c in va["cards"] if c["id"] == "suave")
    assert suave["corpo"] == "Suave editado"
    assert suave["corpo_default"] == r2.CARDS_ATACADO[1].corpo
    assert suave["editado"] is True


def test_get_v2_traz_a_lista_de_textos(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha_v2("faq:atacado:frete", "frete editado")]
    textos = {t["chave"]: t for t in cliente.get(_URL, params=V2).json()["textos"]}
    assert set(textos) == set(r2.CHAVES_TEXTO)
    assert textos[r2.CHAVE_REGRAS_ATACADO]["corpo_default"] == r2.REGRAS_ATACADO_DEFAULT
    assert textos[r2.CHAVE_COMO_FUNCIONA_PL]["corpo"] == r2.COMO_FUNCIONA_PL_DEFAULT
    assert textos["faq:atacado:frete"]["corpo"] == "frete editado"
    assert textos["faq:atacado:frete"]["corpo_default"] == r2.FAQ["atacado"]["frete"]
    assert textos["faq:atacado:frete"]["editado"] is True
    assert textos["faq:private_label:prazo_pl"]["editado"] is False


def test_get_v2_le_os_overrides_so_da_v2(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [
        {"id": "x", "flow_id": reg.FLOW_ID, "node_id": "N0", "corpo": "corpo da v1",
         "rotulos": None, "rotulos_antigos": []},
    ]
    assert _no(cliente.get(_URL, params=V2).json(), "N0")["corpo"] == r2.NOS["N0"].corpo
    assert _no(cliente.get(_URL).json(), "N0")["corpo"] == "corpo da v1"


def test_get_sem_flow_id_continua_a_v1_sem_cards_nem_textos(cliente, banco):
    payload = cliente.get(_URL).json()
    assert payload["flow_id"] == reg.FLOW_ID
    assert {n["id"] for n in payload["nos"]} == set(reg.NOS)
    assert "textos" not in payload
    assert all("cards" not in n for n in payload["nos"])


# ═══════════════════════════════════════════════════════════════════════════════
# flow_id desconhecido
# ═══════════════════════════════════════════════════════════════════════════════
def test_flow_id_desconhecido_e_400_em_toda_rota(cliente, banco):
    ruim = {"flow_id": "recuperacao_v1"}
    assert cliente.get(_URL, params=ruim).status_code == 400
    assert cliente.get(f"{_URL}/channels", params=ruim).status_code == 400
    assert cliente.put(f"{_URL}/N0", params=ruim, json={"corpo": "x"}).status_code == 400
    assert cliente.delete(f"{_URL}/N0", params=ruim).status_code == 400
    with patch.object(rotas, "get_channel", return_value=CANAL_VALERIA):
        resposta = cliente.post(f"{_URL}/activate",
                                json={"channel_id": CANAL_VALERIA["id"], "flow_id": "x"})
    assert resposta.status_code == 400
    assert banco.escritas() == []


# ═══════════════════════════════════════════════════════════════════════════════
# PUT / DELETE
# ═══════════════════════════════════════════════════════════════════════════════
def test_put_card_com_161_caracteres_e_422(cliente, banco):
    resposta = cliente.put(f"{_URL}/card:classico", params=V2, json={"corpo": "x" * 161})
    assert resposta.status_code == 422, resposta.text
    assert banco.escritas("valeria_flow_content") == []


def test_put_card_mede_depois_de_resolver_o_preco(cliente, banco):
    """O marcador é longo e o preço é curto: 160 contados no texto CRU recusariam
    um card que cabe; contados no resolvido, aceita."""
    marcador = "{preco:Canastra Clássico — Moído 250g}"
    corpo = "a" * (160 - len("R$ 28,70")) + marcador
    assert len(corpo) > 160
    resposta = cliente.put(f"{_URL}/card:classico", params=V2, json={"corpo": corpo})
    assert resposta.status_code == 200, resposta.text


def test_put_card_com_3_quebras_e_422(cliente, banco):
    resposta = cliente.put(f"{_URL}/card:classico", params=V2, json={"corpo": "a\nb\nc\nd"})
    assert resposta.status_code == 422


def test_put_card_com_preco_que_nao_existe_e_422(cliente, banco):
    resposta = cliente.put(f"{_URL}/card:classico", params=V2,
                           json={"corpo": "Clássico {preco:Produto Inventado}"})
    assert resposta.status_code == 422
    assert "Produto Inventado" in resposta.json()["detail"]


def test_put_card_grava_na_chave_canonica(cliente, banco):
    resposta = cliente.put(f"{_URL}/card:classico", params=V2, json={"corpo": "Clássico novo"})
    assert resposta.status_code == 200, resposta.text
    gravado = banco.linhas("valeria_flow_content")
    assert [(l["flow_id"], l["node_id"], l["corpo"], l["rotulos"]) for l in gravado] == [
        (r2.FLOW_ID, "card:VA:classico", "Clássico novo", None),
    ]
    corpo = resposta.json()
    assert corpo["chave"] == "card:VA:classico"
    assert corpo["corpo"] == "Clássico novo"
    assert corpo["editado"] is True


def test_put_card_ambiguo_pede_a_chave_com_o_no(cliente, banco):
    """`microlote` existe na vitrine atacado E na de marca própria."""
    resposta = cliente.put(f"{_URL}/card:microlote", params=V2, json={"corpo": "x"})
    assert resposta.status_code == 400
    assert "card:VA:microlote" in resposta.json()["detail"]
    ok = cliente.put(f"{_URL}/card:VA:microlote", params=V2, json={"corpo": "Microlote novo"})
    assert ok.status_code == 200, ok.text


def test_put_card_microlote_pl_valida_o_texto_mesmo_com_o_lote_pendente(cliente, banco, monkeypatch):
    """`exige_min_lot` é estado do CATÁLOGO, não do texto: o card do Microlote PL
    fica fora do ar até o catálogo dizer 100 un, mas o texto dele é editável."""
    sem_lote = [dict(p, min_lot="50 un") if p["sector"] == "Private Label" else p
                for p in _catalogo()]
    monkeypatch.setattr(rotas, "_fetch_active_products", lambda: sem_lote)
    resposta = cliente.put(f"{_URL}/card:VP:microlote", params=V2,
                           json={"corpo": "Microlote com a sua marca"})
    assert resposta.status_code == 200, resposta.text


def test_put_card_com_catalogo_fora_do_ar_e_503(cliente, banco, monkeypatch):
    def _quebra():
        raise RuntimeError("sem banco")
    monkeypatch.setattr(rotas, "_fetch_active_products", _quebra)
    resposta = cliente.put(f"{_URL}/card:classico", params=V2, json={"corpo": "x"})
    assert resposta.status_code == 503
    assert banco.escritas("valeria_flow_content") == []


def test_put_card_rejeita_rotulos(cliente, banco):
    resposta = cliente.put(f"{_URL}/card:classico", params=V2,
                           json={"rotulos": {"x": "y"}})
    assert resposta.status_code == 400


def test_put_card_inexistente_e_404(cliente, banco):
    assert cliente.put(f"{_URL}/card:nao_existe", params=V2, json={"corpo": "x"}).status_code == 404
    assert cliente.put(f"{_URL}/card:VP:classico", params=V2, json={"corpo": "x"}).status_code == 404


def test_put_faq_atacado_frete(cliente, banco):
    resposta = cliente.put(f"{_URL}/faq:atacado:frete", params=V2,
                           json={"corpo": "frete grátis acima de R$2.000"})
    assert resposta.status_code == 200, resposta.text
    linha = banco.linhas("valeria_flow_content")[0]
    assert (linha["flow_id"], linha["node_id"]) == (r2.FLOW_ID, "faq:atacado:frete")
    assert resposta.json()["corpo"] == "frete grátis acima de R$2.000"
    assert resposta.json()["corpo_default"] == r2.FAQ["atacado"]["frete"]


def test_put_texto_em_branco_e_400(cliente, banco):
    resposta = cliente.put(f"{_URL}/{r2.CHAVE_REGRAS_ATACADO}", params=V2, json={"corpo": "  "})
    assert resposta.status_code == 400


def test_put_faq_que_nao_existe_e_404(cliente, banco):
    resposta = cliente.put(f"{_URL}/faq:atacado:prazo_pl", params=V2, json={"corpo": "x"})
    assert resposta.status_code == 404


def test_put_no_da_v2_grava_no_flow_id_da_v2(cliente, banco):
    resposta = cliente.put(f"{_URL}/VA", params=V2,
                           json={"rotulos": {"pedido": "Quero pedir"}})
    assert resposta.status_code == 200, resposta.text
    linha = banco.linhas("valeria_flow_content")[0]
    assert (linha["flow_id"], linha["node_id"]) == (r2.FLOW_ID, "VA")
    assert linha["rotulos"] == {"pedido": "Quero pedir"}


def test_put_no_que_so_existe_na_v2_e_404_na_v1(cliente, banco):
    assert cliente.put(f"{_URL}/VA", json={"corpo": "x"}).status_code == 404
    assert cliente.put(f"{_URL}/faq:atacado:frete", json={"corpo": "x"}).status_code == 404


def test_put_terminal_novo_da_v2(cliente, banco):
    resposta = cliente.put(f"{_URL}/T_KIT", params=V2, json={"corpo": "já chamei o João"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["tipo"] == "terminal"


def test_delete_card_volta_ao_default(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha_v2("card:VA:classico", "editado")]
    resposta = cliente.delete(f"{_URL}/card:classico", params=V2)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["corpo"] == r2.CARDS_ATACADO[0].corpo
    assert banco.linhas("valeria_flow_content") == []


def test_delete_faq_volta_ao_default(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [_linha_v2("faq:atacado:frete", "editado")]
    resposta = cliente.delete(f"{_URL}/faq:atacado:frete", params=V2)
    assert resposta.status_code == 200
    assert resposta.json()["corpo"] == r2.FAQ["atacado"]["frete"]


def test_delete_v2_nao_toca_na_linha_da_v1(cliente, banco):
    banco.tabelas["valeria_flow_content"] = [
        {"id": "a", "flow_id": reg.FLOW_ID, "node_id": "N0", "corpo": "v1",
         "rotulos": None, "rotulos_antigos": []},
        _linha_v2("N0", "v2"),
    ]
    assert cliente.delete(f"{_URL}/N0", params=V2).status_code == 200
    assert [(l["flow_id"], l["corpo"]) for l in banco.linhas("valeria_flow_content")] == [
        (reg.FLOW_ID, "v1"),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# channels / activate
# ═══════════════════════════════════════════════════════════════════════════════
def test_channels_traz_o_flow_id_de_cada_canal(cliente, banco):
    v2 = {**CANAL_VALERIA, "id": "c-v2", "agent_profile_id": "p2",
          "agent_profiles": {"id": "p2", "name": "Botões v2", "kind": "button_flow",
                             "flow_id": r2.FLOW_ID}}
    with patch.object(rotas, "list_channels", return_value=[CANAL_VALERIA, v2]):
        por_id = {c["id"]: c for c in cliente.get(f"{_URL}/channels").json()["canais"]}
    assert por_id["c-v2"]["flow_id"] == r2.FLOW_ID
    assert por_id["c-v2"]["perfil"]["flow_id"] == r2.FLOW_ID
    assert por_id[CANAL_VALERIA["id"]]["flow_id"] is None
    # sem `flow_id` a pergunta "atende este fluxo?" continua sendo sobre a v1
    assert por_id["c-v2"]["atende_este_fluxo"] is False


def test_channels_com_flow_id_v2_responde_pela_v2(cliente, banco):
    v2 = {**CANAL_VALERIA, "agent_profile_id": "p2",
          "agent_profiles": {"id": "p2", "kind": "button_flow", "flow_id": r2.FLOW_ID}}
    with patch.object(rotas, "list_channels", return_value=[v2]):
        payload = cliente.get(f"{_URL}/channels", params=V2).json()
    assert payload["flow_id"] == r2.FLOW_ID
    assert payload["canais"][0]["atende_este_fluxo"] is True


@pytest.fixture
def canal(monkeypatch):
    alvo = dict(CANAL_VALERIA)
    atualizados = []
    monkeypatch.setattr(rotas, "get_channel", lambda cid: alvo if cid == alvo["id"] else None)
    monkeypatch.setattr(rotas, "update_channel",
                        lambda cid, data: atualizados.append((cid, dict(data))) or alvo)
    return SimpleNamespace(alvo=alvo, atualizados=atualizados)


def test_activate_v2_cria_perfil_com_o_flow_id_da_v2(cliente, banco, canal):
    resposta = cliente.post(f"{_URL}/activate",
                            json={"channel_id": canal.alvo["id"], "flow_id": r2.FLOW_ID})
    assert resposta.status_code == 200, resposta.text
    novo = banco.payload_de("agent_profiles", "insert")
    assert novo["flow_id"] == r2.FLOW_ID
    assert novo["kind"] == "button_flow"
    assert resposta.json()["flow_id"] == r2.FLOW_ID
    assert canal.atualizados == [(canal.alvo["id"], {"agent_profile_id": resposta.json()["agent_profile_id"]})]


def test_activate_sem_flow_id_continua_v1(cliente, banco, canal):
    resposta = cliente.post(f"{_URL}/activate", json={"channel_id": canal.alvo["id"]})
    assert resposta.status_code == 200
    assert banco.payload_de("agent_profiles", "insert")["flow_id"] == reg.FLOW_ID
