-- Normaliza o vendedor das vendas registradas no CRM.
--
-- Contexto medido em producao em 24/08/2026:
--   origin='bling'  -> 1.012 vendas, TODAS sem sold_by (o import nunca preenche)
--   origin='manual' ->    91 vendas, 63 sem sold_by
--   origin='crm'    ->     0 vendas
--
-- As 63 sem vendedor sao consequencia de um defeito de frontend: tres das
-- quatro telas que abrem o modal de venda nao passavam o usuario logado, entao
-- o campo nascia vazio. O defeito foi corrigido nesta mesma entrega; esta
-- migration cuida do passado.
--
-- Sem ela, o escopo por vendedor esconderia essas 63 vendas do proprio joao:
-- a regra e `sold_by = <e-mail dele> OU origin = 'bling'`, e uma venda manual
-- sem dono nao satisfaz nenhum dos dois lados.
--
-- As 28 que ja tem vendedor sao todas de joao@cafecanastra.com (verificado).
-- O usuario confirmou que foi ele quem vendeu todas as manuais.

ALTER TABLE sales ADD COLUMN IF NOT EXISTS sold_by_source   text;
ALTER TABLE sales ADD COLUMN IF NOT EXISTS sold_by_anterior text;

-- Guarda: um e-mail errado carimbaria 91 vendas para um usuario inexistente e o
-- painel abriria vazio, sem erro em lugar nenhum. Falhar alto e melhor.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM auth.users WHERE lower(email) = 'joao@cafecanastra.com'
  ) THEN
    RAISE EXCEPTION 'joao@cafecanastra.com nao existe em auth.users';
  END IF;
END $$;

UPDATE sales
   SET sold_by_anterior = sold_by,
       sold_by          = 'joao@cafecanastra.com',
       sold_by_source   = 'normalizacao_joao'
 WHERE origin = 'manual'
   AND (sold_by IS NULL OR lower(sold_by) <> 'joao@cafecanastra.com')
   -- Idempotencia: rodar duas vezes nao sobrescreve `sold_by_anterior` com o
   -- valor ja normalizado, o que destruiria a capacidade de desfazer.
   AND sold_by_source IS NULL
   -- Delimita ao passado. Sem isto, esta migration e uma arma carregada
   -- apontada para o futuro: existe uma segunda conta de vendedor ativa
   -- (Comercial2@cafecanastra.com, hoje com zero vendas), e uma reexecucao
   -- depois que ela comecar a vender transferiria as vendas dela para o joao
   -- sem nada avisar.
   AND created_at < '2026-08-24';

-- ROLLBACK (nao executar; guardado aqui de proposito):
--   UPDATE sales
--      SET sold_by = sold_by_anterior, sold_by_anterior = NULL, sold_by_source = NULL
--    WHERE sold_by_source = 'normalizacao_joao';
--
-- Duas colunas em vez de uma flag porque so assim se distingue "nao foi tocada"
-- de "foi tocada e antes era NULL".
