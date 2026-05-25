# Plano de Implementação — SLA João Dashboard

**Spec:** `docs/superpowers/specs/2026-05-25-sla-joao-dashboard-design.md`  
**Data:** 2026-05-25  
**Status:** Aprovado

---

## Waves de Execução

Os passos são organizados em 2 waves. Dentro de cada wave, os agentes rodam em paralelo.

---

## Wave 1 — Fundação (paralelo)

### Tarefa 1A — Migração DB

**Arquivos:** `backend/migrations/20260525_sla_seller_columns.sql`

1. Adicionar à tabela `conversations`:
   ```sql
   ALTER TABLE conversations
     ADD COLUMN IF NOT EXISTS first_seller_response_at TIMESTAMPTZ,
     ADD COLUMN IF NOT EXISTS last_seller_response_at  TIMESTAMPTZ;
   ```

2. Criar trigger em `messages` (AFTER INSERT):
   ```sql
   CREATE OR REPLACE FUNCTION update_conversation_seller_response()
   RETURNS trigger AS $$
   BEGIN
     IF NEW.sent_by = 'seller' AND NEW.conversation_id IS NOT NULL THEN
       UPDATE conversations
       SET
         last_seller_response_at  = NEW.created_at,
         first_seller_response_at = COALESCE(first_seller_response_at, NEW.created_at)
       WHERE id = NEW.conversation_id;
     END IF;
     RETURN NEW;
   END;
   $$ LANGUAGE plpgsql;

   DROP TRIGGER IF EXISTS trg_conversation_seller_response ON messages;
   CREATE TRIGGER trg_conversation_seller_response
     AFTER INSERT ON messages
     FOR EACH ROW EXECUTE FUNCTION update_conversation_seller_response();
   ```

3. Backfill:
   ```sql
   UPDATE conversations c
   SET
     first_seller_response_at = sub.first_at,
     last_seller_response_at  = sub.last_at
   FROM (
     SELECT
       conversation_id,
       MIN(created_at) AS first_at,
       MAX(created_at) AS last_at
     FROM messages
     WHERE sent_by = 'seller' AND conversation_id IS NOT NULL
     GROUP BY conversation_id
   ) sub
   WHERE c.id = sub.conversation_id;
   ```

4. Criar índice:
   ```sql
   CREATE INDEX IF NOT EXISTS idx_conversations_channel_id
     ON conversations(channel_id);
   ```

5. Aplicar migration via Supabase MCP (`apply_migration`).
6. Verificar: `SELECT COUNT(*) FROM conversations WHERE last_seller_response_at IS NOT NULL;`

---

### Tarefa 1B — Utilitário business-hours.ts

**Arquivo:** `frontend/src/lib/business-hours.ts`

Implementar usando `Intl.DateTimeFormat` para obter hora/dia local em `America/Sao_Paulo` sem lib externa.

```ts
const TZ = "America/Sao_Paulo";
const BUSINESS_START = 10; // hora (inclusive)
const BUSINESS_END   = 16; // hora (exclusive — conta até 16h00:00)

function getLocalParts(date: Date): { year: number; month: number; day: number; hour: number; minute: number; dow: number } {
  // Usar Intl para decompor no fuso correto
}

// Retorna minutos dentro do segmento comercial de um dado dia
function businessMinutesInDay(dayStart: Date, clampFrom: Date, clampTo: Date): number

export function businessMinutesBetween(from: Date, to: Date): number
export function businessMinutesElapsed(from: Date): number  // businessMinutesBetween(from, new Date())
export function isInBusinessHours(date?: Date): boolean
export function formatBusinessDuration(minutes: number): string  // "12min" | "1h23m"
```

**Testes unitários** (`frontend/src/lib/__tests__/business-hours.test.ts`):
- Caso canônico: 15h55 sex → 10h10 seg = 15 min
- Mensagem às 16h01 (fora do horário) → 0 min até 16h01 mesmo dia
- Mensagem às 9h → 0 min até 10h mesmo dia, então conta a partir das 10h
- Fim de semana inteiro não conta
- Mesmo dia, dentro do horário: 10h30 → 11h00 = 30 min

---

## Wave 2 — UI + API (paralelo, após Wave 1)

### Tarefa 2A — Dashboard SLA Hero

**Arquivos:**
- `frontend/src/hooks/use-joao-sla-stats.ts` (novo)
- `frontend/src/components/dashboard/sla-hero-section.tsx` (novo, usa shadcn)
- `frontend/src/app/(authenticated)/dashboard/page.tsx` (modificar)

**OBRIGATÓRIO:** Usar skill `frontend-design` antes de implementar o componente.

#### Hook `useJoaoSlaStats`

