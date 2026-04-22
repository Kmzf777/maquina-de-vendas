# Campanhas Redesign — Disparos + Cadências

## Objetivo

Substituir o sistema unificado de "campanhas" por dois conceitos independentes — **Disparos** (envio em massa de templates WhatsApp) e **Cadências** (sequências automatizadas de follow-up) — com dashboard unificado, triggers automáticos por funil, e presets de template reutilizáveis.

## Decisões de Design

| Decisão | Escolha |
|---------|---------|
| Separação de conceitos | Disparos e Cadências independentes |
| Escopo das cadências | Ambos funis (deals + qualificação) |
| Canal de disparo | Apenas templates Meta (oficial) |
| Templates | Selecionar da Meta + presets de variáveis salvos |
| Página campanhas | Dashboard unificado + tabs (Disparos / Cadências) |
| Builder de cadência | Lista simples + config |
| Triggers de cadência | Manual + por stage + por tempo (inatividade) |
| Métricas | KPIs (volume + resultado) + gráfico de tendência |
| Relação disparo→cadência | Opcional — vincular cadência no momento do disparo |
| Abordagem | Evolução incremental da infra existente |

---

## 1. Modelo de Dados

### 1.1 Tabelas Novas

**`broadcasts`** — Disparos em massa de templates WhatsApp

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid PK | |
| name | text NOT NULL | Nome do disparo (ex: "Promo Black Friday") |
| channel_id | uuid FK → channels | Canal Meta Cloud usado para envio |
| template_name | text NOT NULL | Nome do template aprovado na Meta |
| template_preset_id | uuid FK → template_presets NULL | Preset de variáveis (opcional) |
| template_variables | jsonb DEFAULT '{}' | Variáveis preenchidas para este disparo |
| total_leads | int DEFAULT 0 | Total de leads vinculados |
| sent | int DEFAULT 0 | Enviados com sucesso |
| failed | int DEFAULT 0 | Falhas de envio |
| delivered | int DEFAULT 0 | Entregues (confirmação Meta) |
| status | text DEFAULT 'draft' | draft, scheduled, running, paused, completed |
| scheduled_at | timestamptz NULL | Agendamento (se scheduled) |
| send_interval_min | int DEFAULT 3 | Intervalo mínimo entre envios (segundos) |
| send_interval_max | int DEFAULT 8 | Intervalo máximo entre envios (segundos) |
| cadence_id | uuid FK → cadences NULL | Cadência opcional para leads que não respondem |
| created_at | timestamptz DEFAULT now() | |
| updated_at | timestamptz DEFAULT now() | |

**`broadcast_leads`** — Leads vinculados a um disparo (many-to-many)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid PK | |
| broadcast_id | uuid FK → broadcasts ON DELETE CASCADE | |
| lead_id | uuid FK → leads ON DELETE CASCADE | |
| status | text DEFAULT 'pending' | pending, sent, failed, delivered |
| sent_at | timestamptz NULL | Quando foi enviado |
| error_message | text NULL | Mensagem de erro (se failed) |

UNIQUE(broadcast_id, lead_id).

**`cadences`** — Sequências de follow-up automatizadas

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid PK | |
| name | text NOT NULL | Nome da cadência (ex: "Follow-up Proposta") |
| description | text NULL | Descrição livre |
| target_type | text NOT NULL DEFAULT 'manual' | manual, lead_stage, deal_stage |
| target_stage | text NULL | Stage que dispara a cadência (ex: "proposta", "atacado") |
| stagnation_days | int NULL | Dias parado no stage para disparar (NULL = imediato ao entrar) |
| send_start_hour | int DEFAULT 7 | Início da janela de envio (BRT) |
| send_end_hour | int DEFAULT 18 | Fim da janela de envio (BRT) |
| cooldown_hours | int DEFAULT 48 | Cooldown após lead responder |
| max_messages | int DEFAULT 5 | Máximo de mensagens por lead |
| status | text DEFAULT 'active' | active, paused, archived |
| created_at | timestamptz DEFAULT now() | |
| updated_at | timestamptz DEFAULT now() | |

