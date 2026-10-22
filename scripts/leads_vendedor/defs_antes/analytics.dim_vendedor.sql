-- Definição vigente em produção (pg_get_viewdef), lida em 2026-10-22 (b67f1c6b). Cópia literal para rollback.
-- owner: supabase_admin; reloptions: security_invoker=true
-- acl: {supabase_admin=arwdDxtm/supabase_admin,consulta_ro=r/supabase_admin}

create or replace view analytics.dim_vendedor with (security_invoker=true) as
 WITH fontes AS (
         SELECT c.user_id,
            NULL::text AS email,
            c.display_name AS nome,
            1 AS prioridade
           FROM sla_seller_config c
        UNION ALL
         SELECT ch.owner_user_id,
            NULL::text AS text,
            initcap(lower(TRIM(BOTH FROM regexp_replace(ch.name, '^\s*n[uú]mero\s+'::text, ''::text, 'i'::text)))) AS initcap,
            2
           FROM channels ch
          WHERE ch.mode = 'human'::text AND ch.owner_user_id IS NOT NULL
        UNION ALL
         SELECT p.owner_user_id,
            NULL::text AS text,
            TRIM(BOTH FROM split_part(p.name, ' - '::text, 1)) AS btrim,
            3
           FROM pipelines p
          WHERE p.owner_user_id IS NOT NULL AND p.name ~~ '% - %'::text
        UNION ALL
         SELECT NULL::uuid AS uuid,
            lower(TRIM(BOTH FROM m.user_email)) AS lower,
            NULL::text AS text,
            4
           FROM bling_seller_map m
          WHERE NULLIF(TRIM(BOTH FROM m.user_email), ''::text) IS NOT NULL
        UNION ALL
         SELECT DISTINCT NULL::uuid AS uuid,
            lower(TRIM(BOTH FROM s.sold_by)) AS lower,
            NULL::text AS text,
            5
           FROM sales s
          WHERE NULLIF(TRIM(BOTH FROM s.sold_by), ''::text) IS NOT NULL
        UNION ALL
         SELECT DISTINCT NULL::uuid AS uuid,
            lower(TRIM(BOTH FROM q.created_by)) AS lower,
            NULL::text AS text,
            6
           FROM quotes q
          WHERE NULLIF(TRIM(BOTH FROM q.created_by), ''::text) IS NOT NULL
        ), chaves AS (
         SELECT f.user_id,
            f.email,
            f.nome,
            f.prioridade,
            lower(translate("substring"(TRIM(BOTH FROM COALESCE(f.nome, f.email)), '^[^\s@:._-]+'::text), 'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇáàâãäéèêëíìîïóòôõöúùûüç'::text, 'AAAAAEEEEIIIIOOOOOUUUUCaaaaaeeeeiiiiooooouuuuc'::text)) AS chave
           FROM fontes f
        )
 SELECT chave AS vendedor_chave,
    COALESCE((array_agg(nome ORDER BY prioridade) FILTER (WHERE nome IS NOT NULL))[1], initcap(chave)) AS vendedor,
    (array_agg(DISTINCT user_id) FILTER (WHERE user_id IS NOT NULL))[1] AS user_id,
    min(email) AS email,
    COALESCE(array_agg(DISTINCT email) FILTER (WHERE email IS NOT NULL), '{}'::text[]) AS emails,
    count(DISTINCT user_id) > 1 AS alerta_ambiguo
   FROM chaves
  WHERE COALESCE(chave, ''::text) <> ''::text
  GROUP BY chave;

comment on view analytics.dim_vendedor is 'Auxiliar. Cadastro de vendedores (chave, nome, user_id, e-mails) montado sem auth.users, juntando sla_seller_config, canais humanos, donos de pipeline, bling_seller_map, sales.sold_by e quotes.created_by pelo primeiro nome normalizado; contorno do bug B2 (não existe tabela de vendedores).';
grant SELECT on analytics.dim_vendedor to consulta_ro;
