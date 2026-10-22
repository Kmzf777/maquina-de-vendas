"""Migrations 20261022c (origem_cadastro, fn_lead_canal, gatilho de entrada) e 20261022d
(dashboard_kpis/dashboard_funnel_conversion pela D1) contra um Postgres DE VERDADE.

Cartão b67f1c6b. Sem `B67F_PSQL` os testes pulam (o CI não tem Postgres). Para rodar no
Postgres descartável com o schema de produção + as migrations:

    B67F_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_origem_dashboard_pg.py

Cada cenário roda numa transação com ROLLBACK; datas de 2030 e ids com prefixo b67f1c6b-.
2030-06-11 é uma terça (America/Sao_Paulo, -03).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

try:
    import pytest
except ImportError:  # host sem pytest: o runner do __main__ cuida
    pytest = None

PSQL = os.environ.get("B67F_PSQL", "")


def _id(n: int) -> str:
    return f"b67f1c6b-0000-0000-0000-{n:012d}"


def _conv(n: int) -> str:
    return f"b67f1c6b-0000-0000-0000-{'c' + str(n).rjust(11, '0')}"


def _precisa_pg(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(not PSQL, reason="sem B67F_PSQL (Postgres descartável)")(fn)


def _psql(sql: str) -> str:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def _tx(corpo: str) -> list[str]:
    out = _psql(f"begin;\n{corpo}\nrollback;\n")
    return [x.strip() for x in out.splitlines() if "=" in x]


def _lead(n: int, *, ts: str | None = "2030-06-11 10:00-03", origem: str = "inbound",
          ja_cliente: bool | None = None, extra: dict[str, str] | None = None) -> str:
    cols = {"id": _id(n), "phone": f"55997{n:08d}", "name": f"Teste b67f {n}",
            "origem_cadastro": origem}
    if ts is not None:  # None = default now()
        cols["created_at"] = ts
    if ja_cliente is not None:
        cols["ja_era_cliente"] = "true" if ja_cliente else "false"
    cols.update(extra or {})
    nomes = ", ".join(cols)
    valores = ", ".join("true" if v == "true" else "false" if v == "false" else f"'{v}'"
                        for v in cols.values())
    return f"insert into public.leads ({nomes}) values ({valores});\n"


def _msg(conv: str, lead: str, role: str, sent_by: str | None, ts: str) -> str:
    sb = "null" if sent_by is None else f"'{sent_by}'"
    return (f"insert into public.messages (lead_id, conversation_id, role, content, sent_by, created_at)"
            f" values ('{lead}', '{conv}', '{role}', 'oi', {sb}, '{ts}');\n")


def _entradas(n: int) -> str:
    return (f"select 'e=' || count(*) || '|' || coalesce(string_agg(new_value || ':' || coalesce(source, '') "
            f"|| ':' || coalesce(metadata->>'sem_rastreio', '-'), ',' order by occurred_at), '') "
            f"from public.lead_events where lead_id = '{_id(n)}' and event_type = 'entrada';\n")


# ── fn_lead_canal ──────────────────────────────────────────────────────────────────
@_precisa_pg
def test_fn_lead_canal_regra_bling_depois_dos_click_ids():
    linhas = _tx("""
select 'bling=' || public.fn_lead_canal(null, null, null, null, null, null, null, null, null, 'bling_import');
select 'reat=' || public.fn_lead_canal(null, null, null, null, 'metaads', null, null, null, null, 'reativacao_import');
select 'gclid=' || public.fn_lead_canal('g1', null, null, null, null, null, null, null, null, 'bling_import');
select 'ctwa=' || public.fn_lead_canal(null, null, 'c1', null, null, null, null, null, null, 'bling_import');
select 'inbound=' || public.fn_lead_canal(null, null, null, null, null, null, null, null, null, 'inbound');
select 'nove=' || public.fn_lead_canal(null, null, null, null, 'instagram', null, null, null, null);
select 'sete=' || public.fn_lead_canal(null, null, null, null, null, null, null);
select 'nomeado=' || public.fn_lead_canal(null, null, null, null, null, null, null, p_origem => 'bling_import');
""")
    assert linhas == ["bling=Bling", "reat=Bling", "gclid=Google Ads", "ctwa=Meta Ads",
                      "inbound=Sem rastreio", "nove=Orgânico", "sete=Sem rastreio",
                      "nomeado=Bling"], linhas


@_precisa_pg
def test_fn_lead_canal_grants_e_uma_assinatura_so():
    linhas = _tx("""
