-- scripts/leads_vendedor/f3_contagem_producao.sql — contagem prévia do F3 (cartão b67f1c6b), SÓ SELECT.
-- Não depende de colunas novas. Também lista os gatilhos de leads (o F3 é UPDATE direto em stage).
-- Uso: psql -X -tA -f f3_contagem_producao.sql
begin read only;

select coalesce(stage, 'TOTAL') as stage,
       case when stage = 'secretaria' then 'triagem' when stage is null then '' else 'qualificando' end as fase,
       count(*) as alvo
  from public.leads
 where stage in ('atacado', 'private_label', 'consumo', 'exportacao',
                 'secretaria', 'contato', 'negociacao', 'ja_chamado')
 group by rollup (stage)
 order by stage nulls last;

select t.tgname, pg_get_triggerdef(t.oid)
  from pg_trigger t
 where t.tgrelid = 'public.leads'::regclass and not t.tgisinternal
 order by 1;

rollback;
