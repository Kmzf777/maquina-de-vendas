"""Migrations 20261022b_segmento e 20261022f_stage_fase_check (cartão b67f1c6b) num Postgres DE VERDADE.

Cobre `leads.segmento` (CHECK), `fn_lead_b2b` (segmento, funil, CNPJ no Bling) e a pré-checagem
da migration f (falha com stage fora das fases; passa depois do F3).

Sem `B67F_PSQL` os testes pulam. Para rodar no Postgres descartável (com a migration b aplicada):

    B67F_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_segmento_pg.py

Cada cenário roda numa transação com ROLLBACK e usa ids com prefixo b67f1c6b-.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

try:
    import pytest
except ImportError:  # host sem pytest: o runner do __main__ cuida
    pytest = None

PSQL = os.environ.get("B67F_PSQL", "")
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"

LEAD = "b67f1c6b-0000-0000-0000-0000000000b1"
PIPE = "b67f1c6b-0000-0000-0000-0000000000a1"
BLING_ID = 998877001


def _precisa_pg(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(not PSQL, reason="sem B67F_PSQL (Postgres descartável)")(fn)


def _psql(sql: str, *, falha_ok: bool = False) -> str:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    if r.returncode != 0:
        if falha_ok:
            return "ERRO:" + (r.stderr.strip() or r.stdout.strip())
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


def _corpo_migration(nome: str) -> str:
    """Corpo da migration sem BEGIN/COMMIT, para rodar dentro da transação do cenário."""
    sql = (MIGRATIONS / nome).read_text(encoding="utf-8")
    return re.sub(r"(?im)^\s*(begin|commit)\s*;\s*$", "", sql)


def _b2b(seed: str, *, segmento: str = "null", stage: str = "pending") -> str:
    out = _psql(f"""
begin;
insert into public.leads (id, phone, name, stage, segmento)
  values ('{LEAD}', '5599700000b67', 'Teste b67f1c6b', '{stage}', {segmento});
{seed}
select 'b2b=' || public.fn_lead_b2b('{LEAD}');
rollback;
""")
    return next(x.strip() for x in out.splitlines() if x.startswith("b2b="))


@_precisa_pg
def test_b2b_por_segmento():
    assert _b2b("", segmento="'atacado'") == "b2b=true"
    assert _b2b("", segmento="'private_label'") == "b2b=true"
    assert _b2b("", segmento="'consumo'") == "b2b=false"
    assert _b2b("", segmento="'exportacao'") == "b2b=false"


@_precisa_pg
def test_b2b_por_funil_atacado_ou_pl():
    for nome in ("João - Atacado", "Valeria - Private Label"):
        seed = f"""
insert into public.pipelines (id, name) values ('{PIPE}', '{nome}');
insert into public.deals (lead_id, title, pipeline_id) values ('{LEAD}', 't', '{PIPE}');
"""
        assert _b2b(seed) == "b2b=true", nome
    seed = f"""
insert into public.pipelines (id, name) values ('{PIPE}', 'Valeria - Consumo');
insert into public.deals (lead_id, title, pipeline_id) values ('{LEAD}', 't', '{PIPE}');
"""
    assert _b2b(seed) == "b2b=false"


@_precisa_pg
def test_b2b_por_cnpj_via_lead_bling_contacts():
    seed = f"""
insert into public.bling_contacts (account, id, nome, doc_digits) values ('casa', {BLING_ID}, 'X', '12345678000199');
insert into public.lead_bling_contacts (lead_id, account, bling_contact_id) values ('{LEAD}', 'casa', {BLING_ID});
"""
    assert _b2b(seed, segmento="'consumo'") == "b2b=true"


@_precisa_pg
def test_b2b_por_cnpj_via_leads_bling_contact_id():
    seed = f"""
