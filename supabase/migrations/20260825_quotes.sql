-- supabase/migrations/20260825_quotes.sql
--
-- Orcamento = proposta comercial no Bling.
-- Spec: docs/superpowers/specs/2026-08-25-orcamento-proposta-comercial-design.md (§3 e §6).
--
-- NAO E APLICADA PELO DEPLOY. O GitHub Actions sobe imagem, nao roda migration:
-- este arquivo precisa ser executado a mao no SQL editor do Supabase, ANTES do
-- push que leva /orcamento para producao. Sem ele a tabela nao existe e toda
-- chamada de orcamento morre em PGRST205 — inclusive a leitura da tela, que
-- abriria vazia sem erro visivel para o vendedor.
--
-- Reexecutar e seguro: tabelas e indices sao IF NOT EXISTS, as policies sao
-- recriadas com DROP antes, e o bloco 3 (etapa nova do funil) tem guarda propria.
-- A guarda do bloco 3 nao e zelo: sem ela, cada nova execucao empurraria
-- `fechado_ganho` mais uma casa para baixo e criaria uma coluna duplicada no
-- Kanban de todo funil.
--
-- Nomes de coluna de `pipeline_stages` conferidos em 012_multi_pipeline.sql:
-- (id, pipeline_id, label, key, dot_color, order_index, is_protected, created_at).
-- Batem com o enunciado da tarefa; a tabela nao tem `updated_at`.

