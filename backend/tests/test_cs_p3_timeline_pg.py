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


# (o cenário do backfill — SEED_BACKFILL, test_backfill_idempotente — entra na Task 2)


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
