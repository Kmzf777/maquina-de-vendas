# SLA João — Dashboard Hero + Box Vermelho Conversas

**Data:** 2026-05-25  
**Status:** Aprovado pelo usuário

---

## 1. Objetivo

Medir o tempo de resposta humana do vendedor João (NUMERO JOÃO, `mode='human'`) contando apenas minutos dentro do horário comercial (10h–16h, Seg–Sex, America/Sao_Paulo). Exibir 3 KPIs na hero da dashboard e sinalizar visualmente conversas atrasadas na aba WhatsApp.

---

## 2. Escopo

- **Canal alvo:** `channels` onde `mode='human'` (atualmente só "NUMERO JOÃO", `channel_id: a3a607b1-6bff-4370-8609-b275eef270dd`).
- **Quem é o vendedor:** mensagens com `sent_by='seller'`.
- **Quem é o cliente:** mensagens com `sent_by='user'`.
- **Respostas da IA** (`sent_by='agent'`) **não param o cronômetro.**

---

## 3. Regra de Negócio — Cálculo de SLA

### Janela comercial
- **Horário:** 10h00 às 16h00 (6h por dia útil = 360 min/dia)
- **Dias:** Seg–Sex (feriados nacionais BR não excluídos na v1)
- **Fuso:** America/Sao_Paulo (UTC-3 ou UTC-2 no horário de verão)

### Cálculo de minutos comerciais entre `t_start` e `t_end`
1. Se `t_start` >= `t_end`, resultado = 0.
2. Segmente o intervalo dia a dia.
3. Para cada dia, calcule a interseção entre `[t_start, t_end]` e `[10h, 16h]` naquele dia.
4. Ignore sábado e domingo.
5. Some as interseções em minutos.

**Exemplo canônico (do requisito):**
- Mensagem chegou: 15h55 sexta
- Resposta: 10h10 segunda
- Minutos computados: 5 min (sexta 15h55→16h00) + 10 min (segunda 10h00→10h10) = **15 min**

### Threshold do box vermelho
- **20 minutos comerciais** acumulados sem resposta do vendedor.

---

## 4. Modelo de Dados

### 4.1 Novas colunas em `conversations`

```sql
first_seller_response_at  TIMESTAMPTZ  -- primeira resposta seller nesta conversa
last_seller_response_at   TIMESTAMPTZ  -- resposta seller mais recente
```

### 4.2 Trigger em `messages`

Ao inserir mensagem com `sent_by='seller'`:
- Atualiza `conversations.last_seller_response_at` sempre.
- Atualiza `conversations.first_seller_response_at` se ainda for NULL.

### 4.3 Backfill

SQL de backfill para popular os campos a partir de mensagens históricas:
- `first_seller_response_at` ← MIN `created_at` de mensagens `sent_by='seller'` por conversa.
- `last_seller_response_at` ← MAX `created_at`.

### 4.4 Tipo Conversation no frontend

Adicionar ao `interface Conversation` em `types.ts`:
```ts
first_seller_response_at: string | null;
last_seller_response_at:  string | null;
```

---

## 5. Utilitário `business-hours.ts`

Arquivo: `frontend/src/lib/business-hours.ts`

Funções exportadas:

```ts
// Minutos comerciais entre dois timestamps (America/Sao_Paulo, 10h-16h Seg-Sex)
function businessMinutesBetween(from: Date, to: Date): number

// Minutos comerciais acumulados desde `from` até agora
function businessMinutesElapsed(from: Date): number

// true se agora está dentro da janela comercial
function isInBusinessHours(): boolean

// Formata minutos comerciais como "12min" ou "1h23m"
function formatBusinessDuration(minutes: number): string
```

**Implementação:** iteração por intervalos de 1 minuto seria lenta — usar a abordagem de segmentação por dia:
1. Para cada dia no intervalo, clipe ao intervalo 10h–16h local.
2. Ignore dias de fim de semana.
3. Acumule os minutos de sobreposição.

**Timezone:** usar `Intl.DateTimeFormat` com `America/Sao_Paulo` para obter hora/dia local sem dependência externa.

---

## 6. Dashboard — Hero SLA

### 6.1 Localização

Inserir abaixo do header da dashboard e acima do grid de KPIs existente.

