"""P1.1 — mesclagem dos leads `bling-*` duplicados: pareamento, gemeas e SQL.

Casos reais da call de 01/10: Jovens/Iago (celular no campo `telefone` do Bling), Serginho
(celular antigo sem o 9), ambiguo (celular e documento apontando para leads diferentes).
"""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bling" / "mesclar_leads_duplicados.py"
_spec = importlib.util.spec_from_file_location("mesclar_leads_duplicados", SCRIPT)
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

DUP = "8b915450-bf36-4bd6-be1b-fde35858f9ed"
HIAGO = "eb8ffb98-fbb2-4847-997c-89b7a0c04ac7"
OUTRO = "11111111-1111-1111-1111-111111111111"


def _cand(id_=DUP, **contato):
    base = {"account": "secundaria", "id": 18410375514, "nome": "Jovens Com Uma Missao",
            "doc_digits": None, "telefone_e164": None, "celular_e164": None}
    return {"id": id_, "phone": "bling-18410375514", "name": "Jovens",
            "contatos": [{**base, **contato}]}


def test_chaves_iguais_as_do_modulo_de_contatos():
    from app.bling.contacts import _chaves_de_celular
    casos = [
        {"telefone_e164": "5543999565650", "celular_e164": None},
        {"telefone_e164": "556697222209", "celular_e164": None},
        {"telefone_e164": "554332221111", "celular_e164": None},
        {"telefone_e164": None, "celular_e164": "554332221111"},
        {"telefone_e164": "5511987654321", "celular_e164": "5511912345678"},
        {"telefone_e164": None, "celular_e164": None},
    ]
    for c in casos:
        assert m.chaves_de_celular(c) == _chaves_de_celular(c), c


def test_jovens_iago_celular_no_campo_telefone_pareia():
    r = m.parear([_cand(telefone_e164="5543999565650", doc_digits="06132231000135")],
                 [{"id": HIAGO, "phone": "5543999565650", "name": "Hiago Angelucci", "cnpj": None}])
    assert [(p["duplicado"], p["sobrevivente"]) for p in r["pares"]] == [(DUP, HIAGO)]
    assert "celular:5543999565650" in r["pares"][0]["motivo"]
    assert r["ambiguos"] == [] and r["orfaos"] == []


def test_serginho_celular_antigo_sem_o_9_pareia():
    r = m.parear([_cand(telefone_e164="556697222209")],
                 [{"id": HIAGO, "phone": "5566997222209", "name": "Serginho Sinop", "cnpj": None}])
    assert len(r["pares"]) == 1


def test_lead_legado_sem_o_9_tambem_pareia():
    r = m.parear([_cand(celular_e164="5566997222209")],
                 [{"id": HIAGO, "phone": "556697222209", "name": "Serginho", "cnpj": None}])
    assert len(r["pares"]) == 1


def test_documento_pareia_mesmo_com_mascara_no_lead():
    r = m.parear([_cand(doc_digits="06132231000135")],
                 [{"id": HIAGO, "phone": "5543999565650", "name": "X",
                   "cnpj": "06.132.231/0001-35"}])
    assert r["pares"][0]["motivo"] == "documento:06132231000135"


def test_celular_e_documento_em_leads_diferentes_e_ambiguo():
    r = m.parear([_cand(telefone_e164="5543999565650", doc_digits="06132231000135")],
                 [{"id": HIAGO, "phone": "5543999565650", "name": "Hiago", "cnpj": None},
                  {"id": OUTRO, "phone": "5511900000000", "name": "Jocum",
                   "cnpj": "06132231000135"}])
    assert r["pares"] == []
    assert r["ambiguos"][0]["duplicado"] == DUP
    assert sorted(r["ambiguos"][0]["opcoes"]) == sorted([HIAGO, OUTRO])


def test_sem_achado_e_orfao_e_fixo_nao_conta():
    r = m.parear([_cand(telefone_e164="554332221111")],
                 [{"id": HIAGO, "phone": "554332221111", "name": "Fixo", "cnpj": None}])
    assert r["pares"] == [] and [o["duplicado"] for o in r["orfaos"]] == [DUP]


def test_outro_candidato_nunca_e_sobrevivente():
    outro_dup = _cand(id_=OUTRO, telefone_e164="5543999565650")
    outro_dup["phone"] = "5543999565650"
    r = m.parear([_cand(telefone_e164="5543999565650"), outro_dup],
                 [{"id": OUTRO, "phone": "5543999565650", "name": "Bling 2", "cnpj": None}])
    assert r["pares"] == []
    assert len(r["orfaos"]) == 2


def test_documento_lixo_nao_pareia():
    r = m.parear([_cand(doc_digits="00000000000")],
                 [{"id": HIAGO, "phone": "x", "name": "Lixo", "cnpj": "000.000.000-00"}])
    assert r["pares"] == []


def _venda(id_, lead, valor, origin, sold_at, status="registrada"):
    return {"id": id_, "lead_id": lead, "value": valor, "origin": origin,
            "status": status, "sold_at": sold_at}


PAR = [{"duplicado": DUP, "sobrevivente": HIAGO}]


def test_gemeas_iago_60_bling_e_60_manual():
    g = m.vendas_gemeas(PAR, [
        _venda("VB", DUP, 60, "bling", "2026-09-25T12:00:00+00:00"),
        _venda("VM", HIAGO, "60.00", "manual", "2026-09-24T15:00:00+00:00"),
    ])
    assert len(g) == 1
    assert (g[0]["venda_bling"], g[0]["venda_outra"]) == ("VB", "VM")
    assert g[0]["diferenca_horas"] == 21.0


