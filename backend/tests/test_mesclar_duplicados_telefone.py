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


def test_classificar_possivel_fixo_vai_para_revisar():
    # 55DD9[2-5]... pode ser fixo com o 9 injetado OU celular novo (11 92092-1686, Petter):
    # nao da para saber pelo numero, entao vai para revisao a mao
    m = _script()
    for canonico in ("5549934415750", "5511920921686"):
        assert m.classificar(_grupo("Loja", "Loja", canonico=canonico)) == \
            ("revisar", "possivel telefone fixo (confira)")


# ── Task 5: SQL de um grupo ─────────────────────────────────────────────────────────

TABELAS = {"messages", "conversations", "follow_up_jobs", "sales", "broadcast_leads",
           "lead_tags", "deals", "lead_events", "campaign_enrollments", "quotes",
           "messages_archive"}
CHAVES = {"messages": ["id"], "conversations": ["id"], "follow_up_jobs": ["id"],
          "sales": ["id"], "broadcast_leads": ["id"], "lead_tags": ["lead_id", "tag_id"],
          "deals": ["id"], "lead_events": ["id"], "campaign_enrollments": ["id"],
          "quotes": ["id"], "messages_archive": ["id"]}
# Colunas de producao (crm_schema, 14/10) das tabelas que a fusao de conversas toca.
COLUNAS = {
    "conversations": {"id", "lead_id", "channel_id", "stage", "status", "campaign_id",
                      "last_msg_at", "created_at", "agent_profile_id", "unread_count",
                      "followup_enabled", "first_seller_response_at", "last_seller_response_at",
                      "last_customer_message_at", "agent_persona", "flow_state"},
    "follow_up_jobs": {"id", "conversation_id", "lead_id", "channel_id", "sequence", "fire_at",
                       "status", "cancel_reason", "sent_at", "env_tag", "created_at", "job_type",
                       "metadata", "claimed_at", "wamid"},
    "campaign_enrollments": {"id", "campaign_id", "lead_id", "status", "metadata"},
    "messages": {"id", "lead_id", "conversation_id", "role", "content", "created_at"},
    "sales": {"id", "lead_id", "conversation_id", "value", "sold_at"},
    "quotes": {"id", "lead_id", "conversation_id", "quoted_at"},
    "messages_archive": {"id", "lead_id", "conversation_id", "content"},
}


def _trio():
    return {"canonico": "5549999170363",
            "sobrevivente": _lead(A, "4999170363", "2026-05-08", "Douglas"),
            "duplicados": [_lead(B, "5549999170363", "2026-06-15", "Douglas"),
                           _lead(C, "554999170363", "2026-09-04", "Douglas")]}


def test_sql_do_grupo_trava_todos_os_leads_e_confere_que_existem():
    m = _script()
    linhas = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS).splitlines()
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
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    trava = sql.index("for update;")
    confere = sql.index("raise exception 'grupo 5549999170363: telefone de algum lead mudou")
    assert trava < confere < sql.index("create temp table _dups")
    # a mesma regra de canonico(), em SQL
    assert r"regexp_replace(coalesce(l.phone, ''), '\D', '', 'g')" in sql
    assert "is distinct from '5549999170363'" in sql


def test_possivel_fixo_tambem_fica_com_o_canonico_de_13_digitos():
    # mesma regra do backend (normalize_phone + get_or_create_lead): sempre 13 digitos.
    # Tirar o 9 de "11 92092-1686" quebraria um celular real.
    m = _script()
    for canonico, antigo in (("5549934415750", "4934415750"), ("5511920921686", "11920921686")):
        g = {"canonico": canonico,
             "sobrevivente": _lead(A, antigo, "2026-05-08", "Petter"),
             "duplicados": [_lead(B, canonico, "2026-06-15", "Petter")]}
        sql = m.sql_mesclar_grupo(g, TABELAS, CHAVES, COLUNAS)
        assert f"update public.leads s set phone = '{canonico}'," in sql
        assert f"is distinct from '{canonico}'" in sql
    assert not hasattr(m, "telefone_final")


def test_sql_apaga_os_duplicados_so_depois_de_mover_as_mensagens():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    apaga = sql.index(f"delete from public.leads where id in ('{B}', '{C}');")
    assert sql.count("update public.messages") >= 4  # fusao + mover, para B e para C
    assert sql.rindex("update public.messages") < apaga
    assert sql.index("update public.leads s set phone = '5549999170363'") > apaga