**`cadence_steps`** — Steps individuais da cadência (evolução da tabela existente)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid PK | |
| cadence_id | uuid FK → cadences ON DELETE CASCADE | |
| step_order | int NOT NULL | Ordem do step (1, 2, 3...) |
| message_text | text NOT NULL | Conteúdo da mensagem (suporta {{nome}}, {{empresa}}) |
| delay_days | int DEFAULT 0 | Dias de espera antes de enviar este step (0 = imediato) |
| created_at | timestamptz DEFAULT now() | |

UNIQUE(cadence_id, step_order).

**`cadence_enrollments`** — Estado de cada lead/deal numa cadência (substitui cadence_state)

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid PK | |
| cadence_id | uuid FK → cadences ON DELETE CASCADE | |
| lead_id | uuid FK → leads ON DELETE CASCADE | |
| deal_id | uuid FK → deals NULL | Deal vinculado (quando trigger é deal_stage) |
| broadcast_id | uuid FK → broadcasts NULL | Disparo de origem (quando veio de broadcast) |
| current_step | int DEFAULT 0 | Step atual (0 = não iniciou) |
| status | text DEFAULT 'active' | active, paused, responded, exhausted, completed |
| total_messages_sent | int DEFAULT 0 | Mensagens enviadas |
| next_send_at | timestamptz NULL | Próximo envio agendado |
| cooldown_until | timestamptz NULL | Em cooldown até |
| responded_at | timestamptz NULL | Quando respondeu |
| enrolled_at | timestamptz DEFAULT now() | Quando entrou na cadência |
| completed_at | timestamptz NULL | Quando completou/saiu |

UNIQUE(cadence_id, lead_id) — um lead só pode estar uma vez em cada cadência.

**`template_presets`** — Presets de variáveis reutilizáveis

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid PK | |
| name | text NOT NULL | Nome do preset (ex: "Promo Classico") |
| template_name | text NOT NULL | Template da Meta associado |
| variables | jsonb NOT NULL DEFAULT '{}' | Variáveis preenchidas |
| created_at | timestamptz DEFAULT now() | |
| updated_at | timestamptz DEFAULT now() | |

### 1.2 Tabelas Removidas

- **`campaigns`** — dados migrados para `broadcasts` e `cadences`
- **`cadence_state`** — dados migrados para `cadence_enrollments`

### 1.3 Tabelas Alteradas

- **`leads`** — remove coluna `campaign_id` (relação agora via `broadcast_leads`)
- **`messages`** — sem alteração, `sent_by='cadence'` continua funcionando

### 1.4 Migration Strategy

1. Criar tabelas novas (`broadcasts`, `broadcast_leads`, `cadences`, `cadence_steps` nova, `cadence_enrollments`, `template_presets`)
2. Migrar dados de `campaigns` → `broadcasts` (campos de disparo) + `cadences` (campos de cadência)
3. Migrar `cadence_state` → `cadence_enrollments`
4. Migrar relação `leads.campaign_id` → `broadcast_leads`
5. Manter `cadence_steps` existente e adicionar coluna `delay_days`
6. Drop tabelas antigas após validação
7. Enable realtime para `broadcasts`, `cadences`, `cadence_enrollments`

---

## 2. Página `/campanhas` — Layout

### 2.1 Estrutura

```
┌─────────────────────────────────────────────────┐
│  Campanhas                        [+ Disparo] [+ Cadência]  │
├─────────────────────────────────────────────────┤
│  KPIs Row (5 cards)                                         │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐             │
│  │Dispar│ │Cadênc│ │Leads │ │Taxa  │ │Deals │             │
│  │ativos│ │ativas│ │em    │ │de    │ │gerado│             │
│  │      │ │      │ │follow│ │resp. │ │s     │             │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘             │
├─────────────────────────────────────────────────┤
│  Gráfico de tendência (respostas últimos 30 dias)           │
├─────────────────────────────────────────────────┤
│  [Disparos]  [Cadências]     ← tabs                        │
│                                                             │
│  (conteúdo da tab ativa)                                    │
└─────────────────────────────────────────────────┘
```

### 2.2 Dashboard KPIs

| KPI | Fonte | Cálculo |
|-----|-------|---------|
| Disparos ativos | broadcasts | WHERE status IN ('running', 'scheduled') |
| Cadências ativas | cadences | WHERE status = 'active' |
| Leads em follow-up | cadence_enrollments | WHERE status = 'active' |
| Taxa de resposta | cadence_enrollments | responded / (responded + exhausted + completed) |
| Deals gerados | cadence_enrollments | WHERE deal_id IS NOT NULL AND status = 'responded' |

