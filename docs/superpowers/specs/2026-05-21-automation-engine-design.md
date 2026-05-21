# Design: Motor de Automação Unificado

**Data:** 2026-05-21  
**Branch:** feat/cadence-redesign  
**Status:** Aprovado

---

## Contexto e Problema

O sistema atual tem dois módulos paralelos com o mesmo objetivo (follow-ups personalizados):

- `backend/app/cadence/` — sequência linear de textos livres, scheduler próprio, poucos gatilhos
- `backend/app/campaigns/` — flow builder visual com templates HSM, mais gatilhos mas vários quebrados

**Bugs críticos identificados:**
- `stage_enter` não detecta entrada real — faz polling de todos os leads no stage, causa double-enrollment
- `post_broadcast` trigger existe na UI mas não está implementado no worker
- `resume_enrollment` em cadências reseta para passo 0 em vez de continuar de onde parou
- `add_tag` aparece na UI de ações mas não está implementado no backend
- Sem retry para envios com falha — enrollment fica travado indefinidamente
- Sem controle de frequência — lead pode receber múltiplas mensagens no mesmo dia de campanhas diferentes
- Cadências enviam texto livre após janela de 24h (rejeitado pelo WhatsApp silenciosamente)
- Variáveis limitadas a `{{nome}}`, `{{empresa}}`, `{{telefone}}` — dados de sales/deals não disponíveis

---

## Decisões de Design

1. **Unificar** cadências e campanhas em um único motor (`automation/`)
2. **Event-driven** para eventos pontuais (venda criada, mudança de stage, tag adicionada)
3. **Polling** mantido apenas para triggers de inatividade (sem mensagem, ciclo de recompra)
4. **Priority + Frequency Cap** para evitar spam e priorizar mensagens mais importantes
5. **Retry com backoff exponencial** para envios com falha
6. **Nó `send_text`** para texto livre dentro da janela de 24h

---

## Arquitetura

### Novo módulo

```
backend/app/automation/
  __init__.py
  engine.py      — executa nós, priority queue, frequency cap
  triggers.py    — detecção de gatilhos (event-driven + polling)
  variables.py   — substituição de variáveis enriquecida
  retry.py       — backoff exponencial
  router.py      — API unificada
```

Os módulos `cadence/` e `campaigns/` são mantidos somente para leitura histórica. Endpoints de criação retornam 410 Gone.

### Event hooks

Os seguintes endpoints recebem chamadas ao `automation.triggers` após executar suas operações:

| Endpoint | Evento disparado |
|---|---|
| `PATCH /api/leads/{id}` (mudança de stage) | `stage_enter` |
| `PATCH /api/deals/{id}` (mudança de stage) | `deal_stage_enter`, `deal_closed_lost` |
| `POST /api/sales` | `sale_created` |
| `POST /api/leads/{id}/tags` | `tag_added` |
| Completion do broadcast worker | `post_broadcast` |

---

## Schema de Banco

### Alterações em tabelas existentes

**`campaigns`** (adicionar colunas):
```sql
priority       INT NOT NULL DEFAULT 5          -- 1 (baixa) a 10 (alta)
frequency_cap  INT NOT NULL DEFAULT 1          -- máx mensagens/lead/dia
```

**`campaign_enrollments`** (adicionar colunas):
```sql
retry_count    INT NOT NULL DEFAULT 0
last_error     TEXT NULL
next_retry_at  TIMESTAMPTZ NULL
```

### Nova tabela

```sql
CREATE TABLE lead_daily_sends (
  lead_id  UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  date     DATE NOT NULL,
  count    INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (lead_id, date)
);
```

### Novos campos em `campaign_nodes.config` (JSONB — sem alteração de schema)

Nó `send_text`:
```json
{
  "send_type": "text",
  "message_text": "Olá {{nome}}, ...",
  "on_reply": "pause"
}
```

---

## Gatilhos (Triggers)

### Event-driven (disparam imediatamente)

| Trigger | Configuração no nó | Fonte |
|---|---|---|
| `stage_enter` | `stage_filter: string` | Hook em PATCH /leads e /deals |
| `deal_stage_enter` | `stage_filter: string` | Hook em PATCH /deals |
| `deal_closed_lost` | (sem config extra) | Hook em PATCH /deals |
| `sale_created` | `min_value?: number`, `product_filter?: string` | Hook em POST /api/sales |
| `tag_added` | `tag_name: string` | Hook em POST /api/leads/{id}/tags |
| `post_broadcast` | `broadcast_id?: string`, `replied_only: bool` | Hook em broadcast worker após marcar cada lead como `sent`. Se `replied_only=true`, só enrolla leads que responderam ao broadcast |

### Polling (scheduler periódico)

| Trigger | Configuração no nó | Fonte |
|---|---|---|
| `no_message` | `days: number`, `stage_filter?: string` | `leads.last_msg_at` |
| `stage_stagnation` | `days: number`, `stage_filter: string` | `leads.entered_stage_at` |
| `repurchase_window` | `days: number` | Polling: `(today - MAX(sales.sold_at)) >= days`. Só enrolla uma vez por ciclo — verifica `is_already_enrolled` |
| `no_sale_in_stage` | `days: number`, `stage_filter: string` | leads em stage avançado sem sales |

