-- supabase/migrations/20261022g_search_leads_segmento.sql
--
-- Cartão b67f1c6b — spec docs/superpowers/specs/2026-10-22-crm-leads-vendedor-design.md (B9).
--
-- search_leads (busca universal, frontend/src/app/api/search/route.ts) filtrava p_stage
-- contra leads.stage. Com o segmento separado da fase (migration 20261022b), o filtro passa a:
--   * p_stage segmento (atacado/private_label/consumo/exportacao) -> leads.segmento; se o
--     segmento ainda é NULL (lead não migrado pelo F2), cai no stage antigo;
--   * p_stage 'triagem' ou 'secretaria' -> stage in ('triagem','secretaria');
--   * qualquer outra fase -> leads.stage, como antes.
-- Mesma assinatura e mesma saída da versão vigente em produção (lida por
-- pg_get_functiondef em 22/10/2026). CREATE OR REPLACE preserva os grants (service_role).
-- Reexecutar é seguro.
-- Desfazer: reaplicar a definição de 20260818_universal_search.sql.

begin;
set local lock_timeout = '5s';

CREATE OR REPLACE FUNCTION public.search_leads(search_query text, p_stage text DEFAULT NULL::text, p_created_after timestamp with time zone DEFAULT NULL::timestamp with time zone, p_created_before timestamp with time zone DEFAULT NULL::timestamp with time zone, max_results integer DEFAULT 20, p_offset integer DEFAULT 0)
 RETURNS TABLE(id uuid, name text, company text, phone text, status text, stage text, nome_fantasia text, cnpj text, created_at timestamp with time zone, total_count bigint)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  WITH matches AS (
    SELECT l.*
    FROM leads l
    WHERE (
      f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.razao_social, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.nome_fantasia, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR (
        regexp_replace(search_query, '\D', '', 'g') <> ''
        AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
      )
    )
    AND (
      p_stage IS NULL
      OR (
        p_stage IN ('atacado', 'private_label', 'consumo', 'exportacao')
        AND (l.segmento = p_stage OR (l.segmento IS NULL AND l.stage = p_stage))
      )
      OR (p_stage IN ('triagem', 'secretaria') AND l.stage IN ('triagem', 'secretaria'))
      OR (
        p_stage NOT IN ('atacado', 'private_label', 'consumo', 'exportacao', 'triagem', 'secretaria')
        AND l.stage = p_stage
      )
    )
    AND (p_created_after IS NULL OR l.created_at >= p_created_after)
    AND (p_created_before IS NULL OR l.created_at <= p_created_before)
  )
  SELECT
    m.id, m.name, m.company, m.phone, m.status, m.stage, m.nome_fantasia, m.cnpj, m.created_at,
    COUNT(*) OVER() AS total_count
  FROM matches m
  ORDER BY m.created_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$function$;

commit;
