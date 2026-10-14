"""Mesclagem de leads duplicados por telefone canonico (spec 2026-10-13).

Caso real: Douglas com `4999170363`, `554999170363` e `5549999170363` — tres leads para a
mesma pessoa. O script agrupa pelo telefone canonico (55 + DDD + 9 + 8 digitos, a mesma
regra do backend e do `normalizePhoneBR` do front) e mescla no lead mais antigo.
"""
import csv
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "leads" / "mesclar_duplicados_telefone.py"


def _script():
    spec = importlib.util.spec_from_file_location("mesclar_duplicados_telefone", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def _lead(id_, phone, created_at, name=None):
    return {"id": id_, "phone": phone, "name": name, "created_at": created_at}


def test_canonico():
    m = _script()
    assert m.canonico("4999170363") == "5549999170363"
    assert m.canonico("554999170363") == "5549999170363"
    assert m.canonico("5549999170363") == "5549999170363"
    assert m.canonico("(31) 8301-6991") == "5531983016991"
    assert m.canonico("031983016991") == "5531983016991"
    assert m.canonico("554934415750") == "5549934415750"   # fixo: mesma regra do backend
    for lixo in ("bling-123", "US.1349120865", "", None, "123", "123456789012"):
        assert m.canonico(lixo) is None


def test_agrupar_escolhe_o_mais_antigo_e_ignora_unicos():
    m = _script()
    grupos = m.agrupar([
        _lead(B, "5549999170363", "2026-06-15T10:00:00+00:00"),
        _lead(A, "4999170363", "2026-05-08T10:00:00+00:00"),
        _lead(C, "5531983016991", "2026-01-01T10:00:00+00:00"),
    ])
    assert len(grupos) == 1
    g = grupos[0]
    assert g["canonico"] == "5549999170363"
    assert g["sobrevivente"]["id"] == A
    assert [d["id"] for d in g["duplicados"]] == [B]


def test_agrupar_empate_de_created_at_fica_o_menor_id():
    m = _script()
    mesma_hora = "2026-05-08T10:00:00+00:00"
    g = m.agrupar([_lead(B, "4999170363", mesma_hora), _lead(A, "5549999170363", mesma_hora)])[0]
    assert g["sobrevivente"]["id"] == A
    assert [d["id"] for d in g["duplicados"]] == [B]


def test_agrupar_ignora_bling_e_lixo():
    m = _script()
    assert m.agrupar([_lead(A, "bling-1", "2026-01-01"), _lead(B, "bling-1", "2026-01-02"),
                      _lead(C, None, "2026-01-03"), _lead(D, "", "2026-01-04")]) == []


def _grupo(nome_s, nome_d, canonico="5549999170363", extras=()):
    return {"canonico": canonico,
            "sobrevivente": _lead(A, "4999170363", "2026-05-08", nome_s),
            "duplicados": [_lead(B, canonico, "2026-06-15", nome_d), *extras]}


def test_classificar_mesmo_primeiro_nome_e_automatico():
    m = _script()
    assert m.classificar(_grupo("Douglas Silva", "DOUGLAS")) == ("automatico", "")
    assert m.classificar(_grupo("José", "jose maria")) == ("automatico", "")


def test_classificar_nome_vazio_e_automatico():
    m = _script()
    assert m.classificar(_grupo("Douglas", None)) == ("automatico", "")
    assert m.classificar(_grupo("  ", "Douglas")) == ("automatico", "")


def test_classificar_primeiro_nome_diferente_vai_para_revisar():
    m = _script()
    assert m.classificar(_grupo("Douglas", "Francine")) == ("revisar", "nomes diferentes")


def test_classificar_3_leads_vai_para_revisar():
    m = _script()
    g = _grupo("Douglas", "Douglas", extras=[_lead(C, "554999170363", "2026-09-04", "Douglas")])
    assert m.classificar(g) == ("revisar", "3 leads no grupo")


def test_classificar_fixo_com_9_injetado_vai_para_revisar():
    m = _script()
    assert m.classificar(_grupo("Loja", "Loja", canonico="5549934415750")) == \
        ("revisar", "telefone fixo (9 injetado)")


# ── Task 5: SQL de um grupo ─────────────────────────────────────────────────────────

TABELAS = {"messages", "conversations", "follow_up_jobs", "sales", "broadcast_leads",
           "lead_tags", "deals", "lead_events", "campaign_enrollments"}
CHAVES = {"messages": ["id"], "conversations": ["id"], "follow_up_jobs": ["id"],
          "sales": ["id"], "broadcast_leads": ["id"], "lead_tags": ["lead_id", "tag_id"],
          "deals": ["id"], "lead_events": ["id"], "campaign_enrollments": ["id"]}


def _trio():
    return {"canonico": "5549999170363",
            "sobrevivente": _lead(A, "4999170363", "2026-05-08", "Douglas"),
            "duplicados": [_lead(B, "5549999170363", "2026-06-15", "Douglas"),
                           _lead(C, "554999170363", "2026-09-04", "Douglas")]}


def test_sql_do_grupo_trava_todos_os_leads_e_confere_que_existem():
    m = _script()
    linhas = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES).splitlines()
    assert linhas[0] == "begin;"
    # lead preso por outra transacao: o grupo cai como erro em 5s em vez de travar a rodada
    assert linhas[1] == "set local lock_timeout = '5s';"
    assert linhas[2] == (f"select 1 from public.leads where id in ('{A}', '{B}', '{C}')"
                         " for update;")
    sql = "\n".join(linhas)
    assert f"where id in ('{A}', '{B}', '{C}')) <> 3 then" in sql
    assert sql.rstrip().endswith("commit;")


