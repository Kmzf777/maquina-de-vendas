-- scripts/leads_vendedor/f2_contagem_producao.sql — contagem prévia do F2 (cartão b67f1c6b), SÓ SELECT.
-- Roda em produção ANTES da migration 20261022b (sem leads.segmento: hoje todo segmento é NULL,
-- então o _alvo do F2 = leads com stage-segmento).
-- Uso: psql -X -tA -f f2_contagem_producao.sql
begin read only;

select coalesce(stage, 'TOTAL') as stage, count(*) as alvo
  from public.leads
 where stage in ('atacado', 'private_label', 'consumo', 'exportacao')
 group by rollup (stage)
 order by stage nulls last;

rollback;
