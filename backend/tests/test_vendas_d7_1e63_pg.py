"""Migrations 20261026a_1e63_vendas_d7_funcoes e 20261026c_1e63_fct_vendas (cartão 1e6381fe) num Postgres DE VERDADE.

Cobre (spec docs/superpowers/specs/2026-10-26-vendas-receita-d7-design.md, 3.4 e 3.5):
  - get_avg_repurchase_cycle_days: cancelada fora, intervalo em dias de calendário de Brasília,
    intervalo de 0 dia fora, lower() do vendedor;
  - get_leads_for_repurchase: lead só com cancelada não entra; MAX(sold_at) ignora cancelada;
  - get_leads_no_sale_in_stage: lead só com cancelada conta como "sem venda";
  - search_sales: devolve status e freight; grants iguais aos de produção;
  - analytics.fct_vendas: "Em devolução" registrada não é cancelada; vendedor por sold_by;
    vendedor_fonte gravado (bling_pedido, lead_assigned -> lead_responsavel, crm, sem); alerta_frete
    só para pedido Bling nunca relido (discount nulo); mesmas colunas e tipos.

O CI e o container `canastra-api` não têm Postgres: sem `E1E63_PSQL` os testes pulam.
Para rodar no Postgres descartável (mesma imagem de produção, supabase/postgres:17.6.1.136, com o
schema de produção via `pg_dump --schema-only -n public -n analytics` e as duas migrations; receita
em scripts/repasse_sla/scratch_pg.md, trocando o sufixo para 1e6381fe):

    E1E63_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-1e6381fe psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_vendas_d7_1e63_pg.py

Cada cenário roda numa transação com ROLLBACK e usa ids com prefixo 1e6381fe-.
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

PSQL = os.environ.get("E1E63_PSQL", "")

LEAD_A = "1e6381fe-0000-0000-0000-0000000000a1"
LEAD_B = "1e6381fe-0000-0000-0000-0000000000a2"
LEAD_C = "1e6381fe-0000-0000-0000-0000000000a3"
VEND_JOAO = "1e6381fe-0000-0000-0000-0000000000e1"
EMAIL_JOAO = "joao.1e63@teste.local"


def _sid(n: int) -> str:
    return f"1e6381fe-0000-0000-0000-{n:012d}"


def _precisa_pg(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(not PSQL, reason="sem E1E63_PSQL (Postgres descartável)")(fn)


def _psql(sql: str) -> str:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def _cenario(corpo: str) -> list[str]:
    """Semeia 3 leads e o vendedor João, roda o corpo e desfaz."""
    out = _psql(f"""
begin;
insert into public.leads (id, phone, name, stage, ai_enabled, entered_stage_at) values
  ('{LEAD_A}', '5599700063001', 'Teste 1e63 A', 'pending', true, '2030-01-01T12:00:00-03:00'),
  ('{LEAD_B}', '5599700063002', 'Teste 1e63 B', 'pending', true, '2030-01-01T12:00:00-03:00'),
  ('{LEAD_C}', '5599700063003', 'Teste 1e63 C', 'pending', true, '2030-01-01T12:00:00-03:00');
insert into auth.users (id, email) values ('{VEND_JOAO}', '{EMAIL_JOAO}');
insert into public.vendedores (id, email, nome, apelidos, segmentos, atende_no_crm, ativo)
  values ('{VEND_JOAO}', '{EMAIL_JOAO}', 'Joãozinho Umseis', '{{}}', '{{atacado}}', true, true);
{corpo}
rollback;
""")
    return [x.strip() for x in out.splitlines() if "=" in x]


def _venda(n: int, lead: str, quando: str, **cols) -> str:
    base = {"id": _sid(n), "lead_id": lead, "sold_at": quando, "value": "100", "product": "Café 1e63"}
    base.update(cols)
    nomes = ", ".join(base)
    valores = ", ".join("null" if v is None else f"'{v}'" for v in base.values())
    return f"insert into public.sales ({nomes}) values ({valores});\n"


# ── a: get_avg_repurchase_cycle_days ──────────────────────────────────────────────
@_precisa_pg
def test_ciclo_recompra_ignora_cancelada_e_intervalo_de_zero_dia():
    # 01/10 10h e 01/10 23h30 (mesmo dia em Brasília, já 02/10 em UTC) e 11/10; cancelada em 05/10.
    linhas = _cenario(
        _venda(1, LEAD_A, "2030-10-01T10:00:00-03:00", sold_by=EMAIL_JOAO)
        + _venda(2, LEAD_A, "2030-10-01T23:30:00-03:00", sold_by=EMAIL_JOAO)
        + _venda(3, LEAD_A, "2030-10-05T12:00:00-03:00", sold_by=EMAIL_JOAO, status="cancelada")
        + _venda(4, LEAD_A, "2030-10-11T12:00:00-03:00", sold_by=EMAIL_JOAO)
        + """
