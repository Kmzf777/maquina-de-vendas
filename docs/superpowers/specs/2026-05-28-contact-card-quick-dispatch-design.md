# Contact Card Quick Dispatch — Design Spec

**Data:** 2026-05-28  
**Status:** Aprovado

---

## Problema

Quando um lead compartilha um contato via WhatsApp (message_type = "contact"), o bubble exibe ícone + nome + telefone + link "Baixar contato". Não há nenhuma ação para iniciar uma conversa com o contato referenciado. O vendedor precisa copiar o número, sair da tela e abrir o disparo rápido manualmente.

## Solução

Transformar o bubble de contato em um card interativo com botão "Chamar contato" que abre o `QuickSendModal` pré-preenchido com o número do contato compartilhado.

---

## Arquitetura

### 1. `QuickSendModal` — adicionar prop `prefillPhone`

```ts
interface QuickSendModalProps {
  open: boolean;
  onClose: () => void;
  onSuccess: (count: number) => void;
  prefillPhone?: string;  // NOVO — número pré-inserido ao abrir
}
```

**Comportamento:**
- Quando `prefillPhone` é fornecido, o estado inicial de `phones` é `[prefillPhone]` em vez de `[""]`.
- O número já aparece preenchido no campo ao abrir o modal.
- O vendedor pode trocar ou adicionar mais números normalmente.
- Canal e template continuam vazios (usuário escolhe).

**Implementação:** trocar o `useState<string[]>([""])` por um `useState` inicializado com `prefillPhone ? [prefillPhone] : [""]`. Como o modal só monta quando `open === true`, não é necessário `useEffect` — o valor inicial é suficiente. Porém, como o componente pode ser montado uma vez e ter `prefillPhone` variando, usar `useEffect` no `open` para resetar se necessário (já existe o `handleClose`).

### 2. `MessageBubble` — redesign do bloco `isContact`

O bloco atual (linhas 215–244 de `message-bubble.tsx`) é substituído por um card com:

- Avatar/ícone de pessoa (shadcn `Avatar` ou ícone SVG)
- Nome em destaque
- Telefone em cinza
- Divider
- Botão "Chamar contato" (ocupa largura do card, estilo consistente com o design system)

**Interação:**
- Clique no botão → `onContactDispatch(phone)` callback
- O callback é definido em `MessageList` ou `ChatView` e gerencia o estado `showQuickSendModal` + `quickSendPrefillPhone`

### 3. Propagação do evento por `MessageList` → `ChatView`

`MessageBubble` recebe `onContactDispatch?: (phone: string) => void`.  
`MessageList` recebe e passa para `MessageBubble`.  
`ChatView` implementa o handler: seta `prefillPhone` e abre `QuickSendModal`.

---

## Componentes Afetados

| Arquivo | Mudança |
|---|---|
| `components/conversas/message-bubble.tsx` | Redesign do bloco `isContact` + prop `onContactDispatch` |
| `components/conversas/message-list.tsx` | Passar `onContactDispatch` para `MessageBubble` |
| `components/conversas/chat-view.tsx` | Estado `quickSendPrefillPhone`, abrir `QuickSendModal` |
| `components/campaigns/quick-send-modal.tsx` | Prop `prefillPhone?: string` |

---

## Design do Card (shadcn + Tailwind)

O card usa o vocabulário visual existente do projeto:
- Fundo: `bg-white` com `border border-[#dedbd6]` (igual outros bubbles de mídia)
- Largura: `max-w-[240px]` (consistente com outros cards de mídia)
- Botão: estilo primário do projeto — `bg-[#111111] text-white` com hover scale
- Separador: `border-t border-[#dedbd6]` entre os dados e o botão
- Nome: `text-[13px] font-medium text-[#111111]`
- Telefone: `text-[12px] text-[#7b7b78]`

---

## Fluxo Completo

```
Lead envia contato (Virginia Muller, +55 54 99653-4987)
  → bubble renderiza card com botão "Chamar contato"
  → vendedor clica
  → QuickSendModal abre com phones = ["+55 54 99653-4987"]
  → vendedor seleciona instância + template
  → disparo criado via /api/broadcasts → /api/leads/resolve → broadcast start
```

---

## Fora de Escopo

- Buscar se o contato já existe como lead (sem indicador "já é cliente")
- Abrir conversa existente com o contato (apenas disparo, não navegação)
- Suporte a contatos com múltiplos telefones no vcard (usa apenas o campo `phone` do metadata)
