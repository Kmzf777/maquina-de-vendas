# Cadenciamento por Stage — Design Spec

**Data:** 2026-03-27
**Status:** Aprovado

## Resumo

Sistema de cadenciamento automático de follow-ups por etapa de funil, integrado ao campaign worker existente. Leads importados via campanha recebem mensagens pré-escritas de nurturing específicas ao seu stage (atacado, private_label, exportacao, consumo). Quando o lead responde, a cadência pausa e a Valeria (agente IA) assume. Se o lead esfria novamente, a cadência retoma com cooldown.

## Decisões de Design

| Decisão | Escolha |
|---------|---------|
| Tipo de mensagem | Fixas/pré-escritas por etapa |
| Gatilho de avanço | Resposta = sai da cadência pro agente. Silêncio = cadência avança por tempo |
| Estrutura do funil | Cadência atrelada aos stages existentes (atacado, private_label, etc.) |
| Intervalo entre msgs | Configurável por campanha |
| Lead esgotou cadência | Vai pro pool de frios, pode ser re-inserido em nova campanha |
| Janela de envio | 7h às 18h (horário de Brasília) |
| Lead esfria após agente | Retoma cadência com cooldown (48h default) + limite total de mensagens (8 default) |
| Abordagem técnica | Extensão do campaign worker existente |

## Modelo de Dados

### Nova tabela: `cadence_steps`

Define as mensagens pré-escritas de cada stage por campanha.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | UUID PK | |
| campaign_id | UUID FK → campaigns | Cadência pertence a uma campanha |
| stage | text | Stage do lead (atacado, private_label, exportacao, consumo) |
| step_order | int | Ordem da mensagem (1, 2, 3...) |
| message_text | text | Texto fixo do follow-up |
| created_at | timestamptz | |

**Unique constraint:** (campaign_id, stage, step_order)

### Nova tabela: `cadence_state`

Rastreia o progresso de cada lead na cadência.

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | UUID PK | |
| lead_id | UUID FK → leads (UNIQUE) | Um lead, um estado |
| campaign_id | UUID FK → campaigns | |
| current_step | int DEFAULT 0 | Último step enviado |
| status | text DEFAULT 'active' | active, responded, exhausted, cooled |
| total_messages_sent | int DEFAULT 0 | Contador global (pro limite total) |
| max_messages | int DEFAULT 8 | Teto configurável |
| next_send_at | timestamptz | Quando o próximo follow-up deve sair |
| cooldown_until | timestamptz NULL | Se retomando após resposta, espera até aqui |
| responded_at | timestamptz NULL | Quando o lead respondeu |
| created_at | timestamptz | |

**Status flow:** `active` → `responded` (lead respondeu) → `active` (esfriou, retoma com cooldown) → `exhausted` (bateu limite) ou `cooled` (cadência esgotou steps)

### Alterações em `campaigns`

Novos campos:

| Coluna | Tipo | Default | Descrição |
|--------|------|---------|-----------|
| cadence_interval_hours | int | 24 | Intervalo entre follow-ups |
| cadence_send_start_hour | int | 7 | Início janela de envio |
| cadence_send_end_hour | int | 18 | Fim janela de envio |
| cadence_cooldown_hours | int | 48 | Cooldown pra reengajamento |
| cadence_max_messages | int | 8 | Teto total de msgs por lead |
| cadence_sent | int | 0 | Total de follow-ups enviados |
| cadence_responded | int | 0 | Leads que responderam durante cadência |
| cadence_exhausted | int | 0 | Leads que esgotaram sem resposta |

## Fluxo do Worker

### Ciclo principal (a cada 30s)

