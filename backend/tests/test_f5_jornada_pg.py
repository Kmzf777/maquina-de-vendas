"""Migração 20261106_f5_jornada contra um Postgres DE VERDADE.

Pula sem `CS_P3_PSQL` (mesmo padrão do test_cs_p3_timeline_pg.py): o CI e o container não têm
Postgres. Para rodar num Postgres descartável com o esquema de produção + as migrações até a
20261106:

    CS_P3_PSQL="docker exec -i crm-scratch-pg psql -U postgres -d p3" \\
      python -m pytest backend/tests/test_f5_jornada_pg.py

Cada cenário é um bloco SQL que roda numa transação com ROLLBACK e devolve UM json. Os mesmos
cenários foram rodados no PGlite (Postgres 16 em WASM) com o esquema mínimo, em 06/11/2026.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess

import pytest

from app.campaigns.traffic_report import aplicar_contexto_canal, canal_da_entrada, derive_channel

PSQL = os.environ.get("CS_P3_PSQL", "")
precisa_pg = pytest.mark.skipif(not PSQL, reason="sem CS_P3_PSQL (Postgres descartável)")


def _lit(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'"


# ── espelhos Python × SQL ───────────────────────────────────────────────────────
_ORDEM = ("gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "traffic_type",
          "gbraid", "wbraid", "origem_cadastro")
CANAL_CASOS = [
    {}, {"origem_cadastro": "inbound"}, {"origem_cadastro": "manual"}, {"origem_cadastro": "csv_import"},
    {"origem_cadastro": "bling_import"}, {"origem_cadastro": "reativacao_import"},
    {"origem_cadastro": " Inbound "}, {"origem_cadastro": "manual", "ctwa_clid": "c"},
    {"origem_cadastro": "inbound", "utm_source": "instagram"}, {"origem_cadastro": "inbound", "gbraid": "g"},
    {"origem_cadastro": "csv_import", "utm_source": "google", "utm_medium": "cpc"},
    {"origem_cadastro": "inbound", "traffic_type": "organic"}, {"origem_cadastro": "outro"},
    {"utm_source": "metaads"}, {"gclid": "g", "fbclid": "f"},
]
CONTEXTO_CASOS = [
    (canal, ctx)
    for canal in ("WhatsApp direto", "Cadastro manual / disparo", "Importado (CSV)", "Sem rastreio",
                  "Meta Ads", "Google Ads", "Orgânico", "Bling")
    for ctx in ({}, {"cliente_antigo": True}, {"numero_antigo": "Velho"}, {"numero_antigo": " "},
                {"tem_inbound": False}, {"tem_inbound": False, "lead_channel": "campaign"},
                {"tem_inbound": False, "lead_channel": " BLING "}, {"tem_inbound": True},
                {"cliente_antigo": False, "numero_antigo": "X", "tem_inbound": False})
]
ENTRADA_CASOS = [
    ({"canal": "Meta Ads", "ctwa_clid": "c"}, "Meta Ads"),
    ({"canal": "Orgânico", "sem_rastreio": True}, "Orgânico"),
    ({"canal": "WhatsApp direto", "sem_rastreio": True}, None),
    ({"canal": "WhatsApp direto", "retorno": True}, None),
    ({"canal": "Google Ads", "utm_source": "google", "utm_medium": "cpc", "campanha_nome": "WhatsApp do Google"}, None),
    ({"canal": "Bling"}, None), ({}, None), ({"utm_source": "instagram"}, None), ({"canal": ""}, "Sem rastreio"),
]


def sql_espelho() -> str:
    partes = []
    for i, c in enumerate(CANAL_CASOS):
        args = ", ".join(_lit(c.get(k)) for k in _ORDEM)
        partes.append(f"'canal{i}', public.fn_lead_canal({args})")
    for i, (canal, ctx) in enumerate(CONTEXTO_CASOS):
        args = ", ".join(_lit(x) for x in (canal, ctx.get("cliente_antigo"), ctx.get("numero_antigo"),
                                            ctx.get("tem_inbound"), ctx.get("lead_channel")))
        partes.append(f"'ctx{i}', public.fn_lead_canal_contexto({args})")
    for i, (meta, valor) in enumerate(ENTRADA_CASOS):
        partes.append(f"'ent{i}', public.fn_lead_canal_entrada({_lit(json.dumps(meta))}::jsonb, {_lit(valor)})")
    # jsonb_build_object aceita no máximo 100 argumentos: blocos de 40 pares somados com ||
    blocos = ["jsonb_build_object(" + ", ".join(partes[i:i + 40]) + ")" for i in range(0, len(partes), 40)]
    return "select (" + " || ".join(blocos) + ")::json;"


def esperado_espelho() -> dict[str, str]:
    out = {}
    for i, c in enumerate(CANAL_CASOS):
        out[f"canal{i}"] = derive_channel(c)
    for i, (canal, ctx) in enumerate(CONTEXTO_CASOS):
        out[f"ctx{i}"] = aplicar_contexto_canal(canal, **ctx)
    for i, (meta, valor) in enumerate(ENTRADA_CASOS):
        out[f"ent{i}"] = canal_da_entrada({"metadata": meta, "new_value": valor})
    return out


# ── cenários do gatilho e das views ────────────────────────────────────────────
_LEAD = "f5f5f5f5-0000-0000-0000-00000000000{n}"

CENARIOS: dict[str, tuple[str, dict]] = {
    # Meta e Google em 10 min viram 2 entradas; a automática é substituída pelo 1º clique.
    "meta_google_10min": (f"""
