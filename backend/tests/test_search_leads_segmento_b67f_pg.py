"""Migration 20261022g_search_leads_segmento (cartão b67f1c6b) contra um Postgres DE VERDADE.

O filtro `p_stage` da busca universal passa a ler `leads.segmento` (com o `stage` antigo
como reserva) e 'triagem' casa também o 'secretaria' legado.

Sem `B67F_PSQL` os testes pulam. Para rodar no Postgres descartável:

    B67F_PSQL='ssh -i ~/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \\
      docker exec -i crm-scratch-pg-b67f1c6b psql -U postgres -h localhost -d postgres' \\
      python -m pytest -q backend/tests/test_search_leads_segmento_b67f_pg.py

Cada cenário roda numa transação com ROLLBACK e usa ids com prefixo b67f1c6b-.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

PSQL = os.environ.get("B67F_PSQL", "")
MIGRATION = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
             / "20261022g_search_leads_segmento.sql")

pytestmark = pytest.mark.skipif(not PSQL, reason="sem B67F_PSQL (Postgres descartável)")

L_NOVO_ATAC = "b67f1c6b-0000-0000-0000-0000000e0001"  # segmento atacado, fase qualificando
L_LEGADO = "b67f1c6b-0000-0000-0000-0000000e0002"     # segmento NULL, stage 'atacado' (pré-F2)
L_CONSUMO = "b67f1c6b-0000-0000-0000-0000000e0003"    # segmento consumo
L_TRIAGEM = "b67f1c6b-0000-0000-0000-0000000e0004"    # fase triagem
L_SECRET = "b67f1c6b-0000-0000-0000-0000000e0005"     # 'secretaria' legado
L_PEND = "b67f1c6b-0000-0000-0000-0000000e0006"       # fase pending
L_STAGE_PL = "b67f1c6b-0000-0000-0000-0000000e0007"   # segmento atacado, stage antigo 'private_label'


def _psql(sql: str) -> str:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True, encoding="utf-8",
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r.stdout


SEED = f"""
insert into public.leads (id, phone, name, stage, segmento) values
  ('{L_NOVO_ATAC}', '5599b67f0001', 'b67fbusca A', 'qualificando', 'atacado'),
  ('{L_LEGADO}',    '5599b67f0002', 'b67fbusca B', 'atacado', null),
  ('{L_CONSUMO}',   '5599b67f0003', 'b67fbusca C', 'qualificando', 'consumo'),
  ('{L_TRIAGEM}',   '5599b67f0004', 'b67fbusca D', 'triagem', null),
  ('{L_SECRET}',    '5599b67f0005', 'b67fbusca E', 'secretaria', null),
  ('{L_PEND}',      '5599b67f0006', 'b67fbusca F', 'pending', null),
  ('{L_STAGE_PL}',  '5599b67f0007', 'b67fbusca G', 'private_label', 'atacado');
"""


def _busca(p_stage: str | None) -> set[str]:
    arg = "null" if p_stage is None else f"'{p_stage}'"
    out = _psql(f"""
begin;
set local session_replication_role = replica;  -- sem gatilhos de entrada no seed
-- o seed tem stage legado ('atacado', 'secretaria'); se a migration f já estiver no
-- scratch, o CHECK de fase cai só dentro desta transação (rollback no fim).
alter table public.leads drop constraint if exists leads_stage_fase_check;
{SEED}
select id from public.search_leads('b67fbusca', {arg}, null, null, 50, 0);
rollback;
""")
    return {linha.strip() for linha in out.splitlines() if linha.strip().startswith("b67f1c6b-")}


def test_migration_reaplica_sem_erro():
    sql = MIGRATION.read_text(encoding="utf-8")
    _psql(sql)
    _psql(sql)


def test_segmento_le_leads_segmento_com_reserva_no_stage():
    assert _busca("atacado") == {L_NOVO_ATAC, L_LEGADO, L_STAGE_PL}
    # stage antigo 'private_label' não conta quando o segmento já foi gravado (atacado)
    assert _busca("private_label") == set()
    assert _busca("consumo") == {L_CONSUMO}


def test_triagem_casa_secretaria_legado():
    assert _busca("triagem") == {L_TRIAGEM, L_SECRET}
    assert _busca("secretaria") == {L_TRIAGEM, L_SECRET}


def test_fase_continua_em_stage():
    assert _busca("qualificando") == {L_NOVO_ATAC, L_CONSUMO}
    assert _busca("pending") == {L_PEND}


def test_sem_filtro_traz_todos():
    assert _busca(None) == {L_NOVO_ATAC, L_LEGADO, L_CONSUMO, L_TRIAGEM, L_SECRET, L_PEND, L_STAGE_PL}
