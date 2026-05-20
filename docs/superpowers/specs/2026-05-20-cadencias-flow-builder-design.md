# Spec: Cadências — Flow Builder de Campanhas

**Data:** 2026-05-20  
**Status:** Aprovado  
**Branch:** fix/conversas-crm-panel → novo branch `feat/cadencias-flow-builder`

---

## Contexto

O sistema de Cadências existente (tabelas `cadences`, `cadence_steps`, `cadence_enrollments`) é não-utilizado e tem uma limitação fatal: steps enviam texto puro, que falha fora da janela 24h do WhatsApp. O CRM evoluiu significativamente desde sua criação.

Este documento especifica o redesign completo do sistema de Cadências como um **flow builder visual de campanhas**, usando o sistema de Disparo (broadcast) como base técnica.

---

## Decisões de Design

| Decisão | Escolha |
|---|---|
| Nome no UI | "Cadências" (mantido) |
| Mensagens dos steps | Templates Meta (HSM) — igual ao broadcast |
| Entrada de leads | Gatilhos automáticos por dados do CRM |
| Agendamento | Delays relativos à data de enrollment do lead + `start_date` configurável na campanha |
| Interface | Node graph visual (n8n/Zapier style) — botão `+ Adicionar nó` no v1, sem drag-and-drop |
| Banco de dados | Novas tabelas (`campaigns`, `campaign_nodes`, `campaign_enrollments`) — tabelas antigas abandonadas mas não removidas |
| Comportamento ao responder | Configurável por nó de envio (pausar, cancelar, continuar) |

---

## Banco de Dados

### Tabela: `campaigns`

```sql
id            uuid PRIMARY KEY DEFAULT gen_random_uuid()
name          text NOT NULL
description   text
status        text DEFAULT 'draft'   -- draft | active | paused | archived
env_tag       text NOT NULL
start_date    timestamptz             -- null = ativa imediatamente ao ativar
created_at    timestamptz DEFAULT now()
updated_at    timestamptz DEFAULT now()
```

### Tabela: `campaign_nodes`

```sql
id            uuid PRIMARY KEY DEFAULT gen_random_uuid()
campaign_id   uuid REFERENCES campaigns(id) ON DELETE CASCADE
type          text NOT NULL   -- trigger | send | wait | condition | action | end
config        jsonb NOT NULL DEFAULT '{}'
position_x    int DEFAULT 0
position_y    int DEFAULT 0
next_node_id  uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL
yes_node_id   uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL   -- condition: branch sim
no_node_id    uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL   -- condition: branch não
created_at    timestamptz DEFAULT now()
```

### Tabela: `campaign_enrollments`

```sql
id                  uuid PRIMARY KEY DEFAULT gen_random_uuid()
campaign_id         uuid REFERENCES campaigns(id) ON DELETE CASCADE
lead_id             uuid REFERENCES leads(id) ON DELETE CASCADE
deal_id             uuid REFERENCES deals(id) ON DELETE SET NULL
status              text DEFAULT 'active'  -- active | paused | completed | cancelled
current_node_id     uuid REFERENCES campaign_nodes(id) ON DELETE SET NULL
next_execute_at     timestamptz
enrolled_at         timestamptz DEFAULT now()
completed_at        timestamptz
paused_at           timestamptz
env_tag             text NOT NULL
UNIQUE (campaign_id, lead_id)   -- lead não pode estar duas vezes na mesma campanha
```

---

## Tipos de Nó e seus `config`

### `trigger`
Define o critério de enrollment automático. Avaliado pelo worker a cada tick.

```jsonc
{
  "trigger_type": "no_message" | "stage_stagnation" | "stage_enter" | "post_broadcast",
  "days": 30,                     // para no_message e stage_stagnation
  "stage_filter": "Novo",         // opcional: filtrar por stage específico
  "broadcast_id": "uuid"          // para post_broadcast
}
```

### `send`
Envia um template Meta HSM.

```jsonc
{
  "template_name": "reativacao_30dias",
  "template_language": "pt_BR",
  "template_variables": { "__params_type__": "named", "primeiro_nome": "{{primeiro_nome}}" },
  "channel_id": "uuid",
  "agent_profile_id": "uuid",     // opcional
  "on_reply": "pause" | "cancel" | "continue"  // comportamento ao responder
}
```

### `wait`
Aguarda N dias antes de passar ao próximo nó.

```jsonc
{
  "days": 5,
  "send_start_hour": 7,
  "send_end_hour": 18
}
```

### `condition`
Avalia uma condição e ramifica.

```jsonc
{
  "condition_type": "replied_recently" | "in_stage" | "has_deal",
  "days": 5,          // para replied_recently: janela de dias
  "stage": "Novo"     // para in_stage
}
```

### `action`
Executa uma ação no CRM sem enviar mensagem.

```jsonc
{
  "action_type": "move_stage" | "activate_agent" | "deactivate_agent" | "add_tag",
  "stage_id": "uuid",
  "agent_profile_id": "uuid",
  "tag_id": "uuid"
}
```

### `end`
Encerra o enrollment. Pode executar ações finais.

```jsonc
{
  "label": "Lead convertido",
  "final_actions": [
    { "type": "move_stage", "stage_id": "uuid" },
    { "type": "activate_agent", "agent_profile_id": "uuid" }
  ]
}
```

---

## Arquitetura Backend

