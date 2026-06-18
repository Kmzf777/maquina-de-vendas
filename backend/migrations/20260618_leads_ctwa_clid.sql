-- 20260618_leads_ctwa_clid.sql
-- Adiciona `ctwa_clid`: o Click-to-WhatsApp click id que a Meta envia no objeto
-- `referral` aninhado na PRIMEIRA mensagem de um lead originado de um anúncio
-- "Clique para o WhatsApp" (Meta Ads / CTWA).
--
-- Motivo: este identificador é a base para disparar eventos de conversão de volta
-- para o Facebook via API de Conversões (CAPI), atribuindo a conversa/venda ao
-- clique no anúncio que a originou.
--
-- Captura no webhook: meta_parser.py extrai `message.referral.ctwa_clid` de forma
-- defensiva (mensagens orgânicas não têm `referral` → NULL). Persistido em
-- get_or_create_lead (first-touch, na criação) e atualizado em _register_lead quando
-- um novo clique chega (last-touch). Mensagens orgânicas NUNCA sobrescrevem um clid já
-- capturado.
--
-- Idempotente: seguro reaplicar. Aplicar em PROD e HOMOLOG (paridade de schema).

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS ctwa_clid text NULL;

COMMENT ON COLUMN leads.ctwa_clid IS
    'Click-to-WhatsApp click id (Meta Ads) extraído de message.referral.ctwa_clid na '
    'primeira mensagem vinda de um anúncio. Base para atribuição via API de Conversões '
    '(CAPI). NULL = lead orgânico ou origem não rastreada.';