@pytest.mark.parametrize("outra", [
    _venda("VM", HIAGO, 61, "manual", "2026-09-24T15:00:00+00:00"),
    _venda("VM", HIAGO, 60, "manual", "2026-09-23T11:00:00+00:00"),
    _venda("VM", HIAGO, 60, "manual", "2026-09-24T15:00:00+00:00", status="cancelada"),
    _venda("VM", HIAGO, 60, "bling", "2026-09-24T15:00:00+00:00"),
])
def test_nao_e_gemea(outra):
    assert m.vendas_gemeas(PAR, [_venda("VB", DUP, 60, "bling", "2026-09-25T12:00:00+00:00"),
                                 outra]) == []


def test_gemea_detectada_nos_dois_sentidos():
    g = m.vendas_gemeas(PAR, [
        _venda("VC", DUP, 90, "crm", "2026-09-23T12:00:00+00:00"),
        _venda("VB", HIAGO, 90, "bling", "2026-09-23T12:00:00+00:00"),
    ])
    assert [(x["venda_bling"], x["venda_outra"]) for x in g] == [("VB", "VC")]


def test_tabela_com_lead_id_nao_coberta_aborta():
    with pytest.raises(m.TabelaNaoCoberta) as exc:
        m.verificar_cobertura(m.TABELAS_COBERTAS | {"tabela_nova"})
    assert "tabela_nova" in str(exc.value)
    m.verificar_cobertura(set(m.TABELAS_COBERTAS))


def test_cobertura_bate_com_as_21_tabelas_de_producao():
    producao = {
        "broadcast_leads", "campaign_enrollments", "campaign_execution_log", "conversations",
        "conversion_events", "deals", "follow_up_jobs", "follow_up_jobs_incidente_20261003",
        "lead_bling_contacts", "lead_daily_sends", "lead_events", "lead_notes",
        "lead_qualification_scores", "lead_seller_feelings", "lead_tags", "lp_email_jobs",
        "messages", "messages_archive", "quotes", "sales", "token_usage",
    }
    assert m.TABELAS_COBERTAS == producao


def test_sql_do_par_move_tudo_e_apaga_o_duplicado():
    sql = m.sql_mesclar_par(DUP, HIAGO, {"sales", "messages", "lead_bling_contacts"}, "celular:1")
    assert sql.startswith("begin;") and sql.rstrip().endswith("commit;")
    assert f"update public.sales set lead_id = '{HIAGO}' where lead_id = '{DUP}';" in sql
    assert "delete from public.lead_bling_contacts d using public.lead_bling_contacts s" in sql
    assert "'mesclagem'" in sql and f"'mesclagem:{DUP}'" in sql
    assert f"delete from public.leads where id = '{DUP}';" in sql
    # tabela que nao existe no banco nao entra no SQL
    assert "public.deals" not in sql
    # o sobrevivente recebe cnpj/razao/fantasia/email so se vazios
    assert "coalesce(btrim(s.cnpj), '') = ''" in sql


def test_sql_recusa_id_que_nao_e_uuid():
    with pytest.raises(ValueError):
        m.sql_mesclar_par("x'; drop table leads; --", HIAGO, {"sales"}, "m")


def test_motivo_com_aspas_e_escapado():
    sql = m.sql_mesclar_par(DUP, HIAGO, set(), "nome d'agua")
    assert "nome d''agua" in sql


# ── revisao de 06/10: o lead real do Rafael recebia 14 contatos "Teste Rafael" ──────────

RAFAEL = "5ee7a58f-8c8e-4bcc-8963-9022eeaf67c7"


def _dups_com_o_mesmo_celular(n, celular="5534988861441"):
    return [_cand(id_=f"00000000-0000-0000-0000-{i:012d}", celular_e164=celular)
            for i in range(1, n + 1)]


def test_sobrevivente_com_mais_de_2_duplicados_vai_inteiro_para_ambiguos():
    r = m.parear(_dups_com_o_mesmo_celular(3),
                 [{"id": RAFAEL, "phone": "5534988861441", "name": "Rafael", "cnpj": None}])
    assert r["pares"] == []
    assert len(r["ambiguos"]) == 3
    for amb in r["ambiguos"]:
        assert amb["opcoes"] == [RAFAEL]
        assert "3 duplicados" in amb["motivo"] and "limite 2" in amb["motivo"]


def test_sobrevivente_com_2_duplicados_continua_pareando():
    r = m.parear(_dups_com_o_mesmo_celular(2),
                 [{"id": RAFAEL, "phone": "5534988861441", "name": "Rafael", "cnpj": None}])
    assert [p["sobrevivente"] for p in r["pares"]] == [RAFAEL, RAFAEL]
    assert r["ambiguos"] == []


def test_limite_por_sobrevivente_nao_afeta_os_outros_pares():
    r = m.parear(_dups_com_o_mesmo_celular(3) + [_cand(telefone_e164="5543999565650")],
                 [{"id": RAFAEL, "phone": "5534988861441", "name": "Rafael", "cnpj": None},
                  {"id": HIAGO, "phone": "5543999565650", "name": "Hiago", "cnpj": None}])
    assert [(p["duplicado"], p["sobrevivente"]) for p in r["pares"]] == [(DUP, HIAGO)]
    assert len(r["ambiguos"]) == 3
