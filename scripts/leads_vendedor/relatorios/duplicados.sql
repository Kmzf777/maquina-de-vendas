-- scripts/leads_vendedor/relatorios/duplicados.sql — relatório (cartão b67f1c6b), SÓ SELECT.
--
-- Possíveis leads/contatos duplicados, para decisão humana (nenhum backfill funde nada):
--   1. mesmo leads.wa_id com telefones (leads.phone) diferentes;
--   2. colisão nos últimos 10 dígitos do telefone (mesmo número com/sem 55, com/sem DDD
--      repetido, máscara etc.) entre leads diferentes;
--   3. telefones do Bling com máscara: leads.telefone_comercial com "(34) 99999-9999" (vem do
--      contato Bling) e, se os últimos 10 dígitos já são o phone de outro lead, qual; leads do
--      Bling sem telefone (phone 'bling-<id>'); bling_contacts com máscara nos campos *_e164;
--   4. CNPJ duplicado: leads.cnpj (só dígitos, 14) repetido entre leads, e bling_contacts.doc_digits
--      (14 dígitos) repetido entre contatos da mesma conta.
-- No fim, um resumo com a contagem de cada parte. Usa só colunas que já existem hoje.
-- Uso: psql -X -A -F '|' -f duplicados.sql

begin read only;

\echo '== 1. mesmo wa_id com telefones diferentes =='
select l.wa_id, count(*) as leads, count(distinct l.phone) as telefones,
       string_agg(l.phone || ' (' || coalesce(l.name, '-') || ', ' || l.id || ')', ' ; ' order by l.created_at) as leads_detalhe
  from public.leads l
 where nullif(btrim(l.wa_id), '') is not null
 group by l.wa_id
having count(distinct l.phone) > 1
 order by count(*) desc, l.wa_id;

\echo '== 2. colisao nos ultimos 10 digitos do telefone =='
with t as (
  select l.id, l.name, l.phone, l.created_at, l.channel,
         right(regexp_replace(coalesce(l.phone, ''), '\D', '', 'g'), 10) as fim10
    from public.leads l
)
select t.fim10, count(*) as leads, count(distinct t.phone) as telefones,
       string_agg(t.phone || ' (' || coalesce(t.name, '-') || ', ' || coalesce(t.channel, '-') || ', ' || t.id || ')',
                  ' ; ' order by t.created_at) as leads_detalhe
  from t
 where length(t.fim10) = 10
 group by t.fim10
having count(*) > 1
 order by count(*) desc, t.fim10;

\echo '== 3a. telefone Bling com mascara (leads.telefone_comercial) e lead que ja tem esse numero =='
with t as (
  select l.id, l.name, l.phone, l.channel, l.telefone_comercial,
         right(regexp_replace(l.telefone_comercial, '\D', '', 'g'), 10) as fim10
    from public.leads l
   where l.telefone_comercial ~ '[^0-9+]'
)
select t.id as lead_id, t.name, t.phone, t.channel, t.telefone_comercial,
       regexp_replace(t.telefone_comercial, '\D', '', 'g') as so_digitos,
       (select string_agg(o.phone || ' (' || coalesce(o.name, '-') || ', ' || o.id || ')', ' ; ')
          from public.leads o
         where o.id <> t.id and length(t.fim10) = 10
           and right(regexp_replace(coalesce(o.phone, ''), '\D', '', 'g'), 10) = t.fim10) as outro_lead_com_o_numero
  from t
 order by t.channel, t.name;

\echo '== 3b. leads do Bling sem telefone (phone = bling-<id>) =='
select l.id as lead_id, l.name, l.phone, l.telefone_comercial, l.cnpj, l.bling_contact_id, l.created_at
  from public.leads l
 where l.phone like 'bling-%'
 order by l.created_at;

\echo '== 3c. bling_contacts com mascara em telefone_e164/celular_e164 =='
select bc.account, bc.id as bling_contact_id, bc.nome, bc.telefone_e164, bc.celular_e164
  from public.bling_contacts bc
 where coalesce(bc.telefone_e164, '') || coalesce(bc.celular_e164, '') ~ '[^0-9+]'
 order by bc.account, bc.id;

\echo '== 4a. leads.cnpj duplicado =='
with c as (
  select l.id, l.name, l.phone, l.created_at, regexp_replace(l.cnpj, '\D', '', 'g') as cnpj
    from public.leads l
   where l.cnpj is not null
)
select c.cnpj, count(*) as leads,
       string_agg(coalesce(c.name, '-') || ' (' || coalesce(c.phone, '-') || ', ' || c.id || ')', ' ; ' order by c.created_at) as leads_detalhe
  from c
 where length(c.cnpj) = 14
 group by c.cnpj
having count(*) > 1
 order by count(*) desc, c.cnpj;

\echo '== 4b. bling_contacts.doc_digits (CNPJ) duplicado na mesma conta =='
select bc.account, bc.doc_digits as cnpj, count(*) as contatos,
       string_agg(bc.id::text || ' ' || coalesce(bc.nome, '-'), ' ; ' order by bc.id) as contatos_detalhe
  from public.bling_contacts bc
 where length(bc.doc_digits) = 14
 group by bc.account, bc.doc_digits
having count(*) > 1
 order by count(*) desc, bc.account, bc.doc_digits;

\echo '== Resumo =='
select item, grupos from (
  select '1. wa_id com telefones diferentes' as item, count(*) as grupos from (
    select wa_id from public.leads where nullif(btrim(wa_id), '') is not null
     group by wa_id having count(distinct phone) > 1) x
  union all
  select '2. colisao ultimos 10 digitos', count(*) from (
    select right(regexp_replace(coalesce(phone, ''), '\D', '', 'g'), 10) as f from public.leads
     group by 1 having length(right(regexp_replace(coalesce(min(phone), ''), '\D', '', 'g'), 10)) = 10
                    and count(*) > 1) x
  union all
  select '3a. telefone_comercial com mascara', count(*) from public.leads where telefone_comercial ~ '[^0-9+]'
  union all
  select '3a. ... e o numero ja e o phone de outro lead', count(*) from public.leads t
   where t.telefone_comercial ~ '[^0-9+]'
     and length(right(regexp_replace(t.telefone_comercial, '\D', '', 'g'), 10)) = 10
     and exists (select 1 from public.leads o where o.id <> t.id
                  and right(regexp_replace(coalesce(o.phone, ''), '\D', '', 'g'), 10)
                      = right(regexp_replace(t.telefone_comercial, '\D', '', 'g'), 10))
  union all
  select '3b. leads do Bling sem telefone (bling-<id>)', count(*) from public.leads where phone like 'bling-%'
  union all
  select '3c. bling_contacts com mascara', count(*) from public.bling_contacts bc
   where coalesce(bc.telefone_e164, '') || coalesce(bc.celular_e164, '') ~ '[^0-9+]'
  union all
  select '4a. leads.cnpj duplicado', count(*) from (
    select regexp_replace(cnpj, '\D', '', 'g') from public.leads where cnpj is not null
     group by 1 having length(regexp_replace(min(cnpj), '\D', '', 'g')) = 14 and count(*) > 1) x
  union all
  select '4b. bling_contacts CNPJ duplicado', count(*) from (
    select 1 from public.bling_contacts where length(doc_digits) = 14
     group by account, doc_digits having count(*) > 1) x
) r
 order by item;

rollback;