```
Loop principal:
  ├─ [EXISTENTE] Disparar templates pra leads pendentes
  │   └─ Ao enviar template, criar cadence_state com status='active'
  │      e next_send_at = agora + cadence_interval_hours
  │
  └─ [NOVO] Processar cadência
      ├─ Buscar cadence_states onde:
      │   - status = 'active'
      │   - next_send_at <= agora
      │   - total_messages_sent < max_messages
      │   - hora atual entre 7h e 18h (Brasília, UTC-3)
      │   - lead.human_control = false
      │   - campanha.status != 'paused'
      │
      ├─ Para cada lead:
      │   ├─ Buscar próximo cadence_step (stage + step_order = current_step + 1)
      │   ├─ Se existe step → enviar mensagem, incrementar counters, calcular next_send_at
      │   ├─ Se não existe step → marcar status='cooled'
      │   └─ Se total_messages_sent >= max_messages → marcar status='exhausted'
      │
      └─ Batch de 10, com delay aleatório entre envios
```

### Reengajamento (lead esfriou após falar com agente)

```
Buscar cadence_states onde:
  - status = 'responded'
  - responded_at + cooldown_hours <= agora
  - lead.last_msg_at não mudou desde responded_at
  - total_messages_sent < max_messages
  - lead.human_control = false

Para cada:
  ├─ status = 'active'
  ├─ next_send_at = agora (pega no próximo ciclo dentro da janela)
  └─ cooldown_until = NULL
```

## Interação com Webhook

No `buffer/processor.py`, antes de processar com o agente:

```
Mensagem chega no webhook
  ↓
Verificar se lead tem cadence_state com status='active'
  ↓
Se sim:
  ├─ cadence_state.status = 'responded'
  ├─ responded_at = agora
  └─ Continuar pro fluxo normal (agente assume)
```

## API

### Cadence Steps

- `GET /api/campaigns/{campaign_id}/cadence` — lista steps agrupados por stage
- `POST /api/campaigns/{campaign_id}/cadence` — cria step (stage, step_order, message_text)
- `PUT /api/campaigns/{campaign_id}/cadence/{step_id}` — edita texto
- `DELETE /api/campaigns/{campaign_id}/cadence/{step_id}` — remove step

### Cadence State

- `GET /api/campaigns/{campaign_id}/cadence/status` — resumo por stage (active, responded, exhausted, cooled)
- `GET /api/leads/{lead_id}/cadence` — estado da cadência de um lead

### Configuração na campanha

`POST /api/campaigns` aceita campos opcionais:

```json
{
  "name": "Atacado Q2",
  "template_name": "hello_atacado",
  "cadence_interval_hours": 24,
  "cadence_send_start_hour": 7,
  "cadence_send_end_hour": 18,
  "cadence_cooldown_hours": 48,
  "cadence_max_messages": 8
}
```

## Tratamento de Bordas

### Lead muda de stage durante cadência
- Cadência já está em `status='responded'` (lead estava conversando com agente)
- Se reengajar, busca steps do **novo stage**
- `current_step` reseta pra 0 no novo stage

### Lead encaminhado pro humano
- `lead.human_control = true`
- Worker ignora — nunca envia cadência pra lead com humano

### Campanha pausada
- Worker só processa cadence_states de campanhas ativas

### Lead em múltiplas campanhas
- UNIQUE em lead_id na cadence_state — um estado ativo por vez
- Nova campanha marca estado antigo como `exhausted` e cria novo

### Timezone
- `next_send_at` em UTC
- Janela 7-18h avaliada em horário de Brasília (UTC-3), hardcoded

## Registro e Observabilidade

### Mensagens no histórico
Cada follow-up salvo na tabela `messages`:
- `role = 'assistant'`
- `sent_by = 'cadence'` (diferencia de 'agent' e 'human')
- `stage` = stage atual do lead

A Valeria vê essas mensagens no histórico e não repete conteúdo.

### Contadores
Campos `cadence_sent`, `cadence_responded`, `cadence_exhausted` em `campaigns`, incrementados via RPC functions no Supabase.

### Logs do worker
- `[CADENCE] Sent step {step_order}/{total_steps} to {phone} (stage={stage})`
- `[CADENCE] Lead {phone} responded — pausing cadence`
- `[CADENCE] Lead {phone} re-engaged — resuming from step {step}`
- `[CADENCE] Lead {phone} exhausted — {total} messages sent`
