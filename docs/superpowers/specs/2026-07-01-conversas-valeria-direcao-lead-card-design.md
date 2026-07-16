# Spec: Direção (Inbound/Outbound) + Identidade do Lead em todo card da Valéria — /conversas

**Data:** 2026-07-01
**Status:** Rascunho — aguardando aprovação
**Branch:** `fix/valeria-aba-conversas`
**Escopo primário:** `frontend/src/lib/agent-persona.ts`, `frontend/src/components/conversas/chat-list.tsx`, `frontend/src/lib/types.ts`, `frontend/src/app/api/conversations/route.ts`

---

## Problema

Na lista de conversas (`/conversas`), os cards de atendimento da Valéria apresentam
inconsistência: **alguns cards não exibem a direção do atendimento (inbound / outbound)**.
O objetivo é que **todo** card da Valéria deixe explícito, de forma confiável:

1. Qual lead está sendo atendido naquela interação (nome/telefone).
2. A direção do atendimento — `inbound` (receptivo) ou `outbound` (ativo).

---

## Investigação (o que existe hoje)

**Card = uma conversa** (`conversations`, 1 por lead+canal Meta). Renderizado em
`chat-list.tsx → renderConversationRow`.

- **Identidade do lead:** já renderizada — `displayName = lead?.name || lead?.phone || "Desconhecido"` (`chat-list.tsx:202`). Avatar usa a inicial.
- **Direção:** renderizada pelo `<AgentPersonaBadge>` (`chat-list.tsx:286`), que chama `getAgentPersona(conv)` em `lib/agent-persona.ts`. Mostra seta ↑ "Valéria (Outbound)" ou ↓ "Valéria (Inbound)".

### Por que a direção some em alguns cards

`getAgentPersona()` retorna `null` (badge desaparece) em três situações
(`agent-persona.ts:19-28`):

1. `channels.mode === "human"` → canal humano.
2. `leads.ai_enabled === false` → conversa em handoff para humano (causa nº1 do "Valéria muda", conforme diagnóstico registrado).
3. `promptKey` não resolvido — `agent_persona` é `NULL` (IA ainda não respondeu) **E** conversa sem `agent_profile_id` fixado **E** canal sem `agent_profiles` default.

A direção vem de 3 fontes em cascata:
`conv.agent_persona` → `conv.agent_profiles.prompt_key` (pin) → `conv.channels.agent_profiles.prompt_key` (default do canal).
Quando as três estão vazias, o card renderiza **nada** — este é o buraco silencioso,
especialmente em conversas outbound recém-criadas por disparo antes da 1ª resposta da IA.

### Dados disponíveis na API (`api/conversations/route.ts`)

- O `select("*")` já traz a coluna `agent_persona` da conversa.
- O join traz `agent_profiles(id, name, prompt_key)` (pin) e `channels(... agent_profiles(...))` (default).
- A RPC `get_last_messages` (linha 180) já retorna, por conversa, `sent_by`, `role` e `content` — usados hoje só para montar o prefixo do preview ("IA:", "Vendedor:", "Disparo:"). **Esses campos de direção são descartados** — não chegam ao card.
- Provider: apenas `meta_cloud` passa pela RPC. Evolution API está obsoleto (CLAUDE.md §6) e fica fora de escopo.

---

## Decisões de design (recomendação — confirmar na aprovação)

Fiz perguntas de brainstorming mas você estava ausente; abaixo minhas recomendações,
explicitadas para você ajustar antes de eu escrever o plano.

### D1 — Cobertura: **todo card da Valéria sempre mostra a direção (Inbound/Outbound)**

> **CORREÇÃO (pós-implementação, 2026-07-01):** a ideia inicial de um selo `Humano` para
> handoff estava **conceitualmente errada** e foi removida. Regra de negócio correta:

- IA responsável → `Valéria (Inbound)` ou `Valéria (Outbound)`.
- **Handoff (`ai_enabled === false`)**: a IA apenas **desliga**. O card **continua sendo da
  Valéria** e **mantém** a persona (Inbound/Outbound, com fallback pela última mensagem). Não
  vira "Humano" — o atendimento humano acontece em **outro número/canal**, gerando um **card
  separado**.
- **Canal humano (`channels.mode === "human"`, ex.: número do João)**: esse card é do
  vendedor, não da Valéria → `getAgentPersona` retorna `null` (sem badge de persona). Mantém
  o comportamento original.

Resultado: nenhum card **da Valéria** fica mudo; cards de vendedor humano permanecem sem badge de persona (fora do escopo).

### D2 — Fonte da direção: **híbrida (persona + fallback pela última mensagem)**
- Usar `prompt_key` (persona efetiva → pin → default) quando existir. Semântica atual preservada.
- Quando a persona não resolver (caso 3), **cair para a direção derivada da última mensagem** via `sent_by`/`role` da RPC:
  - `role === "user"` → `inbound` (lead falou por último).
  - `sent_by ∈ {seller, broadcast, campaign, automation, followup, cadence}` ou `role === "assistant"` → `outbound`.
- Assim a cobertura vai a 100% dos cards `meta_cloud` sem perder a semântica de persona quando ela está disponível.

_Nota semântica:_ persona-direction ("Valéria rodou o playbook ativo vs. receptivo") e last-message-direction ("quem falou por último") não são idênticas. O fallback só age quando não há persona, então a fonte primária continua sendo a persona.

