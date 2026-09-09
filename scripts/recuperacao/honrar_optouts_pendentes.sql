-- scripts/recuperacao/honrar_optouts_pendentes.sql
--
-- ⛔ NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO. Escreve em PRODUÇÃO.
--    Nenhum agente de IA deve rodar este arquivo. Ele existe para ser LIDO,
--    revisado, autorizado e então aplicado à mão por um humano.
--
-- ── O QUE ELE FAZ ───────────────────────────────────────────────────────────
-- Honra retroativamente os opt-outs que o CRM recebeu e nunca aplicou: pessoas
-- que TOCARAM no botão de saída de um template e continuam com opt_out = false,
-- ou seja, continuam elegíveis para a próxima campanha.
--
-- ── POR QUE ELES EXISTEM (o incidente) ──────────────────────────────────────
-- backend/app/webhook/meta_parser.py:138-154, na master até 09/09/2026, lia
-- `button.text` e DESCARTAVA `button.payload`, forçando `parsed_type = "text"`.
-- Downstream ficava impossível distinguir um clique de uma digitação — e não
-- existe, em lugar nenhum do webhook, código que aplique opt-out a partir de um
-- clique. `registrar_optout` (agent/tools.py:830) só roda se a IA decidir chamá-la,
-- e nestes leads a IA nem rodava. Resultado: o clique virou uma linha em `messages`
-- com message_type NULL e metadata NULL, e mais nada.
--
-- ── NÚMEROS DE HOJE (medidos em 09/09/2026, SQL de leitura em produção) ─────
--   'Nao tenho interesse' ....... 64 cliques · 56 leads · 12 já com opt_out ·
--                                 52 cliques pendentes em 47 leads
--   'Parar Mensagens' ........... 21 cliques · 21 leads · 0 pendentes
--   'Parar mensagens' ............ 1 clique  ·  1 lead  · 1 pendente
--   ------------------------------------------------------------------------
--   TOTAL A CORRIGIR ............ 53 cliques em 48 LEADS DISTINTOS
--
--   Impacto colateral desses 48 leads:
--     · 75 deals hoje fora da Blacklist, dos quais 71 seriam movidos — os outros
--       4 pertencem ao lead preservado abaixo   (bloco 2)
--     ·  0 follow_up_jobs pendentes      (bloco 3 — hoje é no-op, mas o espelho
--                                         precisa existir: amanhã pode não ser)
--     · 17 leads com ai_enabled = true   (bloco 1)
--     ·  2 leads com venda registrada, e 1 deles ("Pão Com Arte") VENDEU
--       R$ 2.545,50 em 04/09/2026, DEPOIS de ter clicado em 29/07 — ver bloco 2.
--     ·  1 dos 48 cliques não tem `wamid` gravado (122 de 1.200 mensagens de
--       broadcast foram persistidas com wamid NULL); a evidência dele fica com
--       message_id e content, sem o id da Meta. É o que existe.
--
-- ── FRONTEIRA ENTRE O DEVER LEGAL E O JUÍZO COMERCIAL ───────────────────────
-- O bloco 1 é obrigação: LGPD art. 18 §2 (direito de oposição) vale para os 48,
-- sem exceção, inclusive para quem comprou depois. `opt_out` governa quem entra
-- em DISPARO; ele não impede o vendedor de responder dentro de uma conversa que o
-- próprio cliente abrir.
-- Já o bloco 2 (mandar os deals para a Blacklist) é decisão comercial, e nela a
-- exceção é obrigatória: mover para a Blacklist o card de um cliente que faturou
-- R$ 2.545,50 trinta e sete dias DEPOIS do clique tiraria da mesa do João uma
-- conta viva. Os leads com venda posterior ao clique ficam de fora e viram
-- conferência manual.
--
-- ── O QUE ESTE ARQUIVO NÃO FAZ ──────────────────────────────────────────────
-- Não escreve mensagem de sistema nem observação no lead (o texto de um clique de
-- meses atrás seria ruído no histórico da conversa); a auditoria fica em
-- leads.opt_out_evidence. Não mexe em `broadcasts`/`broadcast_leads` — disparo
-- passado é histórico e não se reescreve.
--
-- ── PRÉ-REQUISITO ───────────────────────────────────────────────────────────
-- supabase/migrations/20260909_recuperacao_stages_optout.sql precisa estar
-- APLICADA: sem opt_out_at / opt_out_channel / opt_out_evidence este arquivo
-- morre no primeiro UPDATE (e é bom que morra — gravar 48 booleanos sem evidência
-- é justamente o estado que não se defende na ANPD).

