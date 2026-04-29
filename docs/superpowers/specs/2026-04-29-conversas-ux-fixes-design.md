# Conversas UX Fixes (Fase B-1) — Design Spec

**Data:** 2026-04-29
**Branch:** `feat/conversas-ux-fixes`
**Base:** `feat/conversas-ux-redesign-v2` (já mergeada em master via push)

## Contexto

Após o deploy da Fase B, três regressões/falhas surgiram:

1. **Lista** — `WhatsappWindowIndicator variant="compact"` mostra apenas um dot 1.5px cinza para conversas dentro da janela, sem texto. Vendedor não consegue distinguir leads dentro/fora da janela 24h batendo o olho na lista.
2. **Chat-view sem CTA de disparo** — Task 10 (T10) substituiu os dois banners inline (`expiring` amber + `closed` orange) pelo banner unificado, mas levou junto o botão "Reativar conversa" que era o único caminho para abrir o `WindowReactivatePanel`. Hoje o banner expired só exibe texto, sem ação.
3. **Badge de não-lidas não zera** — `chat-list.tsx` tem um shadow `useState` inicializado de props com sync `if (prev !== current) setConversations(current)`. Quando o pai re-renderiza com state atualizado (realtime ou polling), o shadow sobrescreve o zero local feito em `mark-read`. Resultado: badge volta a aparecer mesmo após o vendedor responder.

## Escopo

### Dentro
- F1: `WhatsappWindowIndicator` ganha prop `onReactivate?: () => void` no variant `banner`; renderiza botão "Reativar conversa" quando recebido.
- F2: `WhatsappWindowIndicator` variant `compact` sempre mostra dot colorido + texto descritivo (verde "Xh" para active, amber para warning, Fin Orange pulse para critical, cinza-bloqueado para expired). Para `none` (sem inbound ainda), mostra dot oat neutro sem texto.
- F3: `chat-view.tsx` passa `onReactivate={() => setShowReactivatePanel(true)}` ao banner; remove a checagem `windowStatus === "closed"` na renderização do panel (o próprio painel só abre via clique).
- F4: `chat-list.tsx` perde o shadow `useState<Conversation[]>`. Recebe `onMarkRead?: (conversationId: string) => void` por prop. O fetch e o reset de state ficam no pai.
- F5: `page.tsx` ganha `handleMarkRead` que faz `fetch POST /api/conversations/{id}/mark-read` e atualiza `conversations` no state-source.

### Fora (vai para depois)
- Tooltip educativo no compact (lista é densa, não cabe)
- Sound notification, badge no tab title, browser notification

## Design system

Cores do palette warm já em uso. Para o "verde dentro da janela" no dot compact, usar tom **warm-green** consistente com `getStageColor("exportacao")` que é `bg-[#5aad65]`. Mantém paleta sem `bg-green-500` frio.

## Detalhamento por fix

### F1+F2 — `whatsapp-window-indicator.tsx`

Adicionar à interface:
```ts
interface Props {
  expiresAt: string | null;
  variant: 'compact' | 'header' | 'banner';
  className?: string;
  onReactivate?: () => void;  // novo — usado só no variant 'banner'
}
```

**Variant `compact`** — sempre visível:
- `active`: `<dot bg-[#5aad65]>` + ` <span> Xh </span>` (compacto, monoespaçado se possível para alinhar)
- `warning`: `<dot bg-amber-500>` + texto `Xh`
- `critical`: `<dot bg-[#ff5600] animate-pulse>` + texto `Xmin`
- `expired`: `<dot bg-[#7b7b78]>` + texto `fechada`
- `none`: `<dot bg-[#dedbd6]>` apenas (sem texto)
- Texto sempre `text-xs text-[#7b7b78]`. Aria-label descrevendo o estado.

**Variant `banner` (expired only)** — adicionar action button quando `onReactivate` é passado:
```tsx
{onReactivate && (
  <button
    onClick={onReactivate}
    className="ml-auto text-xs bg-[#111111] text-white px-3 py-1 rounded-[4px] hover:opacity-90 transition-opacity"
  >
    Reativar conversa
  </button>
)}
```

Layout do banner: `flex items-center gap-2 ... justify-between` em vez de só `gap-2`, para o botão ir pra direita.

### F3 — `chat-view.tsx`

Passar `onReactivate`:
```tsx
<WhatsappWindowIndicator
  expiresAt={conversation.whatsapp_window_expires_at}
  variant="banner"
  onReactivate={() => setShowReactivatePanel(true)}
/>
```

A linha `{showReactivatePanel && windowStatus === "closed" && <WindowReactivatePanel ... />}` continua igual — o estado já protege.

### F4 — `chat-list.tsx`

Remover do componente:
```tsx
const [conversations, setConversations] = useState<Conversation[]>(initialConversations);
const [prevInitial, setPrevInitial] = useState(initialConversations);
if (prevInitial !== initialConversations) {
  setPrevInitial(initialConversations);
  setConversations(initialConversations);
}
```

Trocar para receber `conversations` direto da prop. Adicionar prop:
```tsx
onMarkRead?: (conversationId: string) => void;
```

`handleSelectConversation` simplifica:
```tsx
const handleSelectConversation = (conv: Conversation) => {
  onSelectConversation(conv);
  if ((conv.unread_count ?? 0) > 0 && onMarkRead) {
    onMarkRead(conv.id);
  }
};
```

### F5 — `page.tsx`

Adicionar handler:
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

Passar `onMarkRead={handleMarkRead}` para `<ChatList />`.

⚠️ Race com realtime/polling: se o realtime do Supabase trouxer a mesma conversa com `unread_count=2` de novo, o problema volta. Mitigar: incluir um set local de "marked-as-read recently" — se o realtime trouxer um update para uma conversa marcada nos últimos 30s, ignorar o `unread_count` da resposta. **Implementar essa mitigação inicialmente.** Se não houver realtime listener para conversations (ou listener for só pra mensagens), pular essa mitigação.

## Critério de sucesso

- Vendedor abre conversa com unread > 0 → badge zera e **não volta** mesmo após o realtime push subsequente.
- Lista mostra dot colorido (verde/amber/orange/cinza) ao lado do timestamp em todo card com janela definida — distinção clara entre dentro e fora.
- Lead com janela expirada: chat mostra banner cinza com texto + botão "Reativar conversa" que abre o `WindowReactivatePanel`.
- Nenhuma regressão de comportamento (toggle Valéria, mark-read, envio, sidebar).

## Riscos

- F4/F5 (lift mark-read): se realtime de Supabase listener mudar `conversations` muito rápido, pode haver flicker do badge entre o click e o `setConversations` do parent. A janela de "marked recently" mitiga.
- F2 (sempre mostrar dot): pode aumentar densidade visual do card; mas semantic é alta — vendedor pediu.
