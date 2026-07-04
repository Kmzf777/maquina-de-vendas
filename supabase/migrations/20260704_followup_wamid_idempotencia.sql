-- Idempotência dos follow-up jobs (auditoria 04/07): fecha a janela residual de envio
-- duplicado. Espelha broadcast_leads.wamid: o handler persiste o wamid do envio no job
-- ANTES de marcar terminal; se o worker morre entre o envio à Meta e o _mark_sent, a
-- crash-recovery vê o wamid e conclui o job como 'sent' (não reenvia) em vez de devolver
-- p/ 'pending' e disparar de novo.
ALTER TABLE public.follow_up_jobs ADD COLUMN IF NOT EXISTS wamid text;
