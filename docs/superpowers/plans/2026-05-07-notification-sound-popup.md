# Notification Sound & Pop-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **FRONTEND RULE:** Any agent touching frontend code MUST invoke the `frontend-design` skill before writing any JSX, CSS, or Tailwind classes.

**Goal:** Tocar um som e exibir um toast pop-up global quando um lead envia uma mensagem em conversa com IA desativada.

**Architecture:** Hook `use-message-notifications` assina Supabase Realtime globalmente em `messages` INSERT, filtra `role="user"`, consulta se `ai_enabled=false`, e alimenta o componente `NotificationToast` renderizado dentro de `AuthenticatedShell`.

**Tech Stack:** Next.js App Router, React `"use client"`, Supabase Realtime postgres_changes, Web Audio API (`new Audio()`)

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `frontend/public/notification.mp3` | Criar (placeholder) | Arquivo de áudio de notificação |
| `frontend/src/hooks/use-message-notifications.ts` | Criar | Realtime subscription + lógica de filtro + estado das notificações |
| `frontend/src/components/notification-toast.tsx` | Criar | UI do stack de toasts com auto-dismiss |
| `frontend/src/components/authenticated-shell.tsx` | Modificar | Adicionar `<NotificationToast />` no JSX |

---

## Task 1: Feature branch e placeholder de áudio

**Files:**
- Create: `frontend/public/notification.mp3` (placeholder vazio)

- [ ] **Step 1: Criar branch de feature**

```bash
git checkout -b feat/notification-sound-popup
```

- [ ] **Step 2: Criar placeholder de áudio**

O arquivo real será enviado pelo usuário. Por ora, crie um MP3 mínimo válido para não quebrar o `new Audio()`.

```bash
# Gera um MP3 silencioso de 1 segundo (44-byte header de MP3 vazio)
printf '\xff\xfb\x90\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' > /home/rafael/maquinadevendas/frontend/public/notification.mp3
```

- [ ] **Step 3: Verificar que o arquivo existe**

```bash
ls -la /home/rafael/maquinadevendas/frontend/public/notification.mp3
```

Esperado: arquivo aparece na listagem.

- [ ] **Step 4: Commit**

```bash
git add frontend/public/notification.mp3
git commit -m "feat(notifications): placeholder de audio de notificacao"
```

---

## Task 2: Hook `use-message-notifications`

**Files:**
- Create: `frontend/src/hooks/use-message-notifications.ts`

Este hook:
1. Abre um canal Supabase Realtime global em `messages` INSERT
2. Filtra apenas `role === "user"` (mensagem do lead)
3. Para cada mensagem relevante, consulta a conversa com join em `leads`
4. Se `ai_enabled === false`: adiciona notificação ao estado e toca o som
5. Mantém no máximo 3 toasts simultâneos

- [ ] **Step 1: Criar o hook**

Criar `/home/rafael/maquinadevendas/frontend/src/hooks/use-message-notifications.ts` com o conteúdo:

```ts
"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { createClient } from "@/lib/supabase/client";
import type { Message } from "@/lib/types";

export interface MessageNotification {
  id: string;
  leadId: string;
  leadName: string;
  messagePreview: string;
  conversationId: string;
}

function playNotificationSound() {
  try {
    new Audio("/notification.mp3").play().catch(() => {});
  } catch {
    // autoplay blocked or file missing — silently ignored
  }
}

function truncate(text: string, max: number): string {
  return text.length > max ? text.slice(0, max) + "..." : text;
}

export function useMessageNotifications() {
  const [notifications, setNotifications] = useState<MessageNotification[]>([]);
  const supabase = useMemo(() => createClient(), []);

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  useEffect(() => {
    const channel = supabase
      .channel("global-message-notifications")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages" },
        async (payload) => {
          const msg = payload.new as Message;
          if (msg.role !== "user") return;

          const { data: conv } = await supabase
            .from("conversations")
            .select("id, lead_id, leads!inner(id, name, ai_enabled)")
            .eq("lead_id", msg.lead_id)
            .maybeSingle();

          if (!conv) return;
          const lead = conv.leads as { id: string; name: string; ai_enabled: boolean } | null;
          if (!lead || lead.ai_enabled !== false) return;

          const notification: MessageNotification = {
            id: crypto.randomUUID(),
            leadId: lead.id,
            leadName: lead.name,
            messagePreview: truncate(msg.content || "(mídia)", 80),
            conversationId: conv.id,
          };

          playNotificationSound();
          setNotifications((prev) => [...prev.slice(-2), notification]);
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return { notifications, dismiss };
}
```

- [ ] **Step 2: Verificar que não há erros de TypeScript**

```bash
cd /home/rafael/maquinadevendas/frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros relacionados ao novo arquivo.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/use-message-notifications.ts
git commit -m "feat(notifications): hook use-message-notifications com realtime global"
```

---

## Task 3: Componente `NotificationToast`

**Files:**
- Create: `frontend/src/components/notification-toast.tsx`

> **OBRIGATÓRIO:** Invocar a skill `frontend-design` antes de escrever qualquer JSX/CSS/Tailwind neste task.

O componente é composto por:
- `NotificationToast`: container fixed bottom-right que renderiza a lista de `ToastItem`
- `ToastItem`: card individual com auto-dismiss de 5s, botão X, área clicável de navegação

- [ ] **Step 1: Invocar skill frontend-design**

Antes de escrever o componente, invocar:
```
Skill({ skill: "frontend-design" })
```

- [ ] **Step 2: Criar o componente**

Criar `/home/rafael/maquinadevendas/frontend/src/components/notification-toast.tsx`:

```tsx
"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useMessageNotifications, type MessageNotification } from "@/hooks/use-message-notifications";

interface ToastItemProps {
  notification: MessageNotification;
  onDismiss: () => void;
  onNavigate: () => void;
}

function ToastItem({ notification, onDismiss, onNavigate }: ToastItemProps) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onDismissRef = useRef(onDismiss);
  useEffect(() => { onDismissRef.current = onDismiss; });

  useEffect(() => {
    timerRef.current = setTimeout(() => onDismissRef.current(), 5000);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []); // timer é criado uma vez no mount — ref mantém callback atualizado

  return (
    <div className="w-80 bg-white border border-[#dedbd6] rounded-[8px] shadow-lg flex items-start gap-3 p-3 pointer-events-auto cursor-pointer hover:bg-[#faf9f6] transition-colors">
      <button
        onClick={onNavigate}
        className="flex-1 text-left min-w-0"
        aria-label={`Abrir conversa de ${notification.leadName}`}
      >
        <p className="text-[13px] font-semibold text-[#111111] truncate">
          {notification.leadName}
        </p>
        <p className="text-[12px] text-[#7b7b78] mt-0.5 line-clamp-2 break-words">
          {notification.messagePreview}
        </p>
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDismiss();
        }}
        className="flex-shrink-0 w-5 h-5 flex items-center justify-center rounded text-[#7b7b78] hover:text-[#111111] hover:bg-[#f0ede8] transition-colors"
        aria-label="Fechar notificação"
      >
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}

export function NotificationToast() {
  const router = useRouter();
  const { notifications, dismiss } = useMessageNotifications();

  if (notifications.length === 0) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
      {notifications.map((n) => (
        <ToastItem
          key={n.id}
          notification={n}
          onDismiss={() => dismiss(n.id)}
          onNavigate={() => {
            router.push(`/conversas?lead_id=${n.leadId}`);
            dismiss(n.id);
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Verificar TypeScript**

```bash
cd /home/rafael/maquinadevendas/frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem novos erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/notification-toast.tsx
git commit -m "feat(notifications): componente NotificationToast com auto-dismiss"
```

---

## Task 4: Integrar em `AuthenticatedShell`

**Files:**
- Modify: `frontend/src/components/authenticated-shell.tsx`

> **OBRIGATÓRIO:** Invocar a skill `frontend-design` antes de escrever qualquer JSX/CSS/Tailwind neste task.

Adicionar `<NotificationToast />` como último filho do div raiz do `AuthenticatedShell`. O componente já é `"use client"`, então nenhuma conversão é necessária.

- [ ] **Step 1: Invocar skill frontend-design**

```
Skill({ skill: "frontend-design" })
```

- [ ] **Step 2: Ler o arquivo atual para editar**

Ler `/home/rafael/maquinadevendas/frontend/src/components/authenticated-shell.tsx` (usar Read tool, não cat).

- [ ] **Step 3: Adicionar import**

Adicionar no topo do arquivo, junto aos outros imports:

```ts
import { NotificationToast } from "@/components/notification-toast";
```

- [ ] **Step 4: Adicionar componente no JSX**

Dentro do `return`, após o bloco `<main>...</main>`, antes do fechamento do div raiz `</div>`, adicionar:

```tsx
      <NotificationToast />
```

O JSX final do return deve terminar assim:

```tsx
      <main
        className={`flex-1 relative flex flex-col pt-14 md:pt-0 ${
          isConversas ? "overflow-hidden" : "overflow-auto"
        }`}
      >
        {children}
      </main>
      <NotificationToast />
    </div>
  );
```

- [ ] **Step 5: Verificar TypeScript**

```bash
cd /home/rafael/maquinadevendas/frontend && npx tsc --noEmit 2>&1 | head -30
```

Esperado: sem erros.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/authenticated-shell.tsx
git commit -m "feat(notifications): integrar NotificationToast no AuthenticatedShell"
```

---

## Task 5: Verificação manual

Não há framework de testes configurado no projeto. A verificação é manual via servidor de dev.

- [ ] **Step 1: Subir servidor de dev**

```bash
cd /home/rafael/maquinadevendas/frontend && npm run dev
```

Aguardar "Ready" na saída.

- [ ] **Step 2: Cheklist de verificação**

Abrir o CRM em `http://localhost:3000` e verificar:

1. **Toast não aparece para conversas com IA ativa:** Enviar mensagem de teste em conversa com `ai_enabled=true` → nenhum toast deve aparecer
2. **Toast aparece para conversas com IA desativada:** Desativar IA em uma conversa → simular nova mensagem do lead → toast deve aparecer bottom-right com nome e preview
3. **Auto-dismiss:** Toast some após ~5 segundos sem interação
4. **Dismiss manual:** Clicar no X fecha o toast imediatamente
5. **Navegação:** Clicar no toast navega para `/conversas?lead_id=X` abrindo a conversa correta
6. **Máximo 3 toasts:** Enviar 4 mensagens rápidas → apenas 3 toasts simultâneos
7. **Outras páginas:** Navegar para `/leads` ou `/vendas` → toast ainda aparece ao receber mensagem

- [ ] **Step 3: Confirmar com usuário**

Reportar resultado da verificação ao usuário. Aguardar autorização antes de qualquer push.

---

## Notas de Deploy

- Após aprovação do usuário: `git push origin feat/notification-sound-popup:master`
- O usuário fará upload do `notification.mp3` real em `frontend/public/`
- Não há migrações de banco de dados
- Não há variáveis de ambiente novas