def test_sql_cancela_follow_up_e_matricula_em_vez_de_apagar():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
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
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    # a linha apagada vai inteira para o evento 'mesclagem' (<tabela>_apagados)
    assert (f"with apagados as (delete from public.broadcast_leads d using public.broadcast_leads s"
            f" where d.lead_id = '{C}' and s.lead_id = '{A}' and (s.broadcast_id = d.broadcast_id)"
            " returning to_jsonb(d) as chave) insert into _mesclagem_movidos"
            " select 'broadcast_leads_apagados', chave from apagados;") in sql
    assert "delete from public.lead_tags d using public.lead_tags s" in sql
    assert "'lead_tags_apagados'" in sql


def test_sql_funde_conversa_do_duplicado_no_mesmo_canal():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    assert "sc.channel_id = dc.channel_id" in sql
    assert (f"update public.messages x set lead_id = '{A}', conversation_id = r.para"
            " from public.messages o where o.id = x.id and x.conversation_id = r.de"
            " returning jsonb_build_object('id', x.id, 'de', r.de, 'lead_id', o.lead_id)"
            " as chave)") in sql
    for tabela in ("follow_up_jobs", "sales", "quotes", "messages_archive"):
        assert (f"update public.{tabela} x set conversation_id = r.para"
                " where x.conversation_id = r.de") in sql
    assert "'conversas_fundidas'" in sql
    assert "delete from public.conversations where id = r.de;" in sql
    # a fusao vem antes de mover as conversas restantes do duplicado
    assert (sql.index("sc.channel_id = dc.channel_id")
            < sql.index(f"update public.conversations x set lead_id = '{A}' where x.lead_id = '{B}'"))


def test_sql_grava_um_evento_mesclagem_por_duplicado():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    assert f"'mesclagem:{B}'" in sql and f"'mesclagem:{C}'" in sql
    assert sql.count("on conflict do nothing") == 2
    assert "'telefone canonico 5549999170363'" in sql
    assert sql.count("truncate _mesclagem_movidos;") == 2
    assert "create temp table _dups on commit drop as select * from public.leads" in sql
    assert "select 'movidos=' ||" in sql
    assert "select 'movidos_por_duplicado=' ||" in sql


def test_sql_copia_campos_e_nunca_perde_opt_out():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
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
    sql = m.sql_mesclar_grupo(_trio(), {"messages"}, CHAVES, COLUNAS)
    assert "follow_up_jobs" not in sql and "public.conversations" not in sql
    assert "public.sales" not in sql


def test_sql_recusa_id_que_nao_e_uuid():
    m = _script()
    g = _trio()
    g["duplicados"][1] = _lead("x'; drop table leads; --", "554999170363", "2026-09-04")
    with pytest.raises(ValueError):
        m.sql_mesclar_grupo(g, TABELAS, CHAVES, COLUNAS)
    g = _trio()
    g["canonico"] = "55'; drop"
    with pytest.raises(ValueError):
        m.sql_mesclar_grupo(g, TABELAS, CHAVES, COLUNAS)


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
        if sql is self.m.Q_COLUNAS:
            return [{"table_name": t, "column_name": c}
                    for t, cs in COLUNAS.items() for c in sorted(cs)]
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


# -- revisao de 14/10 ------------------------------------------------------------------

def _fusao(sql):
    return sql[sql.index("for r in select dc.id"):sql.index("end loop;")]


