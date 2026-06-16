-- =============================================================================
-- REMEDIAÇÃO: Reativação da IA (Valéria) para leads órfãos do canal Valéria
-- =============================================================================
-- Contexto: leads que enviaram mensagem recente (janela 24h da Meta aberta) mas
-- ficaram sem resposta porque estavam com ai_enabled=false (passados ao humano).
-- O usuário autorizou reativar a IA SOMENTE no canal da Valéria e agendar a
-- resposta da Valéria para HOJE 2026-06-16 09:00 America/Sao_Paulo (= 12:00 UTC).
--
-- ⚠️  NÃO EXECUTAR sem autorização expressa. Rodar dentro de uma transação.
-- ⚠️  Requer que o handler job_type='ai_reengage' (backend/app/follow_up/
--     scheduler.py) já esteja em PRODUÇÃO antes do fire_at — senão o worker
--     não sabe processar o job. Coordene o deploy (push master) antes das 09h.
--
-- Decisões aprovadas pelo usuário (2026-06-16):
--   • Disparo: HOJE 06-16 09:00 SP  → fire_at = '2026-06-16 12:00:00+00'
--   • Escopo: EXCLUI os 2 leads com human_control=true (Edgar, Marcos) → 8 leads
--   • Canal Valéria: 6e51629d-f095-4a4e-9e26-46a8da225a89
--   • Opt-out = ai_enabled=false + deal no pipeline Blacklist 8988e852-... (excluído)
-- =============================================================================

BEGIN;

-- CTE única que materializa EXATAMENTE os leads-alvo, replicando o filtro da
-- auditoria. Reusada tanto no UPDATE quanto no INSERT para garantir consistência.
WITH valeria_conv AS (
    SELECT c.id AS conversation_id, c.lead_id
    FROM conversations c
    WHERE c.channel_id = '6e51629d-f095-4a4e-9e26-46a8da225a89'::uuid
),
last_msg AS (
    SELECT DISTINCT ON (m.conversation_id)
        m.conversation_id, m.role, m.created_at
    FROM messages m
    JOIN valeria_conv vc ON vc.conversation_id = m.conversation_id
    ORDER BY m.conversation_id, m.created_at DESC
),
blacklisted AS (
    SELECT DISTINCT lead_id
    FROM deals
    WHERE pipeline_id = '8988e852-2836-4add-b023-4db4d6cd0e6e'
),
targets AS (
    SELECT vc.lead_id, vc.conversation_id
    FROM last_msg lm
    JOIN valeria_conv vc ON vc.conversation_id = lm.conversation_id
    JOIN leads l         ON l.id = vc.lead_id
    LEFT JOIN blacklisted bl ON bl.lead_id = l.id
    WHERE lm.role = 'user'                                   -- última msg é inbound
      AND lm.created_at >= now() - interval '24 hours'       -- janela Meta aberta
      AND l.ai_enabled = false                               -- IA desativada
      AND bl.lead_id IS NULL                                 -- não está em opt-out/Blacklist
      AND l.human_control = false                            -- EXCLUI Edgar e Marcos
)

-- Persiste os alvos numa tabela temporária para reuso entre os dois comandos.
SELECT lead_id, conversation_id
INTO TEMP TABLE _reengage_targets
FROM targets;

-- Sanidade: aborta se a contagem fugir do esperado (esperado = 8).
DO $$
DECLARE n int;
BEGIN
    SELECT count(*) INTO n FROM _reengage_targets;
    RAISE NOTICE 'Leads-alvo encontrados: %', n;
    IF n <> 8 THEN
        RAISE EXCEPTION 'Contagem inesperada de alvos (% != 8) — abortando por seguranca. Revise a auditoria antes de prosseguir.', n;
    END IF;
END $$;

-- AÇÃO 1: reativa a IA. human_control já é false em todos (filtrado), mas
-- reafirmamos para satisfazer a regra "remova flags de human_control".
UPDATE leads l
SET ai_enabled   = true,
    human_control = false
FROM _reengage_targets t
WHERE l.id = t.lead_id;

-- AÇÃO 2: enfileira 1 job ai_reengage por lead, disparando 06-16 09:00 SP.
-- env_tag='production' é o que o worker de prod filtra (get_due_followups).
-- ON CONFLICT não se aplica (sem unique key); idempotência vem do guard de
-- não-reinserção abaixo: só insere se ainda não houver job ai_reengage pending.
INSERT INTO follow_up_jobs
    (conversation_id, lead_id, channel_id, sequence, fire_at, status, env_tag, job_type, metadata)
SELECT
    t.conversation_id,
    t.lead_id,
    '6e51629d-f095-4a4e-9e26-46a8da225a89'::uuid,
    1,
    '2026-06-16 12:00:00+00'::timestamptz,        -- 09:00 America/Sao_Paulo
    'pending',
    'production',
    'ai_reengage',
    jsonb_build_object('source', 'reativacao_manual_2026-06-16', 'authorized_by', 'usuario')
FROM _reengage_targets t
WHERE NOT EXISTS (
    SELECT 1 FROM follow_up_jobs j
    WHERE j.lead_id = t.lead_id
      AND j.job_type = 'ai_reengage'
      AND j.status = 'pending'
);

-- Conferência final antes do COMMIT (revise o output):
SELECT l.name, l.phone, l.ai_enabled, l.human_control,
       j.fire_at, j.status, j.job_type
FROM _reengage_targets t
JOIN leads l ON l.id = t.lead_id
LEFT JOIN follow_up_jobs j
       ON j.lead_id = t.lead_id AND j.job_type = 'ai_reengage' AND j.status = 'pending'
ORDER BY l.name;

DROP TABLE _reengage_targets;

-- ⚠️  Revise o SELECT acima. Se estiver correto: COMMIT;  senão: ROLLBACK;
-- COMMIT;
ROLLBACK;
