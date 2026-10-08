"""A semente da tag nova da v2, conferida pelo texto do SQL.

Mesmo molde de test_valeria_migration_2026_09_29.py: não sobe banco. O T_KIT marca o
lead com `TAG_KIT` por NOME EXATO (`add_tags_to_lead` não cria tag e devolve em
silêncio se não achar), então o nome no SQL tem de ser o mesmo do registry.
"""
from pathlib import Path

from app.button_flow import valeria_registry_v2 as r2

SQL = (Path(__file__).resolve().parents[2] / "supabase" / "migrations"
       / "20261008_valeria_botoes_v2.sql").read_text(encoding="utf-8")


def test_semeia_a_tag_do_kit_com_o_nome_exato_do_registry():
    assert f"'{r2.TAG_KIT}'" in SQL
    assert r2.TERMINAIS["T_KIT"].tags and r2.TAG_KIT in r2.TERMINAIS["T_KIT"].tags


def test_e_idempotente_sem_on_conflict():
    """`tags.name` não tem unique: ON CONFLICT (name) quebraria a migration."""
    sql = "\n".join(l.split("--", 1)[0] for l in SQL.lower().splitlines())
    assert "insert into tags" in sql
    assert "where not exists" in sql
    assert "on conflict" not in sql
