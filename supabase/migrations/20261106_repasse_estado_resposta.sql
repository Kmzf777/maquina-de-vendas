-- supabase/migrations/20261106_repasse_estado_resposta.sql
--
-- Frente F2 (06/11/2026) — estados da resposta ao repasse em public.vw_repasse_resposta.
-- Definição comum (F2 e F6): Canastra-Content-Creator/relatorios/2026-11-06-consolidado-trafego-crm.md §6.
-- Casos: Canastra-Content-Creator/relatorios/crm-sem-resposta-falso-2026-11.md.
--
-- O `respondeu` de 20261019_repasse_sla.sql é falso até existir a resposta, sem prazo:
-- o lead que escreveu às 18h25 (fora do horário) e o lead com quem ninguém falou (o
-- repasse dos botões sem contato automático) caem no mesmo "sem resposta" que um vendedor
-- que de fato não respondeu. A coluna `estado` separa:
--
--   vendedor_respondeu      mensagem humana do vendedor depois do repasse (leads.first_response_at,
--                           qualquer conversa). Reação não conta.
--   lead_nao_respondeu      no número do vendedor (canal mode='human'), a última mensagem depois do
--                           repasse é NOSSA (contato automático do João, follow-up): o lead não voltou.
--   em_aberto               a última mensagem é do lead e a espera ainda não chegou a 2 h úteis na
--                           janela do vendedor (fn_minutos_uteis_vendedor: fora do horário o relógio
--                           para). Também: contato automático (handoff_rescue) ainda agendado.
--   vendedor_nao_respondeu  a última mensagem é do lead e a espera passou de 2 h úteis. SÓ ESTE é falha.
--   sem_contato             nenhuma mensagem no número do vendedor depois do repasse e nenhum contato
--                           automático agendado. É falha do SISTEMA (o repasse dos botões antes da F2).
--
-- A espera começa na 1ª mensagem do lead depois da última mensagem nossa no número do vendedor
-- (ou do repasse). Reação do lead também não conta.
-- `fora_do_crm` = o vendedor atende fora do CRM (vendedores.atende_no_crm=false, o Arthur na
-- exportação): o estado continua calculado, mas não mede o vendedor — telas e relatórios o separam.
--
-- Só CREATE OR REPLACE VIEW com colunas NOVAS NO FIM: as 7 colunas de antes, os tipos, os grants
-- e o security_invoker=false continuam iguais (dashboard_kpis e as telas seguem funcionando).
--
-- NAO E APLICADA PELO DEPLOY. Aplicar à mão ANTES do push do frontend, pelo psql do supabase_db.
-- Reexecutar é seguro. Depois: recarregar o cache do PostgREST com SIGUSR1.
-- Desfazer: scripts/repasse_sla/rollback_20261106_estado.sql (DROP + a view de 20261019 §3 + grants).

BEGIN;
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE VIEW public.vw_repasse_resposta WITH (security_invoker = false) AS
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
), y AS (
  -- O número do vendedor depois do repasse: última mensagem nossa, última do lead.
  SELECT x.*,
         t.ultima_nossa_em,
         t.ultima_do_lead_em,
         EXISTS (SELECT 1 FROM follow_up_jobs j
                  WHERE j.lead_id = x.lead_id
                    AND j.job_type = 'handoff_rescue'
                    AND j.status IN ('pending', 'processing')
                    AND j.created_at >= x.repasse_em) AS contato_agendado
    FROM x
    LEFT JOIN LATERAL (
      SELECT max(m.created_at) FILTER (WHERE m.role = 'assistant') AS ultima_nossa_em,
             max(m.created_at) FILTER (WHERE m.role = 'user')      AS ultima_do_lead_em
        FROM conversations c
        JOIN channels ch ON ch.id = c.channel_id AND ch.mode = 'human'
        JOIN messages m  ON m.conversation_id = c.id
       WHERE c.lead_id = x.lead_id
         AND m.created_at > x.repasse_em
         AND m.role IN ('user', 'assistant')
         AND COALESCE(m.message_type, '') <> 'reaction'
    ) t ON true
), z AS (
  SELECT y.*,
         CASE WHEN y.primeira_resposta_em IS NULL
               AND y.ultima_do_lead_em IS NOT NULL
               AND y.ultima_do_lead_em > COALESCE(y.ultima_nossa_em, y.repasse_em)
         THEN (SELECT min(m.created_at)
                 FROM conversations c
                 JOIN channels ch ON ch.id = c.channel_id AND ch.mode = 'human'
                 JOIN messages m  ON m.conversation_id = c.id
                WHERE c.lead_id = y.lead_id
                  AND m.role = 'user'
                  AND COALESCE(m.message_type, '') <> 'reaction'
                  AND m.created_at > COALESCE(y.ultima_nossa_em, y.repasse_em))
         END AS espera_desde
    FROM y
), w AS (
  SELECT z.*,
         CASE WHEN z.espera_desde IS NOT NULL
              THEN fn_minutos_uteis_vendedor(z.vendedor_id, z.espera_desde, now()) END AS minutos_uteis_espera
    FROM z
)
SELECT w.lead_id,
       w.repasse_em,
       w.vendedor_id,
       w.primeira_resposta_em,
       CASE WHEN w.primeira_resposta_em IS NOT NULL
            THEN fn_minutos_uteis_vendedor(w.vendedor_id, w.repasse_em, w.primeira_resposta_em) END AS minutos_uteis,
       CASE WHEN w.primeira_resposta_em IS NULL
            THEN fn_minutos_uteis_vendedor(w.vendedor_id, w.repasse_em, now()) END AS minutos_uteis_em_aberto,
       (w.primeira_resposta_em IS NOT NULL) AS respondeu,
       -- ── F2: colunas novas, sempre no fim ──
       CASE
         WHEN w.primeira_resposta_em IS NOT NULL THEN 'vendedor_respondeu'
         WHEN w.espera_desde IS NOT NULL AND w.minutos_uteis_espera >= 120 THEN 'vendedor_nao_respondeu'
         WHEN w.espera_desde IS NOT NULL THEN 'em_aberto'
         WHEN w.ultima_nossa_em IS NOT NULL THEN 'lead_nao_respondeu'
         WHEN w.contato_agendado THEN 'em_aberto'
         ELSE 'sem_contato'
       END AS estado,
       w.espera_desde,
       w.minutos_uteis_espera,
       COALESCE((SELECT NOT v.atende_no_crm FROM vendedores v WHERE v.id = w.vendedor_id), false) AS fora_do_crm
  FROM w;

COMMENT ON VIEW public.vw_repasse_resposta IS
  'Cartão 7b143561 + F2 (06/11/2026): 1º repasse (mensagem-marcador) por lead, vendedor (evento repasse '
  'ou assigned_to), 1ª resposta seller em qualquer conversa (leads.first_response_at), minutos no horário '
  'do vendedor e o ESTADO da resposta (vendedor_respondeu, lead_nao_respondeu, em_aberto, '
  'vendedor_nao_respondeu, sem_contato; só vendedor_nao_respondeu é falha do vendedor, 2 h úteis). '
  'fora_do_crm = vendedor que atende fora do CRM (Arthur).';

COMMENT ON COLUMN public.vw_repasse_resposta.estado IS
  'vendedor_respondeu | lead_nao_respondeu | em_aberto | vendedor_nao_respondeu | sem_contato. '
  'Definição comum F2/F6 (consolidado de 06/11/2026). Reação não conta.';

COMMIT;
