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
