-- 20260910_contrato_etapas_joao.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem; esta migration roda a
--    MAO no SQL editor do Supabase, depois de lida e revisada por um humano. Ela mexe
--    no FUNIL DE TRABALHO DO VENDEDOR em producao. Nenhum agente de IA deve aplica-la.
--
-- ── O QUE ELE FAZ ───────────────────────────────────────────────────────────
-- Deixa os 5 funis do Joao com a estrutura decidida na reuniao de 10/09/2026 e, acima
-- de tudo, com `key` em toda etapa que o motor precisa reconhecer.
-- Spec: docs/superpowers/specs/2026-09-10-funil-joao-motor-followup-design.md (§4/SP0).
--
-- A ORDEM E OBRIGATORIA e o arquivo a respeita:
--   1. mover os cards para fora das etapas que vao sumir   (senao FK 23503)
--   2. apagar as etapas vazias
--   3. atribuir as keys
--   4. renomear os rotulos
--   5. criar "Em atencao" onde falta
--   6. reordenar order_index sem buracos e proteger as terminais
--   7. reclassificar os cards de "Novo" cujo lead ja falou com o Joao
--
-- ── POR QUE `key` E O CENTRO DISSO ──────────────────────────────────────────
-- `pipeline_stages.key` e o contrato estavel que todo o codigo de negocio usa; `label`
-- e editavel pelo operador (leads/service.py:237). A tela NUNCA escreveu key ao criar
-- etapa avulsa nem ao renomear, entao as etapas criadas a mao em 10/09 nasceram
-- invisiveis para o motor — e o DELETE, que so checava se havia cards, deixou apagar a
-- `proposta_enviada` (vazia) do funil Reposicao. Esta migration conserta o estado; a
-- porta foi fechada no mesmo branch, do lado da API.
--
-- ── DECISOES QUE PARECEM ARBITRARIAS E NAO SAO ──────────────────────────────
-- · "Em conversa" recebe key `respondeu`, e nao `em_conversa`: e a key que
--   `advance_deal_on_reply` (leads/service.py:1192) ja procura como destino. Adotando-a,
--   o movimento automatico "Novo -> Em conversa" da decisao D2 passa a funcionar sem
--   uma linha de backend. Rotulo e key sao coisas diferentes, e e para isso que servem.
-- · "Ja chamado" recebe `chamado_reposicao`, e NAO `ja_chamado`. A key `ja_chamado` e
--   lida por lead_has_active_relationship (service.py:229) e _lead_had_prior_handoff
--   (tools.py:1682) como "tratativa humana em aberto". Para card de reposicao a
--   semantica ate bate — mas o sinal NUNCA e limpo: o PATCH do Kanban escreve stage_id
--   e closed_at, nunca `deals.stage`. O lead ficaria "relacionamento ativo" para sempre,
--   sem nunca mais receber disparo frio nem poder ser marcado perdido.
-- · `conversion_event` fica NULL em tudo. Preencher despacha o card para a Meta CAPI e
--   para o CSV do Google Ads (ver 20260909:44-99).
-- · O funil Recuperacao NAO ganha `proposta_enviada` nem `fechado_ganho`: pela reuniao
--   (55:20, 54:39) a saida dele e mudar de funil, nao fechar dentro dele.
--
-- Idempotente: casa por UUID e grava sempre o mesmo valor; reexecutavel sem efeito
-- colateral. Em ambientes sem esses funis (homolog) afeta 0 linhas.

BEGIN;

DO $$
DECLARE
  -- Funis (UUIDs medidos em producao em 10/09/2026)
  atacado_id     uuid := '9706a14a-3d9a-413b-bceb-26838fc2cc45';
  plabel_id      uuid := '24fb6ce8-6b7b-4612-970d-8debb8c041b7';
  reposicao_id   uuid := '79e35e6b-01d1-482a-bdf0-64c733ff1ca4';
  recuperacao_id uuid := 'fa94029b-d524-4550-919e-67233dfe3a94';
  repos_pl_id    uuid := '9c027143-72f6-42d6-861f-a494ba5bbb4f';

  -- Etapas que vao sumir (Private Label) e o destino dos seus cards
  pl_proposta    uuid := '649019b7-d6aa-44c8-a320-020a2e554d3c';  -- 12 cards
  pl_negociacao  uuid := '37cab94e-ebb0-4575-9b83-8f4ab3417834';  -- 15 cards
  pl_em_conversa uuid := 'c778fe72-ed7c-49cc-b5c8-8d50b00dd84a';  -- "Contato" -> "Em conversa"

  -- Etapas do Reposicao Private Label (0 cards, nasceu com o esquema abolido)
  rpl_proposta   uuid := 'f0049ee9-7344-468d-80ea-b8ca8ad7e12f';
  rpl_negociacao uuid := '09c79b8f-2889-4d8c-8265-a60559efc15b';

  movidos  integer;
  orfaos   integer;
