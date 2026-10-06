"""Triggers e backfill da linha do tempo (P3) contra um Postgres DE VERDADE.

O CI e o container `canastra-api` não têm Postgres nem psql: os testes que precisam do
banco pulam sem `CS_P3_PSQL`. Para rodá-los num Postgres descartável com o esquema de
produção + 20261006 (P0) + 20261006b (P3):

    CS_P3_PSQL="docker exec -i crm-scratch-pg psql -U postgres -d p3" \\
      python3 backend/tests/test_cs_p3_timeline_pg.py

Roda com o python do host (só stdlib); pytest é opcional. Cada cenário de trigger roda numa
transação com ROLLBACK; o do backfill semeia linhas com prefixo f0f0f0f0- e as apaga no fim.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

try:
    import pytest
except ImportError:  # host sem pytest: o runner do __main__ cuida
    pytest = None

PSQL = os.environ.get("CS_P3_PSQL", "")
RAIZ = Path(__file__).resolve().parents[2]
BACKFILL = RAIZ / "scripts" / "timeline" / "backfill_lead_events.py"


def _precisa_pg(fn):
    if pytest is None:
        return fn
    return pytest.mark.skipif(not PSQL, reason="sem CS_P3_PSQL (Postgres descartável)")(fn)


def _rodar(sql: str) -> subprocess.CompletedProcess:
    r = subprocess.run(
        shlex.split(PSQL) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, capture_output=True,
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr.strip() or r.stdout.strip())
    return r


def _psql(sql: str) -> str:
    return _rodar(sql).stdout


# ── Canal: o SQL tem que dar o mesmo que traffic_report.derive_channel ─────────
CANAL_CASOS = [
    ({"gclid": "abc"}, "Google Ads"),
    ({"fbclid": "x"}, "Meta Ads"),
    ({"ctwa_clid": "x"}, "Meta Ads"),
    ({"meta_ad_id": "120"}, "Meta Ads"),
    ({"gclid": "g", "fbclid": "f"}, "Google Ads"),
    ({"traffic_type": "organic"}, "Orgânico"),
    ({"utm_source": "instagram"}, "Orgânico"),
    ({}, "Sem rastreio"),
    ({"gclid": "", "fbclid": "  ", "utm_source": ""}, "Sem rastreio"),
    ({"utm_source": "metaads", "utm_medium": "whatsapp"}, "Meta Ads"),
    ({"utm_source": "MetaAds"}, "Meta Ads"),
    ({"utm_source": " metaads "}, "Meta Ads"),
    ({"utm_source": "google", "utm_medium": "cpc"}, "Google Ads"),
    ({"utm_source": "google", "utm_medium": "PMAX"}, "Google Ads"),
    ({"utm_source": "google", "utm_medium": "organic"}, "Orgânico"),
    ({"utm_source": "google"}, "Orgânico"),
    ({"utm_source": "instagram", "utm_medium": "bio"}, "Orgânico"),
]
ORDEM = ("gclid", "fbclid", "ctwa_clid", "meta_ad_id", "utm_source", "utm_medium", "traffic_type")


def _lit(v):
    return "null" if v is None else "'" + v.replace("'", "''") + "'"


def test_casos_de_canal_batem_com_derive_channel():
    from app.campaigns.traffic_report import derive_channel  # só no container

    for lead, esperado in CANAL_CASOS:
        assert derive_channel(lead) == esperado, lead


@_precisa_pg
def test_canal_sql_igual_ao_derive_channel():
    valores = ",\n".join(
        f"({i}, public.fn_lead_canal({', '.join(_lit(lead.get(c)) for c in ORDEM)}))"
        for i, (lead, _) in enumerate(CANAL_CASOS)
    )
    out = _psql(f"select json_object_agg(i, canal) from (values {valores}) v(i, canal);")
    got = json.loads(out.strip().splitlines()[-1])
    for i, (lead, esperado) in enumerate(CANAL_CASOS):
        assert got[str(i)] == esperado, (lead, got[str(i)])


CENARIO_ENTRADA = """
begin;
insert into public.meta_ad_campaigns (ad_id, campaign_id, campaign_name)
values ('ad-p3', 'camp-p3', 'CTWA Atacado') on conflict (ad_id) do nothing;
insert into public.leads (id, phone, ctwa_clid, traffic_type)
values ('aaaaaaaa-0000-0000-0000-000000000001', '5511900000001', 'clid-1', 'paid');
insert into public.leads (id, phone, name)
values ('aaaaaaaa-0000-0000-0000-000000000002', '5511900000002', 'Sem rastreio');
do $$
declare e public.lead_events; n int;
begin
  select count(*) into n from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000002';
  assert n = 0, 'lead sem rastreio nao gera entrada';
  select * into e from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001';
  assert e.event_type = 'entrada', 'insert com ctwa_clid gera entrada';
  assert e.dedupe_key = 'entrada:lead:aaaaaaaa-0000-0000-0000-000000000001:inicial', e.dedupe_key;
  assert e.metadata->>'canal' = 'Meta Ads' and e.new_value = 'Meta Ads' and e.source = 'ctwa', e.metadata::text;
end $$;
-- o webhook grava meta_ad_id num UPDATE separado, segundos depois: funde no mesmo evento
update public.leads set meta_ad_id = 'ad-p3' where id = 'aaaaaaaa-0000-0000-0000-000000000001';
do $$
declare e public.lead_events; n int;
begin
  select count(*) into n from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001';
  assert n = 1, format('update na janela de 30 min funde, achou %s eventos', n);
  select * into e from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001';
  assert e.metadata->>'meta_ad_id' = 'ad-p3', e.metadata::text;
  assert e.metadata->>'campanha_id' = 'camp-p3' and e.metadata->>'campanha_nome' = 'CTWA Atacado', e.metadata::text;
