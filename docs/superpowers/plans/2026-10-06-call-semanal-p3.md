# P3 — Linha do tempo do lead — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar ao lead uma linha do tempo única (entradas com canal/campanha, etapas, vendas com
selo kit, cancelamentos, disparos, mesclagens, atribuições manuais e dias em que conversou),
capturada por trigger no banco, completada por um backfill idempotente e mostrada numa aba.

**Architecture:** Migração `20261006b` (depois da P0) cria funções SQL de metadata/canal e cinco
triggers que escrevem em `lead_events` com `dedupe_key` determinística e nunca derrubam a escrita
original. `scripts/timeline/backfill_lead_events.py` monta UM `WITH … ` SQL que gera os mesmos
eventos (mesmas chaves) a partir do histórico e roda via `psql` (dry-run em transação READ ONLY).
A rota `GET /api/leads/[id]/timeline` junta `lead_events` com marcadores diários "conversou"
calculados de `messages`; `lead-timeline.tsx` desenha e é montado como aba no
`lead-detail-modal.tsx` (o P4 monta no `contact-detail.tsx`).

**Tech Stack:** Postgres 17 (plpgsql), Python 3 stdlib + `psql`, Next.js 16 App Router route
handler, React 19 + lucide-react, vitest + @testing-library/react, pytest.

**Regras (plano mestre):** todo comando pesado dentro de `flock /root/crm-wt/_heavy.lock`; sem
`next build`, sem suíte completa, sem `tsc` do projeto; produção só leitura; sem push; só os
arquivos do P3.

---

## Decisões de desenho (lidas do código real em 06/10)

1. **CTWA grava em dois passos.** `meta_router._register_lead` cria o lead com `ctwa_clid`
   (INSERT) e grava `meta_ad_id` num UPDATE separado segundos depois. Sem cuidado, todo lead CTWA
   ganharia duas "entradas". Regra: no UPDATE, se o lead tem `entrada` com `occurred_at` nos
   últimos 30 min, o trigger **funde** o snapshot novo nesse evento em vez de criar outro.
2. **`sale_items` chega depois de `sales`** (`orders.py:300`, e no update do Bling os itens são
   apagados e regravados, `orders.py:575`). O `kit` calculado no INSERT da venda quase sempre é
   `false`; um sexto trigger em `sale_items` (insert/delete/update de `descricao`) recalcula
   `metadata.kit` dos eventos `venda:`/`venda_cancelada:` da venda.
3. **Escopo de vendas.** A rota é aberta a qualquer usuário autenticado (o vendedor usa a conversa),
   então o evento de venda carrega `sold_by` e `origin` no metadata e a rota aplica
   `podeVerVenda` (mesma regra de `/api/leads/[id]/sales`).
4. **Chaves de dedupe** (trigger e backfill geram as mesmas):
   - `entrada:lead:<lead_id>:inicial` (INSERT do lead / entrada inicial no backfill)
   - `entrada:lead:<lead_id>:<epoch now()>` (UPDATE de rastreio fora da janela — só ao vivo)
   - `entrada:referral:<log_id>:<md5(referral)>` (só backfill)
   - `etapa:<deal_id>:criado` e `etapa:<deal_id>:<stage_id>:<epoch entered_stage_at>` — o trigger
     BEFORE `update_deal_entered_stage_at` já carimba `entered_stage_at = now()` na mudança, então o
     backfill acha a mesma chave para a etapa atual.
   - `venda:<sale_id>`, `venda_cancelada:<sale_id>`, `disparo:<broadcast_lead_id>`
5. **Backfill não depende das migrações para contar.** Produção ainda não tem P0 nem P3. O script
   detecta o esquema: sem P0 lê referrals de `meta_webhook_logs` e não marca "já existe"; sem P3 a
   metadata sai `null` (só contagem). `--aplicar` exige P0 + P3.
6. **Entrada inicial no backfill** usa o rastreio da linha do lead **menos** o que um referral já
   explica (`ctwa_clid`/`meta_ad_id` iguais aos de um referral do lead — é last-touch); se o
   primeiro referral é da criação (≤ created_at + 30 min), o referral é a entrada inicial.
   Referral com o mesmo anúncio/clid repetido em 30 min conta uma vez; telefone que casa com mais
   de um lead (phone ou wa_id, com/sem 9º dígito) é pulado como ambíguo.
7. **Testes de SQL real:** o container `canastra-api` não tem `psql` nem driver Postgres. Os testes
   que precisam do banco ficam em `backend/tests/test_cs_p3_timeline_pg.py`, pulam no pytest sem
   `CS_P3_PSQL` e rodam no host com `python3` (stdlib) contra o `crm-scratch-pg`.

## Arquivos

| Arquivo | Responsabilidade |
|---|---|
| Create `supabase/migrations/20261006b_lead_timeline_triggers.sql` | funções de canal/metadata + 5 triggers |
| Create `backend/tests/test_cs_p3_timeline_migration.py` | testes de texto da migração (CI) |
| Create `backend/tests/test_cs_p3_timeline_pg.py` | triggers + backfill num Postgres real |
| Create `scripts/timeline/backfill_lead_events.py` | backfill idempotente via psql |
| Create `backend/tests/test_cs_p3_backfill.py` | testes do montador de SQL / CLI (CI) |
| Create `frontend/src/app/api/leads/[id]/timeline/route.ts` | GET timeline |
| Create `frontend/src/app/api/leads/[id]/timeline/route.test.ts` | vitest da rota (prefixo exigido é `lead-timeline*` só para componentes; teste de rota fica ao lado da rota, como `origin/route.test.ts`) |
| Create `frontend/src/components/leads/lead-timeline.tsx` | componente + tipos do payload |
| Create `frontend/src/components/leads/lead-timeline.test.tsx` | vitest do componente |
| Modify `frontend/src/components/leads/lead-detail-modal.tsx` | só a aba "Linha do tempo" |

Comandos usados abaixo:

```bash
# pytest (container)
PYT='cd /root/crm-wt/cs-p3 && flock /root/crm-wt/_heavy.lock docker run --rm --user root -v $PWD:/repo -w /repo/backend -e SUPABASE_URL=https://example.supabase.co -e SUPABASE_SERVICE_KEY=ci-dummy canastra-api:latest sh -c "pip install -q -r requirements-dev.txt >/dev/null 2>&1; python -m pytest -q -p no:cacheprovider $ARQS"'
# Postgres real (host)
export CS_P3_PSQL="docker exec -i crm-scratch-pg psql -U postgres -d p3"
# aplicar migrações no banco p3 (P0 já aplicada na criação do banco)
cp supabase/migrations/20261006b_lead_timeline_triggers.sql /root/crm-wt/_scratchdb/p3_20261006b.sql
flock /root/crm-wt/_heavy.lock docker exec crm-scratch-pg psql -U postgres -d p3 -v ON_ERROR_STOP=1 -q -f /seed/p3_20261006b.sql
```

---

### Task 1: Migração de triggers

**Files:**
- Create: `backend/tests/test_cs_p3_timeline_migration.py`
- Create: `backend/tests/test_cs_p3_timeline_pg.py`
- Create: `supabase/migrations/20261006b_lead_timeline_triggers.sql`

- [ ] **Step 1: Teste de texto (falha: arquivo não existe)**

```python
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
```

- [ ] **Step 2: Teste de Postgres real** — `backend/tests/test_cs_p3_timeline_pg.py`
  (o cenário do backfill é acrescentado na Task 2, Step 2):

```python
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
```

- [ ] **Step 3: Rodar e ver falhar**

`ARQS=tests/test_cs_p3_timeline_migration.py` no container → FAIL (`FileNotFoundError` da
migração). `python3 backend/tests/test_cs_p3_timeline_pg.py` no host → FALHOU
(`function public.fn_lead_canal(...) does not exist`).

- [ ] **Step 4: A migração** — `supabase/migrations/20261006b_lead_timeline_triggers.sql`:

