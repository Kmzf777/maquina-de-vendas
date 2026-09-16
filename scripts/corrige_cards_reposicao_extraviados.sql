-- scripts/corrige_cards_reposicao_extraviados.sql
--
-- ⛔ NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO. Escreve em PRODUÇÃO, no
--    FUNIL DE TRABALHO DO VENDEDOR (João). Nenhum agente de IA deve rodar este
--    arquivo. Ele existe para ser LIDO, revisado, autorizado e só então
--    aplicado à mão por um humano: primeiro o bloco "SELECT DE CONFERÊNCIA —
--    ANTES" sozinho, e só depois de ler o resultado o bloco BEGIN…COMMIT.
--
-- ── O QUE ACONTECEU ──────────────────────────────────────────────────────────
-- `ensure_reposicao_deal` (backend/app/leads/reposicao.py) cria um card
-- title='Reposição' toda vez que um deal do lead fecha em 'fechado_ganho', no
-- funil de Reposição que corresponde ao funil de ORIGEM da venda. Antes do fix
-- de 10/09/2026 (reposicao.py:16-29), a resolução de pipeline caía CALADA no
-- fallback "primeiro pipeline por order_index" de `create_deal`
-- (backend/app/leads/service.py) sempre que o nome do funil não batia — e não
-- bateu duas vezes seguidas (09/09 e 10/09/2026).
--
-- Resultado: 19 cards de reposição automática, criados entre 07/08 e
-- 04/09/2026, pararam no funil "Valéria - Importação Leads Frios" (owner NULL)
-- em vez do funil de Reposição do João — 18 na etapa "Frio", 1 na etapa
-- "Respondeu". Invisíveis para quem venderia: oportunidade de recompra de
-- cliente que ACABOU de comprar, sem ninguém na mesa.
--
-- Reconferido em produção em 16/09/2026: o total continua 19. O corretivo
-- anterior (scripts/recuperacao/corrigir_deals_reposicao.sql, escrito em
-- 09/09/2026) nunca foi aplicado — e, de qualquer forma, só sabia mover para
-- UM destino (João - Reposição Atacado): foi escrito antes de existir o
-- segundo funil de reposição (Private Label, criado em 10/09/2026 — ver
-- reposicao.py:27-29) e teria movido para o funil errado qualquer card cuja
-- venda de origem fosse na verdade do Private Label. Este arquivo substitui
-- aquele: resolve o destino de CADA card pelo funil de origem da venda do
-- PRÓPRIO lead, em vez de uma constante única.
--
-- ── QUANTOS CARDS ────────────────────────────────────────────────────────────
-- 19 cards, de 19 leads distintos (mesma contagem de 09/09/2026 — nada mudou
-- nesse meio-tempo). O bloco de conferência abaixo reconfere o número na hora
-- de aplicar; se tiver mudado, leia por que antes de continuar.
--
-- ── POR QUE NÃO É MIGRATION ──────────────────────────────────────────────────
-- Não cria nem altera estrutura de tabela — não pertence ao histórico
-- permanente de schema que os arquivos em `supabase/migrations/` registram (e
-- que, como este script, também são aplicados à mão: o GitHub Actions só sobe
-- imagem, nunca roda SQL). Isto é uma correção pontual de DADO, escopada aos
-- cards deste incidente específico e descartável depois de aplicada uma única
-- vez — não faz parte da evolução permanente do schema.
--
-- ── COMO OS CARDS SÃO IDENTIFICADOS ─────────────────────────────────────────
-- `title = 'Reposição'` é o literal exato gravado por reposicao.py
-- (`title="Reposição"`) — não é um título que se digita à mão em outro
-- contexto. Cumulativamente:
--   · pipeline_id = funil frio (a9487d77-…)     — só quem está no lugar errado
--   · closed_at IS NULL                          — card fechado é histórico
--   · assigned_to IS NULL                        — ninguém assumiu o card
--   · category IS NULL AND coalesce(value,0)=0   — create_deal não preenche
--     nenhum dos dois; um card editado por humano teria
--   · updated_at - created_at < 1 minuto          — prova de que ninguém mexeu
-- (mesmos critérios de scripts/recuperacao/corrigir_deals_reposicao.sql,
-- confirmados contra os mesmos 19 cards em 09/09/2026.)
--
-- ── COMO O DESTINO DE CADA CARD É CALCULADO ─────────────────────────────────
-- Espelha o mapa de `reposicao_pipeline_para` (backend/app/leads/reposicao.py):
--   João - Atacado (9706a14a-…)       → João - Reposição Atacado (79e35e6b-…)
--   João - Private Label (24fb6ce8-…) → João - Reposição Private Label
--   (9c027143-…)
--
-- O card em si não guarda de qual venda ele nasceu — não há FK para isso na
-- tabela `deals`. A origem é reconstruída a partir das vendas FECHADAS (etapa
-- key='fechado_ganho', o mesmo critério que `deal_is_won` usa em
-- reposicao.py) do MESMO lead. Quando essas vendas mapeiam para um ÚNICO
-- funil de destino, é esse o destino do card. Quando o lead tem vendas
-- fechadas em MAIS DE UM funil de origem diferente, ou em NENHUM funil
-- mapeado, a origem não é segura — o card fica como está, listado no SELECT
-- de conferência com o motivo. Nunca chuta.
--
-- A etapa de destino é resolvida por `key = 'novo'` (rotulada "Cliente
-- Ativo" nos dois funis de reposição — key confirmada em
-- supabase/migrations/20260910_contrato_etapas_joao.sql) — nunca por rótulo,
-- que é editável na tela. Se o funil de destino não tiver etapa key='novo' no
-- momento em que isto rodar, o card também fica de fora (mesma guarda), em
-- vez de nascer em uma etapa qualquer.
--
-- `entered_stage_at` é renovado para now() explicitamente no UPDATE. É o
-- relógio que `get_deals_stage_stagnant`
-- (supabase/migrations/20260904_esteiras_vendedor.sql) lê para decidir se um
-- card está parado numa etapa há tempo demais — mover sem renovar faria um
-- card que acabou de chegar parecer parado há semanas, elegível para a
-- esteira imediatamente. (Existe também um trigger em `deals` que renova este
-- campo ao detectar troca de stage_id; setar aqui explicitamente não depende
-- só do trigger continuar existindo.)
--
-- ── O QUE ESTE ARQUIVO NÃO FAZ ──────────────────────────────────────────────
-- Não cria deal nenhum — os 19 já existem, só no lugar errado. Não mexe em
-- `leads`, `sales`, `conversion_events` nem em tag alguma. Não toca a coluna
-- legada `deals.stage` (congelada — a verdade da etapa é stage_id/key). Não
-- decide o destino de um card cuja origem não é inequívoca: deixa como está.
--
-- ── EFEITO COLATERAL ESPERADO ───────────────────────────────────────────────
-- `updated_at = now()` sobe os cards corrigidos para o topo do Kanban do João
-- (ordenado por updated_at desc) — intencional: um card com data de semanas
-- atrás no meio de centenas de cards abertos é um card que ele nunca vê.
--
-- ── COMO APLICAR ─────────────────────────────────────────────────────────────
-- SQL puro, sem meta-comando de psql — roda direto no editor SQL do Supabase.
--   1. Rode o bloco "SELECT DE CONFERÊNCIA — ANTES" sozinho e leia o
--      resultado.
--   2. Confira: 19 linhas. Toda linha com observação 'ok' tem destino
--      calculado; qualquer outra fica de fora do UPDATE de propósito — não é
--      bug deste script, é o "nunca chuta" em ação. Investigue antes de
--      prosseguir se o total não for 19.
--   3. Rode o bloco BEGIN…COMMIT inteiro de uma vez.
--   4. Rode o bloco "SELECT DE CONFERÊNCIA — DEPOIS" e confira os números.

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — ANTES   (rodar sozinho, ler o resultado antes do BEGIN)
-- ===========================================================================
WITH alvo AS (
    SELECT d.id AS deal_id, d.lead_id, d.pipeline_id, d.stage_id, d.created_at
      FROM deals d
     WHERE d.title = 'Reposição'
       AND d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid  -- Valéria - Importação Leads Frios
       AND d.closed_at IS NULL
       AND d.assigned_to IS NULL
       AND d.category IS NULL
       AND coalesce(d.value, 0) = 0
       AND d.updated_at - d.created_at < interval '1 minute'
),
vendas AS (
    -- Toda venda FECHADA (key='fechado_ganho') dos leads-alvo, mapeada para o
    -- funil de reposição de destino — espelha reposicao_pipeline_para().
    SELECT DISTINCT
           w.lead_id,
           CASE w.pipeline_id
               WHEN '9706a14a-3d9a-413b-bceb-26838fc2cc45'::uuid THEN '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid  -- Atacado -> Reposição Atacado
               WHEN '24fb6ce8-6b7b-4612-970d-8debb8c041b7'::uuid THEN '9c027143-72f6-42d6-861f-a494ba5bbb4f'::uuid  -- Private Label -> Reposição Private Label
               ELSE NULL
           END AS destino_pipeline_id
      FROM deals w
      JOIN pipeline_stages ws ON ws.id = w.stage_id
     WHERE ws.key = 'fechado_ganho'
       AND w.lead_id IN (SELECT lead_id FROM alvo)
),
destino_por_lead AS (
    -- Só resolve quando a origem é INEQUÍVOCA: exatamente 1 destino mapeado
    -- distinto (não-nulo) entre as vendas do lead. Lead com vendas em dois
    -- funis de origem diferentes, ou sem nenhuma venda mapeada, fica sem
    -- destino de propósito — "nunca chutar" é a regra.
    SELECT lead_id, min(destino_pipeline_id) AS destino_pipeline_id
      FROM vendas
     WHERE destino_pipeline_id IS NOT NULL
     GROUP BY lead_id
    HAVING count(DISTINCT destino_pipeline_id) = 1
)
SELECT a.deal_id,
       l.name                                    AS lead,
       l.phone                                    AS telefone,
       p_atual.name                                AS funil_atual,
       s_atual.label                               AS etapa_atual,
       p_destino.name                              AS destino_funil,
       s_destino.label                             AS destino_etapa,
       CASE
         WHEN dl.destino_pipeline_id IS NULL THEN 'SEM ORIGEM SEGURA: deixar como esta'
         WHEN s_destino.id IS NULL           THEN 'FUNIL DESTINO SEM ETAPA key=novo: deixar como esta'
         ELSE 'ok'
       END                                        AS observacao
  FROM alvo a
  JOIN leads l ON l.id = a.lead_id
  LEFT JOIN destino_por_lead dl ON dl.lead_id = a.lead_id
  LEFT JOIN pipelines p_atual ON p_atual.id = a.pipeline_id
  LEFT JOIN pipeline_stages s_atual ON s_atual.id = a.stage_id
  LEFT JOIN pipelines p_destino ON p_destino.id = dl.destino_pipeline_id
  LEFT JOIN pipeline_stages s_destino
         ON s_destino.pipeline_id = dl.destino_pipeline_id
        AND s_destino.key = 'novo'
 ORDER BY observacao DESC, a.created_at;

