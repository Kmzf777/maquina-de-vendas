-- =============================================================================
-- /estatisticas — agrega custo de IA e WhatsApp NO POSTGRES (fim do truncamento).
--
-- Contexto (spec 2026-07-11-fix-estatisticas-llm.md): as rotas /api/stats/* faziam
-- a agregação NO CLIENTE — buscavam linhas cruas de token_usage/meta_webhook_logs
-- com .limit(10000) e somavam com reduce no Node. O PostgREST tem um teto de servidor
-- (max-rows = 1000) que se sobrepõe a qualquer .limit maior, e as queries não tinham
-- .order(), então "7 dias" somava só as 1000 linhas mais ANTIGAS da janela (ordem
-- física da heap). Prova em prod (11/07): 7d real = 2.156 calls / 12.591.462 tok /
-- $4,1303 vs rota truncada = 1000 / 3.108.729 / $0,8743. Como "Hoje" (194 linhas) não
-- batia no teto, o dashboard mostrava "Hoje" > "7 dias" (impossível).
--
-- Estas 6 funções empurram SUM/COUNT/COUNT(DISTINCT)/GROUP BY para o banco: 1 request
-- por card, exatidão garantida pelo Postgres, imune ao crescimento de volume. Semântica
-- espelha byte-a-byte o JS atual (ver contrato stats-rpc-contract.md) — o gap-fill de
-- dias zerados, os preços de WhatsApp e os arredondamentos CONTINUAM na rota (Trilha B).
--
-- Todas: STABLE, SECURITY INVOKER (rotas chamam via service_role, que bypassa RLS),
-- EXECUTE revogado de PUBLIC/anon/authenticated e concedido só a service_role.
-- SET search_path = public fixa o resolver (evita o lint function_search_path_mutable
-- do advisor e a armadilha de search_path mutável em função).
--
-- Datas: as rotas passam 'YYYY-MM-DD'; os params são timestamptz (coerção → meia-noite
-- UTC, MESMA semântica dos gte/lt atuais). Janela sempre [p_start, p_end).
--
-- Ativação exige recarregar o cache do PostgREST (NOTIFY no fim — senão PGRST202).
--
-- Rollback:
--   drop function if exists public.stats_costs_summary(timestamptz, timestamptz, text, text, uuid);
--   drop function if exists public.stats_costs_daily(timestamptz, timestamptz, text, text);
--   drop function if exists public.stats_costs_breakdown(timestamptz, timestamptz, text);
--   drop function if exists public.stats_costs_top_leads(timestamptz, timestamptz, int);
--   drop function if exists public.stats_whatsapp_summary(timestamptz, timestamptz);
--   drop function if exists public.stats_whatsapp_daily(timestamptz, timestamptz);
-- =============================================================================

-- 1) Cards de custo/tokens/chamadas (o bug reportado). Filtros opcionais NULL-áveis.
create or replace function public.stats_costs_summary(
  p_start   timestamptz,
  p_end     timestamptz,
  p_stage   text default null,
  p_model   text default null,
  p_lead_id uuid default null
)
returns table (
  total_cost              numeric,
  total_calls             bigint,
  total_prompt_tokens     bigint,
  total_completion_tokens bigint,
  unique_leads            bigint
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    coalesce(sum(t.total_cost), 0)::numeric                                     as total_cost,
    count(*)                                                                    as total_calls,
    coalesce(sum(t.prompt_tokens), 0)::bigint                                   as total_prompt_tokens,
    coalesce(sum(t.completion_tokens), 0)::bigint                               as total_completion_tokens,
    count(distinct t.lead_id) filter (where t.lead_id is not null)              as unique_leads
  from public.token_usage t
  where t.created_at >= p_start
    and t.created_at <  p_end
    and (p_stage   is null or t.stage   = p_stage)
    and (p_model   is null or t.model   = p_model)
    and (p_lead_id is null or t.lead_id = p_lead_id)
$$;

-- 2) Gráfico diário de IA. GROUP BY dia-UTC (== created_at.slice(0,10) do JS).
--    Só dias com dados — o gap-fill (dias zerados) CONTINUA na rota.
create or replace function public.stats_costs_daily(
  p_start timestamptz,
  p_end   timestamptz,
  p_stage text default null,
  p_model text default null
)
returns table (
  day  date,
  cost numeric
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    (t.created_at at time zone 'UTC')::date        as day,
    coalesce(sum(t.total_cost), 0)::numeric        as cost
  from public.token_usage t
  where t.created_at >= p_start
    and t.created_at <  p_end
    and (p_stage is null or t.stage = p_stage)
    and (p_model is null or t.model = p_model)
  group by (t.created_at at time zone 'UTC')::date
$$;

-- 3) Quebra por stage/model/lead. Chave espelha o JS: lead -> COALESCE(id,'unknown');
--    stage/model -> COALESCE(col,'null') (chave de objeto com valor null vira "null").
create or replace function public.stats_costs_breakdown(
  p_start    timestamptz,
  p_end      timestamptz,
  p_group_by text
)
returns table (
  key    text,
  cost   numeric,
  calls  bigint,
  tokens bigint
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    case p_group_by
      when 'lead'  then coalesce(t.lead_id::text, 'unknown')
      when 'stage' then coalesce(t.stage::text,   'null')
      when 'model' then coalesce(t.model::text,   'null')
    end                                                          as key,
    coalesce(sum(t.total_cost), 0)::numeric                     as cost,
    count(*)                                                    as calls,
    coalesce(sum(t.prompt_tokens + t.completion_tokens), 0)::bigint as tokens
  from public.token_usage t
  where t.created_at >= p_start
    and t.created_at <  p_end
  group by 1
  order by cost desc
$$;

-- 4) Ranking de leads por custo. Exclui lead_id NULL; stage = o da linha mais RECENTE
--    do lead na janela (determinístico por created_at — mudança semântica documentada
--    vs. a "última física" indeterminística do JS). O join com leads (nome/telefone)
--    CONTINUA na rota.
create or replace function public.stats_costs_top_leads(
  p_start timestamptz,
  p_end   timestamptz,
  p_limit int default 20
)
returns table (
  lead_id uuid,
  cost    numeric,
  calls   bigint,
  tokens  bigint,
  stage   text
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    t.lead_id,
    coalesce(sum(t.total_cost), 0)::numeric                         as cost,
    count(*)                                                        as calls,
    coalesce(sum(t.prompt_tokens + t.completion_tokens), 0)::bigint as tokens,
    (array_agg(t.stage order by t.created_at desc))[1]             as stage
  from public.token_usage t
  where t.created_at >= p_start
    and t.created_at <  p_end
    and t.lead_id is not null
  group by t.lead_id
  order by cost desc
  limit p_limit
$$;

-- 5) Cards de WhatsApp. Categoria via LEFT JOIN com message_templates DEDUPLICADA por
--    name (DISTINCT ON — sem ele, nomes duplicados fariam fan-out e dobrariam a
--    contagem; o JS não dobra pois mapeia por nome). UPPER(TRIM(category))='UTILITY'
--    conta utility; TODO o resto (inclusive sem match/sem nome) conta marketing —
--    mesmo default do JS. Preços/arredondamentos CONTINUAM na rota.
create or replace function public.stats_whatsapp_summary(
  p_start timestamptz,
  p_end   timestamptz
)
returns table (
  marketing_count bigint,
  utility_count   bigint
)
language sql
stable
security invoker
set search_path = public
as $$
  with tpl as (
    select distinct on (name) name, category
    from public.message_templates
    order by name
  )
  select
    count(*) filter (where upper(trim(tpl.category)) is distinct from 'UTILITY') as marketing_count,
    count(*) filter (where upper(trim(tpl.category)) = 'UTILITY')                as utility_count
  from public.meta_webhook_logs l
  left join tpl on tpl.name = l.payload->'template'->>'name'
  where l.direction    = 'outbound'
    and l.request_type = 'send_template'
    and l.success      = true
    and l.received_at >= p_start
    and l.received_at <  p_end
$$;

-- 6) Gráfico diário de WhatsApp. Mesma lógica da 5, GROUP BY dia-UTC. Gap-fill/preços
--    continuam na rota.
create or replace function public.stats_whatsapp_daily(
  p_start timestamptz,
  p_end   timestamptz
)
returns table (
  day             date,
  marketing_count bigint,
  utility_count   bigint
)
language sql
stable
security invoker
set search_path = public
as $$
  with tpl as (
    select distinct on (name) name, category
    from public.message_templates
    order by name
  )
  select
    (l.received_at at time zone 'UTC')::date                                    as day,
    count(*) filter (where upper(trim(tpl.category)) is distinct from 'UTILITY') as marketing_count,
    count(*) filter (where upper(trim(tpl.category)) = 'UTILITY')                as utility_count
  from public.meta_webhook_logs l
  left join tpl on tpl.name = l.payload->'template'->>'name'
  where l.direction    = 'outbound'
    and l.request_type = 'send_template'
    and l.success      = true
    and l.received_at >= p_start
    and l.received_at <  p_end
  group by (l.received_at at time zone 'UTC')::date
$$;

-- EXECUTE restrito: nenhuma dessas funções deve ser chamável por anon/authenticated
-- (as rotas usam service_role). REVOKE de PUBLIC remove o grant default; anon/
-- authenticated são explícitos por segurança em profundidade.
revoke execute on function public.stats_costs_summary(timestamptz, timestamptz, text, text, uuid) from public, anon, authenticated;
revoke execute on function public.stats_costs_daily(timestamptz, timestamptz, text, text)          from public, anon, authenticated;
revoke execute on function public.stats_costs_breakdown(timestamptz, timestamptz, text)             from public, anon, authenticated;
revoke execute on function public.stats_costs_top_leads(timestamptz, timestamptz, int)              from public, anon, authenticated;
revoke execute on function public.stats_whatsapp_summary(timestamptz, timestamptz)                  from public, anon, authenticated;
revoke execute on function public.stats_whatsapp_daily(timestamptz, timestamptz)                    from public, anon, authenticated;

grant execute on function public.stats_costs_summary(timestamptz, timestamptz, text, text, uuid) to service_role;
grant execute on function public.stats_costs_daily(timestamptz, timestamptz, text, text)          to service_role;
grant execute on function public.stats_costs_breakdown(timestamptz, timestamptz, text)             to service_role;
grant execute on function public.stats_costs_top_leads(timestamptz, timestamptz, int)              to service_role;
grant execute on function public.stats_whatsapp_summary(timestamptz, timestamptz)                  to service_role;
grant execute on function public.stats_whatsapp_daily(timestamptz, timestamptz)                    to service_role;

-- PostgREST só expõe as funções novas após recarregar o schema cache (senão PGRST202).
notify pgrst, 'reload schema';
