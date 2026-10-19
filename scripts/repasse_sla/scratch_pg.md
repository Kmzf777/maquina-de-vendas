# Postgres descartável do cartão 7b143561

Container na VPS (173.249.15.11), sem volume. Tem o schema de produção (`public` + `analytics`, sem dados)
mais a migration `supabase/migrations/20261019_repasse_sla.sql`. A produção (`supabase_db`) só foi lida:
`pg_dump --schema-only` e SELECT em `BEGIN READ ONLY`.

## Subir (já está de pé desde 19/10/2026)

```bash
ssh -i "C:\Users\rafae\.ssh\agente_crm" -o BatchMode=yes root@173.249.15.11
docker run -d --rm --name crm-scratch-pg-7b143561 -e POSTGRES_PASSWORD=scratch supabase/postgres:17.6.1.136
# esperar ~20 s: o init da imagem cria anon/authenticated/service_role/supabase_admin, auth.*, extensions.*
P=$(docker ps -q -f name=supabase_db | head -1)
docker exec $P pg_dump -U postgres --schema-only -n public -n analytics > /tmp/schema_7b143561.sql
S=crm-scratch-pg-7b143561
docker exec -i $S psql -U postgres -h localhost -X -c "create role consulta_ro nologin" \
  -c "create extension if not exists pg_trgm with schema extensions" \
  -c "create extension if not exists unaccent with schema extensions"
docker exec -i $S psql -U postgres -h localhost -X -v ON_ERROR_STOP=0 < /tmp/schema_7b143561.sql > /tmp/restore_7b143561.log 2>&1
```

O restore dá 29 erros que não atrapalham: 16 `must be able to SET ROLE "supabase_admin"` (OWNER TO),
12 `permission denied to change default privileges` e 1 `schema "public" already exists`. As tabelas,
os triggers e as funções (`dashboard_kpis`, `analytics.vw_resposta_closer`) existem.

**Banco:** `postgres`, não `p7`. O pg_cron da imagem fica conectado no `postgres`, então não dá para
clonar esse banco como template, e um banco novo não teria `auth.*`.

## Aplicar a migration (no host Windows, a partir da raiz do worktree)

```bash
ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 \
  'docker exec -i crm-scratch-pg-7b143561 psql -U postgres -h localhost -d postgres -X -v ON_ERROR_STOP=1' \
  < supabase/migrations/20261019_repasse_sla.sql
```

Foi aplicada duas vezes seguidas, sem erro, o que prova a idempotência. Também rodei
`scripts/repasse_sla/rollback_migration.sql`: `dashboard_kpis` voltou com
md5(prosrc)=`21908debccec861b83a809a2b8769757`, o mesmo de produção. Depois reapliquei a migration.

## Rodar os testes SQL

```bash
REPASSE_PSQL='ssh -i C:/Users/rafae/.ssh/agente_crm -o BatchMode=yes root@173.249.15.11 docker exec -i crm-scratch-pg-7b143561 psql -U postgres -h localhost -d postgres' \
  python backend/tests/test_repasse_sla_pg.py
```

Cada cenário roda em `begin … rollback`, com datas de 2030 e ids `7b143561-…`.

## Remover

```bash
ssh -i "C:\Users\rafae\.ssh\agente_crm" -o BatchMode=yes root@173.249.15.11 'docker stop crm-scratch-pg-7b143561; rm -f /tmp/schema_7b143561.sql /tmp/restore_7b143561.log'
```

Com `--rm`, o container some ao parar.

## Ensaio só leitura em produção (Passo 7, 19/10/2026)

A lógica nova (view + SLA) rodou como CTE em `BEGIN READ ONLY … ROLLBACK`, sem criar objetos. O
`first_response_at` foi simulado como a 1ª `seller` sem reação com `created_at >= 1º marcador`.
O vendedor é `leads.assigned_to`, porque ainda não há eventos `repasse`. Horário: `sla_seller_config`
(só o João, 600–960 seg–sex, igual ao padrão). `sla_overrides` está vazia.

| mês | handoffs (novo = leads com 1º repasse) | amostras novo | mediana novo | p95 novo | analytics respondidos | mediana analytics | dashboard_kpis atual: handoffs / amostras |
|---|---|---|---|---|---|---|---|
| 2026-07 | 525 | 390 | 104.0 | 4790.4 | 390 | 103.95 | 526 / 0 |
| 2026-08 | 508 | 356 | 69.0 | 649.5 | 356 | 68.95 | 508 / 0 |
| 2026-09 | 475 | 335 | 24.4 | 356.4 | 335 | 24.4 | 483 / 0 |
| 2026-10 | 208 | 140 | 33.1 | 433.2 | 140 | 33.1 | 212 / 0 |

Outubro: mediana de 33,1 min úteis, tanto na lógica nova quanto em `analytics.vw_resposta_closer`, com
140 amostras. A spec, com dados de 15/10, esperava ≈31. A diferença de 0,05 em jul/ago é só
arredondamento: a nova arredonda cada lead a 0,1 antes do percentil, como a analytics; a coluna da
analytics aqui não foi arredondada. O handoff atual conta marcadores, e um lead com 2 repasses conta 2.
O novo conta leads (D3).

Outras conferências: há 0 mensagens `seller` sem `lead_id` e 0 marcadores sem `lead_id`, então o
trigger por `lead_id` cobre tudo. O `consulta_ro` já tem SELECT em messages, leads, lead_events,
sla_seller_config e sla_overrides, e USAGE em public.
