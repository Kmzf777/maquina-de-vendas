-- 20260929_valeria_botoes.sql
-- ValerIA de botões: conteúdo editável do fluxo + o fluxo que cada perfil roda.
--
-- §1 é OVERRIDE, não fonte: linha ausente = default de
-- app/button_flow/valeria_registry.py. O fluxo roda com esta tabela VAZIA, de
-- propósito — migration pendente é um modo de falha recorrente neste repo, e
-- aqui ele não pode emudecer a ValerIA.
--
-- APLICAR À MÃO no Supabase: o deploy não roda migrations. Até ser aplicada, o
-- código novo funciona nos defaults do registry (fail-open) — só a tela de
-- edição e o "Ativar" em agent_profiles.flow_id ficam inertes.

-- ─── §1 Conteúdo editável ──────────────────────────────────────────────────
create table if not exists valeria_flow_content (
  id              uuid primary key default gen_random_uuid(),
  flow_id         text not null,
  node_id         text not null,
  corpo           text,
  rotulos         jsonb,
  -- Histórico: quem recebeu a tela antiga e clica depois manda o id antigo. O id
  -- não muda, então isto é rede para o caso de payload que só traz o título.
  rotulos_antigos jsonb not null default '[]'::jsonb,
  updated_at      timestamptz not null default now(),
  updated_by      uuid references auth.users(id),
  unique (flow_id, node_id)
);

-- updated_at automático — reaproveita public.set_updated_at(), já criada em
-- 20260618_products_catalog.sql e reusada por quotes/bling_jobs. Não recriada.
drop trigger if exists valeria_flow_content_set_updated_at on valeria_flow_content;
create trigger valeria_flow_content_set_updated_at
  before update on valeria_flow_content
  for each row execute function public.set_updated_at();

alter table valeria_flow_content enable row level security;

-- Admin lido do JWT (app_metadata.role), via public.jwt_is_admin() — mesma
-- função da Fase 3 de RLS (20260703_rls_fase3_all_tables.sql), reaproveitada
-- aqui e não redefinida. Este repo NÃO tem tabela public.users com coluna
-- role: o papel admin vive em auth.users via app_metadata, nunca numa tabela
-- própria — conferir contra qualquer policy que use "users u ... u.role" é
-- assinatura de convenção errada.
drop policy if exists valeria_flow_content_leitura on valeria_flow_content;
create policy valeria_flow_content_leitura on valeria_flow_content
  for select to authenticated using (true);

drop policy if exists valeria_flow_content_escrita on valeria_flow_content;
create policy valeria_flow_content_escrita on valeria_flow_content
  for all to authenticated
  using (public.jwt_is_admin())
  with check (public.jwt_is_admin());

-- ─── §2 Qual fluxo o perfil roda ───────────────────────────────────────────
-- kind='button_flow' hoje só sabe de UM fluxo (o runner assume recuperacao_v1).
-- Com dois, o perfil precisa dizer qual. NULL = 'recuperacao_v1', para o perfil
-- que já existe em produção continuar funcionando sem UPDATE.
--
-- Coluna nova e NÃO prompt_key reaproveitado: nome com dois significados é
-- exatamente a classe de bug que campaigns/node_registry.py documenta.
alter table agent_profiles add column if not exists flow_id text;

comment on column agent_profiles.flow_id is
  'Fluxo de botões que este perfil roda. NULL = recuperacao_v1. Ignorado quando kind=llm.';

-- ─── §3 Tags de desfecho ───────────────────────────────────────────────────
-- Por NOME EXATO: add_tags_to_lead resolve por nome e devolve em silêncio se não
-- achar, então nome divergente aqui não levanta erro nenhum — só perde a tag.
--
-- NÃO usa ON CONFLICT (name): tags.name não tem unique/exclusion constraint
-- neste schema (002_crm_enrichment.sql cria a tabela sem ela, e nenhuma
-- migration posterior adiciona uma) — ON CONFLICT (name) quebraria com
-- "no unique or exclusion constraint matching". Mesmo padrão WHERE NOT EXISTS
-- de 20260820_button_flow_agent.sql.
insert into tags (name, color)
select v.name, v.color
from (values
  ('Botões: Qualificado',        '#16A34A'),
  ('Botões: Adiado',             '#CA8A04'),
  ('Botões: Atendimento humano', '#2563EB'),
  ('Botões: Opt-out',            '#DC2626')
) as v(name, color)
where not exists (select 1 from tags t where t.name = v.name);

-- PostgREST só enxerga tabela nova depois de recarregar o cache de schema
-- (mesmo cuidado de 20260825_quotes.sql) — sem isto, valeria_flow_content
-- responde PGRST205 mesmo já existindo no banco.
notify pgrst, 'reload schema';
