"""Runner da ValerIA v2: vitrine, texto livre classificado e nota de repasse.

Dublês na mesma forma de `test_valeria_runner_2026_09_29.py`: provedor que grava as
chamadas, banco/CRM/score/histórico dublados no namespace do runner v1 (de onde a v2
reusa os helpers por import), catálogo dublado em `agent.catalog`, classificador
dublado em `valeria_classifier.classificar`.

O catálogo de teste tem a FORMA de produção: `_fetch_active_products` não projeta
`is_active` (o filtro é na query), e o runner precisa funcionar com isso.
"""
from unittest.mock import AsyncMock

import pytest

from app.agent import catalog
from app.button_flow import effects, valeria_classifier, valeria_content
from app.button_flow import runner as irmao
from app.button_flow import valeria_registry_v2 as r2
from app.button_flow import valeria_runner as v1
from app.button_flow import valeria_runner_v2 as v2
from app.button_flow.valeria_classifier import Classificacao

PRONTA_ATACADO = "Olá! Tenho um comércio e quero revender café especial."
PRONTA_PL = "Olá! Quero saber mais sobre ter a Marca Própria de Café."

# Catálogo de produção em 08/10/2026 (sem `is_active`, como `_fetch_active_products`).
ATACADO = [
    ("Canastra Canela — Moído 250g", "R$ 28,70"),
    ("Canastra Clássico — Em Grãos 1kg", "R$ 97,70"),
    ("Canastra Clássico — Em Grãos 250g", "R$ 31,70"),
    ("Canastra Clássico — Em Grãos 500g", "R$ 54,70"),
    ("Canastra Clássico — Moído 250g", "R$ 28,70"),
    ("Canastra Clássico — Moído 500g", "R$ 52,70"),
    ("Canastra Suave — Em Grãos 1kg", "R$ 97,70"),
    ("Canastra Suave — Em Grãos 250g", "R$ 31,70"),
    ("Canastra Suave — Em Grãos 500g", "R$ 54,70"),
    ("Canastra Suave — Moído 250g", "R$ 28,70"),
    ("Canastra Suave — Moído 500g", "R$ 52,70"),
    ("Cápsula Canastra Clássico — Display 10 cápsulas", "R$ 22,90"),
    ("Drip Coffee Canastra Suave — Display 10 sachês", "R$ 24,90"),
    ("Microlote — Em Grãos 250g", "R$ 32,70"),
    ("Microlote — Moído 250g", "R$ 32,70"),
]
PL = [
    ("Café Canastra 250g — c/ embalagem Canastra", "R$ 26,70", "100 un"),
    ("Café Canastra 250g — embalagem do cliente", "R$ 25,70", "100 un"),
    ("Café Canastra 500g — c/ embalagem Canastra", "R$ 48,70", "100 un"),
    ("Café Canastra 500g — embalagem do cliente", "R$ 47,70", "100 un"),
    ("Microlote 250g — c/ embalagem Canastra", "R$ 29,70", "100 un"),
    # Divergência real do catálogo (spec §4): 50 un segura o card do Microlote PL.
    ("Microlote 250g — embalagem do cliente", "R$ 27,70", "50 un"),
]


def catalogo_producao() -> list[dict]:
    return ([{"sector": "Atacado", "name": n, "price_formatted": p, "min_lot": None}
             for n, p in ATACADO]
            + [{"sector": "Private Label", "name": n, "price_formatted": p, "min_lot": m}
               for n, p, m in PL])