def test_sql_confere_que_o_telefone_de_cada_membro_ainda_e_do_grupo():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    trava = sql.index("for update;")
    confere = sql.index("raise exception 'grupo 5549999170363: telefone de algum lead mudou")
    assert trava < confere < sql.index("create temp table _dups")
    # a mesma regra de canonico(), em SQL
    assert r"regexp_replace(coalesce(l.phone, ''), '\D', '', 'g')" in sql
    assert "is distinct from '5549999170363'" in sql


def test_fixo_fica_sem_o_9_injetado():
    m = _script()
    g = {"canonico": "5549934415750",
         "sobrevivente": _lead(A, "4934415750", "2026-05-08", "Loja"),
         "duplicados": [_lead(B, "554934415750", "2026-06-15", "Loja")]}
    sql = m.sql_mesclar_grupo(g, TABELAS, CHAVES)
    assert "update public.leads s set phone = '554934415750'," in sql
    assert "is distinct from '5549934415750'" in sql  # a conferencia usa o canonico
    assert m.telefone_final("5549934415750") == "554934415750"
    assert m.telefone_final("5549999170363") == "5549999170363"


def test_sql_apaga_os_duplicados_so_depois_de_mover_as_mensagens():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    apaga = sql.index(f"delete from public.leads where id in ('{B}', '{C}');")
    assert sql.count("update public.messages") >= 4  # fusao + mover, para B e para C
    assert sql.rindex("update public.messages") < apaga
    assert sql.index("update public.leads s set phone = '5549999170363'") > apaga


def test_sql_cancela_follow_up_e_matricula_em_vez_de_apagar():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    assert "update public.follow_up_jobs d set status = 'cancelled'" in sql
    assert "update public.campaign_enrollments d set status = 'cancelled'" in sql
    assert "delete from public.follow_up_jobs" not in sql
    assert "delete from public.campaign_enrollments" not in sql
    assert "'follow_up_jobs_cancelados'" in sql
    # o cancelamento vem antes de mover (depois dele a linha nao colide mais)
    assert (sql.index("update public.follow_up_jobs d set status = 'cancelled'")
            < sql.index(f"update public.follow_up_jobs x set lead_id = '{A}' where x.lead_id = '{B}'"))


def test_sql_apaga_as_demais_colisoes_como_o_bling():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    assert (f"delete from public.broadcast_leads d using public.broadcast_leads s"
            f" where d.lead_id = '{C}' and s.lead_id = '{A}' and (s.broadcast_id = d.broadcast_id);"
            in sql)
    assert "delete from public.lead_tags d using public.lead_tags s" in sql


def test_sql_funde_conversa_do_duplicado_no_mesmo_canal():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    assert "sc.channel_id = dc.channel_id" in sql
    assert f"set lead_id = '{A}', conversation_id = r.para where x.conversation_id = r.de" in sql
    assert "update public.follow_up_jobs set conversation_id = r.para where conversation_id = r.de" in sql
    assert "update public.sales set conversation_id = r.para where conversation_id = r.de" in sql
    assert "'conversas_fundidas'" in sql
    assert "delete from public.conversations where id = r.de;" in sql
    # a fusao vem antes de mover as conversas restantes do duplicado
    assert (sql.index("sc.channel_id = dc.channel_id")
            < sql.index(f"update public.conversations x set lead_id = '{A}' where x.lead_id = '{B}'"))


