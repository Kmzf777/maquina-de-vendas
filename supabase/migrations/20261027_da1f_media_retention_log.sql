-- Cartão da1f51a7 — spec docs/superpowers/specs/2026-10-27-midia-cliente-permanente-design.md.
-- Registro da rotação de mídia (backend/app/media_retention). Uma linha por objeto do Storage;
-- o dry-run diário faz upsert na mesma linha (unique bucket+path), sem duplicar.
-- Só cria tabela. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST.
-- ROLLBACK: drop table if exists public.media_retention_log;
create table if not exists public.media_retention_log (
  id bigserial primary key,
  bucket text not null,
  path text not null,
  size_bytes bigint,
  message_count int not null default 0,
  dry_run boolean not null,
  registrado_em timestamptz not null default now(),
  apagado_em timestamptz,
  unique (bucket, path)
);
alter table public.media_retention_log enable row level security;
grant select, insert, update on public.media_retention_log to service_role;
grant usage, select on sequence public.media_retention_log_id_seq to service_role;
