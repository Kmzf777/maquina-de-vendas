#!/usr/bin/env python3
"""Backfill da jornada (F5, cartão B item 5): entrada inicial para o lead que não tem NENHUMA.

SIMULAÇÃO por padrão (transação READ ONLY + rollback): mostra quantas entradas entrariam e quantos
leads dos últimos N dias (venda ou cadastro) mudam de canal no /trafego — do canal de hoje (antes
da F5) para a última origem depois da F5 + backfill. Só grava com --aplicar, e --aplicar exige a
migração 20261106_f5_jornada aplicada. NÃO rode --aplicar em produção sem o ok do Rafael.

Quem ganha entrada (a mesma que o gatilho grava hoje para um lead novo, datada do cadastro e com a
mesma dedupe 'entrada:lead:<id>:inicial' — rodar 2x não duplica):
  - lead com rastreio nas colunas (click id ou UTM): entrada com o metadata do rastreio;
  - lead inbound sem rastreio que JÁ escreveu: entrada "WhatsApp direto" (sem_rastreio).
Lead manual/importado sem rastreio e lead que nunca escreveu continuam sem entrada (estimados).

Uso (o comando psql recebe -X -q -A -t -v ON_ERROR_STOP=1 e o SQL pela entrada padrão):
  python3 scripts/f5_jornada/backfill_jornada.py --psql "docker exec -i <db> psql -U postgres -d postgres"
  python3 scripts/f5_jornada/backfill_jornada.py --psql "..." --dias 30 --json
  python3 scripts/f5_jornada/backfill_jornada.py --psql "..." --aplicar
A simulação roda também com o consulta_ro (só lê).
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from typing import Callable

Rodar = Callable[[str], str]

SQL_ESQUEMA = """select json_build_object(
  'f5', to_regprocedure('public.fn_lead_canal_entrada(jsonb,text,jsonb)') is not null
        and to_regclass('public.vw_lead_jornada') is not null);"""

# Canais que a F5 criou: antes deles, o /trafego mostrava "Sem rastreio".
CANAIS_NOVOS = ("WhatsApp direto", "Cadastro manual / disparo", "Importado (CSV)", "Cliente antigo",
                "Número antigo / outro número")

CTE = """
with sem_entrada as (
  select l.*
    from public.leads l
   where not exists (select 1 from public.lead_events e
                      where e.lead_id = l.id and e.event_type = 'entrada')
), ctx as (
  select * from public.vw_lead_contexto_canal
), novas as (
  select s.id as lead_id,
         coalesce(s.created_at, now()) as occurred_at,
         case when public.fn_lead_tem_rastreio(s.gclid, s.fbclid, s.ctwa_clid, s.meta_ad_id,
                                               s.utm_source, s.utm_campaign, s.gbraid, s.wbraid)
              then public.fn_lead_entrada_metadata(s.gclid, s.fbclid, s.ctwa_clid, s.meta_ad_id,
                                                   s.utm_source, s.utm_medium, s.utm_campaign,
                                                   s.traffic_type, s.gbraid, s.wbraid)
                   || jsonb_build_object('canal',
                        public.fn_lead_canal(s.gclid, s.fbclid, s.ctwa_clid, s.meta_ad_id,
                                             s.utm_source, s.utm_medium, s.traffic_type,
                                             s.gbraid, s.wbraid, s.origem_cadastro),
                        'backfill', 'f5_jornada')
              else jsonb_build_object('canal', 'WhatsApp direto', 'sem_rastreio', true,
                                      'backfill', 'f5_jornada')
         end as metadata
    from sem_entrada s
    left join ctx c on c.lead_id = s.id
   where public.fn_lead_tem_rastreio(s.gclid, s.fbclid, s.ctwa_clid, s.meta_ad_id,
                                     s.utm_source, s.utm_campaign, s.gbraid, s.wbraid)
      or (coalesce(s.origem_cadastro, 'inbound') = 'inbound' and c.tem_inbound)
), janela as (
  select l.id from public.leads l
   where l.created_at >= now() - make_interval(days => __DIAS__)
  union
  select s.lead_id from public.sales s
   where s.sold_at >= now() - make_interval(days => __DIAS__)
     and coalesce(lower(btrim(s.status)), '') not like 'cancel%'
), comparacao as (
  select j.id as lead_id,
         -- canal de hoje (antes da F5): os canais novos eram "Sem rastreio"
         case when x.canal_colunas = any (array[__CANAIS_NOVOS__]) then 'Sem rastreio'
              else x.canal_colunas end as de,
         -- depois: a última origem da jornada; quem ganha entrada no backfill passa a ter toque
         case when n.lead_id is not null
              then public.fn_lead_canal_contexto(public.fn_lead_canal_entrada(n.metadata, null),
                                                 c.cliente_antigo, c.numero_antigo, null, l.channel)
              else vj.ultima_origem end as para
    from janela j
    join public.leads l on l.id = j.id
    left join public.vw_lead_jornada vj on vj.lead_id = l.id
    left join novas n on n.lead_id = l.id
    left join ctx c on c.lead_id = l.id
    cross join lateral (select public.fn_lead_canal(l.gclid, l.fbclid, l.ctwa_clid, l.meta_ad_id,
                                                    l.utm_source, l.utm_medium, l.traffic_type,
                                                    l.gbraid, l.wbraid, l.origem_cadastro)
                               as canal_colunas) x
)"""

RESUMO = """
select json_build_object(
  'entradas_novas', (select count(*) from novas),
  'entradas_por_canal', (select coalesce(json_object_agg(canal, n), '{}'::json) from (
      select metadata->>'canal' as canal, count(*) as n from novas group by 1) t),
  'leads_janela', (select count(*) from comparacao),
  'mudam', (select count(*) from comparacao where de is distinct from para),
  'transicoes', (select coalesce(json_agg(t order by t.n desc), '[]'::json) from (
      select de, para, count(*) as n from comparacao where de is distinct from para
       group by de, para) t),
  'sem_rastreio_antes', (select count(*) from comparacao where de = 'Sem rastreio'),
  'sem_rastreio_depois', (select count(*) from comparacao where para = 'Sem rastreio'),
  'gravadas', __GRAVADAS__)"""

INSERT = """, gravadas as (
  insert into public.lead_events (lead_id, event_type, new_value, metadata, occurred_at, source, dedupe_key)
  select n.lead_id, 'entrada', n.metadata->>'canal', n.metadata, n.occurred_at,
         case when n.metadata->>'sem_rastreio' = 'true' then 'inbound'
              else public.fn_lead_entrada_source(n.metadata) end,
         'entrada:lead:' || n.lead_id || ':inicial'
    from novas n
  on conflict (dedupe_key) where dedupe_key is not null do nothing
  returning 1
)"""


def montar_sql(dias: int, aplicar: bool) -> str:
    if not isinstance(dias, int) or dias <= 0:
        raise ValueError("--dias tem que ser inteiro positivo")
    canais = ", ".join("'" + c.replace("'", "''") + "'" for c in CANAIS_NOVOS)
    cte = CTE.replace("__DIAS__", str(dias)).replace("__CANAIS_NOVOS__", canais)
    if aplicar:
        corpo = cte + INSERT + RESUMO.replace("__GRAVADAS__", "(select count(*) from gravadas)")
        return "begin;\n" + corpo + ";\ncommit;\n"
    corpo = cte + RESUMO.replace("__GRAVADAS__", "0")
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


def formatar(res: dict, dias: int, aplicar: bool) -> str:
    linhas = [
        f"{'APLICADO' if aplicar else 'SIMULAÇÃO (nada gravado)'} — backfill da jornada (F5)",
        f"Entradas novas: {res['entradas_novas']}"
        + (f" (gravadas: {res['gravadas']})" if aplicar else ""),
    ]
    for canal, n in sorted((res.get("entradas_por_canal") or {}).items(), key=lambda kv: -kv[1]):
        linhas.append(f"  {canal}: {n}")
    linhas += [
        f"Leads dos últimos {dias} dias (cadastro ou venda): {res['leads_janela']}",
        f"Mudam de canal no /trafego (última origem): {res['mudam']}",
        f"Sem rastreio: {res['sem_rastreio_antes']} antes -> {res['sem_rastreio_depois']} depois",
    ]
    for t in res.get("transicoes") or []:
        linhas.append(f"  {t['de']} -> {t['para']}: {t['n']}")
    return "\n".join(linhas)


def main(argv: list[str] | None = None, rodar: Rodar | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backfill da jornada do lead (F5). Simulação por padrão.")
    ap.add_argument("--psql", default=os.environ.get("TIMELINE_PSQL", "psql"))
    ap.add_argument("--dias", type=int, default=30, help="janela da comparação do /trafego (padrão 30)")
    ap.add_argument("--aplicar", action="store_true", help="grava (exige a migração 20261106 aplicada)")
    ap.add_argument("--json", action="store_true", help="imprime o resultado cru em JSON")
    a = ap.parse_args(argv)
    rodar = rodar or rodar_psql(a.psql)
    if not ultimo_json(rodar(SQL_ESQUEMA)).get("f5"):
        print("A migração 20261106_f5_jornada não está aplicada: a simulação depende das funções e views dela.",
              file=sys.stderr)
        return 2
    res = ultimo_json(rodar(montar_sql(a.dias, a.aplicar)))
    print(json.dumps(res, ensure_ascii=False) if a.json else formatar(res, a.dias, a.aplicar))
    return 0


if __name__ == "__main__":
    sys.exit(main())