```ts
const JOAO_CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd";

export type DateFilter = "1d" | "7d" | "30d" | "all";

export function useJoaoSlaStats(filter: DateFilter = "7d") {
  // 1. Buscar TODAS as conversas do canal João (sem limit, paginação .range(0,999) + loop se necessário)
  //    Campos: id, created_at, first_seller_response_at, last_seller_response_at,
  //            leads(last_customer_message_at)
  //    Filtro de data: WHERE created_at >= cutoff (calculado a partir de filter)
  //
  // 2. Computar:
  //    - avgSlaMinutes: média de businessMinutesBetween(created_at, first_seller_response_at)
  //      apenas para rows onde first_seller_response_at IS NOT NULL
  //    - overdueCount: rows onde
  //        (last_seller_response_at IS NULL OR last_customer_message_at > last_seller_response_at)
  //        AND businessMinutesElapsed(last_customer_message_at) > 20
  //    - worstSlaTodayMinutes: MAX de businessMinutesBetween(created_at, first_seller_response_at)
  //        para rows onde first_seller_response_at::date = today (em Sao Paulo)
  //
  // 3. Realtime subscription em "conversations" channel → refetch ao mudar
}
```

#### Componente `SlaHeroSection`

- Usar shadcn `Select` para filtro de período.
- 3 cards de métrica lado a lado (shadcn `Card` ou estilo existente do projeto — verificar KpiCard).
- Card "Em atraso agora" deve pulsar/ter cor de destaque quando > 0 (vermelho ou âmbar).
- Loading state com skeleton.
- Verificar padrão visual em `components/kpi-card.tsx` antes de criar novos componentes — se KpiCard aceitar as props necessárias, reusá-lo.

#### Dashboard page

Adicionar `<SlaHeroSection />` entre o header e o grid de KPIs atual:
```tsx
// Após o header, antes do grid de KPIs
<SlaHeroSection />
```

---

### Tarefa 2B — Chat List Box Vermelho + API

**Arquivos:**
- `frontend/src/lib/types.ts` (modificar Conversation)
- `frontend/src/app/api/conversations/route.ts` (modificar select)
- `frontend/src/components/conversas/chat-list.tsx` (modificar)

**OBRIGATÓRIO:** Usar skill `frontend-design` antes de implementar estilos visuais.

#### 1. Atualizar `types.ts`

```ts
export interface Conversation {
  // ... campos existentes ...
  first_seller_response_at: string | null;  // NOVO
  last_seller_response_at:  string | null;  // NOVO
}
```

#### 2. Atualizar API `/api/conversations/route.ts`

No select do Supabase, adicionar os campos novos ao join/select de conversations:
```
first_seller_response_at,
last_seller_response_at
```

#### 3. Atualizar `chat-list.tsx`

Adicionar:
```ts
// Hook que força re-render a cada minuto para atualizar o SLA em tempo real
const [tick, setTick] = useState(0);
useEffect(() => {
  const id = setInterval(() => setTick(t => t + 1), 60_000);
  return () => clearInterval(id);
}, []);
```

Função de detecção de SLA breach:
```ts
function isSlaBreached(conv: Conversation): boolean {
  const channel = conv.channels;
  if (channel?.mode !== "human") return false;
  const lastCustomer = conv.leads?.last_customer_message_at;
  if (!lastCustomer) return false;
  const lastSeller = conv.last_seller_response_at;
  if (lastSeller && lastSeller >= lastCustomer) return false; // respondido
  return businessMinutesElapsed(new Date(lastCustomer)) > 20;
}
```

Aplicar estilo no card da conversa:
- Box vermelho: `border-l-[3px] border-l-[#dc2626] bg-[#fef2f2]` (não sobrescreve o estado `isActive`)
- Não conflitar com o `windowBg` existente (janela Meta 24h): SLA vermelho tem prioridade visual quando não está ativo.

---

## Sequência Final

```
Wave 1A (DB migration) ─┐
Wave 1B (business-hours) ┤── paralelo ──► Wave 2A (dashboard hero)
                         └──────────────► Wave 2B (chat list + API)
```

Wave 2 só começa após Wave 1 completo.

---

## Checklist de Verificação

- [ ] `SELECT COUNT(*) FROM conversations WHERE last_seller_response_at IS NOT NULL` retorna > 0 (backfill funcionou)
- [ ] Dashboard mostra 3 KPIs SLA com dados reais
- [ ] Filtro de período funciona (Hoje / 7d / 30d / Tudo)
- [ ] Card "Em atraso" atualiza em tempo real via Realtime
- [ ] Conversa sem resposta há > 20 min comerciais fica com borda vermelha no chat list
- [ ] Conversa respondida pelo vendedor sai do vermelho imediatamente (Realtime)
- [ ] Teste unitário do businessMinutesBetween: caso canônico 15h55→10h10 = 15 min
- [ ] Fim de semana não conta no SLA (test)
- [ ] Commit **sem** push — aguardar aprovação do usuário para fazer o push
