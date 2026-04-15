-- 005_token_usage.sql
-- Token usage tracking and model pricing tables

-- Model pricing configuration
CREATE TABLE IF NOT EXISTS model_pricing (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model text UNIQUE NOT NULL,
    price_per_input_token numeric NOT NULL,
    price_per_output_token numeric NOT NULL,
    updated_at timestamptz DEFAULT now()
);

-- Seed current OpenAI prices (per token, not per 1M)
-- gpt-4.1:      input $2.00/1M = 0.000002,  output $8.00/1M = 0.000008
-- gpt-4.1-mini: input $0.40/1M = 0.0000004, output $1.60/1M = 0.0000016
-- gpt-4o:       input $2.50/1M = 0.0000025, output $10.00/1M = 0.00001
-- whisper-1:    special — no per-token pricing, uses total_cost directly
INSERT INTO model_pricing (model, price_per_input_token, price_per_output_token) VALUES
    ('gpt-4.1',      0.000002,  0.000008),
    ('gpt-4.1-mini', 0.0000004, 0.0000016),
    ('gpt-4o',       0.0000025, 0.00001),
    ('whisper-1',    0,         0)
ON CONFLICT (model) DO NOTHING;

-- Token usage log
CREATE TABLE IF NOT EXISTS token_usage (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id),
    stage text NOT NULL,
    model text NOT NULL,
    call_type text NOT NULL,
    prompt_tokens integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    price_per_input_token numeric NOT NULL,
    price_per_output_token numeric NOT NULL,
    total_cost numeric NOT NULL,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_token_usage_lead_id ON token_usage(lead_id);
CREATE INDEX idx_token_usage_created_at ON token_usage(created_at);
CREATE INDEX idx_token_usage_stage ON token_usage(stage);
CREATE INDEX idx_token_usage_model ON token_usage(model);

ALTER PUBLICATION supabase_realtime ADD TABLE token_usage;
ALTER PUBLICATION supabase_realtime ADD TABLE model_pricing;
