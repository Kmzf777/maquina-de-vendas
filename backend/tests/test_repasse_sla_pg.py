"""Migration 20261019_repasse_sla (cartão 7b143561) contra um Postgres DE VERDADE.

Cobre `fn_minutos_uteis_vendedor`, o trigger `trg_leads_first_response` (D4/D6),
`vw_repasse_resposta` e o SLA/handoffs de `dashboard_kpis`.

O CI e o container `canastra-api` não têm Postgres: sem `REPASSE_PSQL` os testes pulam.
Para rodar num Postgres descartável com o schema de produção + a migration
(ver scripts/repasse_sla/scratch_pg.md):

    REPASSE_PSQL='ssh -i ~/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-7b143561 psql -U postgres -h localhost -d postgres' \\
      python backend/tests/test_repasse_sla_pg.py

Roda com o python do host (só stdlib); pytest é opcional. Cada cenário roda numa transação
com ROLLBACK e usa datas de 2030 e ids com prefixo 7b143561- para não colidir com nada.

Datas fixas (America/Sao_Paulo, -03 sem horário de verão):
  2030-06-11 terça | 2030-06-14 sexta | 2030-06-15 sábado | 2030-06-17 segunda
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

PSQL = os.environ.get("REPASSE_PSQL", "")

LEAD = "7b143561-0000-0000-0000-000000000001"
LEAD2 = "7b143561-0000-0000-0000-000000000002"
CONV_IA = "7b143561-0000-0000-0000-00000000c0a1"
CONV_JOAO = "7b143561-0000-0000-0000-00000000c0b1"
VENDEDOR = "7b143561-0000-0000-0000-0000000000f1"
VENDEDOR2 = "7b143561-0000-0000-0000-0000000000f2"
MARCADOR = "[encaminhar_humano] Lead encaminhado ao vendedor João (atacado)"

# Saída de dashboard_kpis em produção (conferida em 19/10/2026): não pode mudar.
KPIS_RESULT = (
    "TABLE(leads_new bigint, leads_prev bigint, active_with_ai bigint, "
    "active_awaiting_lead bigint, conversations_attended bigint, handoffs bigint, "
    "qualification_rate numeric, sla_median_minutes numeric, sla_p95_minutes numeric, "
    "sla_samples bigint, cost_per_handoff_usd numeric, cost_per_atendimento_usd numeric)"
)


def _precisa_pg(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(not PSQL, reason="sem REPASSE_PSQL (Postgres descartável)")(fn)


def _psql(sql: str) -> str:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def _cenario(corpo: str) -> str:
    """Semeia lead + duas conversas (IA e JOÃO), roda o corpo e desfaz tudo."""
    return _psql(f"""
begin;
insert into public.leads (id, phone, name) values ('{LEAD}', '5599700000001', 'Teste 7b143561');
insert into public.conversations (id, lead_id) values ('{CONV_IA}', '{LEAD}'), ('{CONV_JOAO}', '{LEAD}');
{corpo}
rollback;
""")


def _msg(conv: str, role: str, sent_by: str | None, ts: str, *, tipo: str | None = None,
         conteudo: str = "oi", lead: str = LEAD) -> str:
    sb = "null" if sent_by is None else f"'{sent_by}'"
    mt = "null" if tipo is None else f"'{tipo}'"
    lid = "null" if lead is None else f"'{lead}'"
    c = conteudo.replace("'", "''")
    return (f"insert into public.messages (lead_id, conversation_id, role, content, sent_by, message_type, created_at)"
            f" values ({lid}, '{conv}', '{role}', '{c}', {sb}, {mt}, '{ts}');\n")


def _repasse(ts: str, conv: str = CONV_IA, lead: str = LEAD) -> str:
    return _msg(conv, "system", "agent", ts, conteudo=MARCADOR, lead=lead)


def _valor(sql: str) -> str:
    return _psql(sql).strip().splitlines()[-1].strip()


# ── 1. Repasse na conversa da IA, resposta do vendedor na conversa do JOÃO ────────
@_precisa_pg
def test_resposta_em_outra_conversa_preenche_first_response():
    _cenario(
        _repasse("2030-06-11 10:00-03")
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:30-03")
        + f"""