```sql
-- 20261006b_lead_timeline_triggers.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a mao, DEPOIS da 20261006_call_semanal_base.sql (P0).
--    Idempotente: pode rodar de novo sem efeito colateral.
--
-- Linha do tempo do lead (spec docs/superpowers/specs/2026-10-06-call-semanal-0110-design.md,
-- pacote P3). Captura por trigger, num lugar so, o que hoje esta espalhado:
--   entrada          leads: insert com rastreio, ou update que MUDA ctwa_clid/gclid/fbclid/
--                    meta_ad_id/utm_source/utm_campaign. Reentrada com rastreio identico nao
--                    gera evento (limitacao aceita).
--   etapa            deals: insert e update de stage_id.
--   venda            sales: insert. metadata.kit vem de sale_items (descricao ~ 'kit degust'),
--                    recalculado pelo trigger de sale_items porque os itens chegam DEPOIS.
--   venda_cancelada  sales: status passa a 'cancelada'.
--   disparo          broadcast_leads: sent_at passa a ter valor.
-- mesclagem e atribuicao_manual sao gravados pelo codigo do P1/P2.
--
-- dedupe_key deterministica: scripts/timeline/backfill_lead_events.py gera AS MESMAS chaves,
-- entao o backfill nao duplica o que o trigger ja gravou (e vice-versa).
-- Nenhum trigger derruba a escrita original: corpo em begin ... exception when others then
-- raise warning ... end.

-- ── 0. CANAL — espelho de backend/app/campaigns/traffic_report.py:derive_channel ──────
-- As tres listas abaixo sao testadas contra as constantes do Python
-- (backend/tests/test_cs_p3_timeline_migration.py). Mudou la, muda aqui.
create or replace function public.fn_lead_txt(p text)
returns text language sql immutable as $$
  select lower(btrim(coalesce(p, ''), E' \t\r\n\f'))
$$;

create or replace function public.fn_lead_canal(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_traffic_type text
) returns text language sql immutable as $$
  select case
    when public.fn_lead_txt(p_gclid) <> '' then 'Google Ads'
    when public.fn_lead_txt(p_fbclid) <> '' or public.fn_lead_txt(p_ctwa_clid) <> ''
      or public.fn_lead_txt(p_meta_ad_id) <> '' then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['metaads', 'meta_ads', 'meta-ads', 'meta', 'facebook_ads', 'facebookads', 'fb_ads']) -- _META_AD_SOURCES
      then 'Meta Ads'
    when public.fn_lead_txt(p_utm_source) = any (array['google', 'googleads', 'google_ads', 'adwords']) -- _GOOGLE_AD_SOURCES
     and public.fn_lead_txt(p_utm_medium) = any (array['cpc', 'ppc', 'pmax', 'performance_max', 'paid', 'paid_search', 'paidsearch', 'display', 'cpm', 'paid_social', 'paidsocial']) -- _PAID_CHANNEL_MEDIUMS
      then 'Google Ads'
    when public.fn_lead_txt(p_traffic_type) = 'organic' or public.fn_lead_txt(p_utm_source) <> ''
      then 'Orgânico'
    else 'Sem rastreio'
  end
$$;

create or replace function public.fn_lead_tem_rastreio(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_campaign text
) returns boolean language sql immutable as $$
  select public.fn_lead_txt(p_gclid) <> '' or public.fn_lead_txt(p_fbclid) <> ''
      or public.fn_lead_txt(p_ctwa_clid) <> '' or public.fn_lead_txt(p_meta_ad_id) <> ''
      or public.fn_lead_txt(p_utm_source) <> '' or public.fn_lead_txt(p_utm_campaign) <> ''
$$;

-- ── 1. METADATA (contratos do P0; o backfill usa as mesmas funcoes) ───────────────────
-- entrada: {canal, campanha_id, campanha_nome, ctwa_clid, meta_ad_id, gclid, fbclid,
--           utm_source, utm_medium, utm_campaign}. campanha_* so via meta_ad_campaigns:
-- slug de utm NAO e nome de campanha (o P2 casa o Google pelo ad_spend).
create or replace function public.fn_lead_entrada_metadata(
  p_gclid text, p_fbclid text, p_ctwa_clid text, p_meta_ad_id text,
  p_utm_source text, p_utm_medium text, p_utm_campaign text, p_traffic_type text
) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'canal', public.fn_lead_canal(p_gclid, p_fbclid, p_ctwa_clid, p_meta_ad_id,
                                  p_utm_source, p_utm_medium, p_traffic_type),
    'campanha_id', mac.campaign_id,
    'campanha_nome', nullif(mac.campaign_name, ''),
    'ctwa_clid', p_ctwa_clid,
    'meta_ad_id', p_meta_ad_id,
    'gclid', p_gclid,
    'fbclid', p_fbclid,
    'utm_source', p_utm_source,
    'utm_medium', p_utm_medium,
    'utm_campaign', p_utm_campaign)
  from (select 1) as um
  left join public.meta_ad_campaigns mac on mac.ad_id = nullif(btrim(p_meta_ad_id), '')
$$;

-- lead_events.source da entrada: google | ctwa | lp.
create or replace function public.fn_lead_entrada_source(p_meta jsonb)
returns text language sql immutable as $$
  select case
    when p_meta->>'canal' = 'Google Ads' then 'google'
    when coalesce(p_meta->>'ctwa_clid', '') <> '' or coalesce(p_meta->>'meta_ad_id', '') <> '' then 'ctwa'
    else 'lp'
  end
$$;

-- venda: sold_by/origin vao junto porque a rota aplica o escopo de vendas do vendedor.
create or replace function public.fn_lead_events_venda_metadata(p_sale public.sales)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'sale_id', p_sale.id,
    'valor', p_sale.value,
    'produto', p_sale.product,
    'origin', p_sale.origin,
    'status', p_sale.status,
    'sold_by', p_sale.sold_by,
    'bling_account', p_sale.bling_account,
    'bling_order_number', p_sale.bling_order_number,
    'deal_id', p_sale.deal_id,
    'kit', exists (select 1 from public.sale_items i
                    where i.sale_id = p_sale.id and i.descricao ilike '%kit degust%'))
$$;

create or replace function public.fn_lead_events_etapa_metadata(
  p_deal_id uuid, p_pipeline_id uuid, p_de uuid, p_para uuid
) returns jsonb language sql stable as $$
  select jsonb_build_object(
    'deal_id', p_deal_id,
    'pipeline_id', p_pipeline_id,
    'pipeline_nome', p.name,
    'de_stage_id', p_de,
    'de_label', sd.label,
    'de_key', sd.key,
    'para_stage_id', p_para,
    'para_label', sp.label,
    'para_key', sp.key)
  from (select 1) as um
  left join public.pipelines p on p.id = p_pipeline_id
  left join public.pipeline_stages sd on sd.id = p_de
  left join public.pipeline_stages sp on sp.id = p_para
$$;

create or replace function public.fn_lead_events_disparo_metadata(p_bl public.broadcast_leads)
returns jsonb language sql stable as $$
  select jsonb_build_object(
    'broadcast_lead_id', p_bl.id,
    'broadcast_id', p_bl.broadcast_id,
    'broadcast_nome', b.name,
    'template_name', b.template_name)
  from (select 1) as um
  left join public.broadcasts b on b.id = p_bl.broadcast_id
$$;

-- ── 2. ENTRADA (leads) ─────────────────────────────────────────────────────────────────
-- O webhook CTWA cria o lead com ctwa_clid e grava meta_ad_id num UPDATE separado
-- (meta_router._register_lead). Update de rastreio a menos de 30 min da ultima entrada
-- FUNDE o snapshot nela em vez de criar outra.
create or replace function public.fn_lead_events_leads_entrada()
returns trigger language plpgsql as $$
declare
  v_meta jsonb;
  v_ultimo uuid;
begin
  begin
    if not public.fn_lead_tem_rastreio(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                       new.utm_source, new.utm_campaign) then
      return new;
    end if;
    if tg_op = 'UPDATE' then
      if new.ctwa_clid is not distinct from old.ctwa_clid
         and new.gclid is not distinct from old.gclid
         and new.fbclid is not distinct from old.fbclid
         and new.meta_ad_id is not distinct from old.meta_ad_id
         and new.utm_source is not distinct from old.utm_source
         and new.utm_campaign is not distinct from old.utm_campaign then
        return new;
      end if;
    end if;

    v_meta := public.fn_lead_entrada_metadata(new.gclid, new.fbclid, new.ctwa_clid, new.meta_ad_id,
                                              new.utm_source, new.utm_medium, new.utm_campaign,
                                              new.traffic_type);

    if tg_op = 'UPDATE' then
      select e.id into v_ultimo
        from public.lead_events e
       where e.lead_id = new.id
         and e.event_type = 'entrada'
         and e.occurred_at >= now() - interval '30 minutes'
       order by e.occurred_at desc, e.created_at desc
       limit 1;
      if v_ultimo is not null then
        update public.lead_events
           set metadata = coalesce(metadata, '{}'::jsonb) || v_meta,
               new_value = v_meta->>'canal',
               source = public.fn_lead_entrada_source(v_meta)
         where id = v_ultimo;
        return new;
      end if;
    end if;

    insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
    values (new.id, 'entrada', v_meta->>'canal', v_meta,
            case when tg_op = 'INSERT' then coalesce(new.created_at, now()) else now() end,
            public.fn_lead_entrada_source(v_meta),
            case when tg_op = 'INSERT' then 'entrada:lead:' || new.id || ':inicial'
                 else 'entrada:lead:' || new.id || ':' || extract(epoch from now())::text end)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_leads_entrada: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_leads_entrada on public.leads;
create trigger trg_lead_events_leads_entrada
  after insert or update of ctwa_clid, gclid, fbclid, meta_ad_id, utm_source, utm_campaign
  on public.leads
  for each row execute function public.fn_lead_events_leads_entrada();

-- ── 3. ETAPA (deals) ───────────────────────────────────────────────────────────────────
-- O BEFORE trigger update_deal_entered_stage_at ja carimbou entered_stage_at = now() na
-- mudanca: a chave usa esse instante, e o backfill acha a mesma para a etapa atual.
create or replace function public.fn_lead_events_deals_etapa()
returns trigger language plpgsql as $$
declare
  v_de uuid;
  v_meta jsonb;
  v_quando timestamptz;
begin
  begin
    if new.lead_id is null or new.stage_id is null then
      return new;
    end if;
    if tg_op = 'UPDATE' then
      if new.stage_id is not distinct from old.stage_id then
        return new;
      end if;
      v_de := old.stage_id;
    end if;

    v_meta := public.fn_lead_events_etapa_metadata(new.id, new.pipeline_id, v_de, new.stage_id);

    if tg_op = 'INSERT' then
      insert into public.lead_events (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'etapa', null, v_meta->>'para_label', v_meta,
              coalesce(new.created_at, now()), 'crm',
              'etapa:' || new.id || ':criado')
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
    else
      v_quando := coalesce(new.entered_stage_at, now());
      insert into public.lead_events (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'etapa', v_meta->>'de_label', v_meta->>'para_label', v_meta,
              v_quando, 'crm',
              'etapa:' || new.id || ':' || new.stage_id || ':' || extract(epoch from v_quando)::text)
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
    end if;
  exception when others then
    raise warning 'fn_lead_events_deals_etapa: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_deals_etapa on public.deals;
create trigger trg_lead_events_deals_etapa
  after insert or update of stage_id
  on public.deals
  for each row execute function public.fn_lead_events_deals_etapa();

-- ── 4. VENDA / VENDA_CANCELADA (sales) ─────────────────────────────────────────────────
create or replace function public.fn_lead_events_sales_venda()
returns trigger language plpgsql as $$
declare
  v_meta jsonb;
  v_source text;
  v_cancelou boolean;
begin
  begin
    if new.lead_id is null then
      return new;
    end if;
    v_meta := public.fn_lead_events_venda_metadata(new);
    v_source := case when new.origin = 'bling' then 'bling' else 'crm' end;

    if tg_op = 'INSERT' then
      insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'venda', new.value::text, v_meta, new.sold_at, v_source,
              'venda:' || new.id)
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
      v_cancelou := new.status = 'cancelada';
    else
      update public.lead_events
         set metadata = coalesce(metadata, '{}'::jsonb) || jsonb_build_object('status', new.status)
       where dedupe_key = 'venda:' || new.id;
      v_cancelou := new.status = 'cancelada' and old.status is distinct from 'cancelada';
    end if;

    if v_cancelou then
      insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
      values (new.lead_id, 'venda_cancelada', new.value::text, v_meta,
              case when tg_op = 'INSERT' then coalesce(new.bling_event_date, new.sold_at) else now() end,
              v_source, 'venda_cancelada:' || new.id)
      on conflict (dedupe_key) where dedupe_key is not null do nothing;
    end if;
  exception when others then
    raise warning 'fn_lead_events_sales_venda: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_sales_venda on public.sales;
create trigger trg_lead_events_sales_venda
  after insert or update of status
  on public.sales
  for each row execute function public.fn_lead_events_sales_venda();

-- Os itens chegam depois da venda (orders.py grava sales e depois sale_items; no update do
-- Bling apaga e regrava). Recalcula metadata.kit dos eventos da venda.
create or replace function public.fn_lead_events_sale_items_kit()
returns trigger language plpgsql as $$
declare
  v_sale uuid;
  v_kit boolean;
begin
  begin
    if tg_op = 'DELETE' then
      v_sale := old.sale_id;
    else
      v_sale := new.sale_id;
    end if;
    v_kit := exists (select 1 from public.sale_items i
                      where i.sale_id = v_sale and i.descricao ilike '%kit degust%');
    update public.lead_events e
       set metadata = coalesce(e.metadata, '{}'::jsonb) || jsonb_build_object('kit', v_kit)
     where e.dedupe_key in ('venda:' || v_sale, 'venda_cancelada:' || v_sale)
       and (e.metadata->'kit') is distinct from to_jsonb(v_kit);
  exception when others then
    raise warning 'fn_lead_events_sale_items_kit: %', sqlerrm;
  end;
  return null;
end $$;

drop trigger if exists trg_lead_events_sale_items_kit on public.sale_items;
create trigger trg_lead_events_sale_items_kit
  after insert or delete or update of descricao
  on public.sale_items
  for each row execute function public.fn_lead_events_sale_items_kit();

-- ── 5. DISPARO (broadcast_leads) ───────────────────────────────────────────────────────
create or replace function public.fn_lead_events_broadcast_disparo()
returns trigger language plpgsql as $$
declare
  v_meta jsonb;
begin
  begin
    if new.lead_id is null or new.sent_at is null then
      return new;
    end if;
    if tg_op = 'UPDATE' then
      if old.sent_at is not null then
        return new;
      end if;
    end if;
    v_meta := public.fn_lead_events_disparo_metadata(new);
    insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
    values (new.lead_id, 'disparo', v_meta->>'broadcast_nome', v_meta, new.sent_at, 'disparo',
            'disparo:' || new.id)
    on conflict (dedupe_key) where dedupe_key is not null do nothing;
  exception when others then
    raise warning 'fn_lead_events_broadcast_disparo: %', sqlerrm;
  end;
  return new;
end $$;

drop trigger if exists trg_lead_events_broadcast_disparo on public.broadcast_leads;
create trigger trg_lead_events_broadcast_disparo
  after insert or update of sent_at
  on public.broadcast_leads
  for each row execute function public.fn_lead_events_broadcast_disparo();
```

