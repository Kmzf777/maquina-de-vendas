CREATE OR REPLACE FUNCTION get_broadcast_reply_metrics(p_broadcast_id uuid)
RETURNS TABLE(
  replied_count     bigint,
  reply_rate        numeric,
  avg_reply_secs    numeric,
  median_reply_secs numeric
)
LANGUAGE sql STABLE AS $$
  SELECT
    COUNT(*) FILTER (WHERE first_replied_at IS NOT NULL)
      AS replied_count,
    ROUND(
      COUNT(*) FILTER (WHERE first_replied_at IS NOT NULL)::numeric
      / NULLIF(COUNT(*) FILTER (WHERE status IN ('sent','delivered')), 0) * 100,
      1
    ) AS reply_rate,
    ROUND(
      AVG(EXTRACT(EPOCH FROM (first_replied_at - sent_at)))
        FILTER (WHERE first_replied_at IS NOT NULL),
      0
    ) AS avg_reply_secs,
    ROUND(
      PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (first_replied_at - sent_at))
      ) FILTER (WHERE first_replied_at IS NOT NULL),
      0
    ) AS median_reply_secs
  FROM broadcast_leads
  WHERE broadcast_id = p_broadcast_id
    AND status IN ('sent', 'delivered');
$$;
