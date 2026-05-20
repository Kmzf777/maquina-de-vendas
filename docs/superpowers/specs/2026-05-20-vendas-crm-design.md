# Sistema de Vendas CRM — Design Spec

**Data:** 2026-05-20  
**Status:** Aprovado

---

## Contexto e Objetivo

O CRM atual possui um Kanban de deals (`/vendas`) com estágio "Fechado Ganho". Porém, deals representam a jornada de prospecção — não o evento de compra. Para calcular ciclo de recompra, LTV e churn transacional, e criar campanhas baseadas em tempo desde a última compra, é necessário um registro dedicado de venda como evento.

Um lead pode comprar múltiplas vezes. Cada compra gera um registro `sale` com data. Os deals continuam existindo para gestão do pipeline; vendas são o registro dos eventos de compra efetivos.

---

## Modelo de Dados

### Tabela `sales` (Supabase)

```sql
CREATE TABLE sales (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id         uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  sold_at         timestamptz NOT NULL DEFAULT now(),
  value           numeric(12,2) NOT NULL,
  product         text NOT NULL,
  sold_by         uuid REFERENCES auth.users(id),
  deal_id         uuid REFERENCES deals(id) ON DELETE SET NULL,
  conversation_id uuid REFERENCES conversations(id) ON DELETE SET NULL,
  notes           text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_sales_lead_id_sold_at ON sales(lead_id, sold_at);
CREATE INDEX idx_sales_sold_at ON sales(sold_at);
CREATE INDEX idx_sales_sold_by ON sales(sold_by);
```

### Campos derivados (calculados na query, não armazenados)

- **Dias desde última compra** por lead: `now() - MAX(sold_at) WHERE lead_id = X`
- **Ciclo médio de recompra** por lead: média dos intervalos entre `sold_at` consecutivos
- **Faturamento do período**: `SUM(value) WHERE sold_at BETWEEN X AND Y`
- **LTV**: `SUM(value) GROUP BY lead_id`
- **Churn em risco**: `now() - MAX(sold_at) > ciclo_médio × 1.5`

---

## Interface `Sale` (TypeScript)

```typescript
interface Sale {
  id: string;
  lead_id: string;
  sold_at: string;
  value: number;
  product: string;
  sold_by: string | null;
  deal_id: string | null;
  conversation_id: string | null;
  notes: string | null;
  created_at: string;
  // joined
  leads?: { id: string; name: string | null; phone: string; company: string | null };
  sold_by_user?: { id: string; email: string; raw_user_meta_data?: { full_name?: string } };
  deals?: { id: string; title: string };
}
```

---

## Feature 1 — Registrar Venda no `/conversas`

### Localização

Aba **Perfil** do painel CRM direito (`crm-perfil-tab.tsx`), nova seção **"Vendas"** abaixo da seção "Oportunidades".

### Componentes

**`SalesSection`** (dentro de `crm-perfil-tab.tsx`):
- Título "Vendas" + botão `+ Registrar Venda`
- Lista das últimas 3 vendas do lead: `sold_at` (data), `product`, `value` formatado em R$
- Link "Ver todas" que navega para `/painel-vendas?lead_id=X`
- Atualização real-time via Supabase subscription

**`SaleCreateModal`** (componente novo):

| Campo | Tipo | Obrigatório |
|---|---|---|
| Produto/Serviço | text input | sim |
| Valor (R$) | number input | sim |
| Data da venda | date picker | sim (default: hoje) |
| Vendedor | select de usuários | não (default: usuário logado) |
| Observação | textarea | não |
| Vincular a deal | select dos deals abertos do lead | não |

### Fluxo de criação

1. Usuário clica `+ Registrar Venda`
2. Modal abre com `lead_id` e `conversation_id` pré-preenchidos
3. Usuário preenche produto + valor (mínimo)
4. Confirma → `POST /api/sales`
5. Se `deal_id` foi selecionado → `PATCH /api/deals/[id]` move para estágio "Fechado Ganho" automaticamente
6. Lista de vendas na aba Perfil atualiza via real-time
7. Modal fecha

---

## Feature 2 — Painel de Vendas `/painel-vendas`

### Rota

Nova página: `/app/(authenticated)/painel-vendas/page.tsx`

### Sidebar

Novo item no grupo **Vendas** (abaixo de "Funis de venda"):
- Label: "Painel de Vendas"
- Ícone: `TrendingUp` (lucide)
- Rota: `/painel-vendas`
- Visível para todos os roles (admin e vendedor)

### Layout da página

**Zona 1 — Métricas (topo, 4 cards lado a lado):**

| Card | Valor |
|---|---|
| Faturamento do mês | `SUM(value)` onde `sold_at` no mês atual |
| Nº de vendas | `COUNT(*)` no mês atual |
| Ticket médio | `AVG(value)` no mês atual |
| Ciclo médio de recompra | média dos intervalos entre compras, todos os leads |

**Zona 2 — Filtros:**
- Date range picker (default: mês atual)
- Select de vendedor (default: todos)
- Input de busca por produto ou lead (texto livre)

**Zona 3 — Tabela de vendas:**

Colunas: Data | Lead | Produto | Valor | Vendedor | Deal

- Ordenada por `sold_at DESC`
- Paginação: 25 itens por página
- "Lead" é clicável → abre conversa em `/conversas?lead_id=X`
- "Deal" exibe título do deal como link (se vinculado)
- Todos os roles veem todas as vendas (sem filtro por vendedor no backend)

### Componentes

- `SalesMetricsCards` — 4 cards de métricas
- `SalesFilters` — date range + select vendedor + busca
- `SalesTable` — tabela com paginação
- `useSales(filters)` — hook com fetch + real-time

---

## API Routes

### `GET /api/sales`
Query params: `lead_id?`, `sold_by?`, `from?`, `to?`, `search?`, `page?`, `limit?`  
Returns: `{ data: Sale[], count: number }`

### `POST /api/sales`
Body: `{ lead_id, sold_at, value, product, sold_by?, deal_id?, conversation_id?, notes? }`  
Returns: `Sale`  
Side effect: se `deal_id` presente, move deal para estágio "Fechado Ganho"

### `GET /api/sales/metrics`
Query params: `from?`, `to?`  
Returns: `{ total_value, count, avg_value, avg_repurchase_cycle_days }`

### `PATCH /api/sales/[id]`
Body: campos editáveis  
Returns: `Sale`

### `DELETE /api/sales/[id]`
Returns: `204`

### `GET /api/leads/[id]/sales`
Returns: `Sale[]` ordenado por `sold_at DESC`

---

## Comportamento Real-Time

Supabase subscription na tabela `sales`:
- `SalesSection` no `/conversas` recarrega quando `lead_id` corresponde
- `SalesTable` no `/painel-vendas` recarrega em qualquer mudança

---

## Integrações Futuras (fora do escopo deste MVP)

- **Disparo por tempo de recompra**: query `WHERE now() - MAX(sold_at) > N days GROUP BY lead_id` → enrollar em cadência
- **Churn em risco**: `ciclo_médio × 1.5` como threshold configurável
- **LTV por lead**: visible na aba Perfil do CRM
- **Produtos como entidade**: lista cadastrada em vez de texto livre