### API Routes (FastAPI — `/api/campaigns`)

```
GET    /api/campaigns                          → listar campanhas
POST   /api/campaigns                          → criar campanha
GET    /api/campaigns/{id}                     → obter campanha + nós
PATCH  /api/campaigns/{id}                     → atualizar campanha
DELETE /api/campaigns/{id}                     → excluir (apenas draft)
POST   /api/campaigns/{id}/activate            → ativar campanha
POST   /api/campaigns/{id}/pause               → pausar campanha

POST   /api/campaigns/{id}/nodes               → adicionar nó
PATCH  /api/campaigns/{id}/nodes/{node_id}     → atualizar nó (config + posição)
DELETE /api/campaigns/{id}/nodes/{node_id}     → remover nó

GET    /api/campaigns/{id}/enrollments         → listar enrollments
POST   /api/campaigns/{id}/enrollments         → enrollar lead manualmente
PATCH  /api/campaigns/{id}/enrollments/{eid}   → pausar/retomar enrollment
DELETE /api/campaigns/{id}/enrollments/{eid}   → cancelar enrollment
```

### Worker (`campaign_worker.py`)

O worker roda no mesmo loop de `run_worker()` existente. Dois processos:

**1. `check_campaign_triggers()`** — roda a cada tick
- Para cada campanha `active` com nó `trigger`, verifica leads que satisfazem o critério
- Cria `campaign_enrollment` para leads novos (respeitando o UNIQUE constraint)
- Define `current_node_id = trigger.next_node_id` e `next_execute_at = now()`

**2. `process_campaign_enrollments()`** — roda a cada tick
- Busca enrollments `active` com `next_execute_at <= now()` (limit 20)
- Para cada enrollment, executa o `current_node_id`:
  - `send`: envia template (reutiliza lógica de `broadcast/worker.py`), salva wamid, atualiza conversa, atualiza `ai_enabled` no lead
  - `wait`: define `next_execute_at = now() + days`, dentro da janela de envio
  - `condition`: avalia a condição, seta `current_node_id = yes_node_id | no_node_id`, `next_execute_at = now()`
  - `action`: executa ação CRM (move stage, ativa agente)
  - `end`: executa `final_actions`, marca enrollment como `completed`
- Entre envios: delay aleatório de 3–8s (mesmo padrão do broadcast)

**Comportamento ao responder:**
O webhook de mensagens recebidas (`webhook/handler.py`) verifica se o lead tem enrollment `active`. Se o nó atual é `send` com `on_reply = "pause"`, o enrollment é pausado. Para `on_reply = "cancel"`, é cancelado. Para `continue`, nada muda.

---

## Arquitetura Frontend

### Rotas

```
/campanhas                     → página existente, aba "Cadências" com nova lista
/campanhas/cadencias/[id]      → página do flow builder
```

### Componentes

**`/campanhas` — aba Cadências:**
- `CadenceList` (substituído): grid de cards de campanhas, filtros (draft/ativa/pausada/arquivada), botão "Nova Cadência"
- `CadenceCard`: card com nome, status, contagem de nós, leads ativos, taxa de resposta

**`/campanhas/cadencias/[id]` — flow builder:**
- Layout: Topbar + Paleta (esquerda, 196px) + Canvas (flex 1) + Inspector (direita, 256px)
- **Canvas**: background `#f5f2ed`, dot grid, nós posicionados via `position: absolute`
- **Nós no canvas**: white cards, 3px stripe colorida no topo por tipo, ícone tintado, fonte `Outfit` + `JetBrains Mono`
- **Conectores**: SVG bezier entre port-out e port-in, coloridos por branch (YES verde / NO vermelho)
- **Adicionar nó**: botão `+` no port-out de cada nó → dropdown dos tipos disponíveis → cria nó abaixo
- **Inspector**: painel direito atualiza ao clicar num nó, edita config, botão Salvar

**`CrmCampanhasTab`** (atualizado):
- Mostrar `campaign_enrollments` do lead (nova tabela) além do histórico de disparos
- Manter seção "Disparos Recebidos" existente

### API Routes (Next.js)

Proxies para o backend FastAPI:
```
/api/campaigns/[...slug]  → http://backend/api/campaigns/[...slug]
```

---

## Integração com Broadcast

O campo `cadence_id` da tabela `broadcasts` é mantido para retrocompatibilidade. Novos broadcasts podem apontar para uma `campaign_id` (campo novo: `campaign_id` na tabela `broadcasts`). Quando um broadcast completa o envio para um lead, o worker de broadcast verifica `campaign_id` e cria um enrollment na campanha correspondente.

---

## O que NÃO é escopo do v1

- Drag-and-drop real da paleta para o canvas
- Thumbnails do flow na lista de campanhas
- Métricas por nó (taxa de resposta por step)
- Múltiplos triggers por campanha
- Loop nodes (voltar para um nó anterior)
- Migração/importação de cadências antigas

---

## Critérios de Sucesso

1. É possível criar uma campanha, adicionar nós no canvas e ativá-la
2. O worker detecta leads pelos gatilhos e cria enrollments automaticamente
3. Templates são enviados nos horários corretos com delays respeitados
4. Condições de ramificação funcionam (sim/não)
5. Quando um lead responde, o comportamento configurado é respeitado
6. O painel CRM mostra enrollments ativos do lead
