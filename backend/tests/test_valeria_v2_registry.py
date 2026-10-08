"""O registry da v2 é o contrato entre a tela, o motor v2 e o runner v2.

Mesmo papel de tests/test_valeria_registry_2026_09_29.py para a v1: cruza a
declaração com as regras que a Meta impõe (rótulo ≤ 20, lista ≤ 10, card ≤ 160
caracteres e ≤ 2 quebras), com a topologia (todo destino existe, todo nó é
alcançável) e com os fatos de negócio da spec §4 (nenhum número pendente).

O limite do card é medido DEPOIS de resolver `{preco:...}` contra o catálogo de
produção (as 32 linhas ativas copiadas da Task 2), porque é o texto resolvido
que a Meta recebe — e é ele que ela recusa acima de 160.
"""
import re
from pathlib import Path

from app.button_flow import valeria_registry as v1, valeria_registry_v2 as r
from app.button_flow.engine import normalizar
from app.lead_score.model import CRITERIA_FIELDS

# ── Catálogo de produção (spec §4 / `products`), o mesmo fixture da Task 2 ───
ATACADO = [
 ("Canastra Canela — Moído 250g","R$ 28,70"),("Canastra Clássico — Em Grãos 1kg","R$ 97,70"),
 ("Canastra Clássico — Em Grãos 250g","R$ 31,70"),("Canastra Clássico — Em Grãos 500g","R$ 54,70"),
 ("Canastra Clássico — Moído 250g","R$ 28,70"),("Canastra Clássico — Moído 500g","R$ 52,70"),
 ("Canastra Suave — Em Grãos 1kg","R$ 97,70"),("Canastra Suave — Em Grãos 250g","R$ 31,70"),
 ("Canastra Suave — Em Grãos 500g","R$ 54,70"),("Canastra Suave — Moído 250g","R$ 28,70"),
 ("Canastra Suave — Moído 500g","R$ 52,70"),("Cápsula Canastra Canela — Display 10 cápsulas","R$ 22,90"),
 ("Cápsula Canastra Clássico — Display 10 cápsulas","R$ 22,90"),("Drip Coffee Canastra Suave — Display 10 sachês","R$ 24,90"),
 ("Granel Canastra Clássico — 2kg em grãos","R$ 169,70"),("Granel Canastra Suave — 2kg em grãos","R$ 169,70"),
 ("Granel Néctar de Minas Espresso — 2kg em grãos","R$ 166,70"),("Granel Néctar de Minas Intenso — 2kg em grãos","R$ 166,70"),
 ("Microlote — Em Grãos 250g","R$ 32,70"),("Microlote — Moído 250g","R$ 32,70"),
 ("Moedor + 10 pacotes granel","R$ 599,00"),("Moedor Elétrico Profissional — Unitário","R$ 949,00"),
 ("Néctar de Minas Blend Arábica+Robusta — Em Grãos 1kg","R$ 79,70"),("Néctar de Minas Gourmet — Em Grãos 1kg","R$ 88,70"),
 ("Néctar de Minas Gourmet — Kit 10un 500g","R$ 357,00"),("Néctar de Minas Gourmet — Moído 500g","R$ 39,70"),
]
PL = [("Café Canastra 250g — c/ embalagem Canastra","R$ 26,70","100 un"),("Café Canastra 250g — embalagem do cliente","R$ 25,70","100 un"),
      ("Café Canastra 500g — c/ embalagem Canastra","R$ 48,70","100 un"),("Café Canastra 500g — embalagem do cliente","R$ 47,70","100 un"),
      ("Microlote 250g — c/ embalagem Canastra","R$ 29,70","100 un"),("Microlote 250g — embalagem do cliente","R$ 27,70","50 un")]

PRECOS = {
    "atacado": dict(ATACADO),
    "private_label": {n: p for n, p, _m in PL},
}
# Preço "pior caso" de largura: o card não pode estourar 160 só porque o preço
# subiu de R$ 97,70 para R$ 197,70. Cada preço vira um de 9 caracteres.
PRECO_LARGO = "R$ 999,90"

_MARCADOR = re.compile(r"\{preco:([^}]*)\}")


def _resolver(texto: str, precos: dict[str, str]) -> str:
    return _MARCADOR.sub(lambda m: precos[m.group(1)], texto)