end $$;
-- coluna fora da lista e valor igual nao geram evento
update public.leads set name = 'Fulano' where id = 'aaaaaaaa-0000-0000-0000-000000000001';
update public.leads set ctwa_clid = 'clid-1' where id = 'aaaaaaaa-0000-0000-0000-000000000001';
do $$ begin
  assert (select count(*) from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001') = 1,
    'update sem mudanca de rastreio nao gera evento';
end $$;
-- reentrada depois da janela: evento novo
update public.lead_events set occurred_at = now() - interval '2 hours'
 where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001';
update public.leads set ctwa_clid = 'clid-2' where id = 'aaaaaaaa-0000-0000-0000-000000000001';
do $$
declare e public.lead_events;
begin
  assert (select count(*) from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001') = 2,
    'reentrada fora da janela gera segundo evento';
  select * into e from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000001'
   order by occurred_at desc limit 1;
  assert e.metadata->>'ctwa_clid' = 'clid-2', e.metadata::text;
  assert e.dedupe_key like 'entrada:lead:aaaaaaaa-0000-0000-0000-000000000001:%'
     and e.dedupe_key not like '%:inicial', e.dedupe_key;
end $$;
-- Google pago por UTM e LP organica
insert into public.leads (id, phone, utm_source, utm_medium, utm_campaign) values
  ('aaaaaaaa-0000-0000-0000-000000000003', '5511900000003', 'google', 'cpc', 'marca_propria'),
  ('aaaaaaaa-0000-0000-0000-000000000004', '5511900000004', 'instagram', 'bio', null);
do $$
declare g public.lead_events; o public.lead_events;
begin
  select * into g from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000003';
  assert g.metadata->>'canal' = 'Google Ads' and g.source = 'google', g.metadata::text;
  assert g.metadata->>'utm_campaign' = 'marca_propria', g.metadata::text;
  assert g.metadata->>'campanha_nome' is null, 'slug de utm nao vira nome de campanha';
  select * into o from public.lead_events where lead_id = 'aaaaaaaa-0000-0000-0000-000000000004';
  assert o.metadata->>'canal' = 'Orgânico' and o.source = 'lp', o.metadata::text;
  assert (select canal from public.lead_primeira_origem
           where lead_id = 'aaaaaaaa-0000-0000-0000-000000000003') = 'Google Ads',
    'a view do P0 enxerga a entrada';
end $$;
rollback;
"""

CENARIO_ETAPA = """
begin;
insert into public.pipelines (id, name) values ('bbbbbbbb-0000-0000-0000-000000000001', 'Atacado');
insert into public.pipeline_stages (id, pipeline_id, label, key, order_index) values
  ('bbbbbbbb-0000-0000-0000-0000000000a1', 'bbbbbbbb-0000-0000-0000-000000000001', 'Novo', 'novo', 0),
  ('bbbbbbbb-0000-0000-0000-0000000000a2', 'bbbbbbbb-0000-0000-0000-000000000001', 'Qualificado', 'qualificado', 1);
insert into public.leads (id, phone) values ('bbbbbbbb-0000-0000-0000-0000000000c1', '5511900000011');
insert into public.deals (id, lead_id, title, pipeline_id, stage_id) values
  ('bbbbbbbb-0000-0000-0000-0000000000d1', 'bbbbbbbb-0000-0000-0000-0000000000c1', 'Card',
   'bbbbbbbb-0000-0000-0000-000000000001', 'bbbbbbbb-0000-0000-0000-0000000000a1');
do $$
declare e public.lead_events;
begin
  select * into e from public.lead_events
   where dedupe_key = 'etapa:bbbbbbbb-0000-0000-0000-0000000000d1:criado';
  assert e.event_type = 'etapa' and e.new_value = 'Novo' and e.old_value is null, coalesce(e.new_value, 'sem evento');
  assert e.metadata->>'pipeline_nome' = 'Atacado' and e.metadata->>'para_key' = 'novo', e.metadata::text;
end $$;
update public.deals set stage_id = 'bbbbbbbb-0000-0000-0000-0000000000a2'
 where id = 'bbbbbbbb-0000-0000-0000-0000000000d1';
update public.deals set title = 'Card renomeado' where id = 'bbbbbbbb-0000-0000-0000-0000000000d1';
do $$
declare e public.lead_events; k text;
begin
  assert (select count(*) from public.lead_events where lead_id = 'bbbbbbbb-0000-0000-0000-0000000000c1') = 2,
    'so a mudanca de etapa gera evento';
  select 'etapa:' || d.id || ':' || d.stage_id || ':' || extract(epoch from d.entered_stage_at)::text
    into k from public.deals d where d.id = 'bbbbbbbb-0000-0000-0000-0000000000d1';
  select * into e from public.lead_events where dedupe_key = k;
  assert e.old_value = 'Novo' and e.new_value = 'Qualificado', coalesce(e.new_value, 'sem evento: ' || k);
  assert e.metadata->>'de_key' = 'novo' and e.metadata->>'para_key' = 'qualificado', e.metadata::text;
end $$;
rollback;
"""

CENARIO_VENDA = """
begin;
insert into public.leads (id, phone) values ('cccccccc-0000-0000-0000-0000000000c1', '5511900000021');
insert into public.sales (id, lead_id, value, product, origin, bling_account) values
  ('cccccccc-0000-0000-0000-0000000000e1', 'cccccccc-0000-0000-0000-0000000000c1', 60,
   'Kit Degustação', 'bling', 'default');
do $$
declare e public.lead_events;
begin
  select * into e from public.lead_events where dedupe_key = 'venda:cccccccc-0000-0000-0000-0000000000e1';
  assert e.event_type = 'venda' and e.source = 'bling' and (e.metadata->>'valor')::numeric = 60,
    coalesce(e.metadata::text, 'sem evento');
  assert e.metadata->>'kit' = 'false' and e.metadata->>'origin' = 'bling', e.metadata::text;
end $$;
-- o item chega DEPOIS da venda (orders.py grava sales e depois sale_items)
insert into public.sale_items (sale_id, descricao, quantidade, valor_unitario, total)
values ('cccccccc-0000-0000-0000-0000000000e1', 'KIT DEGUSTAÇÃO 4 cafés', 1, 60, 60);
do $$ begin
  assert (select metadata->>'kit' from public.lead_events
           where dedupe_key = 'venda:cccccccc-0000-0000-0000-0000000000e1') = 'true', 'item de kit marca a venda';
end $$;
delete from public.sale_items where sale_id = 'cccccccc-0000-0000-0000-0000000000e1';
do $$ begin
  assert (select metadata->>'kit' from public.lead_events
           where dedupe_key = 'venda:cccccccc-0000-0000-0000-0000000000e1') = 'false', 'sem o item deixa de ser kit';
end $$;
update public.sales set status = 'cancelada' where id = 'cccccccc-0000-0000-0000-0000000000e1';
update public.sales set status = 'cancelada', notes = 'de novo' where id = 'cccccccc-0000-0000-0000-0000000000e1';
do $$
declare e public.lead_events;
begin
  assert (select count(*) from public.lead_events
           where dedupe_key = 'venda_cancelada:cccccccc-0000-0000-0000-0000000000e1') = 1,
    'cancelamento gera um evento so';
  select * into e from public.lead_events where dedupe_key = 'venda_cancelada:cccccccc-0000-0000-0000-0000000000e1';
  assert e.source = 'bling' and e.new_value = '60.00', e.metadata::text;
  assert (select metadata->>'status' from public.lead_events
           where dedupe_key = 'venda:cccccccc-0000-0000-0000-0000000000e1') = 'cancelada',
    'a venda passa a mostrar o status';
end $$;
insert into public.sales (id, lead_id, value, product, origin, sold_by) values
  ('cccccccc-0000-0000-0000-0000000000e2', 'cccccccc-0000-0000-0000-0000000000c1', 120.5,
   'Clássico 250g', 'crm', 'joao@cafecanastra.com');
do $$
declare e public.lead_events;
begin
  select * into e from public.lead_events where dedupe_key = 'venda:cccccccc-0000-0000-0000-0000000000e2';
  assert e.source = 'crm' and e.metadata->>'sold_by' = 'joao@cafecanastra.com' and e.new_value = '120.50',
    coalesce(e.metadata::text, 'sem evento');
end $$;
rollback;
"""

CENARIO_DISPARO = """
begin;
insert into public.broadcasts (id, name, template_name)
values ('dddddddd-0000-0000-0000-0000000000b1', 'Reativação Outubro', 'reativacao_v2');
insert into public.leads (id, phone) values
  ('dddddddd-0000-0000-0000-0000000000c1', '5511900000031'),
  ('dddddddd-0000-0000-0000-0000000000c2', '5511900000032');
insert into public.broadcast_leads (id, broadcast_id, lead_id) values
  ('dddddddd-0000-0000-0000-0000000000f1', 'dddddddd-0000-0000-0000-0000000000b1', 'dddddddd-0000-0000-0000-0000000000c1');
do $$ begin
  assert (select count(*) from public.lead_events where lead_id = 'dddddddd-0000-0000-0000-0000000000c1') = 0,
    'pendente nao e disparo';
end $$;
update public.broadcast_leads set sent_at = now(), status = 'sent' where id = 'dddddddd-0000-0000-0000-0000000000f1';
update public.broadcast_leads set delivered_at = now(), status = 'delivered' where id = 'dddddddd-0000-0000-0000-0000000000f1';
update public.broadcast_leads set sent_at = now() + interval '1 minute' where id = 'dddddddd-0000-0000-0000-0000000000f1';
do $$
declare e public.lead_events;
begin
  assert (select count(*) from public.lead_events where lead_id = 'dddddddd-0000-0000-0000-0000000000c1') = 1,
    'um disparo por envio';
  select * into e from public.lead_events where dedupe_key = 'disparo:dddddddd-0000-0000-0000-0000000000f1';
  assert e.new_value = 'Reativação Outubro' and e.source = 'disparo'
     and e.metadata->>'template_name' = 'reativacao_v2', coalesce(e.metadata::text, 'sem evento');
end $$;
insert into public.broadcast_leads (id, broadcast_id, lead_id, sent_at, status) values
  ('dddddddd-0000-0000-0000-0000000000f2', 'dddddddd-0000-0000-0000-0000000000b1',
   'dddddddd-0000-0000-0000-0000000000c2', now(), 'sent');
do $$ begin
  assert (select count(*) from public.lead_events
           where dedupe_key = 'disparo:dddddddd-0000-0000-0000-0000000000f2') = 1, 'insert ja enviado gera disparo';
end $$;
rollback;
"""

# lead_events renomeada = todo trigger falha por dentro. Nenhuma escrita original pode cair.
CENARIO_ERRO = """
begin;
alter table public.lead_events rename to lead_events_desligada;
insert into public.pipelines (id, name) values ('eeeeeeee-0000-0000-0000-000000000001', 'Funil');
insert into public.pipeline_stages (id, pipeline_id, label, key)
values ('eeeeeeee-0000-0000-0000-0000000000a1', 'eeeeeeee-0000-0000-0000-000000000001', 'Novo', 'novo');
insert into public.broadcasts (id, name, template_name) values ('eeeeeeee-0000-0000-0000-0000000000b1', 'B', 't');
insert into public.leads (id, phone, ctwa_clid) values ('eeeeeeee-0000-0000-0000-0000000000c1', '5511900000041', 'clid-x');
update public.leads set ctwa_clid = 'clid-y' where id = 'eeeeeeee-0000-0000-0000-0000000000c1';
insert into public.deals (id, lead_id, title, pipeline_id, stage_id) values
  ('eeeeeeee-0000-0000-0000-0000000000d1', 'eeeeeeee-0000-0000-0000-0000000000c1', 'Card',
   'eeeeeeee-0000-0000-0000-000000000001', 'eeeeeeee-0000-0000-0000-0000000000a1');
insert into public.sales (id, lead_id, value, product)
values ('eeeeeeee-0000-0000-0000-0000000000e1', 'eeeeeeee-0000-0000-0000-0000000000c1', 10, 'X');
insert into public.sale_items (sale_id, descricao, quantidade, valor_unitario, total)
values ('eeeeeeee-0000-0000-0000-0000000000e1', 'Kit Degustação', 1, 10, 10);
update public.sales set status = 'cancelada' where id = 'eeeeeeee-0000-0000-0000-0000000000e1';
insert into public.broadcast_leads (id, broadcast_id, lead_id, sent_at) values
  ('eeeeeeee-0000-0000-0000-0000000000f1', 'eeeeeeee-0000-0000-0000-0000000000b1',
   'eeeeeeee-0000-0000-0000-0000000000c1', now());
do $$ begin
  assert (select ctwa_clid from public.leads where id = 'eeeeeeee-0000-0000-0000-0000000000c1') = 'clid-y', 'lead gravado';
  assert exists (select 1 from public.deals where id = 'eeeeeeee-0000-0000-0000-0000000000d1'), 'deal gravado';
  assert (select status from public.sales where id = 'eeeeeeee-0000-0000-0000-0000000000e1') = 'cancelada', 'venda gravada';
  assert exists (select 1 from public.sale_items where sale_id = 'eeeeeeee-0000-0000-0000-0000000000e1'), 'item gravado';
  assert exists (select 1 from public.broadcast_leads where id = 'eeeeeeee-0000-0000-0000-0000000000f1'), 'disparo gravado';
end $$;
rollback;
"""


# Só meta_ad_id mudou (ctwa_clid igual) = enriquecimento da MESMA entrada, nunca entrada nova.
# Casos reais: o webhook grava meta_ad_id depois do ctwa_clid, e o recuperar_meta_ad_id.py do P2
# preenche meta_ad_id em ~687 leads antigos — sem esta regra nasceriam entradas falsas "de hoje".
CENARIO_META_AD_ID = """
begin;
insert into public.meta_ad_campaigns (ad_id, campaign_id, campaign_name)
values ('ad-p3m', 'camp-p3m', 'CTWA Recuperada') on conflict (ad_id) do nothing;
insert into public.leads (id, phone, ctwa_clid)
values ('abababab-0000-0000-0000-000000000001', '5511900000051', 'clid-m1');
-- fora da janela de 30 min (lead antigo)
update public.lead_events set occurred_at = now() - interval '40 days'
 where lead_id = 'abababab-0000-0000-0000-000000000001';
update public.leads set meta_ad_id = 'ad-p3m' where id = 'abababab-0000-0000-0000-000000000001';
do $$
declare e public.lead_events;
begin
  assert (select count(*) from public.lead_events where lead_id = 'abababab-0000-0000-0000-000000000001') = 1,
    'so meta_ad_id mudou: nenhuma entrada nova';
  select * into e from public.lead_events where lead_id = 'abababab-0000-0000-0000-000000000001';
  assert e.metadata->>'meta_ad_id' = 'ad-p3m' and e.metadata->>'campanha_id' = 'camp-p3m'
     and e.metadata->>'campanha_nome' = 'CTWA Recuperada', e.metadata::text;
  assert e.occurred_at < now() - interval '39 days', 'a data da entrada nao muda';
end $$;
-- lead antigo SEM evento algum (anterior a migracao): o update de meta_ad_id nao cria nada
set session_replication_role = replica;
insert into public.leads (id, phone, ctwa_clid)
values ('abababab-0000-0000-0000-000000000002', '5511900000052', 'clid-m2');
set session_replication_role = origin;
update public.leads set meta_ad_id = 'ad-p3m' where id = 'abababab-0000-0000-0000-000000000002';
do $$ begin
  assert (select count(*) from public.lead_events where lead_id = 'abababab-0000-0000-0000-000000000002') = 0,
    'sem entrada com o mesmo ctwa_clid: nao faz nada';
end $$;
-- a entrada mais recente tem OUTRO ctwa_clid: nao enriquece
update public.lead_events set metadata = metadata || '{"ctwa_clid": "clid-velho"}'
 where lead_id = 'abababab-0000-0000-0000-000000000001';
update public.leads set meta_ad_id = 'ad-outro' where id = 'abababab-0000-0000-0000-000000000001';
do $$ begin
  assert (select metadata->>'meta_ad_id' from public.lead_events
           where lead_id = 'abababab-0000-0000-0000-000000000001') = 'ad-p3m', 'clid diferente nao e enriquecido';
  assert (select count(*) from public.lead_events where lead_id = 'abababab-0000-0000-0000-000000000001') = 1,
    'e continua sem entrada nova';
end $$;
-- mudanca de ctwa_clid continua sendo entrada nova
update public.leads set ctwa_clid = 'clid-m3' where id = 'abababab-0000-0000-0000-000000000002';
do $$ begin
  assert (select count(*) from public.lead_events where lead_id = 'abababab-0000-0000-0000-000000000002'
           and event_type = 'entrada') = 1, 'ctwa_clid novo gera 1 entrada';
end $$;
rollback;
"""


@_precisa_pg
def test_so_meta_ad_id_enriquece_sem_criar_entrada():
    _psql(CENARIO_META_AD_ID)


@_precisa_pg
def test_entrada():
    _psql(CENARIO_ENTRADA)


@_precisa_pg
def test_etapa():
    _psql(CENARIO_ETAPA)


@_precisa_pg
def test_venda_kit_e_cancelamento():
    _psql(CENARIO_VENDA)


@_precisa_pg
def test_disparo():
    _psql(CENARIO_DISPARO)


@_precisa_pg
def test_trigger_com_erro_nao_derruba_a_escrita():
    r = _rodar(CENARIO_ERRO)
    for fn in ("fn_lead_events_leads_entrada", "fn_lead_events_deals_etapa",
               "fn_lead_events_sales_venda", "fn_lead_events_sale_items_kit",
               "fn_lead_events_broadcast_disparo"):
        assert f"{fn}:" in r.stderr, fn  # o erro vira WARNING, não exceção



# Revisão (item 1): quem grava no CRM é muitas vezes `authenticated` (ex.:
# components/quick-add-lead.tsx). Em produção ele tem os grants da ACL padrão em lead_events,
# mas a tabela tem RLS SEM policy: rodando como quem grava, o insert do trigger viola o RLS e
# vira WARNING em silêncio. E uma role sem grant algum em lead_events (como no teste da P0)
# leva 'permission denied'. As duas têm que gerar os eventos.
_GRAVA_TUDO = """
insert into public.leads (id, phone, ctwa_clid) values ('__L__', '__FONE__', 'clid-sp');
update public.leads set meta_ad_id = 'ad-sp' where id = '__L__';
insert into public.deals (id, lead_id, title, pipeline_id, stage_id) values
  ('__D__', '__L__', 'Card', 'acacacac-0000-0000-0000-000000000001', 'acacacac-0000-0000-0000-0000000000a1');
update public.deals set stage_id = 'acacacac-0000-0000-0000-0000000000a2' where id = '__D__';
insert into public.sales (id, lead_id, value, product, origin) values ('__S__', '__L__', 60, 'Kit', 'crm');
insert into public.sale_items (sale_id, descricao, quantidade, valor_unitario, total)
values ('__S__', 'Kit Degustação', 1, 60, 60);
update public.sales set status = 'cancelada' where id = '__S__';
insert into public.broadcast_leads (id, broadcast_id, lead_id) values
  ('__B__', 'acacacac-0000-0000-0000-0000000000b1', '__L__');
update public.broadcast_leads set sent_at = now() where id = '__B__';
"""

_CONFERE_TUDO = """
do $$
declare n int;
begin
  select count(*) into n from public.lead_events where lead_id = '__L__';
  assert n = 6, format('__QUEM__: esperava 6 eventos (entrada, 2 etapas, venda, cancelada, disparo), achou %s', n);
  assert (select metadata->>'meta_ad_id' from public.lead_events
           where lead_id = '__L__' and event_type = 'entrada') = 'ad-sp', '__QUEM__: entrada enriquecida';
  assert (select metadata->>'kit' from public.lead_events where dedupe_key = 'venda:__S__') = 'true',
    '__QUEM__: kit marcado';
end $$;
"""


def _cenario_role(quem: str, n: int) -> str:
    ids = {
        "__L__": f"acacacac-0000-0000-0000-00000000{n:04d}",
        "__FONE__": f"551190009{n:04d}",
        "__D__": f"acacacac-0000-0000-0000-0000000d{n:04d}",
        "__S__": f"acacacac-0000-0000-0000-0000000e{n:04d}",
        "__B__": f"acacacac-0000-0000-0000-0000000f{n:04d}",
        "__QUEM__": quem,
    }
    sql = _GRAVA_TUDO + "reset role;\n" + _CONFERE_TUDO
    for k, v in ids.items():
        sql = sql.replace(k, v)
    return sql


CENARIO_SEM_PRIVILEGIO = (
    """
begin;
insert into public.meta_ad_campaigns (ad_id, campaign_id, campaign_name)
values ('ad-sp', 'camp-sp', 'Camp SP') on conflict (ad_id) do nothing;
insert into public.pipelines (id, name) values ('acacacac-0000-0000-0000-000000000001', 'Funil SP');
insert into public.pipeline_stages (id, pipeline_id, label, key, order_index) values
  ('acacacac-0000-0000-0000-0000000000a1', 'acacacac-0000-0000-0000-000000000001', 'Novo', 'novo', 0),
  ('acacacac-0000-0000-0000-0000000000a2', 'acacacac-0000-0000-0000-000000000001', 'Quente', 'quente', 1);
insert into public.broadcasts (id, name, template_name)
values ('acacacac-0000-0000-0000-0000000000b1', 'Disparo SP', 'tpl');

-- 1) authenticated como em produção: grants da ACL padrão + policies; lead_events com RLS sem policy
grant select, insert, update, delete on public.leads, public.deals, public.sales, public.sale_items,
  public.broadcast_leads, public.lead_events to authenticated;
create policy fxp3_deals on public.deals for all to authenticated using (true) with check (true);
create policy fxp3_itens on public.sale_items for all to authenticated using (true) with check (true);
create policy fxp3_bl on public.broadcast_leads for all to authenticated using (true) with check (true);
set local role authenticated;
"""
    + _cenario_role("authenticated", 1)
    + """
-- 2) role sem grant algum em lead_events/pipelines/broadcasts (como o teste da P0)
create role fxp3_t1 bypassrls;
grant select, insert, update on public.leads, public.deals, public.sales, public.sale_items,
  public.broadcast_leads to fxp3_t1;
