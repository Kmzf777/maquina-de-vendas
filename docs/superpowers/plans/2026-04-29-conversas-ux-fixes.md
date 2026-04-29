# Conversas UX Fixes (Fase B-1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkbox syntax.
>
> **PROJECT-SPECIFIC RULE:** Every frontend task MUST invoke the `frontend-design` skill BEFORE writing JSX/CSS/Tailwind.

**Goal:** Corrigir 3 falhas pós-Fase B em `/conversas`: indicador compact invisível, CTA de disparo sumiu no chat expired, badge unread não zera.

**Spec:** `docs/superpowers/specs/2026-04-29-conversas-ux-fixes-design.md`
**Branch:** `feat/conversas-ux-fixes` (já criada e sincronizada com origin/master)

---

## Task 1: Modificar `WhatsappWindowIndicator` — F1 + F2

**Files:**
- Modify: `frontend/src/components/conversas/whatsapp-window-indicator.tsx`

- [ ] **Step 1: Invoke `frontend-design` skill** (mandatory)

- [ ] **Step 2: Atualizar a interface Props**

```tsx
interface Props {
  expiresAt: string | null;
  variant: 'compact' | 'header' | 'banner';
  className?: string;
  onReactivate?: () => void;
}
```

E na assinatura do componente: `export function WhatsappWindowIndicator({ expiresAt, variant, className, onReactivate }: Props) {`

- [ ] **Step 3: Reescrever o variant `compact` para sempre mostrar dot + texto**

Substituir o bloco atual do variant `compact`. **Ler o arquivo primeiro** para encontrar o bloco exato. O novo bloco:

```tsx
if (variant === "compact") {
  const compactDotClass: Record<State, string> = {
    active: "bg-[#5aad65]",
    warning: "bg-amber-500",
    critical: "bg-[#ff5600] animate-pulse",
    expired: "bg-[#7b7b78]",
    none: "bg-[#dedbd6]",
  };
  const compactLabel: Record<State, string> = {
    active: minutesLeft >= 60 ? `${Math.floor(minutesLeft / 60)}h` : `${minutesLeft}min`,
    warning: minutesLeft >= 60 ? `${Math.floor(minutesLeft / 60)}h` : `${minutesLeft}min`,
    critical: `${minutesLeft}min`,
    expired: "fechada",
    none: "",
  };
  const ariaLabel: Record<State, string> = {
    active: "Janela 24h ativa",
    warning: "Janela 24h expirando em breve",
    critical: "Janela 24h crítica",
    expired: "Janela 24h fechada",
    none: "Sem janela aberta",
  };
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-xs text-[#7b7b78]", className)}
      aria-label={ariaLabel[state]}
    >
      <span
        className={cn("inline-block h-2 w-2 rounded-full flex-shrink-0", compactDotClass[state])}
        aria-hidden
      />
      {compactLabel[state] && <span>{compactLabel[state]}</span>}
    </span>
  );
}
```

⚠️ Note que o dot foi para `h-2 w-2` (8px) — antes era `h-1.5 w-1.5` (6px). Mais visível.

⚠️ Re-mover o early-return antigo `if (state === "none" && variant !== "banner") return null;` — agora `compact` renderiza para `none` também. Manter a guarda só pro variant `header`.

A guarda nova fica:
```tsx
if (state === "none" && variant === "header") return null;
```

- [ ] **Step 4: Atualizar variant `banner` para receber `onReactivate`**

Localizar o bloco do banner (que retorna o `<div role="status">...`). Trocar por:

```tsx
// banner — usado quando expired
if (state !== "expired") return null;
return (
  <div
    className={cn(
      "flex items-center gap-2 border-b border-[#dedbd6] bg-[#faf9f6] px-4 py-2 text-sm text-[#111111]",
      className,
    )}
    role="status"
  >
    <span className={cn("inline-block h-2 w-2 rounded-full flex-shrink-0", dotClassFor(state))} aria-hidden />
    <span className="font-medium">Janela 24h expirada</span>
    <span className="text-[#7b7b78]">— só é possível enviar templates aprovados.</span>
    {onReactivate && (
      <button
        type="button"
        onClick={onReactivate}
        className="ml-auto text-xs bg-[#111111] text-white px-3 py-1 rounded-[4px] hover:opacity-90 transition-opacity flex-shrink-0"
      >
        Reativar conversa
      </button>
    )}
  </div>
);
```

