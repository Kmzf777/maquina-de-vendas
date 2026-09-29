"""A migração da ValerIA de botões, conferida pelo texto do SQL.

Mesmo espírito de test_button_flow_migration_2026_08_20.py: não sobe banco, garante
que o arquivo declara o que o código espera encontrar. O código roda SEM a migration
(o carregador de conteúdo é fail-open e devolve os defaults do registry), então o que
este teste protege é a tela e o "Ativar", não o fluxo.
"""
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
       / "20260929_valeria_botoes.sql").read_text(encoding="utf-8")


def test_cria_a_tabela_de_conteudo():
    assert "create table" in SQL.lower()
    assert "valeria_flow_content" in SQL


def test_colunas_que_o_codigo_le():
    for coluna in ("flow_id", "node_id", "corpo", "rotulos", "rotulos_antigos"):
        assert coluna in SQL, f"coluna {coluna} não declarada"


def test_unicidade_por_no():
    """Sem isso, dois overrides do mesmo nó e o carregador escolhe um ao acaso."""
    assert "unique" in SQL.lower()
    assert "flow_id" in SQL and "node_id" in SQL


def test_agent_profiles_ganha_flow_id():
    assert "alter table" in SQL.lower()
    assert "agent_profiles" in SQL
    assert "flow_id" in SQL


def test_tags_semeadas_com_nome_exato():
    """add_tags_to_lead resolve por NOME e devolve em silêncio se não achar —
    nome divergente aqui não levanta nada, só perde a tag."""
    for tag in ("Botões: Qualificado", "Botões: Adiado",
                "Botões: Atendimento humano", "Botões: Opt-out"):
        assert tag in SQL, f"tag {tag!r} não semeada"


def test_rls_declarada():
    assert "enable row level security" in SQL.lower()
    assert "create policy" in SQL.lower()
