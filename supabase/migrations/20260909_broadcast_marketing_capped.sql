-- 20260909_broadcast_marketing_capped.sql
-- Cap de marketing POR USUÁRIO da Meta (erro 131049) vira estado próprio da fila.
--
-- Incidente que a migration previne: até 09/09/2026 `grep -rn 131049 backend/app`
-- devolvia ZERO. O worker só conhecia 131026 (undeliverable). Um 131049 — "a Meta
-- segurou esta mensagem de marketing porque o usuário já recebeu marketing demais
-- hoje, de qualquer marca" — caía no ramo genérico e virava `status='failed'`, que
-- custa duas vezes: perde o lead na onda e, como `_template_dedup_guardrail`
-- (broadcast/worker.py) só conta envios BEM-SUCEDIDOS, ele ainda voltaria à fila
-- sem nunca ter sido tocado. A doc da Meta manda esperar >=24h; reenviar antes pode
-- render mais 24h de suspensão.
--
-- APLICAR À MÃO no Supabase (o deploy não roda migrations). Até ser aplicada, o
-- código degrada sozinho: o UPDATE do adiamento falha, `_defer_marketing_capped_lead`
-- devolve False e o lead segue no tratamento antigo (failed).

-- 1) Quando o lead adiado pode voltar para a fila -----------------------------
ALTER TABLE broadcast_leads
  ADD COLUMN IF NOT EXISTS retry_after timestamptz;

COMMENT ON COLUMN broadcast_leads.retry_after IS
  'Só para status=marketing_capped (Meta 131049): instante a partir do qual o worker '
  'pode devolver o lead para pending. Nunca antes de 24h do erro.';

-- Índice parcial: o varredor pergunta sempre "quem já venceu?", e a esmagadora
-- maioria das linhas tem retry_after NULL.
CREATE INDEX IF NOT EXISTS idx_broadcast_leads_retry_after
  ON broadcast_leads (broadcast_id, status, retry_after)
  WHERE retry_after IS NOT NULL;

-- 2) Desfazer o contador de falha ao adotar um 131049 do webhook --------------
-- O webhook de status (meta_router._handle_delivery_status) já chamou
-- increment_broadcast_failed antes de sabermos que era cap. Sem o inverso, a mesma
-- pessoa contaria como falha hoje e como envio amanhã — e o gate de entrega >=85%
-- por lote leria um número que não existe. GREATEST evita contador negativo se o
-- varredor rodar duas vezes sobre a mesma linha.
CREATE OR REPLACE FUNCTION decrement_broadcast_failed(broadcast_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE broadcasts
       SET failed = GREATEST(COALESCE(failed, 0) - 1, 0)
     WHERE id = broadcast_id_param;
END;
$$ LANGUAGE plpgsql;

-- 3) Desfazer TAMBÉM o contador de envio -------------------------------------
-- Achado na revisão de 09/09/2026: no caminho assíncrono (o provável) a Meta devolve
-- HTTP 200 + wamid e o worker já chamou increment_broadcast_sent ANTES de o webhook
-- reportar a retenção. Desfazer só `failed` deixava a mesma pessoa contada como
-- ENVIADA hoje e contada de novo quando o reenvio de amanhã desse certo — o total de
-- envios passava do total de leads e o gate de entrega >=85% lia um denominador que
-- não existe. GREATEST evita contador negativo se o varredor passar duas vezes.
CREATE OR REPLACE FUNCTION decrement_broadcast_sent(broadcast_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE broadcasts
       SET sent = GREATEST(COALESCE(sent, 0) - 1, 0)
     WHERE id = broadcast_id_param;
END;
$$ LANGUAGE plpgsql;
