-- Retenção de meta_webhook_logs (15 dias) + drop de índice redundante.
-- Contexto: tabela de log inflou a 558MB (88% do DB) por loop de send_template
-- 400/404 sem política de retenção. Ver docs/superpowers/plans/2026-06-27-supabase-usage-anomaly-fix.md

create extension if not exists pg_cron;

-- Função de purga em lotes (batches) para limitar o tamanho de cada DELETE.
create or replace function public.purge_meta_webhook_logs(
  retention_days int default 15,
  batch_size int default 10000
) returns integer
language plpgsql
as $$
declare
  deleted_total int := 0;
  deleted_batch int;
  cutoff timestamptz := now() - make_interval(days => retention_days);
begin
  loop
    delete from public.meta_webhook_logs
    where ctid in (
      select ctid from public.meta_webhook_logs
      where received_at < cutoff
      limit batch_size
    );
    get diagnostics deleted_batch = row_count;
    deleted_total := deleted_total + deleted_batch;
    exit when deleted_batch = 0;
  end loop;
  return deleted_total;
end;
$$;

-- Agendamento diário às 06:00 UTC (03:00 BRT, baixo tráfego).
select cron.schedule(
  'purge-meta-webhook-logs',
  '0 6 * * *',
  $$select public.purge_meta_webhook_logs(15, 10000);$$
);

-- Drop do índice redundante: idx_meta_webhook_logs_from_number cobre (from_number,
-- received_at) na tabela inteira — mas linhas outbound têm from_number NULL (~398k),
-- então ele indexa quase só NULLs (23MB). O parcial inbound
-- meta_webhook_logs_from_number_idx (WHERE direction='inbound') cobre o lookup real.
drop index if exists public.idx_meta_webhook_logs_from_number;
