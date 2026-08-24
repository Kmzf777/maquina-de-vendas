-- Ciclo medio de recompra passa a aceitar um vendedor.
--
-- Ate aqui a funcao nao tinha parametro e agregava a tabela `sales` inteira.
-- No /painel-vendas isso ficava ao lado de tres cards que respeitam o filtro,
-- entao o vendedor lia quatro numeros lado a lado supondo que os quatro eram
-- dele — e o quarto era da operacao toda.
--
-- O periodo (De/Ate) NAO entra aqui, por decisao: restringir a janela
-- descartaria o intervalo entre uma venda dentro e outra fora dela, e o numero
-- encolheria conforme o usuario mexesse nas datas. O ciclo continua sendo
-- calculado sobre todo o historico do vendedor.
--
-- O DROP e necessario, nao e limpeza: criar a versao com DEFAULT sem remover a
-- de zero argumentos deixaria as duas coexistindo, e `get_avg_repurchase_cycle_days()`
-- passaria a ser uma chamada ambigua que o Postgres recusa.

DROP FUNCTION IF EXISTS get_avg_repurchase_cycle_days();

CREATE OR REPLACE FUNCTION get_avg_repurchase_cycle_days(p_sold_by text DEFAULT NULL)
RETURNS numeric
LANGUAGE sql
STABLE
AS $$
  WITH filtradas AS (
    SELECT lead_id, sold_at
      FROM sales
     -- `lower()` dos dois lados pela mesma razao do escopo por vendedor: o seed
     -- grava "Comercial2@..." com maiuscula, e comparacao exata casaria zero.
     WHERE p_sold_by IS NULL OR lower(sold_by) = lower(p_sold_by)
  ),
  ordered AS (
    SELECT
      lead_id,
      sold_at,
      LAG(sold_at) OVER (PARTITION BY lead_id ORDER BY sold_at) AS prev_sold_at
    FROM filtradas
  ),
  intervals AS (
    SELECT EXTRACT(EPOCH FROM (sold_at - prev_sold_at)) / 86400.0 AS days
    FROM ordered
    WHERE prev_sold_at IS NOT NULL
  )
  SELECT ROUND(AVG(days)) FROM intervals;
$$;
