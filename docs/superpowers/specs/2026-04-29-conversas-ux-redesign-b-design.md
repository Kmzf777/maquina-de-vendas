# Conversas UX Redesign — Fase B (Design Spec)

**Data:** 2026-04-29
**Branch:** `feat/conversas-ux-redesign-v2`
**Audit base:** `docs/superpowers/specs/2026-04-29-conversas-ux-audit.md`

## Contexto

A página `/conversas` é a tela mais usada pelos vendedores (atendimento de leads via WhatsApp). Foi construída incrementalmente e features foram empilhadas sem revisão de hierarquia visual. O cliente reportou três dores principais (mensagem nova invisível, datas confusas, janela 24h obscura) e o audit detectou outras seis dores graves.

Esta entrega ataca o subset de maior impacto percebido para devolver a sensação de "página redesenhada" sem virar projeto de mês.

## Escopo

### Dentro do escopo
1. Backend: campo `unread_count` em `conversations`, lógica de increment/reset, endpoint `mark-read`, exposição no payload da API.
2. Frontend: helper `lib/datetime.ts` único e adoção em toda a página `/conversas`.
3. Componente `WhatsappWindowIndicator` unificado com 3 variants e 4 estados.
4. Toggle Valéria movido de `contact-detail.tsx` para o `ChatHeader`.
5. Card selecionado redesenhado (borda lateral + fundo warm-leve, fim do `bg-[#111111]`).
6. Lista de conversas com 3 níveis tipográficos + badge de não-lidas (Fin Orange + contador, pulse).

### Fora do escopo (Fase 3 futura)
- Delivery ticks (✓ / ✓✓ / ✓✓ azul) nas bolhas
- Atalhos de teclado (j/k, ctrl+/, etc.)
- Accessibility full (ARIA states, focus trap em modais, etc.) — só o básico (focus visible, contraste mínimo)
- Mobile/responsividade
- Refactor completo das duplicações de stage colors (`AGENT_STAGES` em 3 lugares)
- Sound notification, browser notification, tab title pulse

## Design system de referência

Todas as mudanças de front-end devem invocar a skill `frontend-design` antes de escrever JSX/CSS/Tailwind. Cores warm-only conforme design system; sem `bg-red-500`, `bg-amber-*` ou outras cores frias na página `/conversas`.

Tokens principais usados:
- **Fin Orange** — cor de destaque/CTA (mesma usada em outras páginas críticas)
- **Warm neutrals** — `stone-*` ou paleta equivalente do design system
- **Status colors** — derivados da paleta warm (sem `red-500` puro)

---

## 1. Backend — `unread_count`

### Schema
Adicionar coluna em `conversations`:

```sql
ALTER TABLE conversations
ADD COLUMN unread_count INTEGER NOT NULL DEFAULT 0;
```

Migration deve fazer backfill `unread_count = 0` para todas as conversas existentes.

### Lógica de increment
Em `backend/app/buffer/processor.py`, no ponto onde uma mensagem inbound é persistida na conversa, incrementar `unread_count` da conversa em 1.

**Não incrementa** para mensagens outbound (vendedor ou IA).

### Lógica de reset
Novo endpoint:

```
POST /conversations/{conversation_id}/mark-read
→ 204 No Content
```

Comportamento: `UPDATE conversations SET unread_count = 0 WHERE id = $1`. Idempotente.

### Frontend trigger do reset
Quando o usuário clica em uma conversa na lista (e ela vira a `selectedConversationId`), o frontend chama `POST /conversations/{id}/mark-read`. Após sucesso, atualiza o estado local zerando o contador. Sem optimistic update — esperamos a resposta para evitar inconsistência se o backend recusar.

### Exposição no payload
`GET /conversations` retorna `unread_count: number` para cada item da lista.

`GET /conversations/{id}` também inclui (caso seja útil em outros pontos).

### Tipos
`frontend/src/lib/types.ts`: adicionar `unread_count: number` ao type `Conversation`.

---

## 2. Datetime helper único — `lib/datetime.ts`

Novo arquivo `frontend/src/lib/datetime.ts` com três funções:

