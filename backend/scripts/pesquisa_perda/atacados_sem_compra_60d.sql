-- backend/scripts/pesquisa_perda/atacados_sem_compra_60d.sql
--
-- Frente F4: público da PESQUISA DE PERDA do atacado (relatório
-- Canastra-Content-Creator/relatorios/atacado-funil-completo-2026-11.md, §6).
--
-- Uma linha por lead de ATACADO repassado ao vendedor nos últimos 60 dias que NÃO comprou
-- depois do repasse. Só leitura (SELECT): pode rodar com o usuário consulta_ro.
--
--   repasse   = 1º repasse do lead (vw_repasse_resposta, a mesma régua do SLA e do /trafego)
--   atacado   = leads.segmento = 'atacado' OU o evento `repasse` foi gravado com segmento atacado
--   sem compra= nenhuma venda não cancelada em `sales` com sold_at >= repasse
--   fora      = opt-out, blacklist e número errado (não se pergunta nada a quem pediu para sair)
--
-- `deal_id` é o card mais recente do lead (aberto ou fechado): é nele que a resposta da pesquisa
-- grava lost_reason_code / lost_competitor (app/button_flow/pesquisa_perda.py::aplicar).
-- `ja_tem_motivo` separa quem já tem motivo estruturado (não precisa de pesquisa).
--
-- Rodar:  psql ... -v dias=60 -f atacados_sem_compra_60d.sql   (sem -v, vale 60)
\if :{?dias}
\else
  \set dias 60
\endif

WITH repasse AS (
  SELECT r.lead_id, r.repasse_em, r.vendedor_id
    FROM public.vw_repasse_resposta r
   WHERE r.repasse_em >= now() - make_interval(days => :dias)
), atacado AS (
  SELECT rp.*
    FROM repasse rp
    JOIN public.leads l ON l.id = rp.lead_id
   WHERE l.segmento = 'atacado'
      OR EXISTS (SELECT 1 FROM public.lead_events e
                  WHERE e.lead_id = rp.lead_id
                    AND e.event_type = 'repasse'
                    AND e.metadata->>'segmento' = 'atacado')
)
SELECT l.id                        AS lead_id,
       COALESCE(l.name, l.nome_fantasia, l.company) AS nome,
       l.phone                     AS telefone,
       a.repasse_em,
       v.nome                      AS vendedor,
       d.id                        AS deal_id,
       d.title                     AS card,
       ps.label                    AS etapa,
       d.lost_reason_code,
       d.lost_competitor,
       d.lost_reason               AS observacao,
       (d.lost_reason_code IS NOT NULL AND d.lost_reason_code <> 'outro') AS ja_tem_motivo
  FROM atacado a
  JOIN public.leads l          ON l.id = a.lead_id
  LEFT JOIN public.vendedores v ON v.id = a.vendedor_id
  LEFT JOIN LATERAL (
        SELECT dd.*
          FROM public.deals dd
         WHERE dd.lead_id = l.id
         ORDER BY dd.updated_at DESC NULLS LAST, dd.created_at DESC
         LIMIT 1) d ON true
  LEFT JOIN public.pipeline_stages ps ON ps.id = d.stage_id
 WHERE NOT EXISTS (
         SELECT 1 FROM public.sales s
          WHERE s.lead_id = l.id
            AND s.sold_at >= a.repasse_em
            AND lower(COALESCE(s.status, '')) NOT LIKE 'cancel%')
   AND COALESCE(l.opt_out, false) = false
   AND (l.metadata->>'blacklisted_at') IS NULL
   AND (l.metadata->>'wrong_number_at') IS NULL
 ORDER BY a.repasse_em DESC;
