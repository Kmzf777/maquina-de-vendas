-- 20260926_followup_joao_ajustes.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem; esta migration roda a
--    MAO no SQL editor do Supabase, depois de lida e revisada por um humano.
--    Nenhum agente de IA deve aplica-la.
--
-- ── INDEPENDENTE, E ISSO E UMA DECISAO ──────────────────────────────────────
-- Esta migration nao referencia, nao le e nao altera nenhuma outra tabela: cria uma
-- so, do zero, e mais nada. Pode ser aplicada ANTES ou DEPOIS de qualquer outra
-- migration de configuracao do follow-up, em qualquer ordem, sem pre-condicao.
-- E de proposito: a outra migration deste mesmo ramo carrega uma pre-condicao
-- manual (tabelas na forma antiga que precisam sair primeiro) e ainda nao foi
-- aplicada. Acoplar as duas faria esta esperar por aquela sem nenhum motivo tecnico
-- — e o custo seria um numero que o dono do funil quer editar continuar so no
-- codigo, atras de um deploy.
--
-- ── O QUE FAZ ───────────────────────────────────────────────────────────────
-- Cria `followup_joao_ajustes`, a tabela chave/valor dos ajustes GLOBAIS do motor de
-- follow-up do vendedor Joao. Spec:
-- docs/superpowers/specs/2026-09-26-esteira-reposicao-design.md (§3.5).
--
--   followup_joao_ajustes   chave -> valor (integer)
--
-- ── POR QUE CHAVE/VALOR, E NAO COLUNAS NA TABELA DE CADENCIA ───────────────
-- Porque estes dois numeros NAO SAO POR CADENCIA — sao do MOTOR inteiro:
--
--   chave                    default de codigo   o que e
--   ────────────────────────────────────────────────────────────────────────
--   teto_diario_disparos     100                 maximo de templates por dia,
--                                                somando as 5 esteiras do Joao
--   adiamento_estoque_dias   30                  espera do botao "Ainda tenho
--                                                estoque" (era 60 ate 26/09/2026)
--
-- Guardar um teto que vale para as cinco esteiras dentro da linha de UMA cadencia
-- criaria cinco copias do mesmo numero e a pergunta "qual delas vale?" — que e a
-- classe de ambiguidade que o ramo do Joao ja pagou caro uma vez (a string "atacado"
-- apontando para dois pipelines, spec 2026-09-21 §1).
--
-- ── POR QUE UM TETO DIARIO EXISTE ───────────────────────────────────────────
-- O teto que ja existia (`JOAO_TETO_PADRAO = 20`) e POR PASSAGEM, e o polling roda a
-- cada 30s: ate 2.400 matriculas por hora numa esteira. Medido em 16/09/2026, a
-- forma real disso foi "888 cards em 6 minutos". Os dois tetos convivem e resolvem
-- problemas diferentes — o por passagem protege contra varrer a base inteira numa
-- consulta; este limita VOLUME DE ENVIO por dia.
--
-- ── A TABELA NASCE VAZIA, E VAZIO VALE O CODIGO ────────────────────────────
-- Nao ha INSERT nenhum neste arquivo, de proposito — mesma disciplina das outras
-- tabelas de sobreposicao deste motor. Semear a tabela com os defaults faria o BANCO
-- virar a origem: a partir do primeiro seed, um ajuste no codigo passaria a brigar
-- em silencio com a linha ja gravada, e quem lesse o codigo nao saberia mais o que
-- esta no ar. Chave ausente e a MESMA coisa que "vale o default de codigo".
-- A leitura no backend (`carregar_ajustes_joao`) e FAIL-CLOSED para os defaults:
-- tabela inexistente, PostgREST fora do ar ou linha ausente caem todos no codigo,
-- nunca em zero. Um teto que virasse 0 por erro de leitura calaria o motor inteiro
-- sem nenhum sintoma visivel.
--
-- ── O QUE OS CHECKS TRAVAM ──────────────────────────────────────────────────
-- 1. A CHAVE. So as duas chaves acima sao aceitas. Sem isso, um erro de digitacao na
--    tela ("teto_diario" em vez de "teto_diario_disparos") gravaria uma linha que o
--    codigo nunca le: a tela mostraria o valor novo e o motor seguiria com o antigo,
--    que e o pior modo de falha de uma tela de configuracao.
-- 2. O VALOR >= 1. Zero, ou negativo, tem significados perigosos e DIFERENTES nas
--    duas chaves: teto 0 para o motor sem avisar ninguem; adiamento 0 faz o botao
--    "Ainda tenho estoque" nao adiar nada, e o toque seguinte sai por cima de quem
--    acabou de dizer que nao precisa. Recusar no banco e a ultima linha de defesa,
--    depois da recusa da API.
--
-- ── O QUE ESTA MIGRATION NAO TOCA ──────────────────────────────────────────
-- Nada do que ja existe. Em especial, nao encosta na tabela de jobs do follow-up:
-- o caminho `standard` da ValerIA e o unico follow-up que funciona em producao
-- (8.140 jobs na historia) e nao pode ser afetado por este ramo.
--
-- ── ESTADO INICIAL ─────────────────────────────────────────────────────────
-- A tabela nasce VAZIA — zero linha — e portanto os dois numeros valem exatamente o
-- que o codigo diz no dia em que isto for aplicado. Nenhuma esteira liga por causa
-- desta migration: o liga/desliga mora em outro lugar e continua desligado.
--
-- Reexecutar e seguro: tabela com IF NOT EXISTS, policies recriadas com DROP antes,
-- trigger idempotente. Nenhuma instrucao apaga ou altera linha existente.

