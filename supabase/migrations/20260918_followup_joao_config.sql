-- 20260918_followup_joao_config.sql
--
-- ⛔ NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem; esta migration roda a
--    MAO no SQL editor do Supabase, depois de lida e revisada por um humano.
--    Nenhum agente de IA deve aplica-la.
--
-- ── O QUE FAZ ───────────────────────────────────────────────────────────────
-- Cria as DUAS tabelas de sobreposicao da configuracao das cadencias de follow-up do
-- vendedor Joao. Spec: docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md
-- (§5). A definicao continua vivendo no codigo (`app/follow_up/cadence_joao.py`); o
-- banco so sobrepoe o que o dono do funil tem direito de editar.
--
--   followup_joao_cadencia   cadencia                 -> gatilho_dias, ativa
--   followup_joao_toque      (cadencia, linha, toque) -> dias, template_name
--
-- ── POR QUE ─────────────────────────────────────────────────────────────────
-- Ata da reuniao de 10/09/2026, 33:28: "45 dias, mas opcao do Joao editar o numero de
-- dias." O caminho anterior (as cadencias como campanhas do builder) nunca entregou
-- isso, e o caminho oposto — deixar tudo no codigo — obrigaria um deploy para cada
-- ajuste de prazo.
--
-- ── AS DUAS TABELAS NASCEM VAZIAS, E VAZIO VALE O CODIGO ───────────────────
-- Nao ha INSERT nenhum neste arquivo, de proposito. Semear as tabelas com os valores
-- do codigo faria o BANCO virar a origem: a partir do primeiro seed, um ajuste no
-- codigo passaria a brigar em silencio com a linha ja gravada, e quem lesse o codigo
-- nao saberia mais o que esta no ar. Ausencia de linha, e cada coluna NULL, querem
-- dizer a mesma coisa: vale o codigo. `resolver_cadencia` aplica essa regra campo a
-- campo — gravar so os dias nunca apaga o template do toque.
--
-- ── O QUE ESTA TABELA DELIBERADAMENTE NAO PERMITE ──────────────────────────
-- ADICIONAR ou REMOVER toque. A forma da cadencia (quantos toques, em que ordem)
-- continua sendo mudanca de codigo — e o que impede a tela de virar builder de novo,
-- que e o erro que este desenho corrige. A trava e estrutural, no CHECK
-- `followup_joao_toque_dentro_da_cadencia`: cada cadencia so aceita os numeros de
-- toque que ela realmente tem (Novo 1, Em conversa 1-7, Reposicao 1-4, Em atencao 1).
-- Sem ele, um INSERT com toque=9 seria aceito pelo banco e ignorado em silencio pelo
-- codigo — configuracao que a tela mostra e o motor nao executa.
--
-- ── O QUE ESTA MIGRATION NAO TOCA ──────────────────────────────────────────
-- Nada do que ja existe. Em especial, nao encosta na tabela de jobs do follow-up nem
-- em `campaigns`: o caminho `standard` da ValerIA e o unico follow-up que funciona em
-- producao (8.140 jobs na historia) e nao pode ser afetado por este ramo.
--
-- ── ESTADO INICIAL ─────────────────────────────────────────────────────────
-- Tudo nasce DESLIGADO (spec §7): sem linha em `followup_joao_cadencia`, `ativa` cai
-- no default do codigo, que e false nas quatro cadencias. Medido em 16/09/2026: no
-- instante em que uma cadencia liga, 888 cards ficam elegiveis de uma vez.
--
-- Reexecutar e seguro: tabelas com IF NOT EXISTS, policies recriadas com DROP antes,
-- trigger idempotente. Nenhuma instrucao apaga ou altera linha existente.

-- ===========================================================================
-- 1. followup_joao_cadencia — o que e editavel POR CADENCIA
-- ===========================================================================
-- Uma linha por cadencia (nao por linha de negocio): o prazo do gatilho e o mesmo nas
-- duas linhas (Atacado e Private Label), e ligar uma cadencia liga o desenho inteiro.
-- Ligar so metade seria uma quinta alavanca, fora do que o spec §5 autoriza.
--
-- `gatilho_dias` e `ativa` sao NULLABLE porque NULL e "nao sobreposto", nunca "false".
-- Um NOT NULL DEFAULT false aqui faria a ausencia de configuracao ser indistinguivel
-- de um desligamento deliberado.
CREATE TABLE IF NOT EXISTS followup_joao_cadencia (
  cadencia       text PRIMARY KEY,
  gatilho_dias   integer,
  ativa          boolean,
  atualizado_por text,
  updated_at     timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT followup_joao_cadencia_codigo_valido
    CHECK (cadencia IN ('novo', 'em_conversa', 'reposicao', 'em_atencao')),
  -- Zero dia no gatilho pegaria o card no instante em que ele entra na etapa — a
  -- cadencia inteira perderia o sentido de "parado ha N dias".
  CONSTRAINT followup_joao_cadencia_gatilho_positivo
    CHECK (gatilho_dias IS NULL OR gatilho_dias >= 1)
);

