-- 20260909_recuperacao_stages_optout.sql
-- Agente "ValerIA Recuperação" — desfechos no funil + evidência de opt-out.
-- Spec: docs/superpowers/specs/2026-09-09-valeria-recuperacao-botoes-design.md §7.1
--
-- NÃO É APLICADA PELO DEPLOY. O GitHub Actions sobe imagem, não roda migration:
-- este arquivo é executado à mão no SQL editor do Supabase. Aplicar JUNTO com
-- 20260820_button_flow_agent.sql (que também segue pendente — verificado em
-- 09/09/2026: agent_profiles.kind e conversations.flow_state não existem no banco).
--
-- Reexecutar é seguro: colunas são ADD COLUMN IF NOT EXISTS e as etapas entram sob
-- guarda de NOT EXISTS por (pipeline_id, key). A guarda das etapas não é zelo: sem
-- ela, uma segunda execução criaria três colunas duplicadas no Kanban do João, e o
-- Kanban não tem como distinguir "Quer repor" de "Quer repor".
--
-- Nomes e tipos de pipeline_stages conferidos no banco em 09/09/2026:
-- (id uuid, pipeline_id uuid, label text NOT NULL, key text, dot_color text NOT NULL
--  DEFAULT '#9ca3af', order_index int NOT NULL DEFAULT 0, is_protected bool NOT NULL
--  DEFAULT false, created_at timestamptz, conversion_event text, conversion_value numeric).

-- ===========================================================================
-- 1. Etapas de desfecho do funil Reativação Bling
-- ===========================================================================
-- O funil tem 8 etapas (order_index 0..7) e TODAS são etapas de RECÊNCIA: elas
-- registram há quanto tempo o lead não compra, ou seja, qual onda ele pegou.
-- Por isso o agente NÃO move o deal no envio — mover na saída destruiria a
-- segmentação e a segunda onda não teria como ser montada. Move só no desfecho,
-- e é para cá que ele move.
--
-- UUIDs fixos, como em scripts/reativacao/lote_completo.py: deixam o INSERT
-- idempotente por id e dão ao rollback um alvo preciso. (A guarda abaixo é por
-- (pipeline_id, key) e não por id, porque o acidente que interessa evitar é
-- alguém ter criado "Quer repor" pela UI antes desta migração rodar — aí o id
-- seria outro e o ON CONFLICT (id) deixaria passar a duplicata.)
--
-- is_protected = false seguindo as 8 irmãs e TODAS as demais etapas do banco
-- (zero linhas com is_protected = true em 09/09/2026). Marcar true aqui mudaria
-- o comportamento de duas telas sem precedente para calibrar
-- (frontend/src/app/api/deals/route.ts:49 e vendas/page.tsx:304); e o único risco
-- concreto de deixar false — virar etapa de entrada de um deal novo — não existe,
-- porque quem resolve entrada pega o MENOR order_index e estas são 8, 9 e 10.
INSERT INTO pipeline_stages
  (id, pipeline_id, label, key, dot_color, order_index, is_protected,
   conversion_event, conversion_value)
SELECT v.id::uuid, 'b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09'::uuid,
       v.label, v.key, v.dot_color, v.order_index, false,
       v.conversion_event, NULL
