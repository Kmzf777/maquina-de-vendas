"""Backfills F1 (vendedores) e F6 (vendedor de deals/leads) do cartão b67f1c6b contra Postgres DE VERDADE.

Os scripts fazem COMMIT, então não dá para rodar dentro de begin/rollback. Por isso os testes
usam um banco SÓ deles, `b67f1c6b_f16`, no container descartável, criado com o schema do banco
`postgres` do scratch (pg_dump -s, que já tem as migrations 20261022a..e). Cada teste zera as
tabelas tocadas e semeia dados mínimos.

    B67F_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_backfill_f1f6_b67f_pg.py

Sem B67F_PSQL os testes pulam.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

PSQL = os.environ.get("B67F_PSQL", "")
DB = "b67f1c6b_f16"
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "leads_vendedor"

pytestmark = pytest.mark.skipif(not PSQL, reason="sem B67F_PSQL (Postgres descartável)")

JOAO = "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6"
ARTHUR = "c504390c-cdd3-46b8-acfc-13883fb40fe3"
RAFAEL = "39032499-c6b5-4531-9e41-d33ecae89e68"
COMERCIAL2 = "7e5b4085-0819-484e-a566-f4cd194cf048"
KELWIN = "af949c1b-18d2-421d-bcb7-224d1efe3c22"
PIPE_ARTHUR = "4a0c9f7f-47ac-45b1-a760-e2ffc976ccf9"
PIPE_JOAO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PIPE_VALERIA = "bda5a3c1-d12b-4df8-bf94-f0e1b9bb0bdb"
PIPE_BLACK = "8988e852-2836-4add-b023-4db4d6cd0e6e"


def L(n: int) -> str:
    return f"b67f1c6b-0000-0000-0000-0000000000{n:02d}"


def D(n: int) -> str:
    return f"b67f1c6b-0000-0000-0000-00000000d0{n:02d}"


def _run(sql: str, *, db: str = DB, vars: dict | None = None, check: bool = True):
    cmd = shlex.split(PSQL) + ["-d", db, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    for k, v in (vars or {}).items():
        cmd += ["-v", f"{k}={v}"]
    r = subprocess.run(cmd, input=sql, text=True, capture_output=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r


def q(sql: str) -> str:
    return _run(sql).stdout.strip()


def script(nome: str, **vars) -> subprocess.CompletedProcess:
    return _run((SCRIPTS / nome).read_text(encoding="utf-8"), vars=vars, check=False)


def _garantir_db() -> None:
    existe = _run(f"select 1 from pg_database where datname = '{DB}'", db="postgres").stdout.strip()
    if existe:
        return
    partes = shlex.split(PSQL)
    prefixo = partes[: partes.index("psql")]  # ssh ... docker exec -i <container>
    clone = (
        f"psql -U postgres -h localhost -d postgres -X -q -c 'create database {DB}' && "
        f"pg_dump -s -O -x -U postgres -h localhost postgres | "
        f"psql -U postgres -h localhost -d {DB} -X -q -o /dev/null"
    )
    subprocess.run(prefixo + ["sh", "-c", shlex.quote(clone)], check=True, capture_output=True)


SEED = f"""
drop table if exists public.backup_b67f_f1, public.backup_b67f_f6;
truncate public.deals, public.pipelines, public.bling_seller_map, public.bling_sellers,
         public.vendedores, public.leads, auth.users cascade;
insert into auth.users (id, email) values
  ('{JOAO}', 'joao@cafecanastra.com'), ('{ARTHUR}', 'arthur@cafecanastra.com'),
  ('{RAFAEL}', 'rafael@cafecanastra.com'), ('{COMERCIAL2}', 'Comercial2@cafecanastra.com'),
  ('{KELWIN}', 'kelwin@cafecanastra.com');
insert into public.bling_sellers (id, nome, account) values
  (5845108828, 'Arthur Silva Boaventura', 'default'),
  (11712213732, 'Joao', 'default'), (12256085549, 'Joao', 'secundaria');
