-- 007_multi_channel.sql
-- Multi-channel: agent_profiles, channels, conversations

CREATE TABLE IF NOT EXISTS agent_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    model text NOT NULL DEFAULT 'gpt-4.1',
    stages jsonb NOT NULL DEFAULT '{}',
    base_prompt text NOT NULL DEFAULT '',
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    phone text NOT NULL UNIQUE,
    provider text NOT NULL CHECK (provider IN ('meta_cloud', 'evolution')),
    provider_config jsonb NOT NULL DEFAULT '{}',
    agent_profile_id uuid REFERENCES agent_profiles(id) ON DELETE SET NULL,
    is_active boolean DEFAULT true,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_channels_phone ON channels(phone);
CREATE INDEX IF NOT EXISTS idx_channels_provider ON channels(provider);

CREATE TABLE IF NOT EXISTS conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    channel_id uuid REFERENCES channels(id) ON DELETE CASCADE,
    stage text DEFAULT 'secretaria',
    status text DEFAULT 'active',
    campaign_id uuid REFERENCES campaigns(id) ON DELETE SET NULL,
    last_msg_at timestamptz,
    created_at timestamptz DEFAULT now(),
    UNIQUE(lead_id, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_channel ON conversations(channel_id);
CREATE INDEX IF NOT EXISTS idx_conversations_lead ON conversations(lead_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);

DO $$ BEGIN ALTER TABLE messages ADD COLUMN conversation_id uuid REFERENCES conversations(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);

DO $$ BEGIN ALTER TABLE campaigns ADD COLUMN channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE templates ADD COLUMN channel_id uuid REFERENCES channels(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

DO $$ BEGIN ALTER TABLE leads ADD COLUMN metadata jsonb DEFAULT '{}';
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

ALTER PUBLICATION supabase_realtime ADD TABLE channels;
ALTER PUBLICATION supabase_realtime ADD TABLE agent_profiles;
ALTER PUBLICATION supabase_realtime ADD TABLE conversations;
