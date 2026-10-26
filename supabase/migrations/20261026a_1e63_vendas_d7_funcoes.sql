-- supabase/migrations/20261026a_1e63_vendas_d7_funcoes.sql
--
-- Cartão 1e6381fe — spec docs/superpowers/specs/2026-10-26-vendas-receita-d7-design.md, 3.4 (D7).
--
--   1. get_avg_repurchase_cycle_days: só vendas não canceladas; intervalo = diferença entre os dias
--      de calendário de Brasília de vendas consecutivas do lead, ignorando intervalo de 0 dia (duas
--      vendas no mesmo dia). Mesma assinatura e mesmo lower() do vendedor.
--   2. get_leads_for_repurchase: venda cancelada fora do EXISTS e do MAX(sold_at).
--   3. get_leads_no_sale_in_stage: venda cancelada não conta como venda.
--   4. search_sales: devolve também status e freight (no fim, as colunas atuais continuam). O retorno
--      é RETURNS TABLE, então é DROP + CREATE na mesma transação, com os grants de produção refeitos
--      (em 26/10: EXECUTE só para postgres, dono, e service_role; SECURITY DEFINER, search_path=public).
--
-- Base: pg_get_functiondef de produção em 26/10, idêntica às migrations 20260824_repurchase_por_vendedor,
-- 20260904_esteiras_vendedor e 20260818_universal_search.
--
-- NÃO É APLICADA PELO DEPLOY. Aplicar à mão no supabase_db (psql -U postgres; as funções são de
-- postgres). Reexecutar é seguro. Depois: SIGUSR1 no PostgREST (o NOTIFY é ignorado nesta VPS).
--
-- ═══════════════════════════════ ROLLBACK ═══════════════════════════════════════════
-- Definições de produção em 26/10/2026 (pg_get_functiondef). Para voltar, rodar este bloco:
--
-- begin;
-- set local lock_timeout = '5s';
-- CREATE OR REPLACE FUNCTION public.get_avg_repurchase_cycle_days(p_sold_by text DEFAULT NULL::text)
--  RETURNS numeric
--  LANGUAGE sql
--  STABLE
-- AS $function$
--   WITH filtradas AS (
--     SELECT lead_id, sold_at
--       FROM sales
--      -- `lower()` dos dois lados pela mesma razao do escopo por vendedor: o seed
--      -- grava "Comercial2@..." com maiuscula, e comparacao exata casaria zero.
--      WHERE p_sold_by IS NULL OR lower(sold_by) = lower(p_sold_by)
--   ),
--   ordered AS (
--     SELECT
--       lead_id,
--       sold_at,
--       LAG(sold_at) OVER (PARTITION BY lead_id ORDER BY sold_at) AS prev_sold_at
--     FROM filtradas
--   ),
--   intervals AS (
--     SELECT EXTRACT(EPOCH FROM (sold_at - prev_sold_at)) / 86400.0 AS days
--     FROM ordered
--     WHERE prev_sold_at IS NOT NULL
--   )
--   SELECT ROUND(AVG(days)) FROM intervals;
-- $function$;
--
-- CREATE OR REPLACE FUNCTION public.get_leads_for_repurchase(cutoff_date timestamp with time zone, p_env_tag text, p_audience text DEFAULT 'ia'::text)
--  RETURNS TABLE(id uuid, phone text)
--  LANGUAGE sql
-- AS $function$
--   SELECT l.id, l.phone
--   FROM leads l
--   WHERE (
--     p_audience = 'ambos'
--     OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
--     OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
--   )
--   AND EXISTS (SELECT 1 FROM sales s WHERE s.lead_id = l.id)
--   AND (
--     SELECT MAX(s2.sold_at) FROM sales s2 WHERE s2.lead_id = l.id
--   ) <= cutoff_date;
-- $function$;
--
-- CREATE OR REPLACE FUNCTION public.get_leads_no_sale_in_stage(p_stage text, cutoff_date timestamp with time zone, p_env_tag text, p_audience text DEFAULT 'ia'::text)
--  RETURNS TABLE(id uuid, phone text)
--  LANGUAGE sql
-- AS $function$
--   SELECT l.id, l.phone
--   FROM leads l
--   WHERE l.stage = p_stage
--     AND (
--       p_audience = 'ambos'
--       OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
--       OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
--     )
--     AND l.entered_stage_at IS NOT NULL
--     AND l.entered_stage_at <= cutoff_date
--     AND NOT EXISTS (
--       SELECT 1 FROM sales s WHERE s.lead_id = l.id
--     );
-- $function$;
--
-- DROP FUNCTION IF EXISTS public.search_sales(text, timestamptz, timestamptz, int, int);
-- CREATE FUNCTION public.search_sales(search_query text, p_sold_after timestamp with time zone DEFAULT NULL::timestamp with time zone, p_sold_before timestamp with time zone DEFAULT NULL::timestamp with time zone, max_results integer DEFAULT 20, p_offset integer DEFAULT 0)
--  RETURNS TABLE(id uuid, product text, value numeric, sold_at timestamp with time zone, notes text, lead_id uuid, lead_name text, lead_phone text, deal_id uuid, deal_title text, total_count bigint)
--  LANGUAGE sql
--  STABLE SECURITY DEFINER
--  SET search_path TO 'public'
-- AS $function$
--   WITH matches AS (
--     SELECT s.*
--     FROM sales s
--     JOIN leads l ON l.id = s.lead_id
--     WHERE (
--       f_unaccent(lower(coalesce(s.product, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
--       OR f_unaccent(lower(coalesce(s.notes, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
--       OR f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
--       OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
--       OR (
--         regexp_replace(search_query, '\D', '', 'g') <> ''
--         AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
--       )
--     )
--     AND (p_sold_after IS NULL OR s.sold_at >= p_sold_after)
--     AND (p_sold_before IS NULL OR s.sold_at <= p_sold_before)
--   )
--   SELECT
--     m.id, m.product, m.value, m.sold_at, m.notes,
--     m.lead_id, l.name AS lead_name, l.phone AS lead_phone,
--     m.deal_id, d.title AS deal_title,
--     COUNT(*) OVER() AS total_count
--   FROM matches m
--   JOIN leads l ON l.id = m.lead_id
--   LEFT JOIN deals d ON d.id = m.deal_id
--   ORDER BY m.sold_at DESC
--   LIMIT GREATEST(max_results, 1)
--   OFFSET GREATEST(p_offset, 0);
-- $function$;
-- REVOKE EXECUTE ON FUNCTION public.search_sales(text, timestamptz, timestamptz, int, int) FROM PUBLIC, anon, authenticated;
-- GRANT  EXECUTE ON FUNCTION public.search_sales(text, timestamptz, timestamptz, int, int) TO service_role;
-- commit;
-- ═════════════════════════════ FIM DO ROLLBACK ══════════════════════════════════════

begin;
set local lock_timeout = '5s';

-- ── 1. get_avg_repurchase_cycle_days ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_avg_repurchase_cycle_days(p_sold_by text DEFAULT NULL::text)
 RETURNS numeric
 LANGUAGE sql
 STABLE
AS $function$
  WITH filtradas AS (
    SELECT lead_id, sold_at,
           (sold_at AT TIME ZONE 'America/Sao_Paulo')::date AS dia
      FROM sales
     -- D7: venda cancelada não é compra.
     WHERE coalesce(status, '') <> 'cancelada'
       -- `lower()` dos dois lados pela mesma razao do escopo por vendedor: o seed
       -- grava "Comercial2@..." com maiuscula, e comparacao exata casaria zero.
       AND (p_sold_by IS NULL OR lower(sold_by) = lower(p_sold_by))
  ),
  ordered AS (
    SELECT
      lead_id,
      dia,
      LAG(dia) OVER (PARTITION BY lead_id ORDER BY sold_at) AS prev_dia
    FROM filtradas
  ),
  intervals AS (
    -- Dias de calendário de Brasília; duas vendas no mesmo dia não são uma recompra.
    SELECT (dia - prev_dia) AS days
    FROM ordered
    WHERE prev_dia IS NOT NULL
      AND dia - prev_dia > 0
  )
  SELECT ROUND(AVG(days)) FROM intervals;
$function$;

-- ── 2. get_leads_for_repurchase ─────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_leads_for_repurchase(cutoff_date timestamp with time zone, p_env_tag text, p_audience text DEFAULT 'ia'::text)
 RETURNS TABLE(id uuid, phone text)
 LANGUAGE sql
AS $function$
  SELECT l.id, l.phone
  FROM leads l
  WHERE (
    p_audience = 'ambos'
    OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
    OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
  )
  -- D7: venda cancelada não conta como compra (nem no EXISTS nem na data da última).
  AND EXISTS (
    SELECT 1 FROM sales s
     WHERE s.lead_id = l.id AND coalesce(s.status, '') <> 'cancelada'
  )
  AND (
    SELECT MAX(s2.sold_at) FROM sales s2
     WHERE s2.lead_id = l.id AND coalesce(s2.status, '') <> 'cancelada'
  ) <= cutoff_date;
$function$;

-- ── 3. get_leads_no_sale_in_stage ───────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_leads_no_sale_in_stage(p_stage text, cutoff_date timestamp with time zone, p_env_tag text, p_audience text DEFAULT 'ia'::text)
 RETURNS TABLE(id uuid, phone text)
 LANGUAGE sql
AS $function$
  SELECT l.id, l.phone
  FROM leads l
  WHERE l.stage = p_stage
    AND (
      p_audience = 'ambos'
      OR (p_audience = 'ia'     AND l.ai_enabled = TRUE)
      OR (p_audience = 'humano' AND l.ai_enabled = FALSE)
    )
    AND l.entered_stage_at IS NOT NULL
    AND l.entered_stage_at <= cutoff_date
    -- D7: lead só com venda cancelada continua "sem venda".
    AND NOT EXISTS (
      SELECT 1 FROM sales s
       WHERE s.lead_id = l.id AND coalesce(s.status, '') <> 'cancelada'
    );
$function$;

-- ── 4. search_sales (+ status, freight) ─────────────────────────────────────────────
-- RETURNS TABLE muda: CREATE OR REPLACE não aceita, então DROP + CREATE (mesma transação).
DROP FUNCTION IF EXISTS public.search_sales(text, timestamptz, timestamptz, int, int);

CREATE FUNCTION public.search_sales(search_query text, p_sold_after timestamp with time zone DEFAULT NULL::timestamp with time zone, p_sold_before timestamp with time zone DEFAULT NULL::timestamp with time zone, max_results integer DEFAULT 20, p_offset integer DEFAULT 0)
 RETURNS TABLE(id uuid, product text, value numeric, sold_at timestamp with time zone, notes text, lead_id uuid, lead_name text, lead_phone text, deal_id uuid, deal_title text, total_count bigint, status text, freight numeric)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  WITH matches AS (
    SELECT s.*
    FROM sales s
    JOIN leads l ON l.id = s.lead_id
    WHERE (
      f_unaccent(lower(coalesce(s.product, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(s.notes, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR (
        regexp_replace(search_query, '\D', '', 'g') <> ''
        AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
      )
    )
    AND (p_sold_after IS NULL OR s.sold_at >= p_sold_after)
    AND (p_sold_before IS NULL OR s.sold_at <= p_sold_before)
  )
  SELECT
    m.id, m.product, m.value, m.sold_at, m.notes,
    m.lead_id, l.name AS lead_name, l.phone AS lead_phone,
    m.deal_id, d.title AS deal_title,
    COUNT(*) OVER() AS total_count,
    m.status, m.freight
  FROM matches m
  JOIN leads l ON l.id = m.lead_id
  LEFT JOIN deals d ON d.id = m.deal_id
  ORDER BY m.sold_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$function$;

-- Grants de produção em 26/10: {postgres=X/postgres,service_role=X/postgres}. CREATE FUNCTION
-- concede EXECUTE a PUBLIC (e os default privileges do Supabase a anon/authenticated): tirar.
REVOKE EXECUTE ON FUNCTION public.search_sales(text, timestamptz, timestamptz, int, int)
  FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.search_sales(text, timestamptz, timestamptz, int, int)
  TO service_role;

commit;

NOTIFY pgrst, 'reload schema';
