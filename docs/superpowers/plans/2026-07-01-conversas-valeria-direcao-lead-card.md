# Conversas — Direção (Inbound/Outbound) + Estado em todo card da Valéria — Implementation Plan

> **For agentic workers:** Implemente task-a-task em TDD (RED → GREEN → refactor). Steps usam checkbox (`- [ ]`) para tracking.
> **IMPORTANT:** Qualquer agente tocando arquivos de frontend com JSX/visual DEVE invocar a skill `frontend-design` antes de alterar (aplica-se à Task 4 — badge).
> **Spec:** `docs/superpowers/specs/2026-07-01-conversas-valeria-direcao-lead-card-design.md` (D1, D2, D3 aprovados).
> **Verificação de segurança (2026-07-01):** worktrees `feats2`/`master`/`feats3` só têm `CLAUDE.md` modificado; os arquivos-alvo estão limpos em todos; sem index.lock, sem op git em progresso, sem swap files. Livre para implementar.

> **⚠️ CORREÇÃO (2026-07-01, pós-implementação):** o estado `Humano` para handoff foi
> **removido** — era regra de negócio errada. Handoff (`ai_enabled === false`) apenas desliga
> a IA; o card **continua sendo da Valéria** e mantém Inbound/Outbound (com fallback pela última
> mensagem). Canal humano (`mode === "human"`, ex.: João) → `getAgentPersona` retorna `null`
> (card do vendedor, não da Valéria). O `agent-persona-badge.tsx` **permanece 2-estados** (Task 4
> revertida). Onde este plano menciona "Humano"/estado `human` abaixo, considere substituído por
> esta regra.

**Goal:** Garantir que **todo** card da Valéria em `/conversas` exiba explicitamente (a) o lead atendido — já OK — e (b) a direção do atendimento, sem cards mudos. Tornar `getAgentPersona` resiliente (nunca-nulo para contexto Valéria): persona efetiva → pin → default do canal → direção da última mensagem → default `inbound`. Handoff mantém a persona da Valéria; canal humano retorna `null`.

**Architecture:** A correção é de **exibição/leitura**, sem migração de banco e sem backend Python. O núcleo é a função pura `getAgentPersona` (alvo ideal de TDD, já tem suíte vitest). O badge é renderizado incondicionalmente em `chat-list.tsx:286` — portanto **`chat-list.tsx` não é alterado**; basta a função parar de retornar `null`. A direção-da-última-mensagem é derivada de campos (`role`/`sent_by`) que a API já busca via RPC `get_last_messages` mas hoje descarta.

**Tech Stack:** React 18, Next.js App Router, TypeScript, Tailwind, Vitest.

---

## File Map

| Ação | Arquivo | Nota |
|------|---------|------|
| Modify | `frontend/src/lib/types.ts` | novo campo opcional `last_message_direction` |
| Modify | `frontend/src/lib/agent-persona.ts` | direção resiliente + estado `human` (locked ✓) |
| Modify | `frontend/src/lib/agent-persona.test.ts` | ajustar 2 testes + 4 novos (TDD) |
| Modify | `frontend/src/components/conversas/agent-persona-badge.tsx` | renderizar estado `human` (5º arquivo — verificado limpo) |
| Modify | `frontend/src/app/api/conversations/route.ts` | expor `last_message_direction` (locked ✓) |
| — | `frontend/src/components/conversas/chat-list.tsx` | **sem alteração** (badge já é incondicional) |

---

### Task 1: Pré-voo (branch + baseline verde)

**Files:** nenhum alterado.

- [ ] **Step 1: Confirmar branch de trabalho**

```bash
git rev-parse --abbrev-ref HEAD
```
Expected: `fix/valeria-aba-conversas` (branch já existe — não criar nova).

- [ ] **Step 2: Baseline — suíte atual passa antes de mexer**

```bash
cd frontend && npx vitest run src/lib/agent-persona.test.ts
```
Expected: 5 testes passam (verde). É o baseline que vamos evoluir.

---

### Task 2: Tipagem — expor `last_message_direction` no tipo `Conversation`

Pré-requisito para os fixtures de teste e a API compilarem sob TS estrito.

**Files:** Modify `frontend/src/lib/types.ts`

- [ ] **Step 1: Adicionar campo opcional em `interface Conversation`**

Após a linha `agent_persona?: string | null;` (fim da interface `Conversation`, ~linha 320), inserir:

```ts
  // Direção derivada da ÚLTIMA mensagem (RPC get_last_messages): "inbound" = lead falou
  // por último; "outbound" = IA/vendedor/disparo. Fallback de direção quando a persona
  // não resolve. NULL quando não há mensagens ou provider sem info de role (Evolution).
  last_message_direction?: "inbound" | "outbound" | null;
```

- [ ] **Step 2: TypeScript sem erros**