-- Resumo esperado em 16/09/2026: 19 cards, 19 leads distintos. Se
-- `leads_com_outro_card_aberto_no_destino` > 0, PARE: mover criaria um
-- segundo card aberto para o mesmo lead no funil de destino, exatamente o
-- duplicado que `dedupe_open` existe para evitar.
SELECT count(*)                                          AS cards_no_alvo,
       count(DISTINCT d.lead_id)                          AS leads_distintos,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM deals o
          WHERE o.lead_id = d.lead_id
            AND o.id <> d.id
            AND o.closed_at IS NULL
            AND o.pipeline_id IN ('79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid,
                                   '9c027143-72f6-42d6-861f-a494ba5bbb4f'::uuid)
       ))                                                  AS leads_com_outro_card_aberto_no_destino
  FROM deals d
 WHERE d.title = 'Reposição'
   AND d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid
   AND d.closed_at IS NULL
   AND d.assigned_to IS NULL
   AND d.category IS NULL
   AND coalesce(d.value, 0) = 0
   AND d.updated_at - d.created_at < interval '1 minute';

-- ===========================================================================
-- O MOVIMENTO
-- ===========================================================================
BEGIN;

-- Alvo + destino calculado, congelados numa temporária: o UPDATE muda
-- pipeline_id, que é parte do próprio critério de seleção — sem congelar, uma
-- conferência posterior dentro da mesma transação já veria conjunto vazio ou
-- errado. Linhas com destino_stage_id NULL (origem ambígua/desconhecida, ou
-- funil de destino sem etapa 'novo') ficam na tabela mas são excluídas do
-- UPDATE abaixo — aparecem aqui só para a guarda de contagem enxergar todo o
-- alvo, resolvido ou não.
CREATE TEMP TABLE cards_extraviados_calc ON COMMIT DROP AS
WITH alvo AS (
    SELECT d.id AS deal_id, d.lead_id
      FROM deals d
     WHERE d.title = 'Reposição'
       AND d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid  -- Valéria - Importação Leads Frios
       AND d.closed_at IS NULL
       AND d.assigned_to IS NULL
       AND d.category IS NULL
       AND coalesce(d.value, 0) = 0
       AND d.updated_at - d.created_at < interval '1 minute'
),
vendas AS (
    SELECT DISTINCT
           w.lead_id,
           CASE w.pipeline_id
               WHEN '9706a14a-3d9a-413b-bceb-26838fc2cc45'::uuid THEN '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
               WHEN '24fb6ce8-6b7b-4612-970d-8debb8c041b7'::uuid THEN '9c027143-72f6-42d6-861f-a494ba5bbb4f'::uuid
               ELSE NULL
           END AS destino_pipeline_id
      FROM deals w
      JOIN pipeline_stages ws ON ws.id = w.stage_id
     WHERE ws.key = 'fechado_ganho'
       AND w.lead_id IN (SELECT lead_id FROM alvo)
),
destino_por_lead AS (
    SELECT lead_id, min(destino_pipeline_id) AS destino_pipeline_id
      FROM vendas
     WHERE destino_pipeline_id IS NOT NULL
     GROUP BY lead_id
    HAVING count(DISTINCT destino_pipeline_id) = 1
)
SELECT a.deal_id,
       a.lead_id,
       dl.destino_pipeline_id,
       ns.id AS destino_stage_id
  FROM alvo a
  LEFT JOIN destino_por_lead dl ON dl.lead_id = a.lead_id
  LEFT JOIN pipeline_stages ns
         ON ns.pipeline_id = dl.destino_pipeline_id
        AND ns.key = 'novo';