def _todos_botoes():
    for no in r.NOS.values():
        yield no, no.botoes


# ── Limites da Meta ─────────────────────────────────────────────────────────

def test_rotulos_cabem_no_whatsapp():
    for no, bs in _todos_botoes():
        lim = v1.LIMITE_TITULO_LISTA if no.tela == "lista" else v1.LIMITE_ROTULO_BOTAO
        for b in bs: assert len(b.rotulo) <= lim, (no.id, b.id)
        if no.tela == "lista": assert len(bs) <= v1.MAX_LINHAS_LISTA
        else: assert len(bs) <= v1.MAX_BOTOES
        for c in no.cards: assert len(c.rotulo_botao) <= v1.LIMITE_ROTULO_BOTAO


def test_descricao_de_linha_de_lista_cabe():
    for no, bs in _todos_botoes():
        for b in bs:
            assert len(b.descricao) <= v1.LIMITE_DESC_LISTA, (no.id, b.id)


def test_ids_de_botao_e_de_card_unicos_dentro_do_no():
    for no in r.NOS.values():
        ids = [b.id for b in no.botoes] + [f"card:{c.id}" for c in no.cards]
        assert len(ids) == len(set(ids)), (no.id, ids)


def test_grava_usa_campo_valido_do_score():
    for no, bs in _todos_botoes():
        for b in bs:
            for campo, _v in b.grava:
                assert campo in CRITERIA_FIELDS, (no.id, b.id, campo)


def test_corpo_nunca_vazio():
    for no in r.NOS.values():
        assert no.corpo.strip(), no.id


# ── Topologia ───────────────────────────────────────────────────────────────

def test_todo_destino_existe():
    especiais = {"tabela", "handoff", "regra:QP2"}
    for no, bs in _todos_botoes():
        for b in bs:
            d = b.destino
            assert d in r.NOS or d in r.TERMINAIS or d in especiais or d.startswith("faq:"), (no.id, b.id, d)
            if d.startswith("faq:"):
                ramo = r.RAMO_DO_NO[no.id]; assert d[4:] in r.FAQ[ramo]
        for c in no.cards: assert c.destino in r.NOS


def test_regra_qp2_cobre_criar_zero_menos_100():
    assert r.REGRA_QP2[("criar_zero", "menos100")] == "PL_ABAIXO"
    assert all(d in r.NOS or d in r.TERMINAIS for d in r.REGRA_QP2.values())


def test_regra_qp2_so_manda_criar_zero_menos_100_para_baixo():
    """Spec §5.2: é a ÚNICA combinação que não repassa; o resto vai ao João."""
    qp1 = {b.id for b in r.NOS["QP1"].botoes if b.destino == "QP2"}
    qp2 = {b.id for b in r.NOS["QP2"].botoes}
    for chave, destino in r.REGRA_QP2.items():
        assert chave[0] in qp1 and chave[1] in qp2, chave
        esperado = "PL_ABAIXO" if chave == ("criar_zero", "menos100") else "T_HANDOFF_PL"
        assert destino == esperado, chave
    assert all(b.destino == "regra:QP2" for b in r.NOS["QP2"].botoes)


def test_mensagens_prontas_do_anuncio():
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Tenho um comércio e quero revender café especial.")] == "VA"
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Quero saber mais sobre compra por atacado.")] == "VA"
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Quero café com a minha marca — já tenho CNPJ")] == "VP"
    assert r.MENSAGENS_PRONTAS[normalizar("Olá! Quero saber mais sobre ter a Marca Própria de Café.")] == "VP"
    assert len(r.MENSAGENS_PRONTAS) == 4
    assert normalizar("oi") not in r.MENSAGENS_PRONTAS


def test_todo_no_alcancavel_a_partir_de_n0_ou_mensagem_pronta():
    vistos, fila = set(), ["N0", "VA", "VP"]
    while fila:
        n = fila.pop()
        if n in vistos or n not in r.NOS: continue
        vistos.add(n)
        for b in r.NOS[n].botoes:
            if b.destino in r.NOS: fila.append(b.destino)
        for c in r.NOS[n].cards: fila.append(c.destino)
        if any(b.destino == "regra:QP2" for b in r.NOS[n].botoes): fila.extend(r.REGRA_QP2.values())
    assert set(r.NOS) - vistos == set()