def test_fusao_junta_o_estado_da_conversa_antes_de_apagar_a_do_duplicado():
    m = _script()
    fusao = _fusao(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    junta = fusao.index("update public.conversations sc set")
    assert junta < fusao.index("delete from public.conversations where id = r.de;")
    assert ("followup_enabled = coalesce(sc.followup_enabled, true)"
            " and coalesce(dc.followup_enabled, true)") in fusao
    for c in ("last_msg_at", "last_customer_message_at", "last_seller_response_at"):
        assert f"{c} = greatest(sc.{c}, dc.{c})" in fusao
    assert "unread_count = coalesce(sc.unread_count, 0) + coalesce(dc.unread_count, 0)" in fusao
    recente = ("coalesce(dc.last_msg_at, '-infinity'::timestamptz)"
               " > coalesce(sc.last_msg_at, '-infinity'::timestamptz)")
    for c in ("stage", "status", "flow_state", "agent_profile_id"):
        assert f"{c} = case when {recente} then dc.{c} else sc.{c} end" in fusao
    assert "where sc.id = r.para and dc.id = r.de;" in fusao
    # o estado anterior da conversa de destino vai para o evento (da para desfazer)
    assert "'para_antes', to_jsonb(sc)" in fusao
    assert fusao.index("'conversas_fundidas'") < junta


def test_fusao_so_usa_colunas_que_existem():
    m = _script()
    colunas = {**COLUNAS, "conversations": {"id", "lead_id", "channel_id", "last_msg_at"}}
    fusao = _fusao(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, colunas))
    assert "last_msg_at = greatest(sc.last_msg_at, dc.last_msg_at)" in fusao
    for c in ("followup_enabled", "unread_count", "flow_state", "stage =",
              "last_seller_response_at"):
        assert c not in fusao
    sem_coluna = {**COLUNAS, "quotes": {"id", "lead_id"}}
    assert "update public.quotes x set conversation_id" not in \
        m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, sem_coluna)


def test_fusao_registra_os_reapontamentos_para_desfazer():
    m = _script()
    fusao = _fusao(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    assert fusao.count("returning jsonb_build_object('id', x.id, 'de', r.de) as chave") == 4
    assert "returning jsonb_build_object('id', x.id, 'de', r.de, 'lead_id', o.lead_id)" in fusao
    for nome in ("messages_fundidas", "sales_reapontadas", "follow_up_jobs_reapontados",
                 "messages_archive_reapontadas", "quotes_reapontadas"):
        assert f"select '{nome}', chave from" in fusao


def test_follow_up_pendente_do_duplicado_com_mesmo_tipo_do_sobrevivente_e_cancelado():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    abertos = "('pending', 'processing', 'awaiting_reopen')"
    cancela = (f"with cancelados as (update public.follow_up_jobs d set status = 'cancelled',"
               f" cancel_reason = 'mesclagem' where d.lead_id = '{B}'"
               f" and d.status in {abertos} and exists (select 1 from"
               f" public.follow_up_jobs s where s.lead_id = '{A}'"
               f" and s.status in {abertos} and s.job_type = d.job_type"
               r" and (d.job_type not like 'joao\_%'"
               " or coalesce(s.metadata->>'deal_id', '') = coalesce(d.metadata->>'deal_id', '')))"
               " returning to_jsonb(d.id) as chave) insert into _mesclagem_movidos"
               " select 'follow_up_jobs_cancelados', chave from cancelados;")
    assert cancela in sql
    # antes da fusao do mesmo duplicado (ainda na conversa original) e antes de mover
    assert sql.index(cancela) < sql.index(f"where dc.lead_id = '{B}'")
    assert sql.count("update public.follow_up_jobs d set status = 'cancelled'") == 2  # B e C


def test_cancel_reason_so_onde_a_coluna_existe():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    assert "update public.campaign_enrollments d set status = 'cancelled' from" in sql
    com = {**COLUNAS,
           "campaign_enrollments": COLUNAS["campaign_enrollments"] | {"cancel_reason"}}
    assert ("update public.campaign_enrollments d set status = 'cancelled',"
            " cancel_reason = 'mesclagem' from") in \
        m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, com)
    sem = {**COLUNAS, "follow_up_jobs": COLUNAS["follow_up_jobs"] - {"cancel_reason"}}
    assert "cancel_reason" not in m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, sem)


def test_executar_passa_as_colunas_do_banco_para_o_sql(tmp_path):
    m = _script()
    db = BancoFalso(m)
    csv_ = _csv_pares(tmp_path / "p.csv", [DOUGLAS])
    m.executar(db, tmp_path / "s", aplicar=True, pares_csv=csv_)
    assert "unread_count = coalesce(sc.unread_count, 0)" in db.escritas[0]
    assert "cancel_reason = 'mesclagem'" in db.escritas[0]


# -- re-revisao de 14/10: controle humano, notas, campanha manual, resumo, evento ---------

def _copia(sql):
    return sql[sql.index("update public.leads s set phone"):]