### 6.2 Componente `SlaHeroSection`

Arquivo: `frontend/src/components/dashboard/sla-hero-section.tsx`

**Layout (3 cards lado a lado):**

```
┌──────────────────────────────────────────────────────────────────┐
│  SLA — Tempo de Resposta João                    [Filtro: 7 dias ▾]│
├────────────────┬────────────────┬──────────────────────────────┤
│  Média         │  Em atraso     │  Pior SLA hoje               │
│  12min         │  3 conversas   │  1h45m                       │
│  [horário com.]│  [> 20min]     │  [maior tempo registrado]    │
└────────────────┴────────────────┴──────────────────────────────┘
```

### 6.3 Hook `useJoaoSlaStats`

Arquivo: `frontend/src/hooks/use-joao-sla-stats.ts`

- Busca **todas** as conversas do canal João (`channel_id = a3a607b1...`) sem limit — usa paginação de 1000 rows por vez via `.range()`.
- Aceita `dateFilter: '1d' | '7d' | '30d' | 'all'` como parâmetro.
- Filtra `created_at` conforme o filtro.
- Retorna:
  - `avgSlaMinutes: number | null` — média de `businessMinutesBetween(created_at, first_seller_response_at)` para conversas com ambos os campos.
  - `overdueCount: number` — conversas em modo humano onde `last_customer_message_at > last_seller_response_at` (ou `last_seller_response_at` é null) E `businessMinutesElapsed(last_customer_message_at) > 20`.
  - `worstSlaTodayMinutes: number | null` — maior SLA dentre conversas cuja `first_seller_response_at` é hoje.
- Suporta Realtime subscription em `conversations` para atualizar em tempo real.

### 6.4 Filtros

Dropdown simples usando shadcn `Select`:
- Hoje
- Últimos 7 dias (padrão)
- Últimos 30 dias
- Tudo

---

## 7. Chat List — Box Vermelho

### 7.1 Condição de box vermelho

```
canal é mode='human'
E last_customer_message_at não é null
E (last_seller_response_at é null OU last_customer_message_at > last_seller_response_at)
E businessMinutesElapsed(last_customer_message_at) > 20
```

### 7.2 Implementação

- `chat-list.tsx` já recebe `conversations` com dados de `leads` joinados.
- API de conversas (`/api/conversations/route.ts`) precisa retornar `last_seller_response_at` e `first_seller_response_at`.
- Lógica de cor: substituir ou complementar o `getWindowBgClass` atual com a verificação SLA.
- Estilo do card vermelho: `border-l-[3px] border-l-red-500 bg-red-50` (ou equivalente na paleta do projeto).
- O timer atualiza a cada minuto (via `useEffect` com `setInterval(60_000)`).

### 7.3 Indicador visual

- Borda esquerda vermelha no card + fundo levemente rosado.
- Não substitui os indicadores existentes (janela Meta 24h), apenas adiciona a camada SLA.

---

## 8. API de Conversas

`/api/conversations/route.ts` — atualizar o select do Supabase para incluir:
```
first_seller_response_at,
last_seller_response_at
```

---

## 9. O que NÃO está no escopo (v1)

- Feriados nacionais brasileiros (desconsidera — só Seg–Sex)
- SLA por canal ValerIA
- SLA por mensagem individual (apenas por conversa — "tempo até a primeira resposta do vendedor")
- Notificações push/alertas automáticos por threshold

---

## 10. Arquivos criados/modificados

| Arquivo | Ação |
|---------|------|
| `backend/migrations/20260525_sla_seller_columns.sql` | Nova migration |
| `frontend/src/lib/business-hours.ts` | Novo utilitário |
| `frontend/src/lib/types.ts` | Adicionar campos ao Conversation |
| `frontend/src/hooks/use-joao-sla-stats.ts` | Novo hook |
| `frontend/src/components/dashboard/sla-hero-section.tsx` | Novo componente |
| `frontend/src/app/(authenticated)/dashboard/page.tsx` | Adicionar SlaHeroSection |
| `frontend/src/app/api/conversations/route.ts` | Incluir novos campos no select |
| `frontend/src/components/conversas/chat-list.tsx` | Box vermelho SLA |