-- ===========================================================================
-- 1. followup_joao_ajustes — os ajustes GLOBAIS do motor
-- ===========================================================================
-- `valor` e integer e NOT NULL: diferente das tabelas por-cadencia, aqui NULL nao
-- teria como significar "nao sobreposto" — a ausencia da LINHA ja diz isso. Uma
-- linha com valor NULL seria um terceiro estado sem significado declarado.
CREATE TABLE IF NOT EXISTS followup_joao_ajustes (
  chave          text    NOT NULL,
  valor          integer NOT NULL,
  atualizado_por text,
  updated_at     timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (chave),

  -- Estas duas chaves sao as MESMAS de `AJUSTES_PADRAO` (app/follow_up/service.py),
  -- e as duas listas sao fixadas pela suite, cada uma do seu lado. Uma chave que
  -- exista so de um lado e configuracao que a tela grava e o motor nunca le.
  CONSTRAINT followup_joao_ajustes_chave_valida CHECK (
    chave IN ('teto_diario_disparos', 'adiamento_estoque_dias')
  ),

  -- Ver "O QUE OS CHECKS TRAVAM", item 2: zero tem significado perigoso e diferente
  -- em cada uma das duas chaves, e em nenhuma delas e um valor util.
  CONSTRAINT followup_joao_ajustes_valor_positivo CHECK (valor >= 1)
);

-- ===========================================================================
-- 2. RLS e updated_at
-- ===========================================================================
-- Mesmo contrato das outras tabelas de configuracao do follow-up: leitura para o CRM
-- autenticado, escrita pela API com a service key (que passa por cima da RLS). A
-- configuracao do motor nao e dado de lead — nao ha escopo por vendedor a aplicar.
ALTER TABLE followup_joao_ajustes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS followup_joao_ajustes_select ON followup_joao_ajustes;

CREATE POLICY followup_joao_ajustes_select ON followup_joao_ajustes
  FOR SELECT TO authenticated, service_role USING (true);

-- `public.set_updated_at()` ja existe no schema (002_crm_enrichment.sql) e e usada
-- por quotes/deals; reusar evita uma segunda versao da mesma regra.
DROP TRIGGER IF EXISTS followup_joao_ajustes_set_updated_at ON followup_joao_ajustes;
CREATE TRIGGER followup_joao_ajustes_set_updated_at
  BEFORE UPDATE ON followup_joao_ajustes
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- O PostgREST serve o schema em cache: sem isto, tabela nova responde PGRST205 e a
-- tela de follow-up abre sem os campos novos, sem erro visivel para quem esta
-- configurando. Precedente: 20260825:195, 20260909:162, 20260910, 20260911.
NOTIFY pgrst, 'reload schema';

-- ===========================================================================
-- Conferencia depois de aplicar (nao altera nada)
-- ===========================================================================
-- Esperado: a tabela existe e esta VAZIA (0 linhas). Vazio e o estado correto —
-- significa "os dois numeros valem o default de codigo".
--
--   SELECT count(*) AS linhas FROM followup_joao_ajustes;
--
-- E a prova de que os dois CHECKS pegam (as duas devem FALHAR):
--
--   INSERT INTO followup_joao_ajustes (chave, valor) VALUES ('teto_diario', 50);
--   INSERT INTO followup_joao_ajustes (chave, valor) VALUES ('teto_diario_disparos', 0);