def test_sql_grava_um_evento_mesclagem_por_duplicado():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    assert f"'mesclagem:{B}'" in sql and f"'mesclagem:{C}'" in sql
    assert sql.count("on conflict do nothing") == 2
    assert "'telefone canonico 5549999170363'" in sql
    assert sql.count("truncate _mesclagem_movidos;") == 2
    assert "create temp table _dups on commit drop as select * from public.leads" in sql
    assert "select 'movidos=' ||" in sql
    assert "select 'movidos_por_duplicado=' ||" in sql


def test_sql_copia_campos_e_nunca_perde_opt_out():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES)
    copia = sql[sql.index("update public.leads s set phone"):]
    for campo in ("name", "email", "bsuid", "wa_id", "gclid", "traffic_type"):
        # sem valor nos duplicados, fica o do sobrevivente (nunca vira null)
        assert (f"{campo} = case when coalesce(btrim(s.{campo}), '') = ''"
                f" then coalesce(d.{campo}, s.{campo}) else s.{campo} end") in copia
    assert "bling_contact_id = coalesce(s.bling_contact_id, d.bling_contact_id)" in copia
    assert "opt_out = coalesce(s.opt_out, false) or d.opt_out" in copia
    assert "last_msg_at = greatest(s.last_msg_at, d.last_msg_at)" in copia
    assert "from _dups" in copia


def test_sql_tabela_que_nao_existe_no_banco_nao_entra():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), {"messages"}, CHAVES)
    assert "follow_up_jobs" not in sql and "public.conversations" not in sql
    assert "public.sales" not in sql


def test_sql_recusa_id_que_nao_e_uuid():
    m = _script()
    g = _trio()
    g["duplicados"][1] = _lead("x'; drop table leads; --", "554999170363", "2026-09-04")
    with pytest.raises(ValueError):
        m.sql_mesclar_grupo(g, TABELAS, CHAVES)
    g = _trio()
    g["canonico"] = "55'; drop"
    with pytest.raises(ValueError):
        m.sql_mesclar_grupo(g, TABELAS, CHAVES)


# ── Task 5: executar (dry-run e --aplicar) com um banco falso ────────────────────────

F1 = "f1f1f1f1-f1f1-4f1f-8f1f-f1f1f1f1f1f1"
F2 = "f2f2f2f2-f2f2-4f2f-8f2f-f2f2f2f2f2f2"
SOLO = "50505050-5050-4050-8050-505050505050"
PIPE = "99999999-9999-4999-8999-999999999999"

LEADS = [
    _lead(F1, "5551981162558", "2026-03-01T10:00:00+00:00", "Francine"),
    _lead(A, "4999170363", "2026-05-08T10:00:00+00:00", "Douglas"),
    _lead(B, "5549999170363", "2026-06-15T10:00:00+00:00", "Douglas Silva"),
    _lead(F2, "555181162558", "2026-07-01T10:00:00+00:00", "Francine Souza"),
    _lead(C, "554999170363", "2026-09-04T10:00:00+00:00", "Douglas"),
    _lead(SOLO, "5511987654321", "2026-01-01T10:00:00+00:00", "Sozinho"),
]
DEALS = [{"id": "de000000-0000-4000-8000-00000000000b", "lead_id": B, "pipeline_id": PIPE},
         {"id": "de000000-0000-4000-8000-00000000000c", "lead_id": C, "pipeline_id": PIPE}]


FKS_CONHECIDAS = (
    [{"tabela": t, "coluna": "lead_id", "alvo": "leads"} for t in sorted(TABELAS - {"lead_tags"})]
    + [{"tabela": "public.lead_tags", "coluna": "lead_id", "alvo": "public.leads"}]
    + [{"tabela": t, "coluna": "conversation_id", "alvo": "conversations"}
       for t in ("messages", "follow_up_jobs", "sales")])