do $$
declare l public.leads; v public.vw_repasse_resposta;
begin
  select * into l from public.leads where id = '{LEAD}';
  assert l.first_response_at = '2030-06-11 10:30-03'::timestamptz, 'first_response_at=' || coalesce(l.first_response_at::text, 'NULL');
  select * into v from public.vw_repasse_resposta where lead_id = '{LEAD}';
  assert v.repasse_em = '2030-06-11 10:00-03'::timestamptz, 'repasse_em=' || coalesce(v.repasse_em::text, 'NULL');
  assert v.primeira_resposta_em = '2030-06-11 10:30-03'::timestamptz, 'primeira_resposta_em';
  assert v.minutos_uteis = 30, 'minutos_uteis=' || coalesce(v.minutos_uteis::text, 'NULL');
  assert v.minutos_uteis_em_aberto is null, 'em_aberto deveria ser NULL';
  assert v.respondeu, 'respondeu';
end $$;
""")


# ── 2. IA, follow-up, disparo e reação do vendedor não contam ──────────────────────
@_precisa_pg
def test_agent_followup_broadcast_e_reacao_nao_contam():
    _cenario(
        _repasse("2030-06-11 10:00-03")
        + _msg(CONV_IA, "assistant", "agent", "2030-06-11 10:05-03")
        + _msg(CONV_JOAO, "assistant", "followup", "2030-06-11 10:06-03")
        + _msg(CONV_JOAO, "assistant", "broadcast", "2030-06-11 10:07-03")
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:08-03", tipo="reaction")
        + f"""
do $$
declare l public.leads; v public.vw_repasse_resposta;
begin
  select * into l from public.leads where id = '{LEAD}';
  assert l.first_response_at is null, 'first_response_at=' || l.first_response_at::text;
  select * into v from public.vw_repasse_resposta where lead_id = '{LEAD}';
  assert not v.respondeu, 'respondeu deveria ser false';
  assert v.minutos_uteis is null, 'minutos_uteis deveria ser NULL';
  -- repasse em 2030 (futuro): conta até now() dá 0, mas nunca NULL quando ainda não respondeu
  assert v.minutos_uteis_em_aberto is not null, 'em_aberto deveria ser preenchido';
end $$;
""")


# ── 3. Resposta do vendedor ANTES do repasse não conta ──────────────────────────────
@_precisa_pg
def test_seller_antes_do_repasse_nao_conta():
    _cenario(
        _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 09:00-03")
        + _repasse("2030-06-11 10:00-03")
        + f"""
do $$ begin
  assert (select first_response_at from public.leads where id = '{LEAD}') is null, 'seller antes do repasse contou';
end $$;
"""
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 11:00-03")
        + f"""
do $$ begin
  assert (select first_response_at from public.leads where id = '{LEAD}') = '2030-06-11 11:00-03'::timestamptz,
         'deveria pegar o seller pos-repasse';
  assert (select minutos_uteis from public.vw_repasse_resposta where lead_id = '{LEAD}') = 60, 'minutos_uteis';
end $$;
""")


# ── 4. Segunda resposta não sobrescreve ─────────────────────────────────────────────
@_precisa_pg
def test_segunda_resposta_nao_sobrescreve():
    _cenario(
        _repasse("2030-06-11 10:00-03")
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:30-03")
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 12:00-03")
        + f"""
do $$ begin
  assert (select first_response_at from public.leads where id = '{LEAD}') = '2030-06-11 10:30-03'::timestamptz,
         'segunda resposta sobrescreveu';
end $$;
""")


# ── 5. Minutos úteis: fim de semana, config do vendedor e override ─────────────────
@_precisa_pg
def test_minutos_uteis_padrao_fim_de_semana():
    # padrão 10h-16h seg-sex: sex 15:00->16:00 (60) + seg 10:00->10:30 (30)
    assert _valor("select public.fn_minutos_uteis_vendedor(null, '2030-06-14 15:00-03', '2030-06-17 10:30-03');") == "90.0"


@_precisa_pg
def test_minutos_uteis_sem_dia_util_e_zero_nao_null():
    # sábado inteiro: nenhum dia útil -> 0 (não NULL); intervalo invertido -> 0
    assert _valor("select public.fn_minutos_uteis_vendedor(null, '2030-06-15 08:00-03', '2030-06-15 20:00-03');") == "0.0"
    assert _valor("select coalesce(public.fn_minutos_uteis_vendedor(null, '2030-06-17 10:30-03', '2030-06-17 10:00-03')::text, 'NULL');") in ("0", "0.0")
    assert _valor("select coalesce(public.fn_minutos_uteis_vendedor(null, null, '2030-06-17 10:00-03')::text, 'NULL');") in ("0", "0.0")


@_precisa_pg
def test_minutos_uteis_config_do_vendedor_e_override():
    out = _psql(f"""
