# Design: Agendamento de Disparos

**Data:** 2026-05-21  
**Status:** Aprovado

---

## Visão Geral

Permitir que o usuário agende um disparo para executar automaticamente em uma data e hora específicas no Horário de Brasília (BRT, UTC-3), sem intervenção manual. O campo `scheduled_at` e o status `"scheduled"` já existem no banco de dados e no backend — falta apenas o comportamento no worker e a UI completa.

---

## Arquitetura

A abordagem escolhida é **worker-loop** (Opção A): adicionar `process_scheduled_broadcasts()` ao loop existente de 5 segundos em `worker.py`. Esse padrão é idêntico ao `process_due_cadences()` já em produção e não introduz nenhuma nova dependência ou serviço.

```
[Loop Worker 5s]
  → process_scheduled_broadcasts()   ← NOVO
  → process_broadcasts()
  → process_due_cadences()
  → ...
```

---

## Componentes

### Backend — `backend/app/broadcast/worker.py`

**Nova função `process_scheduled_broadcasts()`:**
- Query: `status = 'scheduled'` AND `scheduled_at <= now()` AND `env_tag = _ENV_TAG`
- Para cada broadcast encontrado:
  - Verifica se há leads `pending` (se não houver, marca como `failed` com log de erro)
  - Atualiza status para `'running'`
  - Log informativo

**Inserção no loop:** Chamada antes de `process_broadcasts()` para que o broadcast já entre como `running` no mesmo tick.

### Backend — `backend/app/broadcast/router.py`

**`PATCH /{broadcast_id}`:** O endpoint já aceita body livre. Garantir que:
- Quando `scheduled_at` é setado e status é `'draft'` → status vira `'scheduled'`
- Quando `scheduled_at` é `null` e status é `'scheduled'` → status vira `'draft'`
- Essa lógica fica no próprio endpoint PATCH (não exige novo endpoint)

**`DELETE /{broadcast_id}`:** Incluir `'scheduled'` nos status permitidos para exclusão (atualmente só `draft` e `completed`).

### Frontend — `create-broadcast-modal.tsx`

Adicionar **Step 5: Agendamento** entre "Ação" (step 4) e "Revisão" (step 6).

Conteúdo do step:
- Toggle radio: **"Iniciar imediatamente"** (default) / **"Agendar para depois"**
- Se "Agendar para depois":
  - Input `<date>` (data) + Input `<time>` (hora)
  - Label explícita: **(Horário de Brasília — UTC-3)**
  - Validação: data/hora deve ser no futuro
- Ao submeter: converter BRT → UTC antes de enviar (`scheduledAt` no payload)

### Frontend — `broadcast-detail.tsx`

**Se status `'draft'`:**
- Manter botão "Iniciar agora" existente
- Adicionar botão secundário "Agendar" que abre um pequeno painel inline com date/time picker

**Se status `'scheduled'`:**
- Exibir: "Agendado para [DD/MM/YYYY às HH:MM] (Horário de Brasília)"
- Botão "Reagendar" → abre painel com date/time picker preenchido com valor atual
- Botão "Cancelar agendamento" → PATCH `{scheduled_at: null, status: 'draft'}`
- Remover botão "Iniciar agora" (o sistema inicia automaticamente)

**Se status `'running'`, `'completed'`, etc.:** Nenhuma mudança — comportamento atual mantido.

### Frontend — `broadcast-card.tsx`

Para status `'scheduled'`: exibir data/hora formatada em BRT abaixo do badge "Agendado".

---

## Fluxo de Dados

### Criação com agendamento
```
Modal Step 5 (BRT input)
  → converte para UTC
  → POST /api/broadcasts { scheduled_at: "2026-05-22T18:00:00Z", ... }
  → Backend insere com status='scheduled'
  → Worker detecta scheduled_at <= now() no tick seguinte ao horário
  → status = 'running' → process_broadcasts() inicia envio
```

### Agendamento pós-criação
```
BroadcastDetail (draft)
  → clica "Agendar" → date/time picker inline
  → PATCH /api/broadcasts/{id} { scheduled_at: "...", status: "scheduled" }
  → UI atualiza para mostrar estado 'scheduled'
```

### Cancelamento de agendamento
```
BroadcastDetail (scheduled)
  → clica "Cancelar agendamento"
  → PATCH /api/broadcasts/{id} { scheduled_at: null, status: "draft" }
  → UI volta para estado 'draft' com botões normais
```

### Reagendamento
```
BroadcastDetail (scheduled)
  → clica "Reagendar" → picker preenchido com data atual
  → escolhe nova data → PATCH { scheduled_at: "nova-data-utc" }
  → status permanece 'scheduled' com nova data
```

---

## Tratamento de Timezone

- **Armazenamento:** sempre UTC no banco (`scheduled_at` timestamptz)
- **Input do usuário:** date + time pickers interpretados como BRT (UTC-3)
- **Conversão frontend → backend:** `new Date(year, month-1, day, hour-3, minute).toISOString()` (subtrai 3h para obter UTC)
- **Display:** `toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo' })` com label "(Horário de Brasília)"
- **Worker:** comparação `scheduled_at <= now()` em UTC — correto sem nenhuma conversão adicional

---

## Tratamento de Erros

| Cenário | Comportamento |
|---|---|
| Horário passado no picker | Validação client-side bloqueia envio |
| Broadcast agendado sem leads | Worker marca status `'failed'`, loga erro |
| Worker reinicia antes do horário | Na retomada, `process_scheduled_broadcasts()` pega broadcasts ainda `'scheduled'` com `scheduled_at <= now()` |
| Reagendar para o passado | Validação client-side bloqueia |

---

## Escopo Fora do Design

- Notificações push/email quando o disparo for iniciado automaticamente (não incluído)
- Fuso horário configurável por usuário (fixo em BRT)
- Múltiplos horários agendados para o mesmo broadcast (não aplicável — 1 disparo = 1 horário)