select 'n=' || count(*) from pg_proc where proname = 'fn_lead_canal' and pronamespace = 'public'::regnamespace;
select 'g=' || string_agg(r || ':' || has_function_privilege(r,
  'public.fn_lead_canal(text,text,text,text,text,text,text,text,text,text)', 'EXECUTE'), ',' order by r)
  from unnest(array['anon', 'authenticated', 'service_role']) r;
""")
    assert linhas == ["n=1", "g=anon:true,authenticated:true,service_role:true"], linhas


# ── origem_cadastro ────────────────────────────────────────────────────────────────
@_precisa_pg
def test_origem_cadastro_default_inbound_e_check():
    out = _psql(f"""
begin;
insert into public.leads (id, phone) values ('{_id(1)}', '5599700000001');
select 'o=' || origem_cadastro from public.leads where id = '{_id(1)}';
rollback;
""")
    assert [x.strip() for x in out.splitlines() if "=" in x] == ["o=inbound"]
    with pytest.raises(AssertionError, match="leads_origem_cadastro_check"):
        _psql(f"begin;\ninsert into public.leads (id, phone, origem_cadastro) "
              f"values ('{_id(2)}', '5599700000002', 'secretaria');\nrollback;\n")


# ── gatilho de entrada ─────────────────────────────────────────────────────────────
@_precisa_pg
def test_insert_inbound_sem_rastreio_grava_entrada_organico():
    linhas = _tx(_lead(1) + _entradas(1) + f"""
select 'k=' || dedupe_key || '|' || occurred_at::text from public.lead_events
 where lead_id = '{_id(1)}' and event_type = 'entrada';
""")
    assert linhas[0] == "e=1|Orgânico:inbound:true", linhas
    assert linhas[1] == f"k=entrada:lead:{_id(1)}:inicial|2030-06-11 13:00:00+00", linhas


@_precisa_pg
def test_importado_e_manual_nao_ganham_entrada_sem_rastreio():
    linhas = _tx(_lead(1, origem="bling_import") + _lead(2, origem="reativacao_import")
                 + _lead(3, origem="manual") + _lead(4, origem="csv_import")
                 + _entradas(1) + _entradas(2) + _entradas(3) + _entradas(4))
    assert linhas == ["e=0|"] * 4, linhas


@_precisa_pg
def test_importado_com_rastreio_ganha_canal_bling_na_entrada():
    linhas = _tx(_lead(1, origem="bling_import", extra={"utm_source": "instagram"}) + _entradas(1))
    assert linhas == ["e=1|Bling:lp:-"], linhas


@_precisa_pg
def test_insert_com_rastreio_continua_como_antes():
    linhas = _tx(_lead(1, extra={"ctwa_clid": "ctwa-b67f"}) + _entradas(1))
    assert linhas == ["e=1|Meta Ads:ctwa:-"], linhas


@_precisa_pg
def test_rastreio_em_ate_30_min_funde_na_entrada_organico():
    # created_at = agora: a fusão de 30 min olha now()
    linhas = _tx(_lead(1, ts=None)
                 + f"update public.leads set ctwa_clid = 'ctwa-b67f' where id = '{_id(1)}';\n"
                 + _entradas(1))
    assert linhas == ["e=1|Meta Ads:ctwa:-"], linhas


@_precisa_pg
def test_rastreio_depois_de_30_min_e_reentrada():
    # cadastro no passado (a fusão de 30 min compara com now())
    linhas = _tx(_lead(1, ts="2020-06-11 10:00-03")
                 + f"update public.leads set utm_source = 'metaads' where id = '{_id(1)}';\n"
                 + _entradas(1))
    assert linhas == ["e=2|Orgânico:inbound:true,Meta Ads:lp:-"], linhas


@_precisa_pg
def test_meta_ad_id_sozinho_em_lead_sem_entrada_grava_a_entrada():
    linhas = _tx(_lead(1, origem="manual", ts="2030-06-11 10:00-03")
                 + f"update public.leads set meta_ad_id = 'ad-b67f' where id = '{_id(1)}';\n"
                 + _entradas(1) + f"""
select 'k=' || dedupe_key || '|' || occurred_at::text from public.lead_events
 where lead_id = '{_id(1)}' and event_type = 'entrada';