FROM (VALUES
  -- "Quer repor" é A conversão do agente: o lead tocou "Preciso repor" (ou o
  -- classificador leu QUENTE no texto livre) e foi entregue ao João na mesma
  -- thread. Ainda assim `conversion_event` fica NULL — DESVIO DELIBERADO da spec
  -- §7.1, que pedia "conversion_event = sim". Vale a pena explicar por quê, porque
  -- a versão anterior deste arquivo dizia 'qualified'.
  --
  -- `conversion_event` não é um rótulo descritivo: é um GATILHO. Entrar na etapa
  -- faz automation/triggers.py:35-44 chamar fire_conversion_for_deal_stage, que
  -- grava a linha em conversion_events E despacha o evento para a Meta (CAPI).
  -- E quem lê essa tabela é a série de conversão de ANÚNCIO do Dashboard:
  -- campaigns/conversion_analytics.py:33-51 (build_timeseries) conta 'qualified',
  -- 'opportunity' e 'purchase' dos últimos 30 dias SEM NENHUM filtro de funil —
  -- conversion_dashboard:100-123 lhe entrega a tabela inteira, e o resultado é a
  -- seção "Conversões (Ads)" (campaigns/conversions_router.py:15-18), que o time
  -- usa para decidir verba de tráfego.
  --
  -- Medido em produção em 09/09/2026: `conversion_events` tem ZERO linhas e
  -- NENHUMA etapa do banco tem `conversion_event` preenchido. "Quer repor" seria
  -- a primeira e a única — ou seja, a régua do tráfego pago passaria a ser 100%
  -- cliques de um bot de reativação de base própria, que não custou um centavo de
  -- anúncio. Com o ROAS medido em 0,27 (Diagnóstico 01/09), inflar exatamente esse
  -- número é o pior efeito colateral possível.
  --
  -- E por que não um valor FORA do vocabulário (ex.: 'recuperacao_quer_repor'):
  -- ele de fato ficaria fora da série, mas dois consumidores caem no nome CRU
  -- quando não reconhecem o evento — capi_dispatcher.meta_event_name:49-52
  -- mandaria um evento inventado para a Meta, e google_export.conversion_name_for
  -- :29-30 escreveria esse nome na coluna "Conversion Name" do CSV de conversões
  -- offline, onde uma ação inexistente reprova o ARQUIVO INTEIRO no Google Ads.
  -- Isso só dispara para lead com ctwa_clid/gclid; a coorte veio do ERP, mas 1 dos
  -- 1.208 tem ctwa_clid (conferido em 09/09/2026). Um basta para quebrar o CSV.
  --
  -- COMO MEDIR A CONVERSÃO DO AGENTE SEM conversion_events — a tag e a etapa já
  -- bastam, e são gravadas por button_flow/effects.py:
  --   SELECT count(DISTINCT lt.lead_id)
  --     FROM lead_tags lt JOIN tags t ON t.id = lt.tag_id
  --    WHERE t.name = 'Recuperação: Quente';
  -- Série por dia (lead_tags não tem created_at; as mensagens de sistema têm):
  --   SELECT date(created_at) AS dia, count(*)
  --     FROM messages
  --    WHERE role = 'system' AND content LIKE '[button_flow]%TRANSBORDO%'
  --    GROUP BY 1 ORDER BY 1;
  -- Se um dia a conversão do agente merecer um gráfico, o lugar é uma série
  -- PRÓPRIA, filtrada por funil — não a régua do tráfego pago.
  --
  -- conversion_value segue NULL pelo mesmo motivo de sempre: o valor real da
  -- reposição é o pedido que o João fechar, e chutar um ticket médio aqui
  -- contaminaria o ROAS.
  --
  -- (`NULL::text` e não `NULL` cru: as três linhas do VALUES ficaram sem literal
  -- nesta coluna, e sem o cast o Postgres não infere o tipo — "column ... is of
  -- type text but expression is of type unknown".)
  ('29ec05da-3fb6-4149-928a-102d4e6f9bc8', 'Quer repor',          'quer_repor',         '#2f8f5b',  8, NULL::text),
  -- O lead pediu tempo (30/60/90 dias). A data fica em leads.metadata.recontatar_em;
  -- o worker de re-disparo é fase 2 (spec §2.1) e a etapa é o que torna a fila
  -- visível no Kanban enquanto ele não existe.
  ('3afd16eb-40c7-425a-a39b-213e5f70acd9', 'Recontato agendado',  'recontato_agendado', '#c9a227',  9, NULL),
  -- Saída digna e inequívoca. Etapa separada de "perdido" de propósito: perdido é
  -- juízo comercial, descadastrado é um direito exercido — e a diferença precisa
  -- sobreviver a qualquer limpeza futura do funil.
  ('4b0e27fc-51d8-436b-b4ac-324f6081bdea', 'Descadastrado',       'descadastrado',      '#6b7280', 10, NULL)
) AS v(id, label, key, dot_color, order_index, conversion_event)
WHERE NOT EXISTS (
  SELECT 1 FROM pipeline_stages s
   WHERE s.pipeline_id = 'b2f9c31d-8a47-4e26-95c0-3d7a1f6e8b09'::uuid
     AND s.key = v.key
);

-- ===========================================================================
-- 2. Evidência de opt-out em leads
-- ===========================================================================
-- Hoje leads.opt_out é um booleano nu: true/false, sem quando, sem por onde, sem
-- prova. Isso é insuficiente por dois motivos independentes.
--
-- (a) LEGAL. A base que sustenta escrever para 1.208 clientes antigos do Bling é
--     legítimo interesse (LGPD art. 7º IX) sobre relação contratual prévia, e um
--     LIA só se defende na ANPD com registro do exercício do direito de oposição
--     (art. 18 §2): QUANDO a pessoa pediu, POR ONDE pediu e QUAL a evidência. Um
--     booleano não responde a nenhuma das três, e o direito de oposição é
--     unificado entre canais — vale para os três números e para e-mail.
--
-- (b) OPERACIONAL. O incidente já aconteceu: em 09/09/2026 havia 64 cliques em
--     "Nao tenho interesse" e 47 leads distintos ainda com opt_out = false, porque
--     meta_parser.py:138-154 jogava fora a identidade do botão e ninguém aplicava
--     opt-out a partir de um clique. Sem estas colunas, corrigir isso
--     retroativamente (scripts/recuperacao/honrar_optouts_pendentes.sql) produziria
--     47 booleanos indistinguíveis de opt-out declarado pelo próprio cliente hoje.
--
-- Nenhuma coluna é NOT NULL: os opt-outs anteriores a esta migração não têm
-- evidência, e forjar uma seria pior do que admitir a lacuna.
ALTER TABLE leads
  ADD COLUMN IF NOT EXISTS opt_out_at       timestamptz NULL,
  ADD COLUMN IF NOT EXISTS opt_out_channel  text        NULL,
  ADD COLUMN IF NOT EXISTS opt_out_evidence jsonb       NULL;

COMMENT ON COLUMN leads.opt_out_at IS
  'Quando a oposição foi registrada (UTC). NULL com opt_out=true = opt-out anterior a 09/09/2026, sem data conhecida.';

COMMENT ON COLUMN leads.opt_out_channel IS
  'Por onde a pessoa se opôs: whatsapp_button | whatsapp_texto | manual_crm | email | telefone. Vocabulário nosso, minúsculo, sem acento.';

COMMENT ON COLUMN leads.opt_out_evidence IS
  'Prova do pedido de oposição. Chaves usuais: source, clicked_at, button_label, button_payload, message_id, wamid, conversation_id, by. É o que se mostra à ANPD — preencher, nunca sobrescrever.';

-- ===========================================================================
-- 3. Nota sobre as tags de desfecho
-- ===========================================================================
-- Elas NÃO são semeadas aqui. Vivem em 20260820_button_flow_agent.sql §4, que foi
-- corrigida em 09/09/2026 para os nomes atuais ("Recuperação: ...", prazos em dias).
-- O comentário de backend/app/button_flow/flows.py:34 apontava para ESTE arquivo e
-- foi corrigido em 09/09/2026 para apontar para lá. Aplicar as duas juntas.

-- PostgREST guarda o schema em cache: sem o reload, um UPDATE em leads com
-- opt_out_at responde PGRST204 ("column not found") mesmo com a coluna já criada.
NOTIFY pgrst, 'reload schema';