- [ ] **Step 5: Rodar e ver passar**

`ARQS="tests/test_cs_p3_timeline_migration.py tests/test_cs_p3_timeline_pg.py"` no container →
PASS (os de PG pulam; `test_casos_de_canal_batem_com_derive_channel` roda). Aplicar a migração 2×
no `p3` (comando do topo) → sem erro. `CS_P3_PSQL=… python3 backend/tests/test_cs_p3_timeline_pg.py`
→ todos `ok` (o de derive_channel aparece `pulado` no host).

- [ ] **Step 6: Commit**

```bash
git add supabase/migrations/20261006b_lead_timeline_triggers.sql backend/tests/test_cs_p3_timeline_migration.py backend/tests/test_cs_p3_timeline_pg.py
git commit -m "feat(timeline): P3 — triggers da linha do tempo em lead_events"
```

---

### Task 2: Backfill idempotente

**Files:**
- Create: `scripts/timeline/backfill_lead_events.py`
- Create: `backend/tests/test_cs_p3_backfill.py`
- Modify: `backend/tests/test_cs_p3_timeline_pg.py` (cenário do backfill)

- [ ] **Step 1: Teste do script (falha: arquivo não existe)** — `backend/tests/test_cs_p3_backfill.py`:

```python
"""Backfill da linha do tempo (P3): montagem do SQL e CLI. Execução real em
test_cs_p3_timeline_pg.py::test_backfill_idempotente."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "backfill_lead_events", RAIZ / "scripts" / "timeline" / "backfill_lead_events.py"
)
bf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bf  # @dataclass procura o módulo em sys.modules
_spec.loader.exec_module(bf)

MIG = (RAIZ / "supabase" / "migrations" / "20261006b_lead_timeline_triggers.sql").read_text(
    encoding="utf-8"
)

COMPLETO = bf.Esquema(p0=True, arquivo=True, p3=True)
PROD_HOJE = bf.Esquema(p0=False, arquivo=False, p3=False)


def test_dry_run_e_read_only_e_nao_insere():
    sql = bf.montar_sql(COMPLETO, aplicar=False)
    assert sql.startswith("begin transaction read only;")
    assert sql.rstrip().endswith("rollback;")
    assert "insert into" not in sql.lower()


def test_aplicar_insere_com_on_conflict_e_commita():
    sql = bf.montar_sql(COMPLETO, aplicar=True)
    assert sql.startswith("begin;")
    assert "insert into public.lead_events" in sql
    assert "on conflict (dedupe_key) where dedupe_key is not null do nothing" in sql
    assert sql.rstrip().endswith("commit;")


def test_aplicar_sem_migracoes_recusa():
    with pytest.raises(ValueError):
        bf.montar_sql(PROD_HOJE, aplicar=True)
    with pytest.raises(ValueError):
        bf.montar_sql(bf.Esquema(p0=True, arquivo=True, p3=False), aplicar=True)


def test_sem_p0_le_referrals_do_log_e_nao_usa_colunas_novas():
    sql = bf.montar_sql(PROD_HOJE, aplicar=False)
    assert "from public.meta_webhook_logs" in sql
    assert "meta_referrals_arquivo" not in sql
    assert "e.dedupe_key = c.dedupe_key" not in sql
    assert "e.occurred_at between" not in sql
    assert "public.fn_" not in sql


def test_com_p0_le_do_arquivo_e_marca_existentes():
    sql = bf.montar_sql(COMPLETO, aplicar=False)
    assert "from public.meta_referrals_arquivo" in sql
    assert "meta_webhook_logs" not in sql
    assert "e.dedupe_key = c.dedupe_key" in sql


@pytest.mark.parametrize("esq", [COMPLETO, PROD_HOJE, bf.Esquema(p0=True, arquivo=False, p3=False)])
def test_todos_os_tokens_substituidos(esq):
    assert "__" not in bf.montar_sql(esq, aplicar=False)


@pytest.mark.parametrize(
    "no_trigger, no_backfill",
    [
        ("'entrada:lead:' || new.id || ':inicial'", "'entrada:lead:' || l.id || ':inicial'"),
        ("'venda:' || new.id", "'venda:' || s.id"),
        ("'venda_cancelada:' || new.id", "'venda_cancelada:' || s.id"),
        ("'disparo:' || new.id", "'disparo:' || bl.id"),
        ("'etapa:' || new.id || ':criado'", "'etapa:' || d.id || ':criado'"),
        (
            "'etapa:' || new.id || ':' || new.stage_id || ':' || extract(epoch from v_quando)::text",
            "'etapa:' || d.id || ':' || d.stage_id || ':' || extract(epoch from d.entered_stage_at)::text",
        ),
    ],
)
def test_dedupe_key_do_backfill_e_a_mesma_do_trigger(no_trigger, no_backfill):
    assert no_trigger in MIG
    assert no_backfill in bf.montar_sql(COMPLETO, aplicar=True)


def test_main_aplicar_sem_migracoes_sai_com_2():
    chamadas = []

    def rodar(sql):
        chamadas.append(sql)
        return json.dumps({"p0": False, "arquivo": False, "p3": False}) + "\n"

    assert bf.main(["--aplicar"], rodar=rodar) == 2
    assert len(chamadas) == 1  # só a detecção de esquema


def test_main_dry_run_imprime_contagens(capsys):
    respostas = iter([
        json.dumps({"p0": False, "arquivo": False, "p3": False}),
        json.dumps({
            "eventos": [{"event_type": "venda", "candidatos": 10, "existentes": 0}],
            "referrals": {"total": 5, "sem_lead": 1, "ambiguos": 0, "colapsados": 1, "ja_cobertos": 0},
            "inseridos": {},
        }),
    ])
    assert bf.main([], rodar=lambda sql: next(respostas)) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "meta_webhook_logs" in out
    assert "venda" in out and "10" in out


def test_ultimo_json_ignora_linhas_vazias():
    assert bf.ultimo_json('\n\n{"a": 1}\n\n') == {"a": 1}
```

- [ ] **Step 2: Cenário real do backfill** — acrescentar em `test_cs_p3_timeline_pg.py`, antes do
  `if __name__`, substituindo o comentário "(o cenário do backfill … entra na Task 2)":

```python
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
```

- [ ] **Step 3: Rodar e ver falhar** — `ARQS=tests/test_cs_p3_backfill.py` → FAIL (arquivo do script
  não existe); runner do host → `test_backfill_idempotente` FALHOU.

- [ ] **Step 4: O script** — `scripts/timeline/backfill_lead_events.py`:

```python
#!/usr/bin/env python3
"""Backfill da linha do tempo do lead (`lead_events`) — pacote P3 da call de 01/10.

Dry-run por padrão (transação READ ONLY, nada gravado). Só grava com --aplicar, e --aplicar
exige as migrações 20261006 (P0) e 20261006b (P3) aplicadas. Idempotente: cada evento tem a
MESMA `dedupe_key` que os triggers da 20261006b gravam, e o insert é
`on conflict (dedupe_key) do nothing` — rodar 2× não duplica.

O que entra (spec P3.2):
  entrada          um evento por referral CTWA (meta_referrals_arquivo; sem a P0, lê do
                   meta_webhook_logs) casado ao lead pelo telefone (phone ou wa_id, com e sem
                   o 9º dígito). Número que casa com mais de um lead fica de fora (ambíguo). O
                   mesmo clique/anúncio repetido em 30 min conta uma vez. Referral a ±30 min de
                   uma entrada gravada AO VIVO pelo trigger também fica de fora.
                   + a entrada inicial (created_at) com o rastreio da própria linha MENOS o que um
                   referral já explica (ctwa_clid/meta_ad_id são last-touch). Se o primeiro
                   referral é da criação, ele é a entrada inicial.
  venda / venda_cancelada   todas as vendas (cancelada: bling_event_date ou sold_at).
  etapa            criação do card (created_at) e, se o card já se moveu, a etapa atual
                   (entered_stage_at). A etapa em que o card nasceu, nesse caso, é desconhecida.
  disparo          broadcast_leads com sent_at.

Uso (o comando psql recebe -X -q -A -t -v ON_ERROR_STOP=1 e o SQL pela entrada padrão):
  python3 scripts/timeline/backfill_lead_events.py --psql "docker exec -i <db> psql -U postgres -d postgres"
  python3 scripts/timeline/backfill_lead_events.py --psql "psql postgresql://…" --aplicar
  --json imprime o resultado cru. Sem --psql: $TIMELINE_PSQL, senão `psql` (variáveis PG*).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

Rodar = Callable[[str], str]


@dataclass(frozen=True)
class Esquema:
    p0: bool  # lead_events.occurred_at/source/dedupe_key existem
    arquivo: bool  # meta_referrals_arquivo existe
    p3: bool  # funções de metadata da 20261006b existem

    @property
    def completo(self) -> bool:
        return self.p0 and self.p3


SQL_ESQUEMA = """select json_build_object(
  'p0', exists (select 1 from information_schema.columns
                 where table_schema = 'public' and table_name = 'lead_events'
                   and column_name = 'dedupe_key'),
  'arquivo', to_regclass('public.meta_referrals_arquivo') is not null,
  'p3', to_regprocedure('public.fn_lead_entrada_metadata(text,text,text,text,text,text,text,text)') is not null
);
"""

REFS_ARQUIVO = """      select a.log_id, a.received_at, a.from_number, a.ctwa_clid, a.source_id,
             md5(a.referral::text) as ref_hash
        from public.meta_referrals_arquivo a"""

# Mesma extração da fn_arquiva_meta_referrals do P0 (o hash bate com o do arquivo).
REFS_LOG = """      select l.id as log_id, l.received_at, coalesce(m->>'from', l.from_number) as from_number,
             m->'referral'->>'ctwa_clid' as ctwa_clid, m->'referral'->>'source_id' as source_id,
             md5((m->'referral')::text) as ref_hash
        from public.meta_webhook_logs l,
             jsonb_path_query(l.payload, '$.entry[*].changes[*].value.messages[*]') as m
       where l.direction = 'inbound'
         and l.payload::text like '%"referral"%'
         and m ? 'referral'"""

CTE = """with refs as (
  select distinct on (r0.log_id, r0.ref_hash) r0.*
    from (
__REFS__
    ) r0
   order by r0.log_id, r0.ref_hash
),
ref_chaves as (
  select r.log_id, r.ref_hash, k.chave
    from refs r
   cross join lateral (values
     (r.from_number),
     (case when r.from_number ~ '^55[0-9]{10}$'
           then substr(r.from_number, 1, 4) || '9' || substr(r.from_number, 5) end),
     (case when r.from_number ~ '^55[0-9]{2}9[0-9]{8}$'
           then substr(r.from_number, 1, 4) || substr(r.from_number, 6) end)
   ) as k(chave)
   where k.chave is not null
),
ref_match as (
  select x.log_id, x.ref_hash, count(distinct x.lead_id) as n, min(x.lead_id::text)::uuid as lead_id
    from (
      select c.log_id, c.ref_hash, l.id as lead_id
        from ref_chaves c join public.leads l on l.phone = c.chave
      union
      select c.log_id, c.ref_hash, l.id as lead_id
        from ref_chaves c join public.leads l on l.wa_id = c.chave
    ) x
   group by x.log_id, x.ref_hash
),
ref_lead as (
  select r.*, m.lead_id,
         lag(r.received_at) over w as ant_received_at,
         lag(coalesce(r.ctwa_clid, r.source_id)) over w as ant_chave
    from refs r
    join ref_match m on m.log_id = r.log_id and m.ref_hash = r.ref_hash and m.n = 1
  window w as (partition by m.lead_id order by r.received_at, r.log_id)
),
ref_ok as (
  select * from ref_lead
   where ant_received_at is null
      or coalesce(ctwa_clid, source_id) is distinct from ant_chave
      or received_at - ant_received_at > interval '30 minutes'
),
leads_ini as (
  select l.id, l.created_at, l.gclid, l.fbclid, l.utm_source, l.utm_medium, l.utm_campaign,
         l.traffic_type,
         case when exists (select 1 from ref_lead r where r.lead_id = l.id and r.ctwa_clid = l.ctwa_clid)
              then null else l.ctwa_clid end as ctwa_clid,
         case when exists (select 1 from ref_lead r where r.lead_id = l.id and r.source_id = l.meta_ad_id)
              then null else l.meta_ad_id end as meta_ad_id,
         exists (select 1 from ref_ok r
                  where r.lead_id = l.id
                    and r.received_at <= l.created_at + interval '30 minutes') as ref_inicial
    from public.leads l
   where l.created_at is not null
),
deals_bf as (
  select d.id, d.lead_id, d.pipeline_id, d.stage_id, d.created_at, d.entered_stage_at,
         (d.entered_stage_at is not null
          and d.entered_stage_at > d.created_at + interval '1 minute') as mudou
    from public.deals d
   where d.lead_id is not null and d.stage_id is not null and d.created_at is not null
),
cand as (
  select r.lead_id, 'entrada'::text as event_type, null::text as old_value,
         'Meta Ads'::text as new_value, __META_REF__ as metadata,
         r.received_at as occurred_at, 'ctwa'::text as source,
         'entrada:referral:' || r.log_id || ':' || r.ref_hash as dedupe_key
    from ref_ok r
   where __SEM_ENTRADA_VIVA__
  union all
  select l.id, 'entrada', null, __CANAL_INI__, __META_INI__, l.created_at, __SOURCE_INI__,
         'entrada:lead:' || l.id || ':inicial'
    from leads_ini l
   where not l.ref_inicial
     and coalesce(nullif(btrim(l.gclid), ''), nullif(btrim(l.fbclid), ''),
                  nullif(btrim(l.ctwa_clid), ''), nullif(btrim(l.meta_ad_id), ''),
                  nullif(btrim(l.utm_source), ''), nullif(btrim(l.utm_campaign), '')) is not null
  union all
  select s.lead_id, 'venda', null, s.value::text, __META_VENDA__, s.sold_at,
         case when s.origin = 'bling' then 'bling' else 'crm' end,
         'venda:' || s.id
    from public.sales s
   where s.lead_id is not null
  union all
  select s.lead_id, 'venda_cancelada', null, s.value::text, __META_VENDA__,
         coalesce(s.bling_event_date, s.sold_at),
         case when s.origin = 'bling' then 'bling' else 'crm' end,
         'venda_cancelada:' || s.id
    from public.sales s
   where s.lead_id is not null and s.status = 'cancelada'
  union all
  select d.lead_id, 'etapa', null, case when d.mudou then null else ps.label end,
         __META_CRIADO__, d.created_at, 'crm',
         'etapa:' || d.id || ':criado'
    from deals_bf d
    left join public.pipeline_stages ps on ps.id = d.stage_id
  union all
  select d.lead_id, 'etapa', null, ps.label, __META_MOVE__, d.entered_stage_at, 'crm',
         'etapa:' || d.id || ':' || d.stage_id || ':' || extract(epoch from d.entered_stage_at)::text
    from deals_bf d
    left join public.pipeline_stages ps on ps.id = d.stage_id
   where d.mudou
  union all
  select bl.lead_id, 'disparo', null, b.name, __META_DISPARO__, bl.sent_at, 'disparo',
         'disparo:' || bl.id
    from public.broadcast_leads bl
    left join public.broadcasts b on b.id = bl.broadcast_id
   where bl.sent_at is not null and bl.lead_id is not null
),
marcado as (
  select c.*, __EXISTE__ as existe from cand c
)"""

CONTAGEM = """(select coalesce(json_agg(t order by t.event_type), '[]'::json) from (
      select event_type, count(*) as candidatos, count(*) filter (where existe) as existentes
        from marcado group by event_type) t)"""

REFERRALS = """json_build_object(
    'total', (select count(*) from refs),
    'sem_lead', (select count(*) from refs r
                  where not exists (select 1 from ref_match m
                                     where m.log_id = r.log_id and m.ref_hash = r.ref_hash)),
    'ambiguos', (select count(*) from ref_match where n > 1),
    'colapsados', (select count(*) from ref_lead) - (select count(*) from ref_ok),
    'ja_cobertos', (select count(*) from ref_ok)
                   - (select count(*) from cand where dedupe_key like 'entrada:referral:%'))"""

FINAL_DRY = """
select jsonb_build_object(  -- jsonb: sai numa linha só (json_agg quebra linha)
  'eventos', __CONTAGEM__,
  'referrals', __REFERRALS__,
  'inseridos', '{}'::json)"""

FINAL_APLICAR = """,
ins as (
  insert into public.lead_events
         (lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key)
  select lead_id, event_type, old_value, new_value, metadata, occurred_at, source, dedupe_key
    from cand
  on conflict (dedupe_key) where dedupe_key is not null do nothing
  returning event_type
)
select jsonb_build_object(  -- jsonb: sai numa linha só (json_agg quebra linha)
  'eventos', __CONTAGEM__,
  'referrals', __REFERRALS__,
  'inseridos', (select coalesce(json_object_agg(event_type, n), '{}'::json)
                  from (select event_type, count(*) as n from ins group by event_type) t))"""

META_INI = ("public.fn_lead_entrada_metadata(l.gclid, l.fbclid, l.ctwa_clid, l.meta_ad_id, "
            "l.utm_source, l.utm_medium, l.utm_campaign, l.traffic_type)")


def _tokens(esq: Esquema) -> dict[str, str]:
    t = {
        "__REFS__": REFS_ARQUIVO if esq.arquivo else REFS_LOG,
        "__SEM_ENTRADA_VIVA__": "true",
        "__EXISTE__": "false",
        "__META_REF__": "null::jsonb",
        "__META_INI__": "null::jsonb",
        "__CANAL_INI__": "null::text",
        "__SOURCE_INI__": "null::text",
        "__META_VENDA__": "null::jsonb",
        "__META_CRIADO__": "null::jsonb",
        "__META_MOVE__": "null::jsonb",
        "__META_DISPARO__": "null::jsonb",
    }
    if esq.p0:
        t["__EXISTE__"] = ("exists (select 1 from public.lead_events e "
                           "where e.dedupe_key = c.dedupe_key)")
        # Entrada gravada AO VIVO pelo trigger perto do clique já conta esse referral.
        t["__SEM_ENTRADA_VIVA__"] = """not exists (
           select 1 from public.lead_events e
            where e.lead_id = r.lead_id and e.event_type = 'entrada'
              and coalesce(e.dedupe_key, '') not like 'entrada:referral:%'
              and e.occurred_at between r.received_at - interval '30 minutes'
                                    and r.received_at + interval '30 minutes')"""
    if esq.p3:
        t.update({
            "__META_REF__": ("(public.fn_lead_entrada_metadata(null, null, r.ctwa_clid, r.source_id, "
                             "null, null, null, 'paid') || jsonb_build_object('origem', 'referral'))"),
            "__META_INI__": META_INI,
            "__CANAL_INI__": f"({META_INI})->>'canal'",
            "__SOURCE_INI__": f"public.fn_lead_entrada_source({META_INI})",
            "__META_VENDA__": "public.fn_lead_events_venda_metadata(s)",
            "__META_CRIADO__": ("public.fn_lead_events_etapa_metadata(d.id, d.pipeline_id, null, "
                                "case when d.mudou then null else d.stage_id end)"),
            "__META_MOVE__": "public.fn_lead_events_etapa_metadata(d.id, d.pipeline_id, null, d.stage_id)",
            "__META_DISPARO__": "public.fn_lead_events_disparo_metadata(bl)",
        })
    return t


def _preencher(texto: str, tokens: dict[str, str]) -> str:
    for chave, valor in tokens.items():
        texto = texto.replace(chave, valor)
    return texto


def montar_sql(esq: Esquema, aplicar: bool) -> str:
    """SQL completo de uma rodada. Dry-run: READ ONLY + rollback. Aplicar: insert + commit."""
    if aplicar and not esq.completo:
        raise ValueError("--aplicar exige as migrações 20261006 (P0) e 20261006b (P3)")
    tokens = _tokens(esq)
    tokens["__CONTAGEM__"] = CONTAGEM
    tokens["__REFERRALS__"] = REFERRALS
    final = FINAL_APLICAR if aplicar else FINAL_DRY
    corpo = _preencher(CTE + _preencher(final, tokens), tokens)
    if aplicar:
        return "begin;\n" + corpo + ";\ncommit;\n"
    return "begin transaction read only;\n" + corpo + ";\nrollback;\n"


def rodar_psql(comando: str) -> Rodar:
    base = shlex.split(comando) + ["-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]

    def rodar(sql: str) -> str:
        r = subprocess.run(base, input=sql, text=True, capture_output=True)
        if r.returncode != 0:
            raise RuntimeError(f"psql falhou ({r.returncode}): {r.stderr.strip()}")
        return r.stdout

    return rodar


def ultimo_json(saida: str):
    linhas = [ln for ln in saida.splitlines() if ln.strip()]
    if not linhas:
        raise ValueError("psql não devolveu nada")
    return json.loads(linhas[-1])


def detectar_esquema(rodar: Rodar) -> Esquema:
    d = ultimo_json(rodar(SQL_ESQUEMA))
    return Esquema(p0=bool(d["p0"]), arquivo=bool(d["arquivo"]), p3=bool(d["p3"]))


def _sim(v: bool) -> str:
    return "sim" if v else "não"


def formatar(res: dict, esq: Esquema, aplicar: bool) -> str:
    fonte = "meta_referrals_arquivo" if esq.arquivo else "meta_webhook_logs"
    linhas = [
        f"Modo: {'APLICAR' if aplicar else 'DRY-RUN (nada gravado)'} | P0: {_sim(esq.p0)} | "
        f"P3: {_sim(esq.p3)} | referrals de {fonte}",
    ]
    if not esq.p3:
        linhas.append("Sem a 20261006b: só contagem (metadata não é montada).")
    if not esq.p0:
        linhas.append("Sem a P0: não há dedupe_key para conferir — 'já existem' sai 0.")
    cab = f"{'tipo':<17}{'candidatos':>11}{'já existem':>12}{'novos':>8}"
    linhas.append(cab + ("  inseridos" if aplicar else ""))
    inseridos = res.get("inseridos") or {}
    total = 0
    for e in res.get("eventos") or []:
        novos = e["candidatos"] - e["existentes"]
        total += novos
        linha = f"{e['event_type']:<17}{e['candidatos']:>11}{e['existentes']:>12}{novos:>8}"
        if aplicar:
            linha += f"{inseridos.get(e['event_type'], 0):>11}"
        linhas.append(linha)
    linhas.append(f"{'total novos':<17}{'':>11}{'':>12}{total:>8}")
    r = res.get("referrals") or {}
    linhas.append(
        f"Referrals: {r.get('total', 0)} | sem lead: {r.get('sem_lead', 0)} | "
        f"ambíguos: {r.get('ambiguos', 0)} | colapsados (mesmo clique em 30 min): "
        f"{r.get('colapsados', 0)} | já cobertos por entrada ao vivo: {r.get('ja_cobertos', 0)}"
    )
    return "\n".join(linhas)


def main(argv: list[str] | None = None, rodar: Rodar | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill da linha do tempo do lead (lead_events).")
    ap.add_argument("--psql", default=os.environ.get("TIMELINE_PSQL", "psql"),
                    help="comando psql (o SQL vai pela entrada padrão)")
    ap.add_argument("--aplicar", action="store_true", help="grava (exige P0 + P3 aplicadas)")
    ap.add_argument("--json", action="store_true", help="imprime o resultado cru em JSON")
    args = ap.parse_args(argv)

    rodar = rodar or rodar_psql(args.psql)
    esq = detectar_esquema(rodar)
    if args.aplicar and not esq.completo:
        print("--aplicar exige as migrações 20261006 (P0) e 20261006b (P3) aplicadas no banco.",
              file=sys.stderr)
        return 2
    res = ultimo_json(rodar(montar_sql(esq, args.aplicar)))
    print(json.dumps(res, ensure_ascii=False) if args.json else formatar(res, esq, args.aplicar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Rodar e ver passar** — `ARQS="tests/test_cs_p3_backfill.py tests/test_cs_p3_timeline_pg.py"`
  no container → PASS; runner do host → todos `ok` (inclusive `test_backfill_idempotente`).

- [ ] **Step 6: Dry-run contra produção (somente leitura)**

```bash
P=$(docker ps -q -f name=supabase_db | head -1)
python3 scripts/timeline/backfill_lead_events.py --psql "docker exec -i $P psql -U postgres -d postgres"
```
Esperado: `DRY-RUN … P0: não | P3: não | referrals de meta_webhook_logs` e a tabela por tipo.
Anotar as contagens no relatório.

- [ ] **Step 7: Commit**

```bash
git add scripts/timeline/backfill_lead_events.py backend/tests/test_cs_p3_backfill.py backend/tests/test_cs_p3_timeline_pg.py
git commit -m "feat(timeline): P3 — backfill idempotente de lead_events (dry-run por padrão)"
```

---

### Task 3: Rota `GET /api/leads/[id]/timeline`

**Files:**
- Create: `frontend/src/app/api/leads/[id]/timeline/route.test.ts`
- Create: `frontend/src/app/api/leads/[id]/timeline/route.ts`
- (os tipos `TimelineEvent`/`TimelineConversou`/`TimelineItem`/`TimelineResponse` nascem no
  componente — Task 4, Step 3 — e a rota os importa com `import type`; por isso o arquivo do
  componente é criado já nesta task com os tipos e um `LeadTimeline` que a Task 4 completa.)

- [ ] **Step 1: Tipos** — criar `frontend/src/components/leads/lead-timeline.tsx` só com os tipos
  exportados da Task 4 Step 3 (bloco "Tipos do payload") e
  `export function LeadTimeline(_: LeadTimelineProps) { return null; }`.

- [ ] **Step 2: Teste da rota (falha: rota não existe)**

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/supabase/pipeline-access", () => ({ getCurrentUser: vi.fn() }));
vi.mock("@/lib/supabase/api", () => ({ getServiceSupabase: vi.fn() }));

import { GET } from "./route";
import { getCurrentUser } from "@/lib/supabase/pipeline-access";
import { getServiceSupabase } from "@/lib/supabase/api";
import type { TimelineConversou, TimelineEvent, TimelineResponse } from "@/components/leads/lead-timeline";

type Result = { data: unknown; error: { message: string } | null };
type Call = { table: string; ops: [string, unknown[]][] };

/**
 * Fake do query builder. Cada tabela devolve um Result fixo, ou uma FILA de Results (um por
 * consulta — a paginação de `messages`). `calls` registra a tabela e os métodos chamados.
 */
function fakeSupabase(tables: Record<string, Result | Result[]>) {
  const calls: Call[] = [];
  return {
    calls,
    from(table: string) {
      const call: Call = { table, ops: [] };
      calls.push(call);
      const entry = tables[table];
      const result: Result = Array.isArray(entry)
        ? (entry.shift() ?? { data: [], error: null })
        : (entry ?? { data: null, error: null });
      const builder: Record<string, unknown> = {};
      for (const m of ["select", "eq", "in", "order", "limit", "range"]) {
        builder[m] = (...args: unknown[]) => {
          call.ops.push([m, args]);
          return builder;
        };
      }
      builder.maybeSingle = async () => result;
      builder.then = (resolve: (r: Result) => unknown, reject?: (e: unknown) => unknown) =>
        Promise.resolve(result).then(resolve, reject);
      return builder;
    },
  };
}

const call = (id = "lead-1") =>
  GET(new Request(`http://localhost/api/leads/${id}/timeline`) as never, { params: Promise.resolve({ id }) });

