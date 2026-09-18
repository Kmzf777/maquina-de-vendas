-- 20260918_bloquear_lead.sql
-- "Bloquear lead" pelo CRM — alinha o histórico ao critério canônico de bloqueio.
-- Plano: docs/superpowers/plans/2026-09-18-bloquear-lead-plan.md (Task 1.1)
--
-- NÃO É APLICADA PELO DEPLOY. O GitHub Actions sobe imagem Docker; ele não roda
-- migration. Este arquivo é executado À MÃO no SQL editor do Supabase, e precisa
-- ser aplicado ANTES (ou junto) do deploy que traz o gate inbound — ver bloco 1.
--
-- Reexecutar é seguro: o UPDATE é idempotente por construção (o próprio filtro
-- `opt_out = false` esvazia o conjunto na segunda passada) e os índices entram
-- com IF NOT EXISTS.

-- ===========================================================================
-- 1. Backfill: quem já está na Blacklist passa a ter o booleano canônico
-- ===========================================================================
-- Este é exatamente o bloco que ficou COMENTADO em 20260616_leads_opt_out.sql:18-25,
-- como "backfill opcional". Deixou de ser opcional: o gate inbound consulta SÓ
-- `leads.opt_out` (é o caminho quente — roda em toda mensagem recebida, e o braço
-- "tem deal na Blacklist" custaria uma query por mensagem). Sem este UPDATE, todo
-- lead que foi para a Blacklist antes desta entrega — pelos 48 opt-outs retroativos
-- de scripts/recuperacao/honrar_optouts_pendentes.sql, por arrasto de card no
-- Kanban, ou pelo antigo POST /optout que nunca gravava o booleano — continuaria
-- entrando no CRM como se nada tivesse acontecido.
--
-- opt_out_at / opt_out_channel / opt_out_evidence ficam DE FORA de propósito: são
-- leads cuja prova nós não temos. Forjar data e canal aqui produziria uma evidência
-- que não se sustenta na ANPD, o que é pior que a lacuna — mesmo princípio já
-- adotado em 20260909_recuperacao_stages_optout.sql (o canal fica NULL quando a
-- origem não é dedutível).
UPDATE leads l
   SET opt_out = true
  FROM deals d
 WHERE d.lead_id = l.id
   AND d.pipeline_id = '8988e852-2836-4add-b023-4db4d6cd0e6e'  -- pipeline Blacklist
   AND l.opt_out = false;

-- ===========================================================================
-- 2. Índices de suporte
-- ===========================================================================
-- Parcial de propósito: bloqueado é a minoria absoluta da tabela, e o índice só
-- precisa responder "este lead está na lista?" / "quais estão?". Um índice cheio
-- sobre um boolean quase sempre false seria peso morto na escrita de todo lead.
CREATE INDEX IF NOT EXISTS idx_leads_opt_out ON leads(id) WHERE opt_out;

-- A listagem de /conversas passa a filtrar `status <> 'blocked'`, e o realtime
-- reage a UPDATEs de status. Já existe desde 007_multi_channel.sql:42 — repetido
-- aqui sob IF NOT EXISTS para que esta migration valha sozinha em qualquer banco
-- (homolog recriado do zero, por exemplo), sem custo se já estiver lá.
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);

-- ===========================================================================
-- 3. Recarrega o cache de schema do PostgREST
-- ===========================================================================
-- Sem isso o PostgREST segue servindo o schema antigo em memória e devolve
-- PGRST204 ("column not found") para colunas recém-criadas — o mesmo erro que o
-- caminho de degradação de `block_lead` existe para absorver.
NOTIFY pgrst, 'reload schema';