def test_conjunto_de_nos_e_terminais_do_contrato():
    assert r.FLOW_ID == "valeria_botoes_v2" and r.NO_ENTRADA == "N0"
    assert set(r.NOS) == {"N0", "VA", "VP", "QA1", "QA2", "QP1", "QP2", "PL_ABAIXO", "VK",
                          "VD_A", "VD_P", "VO", "C1", "E1", "E2", "E3", "E4"}
    assert set(r.TERMINAIS) == {"T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR", "T_KIT",
                                "T_ADIAR", "T_ADIADO", "T_HUMANO", "T_FIM", "T_OPTOUT"}
    assert set(r.RAMO_DO_NO) == set(r.NOS)
    assert all(r.RAMO_DO_NO[i] == no.ramo for i, no in r.NOS.items())
    assert r.HANDOFF_DO_RAMO == {"atacado": "T_HANDOFF", "private_label": "T_HANDOFF_PL",
                                 "exportacao": "T_HANDOFF_ARTHUR"}
    assert r.VITRINE_DO_RAMO == {"atacado": "VA", "private_label": "VP"}
    assert r.DUVIDAS_DO_RAMO == {"atacado": "VD_A", "private_label": "VD_P"}
    assert r.NOS_COM_INTENCAO == frozenset({"QA1", "QA2", "QP1", "QP2", "VK"})
    assert r.TETO_RUIDO == 2


def test_botoes_de_acao_das_vitrines():
    va = {b.id: b.destino for b in r.NOS["VA"].botoes}
    vp = {b.id: b.destino for b in r.NOS["VP"].botoes}
    assert va == {"pedido": "QA1", "provar": "VK", "duvida": "VD_A"}
    assert vp == {"orcamento": "QP1", "provar": "VK", "duvida": "VD_P"}
    pedido = {b.id: b for b in r.NOS["VA"].botoes}["pedido"]
    assert ("purchase_intent", "clear") in pedido.grava
    assert all(c.destino == "QA1" for c in r.NOS["VA"].cards)
    assert all(c.destino == "QP1" for c in r.NOS["VP"].cards)
    assert r.RAMO_DO_NO["VA"] == "atacado" and r.RAMO_DO_NO["VP"] == "private_label"


def test_qa1_qa2_repetem_ids_e_grava_da_v1():
    for v2, v1id in (("QA1", "N1"), ("QA2", "N2")):
        a = [(b.id, b.grava) for b in r.NOS[v2].botoes]
        b = [(b.id, b.grava) for b in v1.NOS[v1id].botoes]
        assert a == b, v2
    assert {b.destino for b in r.NOS["QA1"].botoes} == {"QA2"}
    assert {b.destino for b in r.NOS["QA2"].botoes} == {"T_HANDOFF"}


def test_qp1_vk_pl_abaixo_destinos():
    assert {b.id: b.destino for b in r.NOS["QP1"].botoes} == {
        "tenho_marca": "QP2", "criar_zero": "QP2", "tenho_graos": "T_HANDOFF_PL"}
    assert {b.id: b.destino for b in r.NOS["VK"].botoes} == {
        "quero_kit": "T_KIT", "ver_precos": "tabela", "vendedor": "handoff"}
    assert {b.id: b.destino for b in r.NOS["PL_ABAIXO"].botoes} == {
        "quero_kit": "T_KIT", "depois": "T_ADIAR"}


def test_listas_de_duvidas_por_ramo():
    def linhas(no_id):
        return {b.id: b.destino for b in r.NOS[no_id].botoes}
    a, p = linhas("VD_A"), linhas("VD_P")
    assert r.NOS["VD_A"].tela == "lista" and r.NOS["VD_P"].tela == "lista"
    assert a["faq_outra"] == "VO" and p["faq_outra"] == "VO"
    assert a["faq_vendedor"] == "T_HANDOFF" and p["faq_vendedor"] == "T_HANDOFF_PL"
    assert {d[4:] for d in a.values() if d.startswith("faq:")} == set(r.FAQ["atacado"])
    assert {d[4:] for d in p.values() if d.startswith("faq:")} == set(r.FAQ["private_label"])
    for linhas_, ramo in ((a, "atacado"), (p, "private_label")):
        for bid, d in linhas_.items():
            if d.startswith("faq:"):
                assert bid == "faq_" + d[4:], bid
    assert set(r.FAQ["atacado"]) == {"grao", "minimo", "frete", "pagamento", "revenda", "capsula"}
    assert set(r.FAQ["private_label"]) == {"grao", "minimo", "frete", "pagamento", "revenda",
                                           "prazo_pl", "fotolito"}
    assert r.NOS["VO"].botoes == () and r.NOS["VO"].corpo == "pode escrever sua pergunta 🙂"