(O `dotClassFor(state)` existente continua válido para o banner — não precisa criar nova função. Se o agent achar que está usando os mesmos tokens, OK. Senão, alinhar com `compactDotClass.expired`.)

- [ ] **Step 5: TypeScript check**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check 2>&1 | tail -10
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/conversas/whatsapp-window-indicator.tsx
git commit -m "feat(conversas): make compact indicator always visible + add onReactivate to banner"
```

---

## Task 2: Atualizar `chat-view.tsx` para passar `onReactivate`

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

- [ ] **Step 1: Invoke `frontend-design` skill**

- [ ] **Step 2: Adicionar `onReactivate` ao banner**

Localizar (o arquivo atualmente tem):
```tsx
<WhatsappWindowIndicator
  expiresAt={conversation.whatsapp_window_expires_at}
  variant="banner"
/>
```

Trocar para:
```tsx
<WhatsappWindowIndicator
  expiresAt={conversation.whatsapp_window_expires_at}
  variant="banner"
  onReactivate={() => setShowReactivatePanel(true)}
/>
```

A condicional `{showReactivatePanel && windowStatus === "closed" && <WindowReactivatePanel ... />}` continua igual — o painel só renderiza quando `showReactivatePanel = true` E a janela está fechada.

- [ ] **Step 3: TypeScript check + commit**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check 2>&1 | tail -5
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "fix(conversas): wire onReactivate from banner to open template panel"
```

---

## Task 3: Refatorar `chat-list.tsx` — remover shadow, aceitar `onMarkRead`

**Files:**
- Modify: `frontend/src/components/conversas/chat-list.tsx`

- [ ] **Step 1: Invoke `frontend-design` skill**

- [ ] **Step 2: Remover o shadow `useState`**

No `chat-list.tsx` (já existente):

Remover essas linhas:
```tsx
const [conversations, setConversations] = useState<Conversation[]>(initialConversations);

// Sync if parent passes new conversations (e.g. after polling refresh)
// We use a ref-less approach: only update if the incoming array reference changed
const [prevInitial, setPrevInitial] = useState(initialConversations);
if (prevInitial !== initialConversations) {
  setPrevInitial(initialConversations);
  setConversations(initialConversations);
}
```

Renomear o param do componente: `conversations: initialConversations` volta para `conversations`. A interface continua igual.

- [ ] **Step 3: Adicionar prop `onMarkRead`**

Atualizar `ChatListProps`:
```tsx
interface ChatListProps {
  conversations: Conversation[];
  channels: Channel[];
  activeTab: string;
  selectedConversationId: string | null;
  selectedChannelId: string;
  onSelectConversation: (conv: Conversation) => void;
  onMarkRead?: (conversationId: string) => void;
  onTabChange: (tab: string) => void;
  onChannelChange: (channelId: string) => void;
}
```

E receber no destructuring: `..., onMarkRead, ...`

- [ ] **Step 4: Simplificar `handleSelectConversation`**

Substituir o handler atual (que tem o `fetch` direto) por:

```tsx
const handleSelectConversation = (conv: Conversation) => {
  onSelectConversation(conv);
  if ((conv.unread_count ?? 0) > 0 && onMarkRead) {
    onMarkRead(conv.id);
  }
};
```

