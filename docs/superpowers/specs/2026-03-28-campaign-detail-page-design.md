# Campaign Detail Page + Enhanced Campaign List — Design Spec

**Data:** 2026-03-28
**Status:** Aprovado

## Resumo

Duas mudanças na página de campanhas do CRM:
1. **Lista de campanhas melhorada** — cards expandidos com métricas de cadência, barra de progresso segmentada, e tags de configuração
2. **Página de detalhe de campanha** — acessível ao clicar numa campanha, com KPIs, config, tabs (Leads em Cadência / Steps / Atividade), e ações completas por lead

## Decisões de Design

| Decisão | Escolha |
|---------|---------|
| Layout da página de detalhe | Dashboard + Tabs (KPIs no topo, tabs abaixo) |
| Edição de steps | Modal (botão "Configurar Cadência" abre modal por stage) |
| Ações nos leads | Completas — pausar, retomar, resetar, mudar stage, conversa, humano |
| Design system | Segue padrões existentes: fundo creme #f6f7ed, KPIs escuros #1f1f1f, cards brancos, DM Sans, olive accent #c8cc8e |

## Design System (referência)

Valores do `globals.css` existente:

| Token | Valor | Uso |
|-------|-------|-----|
| --bg-canvas | #f6f7ed | Background principal |
| --bg-card | #ffffff | Cards, tabelas |
| --bg-dark | #1f1f1f | KPI cards, sidebar, botão primário |
| --border-subtle | #ededea | Bordas de cards |
| --border-default | #e5e5dc | Bordas de inputs, pills |
| --text-primary | #1f1f1f | Texto principal |
| --text-secondary | #5f6368 | Texto secundário |
| --text-muted | #9ca3af | Texto desabilitado |
| --accent-olive | #c8cc8e | Accent principal |
| --accent-green | #4ade80 | Sucesso/responderam |
| --accent-red | #f87171 | Erro/esgotados |
| border-radius | 16px cards, 10px buttons/inputs | Cantos arredondados |
| canvas-texture | noise SVG com opacity 0.015 | Textura de fundo |

## 1. Lista de Campanhas (melhorada)

### Layout

Substitui a tabela atual por cards empilhados verticalmente. Cada card contém:

**Topo:** Nome + badge de status + data de criação + template + ações rápidas (Iniciar/Pausar + Abrir)

**Centro:** Grid 6 colunas com métricas:
- Total Leads
- Templates Enviados
- Responderam (verde)
- Em Cadência (amber)
- Esgotados (vermelho)
- Esfriados (cinza)

**Rodapé:** Barra de progresso segmentada (responderam/cadência/esgotados/enviados) + tags de config (intervalo, janela, max msgs)

### Dados necessários

A query de campanhas precisa incluir os novos campos: `cadence_sent`, `cadence_responded`, `cadence_exhausted`, `cadence_cooled`, `cadence_interval_hours`, `cadence_send_start_hour`, `cadence_send_end_hour`, `cadence_max_messages`.

O hook `useRealtimeCampaigns` já faz `select("*")`, então os campos novos vêm automaticamente.

### Navegação

Clicar no card ou no botão "Abrir →" navega para `/campanhas/[id]`.

### Estilo dos cards

```
background: var(--bg-card)
border: 1px solid var(--border-subtle)
border-radius: 16px
box-shadow: 0 1px 3px rgba(31,31,31,0.04)
hover: translateY(-1px) + shadow aumentado
```

## 2. Página de Detalhe da Campanha

### Rota

`/campanhas/[id]` — nova página dinâmica.

### Header

- Link "← Campanhas" volta pra lista
- Nome da campanha (28px, bold) + badge de status
- Meta: data de criação, template, total de leads
- Ações: "Configurar Cadência" (abre modal) + "Pausar"/"Iniciar" (toggle)

### KPI Cards (6 cards, dark)

Mesma estética das páginas Qualificação e Vendas:

| KPI | Cor do valor | Subtítulo |
|-----|-------------|-----------|
| Total Leads | branco | — |
| Templates Enviados | branco | % do total |
| Responderam | verde #4ade80 | % dos enviados |
| Em Cadência | amber #f59e0b | % ativos |
| Esgotados | vermelho #f87171 | "bateram limite" |
| Esfriados | cinza #888 | "sem mais steps" |

Estilo:
```
background: var(--bg-dark)
border-radius: 16px
padding: 20px
label: 10px uppercase, #888
value: 28px bold
```

### Config Summary Bar

Barra horizontal abaixo dos KPIs mostrando configuração da campanha:
- Intervalo entre msgs
- Janela de envio
- Cooldown após resposta
- Max mensagens por lead
- Total de follow-ups enviados

Estilo: card branco com border-subtle.

### Tabs

3 tabs abaixo da config bar:

**Tab 1: Leads em Cadência** (default)
- Filtros por status: pills "Leads ativos" (default, dark), "Responderam", "Esgotados", "Esfriados"
- Busca por nome/empresa/telefone
- Tabela em card branco com colunas:
  - Lead (nome + telefone)
  - Stage (tag colorida: atacado=olive, private_label=roxo, exportacao=amber)
  - Status Cadência (dot + texto)
  - Progresso (N/total + mini progress bar)
  - Próximo Envio (datetime ou "Com a Valeria" se respondeu)
  - Ações (botões inline)

**Ações por status do lead:**
| Status | Ações disponíveis |
|--------|------------------|
| Ativo | Pausar, Conversa, Humano |
| Respondeu | Conversa, Humano |
| Esgotado | Resetar, Conversa |
| Esfriado | Resetar, Conversa |

**Tab 2: Steps de Cadência**
- Lista agrupada por stage
- Cada stage mostra seus steps numerados com o texto da mensagem
- Botão "Configurar Cadência" abre modal de edição

**Tab 3: Atividade**
- Timeline cronológica das últimas ações:
  - "Maria Silva respondeu" (com timestamp)
  - "Step 3 enviado para Pedro Santos"
  - "Joao Ferreira esgotou cadência"
- Dados: últimas mensagens da campanha com `sent_by='cadence'` + mudanças de status no `cadence_state`

### Modal "Configurar Cadência"

Abre ao clicar "Configurar Cadência":
- Accordion por stage (atacado, private_label, exportacao, consumo)
- Cada stage expande mostrando lista de steps com:
  - Número do step
  - Textarea com o texto da mensagem
  - Botão excluir step
  - Botão "+ Adicionar step" no final
- Seção de configuração geral:
  - Intervalo entre msgs (input numérico, horas)
  - Janela de envio (start/end hour)
  - Cooldown (horas)
  - Max mensagens (input numérico)
- Botão "Salvar" no rodapé do modal

### API Integration

**Dados da campanha:** `useRealtimeCampaigns` existente (já inclui campos de cadência)

**Leads em cadência:** Nova query — `cadence_state` com join em `leads` filtrado por `campaign_id`

**Steps:** GET `/api/campaigns/{id}/cadence` (endpoint já existe no backend)

**Ações nos leads:**
- Pausar cadência: PATCH no `cadence_state` → status = 'paused' (nova ação no backend, ou usar pause_cadence)
- Retomar: resume_cadence
- Resetar: DELETE cadence_state + reset lead
- Conversa: navegar para `/conversas?phone={phone}`
- Humano: PATCH lead → human_control = true

**CRUD dos steps:** POST/PUT/DELETE `/api/campaigns/{id}/cadence/{step_id}` (endpoints já existem)

**Config da campanha:** PUT `/api/campaigns/{id}` (precisa de endpoint de update no backend)

## 3. Tipos TypeScript

### Novos tipos necessários

```typescript
// Adicionar ao Campaign interface existente
interface Campaign {
  // ... campos existentes ...
  cadence_interval_hours: number;
  cadence_send_start_hour: number;
  cadence_send_end_hour: number;
  cadence_cooldown_hours: number;
  cadence_max_messages: number;
  cadence_sent: number;
  cadence_responded: number;
  cadence_exhausted: number;
  cadence_cooled: number;
}

// Novos tipos
interface CadenceStep {
  id: string;
  campaign_id: string;
  stage: string;
  step_order: number;
  message_text: string;
  created_at: string;
}

interface CadenceState {
  id: string;
  lead_id: string;
  campaign_id: string;
  current_step: number;
  status: 'active' | 'responded' | 'exhausted' | 'cooled';
  total_messages_sent: number;
  max_messages: number;
  next_send_at: string | null;
  cooldown_until: string | null;
  responded_at: string | null;
  created_at: string;
  leads?: Lead;  // joined
}
```

## 4. Componentes

| Componente | Responsabilidade |
|-----------|-----------------|
| `campanhas/page.tsx` | Lista de campanhas (refatorar de tabela pra cards) |
| `campanhas/[id]/page.tsx` | Página de detalhe (nova) |
| `components/campaign-card.tsx` | Card de campanha na lista (novo) |
| `components/campaign-kpis.tsx` | Grid de KPI cards (novo) |
| `components/cadence-leads-table.tsx` | Tabela de leads com filtros e ações (novo) |
| `components/cadence-steps-modal.tsx` | Modal de edição de steps (novo) |
| `components/cadence-activity.tsx` | Timeline de atividade (novo) |

## 5. Mockups

Mockups aprovados em `.superpowers/brainstorm/1886-1774671914/content/`:
- `campaign-detail-v2.html` — página de detalhe (aprovada)
- `campaign-list-mockup.html` — lista de campanhas (aprovada, adaptar ao design system)