-- ===========================================================================
-- 1. quotes
-- ===========================================================================
-- `created_by` guarda o e-mail do usuario do CRM, igual a `sales.sold_by` — e o
-- escopo por vendedor (§8) compara e-mail com e-mail. Aqui a regra e mais simples
-- que a de `sales`: nao existe a excecao `origin='bling'`, porque proposta criada
-- direto no ERP nao e sincronizada (decisao 17). Logo, orcamento sem `created_by`
-- fica invisivel para todo mundo que nao for admin — o frontend TEM que preencher.
--
-- O trio desconto (`discount_value` + `discount_unit` + `discount_input`) existe
-- porque as duas pontas querem coisas diferentes: o Bling e o total precisam do
-- valor em REAIS, e a tela precisa reexibir o que foi digitado. Guardar so os
-- reais faria "10" digitado como 10% reabrir como "57,10" na edicao; guardar so a
-- entrada obrigaria a recalcular o desconto a cada leitura, com risco de o total
-- gravado e o exibido divergirem por um centavo.
--
-- `status` e vocabulario NOSSO (rascunho | enviado | aprovado | nao_aprovado |
-- convertido | cancelado), sem acento e em caixa baixa. A situacao do Bling tem
-- acento e caixa propria ('Nao aprovado', 'Rascunho') e vive em `bling_situacao`,
-- como espelho da ultima situacao que conseguimos enviar. Sao campos distintos de
-- proposito: o PATCH de situacao pode falhar sem invalidar o estado local.
CREATE TABLE IF NOT EXISTS quotes (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id               uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  deal_id               uuid REFERENCES deals(id) ON DELETE SET NULL,
  conversation_id       uuid,
  created_by            text,
  quoted_at             date NOT NULL,
  status                text NOT NULL DEFAULT 'rascunho',
  -- UNICO: a criacao no Bling e retentavel (rede, 429, token expirado). O indice
  -- e a defesa estrutural contra a mesma proposta do ERP aparecer em dois
  -- orcamentos — mesmo papel que `sales_bling_order_id_key` faz para o pedido.
  bling_proposal_id     bigint UNIQUE,
  -- O POST devolve so `{data:{id}}`; o numero que sai no PDF vem de um GET
  -- seguinte, best-effort. Por isso e NULLABLE: GET falhando nao pode derrubar
  -- um orcamento que ja existe no ERP.
  bling_proposal_number integer,
  bling_contact_id      bigint,
  bling_situacao        text,
  subtotal              numeric(12,2) NOT NULL DEFAULT 0,
  discount_value        numeric(12,2) NOT NULL DEFAULT 0,
  discount_unit         text NOT NULL DEFAULT 'REAL',
  discount_input        numeric(12,3) NOT NULL DEFAULT 0,
  freight               numeric(12,2) NOT NULL DEFAULT 0,
  freight_mode          smallint,
  total                 numeric(12,2) NOT NULL DEFAULT 0,
  payment_method_id     bigint,
  payment_terms         text,
  notes                 text,
  internal_notes        text,
  -- ON DELETE SET NULL, nao CASCADE: apagar a venda nao pode apagar a proposta
  -- que a originou. O orcamento continua sendo o documento que foi ao cliente;
  -- `converted_at` preserva o carimbo mesmo se o vinculo cair.
  sale_id               uuid REFERENCES sales(id) ON DELETE SET NULL,
  converted_at          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

-- lead_id: a aba Perfil de /conversas lista os orcamentos do lead a cada abertura.
CREATE INDEX IF NOT EXISTS quotes_lead_id_idx    ON quotes (lead_id);
-- created_by: TODA consulta de vendedor nao-admin filtra por aqui (§8).
CREATE INDEX IF NOT EXISTS quotes_created_by_idx ON quotes (created_by);
-- quoted_at DESC: ordenacao padrao da tabela de /orcamento e recorte de periodo
-- dos quatro indicadores.
CREATE INDEX IF NOT EXISTS quotes_quoted_at_idx  ON quotes (quoted_at DESC);
-- status: filtro de situacao e denominador da taxa de aprovacao.
CREATE INDEX IF NOT EXISTS quotes_status_idx     ON quotes (status);

-- ===========================================================================
-- 2. quote_items
-- ===========================================================================
-- Espelha `sale_items` (20260818) e acrescenta `unidade`, que o item da proposta
-- comercial exige no payload do Bling e o PDF imprime na coluna "Un".
-- `desconto_percentual` e o desconto POR ITEM (o Bling recebe percentual no item);
-- o desconto de cabecalho, em reais, mora em `quotes.discount_value`. Misturar os
-- dois no mesmo campo faria o total sair errado nos dois lados.
CREATE TABLE IF NOT EXISTS quote_items (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  quote_id            uuid NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
  bling_product_id    bigint,
  codigo              text,
  descricao           text NOT NULL,
  unidade             text,
  quantidade          numeric(14,3) NOT NULL,
  valor_unitario      numeric(12,2) NOT NULL,
  desconto_percentual numeric(6,3) NOT NULL DEFAULT 0,
  total               numeric(12,2) NOT NULL,
  ordem               integer NOT NULL DEFAULT 0
);
-- Os itens sao sempre lidos pelo pai (embed do PostgREST e montagem do PDF).
CREATE INDEX IF NOT EXISTS quote_items_quote_id_idx ON quote_items (quote_id);

-- ===========================================================================
-- 3. RLS
-- ===========================================================================
-- Mesmo padrao de `sale_items`: RLS ligado + SELECT para authenticated. A escrita
-- fica so no service_role (backend e rotas do Next), que ignora RLS por natureza.
-- O escopo por vendedor NAO e feito aqui de proposito — ele e aplicado na API,
-- exatamente como `sales` ja funciona hoje. Duplicar a regra em policy criaria
-- duas fontes de verdade que divergem no primeiro ajuste de escopo.
ALTER TABLE quotes      ENABLE ROW LEVEL SECURITY;
ALTER TABLE quote_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS quotes_select      ON quotes;
DROP POLICY IF EXISTS quote_items_select ON quote_items;

CREATE POLICY quotes_select      ON quotes      FOR SELECT TO authenticated, service_role USING (true);
CREATE POLICY quote_items_select ON quote_items FOR SELECT TO authenticated, service_role USING (true);

-- updated_at automatico. A funcao generica `public.set_updated_at()` ja existe
-- desde 20260618_products_catalog.sql (e e reusada por `bling_jobs` em
-- 20260818_bling_integration.sql) — reaproveitada, nao recriada, para nao haver
-- duas versoes da mesma regra. `quote_items` nao tem `updated_at`: o item nunca e
-- editado no lugar, o PUT do orcamento troca a lista inteira.
DROP TRIGGER IF EXISTS quotes_set_updated_at ON quotes;
CREATE TRIGGER quotes_set_updated_at
  BEFORE UPDATE ON quotes
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ===========================================================================
-- 4. Etapa nova do funil: "Proposta Enviada" (§6 da spec)
-- ===========================================================================
-- Por que a etapa nasce com `key` propria enquanto quase todas as outras tem
-- `key IS NULL`: os funis sao por usuario e os rotulos variam de funil para funil
-- ("Proposta", "Quente (Fechar)", "Morno"...). Achar a etapa por posicao ou por
-- rotulo seria adivinhacao; com key o movimento do card ao criar um orcamento e
-- deterministico em qualquer funil.
--
-- O rotulo e "Proposta Enviada", nao "Proposta", porque o funil padrao ja tem uma
-- "Proposta" sem key na terceira posicao — duas colunas com o mesmo nome no Kanban
-- seriam indistinguiveis para o vendedor.
--
-- Uma unica instrucao, de proposito. `alvo` e avaliado no snapshot ANTERIOR ao
-- UPDATE (sub-statements de um WITH nao enxergam os efeitos uns dos outros), entao
-- `a.order_index` no INSERT ainda e a posicao original da `fechado_ganho` — sem
-- precisar do "-1" que seria necessario se o INSERT relesse a tabela ja deslocada.
-- CTE que modifica dados roda sempre e ate o fim, mesmo que a consulta principal
-- nao leia a saida dela: o deslocamento acontece garantidamente.
--
-- A guarda NOT EXISTS vive dentro de `alvo`, o que torna deslocamento e insercao
-- idempotentes JUNTOS. Se a guarda ficasse so no INSERT, uma segunda execucao
-- pularia a insercao mas ainda deslocaria tudo uma casa — o pior dos dois mundos.
--
-- O join produz no maximo uma `fechado_ganho` por funil porque
-- `idx_pipeline_stages_key_unique` (pipeline_id, key) e UNICO. Funil sem
-- `fechado_ganho` (existem, com key 'perdido'/'novo' apenas) simplesmente nao
-- entra em `alvo` e fica intocado.
WITH alvo AS (
  SELECT ganho.pipeline_id, ganho.order_index
    FROM pipeline_stages ganho
   WHERE ganho.key = 'fechado_ganho'
     AND NOT EXISTS (
           SELECT 1
             FROM pipeline_stages ja
            WHERE ja.pipeline_id = ganho.pipeline_id
              AND ja.key = 'proposta_enviada'
         )
),
deslocadas AS (
  UPDATE pipeline_stages ps
     SET order_index = ps.order_index + 1
    FROM alvo a
   WHERE ps.pipeline_id = a.pipeline_id
     AND ps.order_index >= a.order_index
  RETURNING ps.id
)
INSERT INTO pipeline_stages (pipeline_id, label, key, dot_color, order_index, is_protected)
SELECT a.pipeline_id, 'Proposta Enviada', 'proposta_enviada', '#9b7abf', a.order_index, false
  FROM alvo a;

-- PostgREST so enxerga tabela nova depois de recarregar o cache de schema; sem
-- isto, `quotes` responde PGRST205 mesmo ja existindo no banco.
NOTIFY pgrst, 'reload schema';
