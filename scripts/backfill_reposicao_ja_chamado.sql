-- scripts/backfill_reposicao_ja_chamado.sql
--
-- ⛔ NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO. Escreve em PRODUÇÃO, no
--    FUNIL DE TRABALHO DO VENDEDOR (João), em 672 cards de uma vez. Nenhum
--    agente de IA deve rodar este arquivo. Ele existe para ser LIDO, revisado,
--    autorizado e só então aplicado à mão por um humano: primeiro o bloco
--    "SELECT DE CONFERÊNCIA — ANTES" sozinho, e só depois de ler o resultado o
--    bloco BEGIN…COMMIT.
--
-- ── O QUE ACONTECEU ──────────────────────────────────────────────────────────
-- A coluna "Já chamado" (key `chamado_reposicao`) do funil João - Reposição
-- Atacado tem 698 cards, e NENHUM deles foi chamado por máquina nenhuma: o
-- motor de follow-up do João nunca rodou em produção (0 matrículas na
-- história). Eles foram postos lá por gente e por uma importação antiga, sob o
-- significado velho da coluna ("já falei com esse cliente alguma vez").
--
-- A esteira de Reposição estreia com o significado NOVO: "Já chamado" passa a
-- querer dizer "recebeu o 1º toque desta esteira" — é o próprio toque 1 que
-- move o card para lá (`Touch.move_para`, app/follow_up/cadence_joao.py). Sob
-- esse contrato, os 698 estão mentindo.
--
-- Pior que mentir: eles estão FORA de alcance. O gatilho da esteira é "parado
-- 45 dias em Cliente Ativo" (key `novo`), e a matrícula só acontece a partir
-- dessa etapa. Card parado em "Já chamado" não é varrido — de propósito, é o
-- que impede a esteira de reentrar sozinha. Então esses clientes nunca
-- receberiam nada.
--
-- ── A DECISÃO DO DONO (26/09/2026) ───────────────────────────────────────────
-- Disparar para eles. Este arquivo os devolve a "Cliente Ativo" PRESERVANDO O
-- RELÓGIO — a data em que cada card entrou na etapa —, para que entrem na
-- esteira já vencidos em vez de esperar mais 45 dias.
--
-- ── OS NÚMEROS MEDIDOS EM 26/09/2026 ─────────────────────────────────────────
--
--   funil                       Cliente Ativo   Já chamado   Já chamado 45d+
--   ─────────────────────────────────────────────────────────────────────────
--   João - Reposição Atacado    170 (0 vencidos)     698          672
--   João - Reposição P. Label    18 (0 vencidos)       0            0
--
-- Private Label NÃO entra: não tem backlog nenhum. Este arquivo toca UM funil.
--
-- ── POR QUE DUAS INSTRUÇÕES, E POR QUE ISSO NÃO É FRESCURA ──────────────────
-- O relógio é `deals.entered_stage_at`, mantido por
-- `trg_update_deal_entered_stage_at` (supabase/migrations/20260904_esteiras_
-- vendedor.sql:38-52) — um BEFORE UPDATE que faz `NEW.entered_stage_at = now()`
-- sempre que `stage_id` **ou** `stage` muda. Ele observa as DUAS colunas
-- justamente porque caminhos legados ainda escrevem o texto.
--
-- Consequência: um UPDATE só, movendo e setando a data na mesma instrução,
-- NÃO funciona — o trigger é BEFORE e sobrescreve o valor que a instrução
-- passou. Os 672 sairiam com o relógio zerado e esperariam 45 dias parados numa
-- coluna onde o vendedor não os procura. O sintoma seria "o backfill rodou e
-- não aconteceu nada", por um mês e meio.
--
-- Por isso:
--
--   instrução 1 — move `stage_id` E a coluna legada `stage` (o trigger dispara
--                 e carimba now(); tudo bem, é esperado);
--   instrução 2 — devolve `entered_stage_at` ao valor capturado ANTES, e não
--                 toca em etapa nenhuma — é exatamente isso que faz o trigger
--                 NÃO disparar de novo e a data sobreviver ao COMMIT.
--
-- A instrução 1 escreve as DUAS colunas de etapa de propósito. `stage_id` é a
-- verdade (o Kanban lê ele), mas deixar o texto legado para trás cria duas
-- colunas discordando sobre onde o card está — e é o texto que
-- `_ACTIVE_DEAL_STAGES` (backend/app/leads/service.py:230, `stage='ja_chamado'`)
-- e outros caminhos antigos ainda leem. O valor escrito é a KEY da etapa de
-- destino (`novo`), o mesmo que `move_deal_to_stage_key` grava.
--
-- ── O ESCOPO É GUARDADO EM TRÊS EIXOS ───────────────────────────────────────
--   1. funil: só João - Reposição Atacado (79e35e6b-…). Conferido nas DUAS
--      pontas — `deals.pipeline_id` E o `pipeline_id` da etapa —, porque card
--      com etapa de outro funil existe neste banco e seria movido para o lugar
--      errado por uma só das duas.
--   2. etapa: só quem está HOJE em `chamado_reposicao`, resolvido por KEY e
--      nunca por rótulo (rótulo é editável na tela por qualquer operador).
--   3. relógio: só 45+ dias. Os ~26 cards mais novos ficam onde estão — eles
--      ainda não venceriam de qualquer forma, e mexer neles seria mexer sem
--      motivo.
--
-- ── O QUE ESTE ARQUIVO NÃO FAZ ──────────────────────────────────────────────
-- Não cria nem apaga card nenhum. Não toca em `leads`, `sales`, `follow_up_jobs`
-- nem em campanha alguma — em especial, não encosta no caminho `standard` da
-- ValerIA, o único follow-up que funciona em produção. Não liga esteira: a
-- Reposição continua desligada depois disto, e ligar segue sendo ato humano na
-- tela. Não mexe em Private Label. Não altera estrutura de tabela — por isso é
-- script, e não migration.
--
-- ── EFEITO COLATERAL ESPERADO, E ELE É GRANDE ───────────────────────────────
-- `updated_at = now()` nos 672 sobe todos eles para o topo do Kanban do João
-- (ordenado por updated_at desc). O board de Reposição Atacado vai parecer
-- inteiro reordenado no dia em que isto rodar. É intencional — a alternativa é
-- um `updated_at` que mente sobre uma linha que mudou — mas avise o vendedor
-- antes, ou ele vai achar que alguém mexeu no funil dele.
--
-- E o efeito que importa: com a esteira LIGADA, esses 672 ficam elegíveis de
-- uma vez. Quem segura o volume é o teto diário de disparos (100/dia, spec §4),
-- e é ele que faz o backlog drenar em ~7 dias em vez de sair em 6 minutos —
-- que é a forma medida em 16/09/2026 ("888 cards em 6 minutos"). NÃO rode este
-- arquivo com a esteira ligada e sem o teto no ar.
--
-- ── COMO APLICAR ─────────────────────────────────────────────────────────────
-- SQL puro, sem meta-comando de psql — roda direto no editor SQL do Supabase.
--   1. Rode o bloco "SELECT DE CONFERÊNCIA — ANTES" sozinho e leia o resultado.
--   2. Confira: ~672 cards no alvo, 0 fechados, o relógio mais novo do alvo com
--      45 dias ou mais. Se o total tiver mudado muito desde 26/09/2026, leia por
--      quê antes de continuar.
--   3. Rode o bloco BEGIN…COMMIT inteiro de uma vez. Ele aborta sozinho se
--      alguma guarda não bater — nenhuma linha é tocada nesse caso.
--   4. Rode o bloco "SELECT DE CONFERÊNCIA — DEPOIS" e confira os números.

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — ANTES   (rodar sozinho, ler o resultado antes do BEGIN)
-- ===========================================================================
-- Esperado em 26/09/2026: cards_no_alvo = 672, fechados = 0,
-- ja_chamado_total = 698, relogio_mais_novo com 45 dias ou mais.
SELECT count(*)                                        AS cards_no_alvo,
       count(*) FILTER (WHERE d.closed_at IS NOT NULL)  AS fechados,
       min(d.entered_stage_at)                          AS relogio_mais_antigo,
       max(d.entered_stage_at)                          AS relogio_mais_novo,
       (now()::date - max(d.entered_stage_at)::date)    AS dias_do_mais_novo
  FROM deals d
  JOIN pipeline_stages s ON s.id = d.stage_id
 WHERE d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid  -- João - Reposição Atacado
   AND s.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
   AND s.key = 'chamado_reposicao'
   AND d.entered_stage_at IS NOT NULL
   AND d.entered_stage_at <= now() - interval '45 days';