insert into public.bling_seller_map (user_email, bling_seller_id, account) values
  ('joao@cafecanastra.com', 11712213732, 'default'),
  ('joao@cafecanastra.com', 12256085549, 'secundaria');
insert into public.pipelines (id, name, owner_user_id) values
  ('{PIPE_ARTHUR}', 'Arthur - Exportação', null),
  ('{PIPE_JOAO}', 'João - Atacado', '{JOAO}'),
  ('{PIPE_VALERIA}', 'Valeria - Atacado', null),
  ('{PIPE_BLACK}', 'Blacklist', '{JOAO}');
insert into public.leads (id, phone, stage, assigned_to, metadata) values
  ('{L(1)}', '5599700000001', 'pending', null,
     '{{"handoff": {{"vendedor": "Joao Bras", "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(2)}', '5599700000002', 'exportacao', null,
     '{{"handoff": {{"vendedor": "Arthur", "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(3)}', '5599700000003', 'pending', null,
     '{{"handoff": {{"vendedor": "Vendedor", "vendedor_id": null, "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(4)}', '5599700000004', 'consumo', null,
     '{{"handoff": {{"vendedor": "Joao Bras", "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(5)}', '5599700000005', 'qualificando', '{JOAO}',
     '{{"handoff": {{"vendedor": "João Brás", "vendedor_id": "{JOAO}", "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(6)}', '5599700000006', 'pending', '{KELWIN}',
     '{{"handoff": {{"vendedor": "Joao Bras", "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(7)}', '5599700000007', 'triagem', null,
     '{{"handoff": {{"vendedor": "Joao Bras", "vendedor_id": null, "segmento": "secretaria", "motivo": "x", "at": "2026-10-01"}}}}'),
  ('{L(8)}', '5599700000008', 'pending', null, '{{}}'),
  ('{L(9)}', '5599700000009', 'pending', null,
     '{{"handoff": {{"vendedor": "joão  brás", "vendedor_id": null, "segmento": "pending", "motivo": "x", "at": "2026-10-01"}}}}');
"""

DEALS = f"""
insert into public.deals (id, lead_id, title, pipeline_id, assigned_to) values
  ('{D(1)}', '{L(8)}', 'd1', '{PIPE_JOAO}', null),
  ('{D(2)}', '{L(2)}', 'd2', '{PIPE_ARTHUR}', null),
  ('{D(3)}', '{L(5)}', 'd3', '{PIPE_VALERIA}', null),
  ('{D(4)}', '{L(1)}', 'd4', '{PIPE_VALERIA}', null),
  ('{D(5)}', '{L(3)}', 'd5', '{PIPE_VALERIA}', null),
  ('{D(6)}', '{L(8)}', 'd6', '{PIPE_JOAO}', '{ARTHUR}'),
  ('{D(7)}', '{L(5)}', 'd7', '{PIPE_BLACK}', null),
  ('{D(8)}', '{L(8)}', 'd8', '{PIPE_BLACK}', null);
"""

FOTO_F1 = """
select coalesce((select string_agg(format('%s|%s|%s|%s|%s|%s|%s', id, email, nome, apelidos, segmentos,
                                          atende_no_crm, ativo), ';' order by id) from public.vendedores), '')
    || '#' || (select string_agg(format('%s|%s|%s|%s', user_email, account, bling_seller_id, vendedor_id),
                                 ';' order by user_email, account) from public.bling_seller_map)
    || '#' || (select string_agg(format('%s|%s', id, owner_user_id), ';' order by id) from public.pipelines);
"""

FOTO_F6 = """
select (select string_agg(format('%s|%s', id, assigned_to), ';' order by id) from public.deals)
    || '#' || (select string_agg(format('%s|%s|%s', id, assigned_to, metadata), ';' order by id) from public.leads);