insert into public.leads (id, phone, origem_cadastro) values ('{_LEAD.format(n=1)}', 'f5-1', 'inbound');
update public.leads set ctwa_clid = 'CLID1', meta_ad_id = 'AD1' where id = '{_LEAD.format(n=1)}';
-- o clique do Meta foi há 10 min (numa transação só, now() é o mesmo para tudo)
update public.lead_events set occurred_at = occurred_at - interval '10 minutes'
 where lead_id = '{_LEAD.format(n=1)}';
update public.leads set gclid = 'G1' where id = '{_LEAD.format(n=1)}';
select json_build_object(
  'canais', (select json_agg(e.new_value order by e.occurred_at, e.created_at, e.dedupe_key)
               from public.lead_events e where e.lead_id = '{_LEAD.format(n=1)}' and e.event_type = 'entrada'),
  'sem_rastreio', (select count(*) from public.lead_events e where e.lead_id = '{_LEAD.format(n=1)}'
                    and e.metadata->>'sem_rastreio' = 'true'),
  'jornada', (select row_to_json(j) from public.vw_lead_jornada j where j.lead_id = '{_LEAD.format(n=1)}'));
""", {"canais": ["Meta Ads", "Google Ads"], "sem_rastreio": 0,
      "jornada": {"primeira_origem": "Meta Ads", "ultima_origem": "Google Ads",
                  "origens": "Meta Ads → Google Ads", "n_toques": 2, "multicanal": True, "estimado": False}}),
    # Mesma plataforma em 30 min continua fundindo (o webhook manda o ctwa_clid e depois o anúncio).
    "mesma_plataforma_funde": (f"""
insert into public.leads (id, phone, origem_cadastro) values ('{_LEAD.format(n=2)}', 'f5-2', 'inbound');
update public.leads set ctwa_clid = 'A' where id = '{_LEAD.format(n=2)}';
update public.leads set ctwa_clid = 'B' where id = '{_LEAD.format(n=2)}';
select json_build_object('canais', (select json_agg(e.new_value) from public.lead_events e
  where e.lead_id = '{_LEAD.format(n=2)}' and e.event_type = 'entrada'));
""", {"canais": ["Meta Ads"]}),
    # Lead inbound sem rastreio: a entrada automática agora se chama "WhatsApp direto".
    "automatica_whatsapp_direto": (f"""
