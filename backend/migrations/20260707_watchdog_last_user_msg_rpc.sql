-- =============================================================================
-- Watchdog egress — agrega "última mensagem do contato por conversa" no Postgres.
--
-- Contexto: `_find_unanswered_conversations` (backend/app/watchdog/service.py,
-- Checks 1/2/5) lê, a cada tick de 60s, até CANDIDATE_MAX_PAGES * CANDIDATE_PAGE_SIZE
-- = 5.000 linhas cruas de `messages` (role=user, janela de 24h) só para reduzir em
-- Python ao `max(created_at)` por conversation_id. Isso é o maior leitor recorrente
-- de banco do backend agora que o reconcile foi batched — puro egress de linhas que
-- o Postgres poderia agregar antes de enviar.
--
-- Esta função empurra a agregação para o banco: devolve UMA linha por conversa
-- (o timestamp da última mensagem do contato na janela) em vez de até 5.000 linhas.
-- Semanticamente idêntica ao loop paginado (é literalmente o GROUP BY que o Python
-- faz à mão) e ESTRITAMENTE mais completa: enxerga toda a janela de uma vez, sem o
-- teto de 5.000 linhas que podia truncar fantasmas antigos sob rajada. Preserva a
-- janela de 24h — NÃO encolhe o lookback (isso regrediria a rede de segurança).
--
-- O backend chama via service_role (bypassa RLS); a função é STABLE e read-only.
-- Ativação exige recarregar o cache do PostgREST (NOTIFY abaixo). O código Python
-- tem fallback para o caminho paginado se a função não existir, então o deploy é
-- seguro mesmo se esta migration ainda não tiver sido aplicada.
--
-- Rollback:
--   drop function if exists public.get_last_user_msg_per_conversation(timestamptz, timestamptz);
-- =============================================================================

create or replace function public.get_last_user_msg_per_conversation(
  p_since timestamptz,
  p_until timestamptz
)
returns table (conversation_id uuid, last_user_at timestamptz)
language sql
stable
as $$
  select m.conversation_id, max(m.created_at) as last_user_at
  from public.messages m
  where m.role = 'user'
    and m.conversation_id is not null
    and m.created_at >= p_since
    and m.created_at <= p_until
  group by m.conversation_id
$$;

grant execute on function public.get_last_user_msg_per_conversation(timestamptz, timestamptz) to service_role;

-- Índice de suporte: a agregação varre (role, created_at) na janela. Parcial em
-- role=user mantém o índice pequeno e cobre exatamente o predicado.
create index if not exists idx_messages_user_created
  on public.messages (created_at)
  where role = 'user';

-- PostgREST só expõe a função nova após recarregar o schema cache (senão PGRST202).
notify pgrst, 'reload schema';
