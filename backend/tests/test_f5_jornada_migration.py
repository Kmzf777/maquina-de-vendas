"""Migração 20261106_f5_jornada: o texto do SQL espelha o Python (traffic_report).

O CI não tem Postgres: aqui fixamos o texto (listas, ordem, chaves, segurança). O comportamento
contra um Postgres de verdade está em test_f5_jornada_pg.py (pula sem CS_P3_PSQL).
"""
import re
from pathlib import Path

import pytest

from app.campaigns import traffic_report as tr

RAIZ = Path(__file__).resolve().parents[2]
SQL = (RAIZ / "supabase" / "migrations" / "20261106_f5_jornada.sql").read_text(encoding="utf-8")
ROLLBACK = (RAIZ / "scripts" / "f5_jornada" / "rollback_20261106.sql").read_text(encoding="utf-8")
SQL_22C = (RAIZ / "supabase" / "migrations" / "20261022c_origem_cadastro.sql").read_text(encoding="utf-8")


def _funcao(nome: str, sql: str = SQL) -> str:
    return sql.split(f"function public.{nome}(")[1].split("$$;")[0]


def _gatilho(sql: str = SQL) -> str:
    return sql.split("function public.fn_lead_events_leads_entrada()")[1].split("end $$;")[0]


def _codigo(sql: str) -> list[str]:
    return [ln for ln in sql.splitlines() if ln.strip() and not ln.lstrip().startswith("--")]


def test_numa_transacao_so_com_lock_timeout():
    codigo = _codigo(SQL)
    assert codigo[0] == "BEGIN;" and codigo[-1] == "COMMIT;"
    assert "lock_timeout = '5s'" in SQL


# ── fn_lead_canal ↔ derive_channel ─────────────────────────────────────────────

@pytest.mark.parametrize("marcador, constante", [
    ("_META_AD_SOURCES", tr._META_AD_SOURCES),
    ("_GOOGLE_AD_SOURCES", tr._GOOGLE_AD_SOURCES),
    ("_PAID_CHANNEL_MEDIUMS", tr._PAID_CHANNEL_MEDIUMS),
    ("_ORIGENS_IMPORTADAS", tr._ORIGENS_IMPORTADAS),
])
def test_canal_usa_as_mesmas_listas_do_derive_channel(marcador, constante):
    m = re.search(r"array\[([^\]]*)\]\)\s*--\s*" + marcador + r"\b", _funcao("fn_lead_canal"))
    assert m, marcador
    assert {s.strip().strip("'") for s in m.group(1).split(",")} == set(constante)


def test_canal_por_origem_e_o_mesmo_do_python_e_vem_depois_do_organico():
    corpo = _funcao("fn_lead_canal")
    pares = dict(re.findall(r"fn_lead_txt\(p_origem\) = '([a-z_]+)' then '([^']+)' -- _CANAL_POR_ORIGEM", corpo))
    assert pares == tr._CANAL_POR_ORIGEM
    assert corpo.index("then 'Orgânico'") < corpo.index("-- _CANAL_POR_ORIGEM") < corpo.index("else 'Sem rastreio'")
    # mesma assinatura de 10 args da 20261022c: nada que dependa dela quebra
    assert "p_gbraid text default null, p_wbraid text default null, p_origem text default null)" in SQL


def test_canal_continua_igual_a_20261022c_ate_o_organico():
    novo = _funcao("fn_lead_canal").split("then 'Orgânico'")[0]
    antigo = _funcao("fn_lead_canal", SQL_22C).split("then 'Orgânico'")[0]
    assert novo == antigo


def test_contexto_espelha_aplicar_contexto_canal():
    corpo = _funcao("fn_lead_canal_contexto")
    m = re.search(r"array\[([^\]]*)\]\)\s*--\s*_CANAIS_SEM_SINAL", corpo)
    assert {s.strip().strip("'") for s in m.group(1).split(",")} == set(tr._CANAIS_SEM_SINAL)
    bloco = corpo.split("-- _CANAL_POR_LEAD_CHANNEL")[1].split("else 'Sem rastreio'")[0]
    assert dict(re.findall(r"when '([a-z_]+)' then '([^']+)'", bloco)) == tr._CANAL_POR_LEAD_CHANNEL
    # ordem: cliente antigo > outro número > nunca escreveu
    i_cli = corpo.index("then 'Cliente antigo'")
    i_num = corpo.index("then 'Número antigo / outro número'")
    i_inb = corpo.index("p_tem_inbound is false")
    assert i_cli < i_num < i_inb
    for rotulo in (tr.CANAL_CLIENTE_ANTIGO, tr.CANAL_NUMERO_ANTIGO, tr.CANAL_MANUAL, tr.CANAL_CSV):
        assert f"'{rotulo}'" in SQL


