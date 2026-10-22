"""Migrations 20261022d1_score_directory e 20261022e_analytics (cartão b67f1c6b) num Postgres DE VERDADE.

Cobre:
  - `valeria_score_directory` sem o filtro `stage='atacado'`: mostra todo lead com score;
  - `analytics.dim_lead.segmento` = `leads.segmento` e `b2b` = `fn_lead_b2b` (ter score não basta, D9);
  - `analytics.dim_vendedor` sobre `public.vendedores`, com as mesmas colunas;
  - as views que dependem delas continuam respondendo.

O CI e o container `canastra-api` não têm Postgres: sem `B67F_PSQL` os testes pulam.
Para rodar no Postgres descartável (schema de produção + migrations a, b, d1 e e):

    B67F_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_analytics_b67f_pg.py

Cada cenário roda numa transação com ROLLBACK e usa ids com prefixo b67f1c6b-.
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

LEAD_PENDING = "b67f1c6b-0000-0000-0000-0000000000d1"
LEAD_ATACADO = "b67f1c6b-0000-0000-0000-0000000000d2"
LEAD_SEM_SCORE = "b67f1c6b-0000-0000-0000-0000000000d3"
VEND_JOAO = "b67f1c6b-0000-0000-0000-0000000000e1"
VEND_ARTHUR = "b67f1c6b-0000-0000-0000-0000000000e2"

# Score definitivo 10 (replace + clear), coerente com os CHECKs de lead_qualification_scores.
_SCORE_COLS = ("lead_id, segment, monthly_volume_kg, supplier_reason, purchase_timing, purchase_intent,"
               " normal_score, final_score, priority, is_provisional, source, rule_version")


def _score(lead: str) -> str:
    return (f"insert into public.lead_qualification_scores ({_SCORE_COLS}) values"
            f" ('{lead}', 'cafeteria', 20, 'replace', 'within_15_days', 'clear', 8, 10, 'maximum', false,"
            f" 'live', 'b67f-teste');\n")


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


def _cenario(corpo: str) -> list[str]:
    """Semeia 3 leads (pending com score, atacado com score, pending sem score), roda e desfaz."""
    out = _psql(f"""
begin;
insert into public.leads (id, phone, name, stage) values
  ('{LEAD_PENDING}', '5599700067001', 'Teste b67f pending', 'pending'),
  ('{LEAD_ATACADO}', '5599700067002', 'Teste b67f atacado', 'qualificando'),
  ('{LEAD_SEM_SCORE}', '5599700067003', 'Teste b67f sem score', 'pending');
update public.leads set segmento = 'atacado' where id = '{LEAD_ATACADO}';
{_score(LEAD_PENDING)}{_score(LEAD_ATACADO)}
{corpo}
rollback;
""")
    return [x.strip() for x in out.splitlines() if "=" in x]


# ── d1: diretório de score ────────────────────────────────────────────────────────
@_precisa_pg
def test_diretorio_mostra_lead_pending_com_score_e_esconde_sem_score():
    linhas = _cenario(f"""
select 'pending=' || count(*) from public.valeria_score_directory where lead_id = '{LEAD_PENDING}';
select 'atacado=' || count(*) from public.valeria_score_directory where lead_id = '{LEAD_ATACADO}';
select 'sem_score=' || count(*) from public.valeria_score_directory where lead_id = '{LEAD_SEM_SCORE}';
select 'final=' || final_score || '|rank=' || priority_rank from public.valeria_score_directory
 where lead_id = '{LEAD_PENDING}';
""")
    assert "pending=1" in linhas, linhas
    assert "atacado=1" in linhas, linhas
    assert "sem_score=0" in linhas, linhas
    assert "final=10|rank=4" in linhas, linhas


@_precisa_pg
def test_diretorio_mantem_as_colunas():
    out = _psql("""
select 'cols=' || string_agg(column_name, ',' order by ordinal_position)
  from information_schema.columns where table_schema = 'public' and table_name = 'valeria_score_directory';
""")
    esperado = ("cols=lead_id,name,phone,company,stage,status,last_interaction_at,traffic_type,utm_campaign,"
                "meta_ad_id,campaign_name,segment,monthly_volume_kg,supplier_reason,purchase_timing,"
                "purchase_intent,evidence,normal_score,final_score,priority,priority_rank,is_provisional,"
                "score_updated_at")
    assert out.strip() == esperado, out


# ── e: dim_lead ───────────────────────────────────────────────────────────────────
@_precisa_pg
def test_dim_lead_b2b_falso_para_lead_so_com_score():
    linhas = _cenario(f"""
select 'pending=' || b2b::text || '|' || coalesce(b2b_fonte, 'null') || '|' || coalesce(segmento, 'null')
  from analytics.dim_lead where lead_id = '{LEAD_PENDING}';
select 'atacado=' || b2b::text || '|' || coalesce(b2b_fonte, 'null') || '|' || coalesce(segmento, 'null')
  from analytics.dim_lead where lead_id = '{LEAD_ATACADO}';
""")
    assert "pending=false|null|null" in linhas, linhas
    assert "atacado=true|segmento|atacado" in linhas, linhas


@_precisa_pg
def test_dim_lead_b2b_por_pipeline():
    linhas = _cenario(f"""