"""


@pytest.fixture(autouse=True)
def _seed():
    _garantir_db()
    q(SEED)
    yield


def _ok(r: subprocess.CompletedProcess) -> str:
    assert r.returncode == 0, r.stderr
    return r.stderr


# ---------------------------------------------------------------- F1

def test_f1_popula_vendedores_mapa_e_dono_do_funil():
    log = _ok(script("f1_vendedores.sql"))
    assert "F1 alvo=8" in log

    linhas = q("select id, email, nome, apelidos, segmentos, atende_no_crm, ativo "
               "from public.vendedores order by email").splitlines()
    assert linhas == [
        f"{ARTHUR}|arthur@cafecanastra.com|Arthur|{{\"Arthur - Café Canastra\",\"Arthur Silva Boaventura\"}}"
        "|{exportacao}|f|t",
        f"{COMERCIAL2}|comercial2@cafecanastra.com|Comercial 2|{{}}|{{}}|t|f",
        f"{JOAO}|joao@cafecanastra.com|João Brás|{{\"Joao Bras\",\"João - Café Canastra\",Joao}}"
        "|{atacado,private_label}|t|t",
        f"{RAFAEL}|rafael@cafecanastra.com|Rafael|{{}}|{{}}|t|f",
    ]
    assert q("select user_email, account, bling_seller_id, vendedor_id from public.bling_seller_map "
             "order by 1, 2").splitlines() == [
        f"arthur@cafecanastra.com|default|5845108828|{ARTHUR}",
        f"joao@cafecanastra.com|default|11712213732|{JOAO}",
        f"joao@cafecanastra.com|secundaria|12256085549|{JOAO}",
    ]
    assert q(f"select owner_user_id from public.pipelines where id = '{PIPE_ARTHUR}'") == ARTHUR
    assert q(f"select owner_user_id from public.pipelines where id = '{PIPE_VALERIA}'") == ""
    assert q("select public.fn_vendedor_id('Joao Bras')") == JOAO
    assert q("select public.fn_vendedor_id('Vendedor')") == ""
    assert q("select count(*) from public.backup_b67f_f1") == "8"


def test_f1_segunda_execucao_nao_muda_nada():
    _ok(script("f1_vendedores.sql"))
    antes = q(FOTO_F1)
    log = _ok(script("f1_vendedores.sql"))
    assert "F1 alvo=0" in log
    assert q(FOTO_F1) == antes


def test_f1_rollback_devolve_o_estado_e_e_idempotente():
    antes = q(FOTO_F1)
    _ok(script("f1_vendedores.sql"))
    _ok(script("f1_rollback.sql"))
    assert q(FOTO_F1) == antes
    _ok(script("f1_rollback.sql"))
    assert q(FOTO_F1) == antes


def test_f1_nao_mexe_em_dono_de_funil_ja_preenchido():
    q(f"update public.pipelines set owner_user_id = '{KELWIN}' where id = '{PIPE_ARTHUR}'")
    log = _ok(script("f1_vendedores.sql"))
    assert "F1 alvo=7" in log
    assert q(f"select owner_user_id from public.pipelines where id = '{PIPE_ARTHUR}'") == KELWIN


def test_f1_sem_vendedor_bling_do_arthur_nao_insere_mapa():
    q("delete from public.bling_sellers where id = 5845108828")
    log = _ok(script("f1_vendedores.sql"))
    assert "5845108828" in log
    assert q("select count(*) from public.bling_seller_map where user_email like 'arthur%'") == "0"


def test_f1_teto_estoura_sem_gravar():
    antes = q(FOTO_F1)
    r = script("f1_vendedores.sql", teto=3)
    assert r.returncode != 0
    assert "F1 acima do teto" in r.stderr
    assert q(FOTO_F1) == antes
    assert q("select to_regclass('public.backup_b67f_f1') is null") == "t"


# ---------------------------------------------------------------- F6

def _f6_pronto():
    _ok(script("f1_vendedores.sql"))
    q(DEALS)


def test_f6_preenche_deals_e_leads_so_onde_inequivoco():
    _f6_pronto()
    log = _ok(script("f6_vendedor.sql"))
    assert "F6 leads alvo=3" in log
    assert "F6 deals alvo=3" in log

    deals = dict(l.split("|") for l in q("select id, assigned_to from public.deals").splitlines())
    assert deals[D(1)] == JOAO      # dono do funil João - Atacado
    assert deals[D(2)] == ARTHUR    # dono do funil Arthur - Exportação (gravado no F1)
    assert deals[D(3)] == JOAO      # funil sem dono -> assigned_to que o lead já tinha
    assert deals[D(4)] == ""        # funil sem dono, lead só ganhou vendedor no F6 -> fica
    assert deals[D(5)] == ""        # lead sem vendedor
    assert deals[D(6)] == ARTHUR    # já preenchido: não mexe
    assert deals[D(7)] == ""        # Blacklist: nem pelo lead
    assert deals[D(8)] == ""        # Blacklist: nem pelo dono do funil

    leads = {l.split("|")[0]: l.split("|")[1:] for l in q(
        "select id, coalesce(assigned_to::text, ''), coalesce(metadata->'handoff'->>'vendedor_id', ''), "
        "metadata->'handoff'->>'vendedor' from public.leads").splitlines()}
    assert leads[L(1)] == [JOAO, JOAO, "Joao Bras"]
    assert leads[L(2)] == [ARTHUR, ARTHUR, "Arthur"]
    assert leads[L(3)] == ["", "", "Vendedor"]          # nome não resolve
    assert leads[L(4)] == ["", "", "Joao Bras"]         # consumo: João não atende
    assert leads[L(5)] == [JOAO, JOAO, "João Brás"]     # já tinha
    assert leads[L(6)] == [KELWIN, "", "Joao Bras"]     # já tem assigned_to: não mexe
    assert leads[L(7)] == ["", "", "Joao Bras"]         # secretaria: João não atende
    assert leads[L(9)] == [JOAO, JOAO, "joão  brás"]    # vendedor_id null -> preenchido
    assert q(f"select metadata->'handoff'->>'motivo' from public.leads where id = '{L(1)}'") == "x"


def test_f6_segunda_execucao_nao_muda_nada():
    _f6_pronto()
    _ok(script("f6_vendedor.sql"))
    antes = q(FOTO_F6)
    log = _ok(script("f6_vendedor.sql"))
    assert "F6 leads alvo=0" in log and "F6 deals alvo=0" in log
    assert q(FOTO_F6) == antes


def test_f6_rollback_devolve_o_estado_e_e_idempotente():
    _f6_pronto()
    antes = q(FOTO_F6)
    _ok(script("f6_vendedor.sql"))
    _ok(script("f6_rollback.sql"))
    assert q(FOTO_F6) == antes
    _ok(script("f6_rollback.sql"))
    assert q(FOTO_F6) == antes
    # com o F6 desfeito (e o deal semeado com o Arthur limpo), o F1 também desfaz
    q(f"update public.deals set assigned_to = null where id = '{D(6)}'")
    _ok(script("f1_rollback.sql"))
    assert q("select count(*) from public.vendedores") == "0"


def test_f6_teto_estoura_sem_gravar():
    _f6_pronto()
    antes = q(FOTO_F6)
    r = script("f6_vendedor.sql", teto_deals=1)
    assert r.returncode != 0 and "F6 deals acima do teto" in r.stderr
    r = script("f6_vendedor.sql", teto_leads=1)
    assert r.returncode != 0 and "F6 leads acima do teto" in r.stderr
    assert q(FOTO_F6) == antes


def test_relatorio_vendedores_ambiguos():
    _f6_pronto()
    _ok(script("f6_vendedor.sql"))
    r = _run((SCRIPTS / "relatorios" / "vendedores_ambiguos.sql").read_text(encoding="utf-8"))
    linhas = [l for l in r.stdout.splitlines() if l.startswith("b67f1c6b-")]
    por_lead = {l.split("|")[0]: l for l in linhas}
    assert set(por_lead) == {L(3), L(4), L(7)}
    assert "nome nao resolve" in por_lead[L(3)]
    assert "vendedor nao atende o segmento" in por_lead[L(4)]
    assert "vendedor nao atende o segmento" in por_lead[L(7)]
    blacklist = [l for l in r.stdout.splitlines() if l.startswith("blacklist|")]
    assert sorted(l.split("|")[1] for l in blacklist) == [D(7), D(8)]
