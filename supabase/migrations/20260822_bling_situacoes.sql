-- Espelho das situacoes de pedido. Existe porque o nome da situacao NAO vem no
-- pedido nem no webhook — os dois trazem so `{id, valor}`. Sem este espelho,
-- `sales.bling_situacao_nome` fica nulo e /painel-vendas mostra "Registrada"
-- para todo pedido, qualquer que seja a situacao real no ERP.
CREATE TABLE IF NOT EXISTS bling_situacoes (
  id        bigint PRIMARY KEY,
  nome      text NOT NULL,
  modulo_id bigint,
  cor       text,
  synced_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE bling_situacoes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS bling_situacoes_select ON bling_situacoes;
CREATE POLICY bling_situacoes_select ON bling_situacoes
  FOR SELECT TO authenticated, service_role USING (true);