class BancoFalso:
    """Responde as consultas de `executar` e guarda o SQL de escrita (um por grupo)."""

    def __init__(self, m, leads=LEADS, deals=DEALS, falhar=(), colunas_p0=3, fks_extras=()):
        self.m, self.leads, self.deals = m, leads, deals
        self.fks = [*FKS_CONHECIDAS, *fks_extras]
        self.falhar, self.colunas_p0, self.escritas = falhar, colunas_p0, []

    def linhas(self, sql):
        b = self.m.bling
        if sql is b.Q_TABELAS:
            return [{"table_name": t} for t in sorted(TABELAS)]
        if sql is b.Q_CHAVES:
            return [{"tabela": t, "colunas": c} for t, c in CHAVES.items()]
        if sql is b.Q_COLUNAS_P0:
            colunas = ("occurred_at", "source", "dedupe_key")
            return [{"column_name": c} for c in colunas][:self.colunas_p0]
        if sql is self.m.Q_LEADS:
            return self.leads
        if sql is self.m.Q_FKS:
            return self.fks
        if sql.startswith("select to_jsonb(l) as lead"):  # bling.q_backup (cita todas as tabelas)
            return [{"lead": dict(l), "ids_por_tabela": {}} for l in self.leads if l["id"] in sql]
        if "from public.deals" in sql:
            return [d for d in self.deals if d["lead_id"] in sql]
        if "from public.conversations" in sql:
            return [{"lead_id": B, "conversas": [{"id": "c0", "lead_id": B}]}] if B in sql else []
        if "as antes" in sql:
            return [{"id": l["id"], "antes": dict(l)} for l in self.leads if l["id"] in sql]
        return []

    def executar(self, sql):
        self.escritas.append(sql)
        if any(f in sql for f in self.falhar):
            raise RuntimeError("psql: erro de teste")
        dups = sql.split("delete from public.leads where id in (")[1].split(")")[0]
        ids = [i.strip(" '") for i in dups.split(",")]
        por_dup = {i: {"messages": [f"msg-{i[:4]}"]} for i in ids}
        return ("1\nmovidos=" + json.dumps({"messages": [f"msg-{i[:4]}" for i in ids]})
                + "\nmovidos_por_duplicado=" + json.dumps(por_dup) + "\n")


def _aplicados(db):
    return [sql.split("update public.leads s set phone = '")[1][:13] for sql in db.escritas]


def _unico(pasta, padrao):
    achados = list(Path(pasta).glob(padrao))
    assert len(achados) == 1, achados
    return achados[0]


def _ler(caminho):
    with open(caminho, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _csv_pares(caminho, linhas, campos=("canonico", "sobrevivente", "duplicados")):
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(campos), extrasaction="ignore")
        w.writeheader()
        for lin in linhas:
            w.writerow(lin)
    return caminho


FRANCINE = {"canonico": "5551981162558", "sobrevivente": F1, "duplicados": F2}
DOUGLAS = {"canonico": "5549999170363", "sobrevivente": A, "duplicados": f"{B}|{C}"}


def test_dry_run_grava_os_csvs_e_nao_escreve(tmp_path):
    m = _script()
    db = BancoFalso(m)
    r = m.executar(db, tmp_path)
    assert db.escritas == []
    pares = _ler(tmp_path / "pares.csv")
    assert [(p["canonico"], p["sobrevivente"], p["duplicados"]) for p in pares] == \
        [("5551981162558", F1, F2)]
    assert pares[0]["duplicados_phones"] == "555181162558"
    assert pares[0]["sobrevivente_nome"] == "Francine"
    revisar = _ler(tmp_path / "revisar.csv")
    assert [(x["canonico"], x["sobrevivente"], x["duplicados"], x["motivo"]) for x in revisar] == \
        [("5549999170363", A, f"{B}|{C}", "3 leads no grupo")]
    assert revisar[0]["duplicados_nomes"] == "Douglas Silva|Douglas"
    deals = _ler(tmp_path / "deals_repetidos.csv")
    assert [(d["canonico"], d["sobrevivente"], d["pipeline_id"]) for d in deals] == \
        [("5549999170363", A, PIPE)]
    assert deals[0]["deals"].count("|") == 1
    assert _ler(tmp_path / "excluidos.csv") == []
    backup = json.loads((tmp_path / "backup.json").read_text(encoding="utf-8"))
    assert sorted(b["lead"]["id"] for b in backup) == sorted([B, C, F2])
    item_b = next(b for b in backup if b["lead"]["id"] == B)
    assert item_b["conversas_duplicados"] == [{"id": "c0", "lead_id": B}]
    assert item_b["sobrevivente_antes"]["id"] == A
    assert item_b["canonico"] == "5549999170363"
    assert r["contagens"] == {
        "leads_lidos": 6, "grupos": 2, "automaticos": 1, "revisar": 1, "excluidos": 0,
        "deals_repetidos": 1, "aplicados_ok": 0, "aplicados_erro": 0,
        "aplicados_recusados": 0, "modo": "dry-run"}