begin;
insert into public.sla_seller_config (user_id, channel_id, display_name, window_start_minute, window_end_minute, active_weekdays, active)
values ('{VENDEDOR}', gen_random_uuid(), 'Teste', 540, 1080, '{{1,2,3,4,5}}', true);
select 'cfg=' || public.fn_minutos_uteis_vendedor('{VENDEDOR}', '2030-06-14 15:00-03', '2030-06-17 10:30-03');
insert into public.sla_overrides (user_id, start_date, end_date, reason) values ('{VENDEDOR}', '2030-06-17', '2030-06-17', 'folga');
select 'ovr=' || public.fn_minutos_uteis_vendedor('{VENDEDOR}', '2030-06-14 15:00-03', '2030-06-17 10:30-03');
-- override de OUTRO vendedor não afeta
select 'outro=' || public.fn_minutos_uteis_vendedor(null, '2030-06-14 15:00-03', '2030-06-17 10:30-03');
rollback;
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert linhas == ["cfg=270.0", "ovr=180.0", "outro=90.0"], linhas


@_precisa_pg
def test_override_sem_user_id_vale_para_todos():
    # sla_overrides.user_id NULL = folga geral (feriado), como use-overdue-leads.ts e o watchdog.
    # Difere de analytics.vw_resposta_closer, que só olha a folga do próprio vendedor.
    out = _psql(f"""
begin;
insert into public.sla_overrides (user_id, start_date, end_date, reason) values (null, '2030-06-17', '2030-06-17', 'feriado');
select 'padrao=' || public.fn_minutos_uteis_vendedor(null, '2030-06-14 15:00-03', '2030-06-17 10:30-03');
select 'vend=' || public.fn_minutos_uteis_vendedor('{VENDEDOR}', '2030-06-14 15:00-03', '2030-06-17 10:30-03');
rollback;
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert linhas == ["padrao=60.0", "vend=60.0"], linhas


@_precisa_pg
def test_config_inativa_usa_padrao():
    out = _psql(f"""
begin;
insert into public.sla_seller_config (user_id, channel_id, display_name, window_start_minute, window_end_minute, active_weekdays, active)
values ('{VENDEDOR}', gen_random_uuid(), 'Teste', 540, 1080, '{{1,2,3,4,5}}', false);
select 'v=' || public.fn_minutos_uteis_vendedor('{VENDEDOR}', '2030-06-14 15:00-03', '2030-06-17 10:30-03');
rollback;
""")
    assert [x.strip() for x in out.splitlines() if "=" in x] == ["v=90.0"]


# ── 6. dashboard_kpis: handoffs e SLA pela regra nova, mesma assinatura ─────────────
@_precisa_pg
def test_dashboard_kpis_sla_por_lead():
    out = _cenario(
        _repasse("2030-06-11 10:00-03")
        + _repasse("2030-06-11 10:10-03", conv=CONV_JOAO)  # 2º marcador do MESMO lead: 1 handoff só
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:30-03")
        + """
select 'k=' || handoffs || '|' || sla_samples || '|' || sla_median_minutes || '|' || sla_p95_minutes
  from public.dashboard_kpis('2030-06-11', '2030-06-12');
select 'fora=' || handoffs || '|' || sla_samples || '|' || coalesce(sla_median_minutes::text, 'NULL')
  from public.dashboard_kpis('2030-06-12', '2030-06-13');
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert linhas == ["k=1|1|30.0|30.0", "fora=0|0|NULL"], linhas


@_precisa_pg
def test_dashboard_kpis_mesma_assinatura():
    args = _valor("select pg_get_function_identity_arguments('public.dashboard_kpis(date,date,text)'::regprocedure);")
    res = _valor("select pg_get_function_result('public.dashboard_kpis(date,date,text)'::regprocedure);")
    assert args == "p_start date, p_end date, p_tz text", args
    assert res == KPIS_RESULT, res


# ── 7. Lead com 2 repasses: vale o 1º ──────────────────────────────────────────────
@_precisa_pg
def test_view_usa_primeiro_repasse():
    _cenario(
        _repasse("2030-06-11 10:00-03")
        + _repasse("2030-06-11 11:00-03")
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 11:30-03")
        + f"""
do $$
declare v public.vw_repasse_resposta;
begin
  assert (select count(*) from public.vw_repasse_resposta where lead_id = '{LEAD}') = 1, 'uma linha por lead';
  select * into v from public.vw_repasse_resposta where lead_id = '{LEAD}';
  assert v.repasse_em = '2030-06-11 10:00-03'::timestamptz, 'repasse_em=' || v.repasse_em::text;
  assert v.minutos_uteis = 90, 'minutos_uteis=' || coalesce(v.minutos_uteis::text, 'NULL');
end $$;
""")


# ── 7b. vendedor_id: evento repasse > leads.assigned_to; horário segue o vendedor ───
@_precisa_pg
def test_vendedor_do_evento_e_fallback_assigned_to():
    _cenario(
        f"""
insert into public.sla_seller_config (user_id, channel_id, display_name, window_start_minute, window_end_minute, active_weekdays, active)
values ('{VENDEDOR}', gen_random_uuid(), 'Cedo', 540, 1080, '{{1,2,3,4,5}}', true);
update public.leads set assigned_to = '{VENDEDOR2}' where id = '{LEAD}';
"""
        + _repasse("2030-06-11 09:00-03")
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:30-03")
        + f"""
do $$
declare v public.vw_repasse_resposta;
begin
  -- sem evento: assigned_to (sem config -> padrão 10h): 09:00->10:30 = 30
  select * into v from public.vw_repasse_resposta where lead_id = '{LEAD}';
  assert v.vendedor_id = '{VENDEDOR2}', 'fallback assigned_to: ' || coalesce(v.vendedor_id::text, 'NULL');
  assert v.minutos_uteis = 30, 'padrao: ' || coalesce(v.minutos_uteis::text, 'NULL');
end $$;
insert into public.lead_events (lead_id, event_type, occurred_at, source, dedupe_key, metadata)
values ('{LEAD}', 'repasse', '2030-06-11 09:00-03', 'ia', 'repasse:7b143561-teste',
        jsonb_build_object('vendedor_id', '{VENDEDOR}', 'vendedor', 'Cedo'));
do $$
declare v public.vw_repasse_resposta;
begin
  -- com evento: vendedor do evento (config 9h-18h): 09:00->10:30 = 90
  select * into v from public.vw_repasse_resposta where lead_id = '{LEAD}';
  assert v.vendedor_id = '{VENDEDOR}', 'vendedor do evento: ' || coalesce(v.vendedor_id::text, 'NULL');
  assert v.minutos_uteis = 90, 'config do vendedor: ' || coalesce(v.minutos_uteis::text, 'NULL');
end $$;
""")


@_precisa_pg
def test_vendedor_id_invalido_no_evento_nao_quebra_view():
    _cenario(
        _repasse("2030-06-11 10:00-03")
        + f"""
insert into public.lead_events (lead_id, event_type, occurred_at, source, dedupe_key, metadata)
values ('{LEAD}', 'repasse', '2030-06-11 10:00-03', 'backfill', 'repasse:7b143561-lixo',
        jsonb_build_object('vendedor_id', 'joao'));
do $$ begin
  assert (select vendedor_id from public.vw_repasse_resposta where lead_id = '{LEAD}') is null, 'vendedor_id lixo';
end $$;
""")


# ── 8. O trigger nunca bloqueia o insert da mensagem ───────────────────────────────
@_precisa_pg
def test_mensagem_sem_lead_passa():
    _cenario(
        _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:30-03", lead=None)
        + f"""
do $$ begin
  assert (select count(*) from public.messages where conversation_id = '{CONV_JOAO}' and lead_id is null) = 1, 'insert sem lead';
end $$;
""")


@_precisa_pg
def test_falha_no_update_vira_warning_e_insert_passa():
    # Um trigger BEFORE UPDATE em leads que explode simula falha no UPDATE do trigger novo.
    out = _cenario(
        _repasse("2030-06-11 10:00-03")
        + """
create function pg_temp.explode() returns trigger language plpgsql as $f$
begin raise exception 'boom 7b143561'; end $f$;
create trigger zz_explode_7b143561 before update on public.leads for each row execute function pg_temp.explode();
"""
        + _msg(CONV_JOAO, "assistant", "seller", "2030-06-11 10:30-03")
        + f"""
select 'n=' || count(*) from public.messages where lead_id = '{LEAD}' and sent_by = 'seller';
select 'fr=' || coalesce(first_response_at::text, 'NULL') from public.leads where id = '{LEAD}';
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert linhas == ["n=1", "fr=NULL"], linhas


@_precisa_pg
def test_grants_para_consulta_ro_e_authenticated():
    out = _psql("""
select 'f=' || has_function_privilege(r, 'public.fn_minutos_uteis_vendedor(uuid,timestamptz,timestamptz)', 'EXECUTE')
            || '|v=' || has_table_privilege(r, 'public.vw_repasse_resposta', 'SELECT')
  from unnest(array['authenticated', 'service_role', 'consulta_ro']) r;
select 'trg_anon=' || has_function_privilege('anon', 'public.fn_leads_first_response()', 'EXECUTE');
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert linhas == ["f=true|v=true"] * 3 + ["trg_anon=false"], linhas


if __name__ == "__main__":
    if not PSQL:
        print("defina REPASSE_PSQL (ver scripts/repasse_sla/scratch_pg.md)")
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