-- A foto do funil inteiro, para comparar com a de DEPOIS. Esperado em
-- 26/09/2026: Cliente Ativo 170, Já chamado 698, Em atenção 0.
SELECT s.key                                             AS etapa,
       s.label                                           AS rotulo,
       count(d.id)                                       AS cards,
       count(d.id) FILTER (
         WHERE d.entered_stage_at <= now() - interval '45 days'
       )                                                 AS vencidos_45d
  FROM pipeline_stages s
  LEFT JOIN deals d
         ON d.stage_id = s.id
        AND d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
 WHERE s.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
 GROUP BY s.key, s.label, s.order_index
 ORDER BY s.order_index;

-- ===========================================================================
-- O MOVIMENTO
-- ===========================================================================
BEGIN;

-- O alvo e o RELÓGIO DE CADA CARD, congelados numa temporária antes de
-- qualquer escrita. Congelar não é zelo: a instrução 1 muda a própria etapa que
-- o WHERE usa para selecionar, e o trigger sobrescreve a própria data que a
-- instrução 2 precisa devolver. Sem esta cópia, o valor original não existe
-- mais em lugar nenhum depois do primeiro UPDATE.
CREATE TEMP TABLE reposicao_ja_chamado_calc ON COMMIT DROP AS
SELECT d.id               AS deal_id,
       d.entered_stage_at AS relogio,
       d.stage_id         AS stage_id_antes,
       d.stage            AS stage_legado_antes,
       d.closed_at        AS closed_at
  FROM deals d
  JOIN pipeline_stages s ON s.id = d.stage_id
 WHERE d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid  -- João - Reposição Atacado
   AND s.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
   AND s.key = 'chamado_reposicao'
   AND d.entered_stage_at IS NOT NULL
   AND d.entered_stage_at <= now() - interval '45 days';

