-- SEGURANÇA (auditoria 04/07): search_customer_messages é SECURITY DEFINER e estava
-- executável por `anon` e `authenticated` (na verdade por PUBLIC) via /rest/v1/rpc.
-- Como a função aceita channel_ids = NULL como "modo admin, SEM restrição de canal",
-- qualquer chamador anônimo podia POSTAR channel_ids:null e vazar TODAS as mensagens
-- de clientes — brecha crítica de exposição de dados.
--
-- O único consumidor legítimo é a rota /api/conversations/search do frontend, que chama
-- o RPC com a SERVICE ROLE (getServiceSupabase) — nunca com a chave anon/authenticated.
-- Logo, revogamos o EXECUTE de PUBLIC/anon/authenticated e deixamos apenas service_role.
-- Isso fecha os lints 0028 (anon) e 0029 (authenticated) do database linter.

REVOKE EXECUTE ON FUNCTION public.search_customer_messages(text, uuid[], int)
  FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.search_customer_messages(text, uuid[], int)
  TO service_role;
