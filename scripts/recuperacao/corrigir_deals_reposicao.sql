-- scripts/recuperacao/corrigir_deals_reposicao.sql
--
-- ⛔ NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO. Escreve em PRODUÇÃO, e o que
--    ele mexe é o FUNIL DE TRABALHO DO VENDEDOR. Nenhum agente de IA deve rodar
--    este arquivo. Ele existe para ser LIDO, revisado, autorizado e então aplicado
--    à mão por um humano, no SQL editor do Supabase.
--
-- ── O QUE ELE FAZ ───────────────────────────────────────────────────────────
-- Move para o funil "João - Reposição" (etapa "Novo") os deals de reposição
-- automática que nasceram no funil errado. Uma linha por deal, nada mais: não
-- cria deal, não mexe em leads, não mexe em sales, não escreve mensagem nem
-- observação.
--
-- ── QUANTAS LINHAS AFETA ────────────────────────────────────────────────────
-- **19 deals, de 19 leads distintos** (medido por leitura em produção em
-- 09/09/2026; o `\echo '=== ANTES ==='` reconfere na hora de aplicar).
--   · criados entre 07/08/2026 e 04/09/2026
--   · 18 na etapa "Frio" e 1 na etapa "Respondeu" do funil frio
--   · TODOS abertos (closed_at IS NULL)
--   · NENHUM dos 19 leads tem outro deal aberto — ou seja, mover não cria card
--     duplicado para ninguém. Os outros deals desses leads (26 no total) estão
--     todos em "Fechado Ganho": são justamente as vendas que dispararam a criação.
--
-- ── POR QUE ELES EXISTEM (o incidente) ──────────────────────────────────────
-- backend/app/leads/reposicao.py definia REPOSICAO_PIPELINE_NAME = "Reposição -
-- João"; o funil real se chama "João - Reposição". `create_deal`
-- (leads/service.py:1129-1147) resolve o pipeline por `.eq("name", ...)` e, não
-- achando, cai CALADO no fallback "primeiro pipeline por order_index" — e SEIS
-- funis empatam em order_index = 0. O sorteio caiu sempre em "Valeria -
-- Importação Leads Frios".
--
-- Nada estourou: `ensure_reposicao_deal` é fail-soft por desenho e `create_deal`
-- CRIOU o deal — só no lugar errado. E o lugar errado é invisível para o João: a
-- visibilidade é por `pipelines.owner_user_id`, e "João - Reposição" é dele
-- (1c3c78ed-…, joao@cafecanastra.com) enquanto o funil frio tem owner NULL.
-- Resultado: 19 oportunidades de recompra de clientes que ACABARAM de comprar,
-- criadas automaticamente, nenhuma delas na mesa de quem venderia.
--
-- A constante já foi corrigida em `backend/app/leads/reposicao.py` e está travada
-- por teste (backend/tests/test_recuperacao_migration_2026_09_09.py). Isso estanca
-- o sangramento; NÃO remedia os 19 que já estão lá. É o que este arquivo faz.
--
-- ── COMO OS 19 SÃO IDENTIFICADOS (e por que o filtro é seguro) ──────────────
-- `title = 'Reposição'` é o literal de reposicao.py:42 (`title="Reposição"`) e
-- NÃO é um título que alguém digite: em 09/09/2026 o banco inteiro tem 19 deals
-- com título casando `ILIKE 'reposi%'`, e os 19 são exatamente estes. Os cards
-- que o João criou à mão nesse funil se chamam 'repor', 'Repor', '1 venda',
-- 'querido - Revenda' — nenhum colide.
--
-- O filtro ainda exige, cumulativamente:
--   · pipeline_id = funil frio  (não tocar em nada que já esteja no lugar certo)
--   · closed_at IS NULL         (deal fechado é histórico; não se reescreve)
--   · assigned_to IS NULL       (ninguém assumiu o card)
--   · category IS NULL AND coalesce(value,0) = 0   (create_deal não preenche
--                                nenhum dos dois; um card editado teria)
--   · updated_at - created_at < 1 minuto  (prova de que nenhum humano mexeu:
--                                nos 19, o maior delta é de 7,6 s — e é o único
--                                card em "Respondeu", movido pelo reflexo
--                                automático `advance_deal_on_reply`
--                                (leads/service.py:1243-1283), não por gente.)
-- Os cinco últimos critérios são redundantes HOJE (os 19 satisfazem todos). Estão
-- aqui porque este arquivo pode ser aplicado semanas depois de escrito: se nesse
-- meio-tempo o João assumir um desses cards, ele sai do alvo sozinho, e a guarda
-- de contagem avisa que o número mudou.
--
-- ── PARA ONDE VÃO ───────────────────────────────────────────────────────────
-- "João - Reposição" (79e35e6b-…), etapa "Novo" (07b4a308-…). Não é escolha
-- estética: é EXATAMENTE o destino que `create_deal` teria resolvido com a
-- constante certa — pipeline por nome, e depois a primeira etapa não-protegida por
-- order_index, que nesse funil é "Novo" (order_index 0). A guarda de sanidade
-- abaixo reconfere essa resolução em vez de confiar no UUID.
--
-- O único card em "Respondeu" também vai para "Novo". "Respondeu" é uma etapa do
-- funil FRIO (key 'respondeu'), não existe em "João - Reposição", e o estado que
-- ela carrega — "o lead respondeu a um disparo frio" — é falso: o lead respondeu
-- porque acabara de comprar. Para o João o card é trabalho novo.
--
-- ── O QUE ESTE ARQUIVO NÃO FAZ (e por quê) ──────────────────────────────────
-- · Não toca a coluna legada `deals.stage`. Ela está CONGELADA e ninguém a lê — a
--   verdade da etapa é `stage_id -> pipeline_stages.key` (leads/service.py:270-275),
--   e `move_lead_deals_to_blacklist` (:1458-1481), que é o precedente de mover
--   deal em massa, também não a toca. Mexer nela criaria um segundo lugar de
--   verdade para a mesma informação.
-- · Não cria deal para lead nenhum. Todos os 19 leads já têm o card — é ele que
--   está no lugar errado.
-- · Não mexe em `leads`, `sales`, `conversion_events` nem em tag alguma.
--
-- ── EFEITO COLATERAL ESPERADO ───────────────────────────────────────────────
-- `updated_at = now()` faz os 19 subirem para o topo do Kanban do João
-- (frontend/src/app/api/deals/route.ts:20 ordena por `updated_at desc`). É
-- intencional: um card que aterrissa com data de três semanas atrás no meio de 659
-- abertos é um card que ele nunca vê, e aí a correção não corrige nada. O preço é
-- perder a evidência "nunca tocado" que hoje vive no delta updated_at−created_at —
-- por isso o dump do bloco ANTES precisa ser SALVO antes de commitar.
--
-- ── PRÉ-REQUISITO ───────────────────────────────────────────────────────────
-- Nenhum. Este arquivo não depende de migração: só usa colunas que já existem.
--
-- ── COMO APLICAR ────────────────────────────────────────────────────────────
-- `\set` e `\echo` são meta-comandos do PSQL, não SQL — no editor SQL do Supabase
-- eles dão erro de sintaxe. Duas opções: rodar o arquivo inteiro com
-- `psql "$DATABASE_URL" -f este_arquivo.sql`, ou, no editor web, apagar as linhas
-- que começam com `\` e executar bloco a bloco, na ordem em que estão. Se for pelo
-- editor, o `BEGIN;`/`COMMIT;` PRECISA ir junto com o UPDATE na mesma execução —
-- separá-los deixaria a transação aberta.
--
-- Todas as leituras deste arquivo foram executadas em produção em 09/09/2026 e os
-- números do bloco ANTES conferem: 19 · 19 · 18 · 1 · 0.

\set ON_ERROR_STOP on

-- ===========================================================================
-- CONFERÊNCIA — ANTES   (SALVE A SAÍDA: é o material de rollback)
-- ===========================================================================
\echo '=== ANTES: os deals que serão movidos ==='
SELECT d.id            AS deal_id,
       d.stage_id      AS stage_id_origem,
       s.label         AS etapa_origem,
       l.name          AS lead,
       l.phone         AS telefone,
       d.created_at
  FROM deals d
  JOIN leads l ON l.id = d.lead_id
  LEFT JOIN pipeline_stages s ON s.id = d.stage_id
 WHERE d.title = 'Reposição'
   AND d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid
   AND d.closed_at IS NULL
 ORDER BY d.created_at;

\echo '=== ANTES: resumo ==='
SELECT count(*)                                   AS deals_a_mover,
       count(DISTINCT d.lead_id)                  AS leads,
       count(*) FILTER (WHERE s.key = 'frio')      AS em_frio,
       count(*) FILTER (WHERE s.key = 'respondeu') AS em_respondeu,
       count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM deals o
          WHERE o.lead_id = d.lead_id AND o.id <> d.id AND o.closed_at IS NULL
       ))                                          AS leads_com_outro_card_aberto
  FROM deals d
  LEFT JOIN pipeline_stages s ON s.id = d.stage_id
 WHERE d.title = 'Reposição'
   AND d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid
   AND d.closed_at IS NULL;
-- Esperado em 09/09/2026: 19 · 19 · 18 · 1 · 0.
-- `leads_com_outro_card_aberto` > 0 é o sinal de PARAR: significaria criar um
-- segundo card aberto para o mesmo lead, que é o duplicado que `dedupe_open`
-- existe para evitar.

BEGIN;

-- Alvo congelado numa temporária: o UPDATE muda `pipeline_id`, que é o próprio
-- critério de seleção. Sem congelar, uma conferência posterior dentro da mesma
-- transação já veria conjunto vazio.
CREATE TEMP TABLE deals_reposicao_extraviados ON COMMIT DROP AS
SELECT d.id AS deal_id, d.lead_id, d.stage_id AS stage_id_origem
  FROM deals d
 WHERE d.title = 'Reposição'
   AND d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid
   AND d.closed_at IS NULL
   AND d.assigned_to IS NULL
   AND d.category IS NULL
   AND coalesce(d.value, 0) = 0
   AND d.updated_at - d.created_at < interval '1 minute';

-- Guarda de sanidade. 19 é o número medido; o teto de 50 não é expectativa, é o
-- limite acima do qual alguma coisa está errada com o WHERE. Abortar aqui desfaz
-- a transação inteira.
DO $$
DECLARE
  alvo        integer;
  destino     uuid := '79e35e6b-01d1-482a-bdf0-64c733ff1ca4';  -- João - Reposição
  etapa       uuid := '07b4a308-c2ad-4896-99ee-caee30f926b8';  -- "Novo"
  etapa_certa uuid;
BEGIN
  SELECT count(*) INTO alvo FROM deals_reposicao_extraviados;
  IF alvo = 0 THEN
    RAISE EXCEPTION 'nenhum deal extraviado — ou já foi corrigido, ou o WHERE mudou';
  END IF;
  IF alvo > 50 THEN
    RAISE EXCEPTION 'alvo grande demais (%): revise o WHERE antes de continuar', alvo;
  END IF;

  -- Reproduz a resolução de etapa do create_deal (leads/service.py:1150-1173):
  -- primeira NÃO-protegida por order_index. Se alguém reordenou ou protegeu o
  -- board do João desde 09/09/2026, o UUID chumbado acima deixou de ser o destino
  -- certo e é melhor abortar do que espalhar 19 cards na coluna errada.
  SELECT s.id INTO etapa_certa
    FROM pipeline_stages s
   WHERE s.pipeline_id = destino
     AND s.is_protected = false
   ORDER BY s.order_index
   LIMIT 1;
  IF etapa_certa IS DISTINCT FROM etapa THEN
    RAISE EXCEPTION 'etapa de entrada de "João - Reposição" mudou (esperava %, achei %)',
                    etapa, etapa_certa;
  END IF;

  RAISE NOTICE 'deals a mover: %', alvo;
END $$;

-- ===========================================================================
-- O MOVIMENTO
-- ===========================================================================
UPDATE deals d
   SET pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid,  -- João - Reposição
       stage_id    = '07b4a308-c2ad-4896-99ee-caee30f926b8'::uuid,  -- "Novo"
       updated_at  = now()
  FROM deals_reposicao_extraviados x
 WHERE d.id = x.deal_id;

COMMIT;

-- ===========================================================================
-- CONFERÊNCIA — DEPOIS
-- ===========================================================================
-- Esperado: extraviados_restantes = 0 · no_funil_do_joao = 19 · fora_da_etapa_novo = 0.
\echo '=== DEPOIS ==='
SELECT count(*) FILTER (
         WHERE d.pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid
       )                                                       AS extraviados_restantes,
       count(*) FILTER (
         WHERE d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
       )                                                       AS no_funil_do_joao,
       count(*) FILTER (
         WHERE d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
           AND d.stage_id <> '07b4a308-c2ad-4896-99ee-caee30f926b8'::uuid
       )                                                       AS fora_da_etapa_novo
  FROM deals d
 WHERE d.title = 'Reposição'
   AND d.closed_at IS NULL;

-- Agrupa por l.id, NÃO por l.name: entre os 19 há DOIS leads distintos chamados
-- "Edson" (5511983739960 e bling-18005063513). Agrupar por nome somaria os dois
-- num grupo de 2 e reprovaria a conferência com um duplicado que não existe.
\echo '=== DEPOIS: nenhum lead pode ter ficado com dois cards abertos ==='
SELECT l.id AS lead_id, l.name, count(*) AS cards_abertos
  FROM deals d
  JOIN leads l ON l.id = d.lead_id
 WHERE d.closed_at IS NULL
   AND d.lead_id IN (SELECT lead_id FROM deals
                      WHERE title = 'Reposição'
                        AND pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid)
 GROUP BY l.id, l.name
HAVING count(*) > 1
 ORDER BY 3 DESC;
-- Esperado: ZERO linhas.

-- ===========================================================================
-- ROLLBACK (não executar junto — é o plano B)
-- ===========================================================================
-- Depois do movimento, os 19 são exatamente os deals com title = 'Reposição' no
-- funil "João - Reposição" (antes disto, esse conjunto é VAZIO — conferido em
-- 09/09/2026: os únicos 19 deals com título ILIKE 'reposi%' no banco inteiro
-- estão todos no funil frio). Isso torna o rollback em bloco seguro:
--
--   UPDATE deals SET pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid,
--                    stage_id    = 'c9594729-cbcf-41fd-aab5-aef734493c84'::uuid,  -- "Frio"
--                    updated_at  = now()
--    WHERE title = 'Reposição'
--      AND pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
--      AND closed_at IS NULL;
--
-- Ele devolve TODOS para "Frio", inclusive o único que estava em "Respondeu" —
-- aceitável, porque aquele estado foi posto por um reflexo automático e não
-- significa nada no funil frio depois desta correção. Para restaurar etapa por
-- etapa, use o dump do bloco ANTES (deal_id + stage_id_origem):
--
--   UPDATE deals d SET pipeline_id = 'a9487d77-ae93-42fe-89b8-9747d5e9cdf4'::uuid,
--                      stage_id    = v.stage_id_origem::uuid,
--                      updated_at  = now()
--     FROM (VALUES ('<deal_id>', '<stage_id_origem>')) AS v(deal_id, stage_id_origem)
--    WHERE d.id = v.deal_id::uuid;
