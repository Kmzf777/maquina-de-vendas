-- 20260626_valeria_unify_stage_keys.sql
-- Unifica o VOCABULÁRIO de `key` em TODOS os funis da Valéria (Atacado, Private Label,
-- Exportação, Consumo), espelhando o que já foi feito no funil frio (migration
-- 20260625). A partir daqui o mesmo conceito tem a MESMA key em qualquer funil, então o
-- reflexo de reply (advance_deal_on_reply) e as tools (marcar_interesse → qualificado)
-- se comportam de forma idêntica em todos os pipelines.
--
-- Mapeamento canônico aprovado (Seção 1 do design 2026-06-26):
--   Entrada        -> entrada
--   Novo (Frio)    -> novo        (já era)
--   Morno          -> respondeu   (era proposta/contato)
--   Quente (Fechar)-> qualificado (era negociacao/proposta)
--   Fechado Ganho  -> fechado_ganho (já era)
--   Perdido        -> perdido     (já era)
-- Também remove a coluna-lixo 'Novo Stage' (Valeria - Atacado), vazia.
--
-- Idempotente: casa por pipeline_id + label e grava a key canônica (reexecutável sem efeito
-- colateral — define sempre o mesmo valor). As keys antigas (proposta/negociacao/contato) NÃO
-- são referenciadas em código; só `stage_id_by_key`/`_perdido_stage_id` leem `key`, e os deals
-- referenciam `stage_id` (inalterado). Em ambientes sem esses pipelines (homolog) afeta 0 linhas.
-- Sem colisão com o índice único parcial (pipeline_id, key): dentro de cada funil as 6 keys
-- finais são distintas.
DO $$
DECLARE
  atacado_id uuid := 'bda5a3c1-d12b-4df8-bf94-f0e1b9bb0bdb';
  plabel_id  uuid := '4b70553e-a111-4679-8fa1-e79c12b3c17b';
  export_id  uuid := '4a0c9f7f-47ac-45b1-a760-e2ffc976ccf9';
  consumo_id uuid := '0f19ac7d-7c7b-4d33-8756-981e5f3e3f71';
BEGIN
  -- Valeria - Atacado (Morno=proposta, Quente=negociacao)
  UPDATE pipeline_stages SET key = 'entrada'     WHERE pipeline_id = atacado_id AND label = 'Entrada';
  UPDATE pipeline_stages SET key = 'novo'        WHERE pipeline_id = atacado_id AND label = 'Novo (Frio)';
  UPDATE pipeline_stages SET key = 'respondeu'   WHERE pipeline_id = atacado_id AND label = 'Morno';
  UPDATE pipeline_stages SET key = 'qualificado' WHERE pipeline_id = atacado_id AND label = 'Quente (Fechar)';
  UPDATE pipeline_stages SET key = 'fechado_ganho' WHERE pipeline_id = atacado_id AND label = 'Fechado Ganho';
  UPDATE pipeline_stages SET key = 'perdido'     WHERE pipeline_id = atacado_id AND label = 'Perdido';
  -- Remove a coluna-lixo vazia (sem deals) 'Novo Stage'.
  DELETE FROM pipeline_stages
   WHERE pipeline_id = atacado_id AND label = 'Novo Stage' AND key IS NULL
     AND NOT EXISTS (SELECT 1 FROM deals d WHERE d.stage_id = pipeline_stages.id);

  -- Valeria - Private Label (Morno=contato, Quente=proposta)
  UPDATE pipeline_stages SET key = 'entrada'     WHERE pipeline_id = plabel_id AND label = 'Entrada';
  UPDATE pipeline_stages SET key = 'novo'        WHERE pipeline_id = plabel_id AND label = 'Novo (Frio)';
  UPDATE pipeline_stages SET key = 'respondeu'   WHERE pipeline_id = plabel_id AND label = 'Morno';
  UPDATE pipeline_stages SET key = 'qualificado' WHERE pipeline_id = plabel_id AND label = 'Quente (Fechar)';
  UPDATE pipeline_stages SET key = 'fechado_ganho' WHERE pipeline_id = plabel_id AND label = 'Fechado Ganho';
  UPDATE pipeline_stages SET key = 'perdido'     WHERE pipeline_id = plabel_id AND label = 'Perdido';

  -- Arthur - Exportação (Morno=contato, Quente=proposta)
  UPDATE pipeline_stages SET key = 'novo'        WHERE pipeline_id = export_id AND label = 'Novo (Frio)';
  UPDATE pipeline_stages SET key = 'respondeu'   WHERE pipeline_id = export_id AND label = 'Morno';
  UPDATE pipeline_stages SET key = 'qualificado' WHERE pipeline_id = export_id AND label = 'Quente (Fechar)';
  UPDATE pipeline_stages SET key = 'fechado_ganho' WHERE pipeline_id = export_id AND label = 'Fechado Ganho';
  UPDATE pipeline_stages SET key = 'perdido'     WHERE pipeline_id = export_id AND label = 'Perdido';

  -- Valeria - Consumo (Morno=contato, Quente=proposta)
  UPDATE pipeline_stages SET key = 'novo'        WHERE pipeline_id = consumo_id AND label = 'Novo (Frio)';
  UPDATE pipeline_stages SET key = 'respondeu'   WHERE pipeline_id = consumo_id AND label = 'Morno';
  UPDATE pipeline_stages SET key = 'qualificado' WHERE pipeline_id = consumo_id AND label = 'Quente';
  UPDATE pipeline_stages SET key = 'fechado_ganho' WHERE pipeline_id = consumo_id AND label = 'Fechado Ganho';
  UPDATE pipeline_stages SET key = 'perdido'     WHERE pipeline_id = consumo_id AND label = 'Perdido';
END $$;
