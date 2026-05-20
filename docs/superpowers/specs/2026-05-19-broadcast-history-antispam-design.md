# Broadcast History & Anti-Spam — Design Spec

**Data:** 2026-05-19
**Status:** Aprovado

---

## Objetivo

Dois recursos relacionados ao histórico de disparos por lead:

1. **Histórico de disparos por lead** — Exibir, na sidebar e no modal de detalhes do lead, todos os disparos que o lead recebeu (com status de entrega e se respondeu).
2. **Anti-spam no disparo** — Ao clicar em "Iniciar" ou "Retomar" em um disparo, verificar se algum lead nesse disparo recebeu outro disparo nas últimas 48 horas. Se sim: remover esses leads do disparo atual, criar um novo rascunho com eles, e disparar apenas para os demais.

---

## Fora do Escopo

- Mensagens template enviadas de `/conversas` (reativação de conversa) — não são "disparos"
- Janela de 48h configurável — fixa em 48 horas
- Agendamento dos leads removidos — o rascunho criado fica para o operador disparar manualmente
- Opt-out tracking
- Histórico de cadências (já existe na aba "Campanhas" do modal)

---

## 1. Backfill `deal_moved_at`

**Arquivo:** `backend/migrations/20260519_backfill_deal_moved_at.sql`

Já criado. Atualiza `deal_moved_at = CURRENT_TIMESTAMP` para todas as `broadcast_leads` onde o deal já está na etapa correta, mas `deal_moved_at` está NULL (caso dos disparos anteriores à migration).

**Ação do operador:** executar manualmente no Supabase SQL Editor.

---

## 2. Histórico de Disparos por Lead

### API

**`GET /api/leads/[id]/broadcasts/route.ts`**

Query:
```sql
SELECT
  bl.id,
  bl.broadcast_id,
  b.name  AS broadcast_name,
  b.status AS broadcast_status,
  bl.status AS message_status,
  bl.sent_at,
  bl.first_replied_at
FROM broadcast_leads bl
JOIN broadcasts b ON b.id = bl.broadcast_id
WHERE bl.lead_id = :id
ORDER BY bl.sent_at DESC NULLS LAST;
```

Resposta (array JSON):
```typescript
interface LeadBroadcastEntry {
  id: string;
  broadcast_id: string;
  broadcast_name: string;
  broadcast_status: string;
  message_status: string; // pending | sent | delivered | failed
  sent_at: string | null;
  first_replied_at: string | null;
}
```

### Componente

**`frontend/src/components/leads/lead-broadcast-history.tsx`**

Props: `leadId: string`

Comportamento:
- Fetch `GET /api/leads/${leadId}/broadcasts` no mount
- Renderiza lista compacta: nome do disparo, badge de status de mensagem, data de envio, badge "Respondeu" se `first_replied_at` não nulo
- Se lista vazia: texto "Nenhum disparo recebido"
- Loading state: skeleton de 2 linhas

Badge de `message_status`:
- `pending` → cinza, "Pendente"
- `sent` → azul, "Enviado"
- `delivered` → verde, "Entregue"
- `failed` → vermelho, "Falhou"

Badge "Respondeu": aparece apenas se `first_replied_at IS NOT NULL` — cor verde, texto "Respondeu"

### Integração — Sidebar

**`frontend/src/components/lead-detail-sidebar.tsx`**

Adicionar seção abaixo dos deals:
```
DISPAROS RECEBIDOS
<LeadBroadcastHistory leadId={lead.id} />
```

### Integração — Modal

**`frontend/src/components/leads/lead-detail-modal.tsx`**

Na aba "Campanhas" (`activeTab === "campanhas"`), após a seção de cadências, adicionar:

```
DISPAROS RECEBIDOS
<LeadBroadcastHistory leadId={lead.id} />
```

O componente faz seu próprio fetch — não precisa de dados extras do modal.

---

## 3. Anti-Spam ao Disparar

### API — Verificação

**`GET /api/broadcasts/[id]/spam-check/route.ts`**

Retorna leads deste disparo (status `pending`) que receberam outro disparo nas últimas 48h:

```sql
SELECT
  bl.lead_id,
  l.name   AS lead_name,
  l.phone  AS lead_phone,
  lb.broadcast_id AS last_broadcast_id,
  b2.name  AS last_broadcast_name,
  lb.sent_at AS last_sent_at
FROM broadcast_leads bl
JOIN leads l ON l.id = bl.lead_id
JOIN broadcast_leads lb ON lb.lead_id = bl.lead_id
  AND lb.broadcast_id != bl.broadcast_id
  AND lb.status IN ('sent', 'delivered')
  AND lb.sent_at > NOW() - INTERVAL '48 hours'
JOIN broadcasts b2 ON b2.id = lb.broadcast_id
WHERE bl.broadcast_id = :id
  AND bl.status = 'pending'
ORDER BY lb.sent_at DESC;
```

