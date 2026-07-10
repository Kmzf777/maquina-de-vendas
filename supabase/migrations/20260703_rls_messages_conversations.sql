-- =============================================================================
-- RLS em `messages` e `conversations` — correção definitiva do vazamento de
-- notificações/dados entre vendedores (Fase 2).
--
-- Contexto: ambas as tabelas estão na publicação `supabase_realtime` com RLS
-- desabilitado. Qualquer portador da anon key (que é pública no bundle JS)
-- podia ler TODAS as mensagens via REST ou assinar todos os INSERTs via
-- Realtime — foi assim que todo browser logado tocava som/toast de mensagens
-- de outros vendedores.
--
-- Modelo de acesso (espelha getAllowedChannelIds do frontend):
--   - admin (JWT app_metadata.role = 'admin')  => vê tudo.
--   - vendedor                                 => apenas linhas de canais que
--                                                 possui (channels.owner_user_id).
--   - anon / não autenticado                   => nada (RLS on sem policy).
--   - service_role (rotas de API e backend)    => bypassa RLS, inalterado.
--
-- O Realtime (postgres_changes) avalia estas policies por assinante: cada
-- browser passa a receber apenas eventos de linhas que pode SELECT-ar.
-- Exceção do protocolo: eventos DELETE não são filtráveis por RLS (só carregam
-- a PK) — os consumidores atuais só usam eventos como gatilho de refetch via
-- API escopada, então sem impacto.
--
-- Escrita client-side: o único write direto do browser nessas tabelas é o
-- UPDATE de conversations.last_seller_response_at (botão "finalizar" no
-- chat-header) — coberto pela policy de UPDATE abaixo. INSERTs/DELETEs de
-- ambas as tabelas acontecem só via service role.
--
-- Rollback:
--   alter table public.conversations disable row level security;
--   alter table public.messages disable row level security;
-- =============================================================================

begin;

-- Papel admin lido do JWT do usuário — mesma fonte que o server-side
-- (user.app_metadata.role). STABLE para ser avaliada uma vez por statement.
create or replace function public.jwt_is_admin()
returns boolean
language sql
stable
as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', '') = 'admin'
$$;

alter table public.conversations enable row level security;
alter table public.messages enable row level security;

-- ---------------------------------------------------------------------------
-- conversations: SELECT para admin ou dono do canal.
-- ---------------------------------------------------------------------------
drop policy if exists conversations_select_scope on public.conversations;
create policy conversations_select_scope on public.conversations
  for select to authenticated
  using (
    public.jwt_is_admin()
    or exists (
      select 1 from public.channels ch
      where ch.id = conversations.channel_id
        and ch.owner_user_id = (select auth.uid())
    )
  );

-- UPDATE com o mesmo escopo (necessário para o "finalizar atendimento" do
-- chat-header, que escreve last_seller_response_at direto do browser).
drop policy if exists conversations_update_scope on public.conversations;
create policy conversations_update_scope on public.conversations
  for update to authenticated
  using (
    public.jwt_is_admin()
    or exists (
      select 1 from public.channels ch
      where ch.id = conversations.channel_id
        and ch.owner_user_id = (select auth.uid())
    )
  )
  with check (
    public.jwt_is_admin()
    or exists (
      select 1 from public.channels ch
      where ch.id = conversations.channel_id
        and ch.owner_user_id = (select auth.uid())
    )
  );

-- ---------------------------------------------------------------------------
-- messages: SELECT para admin ou dono do canal da conversa. O ramo por
-- lead_id cobre mensagens legadas com conversation_id nulo (raras): visíveis
-- a quem possui QUALQUER canal com conversa daquele lead.
-- Índices de suporte já existentes: idx_messages_conversation,
-- idx_messages_lead_id, idx_conversations_channel_id, idx_channels_owner_user_id.
-- ---------------------------------------------------------------------------
drop policy if exists messages_select_scope on public.messages;
create policy messages_select_scope on public.messages
  for select to authenticated
  using (
    public.jwt_is_admin()
    or exists (
      select 1
      from public.conversations c
      join public.channels ch on ch.id = c.channel_id
      where c.id = messages.conversation_id
        and ch.owner_user_id = (select auth.uid())
    )
    or (
      messages.conversation_id is null
      and exists (
        select 1
        from public.conversations c
        join public.channels ch on ch.id = c.channel_id
        where c.lead_id = messages.lead_id
          and ch.owner_user_id = (select auth.uid())
      )
    )
  );

commit;