def test_canal_da_entrada_espelha_o_python():
    corpo = _funcao("fn_lead_canal_entrada")
    # rastreio do metadata manda, sem origem (9 args)
    for k in ("gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium",
              "traffic_type", "gbraid", "wbraid"):
        assert f"p_metadata->>'{k}'" in corpo
        assert k in tr._TRACK_KEYS
    assert "r.rotulo = 'Orgânico' and p_metadata->>'sem_rastreio' = 'true' then 'WhatsApp direto'" in corpo


# ── gatilho ────────────────────────────────────────────────────────────────────

def test_gatilho_continua_seguro():
    corpo = _gatilho()
    assert re.search(r"returns trigger language plpgsql security definer set search_path = public, pg_temp as \$\$", corpo)
    assert "exception when others then" in corpo
    assert "raise warning 'fn_lead_events_leads_entrada: %', sqlerrm" in corpo
    assert "revoke execute on function public.fn_lead_events_leads_entrada() from public, anon, authenticated;" in SQL
    assert "coalesce(new.origem_cadastro, 'inbound') <> 'inbound'" in corpo
    assert "'entrada:lead:' || new.id || ':inicial'" in corpo


def test_entrada_automatica_vira_whatsapp_direto_com_o_marcador():
    corpo = _gatilho()
    assert "values (new.id, 'entrada', 'WhatsApp direto'," in corpo
    assert "jsonb_build_object('canal', 'WhatsApp direto', 'sem_rastreio', true)" in corpo
    assert "'Orgânico'" not in corpo.split("if not v_tem_rastreio then\n      insert")[1].split("return new;")[0]


def test_fusao_de_30_min_so_na_mesma_plataforma_ou_na_automatica():
    corpo = _gatilho()
    fusao = corpo.split("interval '30 minutes'")[1].split("insert into public.lead_events")[0]
    assert "v_ultimo_meta->>'sem_rastreio' = 'true'" in fusao
    assert "public.fn_lead_canal_entrada(v_ultimo_meta, v_ultimo_valor) = v_meta->>'canal'" in fusao
    # a 20261022c fundia qualquer coisa
    antiga = _gatilho(SQL_22C).split("interval '30 minutes'")[1].split("insert into public.lead_events")[0]
    assert "fn_lead_canal_entrada" not in antiga


def test_resto_do_gatilho_igual_a_20261022c():
    """Só a entrada automática e a fusão mudaram: o enriquecimento do meta_ad_id fica igual."""
    trecho = "-- so meta_ad_id mudou"
    novo = _gatilho().split(trecho)[1].split("if tg_op = 'UPDATE' and not v_inicial then")[0]
    antigo = _gatilho(SQL_22C).split(trecho)[1].split("if tg_op = 'UPDATE' and not v_inicial then")[0]
    norm = lambda s: re.sub(r"--[^\n]*", "", s).split()  # noqa: E731
    assert norm(novo) == norm(antigo)


# ── views e acesso ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("view", ["vw_lead_contexto_canal", "vw_lead_jornada"])
def test_views_com_security_invoker_e_grants(view):
    assert f"create or replace view public.{view} with (security_invoker = true) as" in SQL
    assert f"revoke all on public.{view} from anon, authenticated;" in SQL
    assert f"GRANT SELECT ON public.{view} TO consulta_ro;" in SQL
    assert f"grant select on public.{view} to service_role;" in SQL


def test_view_de_contexto_tem_as_colunas_que_o_relatorio_le():
    corpo = SQL.split("create or replace view public.vw_lead_contexto_canal")[1].split(";")[0]
    for col in tr._CONTEXTO_COLS:
        assert f"as {col}" in corpo, col


def test_view_da_jornada_tem_as_colunas_do_cartao():
    corpo = SQL.split("create or replace view public.vw_lead_jornada")[1].split("comment on view")[0]
    for col in ("primeira_origem", "primeira_em", "ultima_origem", "ultima_em", "origens",
                "n_toques", "multicanal", "estimado"):
        assert re.search(rf"\bas {col}\b|\ba\.{col}\b", corpo), col
    assert "string_agg(s.canal, ' → '" in corpo and tr._SETA == " → "
    assert "s.anterior is distinct from s.canal" in corpo  # sem repetir seguidas


# ── rollback ───────────────────────────────────────────────────────────────────

def test_rollback_devolve_a_20261022c():
    assert _funcao("fn_lead_canal", ROLLBACK) == _funcao("fn_lead_canal", SQL_22C)
    assert _gatilho(ROLLBACK) == _gatilho(SQL_22C)
    for obj in ("view if exists public.vw_lead_jornada", "view if exists public.vw_lead_contexto_canal",
                "function if exists public.fn_lead_canal_entrada", "function if exists public.fn_lead_canal_contexto"):
        assert f"drop {obj}" in ROLLBACK
    codigo = _codigo(ROLLBACK)
    assert codigo[0] == "BEGIN;" and codigo[-1] == "COMMIT;"