set local role fxp3_t1;
"""
    + _cenario_role("sem privilegio", 2)
    + """
do $$
declare f text;
begin
  foreach f in array array['fn_lead_events_leads_entrada', 'fn_lead_events_deals_etapa',
      'fn_lead_events_sales_venda', 'fn_lead_events_sale_items_kit', 'fn_lead_events_broadcast_disparo'] loop
    assert not has_function_privilege('anon', 'public.' || f || '()', 'execute'), f || ' executavel por anon';
    assert not has_function_privilege('authenticated', 'public.' || f || '()', 'execute'),
      f || ' executavel por authenticated';
  end loop;
end $$;
rollback;
"""
)


@_precisa_pg
def test_role_sem_privilegio_grava_os_eventos():
    r = _rodar(CENARIO_SEM_PRIVILEGIO)
    assert "WARNING" not in r.stderr, r.stderr



# Revisão (item 2): a venda é editável (vendedor, valor, produto, data, origem). O evento
# acompanha a edição; a exclusão da venda apaga os eventos dela.
CENARIO_VENDA_EDITADA = """
begin;
insert into public.leads (id, phone) values ('cdcdcdcd-0000-0000-0000-0000000000c1', '5511900000061');
insert into public.sales (id, lead_id, value, product, origin, sold_by, sold_at) values
  ('cdcdcdcd-0000-0000-0000-0000000000e1', 'cdcdcdcd-0000-0000-0000-0000000000c1', 60, 'Kit',
   'crm', 'joao@x.com', '2026-09-01 12:00+00');