insert into public.bling_contacts (account, id, nome, doc_digits) values ('default', {BLING_ID}, 'X', '12345678000199');
update public.leads set bling_contact_id = {BLING_ID} where id = '{LEAD}';
"""
    assert _b2b(seed) == "b2b=true"


@_precisa_pg
def test_b2b_falso_para_cpf_e_consumo_sem_cnpj():
    seed = f"""
insert into public.bling_contacts (account, id, nome, doc_digits) values ('default', {BLING_ID}, 'X', '12345678901');
insert into public.lead_bling_contacts (lead_id, account, bling_contact_id) values ('{LEAD}', 'default', {BLING_ID});
update public.leads set bling_contact_id = {BLING_ID} where id = '{LEAD}';
"""
    assert _b2b(seed, segmento="'consumo'") == "b2b=false"
    assert _b2b("", segmento="'consumo'") == "b2b=false"
    # lead inexistente: falso, não NULL
    out = _psql("select 'b2b=' || public.fn_lead_b2b('b67f1c6b-0000-0000-0000-0000000000ff');")
    assert "b2b=false" in out


@_precisa_pg
def test_check_de_segmento_recusa_secretaria():
    out = _psql(f"""
begin;
insert into public.leads (id, phone, name, segmento) values ('{LEAD}', '5599700000b67', 'T', 'secretaria');
rollback;
""", falha_ok=True)
    assert out.startswith("ERRO:") and "segmento" in out, out


@_precisa_pg
def test_migration_b_idempotente():
    corpo = _corpo_migration("20261022b_segmento.sql")
    _psql("begin;\n" + corpo + "\n" + corpo + "\nrollback;")


@_precisa_pg
def test_grants_fn_lead_b2b():
    out = _psql("""
select 'auth=' || has_function_privilege('authenticated', 'public.fn_lead_b2b(uuid)', 'EXECUTE');
select 'sr=' || has_function_privilege('service_role', 'public.fn_lead_b2b(uuid)', 'EXECUTE');
select 'ro=' || has_function_privilege('consulta_ro', 'public.fn_lead_b2b(uuid)', 'EXECUTE');
""")
    linhas = [x.strip() for x in out.splitlines()]
    assert {"auth=true", "sr=true", "ro=true"} <= set(linhas), linhas


@_precisa_pg
def test_migration_f_falha_com_stage_fora_das_fases():
    corpo = _corpo_migration("20261022f_stage_fase_check.sql")
    out = _psql(f"""
begin;
insert into public.leads (id, phone, name, stage) values ('{LEAD}', '5599700000b67', 'T', 'atacado');
{corpo}
rollback;
""", falha_ok=True)
    assert out.startswith("ERRO:") and "F3" in out, out


@_precisa_pg
def test_migration_f_passa_depois_do_f3_e_e_idempotente():
    corpo = _corpo_migration("20261022f_stage_fase_check.sql")
    out = _psql(f"""
begin;
insert into public.leads (id, phone, name, stage) values ('{LEAD}', '5599700000b67', 'T', 'atacado');
update public.leads set stage = 'qualificando', segmento = 'atacado' where id = '{LEAD}';
{corpo}
{corpo}
select 'def=' || column_default from information_schema.columns
 where table_schema = 'public' and table_name = 'leads' and column_name = 'stage';
select 'chk=' || count(*) from pg_constraint
 where conrelid = 'public.leads'::regclass and conname = 'leads_stage_fase_check' and convalidated;
rollback;
""")
    linhas = [x.strip() for x in out.splitlines()]
    assert "def='pending'::text" in linhas, linhas
    assert "chk=1" in linhas, linhas


@_precisa_pg
def test_migration_f_recusa_stage_secretaria():
    corpo = _corpo_migration("20261022f_stage_fase_check.sql")
    out = _psql(f"""
begin;
{corpo}
insert into public.leads (id, phone, name, stage) values ('{LEAD}', '5599700000b67', 'T', 'secretaria');
rollback;
""", falha_ok=True)
    assert out.startswith("ERRO:") and "leads_stage_fase_check" in out, out


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
