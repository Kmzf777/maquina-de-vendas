# Popup de SLA (40 min) para vendedores — Design

**Data:** 23/09/2026 · **Status:** aprovado pelo usuário

## Objetivo

Quando um lead do vendedor passa de **40 minutos de atendimento sem resposta**, o CRM
mostra um popup que força a resposta e lembra o vendedor de atender dentro do seu
horário de atendimento (padrão 10h às 16h).

## Regras

1. **Quem vê:** só usuários com role `vendedor`, e só os leads dos canais configurados para
   ele em `sla_seller_config`. Admin não recebe popup.
2. **Quando o lead entra:** o cliente foi o último a falar e a espera está acima de
   **40 minutos de atendimento**, contados na janela do vendedor (`window_start_minute`,
   `window_end_minute`, `active_weekdays`, `sla_overrides`). A regra de rodada aberta é a
   mesma do "Em atraso agora" do dashboard (`collectOpenRounds` em `lib/sla-rounds.ts`).
   O único valor diferente é o limite: **40 fixo** (constante `SLA_REMINDER_MINUTES`),
   separado da meta configurável de 20 min.
3. **Um popup por lead, em fila:** aparece um de cada vez, primeiro o que espera há mais tempo.
4. **Conteúdo:** título "Lead sem resposta há {duração}", nome e telefone do lead, a última
   mensagem do cliente (quando existir) e o lembrete
   *"Lembre-se: seu horário de atendimento é das {início} às {fim}. Responda os leads dentro
   desse horário."* O horário vem da janela do vendedor, não é texto fixo.
5. **Botões:**
   - **Responder agora:** vai para `/conversas?lead_id=…`.
   - **Depois:** fecha o popup desse lead e mostra o próximo da fila.
6. **Insistência:** os "Depois" valem só para a página atual. **A cada troca de rota
   (pathname), a fila reabre inteira.** O lead só sai de vez quando é respondido: a mensagem
   de seller/agent fecha a rodada, e o mesmo vale para `last_seller_response_at` ("Finalizar").
7. **Lead que estoura com a página aberta:** entra na fila na hora, sem esperar trocar de rota.
8. **Exceção da conversa aberta:** nenhum popup aparece para o lead cuja conversa está aberta
   em `/conversas`, nem para o `lead_id` pendente no deep-link (evita o flash entre clicar em
   "Responder agora" e a conversa abrir).
9. Fechar pelo ESC ou pelo overlay equivale a "Depois".

## Arquitetura

| Unidade | Arquivo | Responsabilidade |
|---|---|---|
| Lógica pura | `frontend/src/lib/sla-reminder.ts` | `SLA_REMINDER_MINUTES`, `buildReminderQueue`, `formatWindowHour` |
| Hook existente | `frontend/src/hooks/use-overdue-leads.ts` | aceitar `{ targetMinutes }` opcional; expor a janela do vendedor em cada `OverdueLead` |
| Store da conversa aberta | `frontend/src/lib/active-conversation.ts` | store mínimo (`setActiveConversation`, `useActiveConversation`) via `useSyncExternalStore` |
| Página de conversas | `frontend/src/app/(authenticated)/conversas/page.tsx` | publicar o lead/conversa selecionados no store e limpar ao desmontar |
| Componente | `frontend/src/components/sla-reminder-popup.tsx` | fila por página, reset no pathname, Dialog, busca preguiçosa da última mensagem |
| Shell | `frontend/src/components/authenticated-shell.tsx` | montar `<SlaReminderPopup />` ao lado do `<NotificationToast />` |

**Fluxo:** o `useOverdueLeads({ targetMinutes: 40 })` já faz realtime em `conversations` e
recomputa a cada 60s. O popup deriva a fila com
`buildReminderQueue(leads, dismissedNestaPagina, conversaAberta)`. `dismissed` zera quando
o `pathname` muda. O primeiro item da fila vira o Dialog aberto.

**Custo:** o hook roda uma vez no shell (o layout persiste entre rotas no App Router). Só
monta para vendedor. A última mensagem é 1 query `limit(1)` por popup exibido.

**Sem migration, sem backend, sem mudança no GitHub Actions.**

## Erros

- Falha de fetch no hook: a lista fica vazia e nenhum popup aparece (falha silenciosa, mesmo
  comportamento do dashboard).
- Falha ao buscar a última mensagem: o popup abre sem o trecho.
- Vendedor sem `sla_seller_config`: nenhum popup.

## Testes

- Vitest em `lib/sla-reminder.test.ts`: ordenação, exclusão por dismissed, exclusão por
  conversa aberta e por lead pendente, formatação de hora (600 → "10h", 630 → "10h30").
- Vitest em `lib/active-conversation.test.ts`: set/get/subscribe.
- O repo não tem jsdom/@testing-library (ver memória), então o componente é validado por
  `tsc --noEmit`, lint e verificação manual no navegador.

## Fora de escopo

Popup para admin, limite configurável em tela, push/Notification fora da aba, som.