update public.sales set status = 'cancelada' where id = 'cdcdcdcd-0000-0000-0000-0000000000e1';
update public.lead_events set occurred_at = '2026-09-02 12:00+00'
 where dedupe_key = 'venda_cancelada:cdcdcdcd-0000-0000-0000-0000000000e1';
update public.sales set sold_by = 'ana@x.com', value = 80, product = 'Clássico',
       sold_at = '2026-09-05 12:00+00', origin = 'bling'
 where id = 'cdcdcdcd-0000-0000-0000-0000000000e1';
do $$
declare v public.lead_events; c public.lead_events;
begin
  select * into v from public.lead_events where dedupe_key = 'venda:cdcdcdcd-0000-0000-0000-0000000000e1';
  assert v.metadata->>'sold_by' = 'ana@x.com' and (v.metadata->>'valor')::numeric = 80
     and v.metadata->>'produto' = 'Clássico' and v.metadata->>'origin' = 'bling'
     and v.metadata->>'status' = 'cancelada', v.metadata::text;
  assert v.new_value = '80.00' and v.source = 'bling', v.new_value || ' ' || v.source;
  assert v.occurred_at = '2026-09-05 12:00+00', 'venda vai para a nova data: ' || v.occurred_at;
  select * into c from public.lead_events where dedupe_key = 'venda_cancelada:cdcdcdcd-0000-0000-0000-0000000000e1';
  assert c.metadata->>'sold_by' = 'ana@x.com' and c.new_value = '80.00', c.metadata::text;
  assert c.occurred_at = '2026-09-02 12:00+00', 'cancelamento mantem a data dele: ' || c.occurred_at;
