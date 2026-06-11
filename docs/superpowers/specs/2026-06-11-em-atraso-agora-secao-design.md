# Seção "Em atraso agora" acionável — Design

**Data:** 2026-06-11
**Status:** Aprovado

## Problema

Hoje "Em atraso agora" é uma **coluna** da tabela de SLA por vendedor, e tem dois defeitos:

1. **Bug de correção:** a contagem é alimentada pela mesma query filtrada por período
   (`use-sla-stats.ts` → `fetchConversations` → `created_at >= cutoff`). Um lead que
   chegou há 9 dias e nunca foi respondido **some** da contagem quando o filtro está em
   "Hoje"/"7 dias" — só reaparece em "30 dias"/"Tudo". Os atrasos mais antigos e graves
   (os que o gestor mais precisa ver) são os que desaparecem. O número subnotifica e
   muda conforme um filtro que conceitualmente não deveria afetá-lo.

2. **Não é acionável:** é só um número. O gestor/vendedor vê "3" mas não sabe *quais*
   leads, há quanto tempo, nem consegue agir direto.

## Solução

Remover a coluna da tabela e criar uma **seção dedicada e acionável** "Em atraso agora",
que lista cada lead atrasado com o tempo de espera e um botão para abrir a conversa.
Escopo por papel do usuário.

## Decisões de produto

- A **coluna "Em atraso agora" sai da tabela** de SLA. A tabela fica só com métricas de
  período: Vendedor · Média resp. · Pior SLA · Total. O filtro de período passa a
  governar apenas métricas de período (coerente).
- A nova seção fica **acima da tabela** de SLA, no dashboard.
- A seção **não é filtrada por período** — é sempre o agora (corrige o bug).
- **Escopo por role:**
  - **admin:** vê os atrasos de todos os vendedores + um filtro por vendedor.
  - **vendedor:** vê apenas os leads em atraso do **seu** canal (sem filtro).
- Cada linha mostra: nome do lead (telefone como fallback), vendedor (quando admin),
  tempo de atraso, e botão **"Abrir conversa"**.
- "Abrir conversa" usa o deep-link existente: `/conversas?lead_id=<leadId>`
  (a página `/conversas` já pré-seleciona a conversa pelo `lead_id` na URL).
- Ordenação: mais atrasado no topo.
- "Em atraso" = rodada de espera **aberta** com tempo comercial decorrido **> alvo
  global** (`sla_settings.target_minutes`, default 20), respeitando janela e anulações
  do vendedor — mesma definição já usada hoje.

> **Segurança:** o app é um CRM compartilhado — qualquer usuário autenticado já lê
> conversas/leads via client (padrão atual: `use-realtime-leads`, `use-sla-stats`). O
> escopo por canal do vendedor nesta seção é de **UX**, coerente com o modelo de acesso
> existente, não uma nova barreira de RLS.

## Sem novas tabelas

Reusa `sla_seller_config`, `sla_overrides`, `sla_settings`, e
`conversations` + `leads` + `messages`. Nenhuma migration nova.

## Motor — refatoração DRY em `sla-rounds.ts`

Hoje `collectRounds` faz o passe cronológico e descarta a identidade das rodadas
abertas (só guarda `openElapsed: number[]`). Extrair o miolo do passe para uma função
interna compartilhada:

```ts
// interna (não exportada): um passe por conversa
function walkConversation(
  conv: SlaConversation,
  win: BusinessWindow,
  now: Date
): { closed: number[]; openElapsedMinutes: number | null }
```

Regras (inalteradas): rodada começa na primeira msg do cliente sem resposta; fecha na
primeira resposta do vendedor (msg `seller` ou `last_seller_response_at` via Finalizar);
rajadas do cliente não reiniciam; msg proativa do vendedor é ignorada.

A partir dela:
- `collectRounds(conversations, win, now)` — agrega `closed`/`openElapsed` como hoje.
  **Comportamento idêntico**; os testes atuais continuam passando.
- **Nova** `collectOpenRounds(conversations, win, now): OpenRound[]` onde
  `OpenRound = { conversationId: string; elapsedMinutes: number }` — emite só as rodadas
  abertas, preservando o `conversationId`. O hook junta com lead/canal.

## Hook `useOverdueLeads()`

