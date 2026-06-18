-- backend/migrations/20260617_quick_replies.sql
--
-- Respostas rápidas (canned replies de texto livre) inseridas via "/" no compositor de /conversas.
-- Biblioteca GLOBAL (sem dono), acessada via route handlers com service-role — mesmo padrão de `tags`.
-- NÃO confundir com `message_templates` (templates HSM da Meta).

create table if not exists public.quick_replies (
  id          uuid primary key default gen_random_uuid(),
  shortcut    text,                       -- atalho do "/" (opcional). Ex.: "saudacao"
  title       text not null,              -- rótulo exibido na lista
  content     text not null,              -- corpo; pode conter {{primeiro_nome}} etc.
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists quick_replies_shortcut_idx on public.quick_replies (shortcut);
