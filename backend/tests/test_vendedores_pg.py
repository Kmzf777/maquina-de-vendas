"""Migration 20261022a_vendedores (cartão b67f1c6b) contra um Postgres DE VERDADE.

Cobre `fn_vendedor_id` (uuid, e-mail, nome/apelido sem acento, 1º token, ambíguo),
os CHECKs de `vendedores` e a FK nova `deals.assigned_to -> vendedores(id)`.

Sem `B67F_PSQL` os testes pulam (CI e container não têm Postgres). Para rodar no
Postgres descartável com o schema de produção + a migration:

    B67F_PSQL='ssh -i ~/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_vendedores_pg.py

Cada cenário roda numa transação com ROLLBACK e usa ids com prefixo b67f1c6b-.
"""
from __future__ import annotations

import os
import shlex
import subprocess

try:
    import pytest
except ImportError:  # host sem pytest: o runner do __main__ cuida
    pytest = None

PSQL = os.environ.get("B67F_PSQL", "")

JOAO = "b67f1c6b-0000-0000-0000-00000000a001"
ARTHUR = "b67f1c6b-0000-0000-0000-00000000a002"
RAFAEL = "b67f1c6b-0000-0000-0000-00000000a003"
ANA1 = "b67f1c6b-0000-0000-0000-00000000a004"
ANA2 = "b67f1c6b-0000-0000-0000-00000000a005"
FORA = "b67f1c6b-0000-0000-0000-00000000a0ff"  # existe em auth.users, não em vendedores
LEAD = "b67f1c6b-0000-0000-0000-00000000b001"
DEAL = "b67f1c6b-0000-0000-0000-00000000d001"


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


SEED = f"""
insert into auth.users (id, email) values
  ('{JOAO}', 'b67f-joao@x.com'), ('{ARTHUR}', 'b67f-arthur@x.com'), ('{RAFAEL}', 'b67f-rafael@x.com'),
  ('{ANA1}', 'b67f-ana1@x.com'), ('{ANA2}', 'b67f-ana2@x.com'), ('{FORA}', 'b67f-fora@x.com');
insert into public.vendedores (id, email, nome, apelidos, segmentos, atende_no_crm, ativo) values
  ('{JOAO}', 'b67f-joao@x.com', 'João Brás', array['Joao Bras', 'João - Café Canastra'], array['atacado','private_label'], true, true),
  ('{ARTHUR}', 'b67f-arthur@x.com', 'Arthur', array['Arthur - Café Canastra'], array['exportacao'], false, true),
  ('{RAFAEL}', 'b67f-rafael@x.com', 'Rafael', '{{}}', '{{}}', true, false);
"""


def _cenario(corpo: str) -> str:
    return _psql(f"begin;\n{SEED}\n{corpo}\nrollback;\n")


def _valor(sql: str) -> str:
    return _cenario(sql).strip().splitlines()[-1].strip()


def _fn(chave: str) -> str:
    c = chave.replace("'", "''")
    return _valor(f"select coalesce(public.fn_vendedor_id('{c}')::text, 'NULL');")


@_precisa_pg
def test_fn_vendedor_id_por_uuid():
    assert _fn(JOAO) == JOAO
    assert _fn(FORA) == "NULL"  # uuid válido mas fora de vendedores


@_precisa_pg
def test_fn_vendedor_id_por_email_maiusculo():
    assert _fn("B67F-JOAO@X.com") == JOAO
    assert _fn("  b67f-arthur@x.com ") == ARTHUR


@_precisa_pg
def test_fn_vendedor_id_por_nome_sem_acento_e_apelido():
    assert _fn("Joao Bras") == JOAO
    assert _fn("joão  brás") == JOAO
    assert _fn("Joao - Cafe Canastra") == JOAO
    assert _fn("Arthur - Café Canastra") == ARTHUR
    assert _fn("arthur") == ARTHUR
    assert _fn("João") == JOAO  # 1º token do nome
    assert _fn("Rafael") == RAFAEL  # inativo também resolve (histórico)


@_precisa_pg
def test_fn_vendedor_id_nada_ou_ambiguo_e_null():
    assert _fn("Vendedor") == "NULL"
    assert _fn("") == "NULL"
    assert _valor("select coalesce(public.fn_vendedor_id(null)::text, 'NULL');") == "NULL"
    ambiguo = _valor(f"""
insert into public.vendedores (id, email, nome) values
  ('{ANA1}', 'b67f-ana1@x.com', 'Ana Souza'), ('{ANA2}', 'b67f-ana2@x.com', 'Ana Lima');
select coalesce(public.fn_vendedor_id('Ana')::text, 'NULL');""")
    assert ambiguo == "NULL"


@_precisa_pg
def test_email_precisa_ser_minusculo():
    with pytest.raises(AssertionError, match="check"):
        _cenario(f"insert into public.vendedores (id, email, nome) values ('{FORA}', 'Fora@X.com', 'Fora');")


@_precisa_pg
def test_deals_assigned_to_e_uuid_com_fk():
    assert _valor("""select data_type from information_schema.columns
                     where table_schema='public' and table_name='deals' and column_name='assigned_to';""") == "uuid"
    base = f"""
insert into public.leads (id, phone, name) values ('{LEAD}', '5599700000067', 'Teste b67f1c6b');
"""
    ok = _valor(base + f"""
insert into public.deals (id, lead_id, title, assigned_to) values ('{DEAL}', '{LEAD}', 't', '{JOAO}');
select assigned_to::text from public.deals where id = '{DEAL}';""")
    assert ok == JOAO
    with pytest.raises(AssertionError, match="foreign key"):
        _cenario(base + f"insert into public.deals (id, lead_id, title, assigned_to) values ('{DEAL}', '{LEAD}', 't', '{FORA}');")


@_precisa_pg
def test_bling_seller_map_tem_vendedor_id():
    assert _valor("""select data_type from information_schema.columns
                     where table_schema='public' and table_name='bling_seller_map' and column_name='vendedor_id';""") == "uuid"


@_precisa_pg
def test_authenticated_le_mas_nao_escreve():
    saida = _cenario(f"""
set local role authenticated;
select count(*) from public.vendedores where id = '{JOAO}';
do $$ begin
  begin
    insert into public.vendedores (id, email, nome) values ('{FORA}', 'b67f-fora@x.com', 'Fora');
    raise exception 'authenticated conseguiu inserir';
  exception when insufficient_privilege then null;
  end;
end $$;
""")
    assert saida.strip().splitlines()[0] == "1"


if __name__ == "__main__":
    import sys
    if not PSQL:
        sys.exit("defina B67F_PSQL")
    falhas = 0
    for nome, fn in list(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", nome)
            except Exception as exc:  # noqa: BLE001
                falhas += 1
                print("FAIL", nome, exc)
    sys.exit(1 if falhas else 0)