insert into public.leads (id, phone, origem_cadastro) values ('{_LEAD.format(n=3)}', 'f5-3', 'inbound');
select json_build_object(
  'entrada', (select json_build_object('valor', e.new_value, 'canal', e.metadata->>'canal',
                                       'sem_rastreio', e.metadata->>'sem_rastreio')
                from public.lead_events e where e.lead_id = '{_LEAD.format(n=3)}'),
  'jornada', (select json_build_object('p', j.primeira_origem, 'o', j.origens, 'est', j.estimado)
                from public.vw_lead_jornada j where j.lead_id = '{_LEAD.format(n=3)}'));
""", {"entrada": {"valor": "WhatsApp direto", "canal": "WhatsApp direto", "sem_rastreio": "true"},
      "jornada": {"p": "WhatsApp direto", "o": "WhatsApp direto", "est": False}}),
    # Contexto: cliente antigo, outro número e o lead antigo que nunca escreveu.
    "contexto": (f"""
insert into public.channels (id, name, phone, provider) values
  ('f5f5f5f5-cccc-0000-0000-000000000001', 'Anúncios', 'f5-ads', 'meta_cloud'),
  ('f5f5f5f5-cccc-0000-0000-000000000002', 'Número velho', 'f5-velho', 'evolution');
insert into public.leads (id, phone, origem_cadastro, ctwa_clid, created_at) values
  ('{_LEAD.format(n=4)}', 'f5-4', 'inbound', 'CL', now() - interval '20 days');
insert into public.leads (id, phone, origem_cadastro, created_at, channel) values
  ('{_LEAD.format(n=5)}', 'f5-5', 'inbound', now() - interval '20 days', 'whatsapp'),
  ('{_LEAD.format(n=6)}', 'f5-6', 'inbound', now() - interval '5 days', 'whatsapp'),
  ('{_LEAD.format(n=7)}', 'f5-7', 'inbound', now() - interval '90 days', 'campaign');
insert into public.conversations (lead_id, channel_id, last_customer_message_at, created_at) values
  ('{_LEAD.format(n=4)}', 'f5f5f5f5-cccc-0000-0000-000000000001', now(), now() - interval '20 days'),
  ('{_LEAD.format(n=5)}', 'f5f5f5f5-cccc-0000-0000-000000000002', now(), now() - interval '20 days'),
  ('{_LEAD.format(n=6)}', 'f5f5f5f5-cccc-0000-0000-000000000001', now(), now() - interval '5 days');
insert into public.sales (lead_id, sold_at, value) values ('{_LEAD.format(n=6)}', now() - interval '60 days', 10);
delete from public.lead_events where lead_id in ('{_LEAD.format(n=5)}', '{_LEAD.format(n=6)}', '{_LEAD.format(n=7)}');
select json_object_agg(right(j.lead_id::text, 1), j.primeira_origem)
  from public.vw_lead_jornada j where j.lead_id::text like 'f5f5f5f5-0000-%';
""", {"4": "Meta Ads", "5": "Número antigo / outro número", "6": "Cliente antigo",
      "7": "Cadastro manual / disparo"}),
}


def _rodar(sql: str) -> object:
    r = subprocess.run(shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
                       input="begin;\n" + sql + "\nrollback;\n", text=True, capture_output=True)
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    linhas = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return json.loads(linhas[-1])


def _confere(obtido, esperado):
    if isinstance(esperado, dict):
        for k, v in esperado.items():
            _confere(obtido[k], v)
    else:
        assert obtido == esperado, (obtido, esperado)


@precisa_pg
def test_espelho_python_sql():
    assert _rodar(sql_espelho()) == esperado_espelho()


@precisa_pg
@pytest.mark.parametrize("nome", list(CENARIOS))
def test_cenario(nome):
    sql, esperado = CENARIOS[nome]
    _confere(_rodar(sql), esperado)
