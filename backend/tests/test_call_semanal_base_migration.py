"""Migração base da call de 01/10 (P0): contratos que P1-P7 consomem.

O CI não tem Postgres; aqui fixamos o texto. O comportamento dos triggers foi verificado
num Postgres 17 com o esquema de produção (ver plano, Task 0.2).
"""
from pathlib import Path

SQL = (
    Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20261006_call_semanal_base.sql"
).read_text(encoding="utf-8")


def test_colunas_ja_era_cliente():
    for col in ("ja_era_cliente boolean", "ja_era_cliente_fonte text",
                "ja_era_cliente_em timestamptz", "ja_era_cliente_por text"):
        assert f"add column if not exists {col}" in SQL


def test_regra_automatica_so_grava_true_e_nao_sobrescreve_vendedor():
    corpo = SQL.split("fn_sales_marca_ja_era_cliente()")[1].split("end $$;")[0]
    assert "ja_era_cliente = true" in corpo
    assert "ja_era_cliente = false" not in SQL
    assert "l.ja_era_cliente is null" in corpo
    assert "new.sold_at < l.created_at" in corpo
    assert "'cancelada'" in corpo


def test_trigger_nunca_derruba_a_venda():
    corpo = SQL.split("fn_sales_marca_ja_era_cliente()")[1].split("end $$;")[0]
    assert "exception when others then" in corpo
    assert "raise warning" in corpo


def test_campanha_manual():
    for col in ("campanha_manual_canal", "campanha_manual_id", "campanha_manual_nome",
                "campanha_manual_por", "campanha_manual_em"):
        assert f"add column if not exists {col}" in SQL
    assert "in ('meta', 'google')" in SQL


def test_lead_events_vira_timeline():
    assert "add column if not exists occurred_at timestamptz not null default now()" in SQL
    assert "add column if not exists dedupe_key text" in SQL
    assert "lead_events_dedupe_key_uidx" in SQL
    assert "where dedupe_key is not null" in SQL


def test_arquivo_de_referrals_tem_trigger_e_backfill():
    assert "create table if not exists public.meta_referrals_arquivo" in SQL
    assert "trg_meta_webhook_logs_arquiva_referral" in SQL
    assert "$.entry[*].changes[*].value.messages[*]" in SQL
    assert "on conflict do nothing" in SQL


def test_view_primeira_origem():
    assert "create or replace view public.lead_primeira_origem" in SQL
    assert "e.event_type = 'entrada'" in SQL
    assert "order by e.lead_id, e.occurred_at asc" in SQL


def test_idempotente():
    assert "create table public." not in SQL  # sempre "if not exists"
    assert SQL.count("drop trigger if exists") == SQL.count("create trigger")
