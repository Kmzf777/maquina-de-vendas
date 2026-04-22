# Kanban de Oportunidades de Vendas

**Data:** 2026-04-02
**Status:** Aprovado

## Objetivo

Substituir a pagina `/vendas` (kanban de leads por `seller_stage`) por um kanban de **oportunidades de vendas (deals)**, introduzindo uma entidade separada do lead. Atualizar o dashboard e demais paginas para integrar com o novo modelo. Alinhado com CRMs de referencia (Kommo, Pipedrive).

## Modelo de Dados

### Nova tabela `deals`

```sql
CREATE TABLE deals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    title text NOT NULL,
    value numeric(12,2) DEFAULT 0,
    stage text NOT NULL DEFAULT 'novo',
    category text,  -- atacado, private_label, exportacao, consumo
    expected_close_date date,
    assigned_to text,
    closed_at timestamptz,
    lost_reason text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);

CREATE INDEX idx_deals_lead_id ON deals(lead_id);
CREATE INDEX idx_deals_stage ON deals(stage);
CREATE INDEX idx_deals_category ON deals(category);
```

### Estagios do deal

`novo` -> `contato` -> `proposta` -> `negociacao` -> `fechado_ganho` -> `fechado_perdido`

### Campos removidos do lead

- `seller_stage` (migrado para `deals.stage`)
- `sale_value` (migrado para `deals.value`)

### Migracao de dados existentes

```sql
INSERT INTO deals (lead_id, title, value, stage, created_at)
SELECT
  id,
  COALESCE(name, phone) || ' - Oportunidade',
  COALESCE(sale_value, 0),
  CASE seller_stage
    WHEN 'novo' THEN 'novo'
    WHEN 'em_contato' THEN 'contato'
    WHEN 'negociacao' THEN 'negociacao'
    WHEN 'fechado' THEN 'fechado_ganho'
    WHEN 'perdido' THEN 'fechado_perdido'
    ELSE 'novo'
  END,
  created_at
FROM leads
WHERE human_control = true
  AND seller_stage IS NOT NULL;

ALTER TABLE leads DROP COLUMN seller_stage;
ALTER TABLE leads DROP COLUMN sale_value;
```

## Kanban de Oportunidades (`/vendas`)

### Estrutura da pagina

- **Header:** "Oportunidades" com botao "+ Nova Oportunidade"
- **Barra de metricas:** Total no pipeline (R$), deals abertos, taxa de conversao, valor ganho no mes
- **Filtros:** busca por texto, filtro por categoria (atacado, PL, exportacao, consumo), filtro por responsavel
- **Kanban:** 6 colunas (Novo, Contato, Proposta, Negociacao, Fechado Ganho, Fechado Perdido)
- **Drag & drop:** arrastar deal entre colunas atualiza `deals.stage` (usa @dnd-kit/core ja instalado)

### Card do Deal

Cada card mostra:
- Titulo da oportunidade
- Nome do lead/empresa (via join com leads)
- Valor formatado (R$ X.XXX)
- Tag de categoria (cor por tipo)
- Dias no estagio (calculado de `updated_at`)
- Iniciais do responsavel (avatar)

### Interacoes

- **Click no card** -> abre sidebar de detalhes do deal (valor, lead vinculado, historico)
- **Botao no sidebar** -> abrir conversa com o lead (link para `/conversas`)
- **Drag & drop** -> mover entre estagios
- **Mover para "Fechado Perdido"** -> pede `lost_reason` num modal simples

### Criacao de Deal

- **No kanban:** botao "+ Nova Oportunidade" -> modal com: titulo, lead (autocomplete), valor, categoria, data prevista
- **No detalhe do lead:** botao "Criar Oportunidade" -> mesmo modal com lead pre-preenchido

## Dashboard atualizado

### KPIs migrados para deals

| KPI | Fonte anterior | Nova fonte |
|---|---|---|
| Total no funil | `leads.length` | deals com stage ativo |
| Valor ativo | `lead.sale_value` (stage != perdido/fechado) | `SUM(deals.value)` stage ativo |
| Valor ganho | `lead.sale_value` (seller_stage = fechado) | `SUM(deals.value)` stage = fechado_ganho |
| Valor perdido | `lead.sale_value` (seller_stage = perdido) | `SUM(deals.value)` stage = fechado_perdido |
| Leads hoje | `leads.created_at` | Mantem igual |
| Tempo medio resp. | `lead.first_response_at` | Mantem igual |

### Novos KPIs

- **Taxa de conversao:** deals ganhos / total de deals
- **Ticket medio:** valor medio dos deals ganhos
- **Ciclo de venda:** tempo medio entre criacao do deal e `closed_at`

### Funnel chart

Mostra estagios de deals: Novo -> Contato -> Proposta -> Negociacao -> Fechado Ganho. Com contagem e valor por estagio.

### FunnelMovement

Migrado para rastrear movimentacao de deals entre estagios.

## Integracao com outras paginas

### Leads (`/leads` e lead detail)

- Grid de leads: remove coluna `seller_stage` e `sale_value`. Adiciona coluna "Oportunidades" com contagem de deals ativos.
- Lead detail modal/sidebar: remove secao de `seller_stage`. Adiciona secao "Oportunidades" com lista dos deals vinculados (titulo, valor, stage) + botao "Criar Oportunidade".

### Conversas (`/conversas` e contact-detail)

- Contact detail: remove referencia a `seller_stage`. Mostra deal ativo mais recente (se houver) com valor e stage como badge.

### Qualificacao (`/qualificacao`)

- Sem mudancas. Continua usando `lead.stage` (estagio do agente IA).

### Campanhas

- Sem mudancas. Campanhas criam leads, nao deals.

## Componentes afetados

| Componente | Mudanca |
|---|---|
| `kanban-metrics-bar` | Reescrever para receber deals em vez de leads |
| `lead-detail-sidebar` | Remover seller_stage, adicionar lista de deals |
| `lead-detail-modal` | Idem |
| `lead-grid-card` | Remover seller_stage badge, adicionar deals count |
| `contact-detail` | Remover seller_stage, mostrar deal ativo |
| `dashboard/funnel-movement` | Migrar para deals |
| `lead-card` | Manter (usado na qualificacao), remover refs a seller_stage |
| `quick-add-lead` | Remover prop `sellerStage` |
| `constants.ts` | `SELLER_STAGES` -> `DEAL_STAGES` com novos estagios |

## Dados e queries

### Realtime

Hook `useRealtimeDeals()` seguindo padrao do `useRealtimeLeads()`:
- Subscribe na tabela `deals` via Supabase realtime
- Join com `leads` para nome/empresa/phone
- Retorna `{ deals, loading }`

### Queries principais

- **Kanban:** `SELECT deals.*, leads.name, leads.company, leads.phone FROM deals JOIN leads ON deals.lead_id = leads.id ORDER BY deals.updated_at DESC`
- **Dashboard KPIs:** Aggregations sobre deals (SUM, COUNT, AVG)
- **Lead detail:** `SELECT * FROM deals WHERE lead_id = ? ORDER BY created_at DESC`
- **Autocomplete de lead:** reutiliza hook `useRealtimeLeads()` existente

## Fora de escopo

- Automacao de criacao de deals (fica manual + via detalhe do lead)
- Atividades/tarefas dentro do deal
- Campos customizados no deal
- Permissoes por usuario/vendedor