-- Guarda de sanidade. Aborta a transação inteira (nenhuma linha é tocada) se
-- o alvo não bater com o esperado, ou se nada puder ser resolvido com
-- segurança — nunca move "pela metade" sem avisar.
DO $$
DECLARE
  total     integer;
  resolvido integer;
BEGIN
  SELECT count(*), count(destino_stage_id)
    INTO total, resolvido
    FROM cards_extraviados_calc;

  IF total = 0 THEN
    RAISE EXCEPTION 'nenhum card extraviado encontrado -- ou ja foi corrigido, ou o WHERE mudou';
  END IF;
  IF total > 50 THEN
    RAISE EXCEPTION 'alvo grande demais (%): revise o WHERE antes de continuar', total;
  END IF;
  IF resolvido = 0 THEN
    RAISE EXCEPTION 'nenhum card teve origem resolvida com seguranca -- releia o SELECT de conferencia antes de investigar por que';
  END IF;

  RAISE NOTICE 'cards no alvo: % | resolvidos com origem segura: % | deixados como estao: %',
               total, resolvido, total - resolvido;
END $$;

UPDATE deals d
   SET pipeline_id      = c.destino_pipeline_id,
       stage_id         = c.destino_stage_id,
       entered_stage_at = now(),
       updated_at       = now()
  FROM cards_extraviados_calc c
 WHERE d.id = c.deal_id
   AND c.destino_stage_id IS NOT NULL;

