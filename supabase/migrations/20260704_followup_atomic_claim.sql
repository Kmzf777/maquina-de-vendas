-- Reivindicação atômica (atomic claim) dos follow-up jobs (auditoria 04/07).
-- Espelha o padrão de broadcast_leads: o worker reivindica o job (pending->processing)
-- com um UPDATE guardado por status, de modo que sob N réplicas apenas um worker
-- processa cada job — blindagem contra template/mensagem duplicados ao escalar.
--
-- 1) A coluna status passa a aceitar 'processing' (estado reivindicado) e
--    'awaiting_reopen' (já escrito por scheduler._mark_awaiting_reopen, mas AUSENTE do
--    CHECK antigo — qualquer disparo desse caminho violava a constraint).
-- 2) claimed_at registra o instante da reivindicação, base da crash-recovery que
--    devolve p/ 'pending' jobs presos em 'processing' há > 5min (worker morto).

ALTER TABLE public.follow_up_jobs DROP CONSTRAINT IF EXISTS follow_up_jobs_status_check;

ALTER TABLE public.follow_up_jobs ADD CONSTRAINT follow_up_jobs_status_check
  CHECK (status = ANY (ARRAY['pending', 'processing', 'sent', 'cancelled', 'awaiting_reopen']::text[]));

ALTER TABLE public.follow_up_jobs ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