Resposta:
```typescript
interface SpamConflict {
  lead_id: string;
  lead_name: string | null;
  lead_phone: string;
  last_broadcast_id: string;
  last_broadcast_name: string;
  last_sent_at: string;
}

// Response body:
{ conflicts: SpamConflict[] }
```

Pode retornar múltiplas linhas por lead (se esteve em vários disparos recentes). O frontend deduplica por `lead_id` para exibição, mas passa a lista completa de `lead_id`s únicos para o resolve.

### API — Resolução

**`POST /api/broadcasts/[id]/resolve-spam/route.ts`**

Body:
```json
{ "conflict_lead_ids": ["uuid1", "uuid2"] }
```

Etapas (atômicas via Supabase):
1. Buscar o broadcast original completo (`SELECT *` para copiar campos)
2. Criar novo broadcast draft:
   - `name = "Rascunho - " + original.name`
   - Copiar: `channel_id, template_name, template_language_code, template_preset_id, template_variables, send_interval_min, send_interval_max, cadence_id, agent_profile_id, move_to_stage_id, env_tag`
   - `status = 'draft'`, `scheduled_at = null`, `total_leads = conflict_lead_ids.length`
3. Deletar `broadcast_leads` do disparo original onde `lead_id IN conflict_lead_ids`
4. Atualizar `total_leads` do disparo original (`COUNT(*) WHERE broadcast_id = id`)
5. Inserir `broadcast_leads` no novo broadcast para cada `conflict_lead_id` (`status = 'pending'`)

Resposta:
```json
{
  "new_broadcast_id": "uuid",
  "new_broadcast_name": "Rascunho - X",
  "removed_count": 3
}
```

Em caso de erro em qualquer etapa: retornar 500 com `{ error: mensagem }`.

### Frontend — Modificação do `handleStart`

**`frontend/src/components/campaigns/broadcast-detail.tsx`**

Novo fluxo de `handleStart`:

```
1. setActionLoading(true)
2. GET /api/broadcasts/${id}/spam-check
3. Se conflicts.length === 0:
   → POST /api/broadcasts/${id}/start
   → atualizar estado, fim
4. Se conflicts.length > 0:
   → setSpamConflicts(deduplicated conflicts por lead_id)
   → setShowSpamModal(true)
   → setActionLoading(false)  // modal assume o controle
```

### Novo Componente — `SpamWarningModal`

**Inline em `broadcast-detail.tsx`** (não arquivo separado — modal simples, ~80 linhas JSX)

Props (via estado interno do BroadcastDetail):
- `conflicts: SpamConflict[]` — lista já deduplicada por lead_id
- `onConfirm: () => void`
- `onCancel: () => void`

Layout:
```
[Modal overlay]
  Título: "Leads disparados recentemente"
  Subtítulo: "X lead(s) abaixo receberam um disparo nas últimas 48h.
              Eles serão removidos deste disparo e adicionados a um
              novo rascunho para você disparar depois."

  [Tabela]
  Nome        | Telefone    | Último disparo   | Enviado em
  -----------   -----------   ---------------   ----------
  João Silva  | 5511999...  | Disparo REVENDA  | 19/05 14:32

  [Cancelar]  [Remover e Disparar]
```

Ao clicar "Remover e Disparar":
1. `setConfirmLoading(true)`
2. `POST /api/broadcasts/${id}/resolve-spam` com `conflict_lead_ids`
3. `POST /api/broadcasts/${id}/start`
4. Fechar modal, atualizar `broadcast.status = 'running'`
5. Toast (alert simples): `"${removed_count} lead(s) movidos para rascunho '${new_broadcast_name}'"`

---

## Tipos TypeScript

**`frontend/src/lib/types.ts`** — adicionar:

```typescript
export interface LeadBroadcastEntry {
  id: string;
  broadcast_id: string;
  broadcast_name: string;
  broadcast_status: string;
  message_status: string;
  sent_at: string | null;
  first_replied_at: string | null;
}

export interface SpamConflict {
  lead_id: string;
  lead_name: string | null;
  lead_phone: string;
  last_broadcast_id: string;
  last_broadcast_name: string;
  last_sent_at: string;
}
```

---

## Migrations a Rodar no Supabase

1. `backend/migrations/20260519_backfill_deal_moved_at.sql` — backfill de deal_moved_at (novo)

Não há novas colunas ou índices nessa feature — usa dados já existentes.

---

## Limitações Conhecidas

- **Múltiplos conflitos por lead**: se um lead recebeu 2 disparos recentes, o spam-check retorna 2 linhas. O frontend exibe apenas o mais recente (ORDER BY sent_at DESC, dedup por lead_id).
- **Corrida de disparo**: se dois operadores clicam "Disparar" ao mesmo tempo, ambos verão 0 conflitos antes de qualquer lead ser marcado `sent`. Não é um caso real no contexto atual (time pequeno).
- **Leads sem nome**: exibir telefone como fallback.