select 'media=' || coalesce(get_avg_repurchase_cycle_days('JOAO.1E63@Teste.Local')::text, 'null');
""")
    assert "media=10" in linhas, linhas


# ── a: get_leads_for_repurchase ───────────────────────────────────────────────────
@_precisa_pg
def test_recompra_ignora_lead_so_com_cancelada_e_cancelada_no_max():
    # A: só cancelada (antiga). B: venda boa antiga + cancelada recente (o MAX é a boa).
    # C: venda boa recente (depois do corte).
    linhas = _cenario(
        _venda(1, LEAD_A, "2030-01-10T12:00:00-03:00", status="cancelada")
        + _venda(2, LEAD_B, "2030-01-10T12:00:00-03:00")
        + _venda(3, LEAD_B, "2030-06-10T12:00:00-03:00", status="cancelada")
        + _venda(4, LEAD_C, "2030-06-10T12:00:00-03:00")
        + f"""
select 'ids=' || coalesce(string_agg(id::text, ',' order by id), '')
  from get_leads_for_repurchase('2030-03-01T00:00:00-03:00', 'prod', 'ambos')
 where id in ('{LEAD_A}', '{LEAD_B}', '{LEAD_C}');
""")
    assert f"ids={LEAD_B}" in linhas, linhas


# ── a: get_leads_no_sale_in_stage ─────────────────────────────────────────────────
@_precisa_pg
def test_sem_venda_na_etapa_conta_lead_so_com_cancelada():
    linhas = _cenario(
        _venda(1, LEAD_A, "2030-01-10T12:00:00-03:00", status="cancelada")
        + _venda(2, LEAD_B, "2030-01-10T12:00:00-03:00")
        + f"""
select 'ids=' || coalesce(string_agg(id::text, ',' order by id), '')
  from get_leads_no_sale_in_stage('pending', '2030-03-01T00:00:00-03:00', 'prod', 'ambos')
 where id in ('{LEAD_A}', '{LEAD_B}', '{LEAD_C}');
""")
    assert f"ids={LEAD_A},{LEAD_C}" in linhas, linhas


# ── a: search_sales ───────────────────────────────────────────────────────────────
@_precisa_pg
def test_search_sales_devolve_status_e_frete():
    linhas = _cenario(
        _venda(1, LEAD_A, "2030-01-10T12:00:00-03:00", product="Produto1e63xyz", status="cancelada",
               freight="12.50")
        + _venda(2, LEAD_B, "2030-01-11T12:00:00-03:00", product="Produto1e63xyz")
        + """
select 's=' || lead_name || '|' || coalesce(status, 'null') || '|' || coalesce(freight::text, 'null')
       || '|' || value || '|' || total_count
  from search_sales('produto1e63XYZ');
""")
    assert "s=Teste 1e63 A|cancelada|12.50|100.00|2" in linhas, linhas
    assert "s=Teste 1e63 B|registrada|0.00|100.00|2" in linhas, linhas


@_precisa_pg
def test_search_sales_assinatura_e_grants_de_producao():
    out = _psql("""
select 'ret=' || pg_get_function_result(p.oid) || '|args=' || pg_get_function_identity_arguments(p.oid)
  from pg_proc p where p.proname = 'search_sales';
select 'n=' || count(*) from pg_proc where proname = 'search_sales';
select 'acl=' || string_agg(g, ',' order by g) from (
  select coalesce(nullif(pg_get_userbyid(a.grantee), ''), 'PUBLIC') as g
    from pg_proc p, aclexplode(p.proacl) a where p.proname = 'search_sales' and a.privilege_type = 'EXECUTE'
    and a.grantee <> 0
  union all
  select 'PUBLIC' from pg_proc p, aclexplode(p.proacl) a where p.proname = 'search_sales' and a.grantee = 0
) x;
select 'def=' || prosecdef::text || '|' || array_to_string(proconfig, ',') from pg_proc where proname = 'search_sales';
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert ("ret=TABLE(id uuid, product text, value numeric, sold_at timestamp with time zone, notes text, "
            "lead_id uuid, lead_name text, lead_phone text, deal_id uuid, deal_title text, total_count bigint, "
            "status text, freight numeric)|args=search_query text, p_sold_after timestamp with time zone, "
            "p_sold_before timestamp with time zone, max_results integer, p_offset integer") in linhas, linhas
    assert "n=1" in linhas, linhas
    assert "acl=postgres,service_role" in linhas, linhas
    assert "def=true|search_path=public" in linhas, linhas


# ── c: analytics.fct_vendas ───────────────────────────────────────────────────────
_SEL_FCT = """
select 'f' || right(venda_id::text, 2) || '=' || cancelada::text || '|' || receita || '|'
       || coalesce(vendedor, 'null') || '|' || vendedor_fonte || '|' || coalesce(alerta_frete, 'null')
       || '|' || coalesce(alerta_vendedor, 'null')
  from analytics.fct_vendas where venda_id::text like '1e6381fe-%' order by venda_id;
"""


