-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_disparos with (security_invoker=true) as
 WITH bl AS (
         SELECT b_1.broadcast_id,
            b_1.lead_id,
            b_1.status,
            b_1.sent_at,
            b_1.delivered_at,
            b_1.first_replied_at,
            b_1.status = ANY (ARRAY['sent'::text, 'delivered'::text]) AS enviado,
            b_1.first_replied_at IS NOT NULL OR (EXISTS ( SELECT 1
                   FROM messages m
                  WHERE b_1.wamid IS NOT NULL AND m.wamid = b_1.wamid AND m.delivery_status = 'read'::text)) AS lido,
            (b_1.sent_at AT TIME ZONE 'America/Sao_Paulo'::text)::date AS envio_data
           FROM broadcast_leads b_1
        ), vendas AS (
         SELECT bl.broadcast_id,
            count(DISTINCT f.venda_id) AS vendas_7d,
            COALESCE(sum(f.receita), 0::numeric) AS receita_7d
           FROM bl
             JOIN analytics.fct_vendas f ON f.lead_id = bl.lead_id AND NOT f.cancelada AND f.venda_data >= bl.envio_data AND f.venda_data <= (bl.envio_data + 7)
          WHERE bl.enviado
          GROUP BY bl.broadcast_id
        ), agg AS (
         SELECT bl.broadcast_id,
            min(bl.sent_at) AS primeiro_envio,
            count(*) AS destinatarios,
            count(*) FILTER (WHERE bl.enviado) AS enviados,
            count(*) FILTER (WHERE bl.delivered_at IS NOT NULL) AS entregues,
            count(*) FILTER (WHERE bl.enviado AND bl.lido) AS lidos,
            count(*) FILTER (WHERE bl.first_replied_at IS NOT NULL) AS respondidos,
            count(*) FILTER (WHERE bl.status = 'failed'::text) AS falhas
           FROM bl
          GROUP BY bl.broadcast_id
        )
 SELECT b.id AS broadcast_id,
    b.name AS nome,
    b.template_name AS template,
    b.status,
    COALESCE(a.primeiro_envio, b.scheduled_at, b.created_at) AS enviado_em,
    (COALESCE(a.primeiro_envio, b.scheduled_at, b.created_at) AT TIME ZONE 'America/Sao_Paulo'::text)::date AS envio_data,
    COALESCE(a.destinatarios, 0::bigint)::integer AS destinatarios,
    COALESCE(a.enviados, 0::bigint)::integer AS enviados,
    COALESCE(a.entregues, 0::bigint)::integer AS entregues,
    COALESCE(a.lidos, 0::bigint)::integer AS lidos,
    COALESCE(a.respondidos, 0::bigint)::integer AS respondidos,
    COALESCE(a.falhas, 0::bigint)::integer AS falhas,
    round(100.0 * a.respondidos::numeric / NULLIF(a.enviados, 0)::numeric, 1) AS taxa_resposta,
    COALESCE(v.vendas_7d, 0::bigint)::integer AS vendas_7d,
    COALESCE(v.receita_7d, 0::numeric) AS receita_7d
   FROM broadcasts b
     LEFT JOIN agg a ON a.broadcast_id = b.id
     LEFT JOIN vendas v ON v.broadcast_id = b.id
  WHERE b.env_tag = 'production'::text;

comment on view analytics.vw_disparos is 'Um disparo (broadcast de produção) por linha: enviados (status sent ou delivered), entregues (delivered_at), lidos (mensagem do disparo com status read, ou que teve resposta), respondidos (first_replied_at, resposta em até 48h), taxa de resposta sobre enviados, e vendas/receita sem frete de quem recebeu, da data do envio até 7 dias depois. Não usa deal_moved_at, que é gravado no envio e não indica conversão (B7).';
grant SELECT on analytics.vw_disparos to consulta_ro;