def test_aplicar_sem_csv_aborta(tmp_path):
    m = _script()
    db = BancoFalso(m)
    with pytest.raises(SystemExit) as exc:
        m.executar(db, tmp_path, aplicar=True)
    assert "--pares" in str(exc.value)
    assert db.escritas == []


def test_aplicar_sem_p0_aborta(tmp_path):
    m = _script()
    db = BancoFalso(m, colunas_p0=2)
    with pytest.raises(SystemExit):
        m.executar(db, tmp_path / "s", aplicar=True,
                   pares_csv=_csv_pares(tmp_path / "p.csv", [FRANCINE]))
    assert db.escritas == []


def test_aplicar_so_os_grupos_do_csv_inclusive_do_revisar(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE, DOUGLAS])
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert _aplicados(db) == ["5551981162558", "5549999170363"]
    assert r["contagens"]["aplicados_ok"] == 2 and r["contagens"]["modo"] == "aplicar"
    aplicados = _ler(_unico(tmp_path / "s", "aplicados-*.csv"))
    assert [a["resultado"] for a in aplicados] == ["ok", "ok"]
    # o backup do --aplicar tem carimbo de hora e ganha o que mudou de dono, por duplicado
    assert not (tmp_path / "s" / "backup.json").exists()
    backup = json.loads(_unico(tmp_path / "s", "backup-*.json").read_text(encoding="utf-8"))
    por_id = {b["lead"]["id"]: b for b in backup}
    assert por_id[B]["movidos"] == {"messages": [f"msg-{B[:4]}"]}
    assert por_id[C]["movidos"] == {"messages": [f"msg-{C[:4]}"]}


def test_aplicar_aceita_o_proprio_pares_csv_do_dry_run(tmp_path):
    m = _script()
    m.executar(BancoFalso(m), tmp_path / "dry")
    db = BancoFalso(m)
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=tmp_path / "dry" / "pares.csv")
    assert _aplicados(db) == ["5551981162558"]
    assert r["contagens"]["aplicados_recusados"] == 0


def test_linha_com_sobrevivente_ou_duplicados_diferentes_e_recusada(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [
        {**FRANCINE, "sobrevivente": F2, "duplicados": F1},          # sobrevivente nao bate
        {**DOUGLAS, "duplicados": B},                               # faltou o C
        {"canonico": "5511987654321", "sobrevivente": SOLO, "duplicados": SOLO},  # sem grupo
    ])
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert db.escritas == []
    recusados = [a for a in r["aplicados"] if a["resultado"] == "recusado"]
    assert len(recusados) == 3
    assert "sobrevivente" in recusados[0]["erro"]
    assert "duplicados" in recusados[1]["erro"]
    assert "sem grupo" in recusados[2]["erro"]
    assert r["contagens"]["aplicados_recusados"] == 3
    assert _unico(tmp_path / "s", "aplicados-*.csv").read_text(encoding="utf-8").count("recusado") == 3


def test_csv_sem_coluna_duplicados_e_recusado(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [DOUGLAS, FRANCINE], campos=("canonico", "sobrevivente"))
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert db.escritas == []
    assert r["contagens"]["aplicados_recusados"] == 2
    assert all("duplicados" in a["erro"] for a in r["aplicados"])


def test_linha_com_duplicados_vazio_e_recusada(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [{**DOUGLAS, "duplicados": ""}])
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert db.escritas == []
    assert r["contagens"]["aplicados_recusados"] == 1


def test_aplicar_nunca_sobrescreve_backup_anterior(tmp_path, monkeypatch):
    m = _script()
    saida = tmp_path / "s"
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE])
    monkeypatch.setattr(m, "_carimbo", lambda: "20261014-100000")
    m.executar(BancoFalso(m), saida, aplicar=True, pares_csv=csv_)
    primeiro = (saida / "backup-20261014-100000.json").read_text(encoding="utf-8")
    assert (saida / "aplicados-20261014-100000.csv").exists()
    # mesmo carimbo: aborta antes de escrever qualquer coisa no banco ou no disco
    db = BancoFalso(m)
    with pytest.raises(SystemExit):
        m.executar(db, saida, aplicar=True, pares_csv=csv_)
    assert db.escritas == []
    assert (saida / "backup-20261014-100000.json").read_text(encoding="utf-8") == primeiro
    # outro carimbo: arquivo novo, o anterior fica
    monkeypatch.setattr(m, "_carimbo", lambda: "20261014-100500")
    m.executar(BancoFalso(m), saida, aplicar=True, pares_csv=csv_)
    assert sorted(p.name for p in saida.glob("backup-*.json")) ==         ["backup-20261014-100000.json", "backup-20261014-100500.json"]