end $$;
-- exclusão da venda (como authenticated, que em produção pode apagar venda)
grant select, delete on public.sales to authenticated;
set local role authenticated;
delete from public.sales where id = 'cdcdcdcd-0000-0000-0000-0000000000e1';
reset role;
do $$ begin
  assert not exists (select 1 from public.lead_events where lead_id = 'cdcdcdcd-0000-0000-0000-0000000000c1'),
    'venda apagada leva venda e venda_cancelada junto';
end $$;
rollback;
"""


@_precisa_pg
def test_venda_editada_e_apagada():
    r = _rodar(CENARIO_VENDA_EDITADA)
    assert "WARNING" not in r.stderr, r.stderr



# Revisão (item 3): o worker volta sent_at para NULL quando a Meta retém a mensagem pelo cap
# de marketing (131049). O disparo sai da timeline; o reenvio grava a data nova.
CENARIO_DISPARO_CAP = """
begin;
insert into public.broadcasts (id, name, template_name)
values ('dededede-0000-0000-0000-0000000000b1', 'Disparo Cap', 'tpl');
insert into public.leads (id, phone) values ('dededede-0000-0000-0000-0000000000c1', '5511900000071');
insert into public.broadcast_leads (id, broadcast_id, lead_id, sent_at) values
  ('dededede-0000-0000-0000-0000000000f1', 'dededede-0000-0000-0000-0000000000b1',
   'dededede-0000-0000-0000-0000000000c1', '2026-09-01 12:00+00');