""")
    assert linhas[0] == "e=1|Meta Ads:ctwa:-", linhas
    # datada do cadastro do lead (é a entrada dele), não do dia do UPDATE
    assert linhas[1] == f"k=entrada:lead:{_id(1)}:inicial|2030-06-11 13:00:00+00", linhas


@_precisa_pg
def test_meta_ad_id_sozinho_substitui_a_entrada_organico_automatica():
    linhas = _tx(_lead(1, ts="2030-06-11 10:00-03")
                 + f"update public.leads set meta_ad_id = 'ad-b67f' where id = '{_id(1)}';\n"
                 + _entradas(1))
    assert linhas == ["e=1|Meta Ads:ctwa:-"], linhas


@_precisa_pg
def test_meta_ad_id_sozinho_com_outra_entrada_nao_inventa_reentrada():
    linhas = _tx(_lead(1, ts="2030-06-11 10:00-03", extra={"utm_source": "instagram"})
                 + f"update public.leads set meta_ad_id = 'ad-b67f' where id = '{_id(1)}';\n"
                 + _entradas(1))
    assert linhas == ["e=1|Orgânico:lp:-"], linhas


@_precisa_pg
def test_meta_ad_id_enriquece_a_entrada_do_mesmo_ctwa_clid():
    linhas = _tx(_lead(1, ts="2030-06-11 10:00-03", extra={"ctwa_clid": "ctwa-b67f"})
                 + f"update public.leads set meta_ad_id = 'ad-b67f' where id = '{_id(1)}';\n"
                 + _entradas(1) + f"""
select 'm=' || (metadata->>'meta_ad_id') from public.lead_events
 where lead_id = '{_id(1)}' and event_type = 'entrada';
""")
    assert linhas == ["e=1|Meta Ads:ctwa:-", "m=ad-b67f"], linhas


# ── dashboard_kpis ─────────────────────────────────────────────────────────────────
KPIS_RESULT = (
    "TABLE(leads_new bigint, leads_prev bigint, active_with_ai bigint, "
    "active_awaiting_lead bigint, conversations_attended bigint, handoffs bigint, "
    "qualification_rate numeric, sla_median_minutes numeric, sla_p95_minutes numeric, "
    "sla_samples bigint, cost_per_handoff_usd numeric, cost_per_atendimento_usd numeric, "
    "contacts_new bigint)"
)


@_precisa_pg
def test_dashboard_kpis_assinatura_com_contacts_new_no_fim_e_grants():
    linhas = _tx("""
select 'args=' || pg_get_function_identity_arguments('public.dashboard_kpis(date,date,text)'::regprocedure);
select 'res=' || pg_get_function_result('public.dashboard_kpis(date,date,text)'::regprocedure);
select 'g=' || string_agg(r || ':' || has_function_privilege(r, 'public.dashboard_kpis(date,date,text)', 'EXECUTE')
  || ':' || has_function_privilege(r, 'public.dashboard_funnel_conversion(date,date,text)', 'EXECUTE'), ',' order by r)
  from unnest(array['anon', 'authenticated', 'service_role']) r;
""")
    assert linhas == ["args=p_start date, p_end date, p_tz text", "res=" + KPIS_RESULT,
                      "g=anon:true:true,authenticated:true:true,service_role:true:true"], linhas


def _seed_d1() -> str:
    return (
        _lead(1)                                              # inbound sem rastreio: Orgânico
        + _lead(2, extra={"ctwa_clid": "ctwa-b67f-2"})        # Meta Ads
        + _lead(3, origem="bling_import", extra={"utm_source": "instagram"})  # importado c/ entrada
        + _lead(4, ja_cliente=True)                          # já era cliente
        + _lead(5, origem="reativacao_import")               # importado sem entrada
        + _lead(6, ts="2030-06-04 10:00-03")                  # chegou na semana anterior...
        # reentradas (o gatilho grava com now(); aqui a data é fixa): o 6 volta no dia 11,
        # o 2 entra de novo no mesmo dia
        + "insert into public.lead_events (lead_id, event_type, new_value, occurred_at, source, dedupe_key) values"
          f" ('{_id(6)}', 'entrada', 'Meta Ads', '2030-06-11 11:00-03', 'lp', 'b67f-reentrada-6'),"
          f" ('{_id(2)}', 'entrada', 'Meta Ads', '2030-06-11 15:00-03', 'lp', 'b67f-reentrada-2');\n"
    )


@_precisa_pg
def test_dashboard_kpis_leads_new_pela_d1_e_contacts_new_conta_tudo():
    linhas = _tx(_seed_d1() + """
select 'k=' || leads_new || '|' || leads_prev || '|' || contacts_new
  from public.dashboard_kpis('2030-06-11', '2030-06-12');
select 'sem=' || leads_new || '|' || leads_prev || '|' || contacts_new
  from public.dashboard_kpis('2030-06-11', '2030-06-18');
