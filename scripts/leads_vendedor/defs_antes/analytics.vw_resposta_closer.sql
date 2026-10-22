-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_resposta_closer with (security_invoker=true) as
 WITH r AS (
         SELECT r.lead_id,
            r.repasse_em,
            r.repasse_data,
            r.vendedor,
            r.vendedor_chave,
            r.vendedor_fonte,
            r.segmento,
            r.b2b,
            r.conversation_id,
            dv.user_id,
            ( SELECT min(m.created_at) AS min
                   FROM messages m
                  WHERE m.lead_id = r.lead_id AND m.sent_by = 'seller'::text AND m.created_at > r.repasse_em) AS primeira_resposta_humana_em
           FROM analytics.vw_repasses r
             LEFT JOIN analytics.dim_vendedor dv ON dv.vendedor_chave = r.vendedor_chave
          WHERE r.ordem = 1
        ), x AS (
         SELECT r.lead_id,
            r.repasse_em,
            r.repasse_data,
            r.vendedor,
            r.vendedor_chave,
            r.vendedor_fonte,
            r.segmento,
            r.b2b,
            r.conversation_id,
            r.user_id,
            r.primeira_resposta_humana_em,
            cfg.user_id IS NOT NULL AS tem_config,
            COALESCE(cfg.window_start_minute, 600) AS ini_min,
            COALESCE(cfg.window_end_minute, 960) AS fim_min,
            COALESCE(cfg.active_weekdays, ARRAY[1, 2, 3, 4, 5]) AS dias_semana,
            (r.repasse_em AT TIME ZONE 'America/Sao_Paulo'::text) AS t0,
            (COALESCE(r.primeira_resposta_humana_em, now()) AT TIME ZONE 'America/Sao_Paulo'::text) AS t1
           FROM r
             LEFT JOIN LATERAL ( SELECT c.user_id,
                    c.window_start_minute,
                    c.window_end_minute,
                    c.active_weekdays
                   FROM sla_seller_config c
                  WHERE c.user_id = r.user_id AND c.active
                  ORDER BY c.updated_at DESC NULLS LAST
                 LIMIT 1) cfg ON true
        )
 SELECT x.lead_id,
    x.repasse_em,
    x.repasse_data,
    x.vendedor,
    x.vendedor_fonte,
    x.segmento,
    x.b2b,
    x.conversation_id,
    x.primeira_resposta_humana_em,
        CASE
            WHEN x.primeira_resposta_humana_em IS NOT NULL THEN round(EXTRACT(epoch FROM x.primeira_resposta_humana_em - x.repasse_em) / 60.0, 1)
            ELSE NULL::numeric
        END AS minutos_corridos,
        CASE
            WHEN x.primeira_resposta_humana_em IS NOT NULL THEN bu.minutos
            ELSE NULL::numeric
        END AS minutos_uteis,
    x.primeira_resposta_humana_em IS NOT NULL AS respondeu,
        CASE
            WHEN x.primeira_resposta_humana_em IS NULL THEN bu.minutos
            ELSE NULL::numeric
        END AS minutos_uteis_em_aberto,
        CASE
            WHEN x.tem_config THEN 'sla_seller_config'::text
            ELSE 'padrao_10h_16h_seg_sex'::text
        END AS horario_fonte,
    'respostas digitadas no celular do vendedor ainda não são gravadas'::text AS alerta_cobertura
   FROM x
     LEFT JOIN LATERAL ( SELECT round(COALESCE(sum(GREATEST(0::numeric, EXTRACT(epoch FROM LEAST(x.t1, d.d + make_interval(mins => x.fim_min)) - GREATEST(x.t0, d.d + make_interval(mins => x.ini_min))))), 0::numeric) / 60.0, 1) AS minutos
           FROM generate_series(date_trunc('day'::text, x.t0), date_trunc('day'::text, x.t1), '1 day'::interval) d(d)
          WHERE (EXTRACT(dow FROM d.d)::integer = ANY (x.dias_semana)) AND NOT (EXISTS ( SELECT 1
                   FROM sla_overrides o
                  WHERE o.user_id = x.user_id AND d.d::date >= o.start_date AND d.d::date <= o.end_date))) bu ON true;

comment on view analytics.vw_resposta_closer is 'Uma linha por primeiro repasse do lead (D3/D4): quanto tempo o closer levou para a primeira mensagem humana (sent_by = seller, em qualquer conversa do lead) depois do repasse, em minutos corridos e úteis (janela do vendedor em sla_seller_config, folgas de sla_overrides; sem configuração, 10h-16h seg-sex). IA, disparos e follow-ups automáticos não contam. Sem resposta: respondeu = false e minutos_uteis_em_aberto conta até agora. Alerta fixo: respostas digitadas no celular do vendedor ainda não são gravadas (B6).';
grant SELECT on analytics.vw_resposta_closer to consulta_ro;
