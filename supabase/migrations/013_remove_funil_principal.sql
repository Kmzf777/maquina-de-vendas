-- 013_remove_funil_principal.sql
-- Remove o pipeline "Funil Principal" e todos os deals associados

DO $$
DECLARE
  v_pid uuid;
BEGIN
  SELECT id INTO v_pid FROM pipelines WHERE name = 'Funil Principal' LIMIT 1;

  IF v_pid IS NULL THEN
    RETURN;
  END IF;

  -- Deletar deals do Funil Principal
  DELETE FROM deals WHERE pipeline_id = v_pid;

  -- Deletar o pipeline (stages deletados via ON DELETE CASCADE)
  DELETE FROM pipelines WHERE id = v_pid;
END $$;