\set ON_ERROR_STOP on

-- ===========================================================================
-- CONFERÊNCIA — ANTES
-- ===========================================================================
\echo '=== ANTES ==='
SELECT count(*)                                        AS cliques_pendentes,
       count(DISTINCT l.id)                            AS leads_pendentes,
       count(DISTINCT l.id) FILTER (WHERE l.ai_enabled) AS com_ai_ligada
  FROM messages m
  JOIN leads l ON l.id = m.lead_id
 WHERE m.role = 'user'
   AND m.content IN ('Nao tenho interesse', 'Não tenho interesse',
                     'Parar mensagens', 'Parar Mensagens')
   AND l.opt_out = false;

BEGIN;

-- Os leads-alvo e a evidência de cada um, congelados numa temporária: os três
-- blocos abaixo precisam ver EXATAMENTE o mesmo conjunto, e o bloco 1 muda
-- `opt_out`, que é o próprio critério de seleção. Sem congelar, os blocos 2 e 3
-- rodariam sobre um conjunto vazio.
CREATE TEMP TABLE optouts_pendentes ON COMMIT DROP AS
SELECT l.id                                   AS lead_id,
       l.phone                                AS phone,
       min(m.created_at)                      AS clicou_em,
       count(*)                               AS cliques,
       (array_agg(m.content     ORDER BY m.created_at))[1] AS rotulo,
       (array_agg(m.id::text    ORDER BY m.created_at))[1] AS message_id,
       (array_agg(m.wamid       ORDER BY m.created_at))[1] AS wamid
  FROM messages m
  JOIN leads l ON l.id = m.lead_id
 WHERE m.role = 'user'
   AND m.content IN ('Nao tenho interesse', 'Não tenho interesse',
                     'Parar mensagens', 'Parar Mensagens')
   AND l.opt_out = false
 GROUP BY l.id, l.phone;

-- Guarda de sanidade. Em 09/09/2026 são 48 leads; o teto de 200 não é o número
-- esperado, é o limite acima do qual alguma coisa está errada com o WHERE (ex.:
-- um rótulo novo entrou na lista e passou a casar meio banco). Abortar aqui
-- desfaz a transação inteira.
DO $$
DECLARE alvo integer;
BEGIN
  SELECT count(*) INTO alvo FROM optouts_pendentes;
  IF alvo = 0 THEN
    RAISE EXCEPTION 'nenhum opt-out pendente — ou já foi aplicado, ou o WHERE mudou';
  END IF;
  IF alvo > 200 THEN
    RAISE EXCEPTION 'alvo grande demais (%): revise o WHERE antes de continuar', alvo;
  END IF;
  RAISE NOTICE 'leads a corrigir: %', alvo;
END $$;

-- ===========================================================================
-- 1. O opt-out em si + a evidência   (OBRIGAÇÃO LEGAL — vale para todos)
-- ===========================================================================
-- `opt_out_at` é o instante do PRIMEIRO clique, não o de agora: é quando a pessoa
-- pediu. Registrar "agora" fabricaria uma data que faz o atraso de até 2 meses
-- desaparecer do registro — o oposto do que a evidência serve para provar.
--
-- `ai_enabled = false` espelha o que todo chamador de apply_optout_side_effects
-- já faz junto com o opt-out (leads/service.py:1594-1616): a função em si não
-- desliga a IA, quem chama é que desliga.
--
-- leads não tem coluna updated_at (conferido em 09/09/2026) — nada a tocar aqui.
UPDATE leads l
   SET opt_out          = true,
       ai_enabled       = false,
       opt_out_at       = p.clicou_em,
       opt_out_channel  = 'whatsapp_button',
       opt_out_evidence = jsonb_build_object(
           'source',       'honrar_optouts_pendentes.sql',
           'aplicado_em',  now(),
           'button_label', p.rotulo,
           'clicked_at',   p.clicou_em,
           'cliques',      p.cliques,
           'message_id',   p.message_id,
           'wamid',        p.wamid,
           'nota',         'Clique de botão em template não honrado na época: '
                        || 'meta_parser.py:138-154 descartava button.payload e '
                        || 'forçava parsed_type="text". Backfill de 09/09/2026.'
       )
  FROM optouts_pendentes p
 WHERE l.id = p.lead_id;

