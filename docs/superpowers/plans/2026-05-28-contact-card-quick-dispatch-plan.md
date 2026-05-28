# Contact Card Quick Dispatch — Implementation Plan

**Spec:** `docs/superpowers/specs/2026-05-28-contact-card-quick-dispatch-design.md`  
**Branch:** `worktree-feat+contact-card-quick-dispatch`  
**Data:** 2026-05-28

---

## Contexto

Leads às vezes compartilham contatos via WhatsApp. O bubble atual mostra nome + telefone + link VCF, mas não tem ação para disparar mensagem para esse contato. O objetivo é adicionar um botão "Chamar contato" que abre o QuickSendModal pré-preenchido com o número.

**IMPORTANTE para todos os agentes de frontend:** usar shadcn e a skill `frontend-design` antes de qualquer trabalho visual.

---

## Tarefas

### Tarefa 1 — `quick-send-modal.tsx`: adicionar prop `prefillPhone`

**Arquivo:** `frontend/src/components/campaigns/quick-send-modal.tsx`

1. Adicionar `prefillPhone?: string` à interface `QuickSendModalProps`
2. Trocar a inicialização de `phones`:
   ```ts
   // antes
   const [phones, setPhones] = useState<string[]>([""]);
   // depois
   const [phones, setPhones] = useState<string[]>(prefillPhone ? [prefillPhone] : [""]);
   ```
3. No `useEffect` do `open` (linhas 73–88), no `handleClose`, garantir que ao fechar e reabrir sem `prefillPhone` o estado volta para `[""]`. O `handleClose` já faz `setPhones([""])` — manter esse comportamento.
4. Adicionar `prefillPhone` ao array de dependências se usar `useEffect` para resetar ao `open`.

**Critério:** abrir o modal com `prefillPhone="+5554996534987"` deve mostrar o número já preenchido no campo, editável normalmente.

---

### Tarefa 2 — `message-bubble.tsx`: redesign do bloco `isContact`

**Arquivo:** `frontend/src/components/conversas/message-bubble.tsx`

**Adicionar prop:**
```ts
interface MessageBubbleProps {
  message: Message;
  isGrouped: boolean;
  conversationId: string;
  onContactDispatch?: (phone: string) => void;  // NOVO
}
```

**Substituir o bloco `isContact` atual** (linhas 215–244) por um card com shadcn:

Estrutura do card:
```
┌──────────────────────────────────┐
│  [ícone pessoa]  Virginia Muller │
│                  +55 54 99653-... │
├──────────────────────────────────┤
│        [Chamar contato]          │
└──────────────────────────────────┘
```

- Usar `Avatar` do shadcn (`@/components/ui/avatar`) se disponível, ou SVG de pessoa
- Card: `rounded-[8px] border border-[#dedbd6] bg-white overflow-hidden min-w-[200px] max-w-[240px]`
- Topo: `px-3 py-2.5 flex items-center gap-2.5`
- Nome: `text-[13px] font-medium text-[#111111]`
- Telefone: `text-[12px] text-[#7b7b78]`
- Divider: `border-t border-[#dedbd6]`
- Botão: `w-full px-3 py-2 text-[12px] text-[#111111] hover:bg-[#f0ede8] transition-colors text-left flex items-center gap-1.5`
- Ícone no botão: seta de disparo (→) ou ícone de mensagem pequeno
- Se `!meta?.phone` ou `!onContactDispatch`: ocultar o botão (fallback gracioso)

**Manter** o link "Baixar contato" (VCF) se `vcardUrl` existir — pode ficar como texto secundário no topo junto ao telefone.

---

### Tarefa 3 — `message-list.tsx`: passar `onContactDispatch`

**Arquivo:** `frontend/src/components/conversas/message-list.tsx`

1. Adicionar `onContactDispatch?: (phone: string) => void` aos props de `MessageList`
2. Passar para cada `<MessageBubble onContactDispatch={onContactDispatch} />`

---

### Tarefa 4 — `chat-view.tsx`: orquestrar o estado e abrir QuickSendModal

**Arquivo:** `frontend/src/components/conversas/chat-view.tsx`

1. Adicionar estado:
   ```ts
   const [quickSendPhone, setQuickSendPhone] = useState<string | null>(null);
   ```
2. Handler:
   ```ts
   function handleContactDispatch(phone: string) {
     setQuickSendPhone(phone);
   }
   ```
3. Passar para `<MessageList onContactDispatch={handleContactDispatch} />`
4. Importar `QuickSendModal` de `@/components/campaigns/quick-send-modal`
5. Renderizar o modal:
   ```tsx
   <QuickSendModal
     open={quickSendPhone !== null}
     onClose={() => setQuickSendPhone(null)}
     onSuccess={() => setQuickSendPhone(null)}
     prefillPhone={quickSendPhone ?? undefined}
   />
   ```
6. No `useEffect` de reset ao trocar de conversa (linha 58), adicionar `setQuickSendPhone(null)`

---

## Ordem de execução

1 → 2 → 3 → 4 (cada tarefa depende da anterior para tipagem correta)

---

## Verificação

- Abrir uma conversa com mensagem de tipo `contact` no metadata
- Confirmar que o card exibe nome, telefone e botão "Chamar contato"
- Clicar no botão → QuickSendModal abre com o número pré-preenchido
- Número editável, canal e template vazios para seleção
- Fechar modal → estado limpo
- Trocar de conversa → modal fechado automaticamente
- Contato sem telefone → botão não aparece (sem erro)
