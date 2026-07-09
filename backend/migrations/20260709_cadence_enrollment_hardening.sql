-- 20260709_cadence_enrollment_hardening.sql
-- Endurece o motor de cadências (campaign_enrollments): claim atômico, idempotência
-- por nó, guarda de loop, índice único de matrícula ativa, e log de execução por nó.
-- Idempotente: seguro reaplicar. Aplicar em HOMOLOG e depois PROD (paridade de schema).

-- 1) Colunas de runtime na matrícula.
ALTER TABLE campaign_enrollments
    ADD COLUMN IF NOT EXISTS claimed_at        timestamptz NULL,
    ADD COLUMN IF NOT EXISTS last_sent_node_id uuid NULL,
    ADD COLUMN IF NOT EXISTS last_sent_wamid   text NULL,
    ADD COLUMN IF NOT EXISTS step_count        int NOT NULL DEFAULT 0;

COMMENT ON COLUMN campaign_enrollments.claimed_at IS
    'Instante do claim atômico do tick atual. NULL = livre. Stale (> 5min) = worker morreu.';
COMMENT ON COLUMN campaign_enrollments.last_sent_node_id IS
    'Nó cujo envio JÁ foi despachado à Meta neste passo (idempotência anti-reenvio no crash).';
COMMENT ON COLUMN campaign_enrollments.step_count IS
    'Nós executados por esta matrícula (guarda anti-loop). Estoura MAX_STEPS → failed.';

-- 2) DEDUP antes do índice único: cancela matrículas ativas/pausadas duplicadas
--    (mantém a mais recente por campaign_id+lead_id). Necessário senão o índice falha.
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY campaign_id, lead_id
               ORDER BY enrolled_at DESC
           ) AS rn
    FROM campaign_enrollments
    WHERE status IN ('active', 'paused')
)
UPDATE campaign_enrollments e
SET status = 'cancelled'
FROM ranked r
WHERE e.id = r.id AND r.rn > 1;

-- 3) Índice único parcial: no máx. 1 matrícula viva por (campanha, lead).
CREATE UNIQUE INDEX IF NOT EXISTS uq_campaign_enrollments_active
    ON campaign_enrollments (campaign_id, lead_id)
    WHERE status IN ('active', 'paused');

-- 4) Índice do claim/recovery (varredura de presos).
CREATE INDEX IF NOT EXISTS idx_campaign_enrollments_claimed
    ON campaign_enrollments (status, env_tag, claimed_at)
    WHERE status = 'active';

-- 5) Opt-in de fim de semana por campanha (default = comportamento atual: envia todo dia).
ALTER TABLE campaigns
    ADD COLUMN IF NOT EXISTS skip_weekends boolean NOT NULL DEFAULT false;

-- 6) Log de execução por nó (observabilidade estilo n8n).
CREATE TABLE IF NOT EXISTS campaign_execution_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    enrollment_id uuid NOT NULL REFERENCES campaign_enrollments(id) ON DELETE CASCADE,
    campaign_id   uuid NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id       uuid NULL REFERENCES leads(id) ON DELETE SET NULL,
    node_id       uuid NULL,
    node_type     text NULL,
    status        text NOT NULL,           -- 'done' | 'failed' | 'skipped'
    log           text NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_campaign_exec_log_campaign
    ON campaign_execution_log (campaign_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_campaign_exec_log_enrollment
    ON campaign_execution_log (enrollment_id, created_at DESC);

ALTER PUBLICATION supabase_realtime ADD TABLE campaign_execution_log;