update public.broadcast_leads set sent_at = null, wamid = null where id = 'dededede-0000-0000-0000-0000000000f1';
do $$ begin
  assert not exists (select 1 from public.lead_events where dedupe_key = 'disparo:dededede-0000-0000-0000-0000000000f1'),
    'disparo retido pelo cap sai da timeline';
end $$;
update public.broadcast_leads set sent_at = '2026-09-02 12:00+00' where id = 'dededede-0000-0000-0000-0000000000f1';
do $$ begin
  assert (select occurred_at from public.lead_events where dedupe_key = 'disparo:dededede-0000-0000-0000-0000000000f1')
    = '2026-09-02 12:00+00', 'reenvio grava a data nova';
end $$;
-- evento que sobrou (ex.: gravado pelo backfill com o trigger desligado): o reenvio atualiza
set session_replication_role = replica;
update public.broadcast_leads set sent_at = null where id = 'dededede-0000-0000-0000-0000000000f1';
update public.broadcasts set name = 'Disparo Cap v2' where id = 'dededede-0000-0000-0000-0000000000b1';
set session_replication_role = origin;
update public.broadcast_leads set sent_at = '2026-09-03 12:00+00' where id = 'dededede-0000-0000-0000-0000000000f1';
do $$
declare e public.lead_events;
begin
  select * into e from public.lead_events where dedupe_key = 'disparo:dededede-0000-0000-0000-0000000000f1';
  assert e.occurred_at = '2026-09-03 12:00+00', 'on conflict atualiza a data: ' || e.occurred_at;
  assert e.metadata->>'broadcast_nome' = 'Disparo Cap v2', e.metadata::text;
  assert (select count(*) from public.lead_events where lead_id = 'dededede-0000-0000-0000-0000000000c1') = 1,
    'um evento so';
