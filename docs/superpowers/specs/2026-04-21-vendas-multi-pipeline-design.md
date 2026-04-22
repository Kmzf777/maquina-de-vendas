# Spec: Multi-Pipeline (Funis Editáveis) — /vendas

**Data:** 2026-04-21  
**Status:** Aprovado pelo usuário

---

## Contexto

A página `/vendas` hoje tem um único funil implícito com 6 stages hardcoded em `constants.ts`. O objetivo é tornar os funis dinâmicos, editáveis e múltiplos — similar ao Kommo — persistindo configurações no banco de dados.

---

## Requisitos

- Suporte a múltiplos funis independentes por workspace
- Cada funil tem seus próprios stages (colunas do kanban)
- Stages totalmente customizáveis: adicionar, renomear, reordenar, deletar, cor
- Dois stages protegidos em cada funil: **Fechado Ganho** e **Perdido** (sempre existem, não podem ser deletados)
- Novo funil começa com 6 stages default (os atuais)
- Um deal pertence a um funil; um lead pode ter deals em funis diferentes
- Migração não destrutiva: dados existentes vão para um "Funil Principal" criado automaticamente

---

## Modelo de Dados

### Novas tabelas

```sql
CREATE TABLE pipelines (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  order_index   int  NOT NULL DEFAULT 0,
  created_at    timestamptz DEFAULT now(),
  updated_at    timestamptz DEFAULT now()
);

CREATE TABLE pipeline_stages (
  id            uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_id   uuid    NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  label         text    NOT NULL,
  key           text,                        -- slug para stages protegidos (ex: 'fechado_ganho', 'fechado_perdido')
  dot_color     text    NOT NULL DEFAULT '#e07a7a',
  order_index   int     NOT NULL DEFAULT 0,
  is_protected  boolean NOT NULL DEFAULT false,
  created_at    timestamptz DEFAULT now()
);
```

### Alterações em `deals`

```sql
ALTER TABLE deals ADD COLUMN pipeline_id uuid REFERENCES pipelines(id);
ALTER TABLE deals ADD COLUMN stage_id    uuid REFERENCES pipeline_stages(id);
-- deals.stage (text) mantido temporariamente durante migração, depois deprecado
```

### Estratégia de migração

1. Criar pipeline "Funil Principal"
2. Criar os 6 stages default nesse pipeline (com `is_protected = true` para `fechado_ganho` e `fechado_perdido`, `key` preenchido só nesses dois)
3. Fazer `UPDATE deals SET pipeline_id = <id>, stage_id = <id do stage correspondente> WHERE stage = 'novo'` etc.
4. Habilitar realtime para `pipelines` e `pipeline_stages`

### Identificação de stages especiais

Stages protegidos são identificados pelo campo `key`:
- `key = 'fechado_ganho'` → comportamento de "ganho" (contabilizado em métricas de win)
- `key = 'fechado_perdido'` → dispara modal de motivo da perda

Stages normais têm `key = null`.

---

## API Routes (Next.js)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/pipelines` | Lista todos os pipelines |
| POST | `/api/pipelines` | Cria novo pipeline (cria stages default automaticamente) |
| PATCH | `/api/pipelines/[id]` | Renomeia pipeline |
| DELETE | `/api/pipelines/[id]` | Deleta pipeline (só se sem deals) |
| GET | `/api/pipelines/[id]/stages` | Lista stages do pipeline |
| POST | `/api/pipelines/[id]/stages` | Cria novo stage |
| PATCH | `/api/pipelines/[id]/stages/[stageId]` | Atualiza label/cor/ordem |
| DELETE | `/api/pipelines/[id]/stages/[stageId]` | Deleta stage (bloqueado se `is_protected` ou se tiver deals) |
| GET | `/api/deals` | Aceita `?pipeline_id=` como filtro |
| POST | `/api/deals` | Agora requer `pipeline_id`, cria deal no primeiro stage não-protegido |
| PATCH | `/api/deals/[id]` | Aceita `stage_id` em vez de `stage` |

---

## Componentes Frontend

### `PipelineSwitcher`
Dropdown no header da página, substitui o título estático "Funis de Venda".  
- Mostra nome do funil ativo com caret `↓`  
- Abre lista de todos os funis ao clicar  
- Funil ativo destacado  
- Botão "+ Novo Funil" no rodapé da lista  
- Ícone `⋯` ao lado do nome do funil ativo → menu com "Editar Funil" e "Excluir Funil"

### `PipelineCreateModal`
Modal simples com campo de nome. Ao criar, API provisiona os 6 stages default.

### `PipelineEditModal`
Modal de edição de stages:
- Lista de stages com drag handle (reordenar)
- Input de nome inline (renomear)
- Color picker (paleta das cores do design system)
- Botão de deletar (desabilitado para stages protegidos — ícone de cadeado)
- Botão "+ Adicionar Stage"
- Stages protegidos mostram badge "Protegido"

### Atualizações em componentes existentes

- `VendasPage` — usa `selectedPipelineId` como estado, busca stages do pipeline ativo dinamicamente (não mais de `constants.ts`)
- `DroppableColumn` — recebe stage do banco (id, label, dotColor, key) em vez de constante
- `DealCreateModal` — remove campo de `category` como proxy de pipeline, recebe `pipelineId` do contexto
- `DealCard` / `DealDetailSidebar` — identifica stage especial pelo `key` em vez de string hardcoded
- `LostReasonModal` — acionado quando `stage.key === 'fechado_perdido'`
- `DealKanbanMetrics` — métricas de ganho quando `stage.key === 'fechado_ganho'`
- Hook `useRealtimeDeals` — filtra por `pipeline_id`, assina realtime de `pipeline_stages`

### Hook `usePipelines`
Novo hook que busca e assina realtime de `pipelines` e stages do pipeline ativo.

---

## UX e Estética

**Switcher:** dropdown clicável no header — não consome espaço horizontal do kanban (crítico pra usabilidade de kanban com múltiplas colunas). Segue o padrão minimalista do design system (fundo `#f0ede8`, border `#dedbd6`, texto `#111111`).

**Editor de stages:** modal limpo, drag-and-drop com `@dnd-kit` (já em uso no projeto). Paleta de cores limitada às cores do design system para manter coerência visual.

**Feedback de proteção:** stages protegidos têm ícone de cadeado e tooltip explicativo ao hover — sem mensagem de erro intrusiva.

---

## Ordem de Implementação

1. **SQL migration** — novas tabelas + migração de dados existentes
2. **API routes** — pipelines CRUD + stages CRUD + atualização do deals API
3. **Frontend** — hook `usePipelines`, refactor de `VendasPage`, novos modals, atualização dos componentes existentes

Fases 1 e 2 são paralelas internamente. Fase 3 depende de 1 e 2.

---

## Restrições

- Stages protegidos nunca podem ser deletados (backend rejeita com 409)
- Pipeline com deals não pode ser deletado sem migrar ou remover os deals primeiro
- Stage com deals não pode ser deletado (backend rejeita com 409, orienta mover deals)
- `constants.ts` — `DEAL_STAGES` será removido após migração completa
- Nenhum commit na branch até autorização explícita do usuário