const LEAD: Result = { data: { id: "lead-1" }, error: null };

const ev = (p: Record<string, unknown>) => ({
  id: "e",
  event_type: "entrada",
  old_value: null,
  new_value: null,
  metadata: {},
  occurred_at: "2026-09-10T12:00:00Z",
  created_at: "2026-09-10T12:00:00Z",
  source: null,
  ...p,
});

const msgs = (...isos: string[]): Result => ({ data: isos.map((created_at) => ({ created_at })), error: null });

async function body(res: Response) {
  return (await res.json()) as TimelineResponse;
}

describe("GET /api/leads/[id]/timeline", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u1", role: "admin", email: "admin@x.com" } as never);
  });

  it("401 sem sessão", async () => {
    vi.mocked(getCurrentUser).mockRejectedValueOnce(new Error("no session"));
    expect((await call()).status).toBe(401);
  });

  it("404 lead inexistente", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({ leads: { data: null, error: null } }) as never,
    );
    expect((await call()).status).toBe(404);
  });

  it("junta eventos e marcadores 'conversou' do mais novo ao mais antigo, no fuso de São Paulo", async () => {
    const sb = fakeSupabase({
      leads: LEAD,
      lead_events: {
        data: [
          ev({ id: "e2", event_type: "etapa", occurred_at: "2026-09-20T12:00:00Z" }),
          ev({ id: "e1", event_type: "entrada", occurred_at: "2026-09-10T12:00:00Z" }),
        ],
        error: null,
      },
      // 16/09 02:00Z = 15/09 23:00 em São Paulo: cai no dia 15.
      messages: [msgs("2026-09-16T02:00:00Z", "2026-09-15T18:00:00Z", "2026-09-15T13:00:00Z")],
    });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);

    const res = await call();
    expect(res.status).toBe(200);
    const { items, partial } = await body(res);
    expect(partial).toEqual([]);
    expect(items.map((i) => i.id)).toEqual(["e2", "conversou:2026-09-15", "e1"]);
    const dia = items[1] as TimelineConversou;
    expect(dia).toEqual({
      kind: "conversou",
      id: "conversou:2026-09-15",
      dia: "2026-09-15",
      at: "2026-09-16T02:00:00.000Z",
      mensagens: 3,
    });
    const evento = items[0] as TimelineEvent;
    expect(evento.kind).toBe("evento");
    expect(evento.at).toBe("2026-09-20T12:00:00Z");

    const evCall = sb.calls.find((c) => c.table === "lead_events")!;
    expect(evCall.ops).toContainEqual(["order", ["occurred_at", { ascending: false }]]);
    const msgCall = sb.calls.find((c) => c.table === "messages")!;
    expect(msgCall.ops).toContainEqual(["eq", ["role", "user"]]);
  });

  it("pagina as mensagens além do teto de 1000 linhas do PostgREST", async () => {
    const cheia = Array.from({ length: 1000 }, () => "2026-09-01T12:00:00Z");
    const sb = fakeSupabase({
      leads: LEAD,
      lead_events: { data: [], error: null },
      messages: [msgs(...cheia), msgs("2026-08-31T12:00:00Z")],
    });
    vi.mocked(getServiceSupabase).mockResolvedValue(sb as never);

    const { items } = await body(await call());
    expect(items.map((i) => [i.id, (i as TimelineConversou).mensagens])).toEqual([
      ["conversou:2026-09-01", 1000],
      ["conversou:2026-08-31", 1],
    ]);
    expect(sb.calls.filter((c) => c.table === "messages")).toHaveLength(2);
  });

  it("vendedor não vê venda de outro vendedor; vê a dele e a importada do Bling", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({ userId: "u2", role: "vendedor", email: "ana@x.com" } as never);
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: {
          data: [
            ev({ id: "v-joao", event_type: "venda", metadata: { sold_by: "joao@x.com", origin: "crm" } }),
            ev({ id: "v-ana", event_type: "venda", metadata: { sold_by: "Ana@x.com", origin: "crm" } }),
            ev({ id: "v-bling", event_type: "venda_cancelada", metadata: { sold_by: null, origin: "bling" } }),
            ev({ id: "ent", event_type: "entrada" }),
          ],
          error: null,
        },
        messages: [msgs()],
      }) as never,
    );
    const { items } = await body(await call());
    expect(items.map((i) => i.id).sort()).toEqual(["ent", "v-ana", "v-bling"]);
  });

  it("admin vê todas as vendas", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: {
          data: [ev({ id: "v-joao", event_type: "venda", metadata: { sold_by: "joao@x.com", origin: "crm" } })],
          error: null,
        },
        messages: [msgs()],
      }) as never,
    );
    const { items } = await body(await call());
    expect(items.map((i) => i.id)).toEqual(["v-joao"]);
  });

  it("falha em lead_events vira partial 'eventos' sem derrubar os marcadores", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: { data: null, error: { message: "column occurred_at does not exist" } },
        messages: [msgs("2026-09-15T13:00:00Z")],
      }) as never,
    );
    const res = await call();
    expect(res.status).toBe(200);
    const { items, partial } = await body(res);
    expect(partial).toEqual(["eventos"]);
    expect(items.map((i) => i.id)).toEqual(["conversou:2026-09-15"]);
  });

  it("falha em messages vira partial 'conversas'", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: { data: [ev({ id: "e1" })], error: null },
        messages: [{ data: null, error: { message: "boom" } }],
      }) as never,
    );
    const { items, partial } = await body(await call());
    expect(partial).toEqual(["conversas"]);
    expect(items.map((i) => i.id)).toEqual(["e1"]);
  });

  it("completa o nome da campanha pelo meta_ad_id quando a entrada não trouxe", async () => {
    vi.mocked(getServiceSupabase).mockResolvedValue(
      fakeSupabase({
        leads: LEAD,
        lead_events: {
          data: [ev({ id: "e1", metadata: { canal: "Meta Ads", meta_ad_id: "ad-9", campanha_nome: null } })],
          error: null,
        },
        meta_ad_campaigns: { data: [{ ad_id: "ad-9", campaign_id: "c-9", campaign_name: "CTWA Atacado" }], error: null },
        messages: [msgs()],
      }) as never,
    );
    const { items } = await body(await call());
    const e = items[0] as TimelineEvent;
    expect(e.metadata.campanha_nome).toBe("CTWA Atacado");
    expect(e.metadata.campanha_id).toBe("c-9");
  });
});
```

- [ ] **Step 3: Rodar e ver falhar** — `cd frontend && flock /root/crm-wt/_heavy.lock npx vitest run "src/app/api/leads/[id]/timeline/route.test.ts"` → FAIL (`Failed to resolve import "./route"`).

- [ ] **Step 4: A rota**

```ts
// Linha do tempo do lead (P3 da call de 01/10): eventos de `lead_events` (gravados pelos
// triggers da migração 20261006b e pelo backfill) + marcadores diários "conversou",
// calculados na leitura a partir das mensagens inbound em `messages`.
//
// Qualquer usuário autenticado: o vendedor abre pela conversa (contact-detail). As vendas
// seguem o MESMO escopo de /api/leads/[id]/sales — o evento traz `sold_by` e `origin` no
// metadata justamente para a rota aplicar `podeVerVenda`.
//
// Seções falham de forma independente e aparecem em `partial` (mesmo contrato da rota
// overview): sem a P0 aplicada, `occurred_at` não existe e "eventos" cai — os dias de
// conversa continuam aparecendo.

