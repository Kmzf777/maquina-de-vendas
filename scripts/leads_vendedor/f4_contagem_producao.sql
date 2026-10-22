-- scripts/leads_vendedor/f4_contagem_producao.sql — contagem prévia do F4 (cartão b67f1c6b), SÓ SELECT.
-- Roda em produção ANTES da migration 20261022c (sem leads.origem_cadastro: depois dela todo lead
-- existente nasce 'inbound', então a regra equivalente ignora a coluna).
-- Uso: psql -X -tA -f f4_contagem_producao.sql
begin read only;

select count(*) filter (where channel = 'bling' or metadata->>'origem' = 'bling_webhook') as bling_import,
       count(*) filter (where not (channel = 'bling' or metadata->>'origem' = 'bling_webhook')
                          and metadata->>'origem' = 'reativacao_bling')               as reativacao_import,
       count(*) filter (where status = 'ativo')                                         as status_ativo,
       count(*) filter (where channel = 'bling' or metadata->>'origem' in ('bling_webhook', 'reativacao_bling')
                           or status = 'ativo')                                          as alvo
  from public.leads;

rollback;
