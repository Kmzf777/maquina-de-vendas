-- Busca universal (/busca): 3 RPCs novas (leads, deals, sales) seguindo o
-- mesmo padrão de unaccent+trigram de 20260812_search_all_messages.sql, mais
-- uma extensão não-destrutiva de search_customer_messages (docs_only + paginação
-- + lead_id, necessário para o deep-link /conversas?lead_id=).
--
-- As 4 funções ficam executáveis SOMENTE por service_role (ver bloco de grants
-- de cada uma). Todos os chamadores são rotas /api/* do Next que usam
-- getServiceSupabase() — nenhuma chama estes RPCs com a chave anon/authenticated.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- f_unaccent já existe (criado em 20260812_search_all_messages.sql); CREATE OR
-- REPLACE aqui é só defensivo caso esta migration rode isolada num ambiente novo.
CREATE OR REPLACE FUNCTION f_unaccent(text)
  RETURNS text
  LANGUAGE sql
  IMMUTABLE PARALLEL SAFE STRICT
  SET search_path = extensions, public, pg_catalog
AS $$ SELECT unaccent('unaccent', $1) $$;

-- ============================================================
-- search_leads
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_leads_name_trgm
  ON leads USING gin (f_unaccent(lower(name)) gin_trgm_ops) WHERE name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_company_trgm
  ON leads USING gin (f_unaccent(lower(company)) gin_trgm_ops) WHERE company IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_razao_social_trgm
  ON leads USING gin (f_unaccent(lower(razao_social)) gin_trgm_ops) WHERE razao_social IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_leads_nome_fantasia_trgm
  ON leads USING gin (f_unaccent(lower(nome_fantasia)) gin_trgm_ops) WHERE nome_fantasia IS NOT NULL;

DROP FUNCTION IF EXISTS search_leads(text, text, timestamptz, timestamptz, int, int);

-- Leads não têm dono (ver spec §5): sem parâmetro de escopo por role.
-- p_stage filtra leads.stage — o segmento do agente (secretaria/atacado/
-- private_label/exportacao/consumo), mesmo campo do filtro "Stage" da barra de
-- filtros de /leads (leads-filter-bar.tsx, alimentado por AGENT_STAGES em
-- lib/constants.ts). NÃO confundir com o stage_id do deal, que é outra coisa.
CREATE OR REPLACE FUNCTION search_leads(
  search_query text,
  p_stage text DEFAULT NULL,
  p_created_after timestamptz DEFAULT NULL,
  p_created_before timestamptz DEFAULT NULL,
  max_results int DEFAULT 20,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  id uuid,
  name text,
  company text,
  phone text,
  status text,
  stage text,
  nome_fantasia text,
  cnpj text,
  created_at timestamptz,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
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
    AND (p_stage IS NULL OR l.stage = p_stage)
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
$$;

-- Todas as 4 funções desta migration são SECURITY DEFINER e tratam parâmetro de
-- escopo NULL como "sem restrição" (e search_leads/search_sales nem têm escopo).
-- Por isso só `service_role` executa — mesmo raciocínio da auditoria de
-- 20260704_revoke_search_customer_messages_public.sql. CREATE FUNCTION concede
-- EXECUTE a PUBLIC por padrão, então o REVOKE abaixo não é redundante.
REVOKE EXECUTE ON FUNCTION public.search_leads(text, text, timestamptz, timestamptz, int, int)
  FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.search_leads(text, text, timestamptz, timestamptz, int, int)
  TO service_role;

-- ============================================================
-- search_deals
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_deals_title_trgm
  ON deals USING gin (f_unaccent(lower(title)) gin_trgm_ops);

DROP FUNCTION IF EXISTS search_deals(text, uuid[], uuid, uuid, timestamptz, timestamptz, int, int);

-- pipeline_ids = NULL -> admin, sem restrição. Vendedor: array de pipelines
-- próprios+universais (mesmo getAllowedPipelineIds() de /api/pipelines).
CREATE OR REPLACE FUNCTION search_deals(
  search_query text,
  pipeline_ids uuid[],
  p_pipeline_id uuid DEFAULT NULL,
  p_stage_id uuid DEFAULT NULL,
  p_created_after timestamptz DEFAULT NULL,
  p_created_before timestamptz DEFAULT NULL,
  max_results int DEFAULT 20,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  id uuid,
  title text,
  value numeric,
  pipeline_id uuid,
  pipeline_name text,
  stage_id uuid,
  stage_label text,
  lead_id uuid,
  lead_name text,
  lead_phone text,
  created_at timestamptz,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT d.*
    FROM deals d
    JOIN leads l ON l.id = d.lead_id
    WHERE (
      f_unaccent(lower(d.title)) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.name, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.company, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR f_unaccent(lower(coalesce(l.nome_fantasia, ''))) LIKE '%' || f_unaccent(lower(search_query)) || '%'
      OR (
        regexp_replace(search_query, '\D', '', 'g') <> ''
        AND regexp_replace(l.phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'
      )
    )
    AND (pipeline_ids IS NULL OR d.pipeline_id = ANY(pipeline_ids))
    AND (p_pipeline_id IS NULL OR d.pipeline_id = p_pipeline_id)
    AND (p_stage_id IS NULL OR d.stage_id = p_stage_id)
    AND (p_created_after IS NULL OR d.created_at >= p_created_after)
    AND (p_created_before IS NULL OR d.created_at <= p_created_before)
  )
  SELECT
    m.id, m.title, m.value, m.pipeline_id, p.name AS pipeline_name,
    m.stage_id, ps.label AS stage_label,
    m.lead_id, l.name AS lead_name, l.phone AS lead_phone,
    m.created_at,
    COUNT(*) OVER() AS total_count
  FROM matches m
  JOIN leads l ON l.id = m.lead_id
  LEFT JOIN pipelines p ON p.id = m.pipeline_id
  LEFT JOIN pipeline_stages ps ON ps.id = m.stage_id
  ORDER BY m.created_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

REVOKE EXECUTE ON FUNCTION public.search_deals(text, uuid[], uuid, uuid, timestamptz, timestamptz, int, int)
  FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.search_deals(text, uuid[], uuid, uuid, timestamptz, timestamptz, int, int)
  TO service_role;

-- ============================================================
-- search_sales
-- ============================================================

-- sales.product é NOT NULL, então o índice não precisa de predicado parcial.
CREATE INDEX IF NOT EXISTS idx_sales_product_trgm
  ON sales USING gin (f_unaccent(lower(product)) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_sales_notes_trgm
  ON sales USING gin (f_unaccent(lower(notes)) gin_trgm_ops) WHERE notes IS NOT NULL;

DROP FUNCTION IF EXISTS search_sales(text, timestamptz, timestamptz, int, int);

-- Vendas não têm dono (ver spec §5): sem parâmetro de escopo por role.
CREATE OR REPLACE FUNCTION search_sales(
  search_query text,
  p_sold_after timestamptz DEFAULT NULL,
  p_sold_before timestamptz DEFAULT NULL,
  max_results int DEFAULT 20,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  id uuid,
  product text,
  value numeric,
  sold_at timestamptz,
  notes text,
  lead_id uuid,
  lead_name text,
  lead_phone text,
  deal_id uuid,
  deal_title text,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
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
    COUNT(*) OVER() AS total_count
  FROM matches m
  JOIN leads l ON l.id = m.lead_id
  LEFT JOIN deals d ON d.id = m.deal_id
  ORDER BY m.sold_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

REVOKE EXECUTE ON FUNCTION public.search_sales(text, timestamptz, timestamptz, int, int)
  FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.search_sales(text, timestamptz, timestamptz, int, int)
  TO service_role;

-- ============================================================
-- search_customer_messages: extensão não-destrutiva
-- (docs_only, paginação via p_offset, e lead_id p/ o deep-link /conversas?lead_id=)
-- ============================================================

DROP FUNCTION IF EXISTS search_customer_messages(text, uuid[], int);

CREATE OR REPLACE FUNCTION search_customer_messages(
  search_query text,
  channel_ids uuid[],
  max_results int DEFAULT 50,
  docs_only boolean DEFAULT false,
  p_offset int DEFAULT 0
)
RETURNS TABLE (
  conversation_id uuid,
  message_id uuid,
  snippet text,
  match_created_at timestamptz,
  match_count bigint,
  lead_id uuid,
  lead_name text,
  lead_phone text,
  channel_id uuid,
  channel_name text,
  sent_by text,
  total_count bigint
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH matches AS (
    SELECT
      m.id            AS message_id,
      m.conversation_id,
      COALESCE(NULLIF(btrim(m.content), ''), m.document_name) AS snippet,
      m.created_at,
      m.sent_by,
      ROW_NUMBER() OVER (
        PARTITION BY m.conversation_id ORDER BY m.created_at DESC
      ) AS rn,
      COUNT(*) OVER (PARTITION BY m.conversation_id) AS match_count
    FROM messages m
    JOIN conversations c ON c.id = m.conversation_id
    WHERE m.role IN ('user', 'assistant')
      -- O OR de LIKE fica intacto (igual a 20260812) porque é a forma que o
      -- planner consegue resolver pelos índices trigram de messages. Colocar
      -- docs_only dentro de um CASE aqui tornaria o predicado não-indexável.
      AND (
        (m.content IS NOT NULL
          AND f_unaccent(lower(m.content)) LIKE '%' || f_unaccent(lower(search_query)) || '%')
        OR (m.document_name IS NOT NULL
          AND f_unaccent(lower(m.document_name)) LIKE '%' || f_unaccent(lower(search_query)) || '%')
      )
      -- docs_only = filtro separado: "restrinja a mensagens COM anexo", que é o
      -- que o toggle "Só documentos/mídia" da UI promete — e não "case apenas
      -- contra o nome do arquivo". Logo, um anexo cuja LEGENDA casa a busca
      -- também aparece com docs_only = true (intencional).
      AND (NOT docs_only OR m.document_name IS NOT NULL)
      AND (channel_ids IS NULL OR c.channel_id = ANY (channel_ids))
  ),
  deduped AS (
    SELECT *, COUNT(*) OVER() AS total_count
    FROM matches
    WHERE rn = 1
  )
  SELECT
    d.conversation_id, d.message_id, d.snippet, d.created_at AS match_created_at,
    d.match_count,
    c.lead_id, l.name AS lead_name, l.phone AS lead_phone,
    c.channel_id, ch.name AS channel_name, d.sent_by, d.total_count
  FROM deduped d
  JOIN conversations c  ON c.id = d.conversation_id
  LEFT JOIN leads l     ON l.id = c.lead_id
  LEFT JOIN channels ch ON ch.id = c.channel_id
  ORDER BY d.created_at DESC
  LIMIT GREATEST(max_results, 1)
  OFFSET GREATEST(p_offset, 0);
$$;

-- O DROP+CREATE acima cria uma função com OID NOVO, e CREATE FUNCTION concede
-- EXECUTE a PUBLIC por padrão — ou seja, o REVOKE da auditoria de
-- 20260704_revoke_search_customer_messages_public.sql morreu junto com a função
-- antiga e precisa ser reaplicado aqui. Sem isto, `anon` volta a poder chamar a
-- função via /rest/v1/rpc com channel_ids:null e vazar TODAS as mensagens.
-- (Este é o mesmo furo que 20260812_search_all_messages.sql deixou aberto ao
-- recriar a função sem reaplicar o revoke.)
REVOKE EXECUTE ON FUNCTION public.search_customer_messages(text, uuid[], int, boolean, int)
  FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.search_customer_messages(text, uuid[], int, boolean, int)
  TO service_role;
