"""Backfills F2 (segmento), F3 (stage -> fase) e F4 (origem_cadastro/status) — cartão b67f1c6b.

Roda os scripts de scripts/leads_vendedor/ contra um Postgres DESCARTÁVEL com o schema de
produção e as migrations 20261022a..e aplicadas (a f só entra depois do F3):

    B67F_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_backfill_f2f3f4_b67f_pg.py

Os scripts fazem COMMIT de verdade, então cada teste semeia leads com id prefixo b67f1c6b-f
e, no fim, apaga esses leads e as tabelas backup_b67f_f2/f3/f4. Sem a env, pula.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

PSQL = os.environ.get("B67F_PSQL", "")
pytestmark = pytest.mark.skipif(not PSQL, reason="sem B67F_PSQL (Postgres descartável)")

RAIZ = Path(__file__).resolve().parents[2]
DIR = RAIZ / "scripts" / "leads_vendedor"
MIG_F = RAIZ / "supabase" / "migrations" / "20261022f_stage_fase_check.sql"

PFX = "b67f1c6b-f234-0000-0000-"
ESTAGIO_ANTIGO = "2026-01-02 03:04:05+00"


def _psql(sql: str, *args: str, ok: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", *args],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    if ok and r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r


def _script(nome: str, *args: str, ok: bool = True) -> subprocess.CompletedProcess:
    return _psql((DIR / nome).read_text(encoding="utf-8"), *args, ok=ok)


def _id(n: int) -> str:
    return f"{PFX}{n:012d}"


# (n, stage, segmento, channel, metadata.origem, status, origem_cadastro)
SEED = [
    (1, "atacado", None, "evolution", None, "imported", "inbound"),
    (2, "private_label", None, "evolution", "terceirizacao", "converted", "inbound"),
    (3, "consumo", None, "evolution", None, "imported", "inbound"),
    (4, "exportacao", None, "evolution", None, "imported", "inbound"),
    (5, "secretaria", None, "evolution", None, "imported", "inbound"),
    (6, "contato", None, "manual", None, "active", "inbound"),
    (7, "negociacao", None, "manual", None, "active", "inbound"),
    (8, "ja_chamado", None, "manual", None, "active", "inbound"),
    (9, "pending", None, "evolution", "atacado", "imported", "inbound"),
    (10, "novo", None, "bling", "bling_webhook", "ativo", "inbound"),
    (11, "pending", None, "manual", "reativacao_bling", "imported", "inbound"),
    (12, "perdido", None, "manual", "reativacao_bling", "imported", "manual"),  # não-inbound: F4 não toca
    (13, "novo", None, "evolution", "bling_webhook", "ativo", "inbound"),  # origem bling sem channel
]


def _semear() -> None:
    linhas = []
    for n, stage, seg, ch, orig, status, oc in SEED:
        meta = f"jsonb_build_object('origem', '{orig}')" if orig else "'{}'::jsonb"
        segv = f"'{seg}'" if seg else "null"
        linhas.append(
            f"('{_id(n)}', '55998671{n:05d}', 'Teste b67f F {n}', '{stage}', {segv}, '{ch}', {meta},"
            f" '{status}', '{oc}', '{ESTAGIO_ANTIGO}')"
        )
    _psql(
        "insert into public.leads (id, phone, name, stage, segmento, channel, metadata, status,"
        " origem_cadastro, entered_stage_at) values\n" + ",\n".join(linhas) + ";"
    )


def _limpar() -> None:
    _psql(
        f"delete from public.lead_events where lead_id::text like '{PFX}%';"
        f"delete from public.leads where id::text like '{PFX}%';"
        "drop table if exists public.backup_b67f_f2, public.backup_b67f_f3, public.backup_b67f_f4;"
    )


@pytest.fixture(autouse=True)
def _seed():
    _limpar()
    _semear()
    yield
    _limpar()


def _estado() -> dict[int, tuple]:
    out = _psql(
        "select id, stage, coalesce(segmento,'-'), origem_cadastro, status, entered_stage_at::text"
        f" from public.leads where id::text like '{PFX}%' order by id"
    ).stdout
    res = {}
    for linha in out.strip().splitlines():
        i, *resto = linha.split("|")
        res[int(i.rsplit("-", 1)[1])] = tuple(resto)
    return res


def _alterados(nome: str, *args: str) -> list[str]:
    r = _script(nome, *args)
    return [l for l in r.stderr.splitlines() if "alterados=" in l]


# ── F2 ─────────────────────────────────────────────────────────────────────────────

def test_f2_segmento_do_stage_idempotente_e_rollback():
    antes = _estado()
    _script("f2_segmento.sql")
    e = _estado()
    assert [e[n][1] for n in (1, 2, 3, 4)] == ["atacado", "private_label", "consumo", "exportacao"]
    # nada mais é inferido (nem metadata.origem 'atacado' do lead 9)
    assert all(e[n][1] == "-" for n in range(5, 14))
    assert all(e[n][0] == antes[n][0] for n in e)  # stage intacto
    assert _psql("select count(*) from public.backup_b67f_f2 where id::text like "
                 f"'{PFX}%'").stdout.strip() == "4"

    snap = _estado()
    assert any("alterados=0" in l for l in _alterados("f2_segmento.sql"))
    assert _estado() == snap

    _script("f2_rollback.sql")
    assert _estado() == antes
    _script("f2_rollback.sql")  # idempotente
    assert _estado() == antes


def test_f2_teto_estoura():
    antes = _estado()
    r = _script("f2_segmento.sql", "-v", "teto=1", ok=False)
    assert r.returncode != 0 and "acima do teto" in r.stderr
    assert _estado() == antes


def test_f2_rollback_recusa_se_f3_ja_rodou():
    _script("f2_segmento.sql")
    _script("f3_fase.sql")
    r = _script("f2_rollback.sql", ok=False)
    assert r.returncode != 0 and "F3" in r.stderr


# ── F3 ─────────────────────────────────────────────────────────────────────────────

def test_f3_exige_f2():
    antes = _estado()
    r = _script("f3_fase.sql", ok=False)
    assert r.returncode != 0 and "F2" in r.stderr
    assert _estado() == antes


def test_f3_fase_preserva_relogio_idempotente_rollback_e_migration_f():
    _script("f2_segmento.sql")
    antes = _estado()
    _script("f3_fase.sql")
    e = _estado()
    esperado = {1: "qualificando", 2: "qualificando", 3: "qualificando", 4: "qualificando",
                5: "triagem", 6: "qualificando", 7: "qualificando", 8: "qualificando",
                9: "pending", 10: "novo", 11: "pending", 12: "perdido", 13: "novo"}
    assert {n: e[n][0] for n in e} == esperado
    assert e[1][1] == "atacado"  # segmento fica
    # o trigger trg_update_entered_stage_at não pode zerar o relógio
    assert all(e[n][4] == antes[n][4] for n in e)

    snap = _estado()
    assert any("alterados=0" in l for l in _alterados("f3_fase.sql"))
    assert _estado() == snap

    # migration f passa depois do F3 (dentro de begin/rollback: no scratch ela não fica)
    mig = MIG_F.read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
    out = _psql(
        "begin;\n" + mig + "\nselect 'ok:' || count(*) from pg_constraint"
        " where conname = 'leads_stage_fase_check' and convalidated;\nrollback;"
    ).stdout
    assert "ok:1" in out

    _script("f3_rollback.sql")
    assert _estado() == antes
    _script("f3_rollback.sql")
    assert _estado() == antes


def test_migration_f_falha_antes_do_f3():
    mig = MIG_F.read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
    r = _psql("begin;\n" + mig + "\nrollback;", ok=False)
    assert r.returncode != 0 and "rodar F3 antes" in r.stderr


def test_f3_teto_estoura():
    _script("f2_segmento.sql")
    antes = _estado()
    r = _script("f3_fase.sql", "-v", "teto=2", ok=False)
    assert r.returncode != 0 and "acima do teto" in r.stderr
    assert _estado() == antes


# ── F4 ─────────────────────────────────────────────────────────────────────────────

def test_f4_origem_e_status_idempotente_e_rollback():
    antes = _estado()
    n_eventos = _psql(f"select count(*) from public.lead_events where lead_id::text like '{PFX}%'").stdout
    _script("f4_origem.sql")
    e = _estado()
    assert e[10][2:4] == ("bling_import", "active")
    assert e[13][2:4] == ("bling_import", "active")
    assert e[11][2:4] == ("reativacao_import", "imported")
    assert e[12][2:4] == ("manual", "imported")  # não era inbound
    assert all(e[n][2] == "inbound" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9))
    assert all(e[n][0] == antes[n][0] and e[n][4] == antes[n][4] for n in e)
    # o gatilho de entrada não reage a origem_cadastro/status
    assert _psql(f"select count(*) from public.lead_events where lead_id::text like '{PFX}%'").stdout == n_eventos

    snap = _estado()
    assert any("alterados=0" in l for l in _alterados("f4_origem.sql"))
    assert _estado() == snap

    _script("f4_rollback.sql")
    assert _estado() == antes
    _script("f4_rollback.sql")
    assert _estado() == antes


def test_f4_teto_estoura():
    antes = _estado()
    r = _script("f4_origem.sql", "-v", "teto=2", ok=False)
    assert r.returncode != 0 and "acima do teto" in r.stderr
    assert _estado() == antes


# ── Relatório ──────────────────────────────────────────────────────────────────────

def test_relatorio_segmento_inferivel_so_select():
    sql = (DIR / "relatorios" / "segmento_inferivel.sql").read_text(encoding="utf-8")
    codigo = " ".join(l.split("--")[0] for l in sql.lower().splitlines())
    for proibido in ("insert ", "update ", "delete ", "create ", "drop ", "alter ", "truncate "):
        assert proibido not in codigo
    out = _psql("begin read only;\n" + sql + "\nrollback;").stdout
    # lead 9: pending, metadata.origem 'atacado' -> inferível por origem
    assert _id(9) in out and "atacado" in out