-- ===========================================================================
-- 2. Deals para a Blacklist   (JUÍZO COMERCIAL — com exceção)
-- ===========================================================================
-- Espelha move_lead_deals_to_blacklist (leads/service.py:1458-1500). Os UUIDs são
-- os mesmos constantes de :1454-1455 — Blacklist é um pipeline real com uma etapa
-- só, e mudá-los aqui e lá em separado é como o funil se parte.
--
-- A exceção: quem registrou venda DEPOIS do clique é cliente ativo. Em 09/09/2026
-- é 1 lead. O opt-out dele continua valendo (bloco 1); o card dele continua no
-- funil do João.
--
-- Diferença deliberada em relação à função: ela CRIA um deal de rastreio para
-- lead sem deal nenhum. Aqui não criamos — inventar 48 cards num backfill
-- histórico só enche a Blacklist de ruído. A evidência do bloco 1 já rastreia.
UPDATE deals d
   SET pipeline_id = '8988e852-2836-4add-b023-4db4d6cd0e6e'::uuid,
       stage_id    = 'fbace13d-d788-423a-879d-ee468dff29ed'::uuid,
       updated_at  = now()
  FROM optouts_pendentes p
 WHERE d.lead_id = p.lead_id
   AND d.pipeline_id <> '8988e852-2836-4add-b023-4db4d6cd0e6e'::uuid
   AND NOT EXISTS (
     SELECT 1 FROM sales s
      WHERE s.lead_id = p.lead_id
        AND s.sold_at > p.clicou_em
   );

-- ===========================================================================
-- 3. Follow-ups pendentes   (espelho de cancel_followups_by_phone)
-- ===========================================================================
-- Parada terminal: cancela TAMBÉM `ai_scheduled_return`, exatamente como
-- apply_optout_side_effects faz com preserve_scheduled_return=False
-- (follow_up/service.py:342-353). Quem pediu para sair não pode receber um
-- retorno proativo depois.
--
-- Hoje isto afeta 0 linhas. Está aqui porque o arquivo pode ser aplicado semanas
-- depois de escrito, e um no-op silencioso é melhor do que uma cadência viva
-- sobrevivendo a um opt-out.
UPDATE follow_up_jobs f
   SET status        = 'cancelled',
       cancel_reason = 'optout'
  FROM conversations c
 WHERE c.id = f.conversation_id
   AND c.lead_id IN (SELECT lead_id FROM optouts_pendentes)
   AND f.status = 'pending';

COMMIT;

-- ===========================================================================
-- CONFERÊNCIA — DEPOIS
-- ===========================================================================
-- 70 leads clicaram num desses rótulos; 22 já tinham opt_out, 48 não tinham.
-- Esperado depois: ainda_pendentes = 0 · honrados_por_botao = 48 ·
-- opt_out_sem_data = 22 (os antigos, que ficam sem evidência mesmo — não se
-- inventa data para eles).
\echo '=== DEPOIS ==='
SELECT count(*) FILTER (WHERE NOT q.opt_out)                          AS ainda_pendentes,
       count(*) FILTER (WHERE q.opt_out
                          AND q.opt_out_channel = 'whatsapp_button')  AS honrados_por_botao,
       count(*) FILTER (WHERE q.opt_out AND q.opt_out_at IS NULL)     AS opt_out_sem_data
  FROM (SELECT DISTINCT l.id, l.opt_out, l.opt_out_at, l.opt_out_channel
          FROM messages m JOIN leads l ON l.id = m.lead_id
         WHERE m.role = 'user'
           AND m.content IN ('Nao tenho interesse', 'Não tenho interesse',
                             'Parar mensagens', 'Parar Mensagens')) q;

\echo '--- leads preservados fora da Blacklist (venda posterior ao clique) ---'
SELECT l.name, l.opt_out_at::date AS clicou, max(s.sold_at)::date AS ultima_venda
  FROM leads l
  JOIN sales s ON s.lead_id = l.id
 WHERE l.opt_out_channel = 'whatsapp_button'
   AND s.sold_at > l.opt_out_at
 GROUP BY l.name, l.opt_out_at
 ORDER BY 3 DESC;