```bash
cd frontend && npx tsc --noEmit
```
Expected: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/types.ts
git commit -m "types(conversas): add last_message_direction field to Conversation"
```

---

### Task 3: `getAgentPersona` resiliente — TDD (RED → GREEN)

Núcleo da correção. Função pura. Escrever/ajustar testes primeiro, ver RED, implementar, ver GREEN.

**Files:** Modify `frontend/src/lib/agent-persona.test.ts`, depois `frontend/src/lib/agent-persona.ts`

- [ ] **Step 1 (RED): Ajustar os 2 testes existentes de `null` para o estado `human`**

No `agent-persona.test.ts`, substituir o teste `"null when ai_enabled === false"` por:

```ts
  it("ai_enabled === false → estado humano (não some)", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: aiChannel,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: false } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("human");
    expect(result!.label).toBe("Humano");
  });
```

E substituir `"null when channels.mode === 'human'"` por:

```ts
  it("canal em modo humano → estado humano (não some)", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: { ...aiChannel, mode: "human" },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("human");
    expect(result!.label).toBe("Humano");
  });
```

- [ ] **Step 2 (RED): Adicionar 4 novos testes de cobertura**

Acrescentar dentro do `describe`:

```ts
  it("fallback: sem persona/pin/canal, usa last_message_direction outbound", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel, // sem agent_profiles default
        last_message_direction: "outbound",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result!.direction).toBe("outbound");
    expect(result!.label).toBe("Valéria (Outbound)");
  });

  it("fallback: last_message_direction inbound", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel,
        last_message_direction: "inbound",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result!.direction).toBe("inbound");
  });

  it("default inbound quando não há nenhuma fonte (nunca card mudo)", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: null,
        agent_profiles: null,
        channels: aiChannel,
        last_message_direction: null,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result).not.toBeNull();
    expect(result!.direction).toBe("inbound");
  });

  it("persona tem prioridade sobre last_message_direction", () => {
    const result = getAgentPersona(
      makeConv({
        agent_persona: "valeria_outbound",
        channels: aiChannel,
        last_message_direction: "inbound", // deve ser ignorado
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        leads: { ai_enabled: true } as any,
      }),
    );
    expect(result!.direction).toBe("outbound");
  });
```

- [ ] **Step 3 (RED): Rodar e confirmar falha**

```bash
cd frontend && npx vitest run src/lib/agent-persona.test.ts
```
Expected: **FALHA** nos testes novos/ajustados (função ainda retorna null). Isto confirma o RED.

- [ ] **Step 4 (GREEN): Reescrever `agent-persona.ts`**

Substituir todo o corpo de `frontend/src/lib/agent-persona.ts` por:

```ts
import type { Conversation } from "@/lib/types";

/**
 * Direção Inbound/Outbound da Valéria no card — resiliente, nunca-nula em contexto Valéria.
 *
 * Cascata de fontes (D2): persona efetiva (`agent_persona`, denormalizada por turno pelo
 * backend) → pin da conversa (`agent_profiles.prompt_key`) → default do canal
 * (`channels.agent_profiles.prompt_key`) → direção da última mensagem
 * (`last_message_direction`) → default `inbound`. Isso elimina o card mudo em conversas
 * outbound recém-disparadas (persona ainda NULL, sem pin/canal).
 *
 * Handoff/canal humano (D1): não some — retorna estado neutro `human` ("Humano"),
 * comunicando explicitamente que a Valéria não é a responsável no momento.
 */
type PersonaState = {
  label: string;
  direction: "inbound" | "outbound" | "human";
  color: string;
};

const HUMAN_COLOR = "#7b7b78";

export function getAgentPersona(conv: Conversation): PersonaState | null {
  const isHumanChannel = conv.channels?.mode === "human";
  const aiDisabled = (conv.leads?.ai_enabled ?? true) === false;
  if (isHumanChannel || aiDisabled) {
    return { label: "Humano", direction: "human", color: HUMAN_COLOR };
  }

  const promptKey =
    conv.agent_persona ??
    conv.agent_profiles?.prompt_key ??
    conv.channels?.agent_profiles?.prompt_key;

  const name =
    conv.agent_profiles?.name ?? conv.channels?.agent_profiles?.name ?? "Valéria";

  let direction: "inbound" | "outbound";
  if (promptKey) {
    direction = promptKey.endsWith("outbound") ? "outbound" : "inbound";
  } else if (conv.last_message_direction) {
    direction = conv.last_message_direction;
  } else {
    direction = "inbound"; // default documentado — garante que nenhum card fique mudo
  }

  return direction === "outbound"
    ? { label: `${name} (Outbound)`, direction, color: "#b45309" }
    : { label: `${name} (Inbound)`, direction, color: "#5b8aad" };
}
```

- [ ] **Step 5 (GREEN): Rodar e confirmar verde**

```bash
cd frontend && npx vitest run src/lib/agent-persona.test.ts && npx tsc --noEmit
```
Expected: **todos** os testes passam; sem erros de tipo.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/agent-persona.ts frontend/src/lib/agent-persona.test.ts
git commit -m "fix(conversas): getAgentPersona nunca-nulo p/ Valeria + estado humano (D1/D2)"
```

---

### Task 4: Badge renderiza o estado `Humano`

**Files:** Modify `frontend/src/components/conversas/agent-persona-badge.tsx`

