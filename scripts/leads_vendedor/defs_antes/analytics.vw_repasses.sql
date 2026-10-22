-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.vw_repasses with (security_invoker=true) as
 WITH msg AS (
         SELECT m.id AS message_id,
            m.lead_id,
            m.conversation_id,
            m.created_at AS repasse_em,
            TRIM(BOTH FROM "substring"(m.content, '^\[encaminhar_humano\] Lead encaminhado para ([^:\n]*)'::text)) AS vendedor_texto,
            "left"(TRIM(BOTH FROM "substring"(m.content, '^\[encaminhar_humano\] Lead encaminhado para [^:\n]*:\s*(.*)$'::text)), 300) AS motivo
           FROM messages m
          WHERE m.role = 'system'::text AND m.content ~~ '[encaminhar\_humano] Lead encaminhado%'::text AND m.lead_id IS NOT NULL
        )
 SELECT r.lead_id,
    r.repasse_em,
    (r.repasse_em AT TIME ZONE 'America/Sao_Paulo'::text)::date AS repasse_data,
    row_number() OVER (PARTITION BY r.lead_id ORDER BY r.repasse_em, r.message_id)::integer AS ordem,
    COALESCE(dvm.vendedor, dl.vendedor_responsavel) AS vendedor,
    COALESCE(dvm.vendedor_chave, dvl.vendedor_chave) AS vendedor_chave,
        CASE
            WHEN dvm.vendedor IS NOT NULL THEN 'mensagem'::text
            WHEN dl.vendedor_responsavel IS NOT NULL THEN 'lead_responsavel'::text
            ELSE 'sem'::text
        END AS vendedor_fonte,
    r.vendedor_texto,
    r.motivo,
    NOT (COALESCE(r.motivo, ''::text) ~~* 'IA temporariamente indispon%'::text OR COALESCE(r.motivo, ''::text) ~~* 'ESCALONAMENTO%'::text) AS por_qualificacao,
    dl.segmento,
    dl.b2b,
    r.conversation_id,
    r.message_id
   FROM msg r
     LEFT JOIN analytics.dim_lead dl ON dl.lead_id = r.lead_id
     LEFT JOIN analytics.dim_vendedor dvm ON dvm.vendedor_chave = lower(translate("substring"(r.vendedor_texto, '^[^\s@:._-]+'::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text))
     LEFT JOIN ( SELECT DISTINCT ON (d.user_id) d.user_id,
            d.vendedor,
            d.vendedor_chave
           FROM analytics.dim_vendedor d
          WHERE d.user_id IS NOT NULL
          ORDER BY d.user_id, d.vendedor_chave) dvl ON dvl.user_id = dl.vendedor_responsavel_id;

comment on view analytics.vw_repasses is 'Um repasse ao closer por linha (D3), lido das mensagens de sistema "[encaminhar_humano] Lead encaminhado para <vendedor>: <motivo>" (contorno do B3: não há evento de handoff em lead_events). ordem = 1 é o primeiro repasse do lead (o "foi ao closer"). Vendedor = nome citado na mensagem; quando a mensagem diz só "Vendedor"/"Comercial", usa o responsável atual do lead (vendedor_fonte). Segmento e B2B são os atuais do lead, não os do momento do repasse.';
grant SELECT on analytics.vw_repasses to consulta_ro;
