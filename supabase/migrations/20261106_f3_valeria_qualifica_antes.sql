-- 20261106_f3_valeria_qualifica_antes.sql
-- F3 (06/11/2026): a ValerIA v2 pergunta uso, volume e CNPJ antes da vitrine.
--
-- Só a tag do desfecho novo, T_SEM_CNPJ (valeria_registry_v2.TAG_SEM_CNPJ). Os
-- eventos novos (`lead_events.desqualificado` e `metadata.motivo_codigo` do
-- `repasse`) não precisam de migração: `event_type` e `metadata` são livres.
--
-- APLICAR À MÃO no Supabase, só com o ok do Rafael: o deploy não roda migrations.
-- Sem ela o T_SEM_CNPJ funciona igual, só não marca o lead (add_tags_to_lead
-- resolve por NOME EXATO e devolve em silêncio se não achar).
--
-- NÃO usa ON CONFLICT (name): tags.name não tem unique (mesmo padrão de
-- 20261008_valeria_botoes_v2.sql).
insert into tags (name, color)
select v.name, v.color
from (values
  ('Atacado sem CNPJ', '#F59E0B')
) as v(name, color)
where not exists (select 1 from tags t where t.name = v.name);
