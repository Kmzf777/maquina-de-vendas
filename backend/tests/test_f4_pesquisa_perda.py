"""Frente F4: pesquisa de perda do atacado — mapeamento botão → motivo, sem ligação a fluxo."""
from __future__ import annotations

import pathlib
from unittest.mock import MagicMock

import pytest

from app.button_flow import pesquisa_perda as pp
from app.leads import motivo_perda as mp

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
SQL = (pathlib.Path(__file__).resolve().parents[1]
       / "scripts/pesquisa_perda/atacados_sem_compra_60d.sql").read_text(encoding="utf-8")


def test_nao_esta_ligado_a_nenhum_fluxo():
    quem_importa = [
        p.relative_to(APP).as_posix() for p in APP.rglob("*.py")
        if p.name != "pesquisa_perda.py" and "pesquisa_perda" in p.read_text(encoding="utf-8")
    ]
    assert quem_importa == []


def test_todo_codigo_do_mapeamento_esta_no_vocabulario():
    for opcoes in pp.REGISTRO.values():
        for o in opcoes:
            assert o.codigo is None or o.codigo in mp.CODIGOS, o


def test_os_sete_botoes_do_relatorio_cobrem_os_motivos_que_o_lead_sabe_dizer():
    assert [o.codigo for o in pp.BOTOES_MOTIVO] == [
        "preco_margem", "frete", "pedido_minimo", "condicao_bonificacao",
        "comprou_outro", "ainda_pesquisando", "consumidor_final"]


def test_rotulos_cabem_nos_limites_do_whatsapp():
    # template: 25; interativa com até 3 botões: 20; lista (4+): 24
    for o in pp.BOTOES_MOTIVO:
        assert len(o.titulo) <= 25, o.titulo
    for no, opcoes in pp.REGISTRO.items():
        if no == pp.NO_MOTIVO:
            continue
        teto = 20 if len(opcoes) <= 3 else 24
        for o in opcoes:
            assert len(o.titulo) <= teto, (no, o.titulo)


def test_ids_unicos_por_no():
    for opcoes in pp.REGISTRO.values():
        ids = [o.id for o in opcoes]
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize("entrada", [
    {"payload": "pesquisa_perda_v1|frete"},
    {"payload": "frete"},
    {"payload": "Frete"},
    {"payload": "xxx", "titulo": "frete"},
])
def test_casar_por_payload_id_ou_rotulo(entrada):
    assert pp.casar(pp.NO_MOTIVO, **entrada).id == "frete"


def test_payload_de_outro_fluxo_nao_casa_por_id():
    assert pp.casar(pp.NO_MOTIVO, "recuperacao_v1|frete") is None


def test_rotulo_sem_acento_casa():
    assert pp.casar(pp.NO_MOTIVO, "Preco nao fechou").codigo == "preco_margem"


@pytest.mark.parametrize("botao,no_seguinte,codigo", [
    ("comprou_outro", pp.NO_CONCORRENTE, "comprou_outro"),
    ("preco", pp.NO_PRECO, "preco_margem"),
    ("frete", pp.NO_AVISAR, "frete"),
    ("pedido_minimo", pp.NO_AVISAR, "pedido_minimo"),
    ("condicao", pp.NO_AVISAR, "condicao_bonificacao"),
    ("ainda_vendo", pp.NO_RECONTATO, "ainda_pesquisando"),
])
def test_primeiro_clique_grava_codigo_e_faz_a_segunda_pergunta(botao, no_seguinte, codigo):
    d = pp.decidir(pp.NO_MOTIVO, payload=botao)
    assert d.proximo_no == no_seguinte and d.codigo == codigo
    assert d.botoes == pp.REGISTRO[no_seguinte] and len(d.mensagens) == 1


def test_uso_proprio_encerra_com_loja_e_marca_consumidor_final():
    d = pp.decidir(pp.NO_MOTIVO, payload="uso_proprio", nome="Ana")
    assert d.proximo_no == pp.NO_ENCERRADO and d.codigo == "consumidor_final"
    assert d.marcar_consumidor_final and "loja.cafecanastra.com" in d.mensagens[0]
    assert d.mensagens[-1].startswith("Muito obrigado pela sinceridade, Ana.")


def test_concorrente_da_lista_grava_nome():
    d = pp.decidir(pp.NO_CONCORRENTE, payload="Orfeu")
    assert (d.codigo, d.concorrente, d.proximo_no) == ("comprou_outro", "Orfeu", pp.NO_ENCERRADO)


