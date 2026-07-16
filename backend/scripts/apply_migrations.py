"""Runner leve de migrações — pasta única supabase/migrations/ + ledger schema_migrations.

Processo (Opt5, spec 2026-07-10-migrations-runner-design.md):
  1. Nova migração = novo arquivo `YYYYMMDD_slug.sql` em supabase/migrations/,
     no MESMO commit da feature que depende dela.
  2. NUNCA editar arquivo já aplicado (drift de sha256 vira warning) — crie outro.
  3. Aplicação é deliberada (humana), mas registrada e ordenada:

     python -m scripts.apply_migrations --status              # aplicadas vs pendentes
     python -m scripts.apply_migrations --baseline            # adota banco EXISTENTE: registra
                                                              # tudo no ledger SEM executar (1x)
     python -m scripts.apply_migrations --apply [--dry-run]   # aplica só o que falta, em ordem

Env: SUPABASE_PROJECT_REF + SUPABASE_ACCESS_TOKEN (PAT do ambiente-alvo).
Execução via Supabase Management API (POST /v1/projects/{ref}/database/query) com
User-Agent explícito — urllib/clientes sem UA tomam Cloudflare 1010.
Sem Alembic/psycopg: httpx (já no requirements) e stdlib.
"""
import argparse
import hashlib
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("apply_migrations")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "supabase" / "migrations"
API_BASE = "https://api.supabase.com"
USER_AGENT = "canastra-apply-migrations/1.0"

LEDGER_DDL = """
create table if not exists public.schema_migrations (
  filename text primary key,
  sha256 text not null,
  applied_at timestamptz not null default now(),
  baseline boolean not null default false
);
""".strip()


class MigrationError(RuntimeError):
    pass


@dataclass
class MigrationFile:
    filename: str
    path: Path
    sha256: str


@dataclass
class Plan:
    applied: list[str] = field(default_factory=list)
    pending: list[MigrationFile] = field(default_factory=list)
    drift: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _esc(value: str) -> str:
    return value.replace("'", "''")


def make_executor(project_ref: str, token: str):
    """Executor real: 1 chamada HTTP por statement/arquivo."""
    import httpx

    def run_sql(query: str):
        resp = httpx.post(
            f"{API_BASE}/v1/projects/{project_ref}/database/query",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
            json={"query": query},
            timeout=120,
        )
        if resp.status_code >= 400:
            raise MigrationError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    return run_sql


def _list_local(migrations_dir: Path) -> list[MigrationFile]:
    files = sorted(migrations_dir.glob("*.sql"), key=lambda p: p.name)
    return [MigrationFile(p.name, p, _sha256(p)) for p in files]


def _ensure_ledger(run_sql) -> None:
    run_sql(LEDGER_DDL)


def _fetch_ledger(run_sql) -> dict[str, str]:
    rows = run_sql("select filename, sha256 from public.schema_migrations") or []
    return {r["filename"]: r["sha256"] for r in rows}


def _record(run_sql, mf: MigrationFile, baseline: bool) -> None:
    run_sql(
        "insert into public.schema_migrations (filename, sha256, baseline) "
        f"values ('{_esc(mf.filename)}', '{_esc(mf.sha256)}', {'true' if baseline else 'false'})"
    )


def build_plan(migrations_dir: Path, run_sql) -> Plan:
    _ensure_ledger(run_sql)
    ledger = _fetch_ledger(run_sql)
    plan = Plan()
    for mf in _list_local(migrations_dir):
        if mf.filename in ledger:
            plan.applied.append(mf.filename)
            if ledger[mf.filename] != mf.sha256:
                plan.drift.append(mf.filename)
        else:
            plan.pending.append(mf)
    return plan


def cmd_status(migrations_dir: Path, run_sql) -> Plan:
    plan = build_plan(migrations_dir, run_sql)
    log.info("aplicadas: %d | pendentes: %d", len(plan.applied), len(plan.pending))
    for mf in plan.pending:
        log.info("  pendente: %s", mf.filename)
    for name in plan.drift:
        log.warning(
            "  DRIFT: %s foi EDITADO após aplicado (sha difere do ledger) — "
            "crie um arquivo novo em vez de editar", name,
        )
    return plan


def cmd_baseline(migrations_dir: Path, run_sql) -> int:
    """Adoção em banco que JÁ TEM o estado: registra tudo sem executar nada."""
    _ensure_ledger(run_sql)
    ledger = _fetch_ledger(run_sql)
    if ledger:
        raise MigrationError(
            f"ledger já populado ({len(ledger)} linhas) — baseline é passo único; "
            "use --status/--apply"
        )
    files = _list_local(migrations_dir)
    for mf in files:
        _record(run_sql, mf, baseline=True)
    log.info("baseline: %d arquivos registrados SEM execução", len(files))
    return len(files)


def cmd_apply(migrations_dir: Path, run_sql, dry_run: bool) -> list[str]:
    plan = build_plan(migrations_dir, run_sql)
    for name in plan.drift:
        log.warning("DRIFT em %s (arquivo editado após aplicado)", name)
    applied: list[str] = []
    for mf in plan.pending:
        if dry_run:
            log.info("[dry-run] aplicaria: %s", mf.filename)
            applied.append(mf.filename)
            continue
        log.info("aplicando: %s", mf.filename)
        try:
            run_sql(mf.path.read_text(encoding="utf-8"))
        except Exception as exc:
            # Para no primeiro erro: nada depois deste arquivo executa, e ele
            # NÃO entra no ledger (rerodar recomeça exatamente daqui).
            raise MigrationError(f"falha em {mf.filename}: {exc}") from exc
        _record(run_sql, mf, baseline=False)
        applied.append(mf.filename)
    if not plan.pending:
        log.info("nada pendente — banco em dia com supabase/migrations/")
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="lista aplicadas vs pendentes (default)")
    group.add_argument("--baseline", action="store_true", help="registra tudo sem executar (adoção, 1x)")
    group.add_argument("--apply", action="store_true", help="aplica pendentes em ordem lexicográfica")
    parser.add_argument("--dry-run", action="store_true", help="com --apply: só lista o que aplicaria")
    args = parser.parse_args()

    ref = os.environ.get("SUPABASE_PROJECT_REF", "")
    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
    if not ref or not token:
        log.error("defina SUPABASE_PROJECT_REF e SUPABASE_ACCESS_TOKEN (PAT do ambiente-alvo)")
        return 2

    run_sql = make_executor(ref, token)
    try:
        if args.baseline:
            cmd_baseline(MIGRATIONS_DIR, run_sql)
        elif args.apply:
            cmd_apply(MIGRATIONS_DIR, run_sql, dry_run=args.dry_run)
        else:
            cmd_status(MIGRATIONS_DIR, run_sql)
    except MigrationError as exc:
        log.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
