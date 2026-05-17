-- 20260517_broadcast_atomic_counters_and_dedup_leads.sql
--
-- 1. Funções atômicas para incrementar contadores de broadcasts (substituem
--    o padrão read-modify-write que causa race conditions com múltiplos workers).
--
-- 2. Consolidação de leads duplicados: quando o mesmo número existe em formato
--    de 12 e 13 dígitos, mantém o de 13 dígitos (canônico) e migra todas as
--    referências do de 12 dígitos para ele antes de deletar o duplicado.
--
-- COMO RODAR:
--   Execute via Supabase SQL Editor ou psql.
--   Idempotente: pode rodar múltiplas vezes sem efeitos colaterais.
--
-- VERIFICAÇÃO ANTES DE RODAR (parte 2):
--   SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
--
-- VERIFICAÇÃO DEPOIS:
--   SELECT COUNT(*) FROM leads WHERE LENGTH(phone) = 12 AND phone LIKE '55%';
--   -- Deve retornar 0.

-- ─────────────────────────────────────────────────────────────
-- Parte 1: Funções atômicas de contadores
-- ─────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION increment_broadcast_sent(broadcast_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE broadcasts SET sent = COALESCE(sent, 0) + 1 WHERE id = broadcast_id_param;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_broadcast_failed(broadcast_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE broadcasts SET failed = COALESCE(failed, 0) + 1 WHERE id = broadcast_id_param;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION increment_broadcast_delivered(broadcast_id_param uuid)
RETURNS void AS $$
BEGIN
    UPDATE broadcasts SET delivered = COALESCE(delivered, 0) + 1 WHERE id = broadcast_id_param;
END;
$$ LANGUAGE plpgsql;

-- ─────────────────────────────────────────────────────────────
-- Parte 2: Consolidação de leads duplicados (12 dígitos → 13 dígitos)
--
-- Para cada lead com 12 dígitos (55 + DDD + 8 dígitos), verifica se existe
-- um lead com 13 dígitos (55 + DDD + 9 + 8 dígitos) para o mesmo número.
-- Se existir:
--   - Migra broadcast_leads, cadence_enrollments, conversations, messages,
--     deals para o lead canônico (13 dígitos).
--   - Deleta o lead duplicado (12 dígitos).
-- Se não existir:
--   - Injeta o 9° dígito no lead existente (normalização simples).
-- ─────────────────────────────────────────────────────────────

DO $$
DECLARE
    rec RECORD;
    canonical_phone text;
    canonical_id    uuid;
BEGIN
    FOR rec IN
        SELECT id, phone
        FROM leads
        WHERE LENGTH(phone) = 12
          AND phone LIKE '55%'
        ORDER BY created_at
    LOOP
        canonical_phone := LEFT(rec.phone, 4) || '9' || RIGHT(rec.phone, 8);

        SELECT id INTO canonical_id
        FROM leads
        WHERE phone = canonical_phone;

        IF canonical_id IS NOT NULL AND canonical_id != rec.id THEN
            -- Duplicate pair found: migrate all references to canonical_id, then delete legacy row.

            -- broadcast_leads: skip if (broadcast_id, canonical_id) already exists (UNIQUE constraint).
            UPDATE broadcast_leads
            SET lead_id = canonical_id
            WHERE lead_id = rec.id
              AND NOT EXISTS (
                SELECT 1 FROM broadcast_leads bl2
                WHERE bl2.broadcast_id = broadcast_leads.broadcast_id
                  AND bl2.lead_id = canonical_id
              );
            DELETE FROM broadcast_leads WHERE lead_id = rec.id;

            -- cadence_enrollments
            UPDATE cadence_enrollments
            SET lead_id = canonical_id
            WHERE lead_id = rec.id
              AND NOT EXISTS (
                SELECT 1 FROM cadence_enrollments ce2
                WHERE ce2.cadence_id = cadence_enrollments.cadence_id
                  AND ce2.lead_id = canonical_id
              );
            DELETE FROM cadence_enrollments WHERE lead_id = rec.id;

            -- conversations
            UPDATE conversations
            SET lead_id = canonical_id
            WHERE lead_id = rec.id
              AND NOT EXISTS (
                SELECT 1 FROM conversations c2
                WHERE c2.channel_id = conversations.channel_id
                  AND c2.lead_id = canonical_id
              );
            DELETE FROM conversations WHERE lead_id = rec.id;

            -- messages
            UPDATE messages SET lead_id = canonical_id WHERE lead_id = rec.id;

            -- deals
            UPDATE deals SET lead_id = canonical_id WHERE lead_id = rec.id;

            -- follow_ups (if table exists)
            IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'follow_ups') THEN
                UPDATE follow_ups SET lead_id = canonical_id WHERE lead_id = rec.id;
            END IF;

            DELETE FROM leads WHERE id = rec.id;

            RAISE NOTICE 'Merged duplicate: % → % (id % → %)', rec.phone, canonical_phone, rec.id, canonical_id;

        ELSIF canonical_id IS NULL THEN
            -- No 13-digit counterpart exists — just inject the 9th digit.
            UPDATE leads SET phone = canonical_phone WHERE id = rec.id;
            RAISE NOTICE 'Normalized: % → %', rec.phone, canonical_phone;
        END IF;
        -- If canonical_id = rec.id, the lead already IS the canonical one (shouldn't happen for 12-digit).
    END LOOP;
END $$;