BEGIN
  -- ────────────────────────────────────────────────────────────────────────
  -- GUARDA 0. O estado do board mudou desde a medicao?
  -- Esta migration foi escrita contra uma leitura de 10/09/2026. Se alguem mexeu nas
  -- etapas nesse meio-tempo, e melhor abortar do que espalhar card na coluna errada.
  -- ────────────────────────────────────────────────────────────────────────
  IF NOT EXISTS (SELECT 1 FROM pipeline_stages WHERE id = pl_proposta AND pipeline_id = plabel_id) THEN
    RAISE EXCEPTION 'etapa "Proposta" do Private Label (%) nao existe mais — reveja a migration', pl_proposta;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pipeline_stages WHERE id = pl_em_conversa AND pipeline_id = plabel_id) THEN
    RAISE EXCEPTION 'etapa de destino (%) nao existe — abortando antes de mover card', pl_em_conversa;
  END IF;

  -- ────────────────────────────────────────────────────────────────────────
  -- 1. MOVER OS CARDS PARA FORA DAS ETAPAS QUE VAO SUMIR
  -- deals.stage_id nao tem ON DELETE (012:32) => NO ACTION. Apagar etapa com card
  -- dentro levanta FK 23503 e desfaz a transacao inteira. Nao existe CASCADE que
  -- "resolva" isso — e bom que nao exista, CASCADE apagaria os deals.
  -- ────────────────────────────────────────────────────────────────────────
  UPDATE deals SET stage_id = pl_em_conversa, updated_at = now()
   WHERE stage_id IN ('649019b7-d6aa-44c8-a320-020a2e554d3c', '37cab94e-ebb0-4575-9b83-8f4ab3417834');
  GET DIAGNOSTICS movidos = ROW_COUNT;
  RAISE NOTICE 'cards movidos de Proposta/Negociacao para Em conversa: %', movidos;
  IF movidos > 100 THEN
    RAISE EXCEPTION 'movidos % cards, esperava ~27 — revise o WHERE antes de continuar', movidos;
  END IF;

  -- ────────────────────────────────────────────────────────────────────────
  -- 2. APAGAR AS ETAPAS, agora vazias
  -- ────────────────────────────────────────────────────────────────────────
  DELETE FROM pipeline_stages
   WHERE id IN (pl_proposta, pl_negociacao, rpl_proposta, rpl_negociacao)
     AND NOT EXISTS (SELECT 1 FROM deals d WHERE d.stage_id = pipeline_stages.id);

  -- ────────────────────────────────────────────────────────────────────────
  -- 3. ATRIBUIR AS KEYS  (o coracao desta migration)
  -- ────────────────────────────────────────────────────────────────────────
  -- Joao - Atacado
  UPDATE pipeline_stages SET key = 'novo'      WHERE id = '26103dba-b371-47a5-b990-70da776ccce5';
  UPDATE pipeline_stages SET key = 'respondeu' WHERE id = '6027a761-ed7e-4d34-b388-5ec2debbeaae';

  -- Joao - Private Label
  UPDATE pipeline_stages SET key = 'novo'      WHERE id = '05b52405-806d-4f1f-89e8-f96c9fd86ba5';
  UPDATE pipeline_stages SET key = 'respondeu' WHERE id = 'c778fe72-ed7c-49cc-b5c8-8d50b00dd84a';

  -- Joao - Reposicao
  UPDATE pipeline_stages SET key = 'novo'              WHERE id = '07b4a308-c2ad-4896-99ee-caee30f926b8';
  UPDATE pipeline_stages SET key = 'chamado_reposicao' WHERE id = '58b9fbe0-c138-4dcb-8318-ed2409c61a9a';
  UPDATE pipeline_stages SET key = 'em_atencao'        WHERE id = '499ab4a7-ce6a-4362-b7a5-63b2c65fd9d0';
  -- A key que foi apagada a mao em 10/09 junto com a etapa vazia que a carregava.
  -- Sem ela, `_move_deal_to_proposal` nao acha a etapa neste funil e o orcamento nao
  -- move o card — em silencio (quotes/router.py:274-279 devolve False com log info).
  UPDATE pipeline_stages SET key = 'proposta_enviada'  WHERE id = 'd1a0a022-71fe-4ff9-bc7d-3ff813a4d9ec';

  -- Joao - Recuperacao (sem proposta_enviada e sem fechado_ganho, de proposito)
  UPDATE pipeline_stages SET key = 'entrada'     WHERE id = '699e0b61-ee7f-480e-827e-fd970379c7da';
  UPDATE pipeline_stages SET key = 'em_followup' WHERE id = 'd8d39be3-97ea-4a43-9cfe-bc95d0fb52b1';
  UPDATE pipeline_stages SET key = 'recuperado'  WHERE id = 'd5bad206-280a-461d-b122-d2c4f0f3a088';

  -- Joao - Reposicao Private Label (espelho do Reposicao, 0 cards)
  UPDATE pipeline_stages SET key = 'novo',              label = 'Cliente Ativo' WHERE id = 'ac70ef91-9e67-4eb2-b36a-5ee52da90737';
  UPDATE pipeline_stages SET key = 'chamado_reposicao', label = 'Já chamado'    WHERE id = 'd2295c6a-bd04-427c-80ff-a8592012e4b1';

  -- ────────────────────────────────────────────────────────────────────────
  -- 4. RENOMEAR OS ROTULOS
  -- "Em Conversa" da Reposicao NAO e a mesma coisa que a dos funis de 1a compra: la
  -- significa "o lead respondeu", aqui significa "ja foi chamado neste ciclo". Manter o
  -- mesmo rotulo nos dois faria a tela de configuracao de esteira mentir.
  -- ────────────────────────────────────────────────────────────────────────
  UPDATE pipeline_stages SET label = 'Em conversa' WHERE id = pl_em_conversa;                          -- era "Contato"
  UPDATE pipeline_stages SET label = 'Já chamado'  WHERE id = '58b9fbe0-c138-4dcb-8318-ed2409c61a9a';  -- era "Em Conversa"
  UPDATE pipeline_stages SET label = 'Em atenção'  WHERE id = '499ab4a7-ce6a-4362-b7a5-63b2c65fd9d0';  -- era "Em ATENÇÃO"
  UPDATE pipeline_stages SET label = 'Em conversa' WHERE id = '6027a761-ed7e-4d34-b388-5ec2debbeaae';  -- "Em Conversa" -> caixa

  -- ────────────────────────────────────────────────────────────────────────
  -- 5. CRIAR "Em atencao" onde falta (Atacado, Private Label, Reposicao PL)
  -- E o estado terminal da esteira: o lead percorreu tudo e nao comprou, entao para de
  -- ser automatico e vira decisao do vendedor (spec D9). Cor viva, por pedido do Arthur.
  -- ────────────────────────────────────────────────────────────────────────
  INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
  SELECT v.pipeline_id, 'Em atenção', 'em_atencao', '#c9457b', 2, false
    FROM (VALUES (atacado_id), (plabel_id), (repos_pl_id)) AS v(pipeline_id)
   WHERE NOT EXISTS (
     SELECT 1 FROM pipeline_stages s
      WHERE s.pipeline_id = v.pipeline_id AND s.key = 'em_atencao'
   );

  -- ────────────────────────────────────────────────────────────────────────
  -- 6. REORDENAR SEM BURACOS E PROTEGER AS TERMINAIS
  -- order_index e a definicao de fato de "etapa de entrada": _first_unprotected_stage_id
  -- pega o MENOR order_index entre is_protected=false. Hoje NENHUMA etapa e protegida,
  -- entao um arrasta-e-solta infeliz faz todo card novo e todo handoff nascer em
  -- "Fechado Ganho" ou "Perdido". Proteger as duas terminais fecha isso.
  --
  -- A ordem tambem importa para o orcamento: `_move_deal_to_proposal` so move se o
  -- order_index atual for MENOR que o de proposta_enviada (quotes/router.py:281). Se
  -- "Em conversa" ficasse depois, o unico marco valido da reuniao pararia em silencio.
  -- ────────────────────────────────────────────────────────────────────────
  WITH ordem AS (
    SELECT id,
           row_number() OVER (
             PARTITION BY pipeline_id
             ORDER BY CASE key
               WHEN 'novo'              THEN 0
               WHEN 'entrada'           THEN 0
               WHEN 'respondeu'         THEN 1
               WHEN 'chamado_reposicao' THEN 1
               WHEN 'em_followup'       THEN 1
               WHEN 'em_atencao'        THEN 2
               WHEN 'recuperado'        THEN 2
               WHEN 'proposta_enviada'  THEN 3
               WHEN 'fechado_ganho'     THEN 8
               WHEN 'fechado_perdido'   THEN 9
               ELSE 5
             END, order_index
           ) - 1 AS nova
      FROM pipeline_stages
     WHERE pipeline_id IN (atacado_id, plabel_id, reposicao_id, recuperacao_id, repos_pl_id)
  )
  UPDATE pipeline_stages p SET order_index = o.nova
    FROM ordem o WHERE p.id = o.id AND p.order_index IS DISTINCT FROM o.nova;

  UPDATE pipeline_stages SET is_protected = true
   WHERE pipeline_id IN (atacado_id, plabel_id, reposicao_id, recuperacao_id, repos_pl_id)
     AND key IN ('fechado_ganho', 'fechado_perdido');

  -- ────────────────────────────────────────────────────────────────────────
  -- 7. RECLASSIFICAR OS CARDS DE "Novo" CUJO LEAD JA FALOU COM O JOAO
  -- Medido em 10/09/2026: 363 dos 578 cards em "Novo" tem lead que ja mandou mensagem
  -- NO NUMERO DO VENDEDOR. Pela decisao D2, "Novo" = o Joao mandou algo e o lead NAO
  -- respondeu — entao esses 363 estao na coluna errada, e sem mover receberiam a
  -- mensagem da esteira "Novo", que diz em essencia "voce nao me respondeu".
  --
  -- O criterio e EXISTS(mensagem role='user' em conversa de canal mode='human'), e nao
  -- "quem falou por ultimo": este ultimo devolveria 792 de 810, porque o normal e o
  -- Joao ter falado por ultimo. Tambem nao serve "o lead ja mandou alguma mensagem":
  -- isso da 570, porque quase todo lead falou com a ValerIA ANTES do handoff.
  -- ────────────────────────────────────────────────────────────────────────
  UPDATE deals d
     SET stage_id = alvo.id, updated_at = now()
    FROM pipeline_stages atual, pipeline_stages alvo
   WHERE d.stage_id = atual.id
     AND atual.key = 'novo'
     AND atual.pipeline_id IN (atacado_id, plabel_id)
     AND alvo.pipeline_id = atual.pipeline_id
     AND alvo.key = 'respondeu'
     AND d.closed_at IS NULL
     AND EXISTS (
       SELECT 1
         FROM messages m
         JOIN conversations c ON c.id = m.conversation_id
         JOIN channels ch     ON ch.id = c.channel_id
        WHERE m.lead_id = d.lead_id
          AND m.role = 'user'
          AND ch.mode = 'human'
     );
  GET DIAGNOSTICS movidos = ROW_COUNT;
  RAISE NOTICE 'cards reclassificados de Novo para Em conversa: % (esperado ~363)', movidos;

  -- ────────────────────────────────────────────────────────────────────────
  -- GUARDA FINAL. Nenhum deal pode ter ficado apontando para etapa inexistente.
  -- ────────────────────────────────────────────────────────────────────────
  SELECT count(*) INTO orfaos
    FROM deals d
   WHERE d.stage_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM pipeline_stages s WHERE s.id = d.stage_id);
  IF orfaos > 0 THEN
    RAISE EXCEPTION 'ficaram % deals orfaos — desfazendo tudo', orfaos;
  END IF;
END $$;

COMMIT;

-- O PostgREST serve o schema em cache: sem isto o CRM responde PGRST204/205 com a
-- coluna ja existindo no banco. Precedente: 20260825:195 e 20260909:162.
NOTIFY pgrst, 'reload schema';