### 2.3 Gráfico de Tendência

Line chart com duas linhas nos últimos 30 dias:
- **Mensagens enviadas** (por dia) — count de messages WHERE sent_by='cadence' GROUP BY date
- **Respostas recebidas** (por dia) — count de cadence_enrollments WHERE responded_at GROUP BY date

Period selector: 7d, 30d, 90d.

### 2.4 Tab Disparos

Lista de broadcasts em cards com:
- Nome, template, status badge
- Progress bar (sent / total_leads)
- Métricas: enviados, entregues, falhas
- Cadência vinculada (se houver)
- Ações: Iniciar, Pausar, Duplicar, Excluir

Filtros: status (draft, running, completed), busca por nome.

### 2.5 Tab Cadências

Lista de cadences em cards com:
- Nome, descrição, status badge
- Trigger info: "Manual" ou "Quando deal entra em Proposta" ou "Após 3 dias em Negociação"
- Métricas: leads ativos, responderam, exauriram, completaram
- Steps count (ex: "4 steps, 12 dias total")
- Ações: Editar steps, Pausar, Arquivar, Duplicar

Filtros: status, target_type, busca por nome.

---

## 3. Criação de Disparo

Modal de 3 steps:

### Step 1 — Configuração
- Nome do disparo
- Canal (dropdown de canais Meta Cloud ativos)
- Template (dropdown listado da API Meta, com preview)
- Preset de variáveis (dropdown, opcional) — ao selecionar, preenche variáveis
- Variáveis do template (campos dinâmicos baseados no template)
- Opção "Salvar como preset" (checkbox + nome)
- Cadência vinculada (dropdown de cadências ativas, opcional)
- Agendamento (imediato ou data/hora)
- Intervalo entre envios (min/max segundos)

### Step 2 — Leads
Duas abas:
- **CRM**: Seletor de leads com filtros (stage, tags, temperatura)
- **CSV**: Import com drag-drop, validação de telefone, preview

### Step 3 — Revisão
- Resumo: template, variáveis, total de leads, cadência vinculada
- Preview da mensagem montada
- Botão "Criar Disparo" (status=draft) ou "Agendar" (status=scheduled)

---

## 4. Builder de Cadência

Página dedicada `/campanhas/cadencias/[id]` (ou modal fullscreen):

### 4.1 Header
- Nome editável
- Descrição editável
- Status badge + toggle (ativar/pausar)

### 4.2 Trigger Config
- Tipo: Manual / Quando lead entra no stage / Quando deal entra no stage
- Se stage: dropdown com stages do funil correspondente
- Se stagnation: campo "Após X dias parado" (number input)

### 4.3 Steps Table

| # | Mensagem | Delay | Ações |
|---|----------|-------|-------|
| 1 | Olá {{nome}}, tudo bem?... | Imediato | Editar, Remover |
| 2 | {{nome}}, conseguiu ver...  | 2 dias | Editar, Remover |
| 3 | Última tentativa... | 5 dias | Editar, Remover |
| [+ Adicionar step] | | | |

Cada step:
- `step_order`: número sequencial
- `message_text`: textarea com suporte a variáveis ({{nome}}, {{empresa}}, {{telefone}})
- `delay_days`: dias de espera antes de enviar (0 para primeiro step)

### 4.4 Configurações Globais
Row compacta com:
- Janela de envio: start_hour — end_hour (sliders ou dropdowns)
- Cooldown após resposta: X horas
- Máximo de mensagens: X

### 4.5 Enrollments Table (abaixo)
Tabela de leads/deals atualmente na cadência:
- Nome, telefone, stage, status, step atual, próximo envio
- Ações: pausar, remover, encaminhar para humano
- Filtro por status (active, paused, responded, exhausted, completed)

---

## 5. Triggers Automáticos

### 5.1 Por Stage (Imediato)

Quando `target_type = 'lead_stage'` ou `'deal_stage'` e `stagnation_days IS NULL`:

- **Backend listener**: No buffer processor (para leads) e na API de deals (para deals), ao detectar mudança de stage, verificar se existe cadência ativa com `target_stage` correspondente.
- Se existe e lead não está já enrolled nessa cadência → criar `cadence_enrollment` com status='active'.

### 5.2 Por Stage + Tempo (Stagnation)

Quando `stagnation_days IS NOT NULL`:

- **Scheduler job**: Roda periodicamente (a cada 5 min junto com o cadence scheduler existente).
- Query: leads/deals que estão no `target_stage` há mais de `stagnation_days` dias E não têm enrollment ativo nessa cadência.
- Para cada match → criar `cadence_enrollment`.

### 5.3 Via Disparo

Quando `broadcast.cadence_id IS NOT NULL`:

- Após template enviado com sucesso e lead não responde dentro do cooldown:
  - Worker cria `cadence_enrollment` com `broadcast_id` preenchido.
- Se lead responde ao template antes de entrar na cadência:
  - Não entra na cadência (verificação no buffer processor).

### 5.4 Safeguards

- Um lead só pode ter um enrollment ativo por cadência (UNIQUE constraint).
- Lead com `human_control = true` nunca entra em cadência automática.
- Lead que já respondeu a qualquer cadência nos últimos `cooldown_hours` não é re-enrolled.

---

## 6. Backend — Worker e Scheduler

### 6.1 Broadcast Worker (evolução do campaign worker)

Loop a cada 5 segundos:
1. Buscar broadcasts com `status = 'running'`
2. Para cada: buscar `broadcast_leads` com `status = 'pending'` (limit 10)
3. Enviar template via Meta Cloud API
4. Atualizar `broadcast_leads.status` e `broadcast.sent` counter
5. Se broadcast tem `cadence_id`: agendar enrollment pós-cooldown
6. Se não há mais pending leads → `status = 'completed'`

### 6.2 Cadence Scheduler (evolução do cadence scheduler)

Loop a cada 5 segundos (junto com broadcast worker):

**A. Process due sends:**
1. Buscar `cadence_enrollments` com `status = 'active'` e `next_send_at <= now`
2. Para cada: buscar step correspondente em `cadence_steps`
3. Substituir variáveis ({{nome}} → lead.name, etc)
4. Enviar via WhatsApp (Evolution ou Meta, conforme canal do lead)
5. Avançar enrollment ou marcar exhausted/completed

**B. Process stagnation triggers:**
1. Buscar cadências com `stagnation_days IS NOT NULL` e `status = 'active'`
2. Para cada: query leads/deals no target_stage há mais de stagnation_days
3. Criar enrollments para os que não têm

**C. Process broadcast-to-cadence:**
1. Buscar broadcasts com `cadence_id NOT NULL` e `status = 'completed'`
2. Para leads que foram enviados mas não responderam (sem enrollment ativo)
3. Criar enrollments na cadência vinculada

### 6.3 Buffer Processor (alterações)

Quando lead envia mensagem:
1. Verificar se tem `cadence_enrollment` ativo → pausar (status='responded')
2. Sem mudança na lógica do agente IA — continua funcionando igual

---

## 7. API Routes

### Frontend API (Next.js)

**Broadcasts:**
- `GET /api/broadcasts` — listar com filtros (status)
- `POST /api/broadcasts` — criar disparo
- `GET /api/broadcasts/[id]` — detalhe
- `PATCH /api/broadcasts/[id]` — atualizar (nome, status, cadence_id)
- `DELETE /api/broadcasts/[id]` — excluir (só draft)
- `POST /api/broadcasts/[id]/leads` — vincular leads (CRM ou CSV import)
- `POST /api/broadcasts/[id]/start` — iniciar envio

**Cadences:**
- `GET /api/cadences` — listar com filtros (status, target_type)
- `POST /api/cadences` — criar cadência
- `GET /api/cadences/[id]` — detalhe com steps e enrollments count
- `PATCH /api/cadences/[id]` — atualizar config
- `DELETE /api/cadences/[id]` — excluir (só se sem enrollments ativos)

**Cadence Steps:**
- `GET /api/cadences/[id]/steps` — listar steps ordenados
- `POST /api/cadences/[id]/steps` — criar step
- `PUT /api/cadences/[id]/steps/[stepId]` — atualizar step
- `DELETE /api/cadences/[id]/steps/[stepId]` — remover step
- `POST /api/cadences/[id]/steps/reorder` — reordenar steps