### `formatRelativeTime(iso: string): string`
Para timestamps em **cards da lista**:
- < 1 minuto: `agora`
- < 60 minutos: `Nmin` (ex: `5min`, `42min`)
- Mesmo dia: `HH:mm` (ex: `14:30`)
- Ontem: `Ontem`
- < 7 dias: nome do dia abreviado (ex: `qua`, `seg`)
- > 7 dias: `dd/MM/yyyy` (ex: `12/03/2025`)

### `formatTimeOnly(iso: string): string`
Para timestamps em **bolhas de mensagem**: sempre `HH:mm` (ex: `14:30`).

### `formatDayLabel(iso: string): string`
Para **separadores de dia** no MessageList:
- Hoje: `Hoje`
- Ontem: `Ontem`
- < 7 dias: nome do dia completo (ex: `quarta-feira`)
- > 7 dias: `dd 'de' MMMM` (ex: `12 de março`)
- Ano diferente: `dd 'de' MMMM 'de' yyyy`

### Implementação
- Usar `date-fns` (já está no projeto — verificar) com locale `pt-BR`
- Todas as funções recebem ISO string e fazem parse interno
- Retornam string vazia se input inválido (não throw)

### Migração
Substituir TODAS as ocorrências em:
- `chat-list.tsx` (`formatTime` interno)
- `message-bubble.tsx` (`formatTime` interno)
- `day-separator.tsx` (`formatDayLabel` interno)
- Qualquer outro `format(...)` ad-hoc na página

---

## 3. `WhatsappWindowIndicator` unificado

Novo componente: `frontend/src/components/conversas/whatsapp-window-indicator.tsx`

### Props

```ts
type Props = {
  expiresAt: string | null  // ISO; null = sem janela aberta
  variant: 'compact' | 'header' | 'banner'
}
```

### Estados (derivados de `expiresAt` vs `now`)
| Estado | Condição | Visual |
|---|---|---|
| `active` | > 4h restantes | dot/pill warm-neutro, label opcional `XXh` |
| `warning` | 1h–4h restantes | dot/pill amber-warm (não vermelho frio), label `Xh restantes` |
| `critical` | < 1h restante | dot/pill Fin Orange, label `Xmin restantes`, pulse animation |
| `expired` | passou | banner/pill cinza-bloqueado, label `Janela expirada — só template` |

### Variants
- **`compact`** — usado nos cards da lista. Apenas um dot colorido + opcionalmente "Xh" em texto bem pequeno (`text-xs`). Sem tooltip (lista densa demais).
- **`header`** — usado no `ChatHeader`. Pill com dot + label de tempo restante. **Tooltip ao hover** explicando: *"Após 24h sem nova mensagem do lead, só é possível enviar templates aprovados pela Meta. Aguarde uma resposta ou use a aba 'Reativar'."*
- **`banner`** — usado em `chat-view` quando `expired`. Banner full-width no topo do chat com label maior e link/botão para reativação.

### Substitui
- Emojis ⏳/⏱/🔒/🔴 em `chat-list.tsx`
- Indicador atual em `chat-header.tsx`
- Pill em `chat-view.tsx`
- Topo de `window-reactivate-panel.tsx` (mantém o painel de reativação em si, só troca o cabeçalho)

### Backend (já existe?)
Auditar se `whatsapp_window_expires_at` (ou equivalente) já é exposto pelo backend. Se não, expor no payload de conversa. Não precisa ser nova coluna — é derivável de `last_inbound_message_at + 24h`.

---

## 4. Toggle Valéria no `ChatHeader`

### Visual
Pill-switch (não checkbox) com 2 estados:
- **Ativa**: bg Fin Orange, texto branco/escuro contrastante, label `Valéria IA · Ativa`
- **Pausada**: bg cinza-warm neutro, texto stone-700, label `Valéria IA · Pausada`

### Posição
Lado direito do `ChatHeader`, antes de qualquer botão de fechar/menu. Visível e clicável em 1 clique. Tamanho compatível com `text-xs` ou `text-sm`.

### Comportamento
- Click toggla o estado e dispara request ao backend (mesmo endpoint que `contact-detail.tsx` usa hoje)
- Optimistic update OK aqui (a race condition já foi corrigida no commit `c93d889`, vamos manter o padrão dele)
- Loading state: dot pulse durante a request

### Remoção do antigo
Remover o toggle de `contact-detail.tsx`. A sidebar direita fica mais limpa — verificar o que sobra e se vale colapsar/simplificar (decisão local do agent que implementar, dentro do escopo da Fase B).

