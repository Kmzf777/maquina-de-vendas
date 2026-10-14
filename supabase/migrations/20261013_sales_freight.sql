-- Frete do pedido de venda, guardado à parte para a edição reabrir com ele.
-- Sem isso o PUT no Bling (que manda o pedido inteiro) apagaria o frete.
-- `value` continua sendo o total com frete (order_net_total).
-- Mesmos tipos de quotes.freight/freight_mode. Só aditiva: vendas antigas
-- ficam com 0/null.
ALTER TABLE sales
  ADD COLUMN IF NOT EXISTS freight numeric(12,2) NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS freight_mode smallint;
