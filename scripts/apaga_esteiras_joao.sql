-- scripts/apaga_esteiras_joao.sql
--
-- ⛔ NÃO EXECUTAR SEM AUTORIZAÇÃO EXPLÍCITA DO DONO. Apaga linhas em
--    PRODUÇÃO. Nenhum agente de IA deve rodar este arquivo. Ele existe para
--    ser LIDO, revisado, autorizado e só então aplicado à mão por um humano:
--    primeiro o bloco "SELECT DE CONFERÊNCIA — ANTES" sozinho, e só depois
--    de ler o resultado o bloco BEGIN…COMMIT.
--
-- ── O QUE ELE FAZ ────────────────────────────────────────────────────────────
-- Apaga as 6 esteiras do João do sistema de automação de campanhas
-- (`campaigns`, supabase/migrations/20260527_automation_campaigns_schema.sql),
-- criadas pelo seed `app/campaigns/esteiras_joao.py` (reunião de 10/09/2026):
--
--     Esteira Joao — Novo (Atacado)                 status='draft'    3 nós
--     Esteira Joao — Novo (Private Label)           status='draft'    3 nós
--     Esteira Joao — Em conversa (Atacado)          status='draft'   16 nós
--     Esteira Joao — Em conversa (Private Label)    status='draft'   16 nós
--     Esteira Joao — Reposicao (Atacado)            status='draft'   10 nós
--     Esteira Joao — Reposicao (Private Label)      status='draft'   10 nós
--
-- (As contagens de nós vêm do grafo do seed — 3 + 16 + 10, vezes as duas
-- linhas, 58 nós no total. O SELECT de conferência abaixo mostra o número
-- real do banco; se divergir, PARE e revise antes de aplicar.)
--
-- ── POR QUE APAGAR ───────────────────────────────────────────────────────────
-- As três cadências do João foram montadas como CAMPANHAS do builder, e essa
-- abordagem foi abandonada em 18/09/2026 por um motivo concreto, provado em
-- simulação com o motor real: a esteira de Reposição morre no primeiro toque.
-- A ata manda mover o card para "Já chamado" ao tocar;
-- `automation/engine.py::_guard_broken` cancela a matrícula quando o card sai
-- da coluna que o gatilho vigia, e o motor NÃO distingue "o vendedor moveu"
-- de "a própria esteira moveu". O follow-up do João passou a rodar no
-- scheduler que já existe (`follow_up/scheduler.py`), como novos `job_type`
-- em `follow_up_jobs` — o mesmo lugar onde a ValerIA e outros quatro tipos já
-- rodam. Desenho completo em
-- docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md.
--
-- Deixar as duas máquinas vivas seria ter dois sistemas para o mesmo
-- trabalho, que é a doença que o projeto inteiro veio corrigir.
--
-- ── O SEED SAIU JUNTO (senão isto aqui não adianta) ──────────────────────────
-- `seed_esteiras_joao` rodava a cada start da API (`app/main.py`) e recriava
-- as 6 campanhas. Só apagar as linhas do banco não bastaria: elas voltariam no
-- próximo deploy. Por isso `app/campaigns/esteiras_joao.py` e a chamada de
-- startup foram REMOVIDOS do código no mesmo commit que criou este arquivo.
-- Aplicar este SQL contra uma versão da API que ainda tenha o seed é inútil.
--
-- `app/campaigns/esteiras.py` (as 4 esteiras GENÉRICAS, que valem para
-- qualquer instalação) continua existindo e continua semeando. Os nomes delas
-- começam com "Esteira — " (sem "Joao"), e este arquivo NÃO as toca: o WHERE
-- casa os 6 nomes EXATOS acima, nunca um padrão (`LIKE`/`ILIKE`) que pudesse
-- pegar "Esteira — Reposicao" ou qualquer outra campanha legítima.
--
-- ── EFEITO CASCATA (leia antes de aplicar) ──────────────────────────────────
-- `campaign_nodes.campaign_id` é `REFERENCES campaigns(id) ON DELETE CASCADE`
-- (20260527_automation_campaigns_schema.sql:22). Apagar as 6 linhas de
-- `campaigns` apaga em cascata os 58 nós delas — não é um DELETE separado
-- neste arquivo, é o Postgres cumprindo a FK. `campaign_enrollments` tem a
-- mesma FK em cascata, mas nenhuma das 6 tem matrícula (é a própria guarda do
-- WHERE abaixo), então a cascata não alcança matrícula nenhuma.
--
-- ── POR QUE É SEGURO ─────────────────────────────────────────────────────────
-- O DELETE exige, cumulativamente:
--   · name IN (...)     — os 6 nomes EXATOS, não um padrão
--   · status = 'draft'  — as 6 nasceram `draft` e nunca foram ativadas
--   · NOT EXISTS em campaign_enrollments — nenhuma delas nunca rodou para
--     lead nenhum. Medido em produção em 16/09/2026 (ver
--     scripts/apaga_campanhas_de_teste.sql): 16 campanhas no banco, 0 com
--     status='active' e 0 matrículas em toda a história. Se alguma ganhar uma
--     matrícula entre a escrita deste arquivo e a aplicação, ela sai do alvo
--     sozinha — e isso É o sinal de que a premissa mudou: algo rodou, e o
--     apagamento precisa ser repensado antes de continuar.
--
-- ── O QUE ESTE ARQUIVO NÃO FAZ ──────────────────────────────────────────────
-- Não mexe nas outras campanhas (esteiras genéricas, espelho da ValerIA, o
-- que mais houver). Não mexe em `leads`, `deals`, `sales`, `follow_up_jobs`
-- nem em tag alguma. Não apaga TEMPLATE nenhum: os 24 templates aprovados na
-- Meta em 13/09/2026 (`scripts/create_templates_esteiras_joao.py`) continuam
-- lá e são reaproveitados pelo motor novo. Não tem DROP, não tem TRUNCATE e
-- não tem DELETE sem WHERE.
--
-- NÃO É MIGRATION: não cria nem altera estrutura de tabela, e por isso não
-- pertence a `supabase/migrations/`. É uma correção pontual de DADO, aplicada
-- à mão após revisão, descartável depois de aplicada uma única vez. O GitHub
-- Actions só sobe imagem — nunca roda SQL, nem daqui nem de lá.
--
-- ── COMO APLICAR ─────────────────────────────────────────────────────────────
-- SQL puro, sem meta-comando de psql — roda direto no editor SQL do Supabase.
--   1. Rode o bloco "SELECT DE CONFERÊNCIA — ANTES" sozinho e confira: 6
--      linhas, matriculas=0 em todas, nos = 3/3/16/16/10/10.
--   2. Rode o bloco BEGIN…COMMIT inteiro de uma vez.
--   3. Rode o bloco "SELECT DE CONFERÊNCIA — DEPOIS" e confira: 0 linhas.

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — ANTES   (rodar sozinho, ler o resultado antes do BEGIN)
-- ===========================================================================
SELECT c.id,
       c.name,
       c.status,
       c.env_tag,
       c.created_at,
       (SELECT count(*) FROM campaign_nodes n WHERE n.campaign_id = c.id)       AS nos,
       (SELECT count(*) FROM campaign_enrollments e WHERE e.campaign_id = c.id) AS matriculas
  FROM campaigns c
 WHERE c.name IN (
         'Esteira Joao — Novo (Atacado)',
         'Esteira Joao — Novo (Private Label)',
         'Esteira Joao — Em conversa (Atacado)',
         'Esteira Joao — Em conversa (Private Label)',
         'Esteira Joao — Reposicao (Atacado)',
         'Esteira Joao — Reposicao (Private Label)'
       )
 ORDER BY c.name;