def test_faq_descricao_cobre_todo_faq_e_preco():
    todos = set(r.FAQ["atacado"]) | set(r.FAQ["private_label"])
    assert todos | {"preco"} == set(r.FAQ_DESCRICAO)
    assert all(d.strip() and "\n" not in d for d in r.FAQ_DESCRICAO.values())


def test_c1_e_exportacao_copiados_da_v1():
    c1 = {b.id: b for b in r.NOS["C1"].botoes}
    assert c1["quantidade"].destino == "VA"
    assert c1["duvida"] == {b.id: b for b in v1.NOS["C1"].botoes}["duvida"]
    assert r.NOS["C1"].corpo == v1.NOS["C1"].corpo
    for e in ("E1", "E2", "E3", "E4"):
        assert r.NOS[e] == v1.NOS[e], e
    n0 = {b.id: b.destino for b in r.NOS["N0"].botoes}
    assert n0 == {"negocio": "VA", "marca": "VP", "consumo": "C1", "exportacao": "E1"}


def test_terminais_reusam_os_da_v1_e_t_kit():
    for tid in ("T_HANDOFF", "T_HANDOFF_PL", "T_HANDOFF_ARTHUR", "T_ADIAR", "T_ADIADO",
                "T_HUMANO", "T_FIM", "T_OPTOUT"):
        assert r.TERMINAIS[tid] is v1.TERMINAIS[tid], tid
    kit = r.TERMINAIS["T_KIT"]
    assert kit.vendedor == v1.VENDEDOR_ATACADO and kit.handoff and kit.silenciar_ia
    assert kit.tags == (v1.TAG_QUALIFICADO, "Botões: Kit amostra") and r.TAG_KIT == "Botões: Kit amostra"
    assert "R$" not in kit.corpo


def test_tipos_e_folha_de_prazos_sao_os_da_v1():
    assert r.No is v1.No and r.Botao is v1.Botao and r.Terminal is v1.Terminal and r.Card is v1.Card
    assert r.BOTOES_PRAZO is v1.BOTOES_PRAZO and r.DIAS_POR_PRAZO is v1.DIAS_POR_PRAZO


def test_no_da_v1_continua_sem_cards():
    assert all(no.cards == () for no in v1.NOS.values())


# ── Vitrine ─────────────────────────────────────────────────────────────────

def test_vitrines_tem_cards_com_fotos_existentes_e_mesmo_numero_de_botoes():
    fotos = Path(v1.__file__).parent.parent / "photos"
    for vid in ("VA", "VP"):
        no = r.NOS[vid]; assert no.tela == "carrossel" and len(no.cards) >= 2
        for c in no.cards: assert (fotos / c.foto).exists(), c.foto
        assert len(no.corpo) <= 1024


def test_cards_e_fotos_do_contrato():
    va = {c.id: c for c in r.NOS["VA"].cards}
    vp = {c.id: c for c in r.NOS["VP"].cards}
    assert list(va) == ["classico", "suave", "microlote"]
    assert list(vp) == ["embalagem_canastra", "embalagem_cliente", "microlote"]
    assert va["classico"].foto == "atacado/foto_1_classico.jpg"
    assert va["suave"].foto == "atacado/foto_2_suave.jpg"
    assert va["microlote"].foto == "atacado/foto_4_microlote.png"
    assert vp["embalagem_canastra"].foto == "private_label/foto_3.jpg"
    assert vp["embalagem_cliente"].foto == "private_label/foto_1.jpg"
    assert vp["microlote"].foto == "private_label/foto_4.jpg"
    assert len(va["classico"].skus) == 5 and len(va["suave"].skus) == 5
    assert all("Clássico" in s for s in va["classico"].skus)
    assert all("Suave" in s for s in va["suave"].skus)
    assert set(va["microlote"].skus) == {"Microlote — Moído 250g", "Microlote — Em Grãos 250g"}


