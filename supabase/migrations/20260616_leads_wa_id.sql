-- 20260616_leads_wa_id.sql
-- Adiciona `wa_id`: o endereço WhatsApp REAL do contato (messages[].from da Meta),
-- usado como destino de envio.
--
-- Motivo: alguns números BR estão registrados no WhatsApp SEM o 9º dígito. O
-- `normalize_phone` injeta o 9 (12→13 dígitos) e grava em `leads.phone`; enviar para
-- essa forma faz a Meta ACEITAR (HTTP 200) mas FALHAR a entrega com erro 131026
-- "Message Undeliverable". O `wa_id` guarda o endereço exato que a Meta entrega.
--
-- Identidade/dedup do lead continua usando `phone` (normalizado). Apenas o ENVIO passa
-- a preferir `wa_id` quando preenchido. NULL → fallback para `phone`.
--
-- Idempotente: seguro reaplicar. Aplicar em PROD e HOMOLOG (paridade de schema).

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS wa_id text NULL;

COMMENT ON COLUMN leads.wa_id IS
    'Endereço WhatsApp real do contato (messages[].from da Meta). Destino de envio entregável — '
    'evita 131026 em números BR registrados sem o 9º dígito. NULL = usar phone como fallback.';