-- Esperado: 6 linhas, status='draft' e matriculas=0 em todas.
--
-- Atenção ao `env_tag`: o seed gerava um id determinístico POR AMBIENTE, e dev
-- e produção apontam para o MESMO Supabase. Se aparecerem 12 linhas (6 com
-- env_tag='production' e 6 com env_tag='dev'), os dois ambientes semearam — a
-- guarda de sanidade abaixo aborta nesse caso, de propósito, para você decidir
-- conscientemente se apaga os dois conjuntos.
--
-- Se alguma linha vier com matriculas > 0, PARE: significa que uma esteira
-- chegou a inscrever lead, a premissa deste arquivo está errada e o
-- apagamento precisa ser repensado (essa linha, aliás, não seria apagada — o
-- NOT EXISTS do DELETE a deixa de fora sozinha).

-- ===========================================================================
-- O APAGAMENTO
-- ===========================================================================
BEGIN;

-- Guarda de sanidade. Abortar aqui desfaz a transação inteira sem apagar nada
-- — nunca "pela metade".
--
-- O teto é `> 6` e não uma igualdade porque duas execuções legítimas podem ver
-- números diferentes: uma segunda passada (ou uma linha já removida à mão)
-- acharia menos de 6, e isso não é motivo para travar. Mais de 6 é: significa
-- que o WHERE passou a casar algo que não foram as seis esteiras do João —
-- dev e produção semeando o mesmo banco, por exemplo — e aí quem revisa
-- decide, não o script.
DO $$
DECLARE
  alvo integer;
