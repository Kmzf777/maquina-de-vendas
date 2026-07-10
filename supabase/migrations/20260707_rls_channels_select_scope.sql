-- =============================================================================
-- RLS em `channels` — corrige janela de chat em branco para vendedores.
--
-- Contexto do bug (prod, 07/07): vendedores (ex.: joao@cafecanastra.com) viam a
-- prévia da conversa na barra lateral mas a janela principal abria vazia
-- ("Nenhuma mensagem."), enquanto admins (ex.: kelwin@cafecanastra.com) viam
-- tudo. A barra lateral é servida por /api/conversations com service_role
-- (bypassa RLS); a janela principal lê `messages` direto do browser (anon key),
-- sujeita a RLS.
--
-- Causa raiz: a fase 3 de RLS habilitou RLS em `channels` SEM criar policy de
-- SELECT (default-deny). As policies `conversations_select_scope` e
-- `messages_select_scope` escopam o vendedor via
--   exists (select 1 from channels ch where ch.owner_user_id = auth.uid())
-- e essa subquery roda sob a RLS do próprio usuário. Como `channels` negava
-- toda linha ao papel authenticated, o exists nunca era verdadeiro para
-- vendedor => 0 conversas e 0 mensagens visíveis no caminho client-side. O
-- admin escapava pelo curto-circuito jwt_is_admin(). Provado por impersonação
-- RLS: com esta policy, joao passa de 0 -> 749 conversas e 0 -> 6073 mensagens,
-- vendo apenas o canal que possui.
--
-- Modelo de acesso (mesmo de getAllowedChannelIds / demais policies):
--   - admin (JWT app_metadata.role = 'admin') => vê todos os canais.
--   - vendedor                                => apenas canais que possui.
--   - anon / não autenticado                  => nada.
--   - service_role (rotas de API e backend)   => bypassa RLS, inalterado.
--
-- Escopo mínimo: apenas SELECT. INSERT/UPDATE/DELETE de channels ocorrem só via
-- service role, então não recebem policy (permanecem negados no client).
--
-- Rollback:
--   drop policy if exists channels_select_scope on public.channels;
-- =============================================================================

begin;

alter table public.channels enable row level security;

drop policy if exists channels_select_scope on public.channels;
create policy channels_select_scope on public.channels
  for select to authenticated
  using (
    public.jwt_is_admin()
    or owner_user_id = (select auth.uid())
  );

commit;
