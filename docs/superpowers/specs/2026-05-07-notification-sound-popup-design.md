# Spec: Som e Pop-up de Notificação de Mensagem Nova

**Data:** 2026-05-07

---

## Problema

Quando um lead envia uma mensagem e a IA está desativada na conversa, o vendedor não tem feedback imediato — especialmente se estiver em outra página do CRM. O único indicador atual é o badge de não-lidas na lista de conversas, visível somente em `/conversas`.

---

## Solução

Ao receber uma mensagem de lead (`role = "user"`) em uma conversa com `ai_enabled = false`:

1. Tocar um som de notificação
2. Exibir um toast pop-up global com o nome do lead e preview da mensagem
3. O toast fecha sozinho após 5 segundos ou ao clicar
4. Clicar navega para `/conversas?lead_id=<id>`

O sistema opera em **todas as páginas autenticadas** do CRM.

---

## Arquitetura

### Fluxo de dados

```
Supabase Realtime (messages INSERT)
  → role === "user"?
      → sim: buscar conversations WHERE lead_id = X
          → ai_enabled === false?
              → sim: tocar som + exibir toast
              → não: ignorar
      → não: ignorar
```

### Componentes novos

**`frontend/src/hooks/use-message-notifications.ts`**
- Hook `"use client"` que abre canal Supabase Realtime em `messages` (INSERT, sem filtro de lead)
- Ao receber INSERT com `role === "user"`, consulta Supabase diretamente:
  ```ts
  supabase
    .from("conversations")
    .select("id, lead_id, leads!inner(id, name, ai_enabled)")
    .eq("lead_id", message.lead_id)
    .maybeSingle()
  ```
- Se `ai_enabled === false`: adiciona notificação ao estado local e chama `playNotificationSound()`
- Retorna: `{ notifications, dismiss }` onde `notifications: Notification[]`

**Tipo `Notification`:**
```ts
interface Notification {
  id: string;          // uuid gerado no client
  leadId: string;
  leadName: string;
  messagePreview: string;  // conteúdo truncado a 80 chars
  conversationId: string;
}
```

**`frontend/src/components/notification-toast.tsx`**
- Componente `"use client"` que usa `use-message-notifications`
- Renderiza stack de toasts (fixed, bottom-right, z-50)
- Cada toast:
  - Lead name em bold
  - Message preview em cinza, truncado com `...` se > 80 chars
  - Auto-dismiss com `setTimeout(5000)`
  - Clicar → `router.push('/conversas?lead_id=X')` + dismiss
  - Botão X para dismiss manual

**`frontend/public/notification.mp3`**
- Placeholder — usuário fará upload do arquivo real
- Reprodução: `new Audio('/notification.mp3').play().catch(() => {})` (silencia erro de autoplay policy)

### Integração

`AuthenticatedShell` (já `"use client"`) recebe `<NotificationToast />` dentro do `return`, após o `<main>`. Nenhuma mudança de estado no shell — o componente é self-contained.

---

## Design do Toast

```
┌─────────────────────────────────────┐
│ 💬  João Silva                    × │
│     "Oi, queria saber sobre o pr..." │
└─────────────────────────────────────┘
```

- Fundo: `#ffffff`, borda `#dedbd6`, sombra `shadow-lg`
- Bordas arredondadas: `rounded-[8px]`
- Largura: `w-80` (320px)
- Stack: múltiplos toasts empilham verticalmente com gap
- Posição: `fixed bottom-6 right-6 z-50 flex flex-col gap-2`
- Animação: slide-in da direita ao aparecer, fade-out ao sair

---

## Casos de Borda

| Cenário | Comportamento |
|---|---|
| AI ativada na conversa | Sem som, sem toast |
| Mensagem do bot (`role="assistant"`) | Ignorada |
| Conversa não encontrada | Silenciosamente descartada |
| Autoplay bloqueado pelo browser | Som não toca, toast aparece normalmente |
| Múltiplas mensagens rápidas | Toasts empilham (máx. 3 simultâneos) |
| Usuário já está na conversa | Toast aparece mesmo assim (ok para v1) |
| Audio file ausente | catch silencioso — sem crash |

---

## O Que Não Muda

- `use-realtime-messages.ts` — sem alteração
- `conversas/page.tsx` — sem alteração
- Tabelas e schema do banco — sem alteração
- Backend Python — sem alteração
- `/api/conversations` route — sem alteração

---

## Arquivos Modificados

| Arquivo | Mudança |
|---|---|
| `frontend/src/hooks/use-message-notifications.ts` | Novo |
| `frontend/src/components/notification-toast.tsx` | Novo |
| `frontend/src/components/authenticated-shell.tsx` | Adicionar `<NotificationToast />` |
| `frontend/public/notification.mp3` | Placeholder (usuário faz upload) |