end $$;
rollback;
"""


@_precisa_pg
def test_disparo_retido_pelo_cap_e_reenvio():
    r = _rodar(CENARIO_DISPARO_CAP)
    assert "WARNING" not in r.stderr, r.stderr


# ── Backfill: semente SEM triggers (o backfill é quem cria os eventos) ─────────────────
# L1 CTWA novo: referral na criação (+ repetido 5 min depois)  → 1 entrada (referral)
# L2 importado em 08/01, clicou em 09/10 (referral de número SEM o 9) → 1 entrada (referral)
# L3 LP Google (gclid/utm)                                      → 1 entrada inicial Google
# L4 LP orgânica (instagram/bio) e depois CTWA                   → inicial Orgânico + referral
# L5/L6 o mesmo número (phone de um, wa_id do outro)            → referral ambíguo, nada
SEED_BACKFILL = """
delete from public.leads where id::text like 'f0f0f0f0-%';
delete from public.meta_referrals_arquivo where log_id::text like 'f0f0f0f0-%';
delete from public.broadcasts where id::text like 'f0f0f0f0-%';
delete from public.pipelines where id::text like 'f0f0f0f0-%';
delete from public.meta_ad_campaigns where ad_id = 'ad-bf';
set session_replication_role = replica;
insert into public.meta_ad_campaigns (ad_id, campaign_id, campaign_name) values ('ad-bf', 'camp-bf', 'Campanha BF');
insert into public.leads (id, phone, wa_id, created_at, ctwa_clid, meta_ad_id, gclid, utm_source, utm_medium, utm_campaign) values
  ('f0f0f0f0-0000-0000-0000-000000000001', '5511911110001', null, '2026-09-01 10:00+00', 'clid-bf1', 'ad-bf', null, null, null, null),
  ('f0f0f0f0-0000-0000-0000-000000000002', '5511911110002', null, '2026-08-01 10:00+00', 'clid-bf2', 'ad-bf', null, null, null, null),
  ('f0f0f0f0-0000-0000-0000-000000000003', '5511911110003', null, '2026-09-05 10:00+00', null, null, 'g-bf', 'google', 'cpc', 'marca'),
  ('f0f0f0f0-0000-0000-0000-000000000004', '5511911110004', null, '2026-08-20 10:00+00', 'clid-bf4', null, null, 'instagram', 'bio', null),
  ('f0f0f0f0-0000-0000-0000-000000000005', '5511911110005', null, '2026-08-01 10:00+00', null, null, null, null, null, null),
  ('f0f0f0f0-0000-0000-0000-000000000006', '5511911110006', '5511911110005', '2026-08-01 10:00+00', null, null, null, null, null, null);
insert into public.meta_referrals_arquivo (log_id, received_at, from_number, ctwa_clid, source_id, source_type, referral) values
  ('f0f0f0f0-0000-0000-0000-0000000000a1', '2026-09-01 09:59:58+00', '5511911110001', 'clid-bf1', 'ad-bf', 'ad', '{"ctwa_clid": "clid-bf1", "source_id": "ad-bf"}'),
  ('f0f0f0f0-0000-0000-0000-0000000000a2', '2026-09-01 10:05:00+00', '5511911110001', 'clid-bf1', 'ad-bf', 'ad', '{"ctwa_clid": "clid-bf1", "source_id": "ad-bf", "n": 2}'),
  ('f0f0f0f0-0000-0000-0000-0000000000a3', '2026-09-10 14:00:00+00', '551111110002', 'clid-bf2', 'ad-bf', 'ad', '{"ctwa_clid": "clid-bf2", "source_id": "ad-bf"}'),
  ('f0f0f0f0-0000-0000-0000-0000000000a4', '2026-09-15 14:00:00+00', '5511911110004', 'clid-bf4', 'ad-bf', 'ad', '{"ctwa_clid": "clid-bf4", "source_id": "ad-bf"}'),
  ('f0f0f0f0-0000-0000-0000-0000000000a5', '2026-09-16 14:00:00+00', '5511911110005', 'clid-bf5', 'ad-bf', 'ad', '{"ctwa_clid": "clid-bf5", "source_id": "ad-bf"}');
insert into public.sales (id, lead_id, value, product, sold_at, origin, status) values
  ('f0f0f0f0-0000-0000-0000-0000000000e1', 'f0f0f0f0-0000-0000-0000-000000000001', 60, 'Kit Degustação', '2026-09-02 12:00+00', 'bling', 'registrada'),
  ('f0f0f0f0-0000-0000-0000-0000000000e2', 'f0f0f0f0-0000-0000-0000-000000000001', 30, 'Clássico', '2026-09-03 12:00+00', 'crm', 'cancelada');
insert into public.sale_items (sale_id, descricao, quantidade, valor_unitario, total) values
  ('f0f0f0f0-0000-0000-0000-0000000000e1', 'Kit Degustação 4 cafés', 1, 60, 60);
insert into public.pipelines (id, name) values ('f0f0f0f0-0000-0000-0000-0000000000b1', 'Funil BF');
insert into public.pipeline_stages (id, pipeline_id, label, key, order_index) values
  ('f0f0f0f0-0000-0000-0000-0000000000c1', 'f0f0f0f0-0000-0000-0000-0000000000b1', 'Novo', 'novo', 0),
  ('f0f0f0f0-0000-0000-0000-0000000000c2', 'f0f0f0f0-0000-0000-0000-0000000000b1', 'Qualificado', 'qualificado', 1);
insert into public.deals (id, lead_id, title, pipeline_id, stage_id, created_at, entered_stage_at) values
  ('f0f0f0f0-0000-0000-0000-0000000000d1', 'f0f0f0f0-0000-0000-0000-000000000001', 'Card 1',
   'f0f0f0f0-0000-0000-0000-0000000000b1', 'f0f0f0f0-0000-0000-0000-0000000000c1', '2026-09-01 10:01+00', '2026-09-01 10:01+00'),
  ('f0f0f0f0-0000-0000-0000-0000000000d2', 'f0f0f0f0-0000-0000-0000-000000000003', 'Card 3',
   'f0f0f0f0-0000-0000-0000-0000000000b1', 'f0f0f0f0-0000-0000-0000-0000000000c2', '2026-09-05 10:00+00', '2026-09-08 10:00+00');
insert into public.broadcasts (id, name, template_name) values ('f0f0f0f0-0000-0000-0000-0000000000b2', 'Disparo BF', 'tpl');
insert into public.broadcast_leads (id, broadcast_id, lead_id, sent_at) values
  ('f0f0f0f0-0000-0000-0000-0000000000f1', 'f0f0f0f0-0000-0000-0000-0000000000b2', 'f0f0f0f0-0000-0000-0000-000000000002', '2026-09-09 12:00+00'),
  ('f0f0f0f0-0000-0000-0000-0000000000f2', 'f0f0f0f0-0000-0000-0000-0000000000b2', 'f0f0f0f0-0000-0000-0000-000000000003', null);