-- Guardas de sanidade. Abortam a transação inteira (nenhuma linha é tocada) se
-- o alvo não bater com o que foi medido, ou se o destino não existir — nunca
-- move "pela metade" nem chuta a etapa.
DO $$
DECLARE
  total    integer;
  fechados integer;
  destino  uuid;
BEGIN
  SELECT count(*), count(*) FILTER (WHERE closed_at IS NOT NULL)
    INTO total, fechados
    FROM reposicao_ja_chamado_calc;

  IF total = 0 THEN
    RAISE EXCEPTION 'nenhum card no alvo -- ou o backfill ja foi aplicado, ou o WHERE mudou';
  END IF;

  -- Medido: 672. Um alvo muito maior significa que o escopo pegou algo que não
  -- é o backlog desta coluna, e mover milhares de cards de um funil de trabalho
  -- não se desfaz com um comando.
  IF total > 1000 THEN
    RAISE EXCEPTION 'alvo grande demais (%): eram 672 em 26/09/2026 -- releia o SELECT de conferencia antes de continuar', total;
  END IF;

  -- Card FECHADO em "Já chamado" é anomalia: venda fechada vai para
  -- fechado_ganho/fechado_perdido, não para cá. Devolvê-lo a "Cliente Ativo" o
  -- reabriria para uma esteira de reposição, que é decisão de gente.
  IF fechados > 0 THEN
    RAISE EXCEPTION 'ha % card(s) FECHADO(S) no alvo -- investigue antes: mover card fechado para Cliente Ativo o reabre para a esteira', fechados;
  END IF;

  -- A etapa de destino é resolvida por KEY, nunca por rótulo (rótulo é editável
  -- na tela). Sem ela, o UPDATE abaixo escreveria stage_id NULL e os cards
  -- sumiriam do board.
  SELECT id INTO destino
    FROM pipeline_stages
   WHERE pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
     AND key = 'novo';
  IF destino IS NULL THEN
    RAISE EXCEPTION 'o funil de Reposicao Atacado nao tem etapa key=novo ("Cliente Ativo") -- nada a fazer aqui ate isso ser resolvido';
  END IF;

  RAISE NOTICE 'cards no alvo: % | destino (Cliente Ativo): %', total, destino;
END $$;

-- ── INSTRUÇÃO 1 — move o card. O trigger vai carimbar entered_stage_at = now().
-- Escreve as DUAS colunas de etapa de propósito (ver o cabeçalho): `stage_id` é
-- a verdade do Kanban, `stage` é o texto legado que caminhos antigos ainda leem.
UPDATE deals d
   SET stage_id   = (SELECT id FROM pipeline_stages
                      WHERE pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
                        AND key = 'novo'),
       stage      = 'novo',
       updated_at = now()
  FROM reposicao_ja_chamado_calc c
 WHERE d.id = c.deal_id;

-- ── INSTRUÇÃO 2 — devolve o relógio ao valor capturado.
-- NÃO TOQUE EM ETAPA AQUI. Acrescentar `stage_id` ou `stage` a este SET faria o
-- trigger disparar de novo e sobrescrever a data — que é o defeito inteiro que
-- estas duas instruções existem para evitar. `updated_at` também fica de fora:
-- a instrução 1 já o atualizou, e mexer nele aqui não muda nada.
UPDATE deals d
   SET entered_stage_at = c.relogio
  FROM reposicao_ja_chamado_calc c
 WHERE d.id = c.deal_id
   AND d.entered_stage_at IS DISTINCT FROM c.relogio;