- [ ] **Step 5: TypeScript check** — ⚠️ vai falhar porque `page.tsx` ainda não passa `onMarkRead`. Esperado. Será corrigido na Task 4.

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check 2>&1 | tail -10
```

- [ ] **Step 6: Commit (mesmo com type erro temporário, pois Task 4 resolve)**

⚠️ **NÃO commitar ainda.** Aguardar Task 4 finalizar antes de commitar conjunto.

---

## Task 4: `page.tsx` — adicionar `handleMarkRead` e passar para ChatList

**Files:**
- Modify: `frontend/src/app/(authenticated)/conversas/page.tsx`

- [ ] **Step 1: Invoke `frontend-design` skill**

- [ ] **Step 2: Adicionar handler `handleMarkRead`**

Localizar onde `handleToggleAi` foi definido (Task 9 da Fase B). Logo abaixo dele, adicionar:

```tsx
const handleMarkRead = async (conversationId: string) => {
  try {
    const res = await fetch(`/api/conversations/${conversationId}/mark-read`, { method: "POST" });
    if (res.ok) {
      setConversations((prev) =>
        prev.map((c) => (c.id === conversationId ? { ...c, unread_count: 0 } : c)),
      );
    }
  } catch (err) {
    console.warn("[mark-read] failed:", err);
  }
};
```

⚠️ Se o nome do setter não for `setConversations`, descobrir o real (procurando no arquivo) e adaptar.

- [ ] **Step 3: Mitigação de race com realtime (best-effort)**

Procurar no arquivo se há listener Supabase realtime para a tabela `conversations` (algo como `supabase.channel('conversations').on('postgres_changes', ...)`). Se houver:

Adicionar um set/ref de IDs marcados como lidos:
```tsx
const recentlyMarkedRef = useRef<Map<string, number>>(new Map());

// Ao marcar como lido com sucesso:
recentlyMarkedRef.current.set(conversationId, Date.now());
```

E no listener, antes de aplicar update no state:
```tsx
const recently = recentlyMarkedRef.current.get(updatedConv.id);
if (recently && Date.now() - recently < 30_000 && updatedConv.unread_count > 0) {
  // Ignorar este update — vendedor acabou de marcar como lido, payload está stale
  return;
}
```

Se NÃO houver listener para `conversations`, pular este step. Reportar `DONE_WITH_CONCERNS` indicando que a mitigação não foi necessária ou não foi possível detectar.

- [ ] **Step 4: Passar `onMarkRead` ao ChatList**

Localizar onde `<ChatList ... />` é renderizado e adicionar a prop:

```tsx
<ChatList
  ...existing props...
  onMarkRead={handleMarkRead}
/>
```

- [ ] **Step 5: TypeScript check final**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run type-check 2>&1 | tail -10
```

Esperado: 0 erros.

- [ ] **Step 6: Commit conjunto (Tasks 3 + 4)**

```bash
git add frontend/src/components/conversas/chat-list.tsx frontend/src/app/\(authenticated\)/conversas/page.tsx
git commit -m "fix(conversas): lift mark-read to parent + ignore stale realtime updates"
```

---

## Task 5: Smoke test e push

- [ ] **Step 1: Build production**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run build 2>&1 | tail -10
```

- [ ] **Step 2: Push (commits são touch suficientes — não precisa marker já que tocam frontend/)**

```bash
cd /home/rafael/maquinadevendas && git push origin feat/conversas-ux-fixes:master 2>&1 | tail -10
```

- [ ] **Step 3: Reportar deploy ao usuário**

Após push, deploy do CRM dispara automaticamente (último commit toca `frontend/`). Aguardar ~3-5min para deploy completar.

---

## Self-Review

**Spec coverage:**
- ✅ F1 (banner CTA): Task 1 step 4 + Task 2
- ✅ F2 (compact sempre visível): Task 1 step 3
- ✅ F3 (chat-view onReactivate): Task 2
- ✅ F4 (chat-list lift): Task 3
- ✅ F5 (page.tsx handler + race mitigation): Task 4

**Placeholder scan:** todos os steps têm código completo. Os "if achar listener" / "se nome do setter for outro" são bounded delegations razoáveis.

**Type consistency:** `onMarkRead?: (conversationId: string) => void`, `onReactivate?: () => void` consistentes nos pontos de uso e definição.

---

## Execução

Ordem sequencial: 1 → 2 → 3 → 4 → 5. Tasks 3+4 ficam num commit conjunto.

Push para master após Task 5 dispara deploy automaticamente (commits tocam `frontend/`).
