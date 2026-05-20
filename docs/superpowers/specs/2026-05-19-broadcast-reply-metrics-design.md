# Broadcast Reply Metrics — Design Spec

**Data:** 2026-05-19  
**Status:** Aprovado

---

## Objetivo

Rastrear e exibir métricas reais de resposta por disparo:

| Métrica | Definição |
|---------|-----------|
| **Taxa de Resposta** | % de leads enviados que responderam dentro de 48 h do envio |
| **Tempo Médio de Resposta** | Média de `(first_replied_at − sent_at)` para leads que responderam |

Janela fixa: **48 horas** após `broadcast_leads.sent_at`.

---

## Fora do Escopo

- Taxa de conversão Kanban (já coberta pelo `deal_moved_at`)
- Tempo de atendimento do time
- Opt-out tracking
- Janela configurável por disparo

---

## Modelo de Dados

### Nova coluna em `broadcast_leads`

```sql
-- backend/migrations/20260519_broadcast_leads_first_replied_at.sql
ALTER TABLE broadcast_leads
  ADD COLUMN IF NOT EXISTS first_replied_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_broadcast_leads_replied
  ON broadcast_leads(broadcast_id, first_replied_at)
  WHERE first_replied_at IS NOT NULL;
```

Sem contadores agregados na tabela `broadcasts` — as métricas são computadas sob demanda via RPC para evitar drift.

### Nova função RPC no Supabase

```sql
-- backend/migrations/20260519_broadcast_reply_metrics_rpc.sql
CREATE OR REPLACE FUNCTION get_broadcast_reply_metrics(p_broadcast_id uuid)
RETURNS TABLE(
  replied_count   bigint,
  reply_rate      numeric,
  avg_reply_secs  numeric,
  median_reply_secs numeric
)
LANGUAGE sql STABLE AS $$
  SELECT
    COUNT(*) FILTER (WHERE first_replied_at IS NOT NULL)                          AS replied_count,
    ROUND(
      COUNT(*) FILTER (WHERE first_replied_at IS NOT NULL)::numeric
      / NULLIF(COUNT(*) FILTER (WHERE status IN ('sent','delivered')), 0) * 100,
      1
    )                                                                              AS reply_rate,
    ROUND(
      AVG(EXTRACT(EPOCH FROM (first_replied_at - sent_at)))
        FILTER (WHERE first_replied_at IS NOT NULL),
      0
    )                                                                              AS avg_reply_secs,
    ROUND(
      PERCENTILE_CONT(0.5) WITHIN GROUP (
        ORDER BY EXTRACT(EPOCH FROM (first_replied_at - sent_at))
      ) FILTER (WHERE first_replied_at IS NOT NULL),
      0
    )                                                                              AS median_reply_secs
  FROM broadcast_leads
  WHERE broadcast_id = p_broadcast_id
    AND status IN ('sent', 'delivered');
$$;
```

---

## Arquitetura Backend

### Componente 1 — Webhook hook (tempo real)

**Arquivo:** `backend/app/broadcast/service.py`

Nova função `record_broadcast_reply(lead_id: str) -> None`:

```
1. Query broadcast_leads WHERE lead_id = ? 
     AND status IN ('sent', 'delivered')
     AND first_replied_at IS NULL
     AND sent_at > now() - interval '48 hours'
   ORDER BY sent_at DESC
   LIMIT 1
2. Se encontrado: UPDATE broadcast_leads SET first_replied_at = now() WHERE id = ?
3. Logar resultado (found vs not found)
```

**Arquivo:** `backend/app/buffer/processor.py`

Após o bloco `save_message(... "user" ...)` (linha ~182), adicionar chamada não-bloqueante:

```python
try:
    from app.broadcast.service import record_broadcast_reply
    record_broadcast_reply(lead["id"])
except Exception as e:
    logger.warning("Failed to record broadcast reply for %s: %s", lead["id"], e)
```

Isso é idempotente: se o lead já tem `first_replied_at`, a query retorna 0 rows e não faz nada.

### Componente 2 — Catch-up periódico (resiliência)