**Cadence Enrollments:**
- `GET /api/cadences/[id]/enrollments` — listar (com filtros status)
- `POST /api/cadences/[id]/enrollments` — enrollment manual
- `PATCH /api/cadences/[id]/enrollments/[enrollId]` — pausar/retomar
- `DELETE /api/cadences/[id]/enrollments/[enrollId]` — remover lead da cadência

**Template Presets:**
- `GET /api/template-presets` — listar
- `POST /api/template-presets` — criar
- `PUT /api/template-presets/[id]` — atualizar
- `DELETE /api/template-presets/[id]` — remover

**Analytics:**
- `GET /api/campaigns/stats` — KPIs agregados (disparos ativos, cadências ativas, etc)
- `GET /api/campaigns/stats/trend` — dados do gráfico de tendência por período

### Backend API (FastAPI)

Os endpoints de worker/scheduler não são API — são processos internos. Mas a API interna do backend precisa:
- `POST /api/broadcasts/{id}/start` — proxy para iniciar no worker
- `POST /api/broadcasts/{id}/pause` — proxy para pausar

---

## 8. Hooks Realtime (Frontend)

**`useRealtimeBroadcasts`** — subscribe to broadcasts table changes
**`useRealtimeCadences`** — subscribe to cadences table changes
**`useRealtimeEnrollments(cadenceId)`** — subscribe to cadence_enrollments filtered by cadence

Substituem o `useRealtimeCampaigns` existente.

---

## 9. Componentes Frontend

### Página `/campanhas`
- `campaigns-dashboard.tsx` — KPIs + gráfico de tendência
- `campaigns-tabs.tsx` — container das tabs
- `broadcast-list.tsx` — lista de disparos com cards
- `broadcast-card.tsx` — card individual de disparo
- `cadence-list.tsx` — lista de cadências com cards
- `cadence-card.tsx` — card individual de cadência

### Modal Criação de Disparo
- `create-broadcast-modal.tsx` — wizard 3 steps (config, leads, revisão)
- `template-selector.tsx` — dropdown com preview de template Meta
- `template-variables-form.tsx` — campos dinâmicos de variáveis
- `preset-selector.tsx` — dropdown de presets

### Página/Modal Cadência
- `cadence-detail.tsx` — página de detalhe da cadência
- `cadence-trigger-config.tsx` — config do trigger (type, stage, stagnation)
- `cadence-steps-table.tsx` — tabela de steps editável
- `cadence-step-editor.tsx` — editor de step individual (textarea + delay)
- `cadence-settings.tsx` — config global (janela, cooldown, max)
- `cadence-enrollments-table.tsx` — tabela de leads enrolled

### Shared
- `campaign-kpi-card.tsx` — card de KPI reutilizável
- `campaign-trend-chart.tsx` — gráfico de tendência

---

## 10. Migration dos Dados Existentes

A migration SQL deve:

1. Criar todas as tabelas novas
2. Para cada `campaign` existente:
   - Criar um `broadcast` com os campos de envio (name, template_name, total_leads, sent, failed, status, send_interval_min/max)
   - Criar uma `cadence` com os campos de cadência (name sufixo " - Cadência", cadence_interval_hours, send_start/end, cooldown, max_messages)
   - Vincular: `broadcast.cadence_id = cadence.id`
3. Migrar `cadence_steps` existentes: adicionar `delay_days` (calculado a partir do `interval_hours` da campaign × step_order)
4. Migrar `cadence_state` → `cadence_enrollments` (mapear campos 1:1)
5. Migrar `leads.campaign_id` → `broadcast_leads` (para leads com campaign_id NOT NULL)
6. Drop: `campaigns`, `cadence_state`, `leads.campaign_id`
7. Enable realtime para novas tabelas

---

## 11. Escopo Excluído (YAGNI)

- A/B testing de mensagens
- Multi-canal (email, SMS) — apenas WhatsApp
- Workflow builder visual — triggers são configurados na cadência diretamente
- Gerenciamento de templates na Meta via CRM — continua no Business Manager
- Analytics avançados (cohort, LTV) — apenas KPIs e tendência
- Cadências com branching (if/else) — sequência linear apenas
