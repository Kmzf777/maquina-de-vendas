-- 20261005_follow_up_jobs_joao_unico.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem; esta migration roda a
--    MAO, depois de lida e revisada por um humano.
--
-- ⚠️ PRE-CONDICAO: a limpeza das duplicatas de 03-04/10/2026 JA RODOU. Com as
--    duplicatas na tabela o indice unico nao consegue ser criado (e falha sem efeito
--    colateral nenhum — e so rodar de novo depois da limpeza).
--
-- ⚠️ CONCURRENTLY nao roda dentro de transacao: no SQL editor, rode UM comando por vez.
--
-- ── O INCIDENTE ─────────────────────────────────────────────────────────────
-- No fim de semana de 03-04/10/2026 o agendador das cadencias do Joao criou
-- 1.019.281 jobs `pending` para 467 leads. A trava que impede uma segunda matricula
-- do mesmo card mora no Python (`motivo_para_pular_joao`, regra "cadencia em
-- andamento"), e ela ficou cega: a leitura dos jobs existentes parava no corte de
-- 1.000 linhas do PostgREST, e o card cujo job aberto ficava depois do corte era
-- matriculado de novo a cada tick de 30 segundos. O Python foi corrigido (leitura
-- paginada). Este indice e a trava que nao depende do Python acertar.
--
-- ── 1. UMA MATRICULA ABERTA POR CARD, NO BANCO ──────────────────────────────
-- Um card (lead + deal) nao pode ter dois jobs ABERTOS do mesmo tipo e do mesmo
-- toque. Por construcao do agendador isso so acontece numa matricula duplicada:
--   * a matricula grava os toques 1..N e o job de mover com sequence N+1 — unicos
--     dentro dela;
--   * a cadencia que se repete ("Em atencao") cria UM job por passagem, e so depois
--     de o anterior ter saido (a regra "cadencia em andamento" barra antes).
-- `processing` entra no recorte: um job reivindicado ainda e uma matricula aberta.
--
-- O EFEITO quando o Python errar de novo: o INSERT em lote da passagem falha inteiro
-- com 23505, `_varrer_cadencia_joao` loga o erro e devolve 0 — nenhum card entra
-- naquela passagem. E fail-closed, e visivel no log; o outro lado e um milhao de jobs.
create unique index concurrently if not exists uq_follow_up_jobs_joao_aberto
    on public.follow_up_jobs (lead_id, job_type, (coalesce(metadata->>'deal_id', '')), sequence)
    where status in ('pending', 'processing') and job_type like 'joao\_%';

-- ── 2. INDICE POR LEAD ──────────────────────────────────────────────────────
-- `follow_up_jobs` nao tinha indice nenhum por `lead_id`. As tres leituras de que a
-- idempotencia do Joao depende filtram por lead (`_jobs_joao_dos_leads`,
-- `processar_resposta_joao` e a guarda de template repetido no envio), e com a
-- tabela inchada pelo incidente cada uma virava varredura sequencial de 1M+ linhas —
-- os statement timeouts medidos em 05/10. Com a leitura agora PAGINADA, sem este
-- indice cada pagina repetiria a varredura.
create index concurrently if not exists idx_followup_jobs_lead
    on public.follow_up_jobs (lead_id, job_type);
