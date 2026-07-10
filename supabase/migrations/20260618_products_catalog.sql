-- backend/migrations/20260618_products_catalog.sql
--
-- Catálogo de produtos para grounding dinâmico da IA (Valéria).
-- Substitui a tabela de preços estática embutida nos prompts por uma fonte de
-- verdade no banco. A equipe de operações popula esta tabela via upload manual de
-- CSV no painel do Supabase; o backend (service-role) lê em runtime e injeta o
-- catálogo nas System Instructions do Gemini para evitar alucinação de preços/produtos.
--
-- `sector` mapeia para o FUNIL/STAGE da conversa (atacado, private_label, exportacao,
-- consumo). O serviço de leitura normaliza (acento/caixa/espaço) então "Private Label",
-- "private_label" e "Atacado" casam com a stage correspondente.
--
-- `image_urls` é texto com URLs separadas por ponto e vírgula (`;`) — formato amigável
-- para preenchimento manual via CSV. O serviço limpa e separa na leitura.

CREATE TABLE IF NOT EXISTS public.products (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    sector          text        NOT NULL,            -- funil: 'Private Label', 'Atacado', 'Exportacao', 'Consumo'
    name            text        NOT NULL,            -- nome do produto
    price_formatted text,                            -- ex.: 'R$ 26,70'
    min_lot         text,                            -- ex.: '100 un'
    description     text,                            -- detalhes adicionais
    image_urls      text,                            -- URLs separadas por ';'
    is_active       boolean     NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Índice para o caminho de leitura quente: filtro por funil + ativo.
CREATE INDEX IF NOT EXISTS products_sector_active_idx
    ON public.products (sector, is_active);

-- ---------------------------------------------------------------------------
-- updated_at automático
-- ---------------------------------------------------------------------------
-- Função genérica e idempotente (CREATE OR REPLACE) — pode ser reutilizada por
-- outras tabelas futuramente. Mantém updated_at coerente mesmo em UPDATEs feitos
-- direto pelo painel do Supabase, fora do código da aplicação.
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS products_set_updated_at ON public.products;
CREATE TRIGGER products_set_updated_at
    BEFORE UPDATE ON public.products
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------
-- Segurança padrão do Supabase: RLS ligado + política explícita de leitura.
-- O service-role (usado pelo backend) ignora RLS por natureza, mas a política
-- abaixo também libera SELECT para usuários autenticados (ex.: futura leitura no
-- frontend). Escrita permanece restrita ao service-role / painel (sem policy de
-- INSERT/UPDATE/DELETE para authenticated).
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS products_select_authenticated ON public.products;
CREATE POLICY products_select_authenticated
    ON public.products
    FOR SELECT
    TO authenticated, service_role
    USING (true);
