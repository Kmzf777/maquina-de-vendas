"""Runner de migrações: ledger schema_migrations, baseline, apply ordenado e drift."""
import hashlib

import pytest

from scripts import apply_migrations as am


class FakeExecutor:
    """Simula o endpoint SQL: registra queries e mantém um ledger em memória."""

    def __init__(self, ledger=None, fail_on_contains=None):
        self.queries: list[str] = []
        self.ledger: list[dict] = list(ledger or [])
        self.fail_on_contains = fail_on_contains

    def __call__(self, query: str):
        self.queries.append(query)
        if self.fail_on_contains and self.fail_on_contains in query:
            raise RuntimeError(f"sql error em: {query[:40]}")
        q = query.strip().lower()
        if q.startswith("select filename"):
            return list(self.ledger)
        if q.startswith("insert into public.schema_migrations"):
            # extrai (filename, sha) do VALUES — suficiente p/ os testes
            import re
            for m in re.finditer(r"\('([^']+)',\s*'([^']+)',\s*(true|false)\)", query):
                self.ledger.append({"filename": m.group(1), "sha256": m.group(2)})
        return []


def _mkdir_with(tmp_path, files: dict[str, str]):
    d = tmp_path / "migrations"
    d.mkdir()
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_pending_ordena_lexicograficamente(tmp_path):
    d = _mkdir_with(tmp_path, {
        "20260101_b.sql": "select 2;",
        "001_a.sql": "select 1;",
        "20260102_c.sql": "select 3;",
    })
    ex = FakeExecutor()
    plan = am.build_plan(d, ex)
    assert [p.filename for p in plan.pending] == ["001_a.sql", "20260101_b.sql", "20260102_c.sql"]


def test_apply_pula_ja_aplicadas_e_registra_novas(tmp_path):
    d = _mkdir_with(tmp_path, {
        "001_a.sql": "create table a();",
        "002_b.sql": "create table b();",
    })
    ex = FakeExecutor(ledger=[{"filename": "001_a.sql", "sha256": _sha("create table a();")}])
    applied = am.cmd_apply(d, ex, dry_run=False)
    assert applied == ["002_b.sql"]
    assert not any("create table a()" in q for q in ex.queries)  # já aplicada não reexecuta
    assert any("create table b()" in q for q in ex.queries)
    assert {r["filename"] for r in ex.ledger} == {"001_a.sql", "002_b.sql"}


def test_apply_para_no_primeiro_erro_sem_registrar(tmp_path):
    d = _mkdir_with(tmp_path, {
        "001_a.sql": "create table a();",
        "002_boom.sql": "create table boom();",
        "003_c.sql": "create table c();",
    })
    ex = FakeExecutor(fail_on_contains="boom")
    with pytest.raises(am.MigrationError):
        am.cmd_apply(d, ex, dry_run=False)
    # 001 aplicada e registrada; 002 falhou sem registrar; 003 nunca executou
    assert {r["filename"] for r in ex.ledger} == {"001_a.sql"}
    assert not any("create table c()" in q for q in ex.queries)


def test_apply_dry_run_nao_executa_nem_registra(tmp_path):
    d = _mkdir_with(tmp_path, {"001_a.sql": "create table a();"})
    ex = FakeExecutor()
    applied = am.cmd_apply(d, ex, dry_run=True)
    assert applied == ["001_a.sql"]
    assert not any("create table a()" in q for q in ex.queries)
    assert ex.ledger == []


def test_baseline_registra_tudo_sem_executar(tmp_path):
    d = _mkdir_with(tmp_path, {
        "001_a.sql": "create table a();",
        "002_b.sql": "create table b();",
    })
    ex = FakeExecutor()
    count = am.cmd_baseline(d, ex)
    assert count == 2
    assert {r["filename"] for r in ex.ledger} == {"001_a.sql", "002_b.sql"}
    assert not any("create table" in q and "schema_migrations" not in q for q in ex.queries)


def test_baseline_recusa_ledger_ja_populado(tmp_path):
    d = _mkdir_with(tmp_path, {"001_a.sql": "select 1;"})
    ex = FakeExecutor(ledger=[{"filename": "000_x.sql", "sha256": "abc"}])
    with pytest.raises(am.MigrationError, match="ledger já populado"):
        am.cmd_baseline(d, ex)


def test_status_detecta_drift_de_sha(tmp_path):
    d = _mkdir_with(tmp_path, {"001_a.sql": "conteudo NOVO (editado depois de aplicado)"})
    ex = FakeExecutor(ledger=[{"filename": "001_a.sql", "sha256": _sha("conteudo original")}])
    plan = am.build_plan(d, ex)
    assert plan.drift == ["001_a.sql"]
    assert plan.pending == []
