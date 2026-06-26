-- 20260625_valeria_coldfunnel_stage_keys.sql
-- Padroniza o funil 'Valeria - Importação Leads Frios' (a9487d77-ae93-42fe-89b8-9747d5e9cdf4):
-- adiciona keys estáveis aos stages custom (que tinham key=null) e corrige a ordem
-- (Qualificado antes de Encerrado). A partir daqui o backend resolve esses stages por `key`
-- (autoritativo) com fallback por label — base do reflexo "Disparo feito → Respondeu" e das
-- tools de pipeline da Valéria (marcar_interesse → Qualificado, sem_interesse → Encerrado).
--
-- Idempotente: casa por pipeline_id + label e só preenche key quando NULL; reexecutável sem
-- efeito colateral. Em ambientes sem esse pipeline (ex.: homolog) afeta 0 linhas.
DO $$
DECLARE
  p_id uuid := 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4';
BEGIN
  UPDATE pipeline_stages SET key = 'frio'          WHERE pipeline_id = p_id AND label = 'Frio'          AND key IS NULL;
  UPDATE pipeline_stages SET key = 'disparo_feito' WHERE pipeline_id = p_id AND label = 'Disparo feito' AND key IS NULL;
  UPDATE pipeline_stages SET key = 'respondeu'     WHERE pipeline_id = p_id AND label = 'Respondeu'     AND key IS NULL;
  UPDATE pipeline_stages SET key = 'qualificado'   WHERE pipeline_id = p_id AND label = 'Qualificado'   AND key IS NULL;
  UPDATE pipeline_stages SET key = 'encerrado'     WHERE pipeline_id = p_id AND label = 'Encerrado'     AND key IS NULL;

  -- Reordena: Frio=0, Disparo feito=1, Respondeu=2, Qualificado=3, Encerrado=4.
  UPDATE pipeline_stages SET order_index = 3 WHERE pipeline_id = p_id AND key = 'qualificado';
  UPDATE pipeline_stages SET order_index = 4 WHERE pipeline_id = p_id AND key = 'encerrado';
END $$;