-- ===========================================================================
-- 2. followup_joao_toque — o que e editavel POR TOQUE
-- ===========================================================================
-- `dias` e contado a partir da MATRICULA (o disparo do gatilho), nunca do toque
-- anterior — e como `cadence.py` conta e e o numero que a tela mostra. Para a cadencia
-- que se repete ("Em atencao"), o `dias` do unico toque E o intervalo da repeticao:
-- foi assim que "uma mensagem a cada tres dias" (ata 38:08) ficou editavel sem abrir
-- uma coluna a mais.
--
-- `template_name` guarda o nome do template APROVADO na Meta. Quem valida se ele
-- existe e esta APPROVED e a API, na hora de LIGAR a cadencia — o banco so guarda o
-- texto.
CREATE TABLE IF NOT EXISTS followup_joao_toque (
  cadencia       text    NOT NULL,
  linha          text    NOT NULL,
  toque          integer NOT NULL,
  dias           integer,
  template_name  text,
  atualizado_por text,
  updated_at     timestamptz NOT NULL DEFAULT now(),

  PRIMARY KEY (cadencia, linha, toque),

  CONSTRAINT followup_joao_toque_linha_valida
    CHECK (linha IN ('atacado', 'private_label')),
  CONSTRAINT followup_joao_toque_numero_positivo
    CHECK (toque >= 1),
  CONSTRAINT followup_joao_toque_dias_positivo
    CHECK (dias IS NULL OR dias >= 0),

  -- A TRAVA. Espelha a contagem de toques de `app/follow_up/cadence_joao.py`, e a
  -- suite cruza os dois numeros: mudar a forma de uma cadencia no codigo sem mudar
  -- este CHECK deixa a suite vermelha antes de chegar no banco.
  CONSTRAINT followup_joao_toque_dentro_da_cadencia CHECK (
       (cadencia = 'novo'        AND toque = 1)
    OR (cadencia = 'em_conversa' AND toque BETWEEN 1 AND 7)
    OR (cadencia = 'reposicao'   AND toque BETWEEN 1 AND 4)
    OR (cadencia = 'em_atencao'  AND toque = 1)
  )
);

-- ===========================================================================
-- 3. RLS e updated_at
-- ===========================================================================
-- Mesmo contrato de 20260825_quotes.sql: leitura para o CRM autenticado, escrita pela
-- API com a service key (que passa por cima da RLS). A configuracao do follow-up nao
-- e dado de lead — nao ha escopo por vendedor a aplicar aqui.
ALTER TABLE followup_joao_cadencia ENABLE ROW LEVEL SECURITY;
ALTER TABLE followup_joao_toque    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS followup_joao_cadencia_select ON followup_joao_cadencia;
DROP POLICY IF EXISTS followup_joao_toque_select    ON followup_joao_toque;

CREATE POLICY followup_joao_cadencia_select ON followup_joao_cadencia
  FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY followup_joao_toque_select    ON followup_joao_toque
  FOR SELECT TO authenticated, service_role USING (true);

-- `public.set_updated_at()` ja existe no schema (002_crm_enrichment.sql) e e usada por
-- quotes/deals; reusar evita uma segunda versao da mesma regra.
DROP TRIGGER IF EXISTS followup_joao_cadencia_set_updated_at ON followup_joao_cadencia;
CREATE TRIGGER followup_joao_cadencia_set_updated_at
  BEFORE UPDATE ON followup_joao_cadencia
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS followup_joao_toque_set_updated_at ON followup_joao_toque;
CREATE TRIGGER followup_joao_toque_set_updated_at
  BEFORE UPDATE ON followup_joao_toque
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- O PostgREST serve o schema em cache: sem isto, tabela nova responde PGRST205 e a
-- tela de follow-up abre vazia, sem erro visivel para quem esta configurando.
-- Precedente: 20260825:195, 20260909:162, 20260910, 20260911.
NOTIFY pgrst, 'reload schema';

-- ===========================================================================
-- Conferencia depois de aplicar (nao altera nada)
-- ===========================================================================
-- Esperado: as duas tabelas existem e estao VAZIAS.
--
--   SELECT 'cadencia' AS tabela, count(*) FROM followup_joao_cadencia
--   UNION ALL
--   SELECT 'toque',              count(*) FROM followup_joao_toque;
