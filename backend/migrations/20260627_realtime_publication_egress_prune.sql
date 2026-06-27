-- Poda da publicação supabase_realtime: remove 7 tabelas sem consumidor no frontend.
-- Contexto: a publicação tinha 15 tabelas, mas o dashboard só assina 8 via
-- postgres_changes. As 7 abaixo geravam decodificação de WAL (list_changes — o #1
-- custo do banco) e fanout de Egress a cada escrita, sem ninguém escutando.
-- Especialmente old_messages, lead_events e broadcast_leads (alto volume).
-- Reversível com ALTER PUBLICATION ... ADD TABLE. Ver auditoria de Egress do Realtime.
--
-- DROP TABLE da publicação não falha se a tabela já não estiver presente? Falha sim —
-- por isso o bloco condicional abaixo torna a migration idempotente (safe re-run e
-- safe para ambientes onde a poda já foi aplicada manualmente, como o prod).

do $$
declare
  t text;
  tables text[] := array[
    'old_messages',
    'lead_events',
    'broadcast_leads',
    'campaign_nodes',
    'channels',
    'agent_profiles',
    'lead_notes'
  ];
begin
  foreach t in array tables loop
    if exists (
      select 1 from pg_publication_tables
      where pubname = 'supabase_realtime'
        and schemaname = 'public'
        and tablename = t
    ) then
      execute format('alter publication supabase_realtime drop table public.%I', t);
    end if;
  end loop;
end $$;
