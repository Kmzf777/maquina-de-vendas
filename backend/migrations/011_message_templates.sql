-- 011_message_templates.sql
-- Tabela para templates de mensagem WhatsApp (Meta Cloud API)

CREATE TABLE IF NOT EXISTS message_templates (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id   uuid        NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    name         text        NOT NULL,
    language     text        NOT NULL DEFAULT 'pt_BR',
    requested_category text  NOT NULL,
    category     text        NOT NULL,
    components   jsonb       NOT NULL DEFAULT '[]',
    meta_template_id text,
    status       text        NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'pending_category_review', 'cancelled')),
    created_at   timestamptz NOT NULL DEFAULT now()
);