def test_lead_herda_o_controle_humano_do_jeito_conservador():
    m = _script()
    copia = _copia(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    # IA so continua ligada se estava ligada em TODOS (null conta como desligada)
    assert ("ai_enabled = case when s.ai_enabled is not true or not d.ai_enabled"
            " then false else true end") in copia
    assert "coalesce(bool_and(coalesce(x.ai_enabled, false)), true) as ai_enabled" in copia
    # controle humano / pausado: basta um ter
    for c in ("human_control", "on_hold"):
        assert (f"{c} = case when coalesce(s.{c}, false) or d.{c} then true"
                f" else s.{c} end") in copia
        assert f"coalesce(bool_or(x.{c}), false) as {c}" in copia


def test_fusao_de_conversa_herda_controle_humano_se_as_colunas_existirem():
    m = _script()
    fusao = _fusao(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    assert "ai_enabled" not in fusao and "human_control" not in fusao  # producao nao tem
    com = {**COLUNAS, "conversations": COLUNAS["conversations"]
           | {"ai_enabled", "human_control", "on_hold"}}
    fusao = _fusao(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, com))
    assert ("ai_enabled = case when sc.ai_enabled is not true or dc.ai_enabled is not true"
            " then false else true end") in fusao
    for c in ("human_control", "on_hold"):
        assert (f"{c} = case when coalesce(sc.{c}, false) or coalesce(dc.{c}, false)"
                f" then true else sc.{c} end") in fusao


def test_notas_sao_concatenadas_com_o_telefone_de_origem():
    m = _script()
    copia = _copia(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    assert ("string_agg(E'\\n\\n--- mesclado de ' || coalesce(x.phone, '') || E' ---\\n'"
            " || x.notes, '' order by x.created_at, x.id)"
            " filter (where coalesce(btrim(x.notes), '') <> '') as notes") in copia
    assert ("notes = case when coalesce(btrim(s.notes), '') = ''"
            " then coalesce(substr(d.notes, 3), s.notes)"
            " else s.notes || coalesce(d.notes, '') end") in copia


def test_campanha_manual_vem_inteira_do_duplicado_mais_antigo_que_tem():
    m = _script()
    copia = _copia(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    for c in ("canal", "id", "nome", "por", "em"):
        k = f"campanha_manual_{c}"
        assert (f"{k} = case when coalesce(btrim(s.campanha_manual_id), '') = ''"
                f" and d.campanha_manual_id is not null then d.{k} else s.{k} end") in copia
        assert (f"(array_agg(x.{k} order by x.created_at, x.id)"
                " filter (where coalesce(btrim(x.campanha_manual_id), '') <> ''))[1]"
                f" as {k}") in copia


def test_resumo_so_se_o_do_sobrevivente_estiver_vazio():
    m = _script()
    copia = _copia(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    assert ("rolling_summary = case when coalesce(btrim(s.rolling_summary), '') = ''"
            " then coalesce(d.rolling_summary, s.rolling_summary) else s.rolling_summary end"
            ) in copia
    assert ("rolling_summary_updated_at = case when coalesce(btrim(s.rolling_summary), '') = ''"
            " and d.rolling_summary is not null then d.rolling_summary_updated_at"
            " else s.rolling_summary_updated_at end") in copia


def test_evento_guarda_a_linha_inteira_do_duplicado():
    m = _script()
    sql = m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS)
    assert "jsonb_build_object('duplicado', to_jsonb(d), 'motivo'" in sql
    assert sql.count(f"from _dups d where d.id = '{B}'") == 1



def test_fusao_persona_primeira_resposta_e_conversa_apagada():
    m = _script()
    fusao = _fusao(m.sql_mesclar_grupo(_trio(), TABELAS, CHAVES, COLUNAS))
    recente = ("coalesce(dc.last_msg_at, '-infinity'::timestamptz)"
               " > coalesce(sc.last_msg_at, '-infinity'::timestamptz)")
    # a persona anda junto com o agent_profile_id (da conversa mais recente)
    assert (f"agent_persona = case when {recente} then dc.agent_persona"
            " else sc.agent_persona end") in fusao
    assert ("first_seller_response_at = least(sc.first_seller_response_at,"
            " dc.first_seller_response_at)") in fusao
    apaga = ("insert into _mesclagem_movidos select 'conversas_apagadas', to_jsonb(dc)"
             " from public.conversations dc where dc.id = r.de;")
    assert fusao.index(apaga) < fusao.index("delete from public.conversations where id = r.de;")
