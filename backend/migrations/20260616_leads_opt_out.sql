-- 20260616_leads_opt_out.sql
-- Adiciona a flag de opt-out definitivo (Hard Opt-out) na tabela leads.
--
-- Contexto: o descarte de leads passa a distinguir HARD OPT-OUT (lead proibiu o contato →
-- registrar_optout) de SOFT REJECTION (lead so nao quer comprar agora → registrar_sem_interesse_atual).
-- O Soft mantem opt_out=false (lead reativavel); o Hard seta opt_out=true + Blacklist.
--
-- Idempotente: seguro reaplicar. Aplicar em PROD e HOMOLOG (paridade de schema).

ALTER TABLE leads
    ADD COLUMN IF NOT EXISTS opt_out boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN leads.opt_out IS
    'Hard opt-out: lead proibiu explicitamente o contato. true = nao contatar (Blacklist). '
    'Soft rejection (sem interesse no momento) NAO seta isto — permanece false para reativacao futura.';

-- Backfill opcional (NAO incluido por padrao): marcar opt_out=true para leads ja na Blacklist.
-- Descomente para alinhar o historico com o novo modelo:
--
-- UPDATE leads l SET opt_out = true
-- FROM deals d
-- WHERE d.lead_id = l.id
--   AND d.pipeline_id = '8988e852-2836-4add-b023-4db4d6cd0e6e'  -- pipeline Blacklist
--   AND l.opt_out = false;
