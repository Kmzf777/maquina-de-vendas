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


def test_todo_insert_tem_on_conflict():
    inserts = SQL.count("insert into public.lead_events")
    assert inserts == 6  # entrada, etapa (criado/mudança), venda, venda_cancelada, disparo
    # o disparo é o único que atualiza no conflito (reenvio depois do cap da Meta)
    assert SQL.count("on conflict (dedupe_key) where dedupe_key is not null do nothing") == inserts - 1
    assert SQL.count("on conflict (dedupe_key) where dedupe_key is not null do update") == 1


def test_disparo_retido_pelo_cap_sai_da_timeline_e_reenvio_atualiza():
    """Revisão: broadcast/worker.py volta sent_at para NULL no erro 131049 (cap da Meta).
    O disparo que ninguém recebeu não pode ficar na timeline; o reenvio leva a data nova."""
    corpo = _corpo("fn_lead_events_broadcast_disparo")
    assert "delete from public.lead_events" in corpo
    assert "'disparo:' || new.id" in corpo
    assert ("on conflict (dedupe_key) where dedupe_key is not null do update\n"
            "      set occurred_at = excluded.occurred_at, metadata = excluded.metadata") in corpo


def test_janela_de_30_min_funde_os_updates_do_webhook():
    corpo = _corpo("fn_lead_events_leads_entrada")
    assert "interval '30 minutes'" in corpo
    assert "update public.lead_events" in corpo


def test_idempotente():
    assert "create table public." not in SQL
    assert "create function" not in SQL  # sempre create or replace
    assert SQL.count("drop trigger if exists") == SQL.count("create trigger") == 5


def test_so_meta_ad_id_enriquece_a_entrada_do_mesmo_ctwa_clid():
    corpo = _corpo("fn_lead_events_leads_entrada")
    assert "e.metadata->>'ctwa_clid' = new.ctwa_clid" in corpo
    trecho = corpo.split("so meta_ad_id mudou")[1].split("return new;")[0]
    assert "insert into" not in trecho


FUNCOES_TRIGGER = re.findall(r"function public\.(\w+)\(\)\s+returns trigger", SQL)


def test_funcoes_de_trigger_rodam_como_dono_e_nao_sao_rpc():
    """Revisão: lead_events tem RLS sem policy. Rodando como quem grava (authenticated, ex.:
    components/quick-add-lead.tsx), o insert no lead_events falhava e virava WARNING em
    silêncio. SECURITY DEFINER com search_path fixo; EXECUTE fora de anon/authenticated."""
    assert set(TRIGGERS) <= set(FUNCOES_TRIGGER)
    for fn in FUNCOES_TRIGGER:
        assert re.search(
            rf"function public\.{fn}\(\)\s+returns trigger language plpgsql "
            r"security definer set search_path = public, pg_temp as \$\$",
            SQL,
        ), fn
        assert f"revoke execute on function public.{fn}() from public, anon, authenticated;" in SQL, fn


def test_migracao_numa_transacao_so():
    codigo = [ln for ln in SQL.splitlines() if ln.strip() and not ln.lstrip().startswith("--")]
    assert codigo[0] == "begin;"
    assert codigo[-1] == "commit;"


def test_venda_acompanha_edicao_e_exclusao_da_sale():
    """Revisão: sold_by/value/product/sold_at/origin são editáveis. O evento era uma foto que
    nunca atualizava (e o sold_by velho decidia o escopo do vendedor na rota)."""
    m = re.search(r"after insert or update of ([a-z_, ]+?) or delete\s+on public\.sales\s", SQL)
    assert m
    assert {c.strip() for c in m.group(1).split(",")} == {
        "status", "sold_by", "value", "product", "sold_at", "origin"}
    corpo = _corpo("fn_lead_events_sales_venda")
    assert "tg_op = 'DELETE'" in corpo
    assert "delete from public.lead_events" in corpo


GUARDAS = {
    "fn_lead_events_leads_entrada": ["fn_lead_tem_rastreio(", "new.utm_campaign is not distinct from old.utm_campaign"],
    "fn_lead_events_deals_etapa": ["new.lead_id is null", "new.stage_id is not distinct from old.stage_id"],
    "fn_lead_events_sales_venda": ["new.lead_id is null", "new.sold_by is not distinct from old.sold_by",
                                   "new.status is not distinct from old.status"],
    "fn_lead_events_sale_items_kit": ["new.descricao is not distinct from old.descricao"],
    "fn_lead_events_broadcast_disparo": ["new.lead_id is null", "old.sent_at is not null",
                                         "old.sent_at is null"],
}


@pytest.mark.parametrize("fn, guardas", GUARDAS.items())
def test_guardas_baratas_ficam_fora_da_subtransacao(fn, guardas):
    """Revisão: um bloco begin/exception abre subtransação a cada linha; o caminho que não faz
    nada não deve pagar isso (UPDATE em massa estoura o cache de subxid)."""
    corpo = _corpo(fn)
    externo = corpo.index("\nbegin\n") + len("\nbegin\n")
    antes = corpo[externo:corpo.index("begin\n", externo)]
    assert "exception when" not in antes
    for g in guardas:
        assert g in antes, (fn, g)
    assert "return" in antes
    # uma subtransação só por função
    assert corpo.count("exception when others then") == 1, fn


def test_venda_so_reescreve_o_evento_quando_algo_muda():
    """Revisão: o Bling regrava a venda a cada webhook; o evento que já mostra o estado atual
    não é reescrito (metadata, new_value, source e data comparados antes do update)."""
    corpo = _corpo("fn_lead_events_sales_venda")
    trecho = corpo.split("update public.lead_events e")[1].split(";")[0]
    assert "e.metadata is distinct from coalesce(e.metadata, '{}'::jsonb) || v_meta" in trecho
    assert "e.new_value is distinct from new.value::text" in trecho