def test_microlote_pl_exige_min_lot_100():
    c = {c.id: c for c in r.NOS["VP"].cards}["microlote"]
    assert c.exige_min_lot == "100 un"
    assert set(c.skus) == {"Microlote 250g — c/ embalagem Canastra", "Microlote 250g — embalagem do cliente"}


def test_marcadores_de_preco_citam_sku_do_card_e_existem_no_catalogo():
    """Nome de produto com um travessão errado = card que nunca sai, em silêncio."""
    for vid in ("VA", "VP"):
        ramo = r.RAMO_DO_NO[vid]
        for c in r.NOS[vid].cards:
            marcados = _MARCADOR.findall(c.corpo)
            assert marcados, c.id
            assert set(marcados) <= set(c.skus), (c.id, set(marcados) - set(c.skus))
            for s in c.skus:
                assert s in PRECOS[ramo], (c.id, s)


def test_cards_cabem_em_160_e_2_quebras_depois_de_resolver_preco():
    """Spec §11: medido no texto RESOLVIDO, com o catálogo de produção e com folga."""
    for vid in ("VA", "VP"):
        ramo = r.RAMO_DO_NO[vid]
        for c in r.NOS[vid].cards:
            for precos in (PRECOS[ramo], {k: PRECO_LARGO for k in PRECOS[ramo]}):
                txt = _resolver(c.corpo, precos)
                assert len(txt) <= 160, (c.id, len(txt), txt)
                assert txt.count("\n") <= 2, (c.id, txt)
                assert "{" not in txt and "}" not in txt, (c.id, txt)


def test_faq_capsula_cita_produtos_do_catalogo():
    marcados = _MARCADOR.findall(r.FAQ["atacado"]["capsula"])
    assert len(marcados) == 2 and all(m in PRECOS["atacado"] for m in marcados)
    for ramo, faqs in r.FAQ.items():
        for fid, txt in faqs.items():
            if fid != "capsula":
                assert "{preco" not in txt, (ramo, fid)


# ── Fatos de negócio (spec §4) ──────────────────────────────────────────────

def test_nenhum_numero_pendente_no_texto():
    # Kit e Microlote PL estão pendentes (spec §4): nenhum "R$" no VK nem no card do microlote PL sem marcador
    assert "R$" not in r.NOS["VK"].corpo
    for c in r.NOS["VP"].cards:
        assert "R$" not in c.corpo   # preço só por {preco:...}
    for c in r.NOS["VA"].cards:
        assert "R$" not in c.corpo
    assert "R$" not in r.NOS["PL_ABAIXO"].corpo


def test_fatos_confirmados_estao_nos_textos():
    assert "R$500" in r.REGRAS_ATACADO_DEFAULT and "R$2.000" in r.REGRAS_ATACADO_DEFAULT
    assert "15 dias úteis" in r.COMO_FUNCIONA_PL_DEFAULT and "R$100" in r.COMO_FUNCIONA_PL_DEFAULT
    assert "{total_pl}" in r.COMO_FUNCIONA_PL_DEFAULT
    assert r.FAQ["atacado"]["minimo"].count("R$500") == 1


def test_regras_atacado_sao_as_4_linhas():
    linhas = r.REGRAS_ATACADO_DEFAULT.split("\n")
    assert [l[0] for l in linhas] == ["✅", "🚚", "💳", "💰"]


def test_textos_editaveis_reservados():
    assert r.CHAVE_NUDGE == v1.CHAVE_NUDGE and r.CORPO_NUDGE == v1.CORPO_NUDGE
    assert r.CHAVE_REGRAS_ATACADO == "__regras_atacado__"
    assert r.CHAVE_COMO_FUNCIONA_PL == "__como_funciona_pl__"
    faqs = {f"faq:{ramo}:{fid}" for ramo, fs in r.FAQ.items() for fid in fs}
    assert r.CHAVES_TEXTO == frozenset(
        {r.CHAVE_NUDGE, v1.CHAVE_ROTULO_LISTA, r.CHAVE_REGRAS_ATACADO, r.CHAVE_COMO_FUNCIONA_PL} | faqs)
    assert not (r.CHAVES_TEXTO & set(r.NOS)) and not (r.CHAVES_TEXTO & set(r.TERMINAIS))
    assert r.CORPO_ACOES == "como você quer seguir?"
