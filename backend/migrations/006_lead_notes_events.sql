-- 006_lead_notes_events.sql
-- Lead notes (manual) and events (automatic activity log)

CREATE TABLE IF NOT EXISTS lead_notes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    author text NOT NULL,
    content text NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_lead_notes_lead_id ON lead_notes(lead_id);

CREATE TABLE IF NOT EXISTS lead_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    old_value text,
    new_value text,
    metadata jsonb,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_lead_events_lead_id ON lead_events(lead_id);

ALTER PUBLICATION supabase_realtime ADD TABLE lead_notes;
ALTER PUBLICATION supabase_realtime ADD TABLE lead_events;