---

## Tipos de Nó

### Existentes (mantidos)

| Nó | Descrição |
|---|---|
| `trigger` | Gatilho de entrada do fluxo |
| `send` | Envia template HSM aprovado pela Meta |
| `wait` | Aguarda N dias antes de avançar |
| `condition` | Ramificação lógica (SIM/NÃO) |
| `action` | Executa ação no CRM |
| `end` | Encerra o enrollment |

### Novo

| Nó | Descrição |
|---|---|
| `send_text` | Envia texto livre — verifica `leads.last_customer_message_at <= 24h` antes de enviar. Se janela expirada: registra `last_error = "24h_window_expired"`, avança para próximo nó sem falhar o enrollment |

---

## Condições

| Condição | Parâmetros | Descrição |
|---|---|---|
| `replied_recently` | `days` | Respondeu nos últimos N dias |
| `in_stage` | `stage` | Lead está no stage X (busca fresca) |
| `has_deal` | — | Tem deal ativo |
| `sale_count` | `operator`, `value` | Total de vendas >= N |
| `total_spend` | `operator`, `value` | Soma de vendas >= R$ X |
| `last_sale_value` | `operator`, `value` | Última venda >= R$ X |
| `deal_value` | `operator`, `value` | Deal atual >= R$ X |
| `has_tag` | `tag_name` | Lead possui tag específica |
| `repurchase_days` | `operator`, `value` | Dias desde última venda |

`operator` aceita: `gte`, `lte`, `eq`, `gt`, `lt`

---

## Ações

| Ação | Parâmetros | Descrição |
|---|---|---|
| `move_stage` | `stage_id` | Mover deal para stage no pipeline |
| `activate_agent` | — | Ativar ValerIA para o lead |
| `deactivate_agent` | — | Desativar ValerIA para o lead |
| `add_tag` | `tag_name` | Adicionar tag ao lead |
| `remove_tag` | `tag_name` | Remover tag do lead |
| `create_deal` | `title_template`, `pipeline_id?` | Criar deal automaticamente |
| `assign_to` | `user_id` | Atribuir lead a vendedor |
| `notify_seller` | `message_template`, `seller_phone` | Enviar WhatsApp ao vendedor |

---

## Variáveis nas Mensagens

Disponíveis em nós `send`, `send_text` e ações com `message_template`:

```
{{nome}}               — lead.name
{{empresa}}            — lead.company
{{telefone}}           — lead.phone
{{produto}}            — último produto comprado (sales)
{{valor_ultima_venda}} — último valor de venda formatado (R$ X,XX)
{{dias_sem_compra}}    — dias desde última venda
{{vendedor}}           — nome do assigned_to
{{deal_titulo}}        — título do deal ativo
{{pipeline}}           — nome do pipeline do deal ativo
```

Variável sem dado disponível → substituída por string vazia (sem erro).

---

## Priority + Frequency Cap

Antes de executar qualquer nó de envio (`send` ou `send_text`):

1. Consultar `lead_daily_sends` para `(lead_id, today)`
2. Se `count >= campaign.frequency_cap`: adiar enrollment para amanhã (próxima janela de envio)
3. Se múltiplos enrollments aguardam slot: executar o da campanha com maior `priority` primeiro
4. Ao enviar com sucesso: `INSERT INTO lead_daily_sends ... ON CONFLICT DO UPDATE count = count + 1`

---

## Retry com Backoff Exponencial

Ao falhar um envio:
```
retry_count = 0 → next_retry_at = now + 1h
retry_count = 1 → next_retry_at = now + 4h
retry_count = 2 → next_retry_at = now + 24h
retry_count = 3 → status = 'failed', last_error gravado, enrollment encerrado
```

O scheduler trata enrollments com `status = 'active'` e `next_retry_at <= now` da mesma forma que enrollments normais.

---

## Migração de Dados

1. `cadence_enrollments` com `status = 'active'` → atualizar para `status = 'completed'`, `last_error = 'migrated_to_automation_engine'`
2. `campaign_enrollments` ativos → continuam rodando (o novo engine é compatível com o schema existente)
3. Endpoints `POST /api/cadences`, `POST /api/cadences/{id}/steps` → retornam 410 Gone com mensagem explicativa
4. UI: aba "Cadências" simples removida. Página `/campanhas/cadencias/[id]` mantida somente leitura para histórico

---

## Considerações de Segurança

- Event hooks executam de forma assíncrona (background task no FastAPI) — nunca bloqueiam a resposta do endpoint que os chamou
- Variáveis são sanitizadas antes da substituição (sem execução de código)
- `notify_seller` valida que o número destino existe na tabela `team_users` antes de enviar

---

## O que NÃO está no escopo

- Interface de analytics/relatórios de campanhas (escopo futuro)
- A/B testing de mensagens (escopo futuro)
- Suporte a múltiplos gatilhos por campanha (a campanha continua tendo um único nó trigger)
