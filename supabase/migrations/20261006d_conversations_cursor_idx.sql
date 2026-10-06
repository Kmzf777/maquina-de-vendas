-- 20261006d_conversations_cursor_idx.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a mao.
-- ⚠️ CONCURRENTLY nao roda dentro de transacao: no SQL editor, rode o comando sozinho.
--
-- A lista de conversas passou a ser paginada por cursor (P5 da call de 01/10):
--   order by last_msg_at desc nulls last, id desc
-- Este indice serve exatamente essa ordem. Com ~5,5 mil conversas ainda e barato sem
-- ele; o indice e para a lista continuar rapida quando a base crescer.
create index concurrently if not exists conversations_last_msg_cursor_idx
  on public.conversations (last_msg_at desc nulls last, id desc);