class ProvedorFalso:
    def __init__(self):
        self.chamadas = []
        self.carrossel_explode = False

    async def send_interactive_carousel(self, to, body, cards):
        if self.carrossel_explode:
            raise RuntimeError("Meta 131009: parameter value is not valid")
        self.chamadas.append(("carrossel", body, cards))
        return {"messages": [{"id": "wamid.c"}]}

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.chamadas.append(("botoes", body, buttons, image_url))
        return {"messages": [{"id": "wamid.1"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.chamadas.append(("lista", body, rows))
        return {"messages": [{"id": "wamid.2"}]}

    async def send_text(self, to, text):
        self.chamadas.append(("texto", text))
        return {"messages": [{"id": "wamid.3"}]}

    async def send_contact(self, to, *, contact_name, contact_phone):
        self.chamadas.append(("cartao", contact_name, contact_phone))
        return {"messages": [{"id": "wamid.4"}]}

    def tipos(self):
        return [c[0] for c in self.chamadas]


@pytest.fixture
def turno(monkeypatch):
    """Dirige `processar_inbound` da v2 com banco, CRM, catálogo e LLM dublados."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.setattr(irmao, "is_lead_blacklisted", lambda _lead_id: False)
    # O despacho resolveria o perfil do canal no banco; aqui a conversa é da v2.
    monkeypatch.setattr(irmao, "fluxo_efetivo", lambda _c, _ch: r2.FLOW_ID)

    registro = {"efeitos": [], "salvas": [], "notas": [], "gravacoes": [],
                "historico": [], "score": [], "classificacoes": [], "kw_efeitos": []}
    conversa = {"id": "C1", "stage": "atacado", "flow_state": None}
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "name": "Roner", "human_control": False, "metadata": {}}
    estado_catalogo = {"linhas": catalogo_producao()}

    def _gravar_estado(_cid, **kw):
        registro["gravacoes"].append(kw["flow_state"])
        conversa["flow_state"] = kw["flow_state"]

    def _salvar(*a, **k):
        linha = {"role": a[2], "content": a[3], "sent_by": k.get("sent_by"),
                 "message_type": k.get("message_type"), "metadata": {}}
        registro["salvas"].append(linha)
        registro["historico"].append(linha)

    def _catalogo():
        linhas = estado_catalogo["linhas"]
        if isinstance(linhas, Exception):
            raise linhas
        return linhas

    def _aplicar(efeitos, **kw):
        registro["efeitos"].append(efeitos)
        registro["kw_efeitos"].append(kw)
        return True

    monkeypatch.setattr(v1, "_reler_estado", lambda c: c.get("flow_state"))
    monkeypatch.setattr(v1, "get_open_deal", lambda _l: None)
    monkeypatch.setattr(v1, "update_conversation", _gravar_estado)
    monkeypatch.setattr(v1, "save_message", _salvar)
    monkeypatch.setattr(v2, "save_message", _salvar)
    monkeypatch.setattr(v1, "url_publica_da_foto", lambda c: f"https://storage.exemplo/{c}")
    monkeypatch.setattr(v1, "save_score_evidence", lambda **kw: registro["score"].append(kw))
    monkeypatch.setattr(v1, "_historico", lambda _cid: [])
    monkeypatch.setattr(v2, "get_history",
                        lambda _cid, **_kw: list(registro["historico"]))
    monkeypatch.setattr(catalog, "_fetch_active_products", _catalogo)
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {})
    monkeypatch.setattr(effects, "anotar", lambda _l, _c, texto: registro["notas"].append(texto))
    monkeypatch.setattr(effects, "atualizar_metadata", lambda *a, **k: True)
    monkeypatch.setattr(effects, "aplicar", _aplicar)

    classificar = AsyncMock(return_value=Classificacao("RUIDO"))
    monkeypatch.setattr(valeria_classifier, "classificar", classificar)

    provedor = ProvedorFalso()

    async def _rodar(texto, *, payload=None, titulo=""):
        meta = {"payload": payload, "title": titulo} if payload else None
        # O processor persiste o inbound ANTES do runner.
        registro["historico"].append({
            "role": "user", "content": texto, "sent_by": None,
            "message_type": "button" if payload else "text", "metadata": meta or {},
        })
        motivo = await v2.processar_inbound(
            lead=lead, conversation=conversa, channel={"mode": "ai", "phone": "553499999999"},
            provider=provedor, texto=texto, metadata=meta, wamid="wamid.in",
            message_type="button" if payload else "text",
        )
        _rodar.motivo = motivo
        return conversa["flow_state"]

    _rodar.provedor = provedor
    _rodar.registro = registro
    _rodar.conversa = conversa
    _rodar.lead = lead
    _rodar.catalogo = estado_catalogo
    _rodar.classificar = classificar
    return _rodar


def _no(estado, node, **extra):
    base = {"flow": r2.FLOW_ID, "node": node, "nudges": 0}
    base.update(extra)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# Primeiro contato e vitrine
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_primeiro_contato_atacado_manda_carrossel_tabela_e_acoes(turno):
    estado = await turno(PRONTA_ATACADO)

    p = turno.provedor
    assert p.tipos() == ["carrossel", "texto", "botoes"]
    _, corpo, cards = p.chamadas[0]
    assert corpo == r2.NOS["VA"].corpo
    assert len(cards) == 3
    assert [c["buttons"] for c in cards] == [
        [("card:classico", "Quero esse")], [("card:suave", "Quero esse")],
        [("card:microlote", "Quero esse")],
    ]
    assert cards[0]["image_url"] == "https://storage.exemplo/atacado/foto_1_classico.jpg"
    assert "R$ 28,70" in cards[0]["body"] and "{preco" not in cards[0]["body"]
    tabela = p.chamadas[1][1]
    assert tabela.startswith("tabela atacado")
    assert "pedido mínimo R$500" in tabela
    assert p.chamadas[2][1] == r2.CORPO_ACOES
    assert [b[0] for b in p.chamadas[2][2]] == ["pedido", "provar", "duvida"]

    assert estado["node"] == "VA" and estado["ramo"] == "atacado"
    assert estado["flow"] == r2.FLOW_ID
    assert estado["viu"] == ["vitrine", "tabela"]
    turno.classificar.assert_not_called()

    salvas = turno.registro["salvas"]
    assert len(salvas) == 3
    # Sem tipo de mídia: o CRM (lib/message-preview.ts) lê `content` só de
    # None/"text"/"button" — "interactive" aparecia como "📎 Mídia" para o vendedor.
    assert salvas[0]["message_type"] is None
    assert r2.NOS["VA"].corpo in salvas[0]["content"] and "R$ 97,70" in salvas[0]["content"]
    assert all(s["sent_by"] == "valeria_botoes" for s in salvas)


@pytest.mark.asyncio
async def test_primeiro_contato_com_oi_manda_a_lista_do_n0(turno):
    estado = await turno("oi")
    assert turno.provedor.tipos() == ["lista"]
    assert len(turno.provedor.chamadas[0][2]) == 4
    assert estado["node"] == "N0"
    turno.classificar.assert_not_called()


@pytest.mark.asyncio
async def test_primeiro_contato_pedindo_para_sair_e_honrado_sem_llm(turno):
    estado = await turno("me tira da lista")
    assert estado["node"] == "T_OPTOUT"
    assert turno.registro["efeitos"][0].optout is True
    turno.classificar.assert_not_called()


@pytest.mark.asyncio
async def test_vitrine_pl_sem_microlote_a_100_un_tem_2_cards(turno):
    estado = await turno(PRONTA_PL)
    p = turno.provedor
    assert p.tipos() == ["carrossel", "texto", "botoes"]
    cards = p.chamadas[0][2]
    assert [c["buttons"][0][0] for c in cards] == ["card:embalagem_canastra",
                                                  "card:embalagem_cliente"]
    como_funciona = p.chamadas[1][1]
    assert "R$ 2.670,00" in como_funciona and "{total_pl}" not in como_funciona
    assert [b[0] for b in p.chamadas[2][2]] == ["orcamento", "provar", "duvida"]
    assert estado["ramo"] == "private_label" and estado["node"] == "VP"


@pytest.mark.asyncio
async def test_um_card_so_vira_texto_e_segue_tabela_e_botoes(turno):
    # Só o Clássico resolve: Suave e Microlote somem do catálogo.
    turno.catalogo["linhas"] = [p for p in catalogo_producao()
                                if "Suave" not in p["name"] and "Microlote" not in p["name"]]
    await turno(PRONTA_ATACADO)
    p = turno.provedor
    assert p.tipos() == ["texto", "texto", "botoes"]
    assert p.chamadas[0][1].startswith("Clássico · torra escura")
    assert p.chamadas[1][1].startswith("tabela atacado")


@pytest.mark.asyncio
async def test_carrossel_recusado_vira_botoes_com_foto_e_sem_terceira_mensagem(turno):
    turno.provedor.carrossel_explode = True
    estado = await turno(PRONTA_ATACADO)
    p = turno.provedor
    # A tabela primeiro; os botões (com a foto) por ÚLTIMO, onde o lead os vê.
    assert p.tipos() == ["texto", "botoes"]
    assert p.chamadas[0][1].startswith("tabela atacado")
    _, corpo, botoes, imagem = p.chamadas[1]
    assert corpo == r2.NOS["VA"].corpo
    assert [b[0] for b in botoes] == ["pedido", "provar", "duvida"]
    assert imagem == "https://storage.exemplo/atacado/foto_1_classico.jpg"
    assert estado["node"] == "VA" and estado["viu"] == ["tabela", "vitrine"]


@pytest.mark.asyncio
async def test_pl_sem_o_sku_base_nao_derruba_a_vitrine(turno):
    """Um SKU faltando não é catálogo vazio: sem "como funciona", o resto sai."""
    turno.catalogo["linhas"] = [p for p in catalogo_producao()
                                if p["name"] != "Café Canastra 250g — c/ embalagem Canastra"]
    estado = await turno(PRONTA_PL)
    p = turno.provedor
    assert p.tipos() == ["texto", "botoes"]       # 1 card só (vira texto) + ações
    assert p.chamadas[0][1].startswith("Sua própria embalagem")
    assert [b[0] for b in p.chamadas[1][2]] == ["orcamento", "provar", "duvida"]
    assert estado["node"] == "VP"
    assert not any(e.handoff for e in turno.registro["efeitos"])


@pytest.mark.asyncio
async def test_atacado_com_preco_mas_sem_linha_de_tabela_nao_repassa(turno):
    turno.catalogo["linhas"] = [{"sector": "Atacado", "name": "SKU fora da tabela",
                                 "price_formatted": "R$ 10,00", "min_lot": None}]
    estado = await turno(PRONTA_ATACADO)
    assert turno.provedor.tipos() == ["botoes"]
    assert turno.provedor.chamadas[0][1] == r2.CORPO_ACOES
    assert estado["node"] == "VA"
    assert not any(e.handoff for e in turno.registro["efeitos"])


@pytest.mark.asyncio
async def test_catalogo_vazio_avisa_e_repassa(turno):
    turno.catalogo["linhas"] = []
    estado = await turno(PRONTA_ATACADO)
    p = turno.provedor
    # UMA mensagem só (sem o corpo do terminal) e o cartão do vendedor.
    assert p.tipos() == ["texto", "cartao"]
    assert p.chamadas[0][1] == (
        "nossa tabela tá sendo atualizada; já chamei o João Brás aqui pra te passar os valores")
    assert estado["node"] == "T_HANDOFF" and estado["ramo"] == "atacado"
    assert any(e.handoff for e in turno.registro["efeitos"])
    nota = turno.registro["notas"][-1]
    assert nota.startswith("[ValerIA botões v2] Atacado")
    assert "Origem do repasse:" in nota


@pytest.mark.asyncio
async def test_catalogo_fora_do_ar_tambem_repassa(turno):
    turno.catalogo["linhas"] = RuntimeError("PostgREST fora")
    estado = await turno(PRONTA_PL)
    assert turno.registro["kw_efeitos"][-1]["nota_sem_qualificacao"] is False
    assert turno.provedor.chamadas[0][1].startswith("nossa tabela tá sendo atualizada")
    assert estado["node"] == "T_HANDOFF_PL"


@pytest.mark.asyncio
async def test_override_de_card_e_aplicado(turno, monkeypatch):
    chave = valeria_content.chave_do_card("VA", "classico")
    monkeypatch.setattr(valeria_content, "carregar",
                        lambda _f: {chave: {"corpo": "Clássico do editor {preco:Canastra Clássico — Moído 250g}"}})
    await turno(PRONTA_ATACADO)
    cards = turno.provedor.chamadas[0][2]
    assert cards[0]["body"] == "Clássico do editor R$ 28,70"


# ═══════════════════════════════════════════════════════════════════════════
# Texto livre classificado
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_faq_frete_no_qa1_responde_e_reapresenta_o_qa1(turno):
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    turno.classificar.return_value = Classificacao("FAQ", faq_id="frete")
    estado = await turno("tem frete grátis?")
    p = turno.provedor
    assert p.tipos() == ["texto", "botoes"]
    assert p.chamadas[0][1] == r2.FAQ["atacado"]["frete"]
    assert p.chamadas[1][1] == r2.NOS["QA1"].corpo
    assert estado["node"] == "QA1"
    assert estado["faqs"] == ["frete"]


@pytest.mark.asyncio
async def test_botao_classificado_avanca_e_grava_o_score(turno):
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    turno.classificar.return_value = Classificacao("BOTAO", botao_id="cafeteria")
    estado = await turno("tenho uma cafeteria")
    p = turno.provedor
    assert p.tipos() == ["botoes"]
    assert p.chamadas[0][1] == r2.NOS["QA2"].corpo
    assert estado["node"] == "QA2"
    assert estado["respostas"] == {"QA1": "cafeteria"}
    assert turno.registro["score"][0]["updates"] == {"segment": "cafeteria"}
    # A prova do critério é o que o lead escreveu.
    assert turno.registro["score"][0]["evidence"] == {
        "segment": {"text": "tenho uma cafeteria"}}


@pytest.mark.asyncio
async def test_pergunta_no_qa2_repassa_com_o_texto_na_nota(turno):
    turno.conversa["flow_state"] = _no(None, "QA2", ramo="atacado", interesse="classico",
                                       respostas={"QA1": "cafeteria"}, viu=["vitrine", "tabela"])
    turno.classificar.return_value = Classificacao("PERGUNTA")
    turno.registro["historico"].append({"role": "user", "content": "tenho 2 lojas em BH",
                                        "message_type": "text", "metadata": {}})
    estado = await turno("vocês fazem café com açaí?")
    p = turno.provedor
    assert p.tipos() == ["texto", "cartao"]
    assert p.chamadas[0][1] == r2.TERMINAIS["T_HANDOFF"].corpo
    assert estado["node"] == "T_HANDOFF"
    nota = turno.registro["notas"][-1]
    assert "interesse: Clássico" in nota
    assert "Negócio: Cafeteria" in nota
    assert "Viu: vitrine + tabela" in nota
    # O texto da pergunta vai na Origem e NÃO se repete em "Mensagens escritas".
    assert 'Mensagens escritas pelo lead: "tenho 2 lojas em BH"' in nota
    assert nota.count("vocês fazem café com açaí?") == 1
    assert "Origem do repasse: PERGUNTA: vocês fazem café com açaí?" in nota


@pytest.mark.asyncio
async def test_dois_ruidos_nudge_e_depois_repasse(turno):
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    estado = await turno("bom dia")
    assert turno.provedor.chamadas[0][1] == r2.CORPO_NUDGE
    assert estado["node"] == "QA1" and estado["ruidos"] == 1 and estado["nudges"] == 1

    estado = await turno("hmmm")
    assert turno.provedor.chamadas[1][1] == r2.TERMINAIS["T_HANDOFF"].corpo
    assert estado["node"] == "T_HANDOFF"
    assert "sem resposta a botões" in turno.registro["notas"][-1]


@pytest.mark.asyncio
async def test_ruido_na_vitrine_reoferece_so_os_botoes_de_acao_com_o_nudge(turno):
    turno.conversa["flow_state"] = _no(None, "VA", ramo="atacado")
    await turno("bom dia")
    p = turno.provedor
    assert p.tipos() == ["botoes"]
    assert p.chamadas[0][1] == r2.CORPO_NUDGE
    assert [b[0] for b in p.chamadas[0][2]] == ["pedido", "provar", "duvida"]


@pytest.mark.asyncio
async def test_classificador_recebe_cards_faqs_do_ramo_e_ultima_mensagem(turno):
    await turno(PRONTA_ATACADO)
    await turno("qual o mínimo?")
    kw = turno.classificar.await_args.kwargs
    assert kw["no_id"] == "VA" and kw["ramo"] == "atacado"
    ids = [b[0] for b in kw["botoes"]]
    assert ids == ["pedido", "provar", "duvida", "card:classico", "card:suave", "card:microlote"]
    assert ("card:classico", "Quero esse — Clássico") in kw["botoes"]
    assert set(kw["faqs"]) == set(r2.FAQ["atacado"]) | {"preco"}
    assert kw["ultima_mensagem"] == r2.CORPO_ACOES
    assert kw["lead_id"] == "L1"


@pytest.mark.asyncio
async def test_faq_de_preco_reenvia_tabela_e_acoes(turno):
    turno.conversa["flow_state"] = _no(None, "QA2", ramo="atacado")
    turno.classificar.return_value = Classificacao("FAQ", faq_id="preco")
    estado = await turno("qual o valor do quilo?")
    p = turno.provedor
    assert p.tipos() == ["texto", "botoes"]
    assert p.chamadas[0][1].startswith("tabela atacado")
    assert p.chamadas[1][1] == r2.CORPO_ACOES
    assert estado["node"] == "VA"


@pytest.mark.asyncio
async def test_faq_com_preco_resolve_do_catalogo_e_nunca_vaza_marcador(turno):
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    turno.classificar.return_value = Classificacao("FAQ", faq_id="capsula")
    await turno("tem cápsula?")
    texto = turno.provedor.chamadas[0][1]
    assert "R$ 22,90" in texto and "R$ 24,90" in texto and "{preco" not in texto

    turno.catalogo["linhas"] = [p for p in catalogo_producao() if "Drip" not in p["name"]]
    await turno("e o drip?")
    texto = turno.provedor.chamadas[2][1]
    assert "sob consulta" in texto and "{preco" not in texto


@pytest.mark.asyncio
async def test_clique_nao_chama_o_classificador(turno):
    turno.conversa["flow_state"] = _no(None, "VA", ramo="atacado")
    estado = await turno("Quero esse", payload="card:suave", titulo="Quero esse")
    turno.classificar.assert_not_called()
    assert estado["node"] == "QA1" and estado["interesse"] == "suave"
    assert turno.registro["score"][0]["updates"] == {"purchase_intent": "clear"}


@pytest.mark.asyncio
async def test_fluxo_pl_ate_o_handoff_com_a_nota(turno):
    await turno(PRONTA_PL)
    await turno("Fazer orçamento", payload="orcamento", titulo="Fazer orçamento")
    await turno("Já tenho a marca", payload="tenho_marca", titulo="Já tenho a marca")
    turno.classificar.return_value = Classificacao("BOTAO", botao_id="de100a500")
    estado = await turno("uns 300 pacotes")
    assert estado["node"] == "T_HANDOFF_PL"
    assert turno.provedor.chamadas[-2][1] == r2.TERMINAIS["T_HANDOFF_PL"].corpo
    assert turno.provedor.chamadas[-1][0] == "cartao"
    # A v2 escreve o resumo; a nota genérica da v1 ("Nenhuma qualificação") não sai.
    assert turno.registro["kw_efeitos"][-1]["nota_sem_qualificacao"] is False
    nota = turno.registro["notas"][-1]
    assert nota.splitlines() == [
        "[ValerIA botões v2] Marca própria",
        "Marca: Já tenho a marca · Quantidade: 100 a 500",
        "Viu: vitrine + como funciona",
        'Origem do repasse: escreveu "uns 300 pacotes"',
    ]


@pytest.mark.asyncio
async def test_nota_de_exportacao_tem_ramo_e_respostas(turno):
    turno.conversa["flow_state"] = _no(None, "E4", respostas={
        "N0": "exportacao", "E1": "europa", "E2": "cnpj_proprio", "E3": "revender"})
    estado = await turno("Sim, quero falar", payload="sim", titulo="Sim, quero falar")
    assert estado["node"] == "T_HANDOFF_ARTHUR"
    assert turno.provedor.tipos() == ["texto", "cartao"]
    assert turno.registro["notas"][-1].splitlines() == [
        "[ValerIA botões v2] Exportação",
        "Destino: Europa · Exporta por: Pelo meu CNPJ · Objetivo: Comprar e revender",
        'Origem do repasse: clicou "Sim, quero falar"',
    ]


def test_nota_sem_ramo_diz_ramo_nao_escolhido():
    nota = v2.montar_nota({"node": "T_HANDOFF"}, r2.NOS, textos=[], motivo="VENDEDOR: oi")
    assert nota.splitlines()[0] == "[ValerIA botões v2] ramo não escolhido"


# ═══════════════════════════════════════════════════════════════════════════
# Nenhum marcador cru chega ao lead
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_faq_editada_com_marcador_desconhecido_corta_a_linha(turno, monkeypatch):
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {
        "faq:atacado:frete": {"corpo": "Frete pro {cidade}\nGrátis acima de R$2.000."}})
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    turno.classificar.return_value = Classificacao("FAQ", faq_id="frete")
    await turno("e o frete?")
    assert turno.provedor.chamadas[0][1] == "Grátis acima de R$2.000."


@pytest.mark.asyncio
async def test_nudge_editado_com_marcador_na_vitrine_nao_vaza(turno, monkeypatch):
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {
        r2.CHAVE_NUDGE: {"corpo": "oi {nome}!\npra seguir, toca aqui 👇"}})
    turno.conversa["flow_state"] = _no(None, "VA", ramo="atacado")
    await turno("bom dia")
    assert turno.provedor.chamadas[0][1] == "pra seguir, toca aqui 👇"


@pytest.mark.asyncio
async def test_frase_exata_de_saida_nao_gasta_llm(turno):
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    estado = await turno("para")
    turno.classificar.assert_not_called()
    assert estado["node"] == "T_OPTOUT"


# ═══════════════════════════════════════════════════════════════════════════
# Guardas
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["T_HUMANO", "T_FIM"])
async def test_lead_encerrado_na_v1_nao_recomeca_na_v2(turno, terminal):
    """Na v1 esses leads estão em silêncio para sempre; a troca de perfil não os reabre."""
    turno.conversa["flow_state"] = {"flow": "valeria_botoes_v1", "node": terminal, "nudges": 3}
    estado = await turno("oi, ainda tem café?")
    assert turno.motivo is None
    assert turno.provedor.chamadas == []
    assert turno.registro["efeitos"] == []
    assert turno.registro["gravacoes"] == []
    turno.classificar.assert_not_called()
    assert estado == {"flow": "valeria_botoes_v1", "node": terminal, "nudges": 3}


@pytest.mark.asyncio
async def test_lead_encerrado_na_v1_que_pede_para_sair_e_honrado(turno):
    """O opt-out vence o encerramento — na v1 também (Meta/LGPD)."""
    turno.conversa["flow_state"] = {"flow": "valeria_botoes_v1", "node": "T_FIM", "nudges": 0}
    estado = await turno("pare")
    assert estado["node"] == "T_OPTOUT" and estado["flow"] == r2.FLOW_ID
    assert turno.registro["efeitos"][0].optout is True


@pytest.mark.asyncio
@pytest.mark.parametrize("estado_v1", [
    {"flow": "valeria_botoes_v1", "node": "N1", "nudges": 0},
    {"flow": "valeria_botoes_v1", "node": "T_ADIADO", "nudges": 0},
    {"flow": "recuperacao_v1", "node": "aguardando_prazo"},
])
async def test_outros_estados_alheios_recomecam_como_primeiro_contato(turno, estado_v1):
    turno.conversa["flow_state"] = dict(estado_v1)
    estado = await turno("oi")
    assert turno.provedor.tipos() == ["lista"]
    assert estado["node"] == "N0" and estado["flow"] == r2.FLOW_ID
@pytest.mark.asyncio
async def test_kill_switch_desligado_nao_faz_nada(turno, monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "off")
    estado = await turno(PRONTA_ATACADO)
    assert turno.provedor.chamadas == []
    assert estado is None
    assert turno.registro["gravacoes"] == []


@pytest.mark.asyncio
async def test_human_control_devolve_o_motivo_da_v1(turno):
    turno.lead["human_control"] = True
    turno.conversa["flow_state"] = _no(None, "QA1", ramo="atacado")
    await turno("oi?")
    assert turno.motivo == irmao.MOTIVO_HANDOFF_FORMAL
    assert turno.provedor.chamadas == []
    turno.classificar.assert_not_called()
    assert turno.conversa["flow_state"]["notificado_humano"] is True
    assert turno.conversa["flow_state"]["flow"] == r2.FLOW_ID


@pytest.mark.asyncio
async def test_human_control_sem_estado_carimba_a_v2_e_nao_a_v1(turno):
    turno.lead["human_control"] = True
    await turno("oi")
    assert turno.conversa["flow_state"]["flow"] == r2.FLOW_ID


@pytest.mark.asyncio
async def test_sem_kwargs_nao_levanta():
    assert await v2.processar_inbound(lead={}, conversation={}) is None


def test_proximo_estado_mescla_respostas_e_acumula_faqs():
    from app.button_flow.valeria_engine_v2 import DecisaoV2
    estado = {"flow": r2.FLOW_ID, "node": "QA1", "nudges": 1, "respostas": {"QA1": "x"},
              "faqs": ["grao"], "notificado_humano": True}
    novo = v2.proximo_estado_v2(estado, DecisaoV2(
        proximo_no="QA2", memoria={"respostas": {"QA2": "ate30"}, "ruidos": 0}, faq="frete"))
    assert novo["respostas"] == {"QA1": "x", "QA2": "ate30"}
    assert novo["faqs"] == ["grao", "frete"]
    assert novo["node"] == "QA2" and novo["nudges"] == 1 and novo["ruidos"] == 0
    assert novo["notificado_humano"] is True
    assert estado["faqs"] == ["grao"], "mutou o estado de entrada"


# ═══════════════════════════════════════════════════════════════════════════
# Repasse automático de parados (spec §8)
# ═══════════════════════════════════════════════════════════════════════════
class _ConsultaFalsa:
    def __init__(self, banco):
        self.banco = banco
        self.filtros = []

    def update(self, dados):
        self.banco["updates"].append(dados)
        return self

    def eq(self, coluna, valor):
        self.filtros.append(("eq", coluna, valor))
        return self

    def is_(self, coluna, valor):
        self.filtros.append(("is", coluna, valor))
        return self

    def execute(self):
        self.banco["filtros"].append(self.filtros)
        return type("R", (), {"data": [{"id": "C1"}] if self.banco["ganha"] else []})()


class _SupabaseFalso:
    def __init__(self, ganha):
        self.banco = {"ganha": ganha, "updates": [], "filtros": []}

    def table(self, nome):
        assert nome == "conversations"
        return _ConsultaFalsa(self.banco)


@pytest.mark.asyncio
async def test_repassar_parado_ganha_a_trava_e_repassa(turno, monkeypatch):
    sb = _SupabaseFalso(ganha=True)
    monkeypatch.setattr(v2, "get_supabase", lambda: sb)
    turno.conversa["flow_state"] = _no(None, "QA2", ramo="atacado",
                                       respostas={"QA1": "loja"})
    ganhou = await v2.repassar_parado(
        lead=turno.lead, conversation=turno.conversa, channel={"mode": "ai"},
        provider=turno.provedor, horas=2.4)
    assert ganhou is True
    filtros = sb.banco["filtros"][0]
    assert ("eq", "id", "C1") in filtros
    assert ("eq", "flow_state->>node", "QA2") in filtros
    assert ("is", "flow_state->>repasse_auto", "null") in filtros
    assert sb.banco["updates"][0]["flow_state"]["repasse_auto"]

    p = turno.provedor
    assert p.tipos() == ["texto", "cartao"]
    assert p.chamadas[0][1] == "vou deixar o João te chamando por aqui pra seguir com você 🙂"
    assert turno.registro["efeitos"][0].handoff is True
    assert turno.registro["kw_efeitos"][0]["nota_sem_qualificacao"] is False
    nota = turno.registro["notas"][-1]
    assert "Negócio: Loja ou empório" in nota
    assert "Origem do repasse: automático — parado há 2h em QA2" in nota
    assert turno.conversa["flow_state"]["node"] == "T_HANDOFF"
    assert turno.conversa["flow_state"]["repasse_auto"]


@pytest.mark.asyncio
async def test_repassar_parado_so_roda_se_a_conversa_ainda_e_da_v2(turno, monkeypatch):
    sb = _SupabaseFalso(ganha=True)
    monkeypatch.setattr(v2, "get_supabase", lambda: sb)
    monkeypatch.setattr(irmao, "fluxo_efetivo", lambda _c, _ch: "valeria_botoes_v1")
    turno.conversa["flow_state"] = _no(None, "QA2", ramo="atacado")
    ganhou = await v2.repassar_parado(
        lead=turno.lead, conversation=turno.conversa, channel={"mode": "ai"},
        provider=turno.provedor, horas=3)
    assert ganhou is False
    assert sb.banco["updates"] == []
    assert turno.provedor.chamadas == []
    assert turno.registro["efeitos"] == []


@pytest.mark.asyncio
async def test_repassar_parado_perde_a_trava_e_nao_faz_nada(turno, monkeypatch):
    sb = _SupabaseFalso(ganha=False)
    monkeypatch.setattr(v2, "get_supabase", lambda: sb)
    turno.conversa["flow_state"] = _no(None, "QP1", ramo="private_label")
    ganhou = await v2.repassar_parado(
        lead=turno.lead, conversation=turno.conversa, channel={"mode": "ai"},
        provider=turno.provedor, horas=3)
    assert ganhou is False
    assert turno.provedor.chamadas == []
    assert turno.registro["efeitos"] == []
    assert turno.registro["notas"] == []
    assert turno.registro["gravacoes"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("guarda", ["kill_switch", "human_control", "blacklist", "card_movido"])
async def test_repassar_parado_respeita_as_guardas_do_turno(turno, monkeypatch, guarda):
    sb = _SupabaseFalso(ganha=True)
    monkeypatch.setattr(v2, "get_supabase", lambda: sb)
    turno.conversa["flow_state"] = _no(None, "QA2", ramo="atacado", deal_stage_id="S1")
    if guarda == "kill_switch":
        monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "off")
    elif guarda == "human_control":
        turno.lead["human_control"] = True
    elif guarda == "blacklist":
        monkeypatch.setattr(irmao, "is_lead_blacklisted", lambda _l: True)
    else:
        monkeypatch.setattr(v1, "get_open_deal", lambda _l: {"stage_id": "S2"})
    ganhou = await v2.repassar_parado(
        lead=turno.lead, conversation=turno.conversa, channel={"mode": "ai"},
        provider=turno.provedor, horas=3)
    assert ganhou is False
    assert sb.banco["updates"] == [], "pegou a trava apesar da guarda"
    assert turno.provedor.chamadas == []
    assert turno.registro["efeitos"] == []


@pytest.mark.asyncio
async def test_repassar_parado_com_banco_fora_nao_levanta(turno, monkeypatch):
    def explode():
        raise RuntimeError("PostgREST fora")
    monkeypatch.setattr(v2, "get_supabase", explode)
    turno.conversa["flow_state"] = _no(None, "VK", ramo="atacado")
    ganhou = await v2.repassar_parado(
        lead=turno.lead, conversation=turno.conversa, channel={"mode": "ai"},
        provider=turno.provedor, horas=5)
    assert ganhou is False
    assert turno.provedor.chamadas == []


# ═══════════════════════════════════════════════════════════════════════════
# A nota genérica da v1 no `effects` (follow-up do Task 8)
# ═══════════════════════════════════════════════════════════════════════════
def test_effects_sem_a_nota_generica_quando_a_v2_pede():
    """A v2 grava o resumo de verdade; "Nenhuma qualificação" o contradiria."""
    from app.button_flow.engine import Efeitos
    from tests.test_button_flow_effects_2026_08_20 import _crm_mockado

    terminal = r2.TERMINAIS["T_HANDOFF"]
    with _crm_mockado(deal=None) as crm:
        ok = effects.aplicar(
            Efeitos(tags=terminal.tags, handoff=True, silenciar_ia=True,
                    vendedor=terminal.vendedor),
            lead={"id": "lead-1", "metadata": {}}, conversation_id="c1",
            fluxo=effects.FLUXO_VALERIA, nota_sem_qualificacao=False,
        )
    assert ok is True
    notas = [c.args[1] for c in crm.obs.call_args_list]
    assert len(notas) == 1
    assert "[TRANSBORDO p/ " in notas[0]
    assert notas[0].endswith(f"{effects.FLUXO_VALERIA}: lead pediu atendimento do vendedor.")
    assert "Nenhuma qualificação" not in notas[0]
