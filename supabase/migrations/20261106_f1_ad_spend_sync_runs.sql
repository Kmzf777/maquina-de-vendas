-- Frente F1 (06/11/2026) — /trafego seguro e confiável. Spec: Canastra-Content-Creator/relatorios/
-- crm-jornada-e-trafego-2026-11.md, Cartão A, item 4.
-- ad_spend_sync_runs grava cada rodada do sync de investimento (Google e Meta): status ok/falha/aviso,
-- linhas e o motivo. Alimenta a linha "sincronizado/falhou em" embaixo do botão Atualizar do /trafego.
-- "aviso" = a API respondeu 0 linhas em dia útil com gasto nos últimos 7 dias (foi assim que a v21 do
-- Google morreu em 11/08/2026 sem ninguém ver).
-- O backend é fail-soft sem esta tabela (o sync segue, só sem histórico). Aplicar à mão, como as outras.
-- Só cria objetos. Reexecutar é seguro. Depois: SIGUSR1 no PostgREST (ou NOTIFY pgrst, 'reload schema').
-- ROLLBACK: drop table if exists public.ad_spend_sync_runs;
create table if not exists public.ad_spend_sync_runs (
  id bigserial primary key,
  platform text not null check (platform in ('google', 'meta')),
  status text not null check (status in ('ok', 'falha', 'aviso')),
  linhas int not null default 0,
  motivo text,
  origem text not null default 'automatica' check (origem in ('automatica', 'manual')),
  criado_em timestamptz not null default now()
);
create index if not exists ad_spend_sync_runs_platform_criado_idx
  on public.ad_spend_sync_runs (platform, criado_em desc);

alter table public.ad_spend_sync_runs enable row level security;

grant select, insert on public.ad_spend_sync_runs to service_role;
grant usage, select on sequence public.ad_spend_sync_runs_id_seq to service_role;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'consulta_ro') then
    grant select on public.ad_spend_sync_runs to consulta_ro;
  end if;
end $$;
