-- Preenche messages.metadata.delivery_error das falhas antigas a partir dos webhooks
-- de status guardados em meta_webhook_logs (últimos 90 dias). Só ACRESCENTA a chave.
-- Desfazer: update messages set metadata = metadata - 'delivery_error' where metadata ? 'delivery_error';
-- Uso: psql -v ON_ERROR_STOP=1 -f backfill_delivery_error.sql   (cartão 7c6b70e7)
with ev as (
  select distinct on (s->>'id')
         s->>'id'                        as wamid,
         s->'errors'->0                  as err,
         (s->>'timestamp')::bigint       as ts
    from meta_webhook_logs w,
         jsonb_array_elements(w.payload->'entry')        en,
         jsonb_array_elements(en->'changes')             ch,
         jsonb_array_elements(ch->'value'->'statuses')   s
   where w.received_at > now() - interval '90 days'
     and jsonb_typeof(w.payload->'entry') = 'array'
     and s->>'status' = 'failed'
     and jsonb_typeof(s->'errors') = 'array'
     and jsonb_array_length(s->'errors') > 0
   order by s->>'id', w.received_at desc
)
update messages m
   set metadata = coalesce(m.metadata, '{}'::jsonb) || jsonb_build_object(
         'delivery_error', jsonb_build_object(
           'code',    (ev.err->>'code')::int,
           'title',   coalesce(ev.err->>'title', ev.err->>'message'),
           'details', ev.err->'error_data'->>'details',
           'at',      to_char(to_timestamp(ev.ts) at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')))
  from ev
 where m.wamid = ev.wamid
   and m.delivery_status = 'failed'
   and not (coalesce(m.metadata, '{}'::jsonb) ? 'delivery_error');