COMMIT;

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — DEPOIS
-- ===========================================================================
-- `extraviados_restantes` só é > 0 se algum card ficou sem origem segura (ou
-- sem etapa 'novo' no destino) — esperado quando o SELECT de conferência
-- ANTES já mostrava observação diferente de 'ok'. `movidos_para_reposicao` é
-- o resto dos 19.
SELECT count(*) FILTER (
         WHERE d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid
       ) AS extraviados_restantes,
       count(*) FILTER (
         WHERE d.pipeline_id IN ('79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid,
                                  '9c027143-72f6-42d6-861f-a494ba5bbb4f'::uuid)
       ) AS movidos_para_reposicao
  FROM deals d
 WHERE d.title = 'Reposição'
   AND d.closed_at IS NULL;

-- Agrupa por l.id, NÃO por l.name: nomes repetidos entre leads distintos são
-- reais neste banco (dois leads chamados "Edson" já apareceram na mesma
-- conferência em 09/09/2026) — agrupar por nome acusaria um duplicado que não
-- existe.
SELECT l.id AS lead_id, l.name, count(*) AS cards_abertos
  FROM deals d
  JOIN leads l ON l.id = d.lead_id
 WHERE d.closed_at IS NULL
   AND d.pipeline_id IN ('79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid,
                          '9c027143-72f6-42d6-861f-a494ba5bbb4f'::uuid)
 GROUP BY l.id, l.name
HAVING count(*) > 1
 ORDER BY 3 DESC;
-- Esperado: ZERO linhas.

-- ===========================================================================
-- ROLLBACK (plano B — não roda junto)
-- ===========================================================================
-- Depois do movimento, os cards corrigidos são identificáveis por
-- title='Reposição' num dos dois funis de destino. Restaurar caso a caso pelo
-- dump do bloco ANTES (deal_id + funil_atual + etapa_atual) é mais seguro que
-- um UPDATE em bloco, porque os 19 têm DUAS etapas de origem diferentes
-- (Frio e Respondeu) e o dump é a única cópia dessa distinção depois que o
-- UPDATE roda:
--
--   UPDATE deals d SET pipeline_id = v.funil_atual::uuid,
--                       stage_id    = v.etapa_atual_id::uuid,
--                       updated_at  = now()
--     FROM (VALUES ('<deal_id>', '<funil_atual_id>', '<etapa_atual_id>'))
--            AS v(deal_id, funil_atual, etapa_atual_id)
--    WHERE d.id = v.deal_id::uuid;