def test_concorrente_escrito_a_mao():
    d = pp.decidir(pp.NO_CONCORRENTE, payload="conc_outra")
    assert d.proximo_no == pp.NO_CONCORRENTE_TEXTO and d.concorrente is None
    d2 = pp.decidir(pp.NO_CONCORRENTE_TEXTO, texto="  Café   Três Corações ")
    assert (d2.codigo, d2.concorrente) == ("comprou_outro", "Café Três Corações")


def test_prefiro_nao_dizer_fica_sem_concorrente():
    d = pp.decidir(pp.NO_CONCORRENTE, payload="conc_nao_dizer")
    assert d.codigo == "comprou_outro" and d.concorrente is None and d.observacao


def test_recontato_e_avisar():
    assert pp.decidir(pp.NO_RECONTATO, payload="recontato_sim").recontato_dias == 15
    assert pp.decidir(pp.NO_RECONTATO, payload="recontato_nao").recontato_dias is None
    assert pp.decidir(pp.NO_AVISAR, payload="avisar_sim").avisar_se_mudar
    assert pp.decidir(pp.NO_AVISAR, payload="avisar_nao").codigo is None  # não sobrescreve o motivo


def test_texto_ou_clique_desconhecido_vai_ao_humano():
    assert pp.decidir(pp.NO_MOTIVO, payload="quanto custa o kg?").ao_humano
    assert pp.decidir(pp.NO_CONCORRENTE_TEXTO, texto="   ").ao_humano
    assert pp.decidir("no_que_nao_existe", payload="frete").ao_humano


def test_fechamento_sem_nome():
    d = pp.decidir(pp.NO_PRECO, payload="preco_ml_site")
    assert d.mensagens == ("Muito obrigado pela sinceridade. Qualquer coisa, é só chamar.",)


# ── aplicar (único I/O) ─────────────────────────────────────────────────────
def _sb():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"id": "d-recente"}]
    return sb


def test_aplicar_grava_codigo_concorrente_e_nota_no_card_da_lista():
    sb = _sb()
    d = pp.decidir(pp.NO_CONCORRENTE, payload="conc_orfeu")
    assert pp.aplicar("L1", d, deal_id="d-lista", sb=sb) == "d-lista"
    sb.table.return_value.update.assert_called_once_with(
        {"lost_reason_code": "comprou_outro", "lost_competitor": "Orfeu"})
    sb.table.return_value.update.return_value.eq.assert_called_once_with("id", "d-lista")
    nota = sb.table.return_value.insert.call_args.args[0]
    assert nota["lead_id"] == "L1" and "Orfeu" in nota["content"]


def test_aplicar_sem_deal_usa_o_mais_recente_e_nao_move_etapa():
    sb = _sb()
    pp.aplicar("L1", pp.decidir(pp.NO_MOTIVO, payload="frete"), sb=sb)
    up = sb.table.return_value.update.call_args.args[0]
    assert up == {"lost_reason_code": "frete", "lost_competitor": None}
    assert "stage_id" not in up and "closed_at" not in up


def test_aplicar_outra_marca_nao_apaga_nome_ja_gravado():
    sb = _sb()
    pp.aplicar("L1", pp.decidir(pp.NO_CONCORRENTE, payload="conc_outra"), deal_id="d", sb=sb)
    assert sb.table.return_value.update.call_args.args[0] == {"lost_reason_code": "comprou_outro"}


def test_aplicar_sem_nada_a_gravar_nao_toca_o_banco():
    sb = _sb()
    assert pp.aplicar("L1", pp.decidir(pp.NO_AVISAR, payload="avisar_nao"), sb=sb) is None
    sb.table.assert_not_called()


def test_aplicar_fail_soft():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("fora")
    assert pp.aplicar("L1", pp.decidir(pp.NO_MOTIVO, payload="frete"), deal_id="d", sb=sb) is None


# ── Consulta da lista ───────────────────────────────────────────────────────
def test_consulta_so_le():
    corpo = "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--")).lower()
    for proibido in ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "truncate "):
        assert proibido not in corpo, proibido


def test_consulta_tem_os_filtros_do_publico():
    assert "vw_repasse_resposta" in SQL
    assert "segmento = 'atacado'" in SQL
    assert "\\set dias 60" in SQL
    assert "s.sold_at >= a.repasse_em" in SQL and "'cancel%'" in SQL
    assert "opt_out" in SQL and "blacklisted_at" in SQL and "wrong_number_at" in SQL