**Arquivo:** `backend/app/broadcast/worker.py`

Nova função `reconcile_broadcast_replies()` chamada no loop principal `run_worker()` a cada ciclo (junto com `process_due_cadences` etc.):

```
1. Buscar broadcast_leads WHERE:
     status IN ('sent', 'delivered')
     AND first_replied_at IS NULL
     AND sent_at BETWEEN now()-48h AND now()-2min
   LIMIT 200
2. Para cada lead:
   a. Buscar em messages: role='user' AND lead_id=? AND created_at > sent_at
      ORDER BY created_at ASC LIMIT 1
   b. Se encontrado: UPDATE first_replied_at = messages.created_at
3. Logar contagem de leads reconciliados
```

O `AND sent_at < now()-2min` evita corrida com o webhook que acabou de processar.  
O `LIMIT 200` evita varredura de tabela em disparos grandes.

A função não mantém estado interno — é segura para ser chamada a cada tick do worker (5s), mas roda a query completa só quando há leads pendentes de reconciliação.

---

## Arquitetura Frontend

### Nova rota API: `GET /api/broadcasts/[id]/metrics`

**Arquivo:** `frontend/src/app/api/broadcasts/[id]/metrics/route.ts`

```
1. Chamar supabase.rpc('get_broadcast_reply_metrics', { p_broadcast_id: id })
2. Retornar: { replied_count, reply_rate, avg_reply_secs, median_reply_secs }
3. Se erro ou null: retornar { replied_count: 0, reply_rate: 0, avg_reply_secs: null, median_reply_secs: null }
```

Rota separada (não acoplada ao GET broadcast) para poder ser refrescada independentemente.

### Types

**Arquivo:** `frontend/src/lib/types.ts`

```typescript
export interface BroadcastMetrics {
  replied_count: number;
  reply_rate: number;        // percentual: 0–100
  avg_reply_secs: number | null;
  median_reply_secs: number | null;
}
```

### Componente de detalhe

**Arquivo:** `frontend/src/components/campaigns/broadcast-detail.tsx`

- Fetch `BroadcastMetrics` em paralelo com broadcast e leads (mesmo `Promise.all`)
- 2 novos cards na grade de métricas (expandir de 5 para 7 colunas quando `move_to_stage_id` e métricas existem, ou adaptar responsivamente)
- Card **"Responderam"**: `{replied_count} · {reply_rate}%`
- Card **"Tempo Médio"**: `{formatSeconds(avg_reply_secs)}` (ex: "2h 15min" / "45min" / "—")
- Cards visíveis apenas quando `broadcast.status !== 'draft'`
- `first_replied_at` como nova coluna na tabela de leads (ao lado de "Enviado em"), exibindo hora da resposta formatada ou "—"

#### Formatação de tempo

```
< 60s   → "< 1 min"
< 3600s → "{min} min"
< 86400s → "{h}h {min}min"
≥ 86400s → "{d}d {h}h"
```

---

## Migrations a rodar no Supabase

1. `backend/migrations/20260519_broadcast_leads_first_replied_at.sql`
2. `backend/migrations/20260519_broadcast_reply_metrics_rpc.sql`

Ambas usam `IF NOT EXISTS` / `CREATE OR REPLACE` — idempotentes.

---

## Limitações Conhecidas

- **Broadcasts anteriores**: `first_replied_at` será `NULL` para disparos já concluídos. O catch-up job preenche somente leads dentro da janela de 48h ainda ativa. Disparos antigos mostrarão "—" nas métricas até que dados históricos sejam backfillados manualmente.
- **Múltiplos disparos**: Se um lead estava em 2 broadcasts simultâneos, a função `record_broadcast_reply` atualiza o broadcast_lead mais recente (ORDER BY sent_at DESC LIMIT 1). Isso é o comportamento correto.
- **Mensagens de sistema**: Mensagens com `role='user'` no buffer incluem qualquer texto inbound — incluindo mensagens de sistema/auto-reply da Meta. Não há filtragem de conteúdo por ora.
