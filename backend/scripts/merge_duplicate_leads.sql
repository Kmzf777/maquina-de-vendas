-- merge_duplicate_leads.sql
--
-- Unifica leads duplicados causados pelo bug do 9º dígito WhatsApp.
-- Para cada par (lead 12-dígitos, lead 13-dígitos que representam a mesma pessoa):
--   - Determina o "pai" (quem tem dados em broadcast_leads ou messages; empate → mais antigo)
--   - Migra todos os registros dependentes do "filho" para o "pai"
--   - Deleta o "filho"
--   - Normaliza o phone do "pai" para 13 dígitos (caso tenha ficado com 12)
--
-- ╔══ COMO USAR ══════════════════════════════════════════════════════════════╗
-- ║  DRY RUN (sem commit — só para inspecionar o RAISE NOTICE):              ║
-- ║    BEGIN; [cole este script]; ROLLBACK;                                  ║
-- ║                                                                          ║
-- ║  EXECUTAR DE VERDADE:                                                    ║
-- ║    BEGIN; [cole este script]; COMMIT;                                    ║
-- ╚═══════════════════════════════════════════════════════════════════════════╝

DO $$
DECLARE
    r            RECORD;
    conv_conflict RECORD;
    v_deleted    INTEGER;
BEGIN
    FOR r IN (
        WITH raw_pairs AS (
            SELECT
                filho.id         AS d12_id,
                pai.id           AS d13_id,
                filho.created_at AS d12_created,
                pai.created_at   AS d13_created,
                (
                    EXISTS (SELECT 1 FROM broadcast_leads bl WHERE bl.lead_id = filho.id)
                    OR EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = filho.id)
                ) AS d12_has_data,
                (
                    EXISTS (SELECT 1 FROM broadcast_leads bl WHERE bl.lead_id = pai.id)
                    OR EXISTS (SELECT 1 FROM messages m WHERE m.lead_id = pai.id)
                ) AS d13_has_data
            FROM leads filho
            JOIN leads pai
              ON pai.phone = LEFT(filho.phone, 4) || '9' || RIGHT(filho.phone, 8)
            WHERE LENGTH(filho.phone) = 12
              AND filho.phone LIKE '55%'
        )
        SELECT
            -- filho_id = o que será DELETADO
            -- pai_id   = o que será MANTIDO
            CASE
                WHEN d12_has_data AND NOT d13_has_data THEN d13_id   -- 12-dígitos tem dados → mantém 12, deleta 13
                WHEN d13_has_data AND NOT d12_has_data THEN d12_id   -- 13-dígitos tem dados → mantém 13, deleta 12
                WHEN d12_created < d13_created         THEN d13_id   -- empate/nenhum: mantém o mais antigo (12)
                ELSE d12_id                                           -- fallback: mantém 13-dígitos
            END AS filho_id,
            CASE
                WHEN d12_has_data AND NOT d13_has_data THEN d12_id
                WHEN d13_has_data AND NOT d12_has_data THEN d13_id
                WHEN d12_created < d13_created         THEN d12_id
                ELSE d13_id
            END AS pai_id
        FROM raw_pairs
    )
    LOOP
        RAISE NOTICE 'Merge: filho=% → pai=%', r.filho_id, r.pai_id;

        -- ── Tipo 1: UPDATE direto (sem unique constraint em lead_id+X) ────────

        UPDATE messages           SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE deals              SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE lead_events        SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE lead_notes         SET lead_id = r.pai_id WHERE lead_id = r.filho_id;
        UPDATE token_usage        SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── conversations: UNIQUE(lead_id, channel_id) ────────────────────────
        -- Para cada conversa do filho que conflita com o pai (mesmo channel),
        -- reassina as mensagens da conversa do filho para a do pai, depois deleta.

        FOR conv_conflict IN (
            SELECT c_filho.id AS filho_conv_id, c_pai.id AS pai_conv_id
            FROM conversations c_filho
            JOIN conversations c_pai
              ON c_pai.lead_id    = r.pai_id
             AND c_pai.channel_id = c_filho.channel_id
            WHERE c_filho.lead_id = r.filho_id
        ) LOOP
            UPDATE messages
               SET conversation_id = conv_conflict.pai_conv_id
             WHERE conversation_id = conv_conflict.filho_conv_id;
            DELETE FROM conversations WHERE id = conv_conflict.filho_conv_id;
        END LOOP;
        -- Conversas restantes (sem conflito de channel) simplesmente migram
        UPDATE conversations SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── broadcast_leads: UNIQUE(broadcast_id, lead_id) ───────────────────

        DELETE FROM broadcast_leads
        WHERE lead_id = r.filho_id
          AND broadcast_id IN (
              SELECT broadcast_id FROM broadcast_leads WHERE lead_id = r.pai_id
          );
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        IF v_deleted > 0 THEN
            RAISE NOTICE '  broadcast_leads: % registro(s) do filho descartado(s) por conflito (pai já tem esse broadcast)', v_deleted;
        END IF;
        UPDATE broadcast_leads SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── cadence_enrollments: UNIQUE(cadence_id, lead_id) ─────────────────

        DELETE FROM cadence_enrollments
        WHERE lead_id = r.filho_id
          AND cadence_id IN (
              SELECT cadence_id FROM cadence_enrollments WHERE lead_id = r.pai_id
          );
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        IF v_deleted > 0 THEN
            RAISE NOTICE '  cadence_enrollments: % registro(s) do filho descartado(s) por conflito', v_deleted;
        END IF;
        UPDATE cadence_enrollments SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── lead_tags: PK (lead_id, tag_id) ──────────────────────────────────

        DELETE FROM lead_tags
        WHERE lead_id = r.filho_id
          AND tag_id IN (
              SELECT tag_id FROM lead_tags WHERE lead_id = r.pai_id
          );
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        IF v_deleted > 0 THEN
            RAISE NOTICE '  lead_tags: % registro(s) do filho descartado(s) por conflito', v_deleted;
        END IF;
        UPDATE lead_tags SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── cadence_state: UNIQUE em lead_id (uma linha por lead) ─────────────

        DELETE FROM cadence_state
        WHERE lead_id = r.filho_id
          AND EXISTS (SELECT 1 FROM cadence_state WHERE lead_id = r.pai_id);
        GET DIAGNOSTICS v_deleted = ROW_COUNT;
        IF v_deleted > 0 THEN
            RAISE NOTICE '  cadence_state: registro do filho descartado por conflito';
        END IF;
        UPDATE cadence_state SET lead_id = r.pai_id WHERE lead_id = r.filho_id;

        -- ── Deletar o lead filho ──────────────────────────────────────────────

        DELETE FROM leads WHERE id = r.filho_id;

        -- ── Normalizar phone do pai para 13 dígitos ───────────────────────────
        -- Necessário quando o pai era o lead 12-dígitos (o "mais rico")

        UPDATE leads
           SET phone = LEFT(phone, 4) || '9' || RIGHT(phone, 8)
         WHERE id = r.pai_id
           AND LENGTH(phone) = 12;

        RAISE NOTICE 'OK: filho=% deletado, pai=% preservado', r.filho_id, r.pai_id;
    END LOOP;
END $$;
