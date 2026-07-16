-- Returns the most recent active deal (pipeline + stage) per lead.
-- "Active" = stage key is not 'fechado_ganho' or 'fechado_perdido'.
CREATE OR REPLACE FUNCTION get_lead_deals(lead_ids uuid[])
RETURNS TABLE(lead_id uuid, pipeline_name text, stage_label text, stage_dot_color text)
LANGUAGE sql STABLE AS $$
  SELECT DISTINCT ON (d.lead_id)
    d.lead_id,
    p.name        AS pipeline_name,
    ps.label      AS stage_label,
    ps.dot_color  AS stage_dot_color
  FROM deals d
  JOIN pipelines p       ON p.id  = d.pipeline_id
  JOIN pipeline_stages ps ON ps.id = d.stage_id
  WHERE d.lead_id = ANY(lead_ids)
    AND (ps.key IS NULL OR ps.key NOT IN ('fechado_ganho', 'fechado_perdido'))
  ORDER BY d.lead_id, d.created_at DESC;
$$;