select 'prev=' || leads_new || '|' || contacts_new
  from public.dashboard_kpis('2030-06-04', '2030-06-05');
""")
    # dia 11: D1 = leads 1 e 2 (reentrada do 2 não conta de novo; o 6 já tinha entrado no dia 4;
    # 3 e 5 importados; 4 já era cliente). contacts_new = os 5 criados no dia 11.
    # leads_prev do dia 11 = dia 10: ninguém. Semana 11-17: prev = 04-10 -> o lead 6.
    assert linhas == ["k=2|0|5", "sem=2|1|5", "prev=1|1"], linhas


@_precisa_pg
def test_dashboard_funnel_conversion_cohort_d1():
    linhas = _tx(_seed_d1()
                 + f"insert into public.conversations (id, lead_id) values ('{_conv(1)}', '{_id(1)}');\n"
                 + f"insert into public.messages (lead_id, conversation_id, role, content, sent_by, created_at) values"
                   f" ('{_id(1)}', '{_conv(1)}', 'system', '[encaminhar_humano] Lead encaminhado ao vendedor', 'agent',"
                   f" '2030-06-11 12:00-03');\n"
                 + """
select 'f=' || leads_total || '|' || with_handoff || '|' || won
  from public.dashboard_funnel_conversion('2030-06-11', '2030-06-12');
""")
    assert linhas == ["f=2|1|0"], linhas


@_precisa_pg
def test_dashboard_kpis_taxa_qualificados_sobre_atendidos():
    corpo = (
        _lead(1) + _lead(2) + _lead(3)
        + f"insert into public.conversations (id, lead_id) values ('{_conv(1)}', '{_id(1)}'),"
          f" ('{_conv(2)}', '{_id(2)}'), ('{_conv(3)}', '{_id(3)}'), ('{_conv(4)}', '{_id(1)}');\n"
        # lead 1: atendido pela IA (e de novo noutra conversa: conta 1 lead só)
        + _msg(_conv(1), _id(1), "user", "user", "2030-06-11 10:00-03")
        + _msg(_conv(1), _id(1), "assistant", "agent", "2030-06-11 10:01-03")
        + _msg(_conv(4), _id(1), "user", "user", "2030-06-11 11:00-03")
        + _msg(_conv(4), _id(1), "assistant", "valeria_botoes", "2030-06-11 11:01-03")
        # lead 2: atendido pelo bot de botões
        + _msg(_conv(2), _id(2), "user", "user", "2030-06-11 10:00-03")
        + _msg(_conv(2), _id(2), "assistant", "valeria_botoes", "2030-06-11 10:01-03")
        # lead 3: só o vendedor respondeu -> não é atendido pela Valeria
        + _msg(_conv(3), _id(3), "user", "user", "2030-06-11 10:00-03")
        + _msg(_conv(3), _id(3), "assistant", "seller", "2030-06-11 10:01-03")
        # qualificado: lead 1 no período (2 eventos com dedupe diferente contam 1 lead);
        # lead 2 fora do período
        + f"insert into public.lead_events (lead_id, event_type, occurred_at, source, dedupe_key) values"
          f" ('{_id(1)}', 'qualificado', '2030-06-11 10:05-03', 'ia', 'qualificado:{_id(1)}'),"
          f" ('{_id(1)}', 'qualificado', '2030-06-11 10:06-03', 'score', 'qualificado-b67f-teste:{_id(1)}'),"
          f" ('{_id(2)}', 'qualificado', '2030-06-12 10:05-03', 'ia', 'qualificado:{_id(2)}');\n"
        + """
select 'q=' || qualification_rate || '|' || conversations_attended
  from public.dashboard_kpis('2030-06-11', '2030-06-12');
select 'vazio=' || qualification_rate from public.dashboard_kpis('2030-07-11', '2030-07-12');
"""
    )
    linhas = _tx(corpo)
    # 1 qualificado ÷ 2 atendidos (1 e 2). conversations_attended segue a regra antiga (só 'agent').
    assert linhas == ["q=0.5000|1", "vazio=0"], linhas


if __name__ == "__main__":
    if not PSQL:
        print("defina B67F_PSQL")
        sys.exit(2)
    falhas = 0
    for nome, fn in sorted((n, f) for n, f in list(globals().items())
                           if n.startswith("test_") and callable(f)):
        try:
            fn()
            print(f"ok     {nome}")
        except Exception as exc:  # noqa: BLE001 — runner mínimo
            falhas += 1
            print(f"FALHOU {nome}: {exc}")
    sys.exit(1 if falhas else 0)
