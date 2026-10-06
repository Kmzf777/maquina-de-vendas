"""Backfill da linha do tempo (P3): montagem do SQL e CLI. Execução real em
test_cs_p3_timeline_pg.py::test_backfill_idempotente."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "backfill_lead_events", RAIZ / "scripts" / "timeline" / "backfill_lead_events.py"
)
bf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bf  # @dataclass procura o módulo em sys.modules
_spec.loader.exec_module(bf)

MIG = (RAIZ / "supabase" / "migrations" / "20261006b_lead_timeline_triggers.sql").read_text(
    encoding="utf-8"
)

COMPLETO = bf.Esquema(p0=True, arquivo=True, p3=True)
PROD_HOJE = bf.Esquema(p0=False, arquivo=False, p3=False)


def test_dry_run_e_read_only_e_nao_insere():
    sql = bf.montar_sql(COMPLETO, aplicar=False)
    assert sql.startswith("begin transaction read only;")
    assert sql.rstrip().endswith("rollback;")
    assert "insert into" not in sql.lower()


def test_aplicar_insere_com_on_conflict_e_commita():
    sql = bf.montar_sql(COMPLETO, aplicar=True)
    assert sql.startswith("begin;")
    assert "insert into public.lead_events" in sql
    assert "on conflict (dedupe_key) where dedupe_key is not null do nothing" in sql
    assert sql.rstrip().endswith("commit;")


def test_aplicar_sem_migracoes_recusa():
    with pytest.raises(ValueError):
        bf.montar_sql(PROD_HOJE, aplicar=True)
    with pytest.raises(ValueError):
        bf.montar_sql(bf.Esquema(p0=True, arquivo=True, p3=False), aplicar=True)


def test_sem_p0_le_referrals_do_log_e_nao_usa_colunas_novas():
    sql = bf.montar_sql(PROD_HOJE, aplicar=False)
    assert "from public.meta_webhook_logs" in sql
    assert "meta_referrals_arquivo" not in sql
    assert "e.dedupe_key = c.dedupe_key" not in sql
    assert "e.occurred_at between" not in sql
    assert "public.fn_" not in sql


def test_com_p0_le_do_arquivo_e_marca_existentes():
    sql = bf.montar_sql(COMPLETO, aplicar=False)
    assert "from public.meta_referrals_arquivo" in sql
    assert "meta_webhook_logs" not in sql
    assert "e.dedupe_key = c.dedupe_key" in sql


@pytest.mark.parametrize("esq", [COMPLETO, PROD_HOJE, bf.Esquema(p0=True, arquivo=False, p3=False)])
def test_todos_os_tokens_substituidos(esq):
    assert "__" not in bf.montar_sql(esq, aplicar=False)


@pytest.mark.parametrize(
    "no_trigger, no_backfill",
    [
        ("'entrada:lead:' || new.id || ':inicial'", "'entrada:lead:' || l.id || ':inicial'"),
        ("'venda:' || new.id", "'venda:' || s.id"),
        ("'venda_cancelada:' || new.id", "'venda_cancelada:' || s.id"),
        ("'disparo:' || new.id", "'disparo:' || bl.id"),
        ("'etapa:' || new.id || ':criado'", "'etapa:' || d.id || ':criado'"),
        (
            "'etapa:' || new.id || ':' || new.stage_id || ':' || extract(epoch from v_quando)::text",
            "'etapa:' || d.id || ':' || d.stage_id || ':' || extract(epoch from d.entered_stage_at)::text",
        ),
    ],
)
def test_dedupe_key_do_backfill_e_a_mesma_do_trigger(no_trigger, no_backfill):
    assert no_trigger in MIG
    assert no_backfill in bf.montar_sql(COMPLETO, aplicar=True)


def test_main_aplicar_sem_migracoes_sai_com_2():
    chamadas = []

    def rodar(sql):
        chamadas.append(sql)
        return json.dumps({"p0": False, "arquivo": False, "p3": False}) + "\n"

    assert bf.main(["--aplicar"], rodar=rodar) == 2
    assert len(chamadas) == 1  # só a detecção de esquema


def test_main_dry_run_imprime_contagens(capsys):
    respostas = iter([
        json.dumps({"p0": False, "arquivo": False, "p3": False}),
        json.dumps({
            "eventos": [{"event_type": "venda", "candidatos": 10, "existentes": 0}],
            "referrals": {"total": 5, "sem_lead": 1, "ambiguos": 0, "colapsados": 1, "ja_cobertos": 0},
            "inseridos": {},
        }),
    ])
    assert bf.main([], rodar=lambda sql: next(respostas)) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "meta_webhook_logs" in out
    assert "venda" in out and "10" in out


def test_ultimo_json_ignora_linhas_vazias():
    assert bf.ultimo_json('\n\n{"a": 1}\n\n') == {"a": 1}