import { NextResponse, type NextRequest } from "next/server";
import { getServiceSupabase } from "@/lib/supabase/api";
import { getCurrentUser, type CurrentUser } from "@/lib/supabase/pipeline-access";
import { podeVerVenda, scopeAtivo } from "@/lib/sales/sales-scope";
import type {
  TimelineConversou,
  TimelineEvent,
  TimelineItem,
  TimelineResponse,
} from "@/components/leads/lead-timeline";

/** Uma vida inteira de lead cabe folgado; acima disso a tela já não é lida. */
const MAX_EVENTS = 500;
/** max-rows do PostgREST: páginas maiores voltam cortadas em silêncio. */
const PAGE = 1000;
const MAX_MESSAGE_PAGES = 20;
const TZ = "America/Sao_Paulo";
const TIPOS_VENDA = new Set(["venda", "venda_cancelada"]);

type Row = Record<string, unknown>;
type Sb = Awaited<ReturnType<typeof getServiceSupabase>>;

function str(v: unknown): string | null {
  return typeof v === "string" && v !== "" ? v : null;
}

function obj(v: unknown): Row {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Row) : {};
}

function ts(iso: string): number {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
}

const diaSP = new Intl.DateTimeFormat("en-CA", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function mapEvento(r: Row): TimelineEvent {
  return {
    kind: "evento",
    id: String(r.id),
    event_type: str(r.event_type) ?? "evento",
    at: str(r.occurred_at) ?? str(r.created_at) ?? "",
    source: str(r.source),
    old_value: str(r.old_value),
    new_value: str(r.new_value),
    metadata: obj(r.metadata),
  };
}

/** Um marcador por dia (São Paulo) com mensagem do cliente, posicionado na última do dia. */
function diasConversou(inbound: string[]): TimelineConversou[] {
  const porDia = new Map<string, { ultimo: number; n: number }>();
  for (const iso of inbound) {
    const t = Date.parse(iso);
    if (Number.isNaN(t)) continue;
    const dia = diaSP.format(t);
    const atual = porDia.get(dia);
    if (atual) {
      atual.n += 1;
      atual.ultimo = Math.max(atual.ultimo, t);
    } else {
      porDia.set(dia, { ultimo: t, n: 1 });
    }
  }
  return [...porDia].map(([dia, { ultimo, n }]) => ({
    kind: "conversou",
    id: `conversou:${dia}`,
    dia,
    at: new Date(ultimo).toISOString(),
    mensagens: n,
  }));
}

function vendaVisivel(e: TimelineEvent, user: CurrentUser, escopo: boolean): boolean {
  if (!TIPOS_VENDA.has(e.event_type)) return true;
  try {
    return podeVerVenda(
      { sold_by: str(e.metadata.sold_by), origin: str(e.metadata.origin) },
      { userId: user.userId, email: user.email, role: user.role },
      escopo,
    );
  } catch {
    // e-mail ausente/inválido: na dúvida, esconde (mesma postura do escopo de /painel-vendas)
    return false;
  }
}

async function carregarEventos(sb: Sb, id: string, partial: string[]): Promise<TimelineEvent[]> {
  try {
    const { data, error } = await sb
      .from("lead_events")
      .select("id, event_type, old_value, new_value, metadata, occurred_at, created_at, source")
      .eq("lead_id", id)
      .order("occurred_at", { ascending: false })
      .limit(MAX_EVENTS);
    if (error) throw new Error(error.message);
    return ((data ?? []) as unknown as Row[]).map(mapEvento);
  } catch {
    partial.push("eventos");
    return [];
  }
}

async function carregarInbound(sb: Sb, id: string, partial: string[]): Promise<string[]> {
  const out: string[] = [];
  try {
    for (let pagina = 0; pagina < MAX_MESSAGE_PAGES; pagina++) {
      const { data, error } = await sb
        .from("messages")
        .select("created_at")
        .eq("lead_id", id)
        .eq("role", "user")
        .order("created_at", { ascending: false })
        .range(pagina * PAGE, pagina * PAGE + PAGE - 1);
      if (error) throw new Error(error.message);
      const rows = (data ?? []) as unknown as Row[];
      for (const r of rows) {
        const c = str(r.created_at);
        if (c) out.push(c);
      }
      if (rows.length < PAGE) break;
    }
    return out;
  } catch {
    partial.push("conversas");
    return [];
  }
}

/** Entrada gravada antes do mapa anúncio→campanha sincronizar: completa na leitura. */
async function completarCampanhas(sb: Sb, eventos: TimelineEvent[]): Promise<TimelineEvent[]> {
  const semNome = [
    ...new Set(
      eventos
        .filter((e) => e.event_type === "entrada" && !str(e.metadata.campanha_nome) && str(e.metadata.meta_ad_id))
        .map((e) => String(e.metadata.meta_ad_id)),
    ),
  ];
  if (semNome.length === 0) return eventos;
  try {
    const { data, error } = await sb
      .from("meta_ad_campaigns")
      .select("ad_id, campaign_id, campaign_name")
      .in("ad_id", semNome);
    if (error) return eventos;
    const porAd = new Map(((data ?? []) as unknown as Row[]).map((r) => [String(r.ad_id), r]));
    return eventos.map((e) => {
      const c = e.event_type === "entrada" ? porAd.get(String(e.metadata.meta_ad_id)) : undefined;
      if (!c || !str(c.campaign_name)) return e;
      return {
        ...e,
        metadata: {
          ...e.metadata,
          campanha_id: str(e.metadata.campanha_id) ?? str(c.campaign_id),
          campanha_nome: str(c.campaign_name),
        },
      };
    });
  } catch {
    return eventos;
  }
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  let user: CurrentUser;
  try {
    user = await getCurrentUser();
  } catch {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const { id } = await params;
  const sb = await getServiceSupabase();

  const { data: lead, error: leadError } = await sb.from("leads").select("id").eq("id", id).maybeSingle();
  if (leadError) return NextResponse.json({ error: leadError.message }, { status: 500 });
  if (!lead) return NextResponse.json({ error: "lead_not_found" }, { status: 404 });

  const partial: string[] = [];
  const [eventos, inbound] = await Promise.all([
    carregarEventos(sb, id, partial),
    carregarInbound(sb, id, partial),
  ]);

  const escopo = scopeAtivo();
  const visiveis = await completarCampanhas(
    sb,
    eventos.filter((e) => vendaVisivel(e, user, escopo)),
  );

  const items: TimelineItem[] = [...visiveis, ...diasConversou(inbound)].sort(
    (a, b) => ts(b.at) - ts(a.at),
  );
  const payload: TimelineResponse = { items, partial };
  return NextResponse.json(payload);
}
```

- [ ] **Step 5: Rodar e ver passar** — mesmo comando do Step 3 → PASS (9 testes).

- [ ] **Step 6: Commit**

```bash
git add "frontend/src/app/api/leads/[id]/timeline" frontend/src/components/leads/lead-timeline.tsx
git commit -m "feat(timeline): P3 — rota GET /api/leads/[id]/timeline com dias de conversa"
```

---

### Task 4: Componente `LeadTimeline` e aba no modal

**Files:**
- Create: `frontend/src/components/leads/lead-timeline.test.tsx`
- Modify: `frontend/src/components/leads/lead-timeline.tsx`
- Modify: `frontend/src/components/leads/lead-detail-modal.tsx:1-35,448`

- [ ] **Step 1: Teste do componente (falha: `LeadTimeline` devolve null)**

```tsx
/**
 * @vitest-environment jsdom
 *
 * Sem `@testing-library/jest-dom` (não está nas dependências): asserções com a API crua do
 * DOM/`screen`, mesmo padrão de lead-bling-section.test.tsx.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { LeadTimeline, type TimelineResponse } from "./lead-timeline";

const resposta = (corpo: unknown, ok = true, status = 200) =>
  ({ ok, status, json: async () => corpo }) as Response;

function mockFetch(r: Response) {
  const fn = vi.fn(() => Promise.resolve(r));
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

const EXEMPLO: TimelineResponse = {
  partial: [],
  items: [
    {
      kind: "evento", id: "e4", event_type: "venda_cancelada", at: "2026-09-25T15:00:00Z", source: "crm",
      old_value: null, new_value: "30", metadata: { valor: 30, produto: "Clássico 250g" },
    },
    {
      kind: "evento", id: "e3", event_type: "venda", at: "2026-09-20T15:00:00Z", source: "bling",
      old_value: null, new_value: "60", metadata: { valor: 60, produto: "Kit Degustação", kit: true, origin: "bling" },
    },
    { kind: "conversou", id: "conversou:2026-09-18", dia: "2026-09-18", at: "2026-09-18T20:00:00Z", mensagens: 3 },
    {
      kind: "evento", id: "e2", event_type: "etapa", at: "2026-09-12T12:00:00Z", source: "crm",
      old_value: "Novo", new_value: "Qualificado",
      metadata: { pipeline_nome: "Atacado", de_label: "Novo", para_label: "Qualificado" },
    },
    {
      kind: "evento", id: "e1", event_type: "entrada", at: "2026-09-10T12:00:00Z", source: "ctwa",
      old_value: null, new_value: "Meta Ads", metadata: { canal: "Meta Ads", campanha_nome: "CTWA Atacado", meta_ad_id: "ad-1" },
    },
    {
      kind: "evento", id: "e0", event_type: "entrada", at: "2026-08-01T12:00:00Z", source: "ctwa",
      old_value: null, new_value: "Meta Ads", metadata: { canal: "Meta Ads", meta_ad_id: "ad-2" },
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("LeadTimeline", () => {
  it("busca a rota do lead e desenha os itens na ordem recebida (mais novo primeiro)", async () => {
    const f = mockFetch(resposta(EXEMPLO));
    const { container } = render(<LeadTimeline leadId="lead-1" />);
    await screen.findAllByText("Entrada — Meta Ads");
    expect(f).toHaveBeenCalledWith("/api/leads/lead-1/timeline");
    const tipos = [...container.querySelectorAll("li")].map((li) => li.getAttribute("data-tipo"));
    expect(tipos).toEqual(["venda_cancelada", "venda", "conversou", "etapa", "entrada", "entrada"]);
  });

  it("entrada mostra canal e campanha; sem nome, 'Campanha não identificada'", async () => {
    mockFetch(resposta(EXEMPLO));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("CTWA Atacado")).toBeTruthy();
    expect(screen.getByText("Campanha não identificada")).toBeTruthy();
  });

  it("venda mostra valor, produto e os selos kit e Bling; cancelada aparece", async () => {
    mockFetch(resposta(EXEMPLO));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText(/R\$\s60,00 · Kit Degustação/)).toBeTruthy();
    expect(screen.getByText("kit")).toBeTruthy();
    expect(screen.getByText("Bling")).toBeTruthy();
    expect(screen.getByText("Venda cancelada")).toBeTruthy();
    expect(screen.getByText(/R\$\s30,00 · Clássico 250g/)).toBeTruthy();
  });

  it("marcador 'conversou' mostra o dia e quantas mensagens; etapa mostra funil e de → para", async () => {
    mockFetch(resposta(EXEMPLO));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("Conversou")).toBeTruthy();
    expect(screen.getByText("3 mensagens do cliente")).toBeTruthy();
    expect(screen.getByText("18/09/2026")).toBeTruthy();
    expect(screen.getByText("Etapa — Atacado")).toBeTruthy();
    expect(screen.getByText("Novo → Qualificado")).toBeTruthy();
  });

  it("lista vazia", async () => {
    mockFetch(resposta({ items: [], partial: [] }));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("Nenhum evento registrado ainda.")).toBeTruthy();
  });

  it("erro HTTP mostra mensagem de falha", async () => {
    mockFetch(resposta({ error: "boom" }, false, 500));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText("Não foi possível carregar a linha do tempo.")).toBeTruthy();
  });

  it("seção que falhou aparece como aviso, sem esconder o resto", async () => {
    mockFetch(resposta({ items: EXEMPLO.items.slice(2, 3), partial: ["eventos"] }));
    render(<LeadTimeline leadId="lead-1" />);
    expect(await screen.findByText(/Parte da linha do tempo não carregou: eventos/)).toBeTruthy();
    expect(screen.getByText("Conversou")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Rodar e ver falhar** — `npx vitest run src/components/leads/lead-timeline.test.tsx`
  → FAIL (timeout do `findBy…`).

- [ ] **Step 3: O componente** — `frontend/src/components/leads/lead-timeline.tsx` completo:

```tsx
"use client";

import { useEffect, useState } from "react";
import {
  ArrowRightLeft,
  Ban,
  Circle,
  GitMerge,
  LogIn,
  Megaphone,
  MessageCircle,
  ShoppingBag,
  Target,
  type LucideIcon,
} from "lucide-react";

// ── Tipos do payload de GET /api/leads/[id]/timeline ───────────────────────────────────

/** Linha de `lead_events` como a rota entrega. */
export interface TimelineEvent {
  kind: "evento";
  id: string;
  /** entrada | etapa | venda | venda_cancelada | disparo | mesclagem | atribuicao_manual | (legado) stage_change */
  event_type: string;
  /** occurred_at (quando aconteceu; no backfill ≠ inserção), ISO. */
  at: string;
  source: string | null;
  old_value: string | null;
  new_value: string | null;
  metadata: Record<string, unknown>;
}

/** Marcador diário: o cliente mandou mensagem neste dia (fuso America/Sao_Paulo). */
export interface TimelineConversou {
  kind: "conversou";
  /** `conversou:YYYY-MM-DD` */
  id: string;
  /** YYYY-MM-DD em São Paulo. */
  dia: string;
  /** Última mensagem inbound do dia (ISO) — define a posição na lista. */
  at: string;
  mensagens: number;
}

export type TimelineItem = TimelineEvent | TimelineConversou;

export interface TimelineResponse {
  /** Do mais novo para o mais antigo. */
  items: TimelineItem[];
  /** Seções que falharam: "eventos" | "conversas". */
  partial: string[];
}

export interface LeadTimelineProps {
  leadId: string;
}

// ── Apresentação ───────────────────────────────────────────────────────────────────────

type Linha = {
  icon: LucideIcon;
  cor: string;
  titulo: string;
  detalhe: string | null;
  selos: string[];
};

const TZ = "America/Sao_Paulo";
const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const SECOES: Record<string, string> = { eventos: "eventos", conversas: "dias de conversa" };

function texto(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

function dinheiro(v: unknown): string | null {
  const n = typeof v === "number" ? v : typeof v === "string" && v.trim() !== "" ? Number(v) : NaN;
  return Number.isFinite(n) ? BRL.format(n) : null;
}

function descrever(item: TimelineItem): Linha {
  if (item.kind === "conversou") {
    return {
      icon: MessageCircle,
      cor: "#65b5ff",
      titulo: "Conversou",
      detalhe: item.mensagens === 1 ? "1 mensagem do cliente" : `${item.mensagens} mensagens do cliente`,
      selos: [],
    };
  }
  const m = item.metadata;
  switch (item.event_type) {
    case "entrada": {
      const canal = texto(m.canal) ?? item.new_value ?? "Origem desconhecida";
      const campanha =
        texto(m.campanha_nome) ?? texto(m.utm_campaign) ?? (texto(m.meta_ad_id) ? "Campanha não identificada" : null);
      return { icon: LogIn, cor: "#0bdf50", titulo: `Entrada — ${canal}`, detalhe: campanha, selos: [] };
    }
    case "etapa": {
      const funil = texto(m.pipeline_nome) ?? "Funil";
      const de = texto(m.de_label) ?? item.old_value;
      const para = texto(m.para_label) ?? item.new_value;
      const detalhe = de && para ? `${de} → ${para}` : para ? `Entrou em ${para}` : "Entrou no funil";
      return { icon: ArrowRightLeft, cor: "#7b7b78", titulo: `Etapa — ${funil}`, detalhe, selos: [] };
    }
    case "venda":
    case "venda_cancelada": {
      const cancelada = item.event_type === "venda_cancelada";
      const partes = [dinheiro(m.valor) ?? dinheiro(item.new_value), texto(m.produto)].filter(Boolean);
      const selos: string[] = [];
      if (m.kit === true) selos.push("kit");
      if (m.origin === "bling") selos.push("Bling");
      return {
        icon: cancelada ? Ban : ShoppingBag,
        cor: cancelada ? "#c41c1c" : "#ff5600",
        titulo: cancelada ? "Venda cancelada" : "Venda",
        detalhe: partes.join(" · ") || null,
        selos,
      };
    }
    case "disparo":
      return { icon: Megaphone, cor: "#a855f7", titulo: "Disparo", detalhe: texto(m.broadcast_nome) ?? item.new_value, selos: [] };
    case "mesclagem":
      return { icon: GitMerge, cor: "#7b7b78", titulo: "Lead mesclado", detalhe: item.new_value ?? item.old_value, selos: [] };
    case "atribuicao_manual":
      return {
        icon: Target,
        cor: "#ff5600",
        titulo: "Campanha atribuída manualmente",
        detalhe: texto(m.campanha_nome) ?? item.new_value,
        selos: ["manual"],
      };
    case "stage_change":
      return {
        icon: ArrowRightLeft,
        cor: "#7b7b78",
        titulo: "Etapa",
        detalhe: item.old_value && item.new_value ? `${item.old_value} → ${item.new_value}` : item.new_value,
        selos: [],
      };
    default:
      return { icon: Circle, cor: "#9ca3af", titulo: item.event_type, detalhe: item.new_value, selos: [] };
  }
}

function quando(item: TimelineItem): string {
  if (item.kind === "conversou") {
    const [ano, mes, dia] = item.dia.split("-");
    return `${dia}/${mes}/${ano}`;
  }
  const t = Date.parse(item.at);
  if (Number.isNaN(t)) return "";
  return new Date(t).toLocaleString("pt-BR", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Linha do tempo do lead: entradas (canal/campanha), etapas, vendas (valor e selo "kit"),
 * cancelamentos, disparos, mesclagens, atribuições manuais e os dias em que o cliente
 * conversou. Montada como aba no lead-detail-modal (P3) e no contact-detail (P4).
 */
export function LeadTimeline({ leadId }: LeadTimelineProps) {
  // A resposta guarda o leadId que a pediu: trocar de lead volta ao "carregando" sem
  // setState síncrono no efeito.
  const [res, setRes] = useState<{ leadId: string; data: TimelineResponse | null } | null>(null);

  useEffect(() => {
    let vivo = true;
    fetch(`/api/leads/${leadId}/timeline`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as TimelineResponse;
      })
      .then((data) => {
        if (vivo) setRes({ leadId, data });
      })
      .catch(() => {
        if (vivo) setRes({ leadId, data: null });
      });
    return () => {
      vivo = false;
    };
  }, [leadId]);

  if (!res || res.leadId !== leadId) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Carregando linha do tempo">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 rounded-[4px] bg-[#f0ede8] animate-pulse" />
        ))}
      </div>
    );
  }

  if (!res.data) {
    return <p className="text-[13px] text-[#c41c1c]">Não foi possível carregar a linha do tempo.</p>;
  }

  const { items, partial } = res.data;
  return (
    <div>
      {partial.length > 0 && (
        <p
          role="status"
          className="mb-3 rounded-[4px] border border-[#fde68a] bg-[#fef3c7] px-2 py-1 text-[12px] text-[#b45309]"
        >
          Parte da linha do tempo não carregou: {partial.map((p) => SECOES[p] ?? p).join(", ")}.
        </p>
      )}
      {items.length === 0 ? (
        <p className="py-4 text-center text-[13px] text-[#7b7b78]">Nenhum evento registrado ainda.</p>
      ) : (
        <ol className="relative ml-3 border-l border-[#dedbd6]">
          {items.map((item) => {
            const l = descrever(item);
            const Icon = l.icon;
            return (
              <li
                key={item.id}
                data-tipo={item.kind === "conversou" ? "conversou" : item.event_type}
                className="relative pb-4 pl-6 last:pb-0"
              >
                <span
                  className="absolute -left-3 top-0 flex h-6 w-6 items-center justify-center rounded-full border border-[#dedbd6] bg-white"
                  style={{ color: l.cor }}
                >
                  <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <div className="flex flex-wrap items-center gap-1.5">
                  <p className="text-[13px] font-medium text-[#111111]">{l.titulo}</p>
                  {l.selos.map((s) => (
                    <span
                      key={s}
                      className="inline-flex items-center rounded-[4px] border border-[#ff5600]/20 bg-[#ff5600]/10 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.6px] text-[#ff5600]"
                    >
                      {s}
                    </span>
                  ))}
                </div>
                {l.detalhe && <p className="text-[12px] text-[#7b7b78]">{l.detalhe}</p>}
                <p className="text-[11px] text-[#9ca3af]">{quando(item)}</p>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Rodar e ver passar** — vitest do componente + da rota → PASS.

- [ ] **Step 5: Aba no modal** — em `lead-detail-modal.tsx`:

```tsx
import { LeadTimeline } from "./lead-timeline";
// …
type TabKey = "dados" | "linha_do_tempo" | "funis" | "campanhas" | "tags_notas" | "metricas";

const TABS: { key: TabKey; label: string }[] = [
  { key: "dados", label: "Dados Gerais" },
  { key: "linha_do_tempo", label: "Linha do tempo" },
  { key: "funis", label: "Funis" },
  // … resto igual
];
// … logo antes de `{activeTab === "funis" && …}`:
          {/* TAB: Linha do tempo */}
          {activeTab === "linha_do_tempo" && <LeadTimeline leadId={lead.id} />}
```

- [ ] **Step 6: eslint nos arquivos alterados** — `flock /root/crm-wt/_heavy.lock npx eslint
  src/components/leads/lead-timeline.tsx src/components/leads/lead-timeline.test.tsx
  src/components/leads/lead-detail-modal.tsx "src/app/api/leads/[id]/timeline/route.ts"
  "src/app/api/leads/[id]/timeline/route.test.ts"` → sem erros.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/leads/lead-timeline.tsx frontend/src/components/leads/lead-timeline.test.tsx frontend/src/components/leads/lead-detail-modal.tsx
git commit -m "feat(timeline): P3 — componente LeadTimeline e aba no modal do lead"
```

---

### Task 5: Verificação final (superpowers:verification-before-completion)

- [ ] pytest: `tests/test_cs_p3_timeline_migration.py tests/test_cs_p3_backfill.py tests/test_cs_p3_timeline_pg.py` (container, flock).
- [ ] Postgres real: recriar `p3` do zero (`drop database p3; create database p3 template crm_schema;`), aplicar P0, aplicar 20261006b **duas vezes**, rodar o runner do host.
- [ ] vitest: rota + componente (flock).
- [ ] eslint: os 5 arquivos do frontend (flock).
- [ ] Dry-run do backfill contra produção (só leitura) — contagens no relatório.

## Self-review

- Spec P3.1: entrada (insert/update das 6 colunas) ✔ T1; etapa ✔; venda + kit via sale_items ✔
  (+ trigger em sale_items, desvio justificado na decisão 2); venda_cancelada ✔; disparo ✔;
  dedupe determinística ✔; exception/warning ✔ (testado com erro forçado).
- Spec P3.2: referrals por telefone ✔, entrada inicial ✔, vendas ✔, deals created_at +
  entered_stage_at ✔, disparos ✔, dry-run com contagem ✔, `--aplicar` ✔, idempotente ✔ (T2).
- Spec P3.3: lista do mais novo ao mais antigo ✔, ícone por tipo ✔, canal/campanha ✔, valor +
  "kit" ✔, "conversou" diário calculado na leitura ✔, rota ✔, aba no modal ✔. Assinatura para o
  P4: `export function LeadTimeline({ leadId }: LeadTimelineProps)` com
  `LeadTimelineProps = { leadId: string }`.
- Overview (`api/leads/[id]/overview/route.ts:133`) lê `id, event_type, old_value, new_value,
  created_at` — todos continuam preenchidos (`new_value` = canal/etapa/valor/nome do disparo).

---

## Ajuste pedido na integração (P2 × P3, 06/10)

Update em que **só `meta_ad_id`** muda (ctwa_clid, gclid, fbclid, utm_source, utm_campaign
iguais) **não é entrada nova**: o trigger atualiza `metadata.meta_ad_id` (e `campanha_id`/
`campanha_nome` quando o anúncio resolve em `meta_ad_campaigns`) da `entrada` mais recente do
lead com o **mesmo `ctwa_clid`**; sem essa entrada (ou lead sem ctwa_clid), não faz nada.
Motivo: o webhook grava meta_ad_id depois do ctwa_clid e o `recuperar_meta_ad_id.py` do P2
preenche ~687 leads antigos — sem a regra nasceriam entradas falsas datadas do dia do script.
Coberto por `test_cs_p3_timeline_pg.py::test_so_meta_ad_id_enriquece_sem_criar_entrada` (update
só de meta_ad_id → 0 eventos novos + metadata enriquecida; clid diferente → intocado; lead sem
evento → nada; ctwa_clid novo → 1 entrada) e por
`test_cs_p3_timeline_migration.py::test_so_meta_ad_id_enriquece_a_entrada_do_mesmo_ctwa_clid`.