-- Guarda de saída: prova, ainda DENTRO da transação, que as duas coisas que
-- importam aconteceram — o card andou E o relógio sobreviveu. Se o trigger
-- tiver mudado de forma, é aqui que se descobre, com ROLLBACK automático em vez
-- de 672 cards com a data zerada em produção.
DO $$
DECLARE
  nao_moveram   integer;
  relogio_ruim  integer;
BEGIN
  SELECT count(*) INTO nao_moveram
    FROM reposicao_ja_chamado_calc c
    JOIN deals d ON d.id = c.deal_id
    JOIN pipeline_stages s ON s.id = d.stage_id
   WHERE s.key IS DISTINCT FROM 'novo' OR d.stage IS DISTINCT FROM 'novo';

  SELECT count(*) INTO relogio_ruim
    FROM reposicao_ja_chamado_calc c
    JOIN deals d ON d.id = c.deal_id
   WHERE d.entered_stage_at IS DISTINCT FROM c.relogio;

  IF nao_moveram > 0 THEN
    RAISE EXCEPTION '% card(s) nao chegaram em Cliente Ativo nas duas colunas de etapa', nao_moveram;
  END IF;
  IF relogio_ruim > 0 THEN
    RAISE EXCEPTION '% card(s) perderam entered_stage_at -- o trigger sobrescreveu: NAO aplique', relogio_ruim;
  END IF;

  RAISE NOTICE 'ok: todos os cards em Cliente Ativo com o relogio original preservado';
END $$;

COMMIT;

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — DEPOIS
-- ===========================================================================
-- Esperado: "Já chamado" cai de 698 para ~26 (os que ainda não tinham 45 dias),
-- "Cliente Ativo" sobe de 170 para ~842, e `vencidos_45d` de Cliente Ativo passa
-- de 0 para ~672 — esse último número é o ponto do backfill inteiro: eles entram
-- na esteira JÁ VENCIDOS, sem esperar mais 45 dias.
SELECT s.key                                             AS etapa,
       s.label                                           AS rotulo,
       count(d.id)                                       AS cards,
       count(d.id) FILTER (
         WHERE d.entered_stage_at <= now() - interval '45 days'
       )                                                 AS vencidos_45d
  FROM pipeline_stages s
  LEFT JOIN deals d
         ON d.stage_id = s.id
        AND d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
 WHERE s.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
 GROUP BY s.key, s.label, s.order_index
 ORDER BY s.order_index;

-- A prova de que o relógio sobreviveu: nenhum card de Cliente Ativo pode ter
-- entrado na etapa "hoje". Se esta consulta devolver ~672, o trigger venceu e a
-- instrução 2 não fez efeito.
SELECT count(*) AS entraram_hoje_em_cliente_ativo
  FROM deals d
  JOIN pipeline_stages s ON s.id = d.stage_id
 WHERE d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
   AND s.key = 'novo'
   AND d.entered_stage_at >= now() - interval '1 hour';
-- Esperado: ZERO (ou só cards que uma venda real criou na última hora).

-- E a prova de que as duas colunas de etapa concordam — o achado de §6 da spec.
SELECT count(*) AS etapa_divergente
  FROM deals d
  JOIN pipeline_stages s ON s.id = d.stage_id
 WHERE d.pipeline_id = '79e35e6b-01d1-482a-bdf0-64c733ff1ca4'::uuid
   AND s.key IS DISTINCT FROM d.stage;
-- Esperado: os cards que este arquivo NÃO tocou podem divergir (é o defeito
-- antigo); nenhum dos 672 pode.

-- ===========================================================================
-- ROLLBACK (plano B — não roda junto)
-- ===========================================================================
-- Depois do COMMIT a temporária some, então a única cópia do estado anterior é
-- o resultado do bloco "SELECT DE CONFERÊNCIA — ANTES" — SALVE ESSE RESULTADO
-- antes de rodar o movimento. Desfazer é o mesmo par de instruções, invertido:
-- primeiro devolver a etapa (o trigger zera a data), depois devolver a data.
--
--   BEGIN;
--   UPDATE deals SET stage_id = '<uuid da etapa Ja chamado>'::uuid,
--                     stage    = 'chamado_reposicao',
--                     updated_at = now()
--    WHERE id IN (<os deal_id salvos>);
--   UPDATE deals SET entered_stage_at = '<o relogio salvo daquele card>'::timestamptz
--    WHERE id = '<deal_id>'::uuid;   -- um por card: cada um tem sua data
--   COMMIT;