---

## 5. Card selecionado redesenhado

### Atual
`bg-[#111111]` (preto sólido) — destrói hierarquia, força `text-white/60` em meta-dados (contraste ruim).

### Novo
- Estado `default`: fundo transparente ou warm-25 muito leve, texto stone-700/900
- Estado `hover`: fundo warm-50
- Estado `selected`:
  - Borda esquerda 3px **Fin Orange** (visual primary)
  - Fundo warm-50 ou warm-100 (leve, preserva legibilidade)
  - Sem inverter cores de texto
- Estado `focus-visible`: ring 2px Fin Orange (a11y básica)

### Resultado
Meta-dados (timestamp, stage pill, indicador 24h) continuam legíveis. Hierarquia preservada. Estado selecionado claro mas não invasivo.

---

## 6. Lista — 3 níveis tipográficos + badge de não-lidas

### Estrutura do card

```
┌────────────────────────────────────────────────┐
│ [avatar]  L1: Nome do Lead             [badge] │
│           L2: Preview da última msg…           │
│           L3: 14:30  ·  Stage  ·  ◉ 12h        │
└────────────────────────────────────────────────┘
```

### Níveis tipográficos
- **L1 (primary)** — Nome do lead. `text-sm font-semibold` em estado normal. **`font-bold`** quando `unread_count > 0`.
- **L2 (secondary)** — Preview da última mensagem. `text-sm text-stone-600 truncate`. Prefixar com `Você: ` ou `IA: ` quando outbound (decidir no agent — manter padrão atual se já fizer isso).
- **L3 (meta)** — `text-xs text-stone-500 flex gap-2 items-center`. Contém: timestamp via `formatRelativeTime`, stage pill (mantendo cores atuais por enquanto — cleanup é Fase 3), `WhatsappWindowIndicator` variant `compact`.

### Badge de não-lidas
- Posição: canto superior direito do card, alinhado verticalmente com L1
- Visual: pill Fin Orange (mesma cor do toggle ativo da Valéria)
- Conteúdo: número (`unread_count`); se > 9, exibe `9+`
- Animação: `animate-pulse` Tailwind (sutil) quando há não-lidas
- Esconde quando `unread_count === 0`

### Sort
Ordenar a lista por `last_message_at DESC` (manter comportamento atual, só verificar). Conversas com não-lidas sobem naturalmente porque tiveram mensagem recente.

---

## Plano de execução (resumo)

1. **Spec** (este documento) — ✅
2. **Plano de implementação** — `docs/superpowers/plans/2026-04-29-conversas-ux-redesign-b.md` (próximo passo via `writing-plans`)
3. **Execução** — via `executing-plans` skill, com subagents paralelos onde possível.
4. **Regra obrigatória do projeto:** todo subagent que tocar em código de front-end DEVE invocar a skill `frontend-design` antes de escrever JSX/CSS/Tailwind. Anotado em cada step relevante do plano.

## Critério de sucesso

- Vendedor abre `/conversas` e identifica conversas com mensagem nova em < 1 segundo (badge visível)
- Datas/horas são consistentes entre lista, header e bolhas
- Vendedor entende o estado da janela 24h sem precisar perguntar (visual + tooltip)
- Toggle Valéria é acessível em 1 clique do header
- Card selecionado não destrói hierarquia visual
- Nenhuma regressão de comportamento (envio de mensagem, abertura de conversa, sidebar, etc.)

## Riscos

- **Migration `unread_count`**: rodar em produção precisa de coordenação. Default 0 + backfill 0 minimiza risco.
- **`mark-read` race**: se vendedor abre/fecha rápido várias conversas, várias requests concorrentes. Endpoint é idempotente (zera, não decrementa) — seguro.
- **Janela 24h derivada vs persistida**: se backend ainda não expõe `whatsapp_window_expires_at`, precisa adicionar — pode ser computed field ou nova coluna. Decisão durante implementação.
- **Cores warm-only**: amber/orange/red atuais em alguns lugares precisam migrar para tokens warm — risco baixo, mas pede inspeção visual.

## Próximo passo

Invocar skill `writing-plans` para destrinchar este spec em plano de implementação acionável (steps, dependencies, dispatch de subagents, verificação).
