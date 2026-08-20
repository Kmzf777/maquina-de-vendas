"""A migração do bot de botões precisa ser idempotente e semear TODAS as tags.

Testar SQL como texto parece pobre, mas aqui é o único guard-rail possível: a
migração é aplicada à mão no Supabase (o deploy não roda migrations), então um
seed faltando só apareceria em produção, silenciosamente — `add_tags_to_lead`
ignora nome de tag inexistente sem erro.
"""
from pathlib import Path

import pytest

SQL = (
    Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20260820_button_flow_agent.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    assert SQL.exists(), f"migração não encontrada em {SQL}"
    return SQL.read_text(encoding="utf-8")


def test_adiciona_colunas_de_forma_idempotente(sql: str):
    assert "agent_profiles" in sql and "kind" in sql
    assert "conversations" in sql and "flow_state" in sql
    assert sql.count("ADD COLUMN IF NOT EXISTS") >= 2


def test_constraint_de_kind_dentro_de_do_block(sql: str):
    # ADD CONSTRAINT não aceita IF NOT EXISTS — sem o DO block a migração
    # quebra na segunda execução.
    assert "DO $$" in sql
    assert "agent_profiles_kind_check" in sql
    assert "'llm'" in sql and "'button_flow'" in sql


def test_semeia_o_agente_com_prompt_key_estavel(sql: str):
    assert "Bot Reativação" in sql
    assert "bot_reativacao" in sql
    assert "WHERE NOT EXISTS" in sql


@pytest.mark.parametrize("tag", [
    "Reativação: Quente",
    "Reativação: 1 mês",
    "Reativação: 3 meses",
    "Reativação: 6 meses",
    "Reativação: Recusou",
    "Reativação: Atendimento humano",
])
def test_semeia_todas_as_seis_tags(sql: str, tag: str):
    assert tag in sql, f"tag {tag!r} não semeada — add_tags_to_lead a ignoraria em silêncio"