@_precisa_pg
def test_fct_vendas_em_devolucao_registrada_nao_e_cancelada():
    linhas = _cenario(
        _venda(1, LEAD_A, "2030-01-10T12:00:00-03:00", origin="bling", status="registrada",
               bling_situacao_nome="Em devolução", freight="10", discount="0", sold_by=EMAIL_JOAO,
               vendedor_fonte="bling_pedido")
        + _venda(2, LEAD_A, "2030-01-11T12:00:00-03:00", origin="bling", status="cancelada",
                 bling_situacao_nome="Cancelado", freight="10", discount="0")
        + _SEL_FCT)
    assert "f01=false|90.00|Joãozinho Umseis|bling_pedido|null|null" in linhas, linhas
    assert ("f02=true|0|null|sem|null|pedido sem vendedor no Bling e sem fonte na cascata D8"
            in linhas), linhas


@_precisa_pg
def test_fct_vendas_vendedor_fonte_e_alerta_frete():
    linhas = _cenario(
        f"update public.leads set assigned_to = '{VEND_JOAO}' where id in ('{LEAD_A}', '{LEAD_B}', '{LEAD_C}');\n"
        # bling nunca relido (discount nulo), sem vendedor: o responsável do lead NÃO entra mais.
        + _venda(1, LEAD_A, "2030-01-10T12:00:00-03:00", origin="bling", freight="0")
        # bling relido, frete 0, vendedor pela cascata (lead_assigned).
        + _venda(2, LEAD_B, "2030-01-10T12:00:00-03:00", origin="bling", freight="0", discount="5",
                 sold_by=EMAIL_JOAO, vendedor_fonte="lead_assigned")
        # venda do CRM com sold_by (caixa diferente) e sem fonte.
        + _venda(3, LEAD_C, "2030-01-10T12:00:00-03:00", origin="crm", sold_by="Joao.1e63@Teste.local")
        # manual com sold_by sem cadastro de vendedor.
        + _venda(4, LEAD_C, "2030-01-12T12:00:00-03:00", origin="manual", sold_by="ninguem.1e63@teste.local")
        + _SEL_FCT)
    assert ("f01=false|100.00|null|sem|pedido Bling nunca relido (desconto e frete não gravados): "
            "a receita pode incluir o frete|pedido sem vendedor no Bling e sem fonte na cascata D8") in linhas, linhas
    assert ("f02=false|100.00|Joãozinho Umseis|lead_responsavel|null|"
            "vendedor pelo responsável do lead (cascata D8, lead_assigned)") in linhas, linhas
    assert "f03=false|100.00|Joãozinho Umseis|crm|null|null" in linhas, linhas
    assert ("f04=false|100.00|null|sem|null|sold_by sem vendedor cadastrado (vendedores/bling_seller_map)"
            in linhas), linhas


@_precisa_pg
def test_fct_vendas_mantem_colunas_tipos_e_grant():
    out = _psql("""
select 'cols=' || string_agg(column_name || ':' || data_type, ',' order by ordinal_position)
  from information_schema.columns where table_schema = 'analytics' and table_name = 'fct_vendas';
select 'grant=' || has_table_privilege('consulta_ro', 'analytics.fct_vendas', 'SELECT')::text
       || '|' || array_to_string(reloptions, ',') from pg_class where oid = 'analytics.fct_vendas'::regclass;
select 'coment=' || (obj_description('analytics.fct_vendas'::regclass) like '%bling_pedido%')::text;
select 'dep=' || (select count(*) from analytics.vw_vendedores_semana) * 0
             + (select count(*) from analytics.vw_clientes) * 0
             + (select count(*) from analytics.vw_funil_mes) * 0
             + (select count(*) from analytics.vw_produtos_mes) * 0
             + (select count(*) from analytics.vw_campanhas_dia) * 0
             + (select count(*) from analytics.vw_disparos) * 0;
""")
    linhas = [x.strip() for x in out.splitlines() if "=" in x]
    assert ("cols=venda_id:uuid,lead_id:uuid,vendida_em:timestamp with time zone,venda_data:date,origem:text,"
            "conta_bling:text,status:text,situacao_bling:text,cancelada:boolean,valor_bruto:numeric,"
            "frete:numeric,receita:numeric,vendedor:text,vendedor_fonte:text,b2b:boolean,segmento:text,"
            "eh_lead_marketing:boolean,plataforma_primeiro_toque:text,campanha_id_primeiro_toque:text,"
            "campanha_primeiro_toque:text,dentro_janela_atribuicao:boolean,dias_desde_entrada:integer,"
            "tem_itens:boolean,tem_deal:boolean,numero_compra:integer,alerta_frete:text,"
            "alerta_vendedor:text") in linhas, linhas
    assert "grant=true|security_invoker=true" in linhas, linhas
    assert "coment=true" in linhas, linhas
    assert "dep=0" in linhas, linhas


if __name__ == "__main__":
    if not PSQL:
        print("defina E1E63_PSQL")
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
