"""Migração 20261006b (P3): triggers da linha do tempo do lead.

O CI não tem Postgres: aqui fixamos o texto (contratos, chaves, segurança). O comportamento
de verdade é testado em test_cs_p3_timeline_pg.py contra um Postgres 17 com o esquema de
produção.
"""
import re
from pathlib import Path

import pytest

from app.campaigns import traffic_report as tr

SQL = (
    Path(__file__).resolve().parents[2]
    / "supabase" / "migrations" / "20261006b_lead_timeline_triggers.sql"
).read_text(encoding="utf-8")

TRIGGERS = {
    "fn_lead_events_leads_entrada": "public.leads",
    "fn_lead_events_deals_etapa": "public.deals",
    "fn_lead_events_sales_venda": "public.sales",
    "fn_lead_events_sale_items_kit": "public.sale_items",
    "fn_lead_events_broadcast_disparo": "public.broadcast_leads",
}


def _corpo(fn: str) -> str:
    return SQL.split(f"function public.{fn}()")[1].split("end $$;")[0]


@pytest.mark.parametrize("fn", TRIGGERS)
def test_trigger_nunca_derruba_a_escrita_original(fn):
    corpo = _corpo(fn)
    assert "exception when others then" in corpo
    assert f"raise warning '{fn}: %', sqlerrm" in corpo


@pytest.mark.parametrize("fn, tabela", TRIGGERS.items())
def test_trigger_criado_na_tabela_certa(fn, tabela):
    assert re.search(
        rf"on {re.escape(tabela)}\s+for each row execute function public\.{fn}\(\)", SQL
    )


def test_entrada_so_dispara_nas_colunas_de_rastreio():
    m = re.search(r"after insert or update of ([a-z_, ]+?)\s+on public\.leads", SQL)
    assert m
    colunas = {c.strip() for c in m.group(1).split(",")}
    assert colunas == {"ctwa_clid", "gclid", "fbclid", "meta_ad_id", "utm_source", "utm_campaign"}


@pytest.mark.parametrize(
    "marcador, constante",
    [
        ("_META_AD_SOURCES", tr._META_AD_SOURCES),
        ("_GOOGLE_AD_SOURCES", tr._GOOGLE_AD_SOURCES),
        ("_PAID_CHANNEL_MEDIUMS", tr._PAID_CHANNEL_MEDIUMS),
    ],
)
def test_canal_sql_usa_as_mesmas_listas_do_derive_channel(marcador, constante):
    m = re.search(r"array\[([^\]]*)\]\)\s*--\s*" + marcador + r"\b", SQL)
    assert m, marcador
    itens = {s.strip().strip("'") for s in m.group(1).split(",")}
    assert itens == set(constante)


def test_canal_sql_devolve_os_rotulos_do_derive_channel():
    corpo = SQL.split("function public.fn_lead_canal(")[1].split("$$;")[0]
    for rotulo in ("'Google Ads'", "'Meta Ads'", "'Orgânico'", "'Sem rastreio'"):
        assert rotulo in corpo


def test_kit_pela_descricao():
    assert "descricao ilike '%kit degust%'" in SQL


def test_todo_insert_tem_on_conflict_do_nothing():
    inserts = SQL.count("insert into public.lead_events")
    assert inserts == 6  # entrada, etapa (criado/mudança), venda, venda_cancelada, disparo
    assert SQL.count("on conflict (dedupe_key) where dedupe_key is not null do nothing") == inserts


def test_janela_de_30_min_funde_os_updates_do_webhook():
    corpo = _corpo("fn_lead_events_leads_entrada")
    assert "interval '30 minutes'" in corpo
    assert "update public.lead_events" in corpo


def test_idempotente():
    assert "create table public." not in SQL
    assert "create function" not in SQL  # sempre create or replace
    assert SQL.count("drop trigger if exists") == SQL.count("create trigger") == 5
