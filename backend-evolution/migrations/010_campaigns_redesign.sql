-- 010_campaigns_redesign.sql
-- Split campaigns into broadcasts + cadences

-- 1. Create broadcasts table
CREATE TABLE IF NOT EXISTS broadcasts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    channel_id uuid REFERENCES channels(id),
    template_name text NOT NULL,
    template_preset_id uuid,
    template_variables jsonb DEFAULT '{}',
    total_leads int DEFAULT 0,
    sent int DEFAULT 0,
    failed int DEFAULT 0,
    delivered int DEFAULT 0,
    status text NOT NULL DEFAULT 'draft',
    scheduled_at timestamptz,
    send_interval_min int DEFAULT 3,
    send_interval_max int DEFAULT 8,
    cadence_id uuid,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON broadcasts(status);

-- 2. Create broadcast_leads table
CREATE TABLE IF NOT EXISTS broadcast_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    broadcast_id uuid NOT NULL REFERENCES broadcasts(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending',
    sent_at timestamptz,
    error_message text,
    UNIQUE(broadcast_id, lead_id)
);

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_broadcast ON broadcast_leads(broadcast_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_leads_status ON broadcast_leads(broadcast_id, status);

-- 3. Create cadences table
CREATE TABLE IF NOT EXISTS cadences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    description text,
    target_type text NOT NULL DEFAULT 'manual',
    target_stage text,
    stagnation_days int,
    send_start_hour int DEFAULT 7,
    send_end_hour int DEFAULT 18,
    cooldown_hours int DEFAULT 48,
    max_messages int DEFAULT 5,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cadences_status ON cadences(status);
CREATE INDEX IF NOT EXISTS idx_cadences_target ON cadences(target_type, target_stage);

-- 4. Add FK from broadcasts to cadences (after cadences exists)
ALTER TABLE broadcasts ADD CONSTRAINT fk_broadcasts_cadence
    FOREIGN KEY (cadence_id) REFERENCES cadences(id) ON DELETE SET NULL;

-- 5. Create new cadence_steps table (replaces old one)
-- Drop old cadence_steps
DROP TABLE IF EXISTS cadence_steps CASCADE;

CREATE TABLE cadence_steps (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence_id uuid NOT NULL REFERENCES cadences(id) ON DELETE CASCADE,
    step_order int NOT NULL,
    message_text text NOT NULL,
    delay_days int DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE(cadence_id, step_order)
);

CREATE INDEX IF NOT EXISTS idx_cadence_steps_cadence ON cadence_steps(cadence_id);

-- 6. Create cadence_enrollments table (replaces cadence_state)
CREATE TABLE IF NOT EXISTS cadence_enrollments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence_id uuid NOT NULL REFERENCES cadences(id) ON DELETE CASCADE,
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    deal_id uuid REFERENCES deals(id) ON DELETE SET NULL,
    broadcast_id uuid REFERENCES broadcasts(id) ON DELETE SET NULL,
    current_step int DEFAULT 0,
    status text NOT NULL DEFAULT 'active',
    total_messages_sent int DEFAULT 0,
    next_send_at timestamptz,
    cooldown_until timestamptz,
    responded_at timestamptz,
    enrolled_at timestamptz DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(cadence_id, lead_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_cadence ON cadence_enrollments(cadence_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_lead ON cadence_enrollments(lead_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_status ON cadence_enrollments(status);
CREATE INDEX IF NOT EXISTS idx_enrollments_next_send ON cadence_enrollments(status, next_send_at);

-- 7. Create template_presets table
CREATE TABLE IF NOT EXISTS template_presets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    template_name text NOT NULL,
    variables jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

-- 8. Migrate data from campaigns -> broadcasts + cadences
DO $$
DECLARE
    c RECORD;
    new_cadence_id uuid;
    new_broadcast_id uuid;
BEGIN
    FOR c IN SELECT * FROM campaigns LOOP
        -- Create cadence from campaign's cadence config
        INSERT INTO cadences (name, description, target_type, send_start_hour, send_end_hour, cooldown_hours, max_messages, status)
        VALUES (
            c.name || ' - Cadencia',
            'Migrado da campanha: ' || c.name,
            'manual',
            COALESCE(c.cadence_send_start_hour, 7),
            COALESCE(c.cadence_send_end_hour, 18),
            COALESCE(c.cadence_cooldown_hours, 48),
            COALESCE(c.cadence_max_messages, 8),
            CASE c.status WHEN 'completed' THEN 'archived' WHEN 'paused' THEN 'paused' ELSE 'active' END
        )
        RETURNING id INTO new_cadence_id;

        -- Create broadcast from campaign's send config
        INSERT INTO broadcasts (name, template_name, template_variables, total_leads, sent, failed, status, send_interval_min, send_interval_max, cadence_id, created_at)
        VALUES (
            c.name,
            c.template_name,
            COALESCE(c.template_params, '{}'),
            c.total_leads,
            c.sent,
            c.failed,
            c.status,
            COALESCE(c.send_interval_min, 3),
            COALESCE(c.send_interval_max, 8),
            new_cadence_id,
            c.created_at
        )
        RETURNING id INTO new_broadcast_id;

        -- Migrate leads.campaign_id -> broadcast_leads
        INSERT INTO broadcast_leads (broadcast_id, lead_id, status)
        SELECT new_broadcast_id, id,
            CASE status
                WHEN 'imported' THEN 'pending'
                WHEN 'template_sent' THEN 'sent'
                WHEN 'failed' THEN 'failed'
                ELSE 'sent'
            END
        FROM leads
        WHERE campaign_id = c.id;

        -- Migrate cadence_state -> cadence_enrollments
        INSERT INTO cadence_enrollments (cadence_id, lead_id, broadcast_id, current_step, status, total_messages_sent, next_send_at, cooldown_until, responded_at, enrolled_at)
        SELECT new_cadence_id, cs.lead_id, new_broadcast_id, cs.current_step,
            CASE cs.status
                WHEN 'cooled' THEN 'completed'
                ELSE cs.status
            END,
            cs.total_messages_sent, cs.next_send_at, cs.cooldown_until, cs.responded_at, cs.created_at
        FROM cadence_state cs
        WHERE cs.campaign_id = c.id;
    END LOOP;
END $$;

-- 9. Drop old tables
DROP TABLE IF EXISTS cadence_state CASCADE;
DROP TABLE IF EXISTS campaigns CASCADE;

-- 10. Remove campaign_id from leads
ALTER TABLE leads DROP COLUMN IF EXISTS campaign_id;

-- 11. Enable realtime
ALTER PUBLICATION supabase_realtime ADD TABLE broadcasts;
ALTER PUBLICATION supabase_realtime ADD TABLE cadences;
ALTER PUBLICATION supabase_realtime ADD TABLE cadence_enrollments;
ALTER PUBLICATION supabase_realtime ADD TABLE broadcast_leads;
