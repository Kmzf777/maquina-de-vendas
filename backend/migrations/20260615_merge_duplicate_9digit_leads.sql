-- 20260615_merge_duplicate_9digit_leads.sql
--
-- Remediação de dados: leads brasileiros duplicados pelo 9º dígito.
--
-- Contexto: o import de CSV do frontend inseria telefones de 12 dígitos
-- (55 + DDD + 8) SEM injetar o 9º dígito do celular, enquanto o webhook de
-- inbound usa backend/app/leads/service.py:normalize_phone (que injeta o 9).
-- Resultado: o disparo saía para um lead-fantasma de 12 dígitos e a resposta
-- do cliente caía no lead canônico de 13 dígitos → disparo e resposta em
-- conversas separadas ("Mensagem original não disponível" + histórico
-- fragmentado). A prevenção no código está no commit que adiciona
-- frontend/src/lib/phone.ts (normalizePhoneBR) e o aplica no modal e na rota
-- POST /api/leads/import.
--
-- Esta migração consolida o passado:
--   1. Mescla cada lead-fantasma de 12 dígitos no seu gêmeo canônico de 13:
--      move messages (lead_id + conversation_id), deals e broadcast_leads.
--   2. Remove os leads-fantasma (CASCADE limpa o que sobrar).
--   3. Normaliza in-place os 12 dígitos que NÃO têm gêmeo.
--   4. Faz backfill de quoted_message_id nas respostas órfãs.
--
-- Idempotente: após aplicada, não há leads de 12 dígitos, então os passos
-- viram no-op. Aplicada em PRODUÇÃO (tshmvxxxyxgctrdkqvam) via MCP em
-- 2026-06-15. Pendente aplicar em homolog (mosbwmsqfcwqdypucgtc).
--
-- Resultado em prod: 146 fantasmas mesclados, 216 normalizados in-place,
-- 9 conversas mescladas + 3 reapontadas, 144 deals movidos (2 descartados por
-- colisão de funil), 12 broadcast_leads reapontados, 30 quotes resolvidos.

BEGIN;

-- ghost (12-digit) -> canonical (13-digit twin) mapping
CREATE TEMP TABLE _ghost_map ON COMMIT DROP AS
SELECT g.id AS ghost_id, c.id AS canon_id
FROM leads g
JOIN leads c ON c.phone = substr(g.phone,1,4)||'9'||substr(g.phone,5)
WHERE length(g.phone)=12 AND g.phone LIKE '55%';

-- ghost conversation -> canonical conversation on the same channel (NULL = no twin conv)
CREATE TEMP TABLE _conv_map ON COMMIT DROP AS
SELECT gc.id AS ghost_conv, gm.ghost_id, gm.canon_id, cc.id AS canon_conv
FROM _ghost_map gm
JOIN conversations gc ON gc.lead_id = gm.ghost_id
LEFT JOIN LATERAL (
  SELECT id FROM conversations cc
  WHERE cc.lead_id = gm.canon_id AND cc.channel_id = gc.channel_id
  ORDER BY created_at LIMIT 1
) cc ON true;

-- 1) MERGE: move ghost-conversation messages into the existing canonical conversation (same thread)
UPDATE messages m
SET conversation_id = cm.canon_conv, lead_id = cm.canon_id
FROM _conv_map cm
WHERE m.conversation_id = cm.ghost_conv AND cm.canon_conv IS NOT NULL;

-- 2) REPOINT: canonical has no conversation on that channel -> move the whole conversation to canonical lead
UPDATE conversations c
SET lead_id = cm.canon_id
FROM _conv_map cm
WHERE c.id = cm.ghost_conv AND cm.canon_conv IS NULL;
UPDATE messages m
SET lead_id = cm.canon_id
FROM _conv_map cm
WHERE m.conversation_id = cm.ghost_conv AND cm.canon_conv IS NULL;

-- 3) safety: any stray message still on a ghost lead
UPDATE messages m
SET lead_id = gm.canon_id
FROM _ghost_map gm
WHERE m.lead_id = gm.ghost_id;

-- 4) delete now-empty ghost conversations (merge case)
DELETE FROM conversations c
USING _conv_map cm
WHERE c.id = cm.ghost_conv AND cm.canon_conv IS NOT NULL;

-- 5) deals: move to canonical except where canonical already has a deal in the same pipeline
UPDATE deals d
SET lead_id = gm.canon_id
FROM _ghost_map gm
WHERE d.lead_id = gm.ghost_id
  AND NOT EXISTS (
    SELECT 1 FROM deals cd
    WHERE cd.lead_id = gm.canon_id AND cd.pipeline_id IS NOT DISTINCT FROM d.pipeline_id
  );

-- 6) broadcast_leads: preserve disparo tracking (repoint where it does not collide on broadcast_id+lead_id)
UPDATE broadcast_leads bl
SET lead_id = gm.canon_id
FROM _ghost_map gm
WHERE bl.lead_id = gm.ghost_id
  AND NOT EXISTS (
    SELECT 1 FROM broadcast_leads x WHERE x.lead_id = gm.canon_id AND x.broadcast_id = bl.broadcast_id
  );

-- 7) delete ghost leads (CASCADE clears any colliding deals/broadcast_leads left behind)
DELETE FROM leads l USING _ghost_map gm WHERE l.id = gm.ghost_id;

-- 8) in-place normalize remaining 12-digit leads (no twin -> safe)
UPDATE leads l
SET phone = substr(l.phone,1,4)||'9'||substr(l.phone,5)
WHERE length(l.phone)=12 AND l.phone LIKE '55%'
  AND NOT EXISTS (SELECT 1 FROM leads c WHERE c.phone = substr(l.phone,1,4)||'9'||substr(l.phone,5));

-- 9) backfill quoted_message_id on orphan replies (global by wamid)
UPDATE messages r
SET quoted_message_id = o.id
FROM messages o
WHERE r.quoted_message_id IS NULL
  AND r.quoted_wamid IS NOT NULL
  AND o.wamid = r.quoted_wamid;

COMMIT;
