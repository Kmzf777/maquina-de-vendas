-- Onda 2 (09/07/2026): a cadência multi-touch de 4 toques (f54507c, 26/06) insere
-- sequences 1-4, mas o constraint original do design de 2 toques só aceitava (1,2).
-- Resultado: TODO agendamento de cadência falhou com 23514 desde 26/06 (zero jobs
-- 'standard' criados; logs "[FOLLOWUP] Erro ao inserir jobs ... sequence_check").
-- Relaxa para 1-9 (folga p/ toques extras como o nudge outbound D+1) mantendo a
-- proteção contra lixo (sequence negativa/zero/absurda).
-- IF EXISTS: homolog nunca teve o constraint (schema atrás do prod) — só o ADD vale lá.
ALTER TABLE follow_up_jobs DROP CONSTRAINT IF EXISTS follow_up_jobs_sequence_check;
ALTER TABLE follow_up_jobs ADD CONSTRAINT follow_up_jobs_sequence_check
  CHECK (sequence >= 1 AND sequence <= 9);