def test_csv_sem_as_colunas_obrigatorias_aborta(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE], campos=("sobrevivente",))
    with pytest.raises(ValueError):
        m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert db.escritas == []


def test_csv_com_id_invalido_aborta_antes_de_escrever(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE, {**DOUGLAS, "sobrevivente": "x'; drop"}])
    with pytest.raises(ValueError):
        m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert db.escritas == []


@pytest.mark.parametrize("limite,esperado", [
    (0, []), (1, ["5551981162558"]), (None, ["5551981162558", "5549999170363"])])
def test_limite(tmp_path, limite, esperado):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE, DOUGLAS])
    m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_, limite=limite)
    assert _aplicados(db) == esperado


def test_excluir_tira_o_grupo_que_contem_o_id(tmp_path):
    m = _script()
    r = m.executar(BancoFalso(m), tmp_path, excluir=[C])
    assert r["contagens"]["excluidos"] == 1 and r["contagens"]["revisar"] == 0
    excluidos = _ler(tmp_path / "excluidos.csv")
    assert excluidos[0]["canonico"] == "5549999170363"
    assert "excluido via --excluir" in excluidos[0]["motivo"]
    # e no --aplicar a linha do grupo excluido e recusada
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE, DOUGLAS])
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_, excluir=[A])
    assert _aplicados(db) == ["5551981162558"]
    assert r["contagens"]["aplicados_recusados"] == 1


def test_excluir_recusa_id_invalido(tmp_path):
    m = _script()
    with pytest.raises(ValueError):
        m.executar(BancoFalso(m), tmp_path, excluir=["nao-e-uuid"])


def test_erro_num_grupo_nao_para_os_outros(tmp_path):
    m = _script()
    db = BancoFalso(m, falhar=(F2,))
    csv_ = _csv_pares(tmp_path / "p.csv", [FRANCINE, DOUGLAS])
    r = m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert len(db.escritas) == 2
    assert [a["resultado"] for a in r["aplicados"]] == ["erro", "ok"]
    assert "erro de teste" in r["aplicados"][0]["erro"]
    assert r["contagens"]["aplicados_erro"] == 1 and r["contagens"]["aplicados_ok"] == 1


def test_main_aplicar_exige_pares(capsys):
    m = _script()
    with pytest.raises(SystemExit):
        m.main(["--psql", "psql", "--aplicar"])
    assert "--pares" in capsys.readouterr().err


def test_main_repassa_os_argumentos(monkeypatch):
    m = _script()
    visto = {}

    def falso(db, saida, **kw):
        visto.update(kw, saida=saida)
        return {"contagens": {}}

    monkeypatch.setattr(m, "executar", falso)
    m.main(["--psql", "psql", "--saida", "/tmp/x", "--excluir", f"{A}, {B}", "--limite", "0"])
    assert visto["excluir"] == [A, B] and visto["limite"] == 0 and visto["aplicar"] is False
    assert visto["saida"] == "/tmp/x"


def test_exporta_o_psql_do_irmao_do_bling():
    m = _script()
    assert m.Psql is m.bling.Psql


@pytest.mark.parametrize("fk", [
    {"tabela": "quotes", "coluna": "conversation_id", "alvo": "conversations"},
    {"tabela": "deals", "coluna": "contato_id", "alvo": "leads"},
    {"tabela": "outro.tabela", "coluna": "lead_id", "alvo": "public.leads"},
])
def test_fk_desconhecida_para_leads_ou_conversations_aborta(tmp_path, fk):
    m = _script()
    db = BancoFalso(m, fks_extras=[fk])
    with pytest.raises(m.FKDesconhecida) as exc:
        m.executar(db, tmp_path)
    assert fk["coluna"] in str(exc.value)
    assert db.escritas == [] and not (tmp_path / "pares.csv").exists()


def test_fks_conhecidas_passam():
    m = _script()
    m.verificar_fks(FKS_CONHECIDAS)
