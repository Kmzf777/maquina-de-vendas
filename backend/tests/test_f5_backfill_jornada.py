"""scripts/f5_jornada/backfill_jornada.py: simulação por padrão, grava só com --aplicar.

O SQL de verdade foi rodado no PGlite (Postgres em WASM) com o esquema mínimo em 06/11/2026:
simulação, aplicação e segunda aplicação (0 entradas novas, idempotente)."""
import importlib.util
import json
from pathlib import Path

import pytest

_ARQ = Path(__file__).resolve().parents[2] / "scripts" / "f5_jornada" / "backfill_jornada.py"
_spec = importlib.util.spec_from_file_location("backfill_jornada", _ARQ)
bj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bj)

RES = {"entradas_novas": 2, "entradas_por_canal": {"WhatsApp direto": 2}, "leads_janela": 6, "mudam": 3,
       "transicoes": [{"de": "Sem rastreio", "para": "Cliente antigo", "n": 1}],
       "sem_rastreio_antes": 3, "sem_rastreio_depois": 0, "gravadas": 0}


def test_simulacao_e_read_only_e_nao_insere():
    sql = bj.montar_sql(30, False)
    assert sql.startswith("begin transaction read only;") and sql.rstrip().endswith("rollback;")
    assert "insert into" not in sql.lower()
    assert "make_interval(days => 30)" in sql


def test_aplicar_insere_com_a_dedupe_do_gatilho():
    sql = bj.montar_sql(7, True)
    assert sql.startswith("begin;") and sql.rstrip().endswith("commit;")
    assert "'entrada:lead:' || n.lead_id || ':inicial'" in sql
    assert "on conflict (dedupe_key) where dedupe_key is not null do nothing" in sql


@pytest.mark.parametrize("dias", [0, -1, "30"])
def test_dias_invalido(dias):
    with pytest.raises(ValueError):
        bj.montar_sql(dias, False)


def test_canais_novos_batem_com_o_relatorio():
    from app.campaigns import traffic_report as tr
    assert set(bj.CANAIS_NOVOS) == {tr.CANAL_WHATSAPP_DIRETO, tr.CANAL_MANUAL, tr.CANAL_CSV,
                                    tr.CANAL_CLIENTE_ANTIGO, tr.CANAL_NUMERO_ANTIGO}


def test_main_sem_migracao_nao_roda(capsys):
    chamadas = []

    def rodar(sql):
        chamadas.append(sql)
        return json.dumps({"f5": False})
    assert bj.main(["--psql", "x"], rodar=rodar) == 2
    assert len(chamadas) == 1


def test_main_simula_por_padrao_e_formata(capsys):
    chamadas = []

    def rodar(sql):
        chamadas.append(sql)
        return json.dumps({"f5": True}) if len(chamadas) == 1 else json.dumps(RES)
    assert bj.main(["--psql", "x"], rodar=rodar) == 0
    assert "read only" in chamadas[1]
    out = capsys.readouterr().out
    assert "SIMULAÇÃO (nada gravado)" in out
    assert "Mudam de canal no /trafego (última origem): 3" in out
    assert "Sem rastreio: 3 antes -> 0 depois" in out
    assert "Sem rastreio -> Cliente antigo: 1" in out
