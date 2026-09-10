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
    # quebra na segunda execução. Fatiamos o bloco DO $$ ... END $$; e
    # verificamos QUE O ADD CONSTRAINT está dentro dele — não só que ambos
    # aparecem em algum lugar do arquivo.
    bloco = sql[sql.index("DO $$"):sql.index("END $$;")]
    assert "ADD CONSTRAINT agent_profiles_kind_check" in bloco
    assert "'llm'" in bloco and "'button_flow'" in bloco


def test_semeia_o_agente_com_prompt_key_estavel(sql: str):
    assert "Bot Reativação" in sql
    assert "bot_reativacao" in sql
    assert "WHERE NOT EXISTS" in sql


def test_semeia_alguma_tag_de_desfecho(sql: str):
    """Sanidade mínima: o bloco de seed não pode simplesmente sumir do arquivo.

    Os NOMES das tags foram renomeados em 09/09/2026 ("Reativação: ..." →
    "Recuperação: ...", prazos de meses → dias) e agora são conferidos um a um
    contra `app.button_flow.flows` em
    tests/test_recuperacao_migration_2026_09_09.py::TestTagsDoDesfecho — lá o teste
    DERIVA a lista do módulo em vez de copiá-la, então uma renomeação futura quebra
    o teste em vez de passar despercebida. Repetir os literais aqui reintroduziria
    a terceira cópia que causou a divergência original.
    """
    assert "INSERT INTO tags (name, color)" in sql
    assert "WHERE NOT EXISTS (SELECT 1 FROM tags t WHERE t.name = v.name);" in sql