BEGIN
  SELECT count(*) INTO alvo
    FROM campaigns c
   WHERE c.name IN (
           'Esteira Joao — Novo (Atacado)',
           'Esteira Joao — Novo (Private Label)',
           'Esteira Joao — Em conversa (Atacado)',
           'Esteira Joao — Em conversa (Private Label)',
           'Esteira Joao — Reposicao (Atacado)',
           'Esteira Joao — Reposicao (Private Label)'
         )
     AND c.status = 'draft'
     AND NOT EXISTS (
       SELECT 1 FROM campaign_enrollments e WHERE e.campaign_id = c.id
     );

  IF alvo = 0 THEN
    RAISE EXCEPTION 'nenhuma esteira do Joao encontrada -- ou ja foi apagada, ou o WHERE mudou, ou alguma ganhou matricula';
  END IF;
  IF alvo > 6 THEN
    RAISE EXCEPTION 'esperava no maximo 6 esteiras do Joao, achei % -- revise (dev e producao semeando o mesmo banco?) antes de continuar', alvo;
  END IF;

  RAISE NOTICE 'esteiras do Joao a apagar: % (dos 6 nomes exatos, draft, sem matricula)', alvo;
END $$;

-- campaign_nodes cai por ON DELETE CASCADE (ver seção acima) — nenhum
-- comando explícito para essa tabela é necessário nem escrito aqui.
DELETE FROM campaigns AS c
 WHERE c.name IN (
         'Esteira Joao — Novo (Atacado)',
         'Esteira Joao — Novo (Private Label)',
         'Esteira Joao — Em conversa (Atacado)',
         'Esteira Joao — Em conversa (Private Label)',
         'Esteira Joao — Reposicao (Atacado)',
         'Esteira Joao — Reposicao (Private Label)'
       )
   AND c.status = 'draft'
   AND NOT EXISTS (
     SELECT 1 FROM campaign_enrollments e WHERE e.campaign_id = c.id
   );

COMMIT;

-- ===========================================================================
-- SELECT DE CONFERÊNCIA — DEPOIS
-- ===========================================================================
-- Esperado: 0 linhas.
SELECT c.id, c.name, c.status, c.env_tag
  FROM campaigns c
 WHERE c.name IN (
         'Esteira Joao — Novo (Atacado)',
         'Esteira Joao — Novo (Private Label)',
         'Esteira Joao — Em conversa (Atacado)',
         'Esteira Joao — Em conversa (Private Label)',
         'Esteira Joao — Reposicao (Atacado)',
         'Esteira Joao — Reposicao (Private Label)'
       );

-- E as 4 esteiras genéricas de `app/campaigns/esteiras.py` continuam intactas.
-- Esperado: 4 linhas. (Listadas pelos nomes exatos, não por padrão — mesmo
-- critério do WHERE acima.)
SELECT c.name, c.status
  FROM campaigns c
 WHERE c.name IN (
         'Esteira — Novo sem resposta nossa',
         'Esteira — Novo, lead sumiu',
         'Esteira — Reposicao',
         'Esteira — Follow-up de proposta'
       )
 ORDER BY c.name;
