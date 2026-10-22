"""Backfills F5 (entrada "Orgânico" / meta_ad_id) e F7 (evento `qualificado`) — cartão b67f1c6b.

Roda os scripts de scripts/leads_vendedor/ contra um Postgres DESCARTÁVEL com o schema de
produção e as migrations 20261022a..e aplicadas:

    B67F_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_backfill_f5f7_b67f_pg.py

Os scripts fazem COMMIT de verdade, então cada teste semeia linhas com id prefixo
b67f1c6b-f57 e, no fim, apaga essas linhas e as tabelas backup_b67f_f5/f7. Sem a env, pula.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

PSQL = os.environ.get("B67F_PSQL", "")
pytestmark = pytest.mark.skipif(not PSQL, reason="sem B67F_PSQL (Postgres descartável)")

DIR = Path(__file__).resolve().parents[2] / "scripts" / "leads_vendedor"
PFX = "b67f1c6b-f570-0000-0000-"
VEND = "b67f1c6b-f570-0000-0000-0000000000aa"


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


def _conv(n: int) -> str:
    return f"{PFX}{n + 500:012d}"


def _notice(r: subprocess.CompletedProcess, chave: str) -> str:
    linhas = [l for l in r.stderr.splitlines() if chave in l]
    assert linhas, r.stderr
    return linhas[-1].split(chave, 1)[1].split()[0]


def _limpar() -> None:
    _psql(
        f"delete from public.lead_qualification_scores where lead_id::text like '{PFX}%';"
        f"delete from public.messages where conversation_id::text like '{PFX}%';"
        f"delete from public.conversations where id::text like '{PFX}%';"
        f"delete from public.lead_events where lead_id::text like '{PFX}%';"
        f"delete from public.leads where id::text like '{PFX}%';"
        f"delete from public.vendedores where id::text like '{PFX}%';"
        f"delete from auth.users where id::text like '{PFX}%';"
        "drop table if exists public.backup_b67f_f5, public.backup_b67f_f7;"
    )


def _lead(n: int, *, created: str = "2026-08-10 12:00:00+00", origem: str = "inbound",
          extra_cols: str = "", extra_vals: str = "", user_msg: bool = True) -> str:
    sql = (
        f"insert into public.leads (id, phone, name, origem_cadastro, created_at{extra_cols})"
        f" values ('{_id(n)}', '55998757{n:05d}', 'Teste b67f F57 {n}', '{origem}', '{created}'{extra_vals});"
        f"insert into public.conversations (id, lead_id) values ('{_conv(n)}', '{_id(n)}');"
    )
    if user_msg:
        sql += (f"insert into public.messages (lead_id, conversation_id, role, content, created_at)"
                f" values ('{_id(n)}', '{_conv(n)}', 'user', 'oi', '{created}');")
    return sql


def _marcador(n: int, ts: str, vendedor: str, motivo: str, mid: str | None = None) -> str:
    idcol, idval = ("id, ", f"'{mid}', ") if mid else ("", "")
    return (f"insert into public.messages ({idcol}lead_id, conversation_id, role, content, created_at)"
            f" values ({idval}'{_id(n)}', '{_conv(n)}', 'system',"
            f" '[encaminhar_humano] Lead encaminhado para {vendedor}: {motivo}', '{ts}');")


@pytest.fixture(autouse=True)
def _limpeza():
    _limpar()
    yield
    _limpar()


# ── F5 ─────────────────────────────────────────────────────────────────────────────

def _semear_f5() -> None:
    _psql(
        _lead(1)                                                             # alvo: Orgânico
        + _lead(2, created="2026-06-30 12:00:00+00")                         # antes de julho
        + _lead(3, user_msg=False)                                           # sem msg do lead
        + _lead(4, extra_cols=", ja_era_cliente", extra_vals=", true")       # já era cliente
        + _lead(5, origem="bling_import")                                    # importado
        + _lead(6, extra_cols=", utm_source", extra_vals=", 'instagram'")    # tem rastreio
        + _lead(7)                                                           # já tem entrada
        + _lead(8, created="2026-10-06 02:36:57+00",                         # alvo: meta_ad_id
                extra_cols=", meta_ad_id", extra_vals=", '120200000000000001'")
        # o gatilho novo já grava a entrada no INSERT: simula os leads de antes da migration
        + f"delete from public.lead_events where lead_id::text like '{PFX}%' and lead_id <> '{_id(7)}';"
    )


def _entradas() -> dict[int, tuple]:
    out = _psql(
        "select lead_id, new_value, source, occurred_at = (select created_at from public.leads l"
        " where l.id = e.lead_id), dedupe_key = 'entrada:lead:' || lead_id || ':inicial',"
        " coalesce(metadata->>'sem_rastreio','-'), coalesce(metadata->>'meta_ad_id','-')"
        f" from public.lead_events e where event_type = 'entrada' and lead_id::text like '{PFX}%'"
    ).stdout
    res = {}
    for linha in out.strip().splitlines():
        lid, *resto = linha.split("|")
        res[int(lid.rsplit("-", 1)[1])] = tuple(resto)
    return res


def test_f5_grava_entrada_idempotente_e_rollback():
    _semear_f5()
    antes = _entradas()
    assert set(antes) == {7}

    r = _script("f5_entrada_organico.sql")
    assert _notice(r, "F5 alvo=") == "2"
    assert _notice(r, "F5 alterados=") == "2"
    depois = _entradas()
    assert set(depois) == {1, 7, 8}
    assert depois[1] == ("Orgânico", "inbound", "t", "t", "true", "-")
    assert depois[8] == ("Meta Ads", "ctwa", "t", "t", "-", "120200000000000001")
    assert depois[7] == antes[7]

    r2 = _script("f5_entrada_organico.sql")
    assert _notice(r2, "F5 alvo=") == "0"
    assert _notice(r2, "F5 alterados=") == "0"
    assert _entradas() == depois

    rb = _script("f5_rollback.sql")
    assert _notice(rb, "F5 rollback apagados=") == "2"
    assert _entradas() == antes
    rb2 = _script("f5_rollback.sql")
    assert _notice(rb2, "F5 rollback apagados=") == "0"


def test_f5_teto_estoura_sem_gravar():
    _semear_f5()
    r = _script("f5_entrada_organico.sql", "-v", "teto=1", ok=False)
    assert r.returncode != 0
    assert "F5 acima do teto: 2 > 1" in r.stderr
    assert set(_entradas()) == {7}


# ── F7 ─────────────────────────────────────────────────────────────────────────────

M3 = f"{PFX}0000000003e1"


def _semear_f7() -> None:
    _psql(
        f"insert into auth.users (id, email) values ('{VEND}', 'joao.b67f@example.com');"
        f"insert into public.vendedores (id, email, nome, apelidos, segmentos)"
        f" values ('{VEND}', 'joao.b67f@example.com', 'João Brás', '{{Joao Bras}}', '{{atacado}}');"
        + "".join(_lead(n, extra_cols=", segmento", extra_vals=", 'atacado'") for n in (1, 2, 3, 4, 5, 6, 7))
        # 1: 1º repasse excluído (IA fora), 2º ok -> qualificado no 2º, vendedor pelo nome
        + _marcador(1, "2026-08-01 10:00:00+00", "Joao Bras",
                    "IA temporariamente indisponível — atendimento encaminhado ao humano")
        + _marcador(1, "2026-08-02 10:00:00+00", "Joao Bras", "atacado qualificado")
        # 2: só escalonamento -> nada
        + _marcador(2, "2026-08-01 10:00:00+00", "Joao Bras", "escalonamento: cliente reclamou")
        # 3: marcador + evento repasse (fonte preferida: source, segmento, vendedor_id)
        + _marcador(3, "2026-08-03 10:00:00+00", "Vendedor",
                    "bot de botões da ValerIA: lead pediu atendimento do vendedor", mid=M3)
        + "insert into public.lead_events (lead_id, event_type, source, occurred_at, dedupe_key, metadata)"
          f" values ('{_id(3)}', 'repasse', 'button_flow', '2026-08-03 10:00:00+00', 'repasse:{M3}',"
          f" jsonb_build_object('motivo', 'bot de botões da ValerIA: lead pediu atendimento do vendedor',"
          f" 'segmento', 'private_label', 'vendedor', 'Vendedor', 'vendedor_id', '{VEND}'));"
        # 4: score >= 5 definitivo sem repasse -> criterio score
        + "insert into public.lead_qualification_scores (lead_id, segment, monthly_volume_kg, supplier_reason,"
          " purchase_timing, purchase_intent, normal_score, final_score, priority, is_provisional, source,"
          " rule_version, updated_at)"
          f" values ('{_id(4)}', 'cafeteria', 20, 'second_supplier', 'within_15_days', 'clear', 6, 6, 'high',"
          " false, 'live', 'v1', '2026-09-01 12:00:00+00'),"
          # 5: score provisório (sem volume) -> nada
          f" ('{_id(5)}', 'cafeteria', null, null, 'within_15_days', 'clear', 5, 5, 'high',"
          " true, 'live', 'v1', '2026-09-01 12:00:00+00');"
        # 6: já tem o evento qualificado -> intocado
        + _marcador(6, "2026-08-01 10:00:00+00", "Joao Bras", "atacado qualificado")
        + "insert into public.lead_events (lead_id, event_type, source, occurred_at, dedupe_key, metadata)"
          f" values ('{_id(6)}', 'qualificado', 'ia', '2026-08-01 10:00:00+00', 'qualificado:{_id(6)}',"
          " jsonb_build_object('criterio', 'repasse'));"
        # 7: marcador de texto ok, mas o carimbo do MESMO repasse diz IA fora -> nada
        + _marcador(7, "2026-08-05 10:00:00+00", "Joao Bras", "encaminhado")
        + "update public.leads set metadata = jsonb_build_object('handoff', jsonb_build_object("
          "'at', '2026-08-05T07:00:30-03:00', 'motivo', 'IA temporariamente indisponível'))"
          f" where id = '{_id(7)}';"
    )


def _qualificados() -> dict[int, tuple]:
    out = _psql(
        "select lead_id, source, occurred_at::text, metadata->>'criterio', coalesce(metadata->>'segmento','-'),"
        " coalesce(metadata->>'b2b','-'), coalesce(metadata->>'motivo','-'), coalesce(metadata->>'vendedor_id','-')"
        f" from public.lead_events where event_type = 'qualificado' and lead_id::text like '{PFX}%'"
    ).stdout
    res = {}
    for linha in out.strip().splitlines():
        lid, *resto = linha.split("|")
        res[int(lid.rsplit("-", 1)[1])] = tuple(resto)
    return res


def test_f7_grava_qualificado_idempotente_e_rollback():
    _semear_f7()
    antes = _qualificados()
    assert set(antes) == {6}

    r = _script("f7_qualificado.sql")
    assert _notice(r, "F7 alvo=") == "3"
    assert _notice(r, "F7 alterados=") == "3"
    depois = _qualificados()
    assert set(depois) == {1, 3, 4, 6}
    assert depois[1] == ("ia", "2026-08-02 10:00:00+00", "repasse", "atacado", "true",
                         "atacado qualificado", VEND)
    assert depois[3] == ("button_flow", "2026-08-03 10:00:00+00", "repasse", "private_label", "true",
                         "bot de botões da ValerIA: lead pediu atendimento do vendedor", VEND)
    assert depois[4] == ("score", "2026-09-01 12:00:00+00", "score", "atacado", "true", "-", "-")
    assert depois[6] == antes[6]

    r2 = _script("f7_qualificado.sql")
    assert _notice(r2, "F7 alvo=") == "0"
    assert _notice(r2, "F7 alterados=") == "0"
    assert _qualificados() == depois

    rb = _script("f7_rollback.sql")
    assert _notice(rb, "F7 rollback apagados=") == "3"
    assert _qualificados() == antes
    rb2 = _script("f7_rollback.sql")
    assert _notice(rb2, "F7 rollback apagados=") == "0"


def test_f7_teto_estoura_sem_gravar():
    _semear_f7()
    r = _script("f7_qualificado.sql", "-v", "teto=2", ok=False)
    assert r.returncode != 0
    assert "F7 acima do teto: 3 > 2" in r.stderr
    assert set(_qualificados()) == {6}