set session_replication_role = origin;
"""

LIMPA_BACKFILL = """
delete from public.leads where id::text like 'f0f0f0f0-%';
delete from public.meta_referrals_arquivo where log_id::text like 'f0f0f0f0-%';
delete from public.broadcasts where id::text like 'f0f0f0f0-%';
delete from public.pipelines where id::text like 'f0f0f0f0-%';
delete from public.meta_ad_campaigns where ad_id = 'ad-bf';
"""

CONTA_BACKFILL = """
select coalesce(json_object_agg(event_type, n), '{}'::json) from (
  select event_type, count(*) as n from public.lead_events
   where lead_id::text like 'f0f0f0f0-%' group by event_type) t;
"""

CONFERE_BACKFILL = """
do $$
declare e public.lead_events;
begin
  -- L1: só o referral da criação (o repetido em 5 min colapsa; a "inicial" não entra)
  assert (select count(*) from public.lead_events where lead_id = 'f0f0f0f0-0000-0000-0000-000000000001'
           and event_type = 'entrada') = 1, 'L1: uma entrada';
  select * into e from public.lead_events where lead_id = 'f0f0f0f0-0000-0000-0000-000000000001' and event_type = 'entrada';
  assert e.dedupe_key like 'entrada:referral:f0f0f0f0-0000-0000-0000-0000000000a1:%', e.dedupe_key;
  assert e.metadata->>'campanha_nome' = 'Campanha BF' and e.metadata->>'canal' = 'Meta Ads' and e.source = 'ctwa', e.metadata::text;
  assert e.occurred_at = '2026-09-01 09:59:58+00', e.occurred_at::text;
  -- L2: referral de número sem o 9 casa com o lead; rastreio explicado → sem inicial
  assert (select count(*) from public.lead_events where lead_id = 'f0f0f0f0-0000-0000-0000-000000000002'
           and event_type = 'entrada') = 1, 'L2: uma entrada';
  assert (select occurred_at from public.lead_events where lead_id = 'f0f0f0f0-0000-0000-0000-000000000002'
           and event_type = 'entrada') = '2026-09-10 14:00+00', 'L2: na data do clique';
  -- L3: inicial Google
  select * into e from public.lead_events where dedupe_key = 'entrada:lead:f0f0f0f0-0000-0000-0000-000000000003:inicial';
  assert e.metadata->>'canal' = 'Google Ads' and e.source = 'google', coalesce(e.metadata::text, 'L3 sem inicial');
  -- L4: inicial orgânica sem o clid do clique posterior + o referral
  select * into e from public.lead_events where dedupe_key = 'entrada:lead:f0f0f0f0-0000-0000-0000-000000000004:inicial';
  assert e.metadata->>'canal' = 'Orgânico' and e.metadata->>'ctwa_clid' is null, coalesce(e.metadata::text, 'L4 sem inicial');
  assert (select count(*) from public.lead_events where lead_id = 'f0f0f0f0-0000-0000-0000-000000000004'
           and event_type = 'entrada') = 2, 'L4: inicial + referral';
  -- L5/L6: ambíguo
  assert not exists (select 1 from public.lead_events where lead_id in
           ('f0f0f0f0-0000-0000-0000-000000000005', 'f0f0f0f0-0000-0000-0000-000000000006')), 'ambiguo nao entra';
  -- venda com kit, card que se moveu = 2 eventos
  assert (select metadata->>'kit' from public.lead_events
           where dedupe_key = 'venda:f0f0f0f0-0000-0000-0000-0000000000e1') = 'true', 'kit';
  assert (select new_value from public.lead_events
           where dedupe_key = 'etapa:f0f0f0f0-0000-0000-0000-0000000000d2:criado') is null, 'etapa inicial desconhecida';
  assert (select count(*) from public.lead_events where lead_id = 'f0f0f0f0-0000-0000-0000-000000000003'
           and event_type = 'etapa' and new_value = 'Qualificado') = 1, 'etapa atual';
end $$;
"""

ESPERADO_BACKFILL = {"entrada": 5, "venda": 2, "venda_cancelada": 1, "etapa": 3, "disparo": 1}


def _backfill(*args: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(BACKFILL), "--psql", PSQL, "--json", *args],
        text=True, capture_output=True,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@_precisa_pg
def test_backfill_idempotente():
    _psql(SEED_BACKFILL)
    try:
        primeira = _backfill("--aplicar")
        assert json.loads(_psql(CONTA_BACKFILL).strip()) == ESPERADO_BACKFILL
        _psql(CONFERE_BACKFILL)
        assert primeira["referrals"]["ambiguos"] >= 1 and primeira["referrals"]["colapsados"] >= 1

        segunda = _backfill("--aplicar")
        assert segunda["inseridos"] == {}, segunda["inseridos"]
        assert json.loads(_psql(CONTA_BACKFILL).strip()) == ESPERADO_BACKFILL
        candidatos = lambda r: {e["event_type"]: e["candidatos"] for e in r["eventos"]}  # noqa: E731
        assert candidatos(segunda) == candidatos(primeira), "mesma contagem nas duas rodadas"
        assert all(e["existentes"] == e["candidatos"] for e in segunda["eventos"]), segunda["eventos"]

        seca = _backfill()
        assert all(e["candidatos"] == e["existentes"] for e in seca["eventos"]), seca["eventos"]
    finally:
        _psql(LIMPA_BACKFILL)


if __name__ == "__main__":
    if not PSQL:
        print("defina CS_P3_PSQL (ex.: docker exec -i crm-scratch-pg psql -U postgres -d p3)")
        sys.exit(2)
    falhas = 0
    for nome, fn in sorted((n, f) for n, f in list(globals().items())
                           if n.startswith("test_") and callable(f)):
        try:
            fn()
            print(f"ok     {nome}")
        except ImportError as exc:
            print(f"pulado {nome} ({exc})")
        except Exception as exc:  # noqa: BLE001 — runner mínimo
            falhas += 1
            print(f"FALHOU {nome}: {exc}")
    sys.exit(1 if falhas else 0)
