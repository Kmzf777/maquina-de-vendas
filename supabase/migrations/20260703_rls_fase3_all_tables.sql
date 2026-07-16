-- =============================================================================
-- RLS Fase 3 — fecha as 28 tabelas públicas restantes sem Row Level Security.
--
-- Contexto: a anon key (pública no bundle JS do CRM) podia ler/escrever TODAS
-- estas tabelas via REST/Realtime. A Fase 2 (20260703_rls_messages_conversations.sql)
-- fechou `messages`/`conversations`; pipelines/deals/products/sla_* já tinham RLS.
-- Inventário completo do frontend (Onda 0, 03/07/2026) classificou o restante:
--
--   GRUPO A (22 tabelas) — ZERO acesso client-side (todo uso via API routes com
--   service key, que bypassa RLS): habilitar RLS SEM policy = nega anon e
--   authenticated por padrão, sem quebrar nada.
--
--   GRUPO B (4 tabelas) — leitura client-side (algumas com Realtime):
--     tags, lead_tags        -> SELECT para authenticated (USING true — dados não
--                               segmentados; mesmo precedente de sla_*/products).
--     broadcasts, campaigns  -> SELECT admin-ou-dono-do-canal (padrão da Fase 2);
--                               linhas com channel_id NULL ficam visíveis a todo
--                               authenticated (preserva o comportamento atual das
--                               telas; segmentar NULLs é decisão de produto futura).
--     campaign_enrollments   -> SELECT via junção campaign -> channels (mesma regra
--                               de NULL). O filtro client-side por campaign_id NÃO
--                               é segurança; a policy é quem corta o Realtime.
--
--   GRUPO C (1 tabela) — leads: o CRM lê/insere/atualiza DIRETO do browser
--   (use-realtime-leads, quick-add-lead, lead-detail-sidebar) e leads NÃO tem FK
--   para channels (vínculo com dono é só transitivo e um lead pode ter conversas
--   em N canais). Decisão registrada: policies para authenticated SEM segmentação
--   (USING/WITH CHECK true) — fecha a exposição anon (a vulnerabilidade real) e
--   preserva o comportamento atual do CRM 1:1. Segmentação por vendedor em leads
--   é decisão de produto futura (exigiria escopo transitivo via conversations e
--   rework das telas /leads e /qualificacao, que hoje são globais).
--
-- Compatibilidade homolog: o schema de homolog está atrás do prod (6 tabelas do
-- Grupo A não existem lá) — todos os statements são guardados por to_regclass,
-- então o MESMO arquivo aplica limpo nos dois ambientes.
--
-- Realtime: policies de SELECT filtram postgres_changes por assinante (mesma
-- mecânica da Fase 2). DELETEs só carregam a PK (não filtráveis) — consumidores
-- atuais usam eventos como gatilho de refetch escopado, sem impacto.
--
-- service_role (backend Python e API routes do Next): bypassa RLS, inalterado.
--
-- Rollback (por tabela):
--   alter table public.<tabela> disable row level security;
--   (policies podem permanecer — inertes com RLS off; ou drop policy if exists)
-- =============================================================================

begin;

-- Mesma função da Fase 2 (idempotente): papel admin lido do JWT (app_metadata.role).
create or replace function public.jwt_is_admin()
returns boolean
language sql
stable
as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', '') = 'admin'
$$;

-- ---------------------------------------------------------------------------
-- GRUPO A — enable-only (nega anon/authenticated por padrão; service_role passa)
-- ---------------------------------------------------------------------------
do $$
declare
  t text;
begin
  foreach t in array array[
    'channels', 'agent_profiles', 'broadcast_leads', 'campaign_nodes',
    'conversion_events', 'follow_up_jobs', 'lead_daily_sends', 'lead_events',
    'lead_notes', 'lp_email_jobs', 'message_processing_locks',
    'message_templates', 'messages_archive', 'meta_webhook_logs',
    'model_pricing', 'old_messages', 'quick_replies', 'quick_send_phones',
    'system_alerts', 'template_presets', 'templates', 'token_usage'
  ] loop
    if to_regclass('public.' || t) is not null then
      execute format('alter table public.%I enable row level security', t);
    end if;
  end loop;
end $$;

