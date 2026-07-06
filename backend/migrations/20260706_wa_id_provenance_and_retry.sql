-- 20260706_wa_id_provenance_and_retry.sql
-- Blindagem da entrega outbound fria (descarte silencioso da Meta).
--
-- 1) leads.wa_id_confirmed_at: marca de PROCEDÊNCIA do wa_id. O wa_id só é endereço
--    autoritativo quando veio de um `from` real de inbound OU do `contacts[0].wa_id`
--    devolvido pela Meta no envio. resolve_send_target (modo estrito, usado no disparo
--    frio) só confia no wa_id se esta coluna OU last_customer_message_at estiver setada;
--    caso contrário, roteia para o phone de 13 dígitos (E.164 com o 9º dígito).
--
-- 2) broadcast_leads.delivery_retried: trava de idempotência para a dupla tentativa
--    estruturada. Quando reconcile_delivery_timeouts vira uma mensagem fria de
--    'accepted' para 'undelivered', o worker agenda ESTRITAMENTE UMA retentativa
--    alternando o 9º dígito, guardada por delivered_at IS NULL e por esta flag.
--
-- Idempotente: seguro reaplicar. Aplicar em PROD e HOMOLOG (paridade de schema).

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS wa_id_confirmed_at timestamptz NULL;

COMMENT ON COLUMN leads.wa_id_confirmed_at IS
    'Quando o wa_id foi confirmado por procedência real (from de inbound ou contacts[].wa_id '
    'da resposta de envio da Meta). NULL = wa_id sem procedência → disparo frio usa phone.';

ALTER TABLE broadcast_leads
    ADD COLUMN IF NOT EXISTS delivery_retried boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN broadcast_leads.delivery_retried IS
    'True após a única retentativa de entrega (alternando o 9º dígito) disparada quando o '
    'callback de status não confirmou a entrega no prazo. Impede múltiplas retentativas.';

-- Backfill de procedência: todo wa_id já existente que coexiste com um inbound real
-- (last_customer_message_at preenchido) é legítimo e passa a contar como confirmado,
-- preservando o comportamento quente após o gate estrito entrar em vigor.
UPDATE leads
   SET wa_id_confirmed_at = COALESCE(wa_id_confirmed_at, last_customer_message_at)
 WHERE wa_id IS NOT NULL
   AND last_customer_message_at IS NOT NULL
   AND wa_id_confirmed_at IS NULL;
