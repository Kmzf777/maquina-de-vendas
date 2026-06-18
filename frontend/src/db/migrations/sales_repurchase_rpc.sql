-- Ciclo médio de recompra (dias) calculado no banco, evitando carregar toda a tabela sales no Node.
-- Média dos intervalos entre vendas consecutivas do mesmo lead.
CREATE OR REPLACE FUNCTION get_avg_repurchase_cycle_days()
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
  WITH ordered AS (
    SELECT
      lead_id,
      sold_at,
      LAG(sold_at) OVER (PARTITION BY lead_id ORDER BY sold_at) AS prev_sold_at
    FROM sales
  ),
  intervals AS (
    SELECT EXTRACT(EPOCH FROM (sold_at - prev_sold_at)) / 86400.0 AS days
    FROM ordered
    WHERE prev_sold_at IS NOT NULL
  )
  SELECT ROUND(AVG(days)) FROM intervals;
$$;