-- ---------------------------------------------------------------------------
-- GRUPO B — tags / lead_tags: leitura livre para authenticated (não segmentado;
-- precedente: sla_seller_config/products). Escrita continua só via service role.
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.tags') is not null then
    execute 'alter table public.tags enable row level security';
    execute 'drop policy if exists tags_select_authenticated on public.tags';
    execute 'create policy tags_select_authenticated on public.tags '
         || 'for select to authenticated using (true)';
  end if;

  if to_regclass('public.lead_tags') is not null then
    execute 'alter table public.lead_tags enable row level security';
    execute 'drop policy if exists lead_tags_select_authenticated on public.lead_tags';
    execute 'create policy lead_tags_select_authenticated on public.lead_tags '
         || 'for select to authenticated using (true)';
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- GRUPO B — broadcasts / campaigns: admin OU dono do canal (padrão Fase 2);
-- channel_id NULL visível a todo authenticated (preserva telas atuais).
-- Fecha também o Realtime aberto (broadcasts-changes / campaigns-realtime).
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.broadcasts') is not null then
    execute 'alter table public.broadcasts enable row level security';
    execute 'drop policy if exists broadcasts_select_scope on public.broadcasts';
    execute 'create policy broadcasts_select_scope on public.broadcasts '
         || 'for select to authenticated using ( '
         || '  public.jwt_is_admin() '
         || '  or broadcasts.channel_id is null '
         || '  or exists ( '
         || '    select 1 from public.channels ch '
         || '    where ch.id = broadcasts.channel_id '
         || '      and ch.owner_user_id = (select auth.uid()) '
         || '  ) '
         || ')';
  end if;

  if to_regclass('public.campaigns') is not null then
    execute 'alter table public.campaigns enable row level security';
    execute 'drop policy if exists campaigns_select_scope on public.campaigns';
    execute 'create policy campaigns_select_scope on public.campaigns '
         || 'for select to authenticated using ( '
         || '  public.jwt_is_admin() '
         || '  or campaigns.channel_id is null '
         || '  or exists ( '
         || '    select 1 from public.channels ch '
         || '    where ch.id = campaigns.channel_id '
         || '      and ch.owner_user_id = (select auth.uid()) '
         || '  ) '
         || ')';
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- GRUPO B — campaign_enrollments: escopo herdado da campanha (junção dupla
-- enrollments -> campaigns -> channels), com a mesma regra de NULL.
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.campaign_enrollments') is not null then
    execute 'alter table public.campaign_enrollments enable row level security';
    execute 'drop policy if exists campaign_enrollments_select_scope on public.campaign_enrollments';
    execute 'create policy campaign_enrollments_select_scope on public.campaign_enrollments '
         || 'for select to authenticated using ( '
         || '  public.jwt_is_admin() '
         || '  or exists ( '
         || '    select 1 from public.campaigns cp '
         || '    left join public.channels ch on ch.id = cp.channel_id '
         || '    where cp.id = campaign_enrollments.campaign_id '
         || '      and (cp.channel_id is null or ch.owner_user_id = (select auth.uid())) '
         || '  ) '
         || ')';
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- GRUPO C — leads: fecha anon; preserva o CRM atual (não segmentado) 1:1.
-- SELECT (use-realtime-leads/lead-selector), INSERT (quick-add-lead) e
-- UPDATE (lead-detail-sidebar: status="lost") são feitos direto do browser.
-- DELETE continua só via API (service role) — sem policy de propósito.
-- ---------------------------------------------------------------------------
do $$
begin
  if to_regclass('public.leads') is not null then
    execute 'alter table public.leads enable row level security';
    execute 'drop policy if exists leads_select_authenticated on public.leads';
    execute 'create policy leads_select_authenticated on public.leads '
         || 'for select to authenticated using (true)';
    execute 'drop policy if exists leads_insert_authenticated on public.leads';
    execute 'create policy leads_insert_authenticated on public.leads '
         || 'for insert to authenticated with check (true)';
    execute 'drop policy if exists leads_update_authenticated on public.leads';
    execute 'create policy leads_update_authenticated on public.leads '
         || 'for update to authenticated using (true) with check (true)';
  end if;
end $$;

commit;

-- Pós-aplicação (fora da transação): recarrega o cache do PostgREST para as
-- policies valerem imediatamente nas conexões REST (ver memória do projeto:
-- PGRST205/cache após DDL).
notify pgrst, 'reload schema';
