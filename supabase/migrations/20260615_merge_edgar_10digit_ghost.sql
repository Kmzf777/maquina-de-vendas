-- 20260615_merge_edgar_10digit_ghost.sql
--
-- Remediação de dados pontual: lead-fantasma de 10 dígitos do Edgar Prospect BSB.
--
-- Contexto: a migração global 20260615_merge_duplicate_9digit_leads.sql só tratava
-- fantasmas de 12 dígitos (55 + DDD + 8, LIKE '55%'). O lead do Edgar importado em
-- 2026-05-08 ficou com phone='6199672905' (10 dígitos: DDD 61 + 8, SEM país 55 e
-- SEM 9º dígito), então escapou daquela remediação. O gêmeo canônico de 13 dígitos
-- '5561999672905' (criado pelo webhook inbound, que normaliza via normalize_phone)
-- concentra a qualificação real da Valéria e o handoff para o João.
--
-- Esta migração mescla o fantasma no canônico, espelhando o mesmo padrão da global:
-- move conversas/mensagens/deals/broadcast_leads e remove o fantasma.
--
-- Transform 10→13: '55' || substr(phone,1,2) || '9' || substr(phone,3)
--   '6199672905' -> '55' || '61' || '9' || '99672905' = '5561999672905'
--
-- Idempotente: escopo restrito ao phone '6199672905'. Após aplicada o fantasma não
-- existe mais, então a CTE _gm retorna vazia e todos os passos viram no-op.
-- Aplicada em PRODUÇÃO (tshmvxxxyxgctrdkqvam) via MCP em 2026-06-15.
-- Pendente aplicar em homolog (mosbwmsqfcwqdypucgtc), se o fantasma existir lá.

BEGIN;

-- ghost (10-digit) -> canonical (13-digit twin) mapping, escopo: phone do Edgar
CREATE TEMP TABLE _gm ON COMMIT DROP AS
SELECT g.id AS ghost_id, c.id AS canon_id
FROM leads g
JOIN leads c ON c.phone = '55' || substr(g.phone,1,2) || '9' || substr(g.phone,3)
WHERE g.phone = '6199672905';

-- ghost conversation -> canonical conversation on the same channel (NULL = no twin conv)
CREATE TEMP TABLE _cm ON COMMIT DROP AS
SELECT gc.id AS ghost_conv, gm.ghost_id, gm.canon_id, cc.id AS canon_conv
FROM _gm gm
JOIN conversations gc ON gc.lead_id = gm.ghost_id
LEFT JOIN LATERAL (
  SELECT id FROM conversations cc
  WHERE cc.lead_id = gm.canon_id AND cc.channel_id = gc.channel_id
  ORDER BY created_at LIMIT 1
) cc ON true;

-- 1) MERGE: move ghost-conversation messages into existing canonical conversation (same thread)
UPDATE messages m
SET conversation_id = cm.canon_conv, lead_id = cm.canon_id
FROM _cm cm
WHERE m.conversation_id = cm.ghost_conv AND cm.canon_conv IS NOT NULL;

-- 2) REPOINT: canonical has no conversation on that channel -> move the whole conversation
UPDATE conversations c
SET lead_id = cm.canon_id
FROM _cm cm
WHERE c.id = cm.ghost_conv AND cm.canon_conv IS NULL;
UPDATE messages m
SET lead_id = cm.canon_id
FROM _cm cm
WHERE m.conversation_id = cm.ghost_conv AND cm.canon_conv IS NULL;

-- 3) safety: any stray message still on the ghost lead
UPDATE messages m
SET lead_id = gm.canon_id
FROM _gm gm
WHERE m.lead_id = gm.ghost_id;

-- 4) delete now-empty ghost conversations (merge case only)
DELETE FROM conversations c
USING _cm cm
WHERE c.id = cm.ghost_conv AND cm.canon_conv IS NOT NULL;

-- 5) deals: move to canonical except where canonical already has a deal in the same pipeline
UPDATE deals d
SET lead_id = gm.canon_id
FROM _gm gm
WHERE d.lead_id = gm.ghost_id
  AND NOT EXISTS (
    SELECT 1 FROM deals cd
    WHERE cd.lead_id = gm.canon_id AND cd.pipeline_id IS NOT DISTINCT FROM d.pipeline_id
  );

-- 6) broadcast_leads: preserve disparo tracking (repoint where it does not collide)
UPDATE broadcast_leads bl
SET lead_id = gm.canon_id
FROM _gm gm
WHERE bl.lead_id = gm.ghost_id
  AND NOT EXISTS (
    SELECT 1 FROM broadcast_leads x WHERE x.lead_id = gm.canon_id AND x.broadcast_id = bl.broadcast_id
  );

-- 7) delete ghost lead (CASCADE clears any colliding deals/broadcast_leads left behind)
DELETE FROM leads l USING _gm gm WHERE l.id = gm.ghost_id;

COMMIT;
