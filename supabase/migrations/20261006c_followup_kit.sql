-- 20261006c_followup_kit.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. Roda a MAO, depois de revisada (como 20260918/20260926).
--    Ordem do lote da call semanal: 20261006 -> 20261006b -> 20261006c (esta nao
--    depende das outras duas).
--
-- Pacote P6 da call semanal de 01/10 (spec 2026-10-06-call-semanal-0110-design.md, P6).
-- So ALARGA tres CHECKs; nao cria tabela, nao semeia, nao apaga linha, nao encosta na
-- tabela de jobs. Toda linha que ja existe continua valida (os CHECKs novos sao
-- superconjuntos dos antigos).
--
--   followup_joao_cadencia_par_valido      + 'kit' nos dois funis de Reposicao
--   followup_joao_toque_dentro_da_cadencia + kit com toques 1..2
--   followup_joao_ajustes_chave_valida     + 'dias_sem_prospeccao_apos_venda'
--
-- A cadencia `kit` NASCE DESLIGADA sem linha nenhuma aqui: ausencia de linha = vale o
-- codigo (app/follow_up/cadence_joao.py), e o codigo traz `ativa=False` e os dois
-- toques SEM template. Ligar, quando os templates forem aprovados na Meta, e gravar a
-- mao as linhas de toque (template) e de cadencia (ativa) — ver o relatorio do P6.
-- O ajuste novo tambem nasce sem linha: vale o default de codigo (30 dias).
--
-- Reexecutar e seguro: DROP CONSTRAINT IF EXISTS + ADD, numa transacao.

BEGIN;

ALTER TABLE followup_joao_cadencia
  DROP CONSTRAINT IF EXISTS followup_joao_cadencia_par_valido;
ALTER TABLE followup_joao_cadencia
  ADD CONSTRAINT followup_joao_cadencia_par_valido CHECK (
       (funil = 'atacado'                 AND cadencia IN ('novo', 'em_conversa', 'proposta'))
    OR (funil = 'private_label'           AND cadencia IN ('novo', 'em_conversa', 'proposta'))
    OR (funil = 'reposicao_atacado'       AND cadencia IN ('reposicao', 'em_atencao', 'kit'))
    OR (funil = 'reposicao_private_label' AND cadencia IN ('reposicao', 'em_atencao', 'kit'))
  );

ALTER TABLE followup_joao_toque
  DROP CONSTRAINT IF EXISTS followup_joao_toque_dentro_da_cadencia;
ALTER TABLE followup_joao_toque
  ADD CONSTRAINT followup_joao_toque_dentro_da_cadencia CHECK (
       (cadencia = 'novo'        AND toque BETWEEN 1 AND 3)
    OR (cadencia = 'em_conversa' AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'proposta'    AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'reposicao'   AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'em_atencao'  AND toque = 1)
    OR (cadencia = 'kit'         AND toque BETWEEN 1 AND 2)
  );

ALTER TABLE followup_joao_ajustes
  DROP CONSTRAINT IF EXISTS followup_joao_ajustes_chave_valida;
ALTER TABLE followup_joao_ajustes
  ADD CONSTRAINT followup_joao_ajustes_chave_valida CHECK (
    chave IN ('teto_diario_disparos', 'adiamento_estoque_dias',
              'dias_sem_prospeccao_apos_venda')
  );

COMMIT;

NOTIFY pgrst, 'reload schema';

-- Conferencia (nao altera nada):
--   SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conname IN ('followup_joao_cadencia_par_valido',
--                      'followup_joao_toque_dentro_da_cadencia',
--                      'followup_joao_ajustes_chave_valida');
