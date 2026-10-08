-- 20261008_valeria_botoes_v2.sql
-- ValerIA de botões v2 (vitrine): a tag do desfecho novo, T_KIT.
--
-- Só a tag: o conteúdo editável da v2 mora na MESMA valeria_flow_content da v1
-- (flow_id = 'valeria_botoes_v2'), e o perfil aponta para a v2 pelo mesmo
-- agent_profiles.flow_id — os dois já criados por 20260929_valeria_botoes.sql.
--
-- APLICAR À MÃO no Supabase: o deploy não roda migrations. Sem ela o T_KIT
-- funciona igual, só não marca o lead (add_tags_to_lead resolve por NOME EXATO e
-- devolve em silêncio se não achar). O nome tem de ser idêntico a
-- valeria_registry_v2.TAG_KIT.
--
-- NÃO usa ON CONFLICT (name): tags.name não tem unique/exclusion constraint
-- (mesmo motivo e mesmo padrão WHERE NOT EXISTS de 20260929_valeria_botoes.sql).
insert into tags (name, color)
select v.name, v.color
from (values
  ('Botões: Kit amostra', '#9333EA')
) as v(name, color)
where not exists (select 1 from tags t where t.name = v.name);
