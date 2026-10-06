"""P6 — a migração 20261006c espelha o código: pares, toques e a chave do ajuste."""
import re
from pathlib import Path

import pytest

from app.follow_up import cadence_joao as C
from app.follow_up import service as S

SQL = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
       / "20261006c_followup_kit.sql")


@pytest.fixture(scope="module")
def sql():
    return SQL.read_text(encoding="utf-8")


def test_cada_funil_aceita_exatamente_as_cadencias_do_codigo(sql):
    for f in C.FUNIS:
        esperado = sorted(c.codigo for c in C.cadencias_do_funil(f.codigo))
        m = re.search(rf"funil\s*=\s*'{f.codigo}'\s+AND\s+cadencia\s+IN\s*\(([^)]*)\)",
                      sql, re.I)
        if not esperado:
            assert m is None, f.codigo
            continue
        assert m, f.codigo
        assert sorted(t.strip().strip("'") for t in m.group(1).split(",")) == esperado


def test_o_check_de_toques_bate_com_o_codigo(sql):
    maior: dict[str, int] = {}
    for f in C.FUNIS:
        for c in C.cadencias_do_funil(f.codigo):
            maior[c.codigo] = max(maior.get(c.codigo, 0), len(c.touches))
    for codigo, n in maior.items():
        if n == 1:
            assert re.search(rf"cadencia = '{codigo}'\s+AND\s+toque = 1", sql), codigo
        else:
            assert re.search(
                rf"cadencia = '{codigo}'\s+AND\s+toque BETWEEN 1 AND {n}\b", sql), codigo


def test_a_chave_do_ajuste_novo_e_as_antigas(sql):
    m = re.search(r"chave\s+IN\s*\(([^)]*)\)", sql, re.I)
    assert m
    chaves = {t.strip().strip("'") for t in m.group(1).split(",")}
    assert chaves == set(S.AJUSTES_PADRAO) | {S.AJUSTE_DIAS_SEM_PROSPECCAO}


def _comandos(sql: str) -> str:
    """O SQL sem os comentários `--` — o que de fato executa."""
    return "\n".join(linha.split("--", 1)[0] for linha in sql.splitlines())


def test_reexecutavel_e_nao_semeia_nem_apaga(sql):
    comandos = _comandos(sql)
    assert len(re.findall(r"DROP CONSTRAINT IF EXISTS", comandos)) == 3
    assert len(re.findall(r"ADD CONSTRAINT", comandos)) == 3
    for proibido in (r"\bINSERT\b", r"\bDELETE\b", r"DROP\s+TABLE", r"TRUNCATE",
                     r"\bUPDATE\b"):
        assert not re.search(proibido, comandos, re.I), proibido
    assert "follow_up_jobs" not in comandos
    assert re.search(r"^BEGIN;", comandos, re.M) and re.search(r"^COMMIT;", comandos, re.M)
    assert "NOTIFY pgrst" in comandos