`frontend/src/hooks/use-overdue-leads.ts`:

1. Usuário logado: `supabase.auth.getUser()` → `id` + `app_metadata.role`.
2. Lê `sla_seller_config` (active=true), `sla_overrides`, `sla_settings` (alvo).
3. Escopo de canais:
   - admin → todos os `channel_id` das configs ativas.
   - vendedor → o `channel_id` da config onde `user_id == id` (vazio se não houver).
4. Busca conversas **sem cutoff** dos canais no escopo, com lead:
   `.select("id, channel_id, lead_id, last_seller_response_at, leads(name, phone)")`
   (paginação como em `use-sla-stats`). Busca mensagens `user`/`seller` dessas conversas.
5. Para cada vendedor, monta a `BusinessWindow` (janela + anulações, igual `use-sla-stats`)
   e roda `collectOpenRounds`. Filtra `elapsedMinutes > target`.
6. Enriquece cada item: `{ conversationId, leadId, leadName, leadPhone, channelId,
   vendedorName, elapsedMinutes }` (mapeando conversa→lead e canal→vendedor).
7. Retorna `{ leads: OverdueLead[], vendedores: {userId, name}[], isAdmin, loading }`,
   `leads` ordenado por `elapsedMinutes` desc. Realtime (`conversations`, `messages`) +
   ticker de 60s.

Tipo exportado:
```ts
export interface OverdueLead {
  conversationId: string;
  leadId: string;
  leadName: string;   // nome ou, na falta, telefone
  leadPhone: string;
  channelId: string;
  userId: string;     // user_id do vendedor (filtro robusto do admin)
  vendedorName: string;
  elapsedMinutes: number;
}
```

## Componente `OverdueLeadsSection`

`frontend/src/components/dashboard/overdue-leads-section.tsx`, renderizado acima de
`<SlaTable />` no dashboard:

- Cabeçalho "Em atraso agora" + contagem total (vermelho quando > 0).
- **admin:** dropdown de filtro por vendedor ("Todos" + cada vendedor). **vendedor:**
  sem dropdown.
- Lista de linhas: nome do lead · vendedor (quando admin) · tempo de atraso
  (`formatBusinessDuration(elapsedMinutes)`) · botão "Abrir conversa" (link Next para
  `/conversas?lead_id=<leadId>`).
- Mais atrasado no topo. Estado vazio: "Nenhum lead em atraso agora." Skeleton no loading.
- Segue os padrões visuais do dashboard (cartões `bg-white border-[#dedbd6] rounded-[8px]`,
  vermelho `#c41c1c` para urgência).

## Ajuste na `SlaTable`

`frontend/src/components/dashboard/sla-table.tsx`: remover a coluna "Em atraso agora"
(cabeçalho, células das linhas e do total). A tabela passa a ter 3 colunas. O hook
`use-sla-stats.ts` permanece (ainda calcula `overdueCount` em `summarizeRounds`, mas
não é mais exibido — sem mudança funcional).

## Dashboard

`frontend/src/app/(authenticated)/dashboard/page.tsx`: adicionar
`<OverdueLeadsSection />` imediatamente antes de `<SlaTable />`.

## Testes

- **`sla-rounds`**: testes atuais de `collectRounds` continuam verdes (paridade do
  `walkConversation`). Novos testes de `collectOpenRounds`:
  - rodada aberta acima/abaixo do tempo → retorna `{conversationId, elapsedMinutes}`;
  - rodada fechada (resposta do vendedor) → não entra;
  - rodada fechada via Finalizar (`last_seller_response_at`) → não entra;
  - dois leads abertos → dois itens com os conversationIds certos.
- Hook e componente: sem teste unitário (I/O + tempo + role); validação por `tsc` e
  teste manual no dashboard.

## Casos de borda

- Vendedor sem config de SLA → seção vazia (sem erro).
- Lead sem nome → exibe telefone.
- Conversa sem `lead_id`/lead → ignorada na lista (não dá pra abrir conversa sem lead).
- Dia anulado / fora da janela → não acumula atraso (janela já trata).
- "obrigado!" após resolvido → pode aparecer como atraso (limitação conhecida; mitigação
  é o botão Finalizar, igual ao resto do SLA).