insert into public.pipelines (id, name) values ('b67f1c6b-0000-0000-0000-0000000000a1', 'João - Atacado b67f');
insert into public.deals (lead_id, pipeline_id, title)
  values ('{LEAD_SEM_SCORE}', 'b67f1c6b-0000-0000-0000-0000000000a1', 'b67f');
select 'sem_score=' || b2b::text || '|' || coalesce(b2b_fonte, 'null')
  from analytics.dim_lead where lead_id = '{LEAD_SEM_SCORE}';
""")
    assert "sem_score=true|pipeline" in linhas, linhas


@_precisa_pg
def test_vw_leads_segue_dim_lead():
    linhas = _cenario(f"""
select 'pending=' || b2b::text || '|' || qualificado::text
  from analytics.vw_leads where lead_id = '{LEAD_PENDING}';
select 'atacado=' || b2b::text || '|' || qualificado::text || '|' || coalesce(criterio_qualificacao, 'null')
  from analytics.vw_leads where lead_id = '{LEAD_ATACADO}';
""")
    # Lead só com score não é B2B: sem repasse, não é qualificado. O atacado com score >= 5 é.
    assert "pending=false|false" in linhas, linhas
    assert "atacado=true|true|score" in linhas, linhas


# ── e: dim_vendedor ───────────────────────────────────────────────────────────────
@_precisa_pg
def test_dim_vendedor_lista_os_vendedores():
    linhas = _cenario(f"""
insert into auth.users (id, email) values
  ('{VEND_JOAO}', 'joao.b67f@teste.local'), ('{VEND_ARTHUR}', 'arthur.b67f@teste.local');
insert into public.vendedores (id, email, nome, apelidos, segmentos, atende_no_crm, ativo) values
  ('{VEND_JOAO}', 'joao.b67f@teste.local', 'Jõaozinho Brás', '{{"Joaozinho Bras"}}', '{{atacado,private_label}}', true, true),
  ('{VEND_ARTHUR}', 'arthur.b67f@teste.local', 'Arthurzinho', '{{}}', '{{exportacao}}', false, true);
select 'v=' || vendedor_chave || '|' || vendedor || '|' || user_id || '|' || email || '|'
       || array_to_string(emails, ',') || '|' || alerta_ambiguo::text
  from analytics.dim_vendedor where user_id in ('{VEND_JOAO}', '{VEND_ARTHUR}') order by vendedor_chave;
update public.leads set assigned_to = '{VEND_JOAO}' where id = '{LEAD_ATACADO}';
select 'resp=' || coalesce(vendedor_responsavel, 'null') from analytics.dim_lead where lead_id = '{LEAD_ATACADO}';
""")
    assert f"v=arthurzinho|Arthurzinho|{VEND_ARTHUR}|arthur.b67f@teste.local|arthur.b67f@teste.local|false" \
        in linhas, linhas
    assert f"v=joaozinho|Jõaozinho Brás|{VEND_JOAO}|joao.b67f@teste.local|joao.b67f@teste.local|false" \
        in linhas, linhas
    assert "resp=Jõaozinho Brás" in linhas, linhas


@_precisa_pg
def test_dim_vendedor_e_dim_lead_mantem_as_colunas():
    out = _psql("""
select table_name || '=' || string_agg(column_name || ':' || data_type, ',' order by ordinal_position)
  from information_schema.columns
 where table_schema = 'analytics' and table_name in ('dim_vendedor')
 group by table_name;
select 'dim_lead_b2b=' || string_agg(column_name || ':' || data_type, ',' order by ordinal_position)
  from information_schema.columns
 where table_schema = 'analytics' and table_name = 'dim_lead' and column_name in ('segmento', 'b2b', 'b2b_fonte');
select 'grant=' || has_table_privilege('consulta_ro', 'analytics.dim_vendedor', 'SELECT')::text
       || '|' || has_table_privilege('consulta_ro', 'analytics.dim_lead', 'SELECT')::text
       || '|' || has_table_privilege('consulta_ro', 'analytics.vw_leads', 'SELECT')::text;
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert ("dim_vendedor=vendedor_chave:text,vendedor:text,user_id:uuid,email:text,emails:ARRAY,"
            "alerta_ambiguo:boolean") in linhas, linhas
    assert "dim_lead_b2b=segmento:text,b2b:boolean,b2b_fonte:text" in linhas, linhas
    assert "grant=true|true|true" in linhas, linhas


@_precisa_pg
def test_views_dependentes_respondem():
    out = _psql("""
select 'ok=' || (select count(*) from analytics.vw_repasses) * 0
             + (select count(*) from analytics.fct_vendas) * 0
             + (select count(*) from analytics.vw_funil_mes) * 0
             + (select count(*) from analytics.vw_vendedores_semana) * 0
             + (select count(*) from analytics.vw_resposta_closer) * 0
             + (select count(*) from analytics.vw_clientes) * 0
             + (select count(*) from analytics.vw_campanhas_dia) * 0;
""")
    assert "ok=0" in out, out


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
