-- scripts/repasse_sla/rollback_20261106_estado.sql
-- Desfaz supabase/migrations/20261106_repasse_estado_resposta.sql (frente F2): volta a
-- vw_repasse_resposta às 7 colunas de 20261019_repasse_sla.sql §3.
-- CREATE OR REPLACE não remove colunas, então é DROP + CREATE. dashboard_kpis não segura a
-- view (corpo LANGUAGE sql em string, sem dependência registrada), mas o DROP derruba os
-- grants: eles são refeitos no fim. Depois: SIGUSR1 no PostgREST.
-- Antes, reverter o frontend (as telas leem `estado`; sem a coluna elas mostram "—").

BEGIN;
SET LOCAL lock_timeout = '5s';

DROP VIEW IF EXISTS public.vw_repasse_resposta;

CREATE VIEW public.vw_repasse_resposta WITH (security_invoker = false) AS
WITH r AS (
  SELECT h.lead_id, min(h.created_at) AS repasse_em
    FROM messages h
   WHERE h.role = 'system'
     AND h.content LIKE '[encaminhar\_humano] Lead encaminhado%'
     AND h.lead_id IS NOT NULL
   GROUP BY h.lead_id
), x AS (
  SELECT r.lead_id,
         r.repasse_em,
         COALESCE(
           (SELECT (e.metadata->>'vendedor_id')::uuid
              FROM lead_events e
             WHERE e.lead_id = r.lead_id
               AND e.event_type = 'repasse'
               AND e.metadata->>'vendedor_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
             ORDER BY e.occurred_at
             LIMIT 1),
           l.assigned_to) AS vendedor_id,
         l.first_response_at AS primeira_resposta_em
    FROM r
    JOIN leads l ON l.id = r.lead_id
)
SELECT x.lead_id,
       x.repasse_em,
       x.vendedor_id,
       x.primeira_resposta_em,
       CASE WHEN x.primeira_resposta_em IS NOT NULL
            THEN fn_minutos_uteis_vendedor(x.vendedor_id, x.repasse_em, x.primeira_resposta_em) END AS minutos_uteis,
       CASE WHEN x.primeira_resposta_em IS NULL
            THEN fn_minutos_uteis_vendedor(x.vendedor_id, x.repasse_em, now()) END AS minutos_uteis_em_aberto,
       (x.primeira_resposta_em IS NOT NULL) AS respondeu
  FROM x;

COMMENT ON VIEW public.vw_repasse_resposta IS
  'Cartão 7b143561: 1º repasse (mensagem-marcador) por lead, vendedor (evento repasse ou assigned_to), '
  '1ª resposta seller em qualquer conversa (leads.first_response_at) e minutos no horário do vendedor. '
  'Respostas digitadas no celular do vendedor não são gravadas.';

REVOKE ALL ON public.vw_repasse_resposta FROM PUBLIC, anon;
GRANT SELECT ON public.vw_repasse_resposta TO authenticated, service_role;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'consulta_ro') THEN
    GRANT SELECT ON public.vw_repasse_resposta TO consulta_ro;
  END IF;
END $$;

COMMIT;