> **REQUIRED:** invocar `frontend-design` skill antes (mudança visual).

- [ ] **Step 1: Tratar `direction === "human"` no título e no ícone**

Substituir o bloco do `title` e o `<svg>` para cobrir os 3 estados. Novo `title`:

```tsx
      title={
        persona.direction === "human"
          ? "Atendimento humano (IA desativada / canal humano)"
          : persona.direction === "outbound"
            ? "Atendimento ativo (outbound)"
            : "Atendimento receptivo (inbound)"
      }
```

E o path do ícone:

```tsx
        {persona.direction === "human" ? (
          // ícone de pessoa (neutro)
          <path d="M12 12a4 4 0 100-8 4 4 0 000 8zm-7 8a7 7 0 0114 0" />
        ) : persona.direction === "outbound" ? (
          <path d="M12 19V5M5 12l7-7 7 7" />
        ) : (
          <path d="M12 5v14M19 12l-7 7-7-7" />
        )}
```

- [ ] **Step 2: TypeScript sem erros**

```bash
cd frontend && npx tsc --noEmit
```
Expected: sem erros (o novo tipo `direction: "inbound" | "outbound" | "human"` propaga).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/agent-persona-badge.tsx
git commit -m "feat(conversas): badge exibe estado Humano no handoff"
```

---

### Task 5: API — derivar e expor `last_message_direction`

**Files:** Modify `frontend/src/app/api/conversations/route.ts`

- [ ] **Step 1: Construir o mapa de direção junto ao `lastMsgMap`**

No bloco que itera `lastMsgs` (~linha 178-190), adicionar o mapa e populá-lo:

```ts
  const lastMsgMap = new Map<string, string>();
  const lastDirMap = new Map<string, "inbound" | "outbound">();
  if (metaConvIds.length > 0) {
    const { data: lastMsgs } = await supabase.rpc("get_last_messages", {
      conv_ids: metaConvIds,
    });
    for (const row of lastMsgs || []) {
      let prefix = "";
      if (row.sent_by === "seller") prefix = "Vendedor: ";
      else if (["broadcast", "campaign", "automation", "followup", "cadence"].includes(row.sent_by)) prefix = "Disparo: ";
      else if (row.role === "assistant") prefix = "IA: ";
      lastMsgMap.set(row.conversation_id, prefix + row.content);
      // role "user" = lead falou por último → inbound; caso contrário nós falamos → outbound
      lastDirMap.set(row.conversation_id, row.role === "user" ? "inbound" : "outbound");
    }
  }
```

- [ ] **Step 2: Anexar `last_message_direction` em `dbWithLastMsg`**

No `.map` de `dbWithLastMsg` (~linha 256-266), acrescentar a chave no objeto retornado:

```ts
      last_message_text: lastMsgMap.get(c.id as string) ?? null,
      last_message_direction: lastDirMap.get(c.id as string) ?? null,
```

- [ ] **Step 3: Evolution — setar `last_message_direction: null` explicitamente**

No objeto retornado por `fetchEvolutionConversations` (junto de `last_message_text`), adicionar:

```ts
      last_message_direction: null, // Evolution não tem info de role (fora de escopo — CLAUDE.md §6)
```

- [ ] **Step 4: TypeScript sem erros**

```bash
cd frontend && npx tsc --noEmit
```
Expected: sem erros.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/api/conversations/route.ts
git commit -m "feat(conversas): API expoe last_message_direction (fallback de direcao)"
```

---

### Task 6: Verificação end-to-end (skill `verify`)

**Files:** nenhum alterado.

- [ ] **Step 1: Suíte completa + type-check**

```bash
cd frontend && npx vitest run && npx tsc --noEmit
```
Expected: tudo verde.

- [ ] **Step 2: Rodar app e inspecionar `/conversas`**

Usar a task `Run All Dev (CRM & Backend)`. Abrir `/conversas` e confirmar:
- **100% dos cards da Valéria exibem selo de direção** — nenhum card mudo.
- Conversa outbound recém-disparada (persona ainda NULL) mostra `Valéria (Outbound)` via fallback.
- Conversa em handoff (`ai_enabled=false`) mostra `Humano` (não some).
- Canal humano mostra `Humano`.
- Conversa inbound normal mostra `Valéria (Inbound)`.
- O nome/telefone do lead continua correto em cada card.

- [ ] **Step 3: (opcional) Registrar evidência**

Screenshot da lista antes/depois anexado ao PR interno / nota do plano.

---

## Fora de escopo

- Cards do provider Evolution (obsoleto — CLAUDE.md §6): `last_message_direction` fica `null`; comportamento de persona mantido.
- Backend Python / denormalização de `agent_persona` na origem.
- Redesenho de identidade do lead / desambiguação multi-canal (D3: já suficiente).
- `chat-list.tsx`: sem alteração (badge já incondicional).

## Sequência de deploy (após aprovação da implementação)

Seguir CLAUDE.md §1: `git pull origin master` → `git push origin fix/valeria-aba-conversas:master` **mediante autorização explícita** do usuário. Não subir sem OK.