### D3 — Identidade do lead: **já suficiente; melhoria mínima**
O nome/telefone já aparece. Não vou reescrever a identidade. Duas melhorias pequenas e opcionais:
- Trocar `"Desconhecido"` por telefone formatado quando `name` for nulo (já cai em `phone`; o "Desconhecido" só ocorre sem lead — ex. aba "pessoal").
- (Opcional) Reforçar desambiguação do mesmo lead em múltiplos canais reutilizando o badge de canal já existente. **Recomendo deixar fora do escopo** deste fix — já tratado pelo `channelBadge` e pelo indicador de conversas-irmãs.

---

## Solução proposta

### 1. `lib/agent-persona.ts` — tornar a direção resiliente e nunca-nula para a Valéria

Refatorar `getAgentPersona` para uma função que **sempre** classifica o card, retornando também um estado `human`:

```ts
type PersonaState = {
  label: string;
  direction: "inbound" | "outbound" | "human";
  color: string;
};

export function getAgentPersona(conv: Conversation): PersonaState | null
```

Regras:
1. Canal humano OU `ai_enabled === false` → `{ direction: "human", label: "Humano", color: <neutro> }` (D1).
2. IA responsável:
   a. Resolve `promptKey` na cascata atual → direção por `endsWith("outbound")`.
   b. Se `promptKey` ausente → usar `conv.last_message_direction` (novo campo, item 3) como fallback (D2).
   c. Se ainda indeterminado (sem persona e sem última mensagem — conversa vazia recém-criada) → default `inbound` documentado, OU esconder só nesse caso extremo. **Recomendo default `inbound`** para não reintroduzir card mudo.

Mantém `null` apenas se `conv` não for de contexto Valéria de forma alguma (defensivo).

### 2. `components/conversas/chat-list.tsx` — badge sempre visível + estado humano

- `AgentPersonaBadge` passa a renderizar também o estado `human` (ícone/label neutros).
- Nenhuma mudança na posição; o badge continua na L3 (meta row).

### 3. `app/api/conversations/route.ts` — expor a direção da última mensagem

No loop que consome `get_last_messages` (linha 183), além do prefixo, computar e anexar por conversa:

```ts
const direction =
  row.role === "user" ? "inbound" : "outbound";
lastDirMap.set(row.conversation_id, direction);
```

E no `dbWithLastMsg` (linha 256) adicionar `last_message_direction: lastDirMap.get(c.id) ?? null`.
Evolution (`fetchEvolutionConversations`) seta `last_message_direction: null` (sem info de role — fora de escopo).

### 4. `lib/types.ts` — tipar o novo campo

Em `interface Conversation`, adicionar:
```ts
last_message_direction?: "inbound" | "outbound" | null;
```

---

## Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `frontend/src/lib/agent-persona.ts` | Direção resiliente + estado `human` + fallback por última msg |
| `frontend/src/components/conversas/chat-list.tsx` | Badge renderiza estado `human`; sempre visível p/ Valéria |
| `frontend/src/app/api/conversations/route.ts` | Deriva e expõe `last_message_direction` a partir da RPC |
| `frontend/src/lib/types.ts` | Novo campo opcional `last_message_direction` |

Sem migração de banco. Sem mudança em backend Python. `constants.ts` intacto.

---

## Plano de testes (TDD — a detalhar no writing-plans após aprovação)

Testes unitários de `getAgentPersona` (função pura, alvo ideal de TDD):

1. Persona efetiva `valeria_outbound` → `outbound`.
2. Persona efetiva `valeria_inbound` → `inbound`.
3. `agent_persona` nulo + pin outbound → `outbound` (fallback pin).
4. `agent_persona` nulo + sem pin + canal default inbound → `inbound` (fallback canal).
5. **Novo:** sem persona/pin/canal + `last_message_direction: "outbound"` → `outbound` (fallback última msg).
6. **Novo:** sem nenhuma fonte + última msg nula → default `inbound` (nunca nulo).
7. `channels.mode === "human"` → estado `human`.
8. `leads.ai_enabled === false` → estado `human`.

Teste de mapeamento na API (`route.ts`): `role === "user"` → `inbound`; `sent_by === "broadcast"` → `outbound`.

Validação manual: rodar `Run All Dev (CRM & Backend)`, abrir `/conversas`, confirmar
que 100% dos cards da Valéria exibem selo, incluindo conversa outbound recém-disparada
(pré-1ª-resposta) e conversa em handoff.

---

## Fora de escopo

- Cards do provider Evolution (obsoleto — CLAUDE.md §6): mantêm comportamento atual.
- Backend Python / denormalização de `agent_persona` (a correção é de exibição, não de dado de origem).
- Redesenho da identidade do lead / desambiguação multi-canal (já coberto por `channelBadge` + conversas-irmãs).
- Persistência de filtros, mudanças em tabs.

---

## Riscos / notas

- **Semântica persona vs. última-mensagem** (D2): documentado que o fallback é secundário; se você preferir direção 100% baseada em persona (aceitando cards mudos onde não há persona), reduz-se ao item 1–2 sem tocar na API. Confirmar na aprovação.
- ~~**Estado `human`** (D1)~~: **removido** — ver correção em D1. Handoff mantém a persona da Valéria; canal humano retorna `null`. O `agent-persona-badge.tsx` **não foi alterado** (permanece 2-estados).
- Mudança é puramente de leitura/exibição — baixo risco de regressão; sem efeitos em envio de mensagens.
