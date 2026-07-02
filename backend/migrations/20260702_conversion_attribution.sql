-- 20260702_conversion_attribution.sql
-- Atribuição de conversões de anúncios (multi-etapa) — lado CRM.
--
-- 1) Marca, POR ETAPA de pipeline, qual evento de conversão de anúncio ela representa e o
--    valor a reportar. NULL = etapa não dispara conversão.
-- 2) Tabela de auditoria + DEDUP dos eventos disparados (único por deal+evento), fonte de
--    verdade p/ Meta CAPI (direto) e p/ a Planilha do Google (Data Manager).
--
-- Idempotente: seguro reaplicar. Aplicar em HOMOLOG e depois PROD (paridade de schema).

ALTER TABLE pipeline_stages
    ADD COLUMN IF NOT EXISTS conversion_event text NULL,
    ADD COLUMN IF NOT EXISTS conversion_value numeric NULL;

COMMENT ON COLUMN pipeline_stages.conversion_event IS
    'Evento de conversão de anúncio desta etapa: lead|qualified|opportunity|purchase. NULL = não dispara.';
COMMENT ON COLUMN pipeline_stages.conversion_value IS
    'Valor fixo (BRL) reportado ao entrar nesta etapa. Ignorado em purchase (usa valor real da venda).';

CREATE TABLE IF NOT EXISTS conversion_events (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id      uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    deal_id      uuid NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    event        text NOT NULL,
    value        numeric NULL,
    currency     text NOT NULL DEFAULT 'BRL',
    platform     text NOT NULL DEFAULT 'both',
    gclid        text NULL,
    ctwa_clid    text NULL,
    sent_meta    boolean NOT NULL DEFAULT false,
    sheet_synced boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversion_events_deal_event_unique UNIQUE (deal_id, event)
);

COMMENT ON TABLE conversion_events IS
    'Auditoria + dedup de eventos de conversão de anúncio. UNIQUE(deal_id,event) evita redisparo.';
