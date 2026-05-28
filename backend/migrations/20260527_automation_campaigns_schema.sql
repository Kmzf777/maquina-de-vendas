-- 20260527_automation_campaigns_schema.sql
-- Cria as tabelas do sistema de automação de campanhas (campaigns, campaign_nodes,
-- campaign_enrollments). A tabela `campaigns` antiga foi derrubada pela migration
-- 010_campaigns_redesign.sql e substituída por broadcasts/cadences. Este schema é
-- distinto: representa fluxos de automação baseados em gatilhos (triggers).

-- 1. campaigns ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaigns (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    description text,
    status      text NOT NULL DEFAULT 'draft',
    env_tag     text NOT NULL DEFAULT 'production',
    created_at  timestamptz DEFAULT now(),
    updated_at  timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_campaigns_status_env ON campaigns(status, env_tag);

-- 2. campaign_nodes ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaign_nodes (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id  uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    type         text NOT NULL,
    config       jsonb NOT NULL DEFAULT '{}',
    position_x   int DEFAULT 0,
    position_y   int DEFAULT 0,
    -- Navegação do fluxo
    next_node_id uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
    yes_node_id  uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
    no_node_id   uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_campaign_nodes_campaign ON campaign_nodes(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_nodes_type ON campaign_nodes(campaign_id, type);

-- 3. campaign_enrollments ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS campaign_enrollments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id     uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id         uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    deal_id         uuid REFERENCES deals(id) ON DELETE SET NULL,
    current_node_id uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL,
    next_execute_at timestamptz,
    status          text NOT NULL DEFAULT 'active',
    env_tag         text NOT NULL DEFAULT 'production',
    enrolled_at     timestamptz DEFAULT now(),
    completed_at    timestamptz,
    paused_at       timestamptz
);

CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_campaign ON campaign_enrollments(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_lead ON campaign_enrollments(lead_id);
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_due
    ON campaign_enrollments(status, env_tag, next_execute_at)
    WHERE status = 'active';

-- 4. Habilita Realtime para que o frontend possa observar mudanças
ALTER PUBLICATION supabase_realtime ADD TABLE campaigns;
ALTER PUBLICATION supabase_realtime ADD TABLE campaign_nodes;
ALTER PUBLICATION supabase_realtime ADD TABLE campaign_enrollments;
