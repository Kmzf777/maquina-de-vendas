# Spec: Respostas Rápidas (`/` no chat)

**Data:** 2026-06-17  
**Branch:** feat/chat-quick-replies  
**Status:** Aprovado

---

## Contexto

No chat de atendimento (`/conversas`), o vendedor digita as mesmas mensagens repetidamente (saudações, condições, links, follow-ups). Queremos uma biblioteca de **respostas rápidas** de texto livre:

1. Em `/conversas`, ao digitar `/` no compositor, abre uma lista filtrável das mensagens prontas; selecionar insere o texto no compositor. A lista tem um botão que **redireciona para a criação** de uma nova mensagem.
2. Em `/config`, um **modal com a lista** das mensagens criadas permite criar/editar/excluir.

> ⚠️ **Não confundir com Templates HSM da Meta.** O recurso "Templates" que já existe na UI (`template-dispatch-modal.tsx`, tabela `message_templates`, scripts `create_utility_templates.py`/`insert_templates.sql`) é o sistema de templates aprovados da Meta para reabrir a janela de 24h — conceito **diferente**. Por isso o rótulo desta feature é **"Respostas Rápidas"**, nunca "Templates".

---

## Decisões (travadas no brainstorming)

| Tema | Decisão |
|---|---|
| **Gatilho** | `/` abre a lista; digitar depois filtra por `shortcut`/`title`/`content`. Cada resposta tem um `shortcut` curto **opcional**. |
| **Escopo** | Biblioteca **global compartilhada** (sem dono), igual ao padrão de `tags`/`quick_send_phones`. |
| **Variáveis** | Suporta `{{primeiro_nome}}` etc. já no v1, **reusando o mapa de resolvers existente**, resolvidas **na inserção**. |
| **Gestão** | Modal em `/config` com a lista (CRUD). Botão no menu do `/conversas` **redireciona** para esse modal em modo criação. |
| **Permissões** | Todos os vendedores criam/editam (consistente com `tags` globais). *(Trocar para admin-only é 1 linha se necessário.)* |
| **Build do menu** | Componente **custom** (overlay na mão, estilo `QuickSendModal`) — **zero dependência nova**. |

---

## Modelo de dados

Tabela nova e dedicada (não sobrecarregar `message_templates`/`template_presets`, que são HSM). Mesma postura de RLS/acesso que `tags` (lida/escrita via route handlers com service-role).

```sql
-- backend/migrations/20260617_quick_replies.sql  (aplicar manualmente no Supabase)
create table public.quick_replies (
  id          uuid primary key default gen_random_uuid(),
  shortcut    text,                       -- atalho do "/" (opcional). Ex.: "saudacao"
  title       text not null,              -- rótulo exibido na lista
  content     text not null,              -- corpo; pode conter {{primeiro_nome}} etc.
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index quick_replies_shortcut_idx on public.quick_replies (shortcut);
```

- **Global:** sem `owner_user_id`. Um `owner_user_id` nullable pode ser adicionado depois sem quebrar a UI, se um dia quiserem snippets privados.
- `shortcut` não é único no v1 (a lista filtrável resolve colisões).

---

## API (route handlers Next — sem FastAPI)

Clone do padrão de `frontend/src/app/api/tags/`, usando `getServiceSupabase()` de `@/lib/supabase/api`.

| Método | Rota | Ação |
|---|---|---|
| `GET` | `/api/quick-replies` | Lista todas (ordenadas por `title`). |
| `POST` | `/api/quick-replies` | Cria `{ shortcut?, title, content }`. |
| `PUT` | `/api/quick-replies/[id]` | Atualiza. |
| `DELETE` | `/api/quick-replies/[id]` | Remove. |

Tipo `QuickReply` adicionado em `frontend/src/lib/types.ts`.

---

## Variáveis de lead (`{{...}}`)

**Refactor de extração (melhoria do código que estamos tocando):**

- Criar `frontend/src/lib/lead-variables.ts` exportando:
  - `LEAD_RESOLVERS` — **movido** de `template-dispatch-modal.tsx` (hoje é `const` privada na linha 22).
  - `resolveLeadVariables(text: string, lead): string` — substitui cada `{{token}}` por `LEAD_RESOLVERS[token]?.(lead)`; tokens desconhecidos ficam como estão.
- `template-dispatch-modal.tsx` passa a **importar** `LEAD_RESOLVERS` desse módulo (sem mudança de comportamento; `resolveBody` continua lá, pois é específico dos params HSM).
- Na **inserção** em `/conversas`, o `content` é passado por `resolveLeadVariables(content, conversation.leads)` antes de entrar no `text`. O modal de gestão guarda o **texto cru** (`{{...}}`); só o compositor conhece o lead.

---

## `/conversas` — menu do `/`

Tudo em `frontend/src/components/conversas/chat-view.tsx`, **apenas no branch de input normal** (quando não está bloqueado pela janela 24h, nem em preview/gravação de mídia). O menu em si vira um componente isolado `quick-reply-menu.tsx` (o `chat-view.tsx` já é grande).

**Estado novo no `ChatView`:** `qrOpen`, `qrQuery` (derivado do texto), `qrItems` (lista buscada 1x), `qrIndex` (item destacado). Resetar `qrOpen` no effect de troca de conversa (já existe em `chat-view.tsx:71-87`).

**1. Detecção do gatilho** (no `onChange` do textarea):
- Regex no texto **até o caret**: `/(^|\s)\/(\S*)$/`. Casa `/` no início da linha ou após espaço, capturando o token parcial como filtro (`qrQuery`).
- Abre o menu quando casa; fecha ao digitar espaço, ao apagar o `/`, no `Esc` ou após selecionar.
- Filtro client-side case-insensitive em `shortcut` + `title` + `content`.

**2. Navegação por teclado** — estender `handleKeyDown` (hoje em `chat-view.tsx:201-206`), tratando o menu **primeiro**:
```
if (qrOpen) {
  ArrowDown → move(+1); preventDefault
  ArrowUp   → move(-1); preventDefault
  Enter|Tab → selecionar destacado; preventDefault   // NÃO cair no handleSend
  Escape    → fechar menu; preventDefault
  return
}
// fechado: mantém o Enter→handleSend atual (linha 202-205)
```

**3. Inserção** (ao selecionar):
- `resolved = resolveLeadVariables(item.content, conversation.leads)`.
- Remove o trecho `\/(\S*)$` (preservando o espaço/início anterior) do texto antes do caret e concatena `resolved` + o que vinha depois do caret.
- `setText(next)`, fecha o menu, refoca `textareaRef` e posiciona o caret ao fim do texto inserido (via `requestAnimationFrame`).

**4. Botão "criar"** — no rodapé do menu, **"+ Criar mensagem"** faz `router.push('/config?tab=respostas-rapidas&qr=new')` (redireciona para o modal de gestão em modo criação).

---

## `/config` — modal de gestão

- Nova aba **"Respostas Rápidas"** em `frontend/src/app/(authenticated)/config/page.tsx` (junto de `BASE_TABS`).
- A aba abre o `QuickRepliesModal` (`frontend/src/components/config/quick-replies-modal.tsx`): **lista** todas as respostas com editar/excluir + formulário de criar/editar (`shortcut`, `title`, `content`) e um helper pra inserir variáveis (`{{primeiro_nome}}`…). Overlay na mão, estilo `QuickSendModal`.
- **Deep-link:** a aba/modal abre via query param (`?tab=respostas-rapidas&qr=new` → modal já em criação), pro botão do `/conversas` funcionar. Garantir que `config/page.tsx` lê a aba do `searchParams`.

---

## UX/UI

**Menu do `/` (abre para cima, largura do input):**
```
┌──────────────────────────────────────────────┐
│  /saud                              ↑↓ Enter  │
├──────────────────────────────────────────────┤
│  ▸ Saudação          /saud                    │
│    Olá {{primeiro_nome}}, tudo bem? ...        │
│  ▸ Condições         /cond                    │
│    Trabalhamos com pagamento em ...            │
│  ▸ Link catálogo     /cat                     │
├──────────────────────────────────────────────┤
│  + Criar mensagem                              │
└──────────────────────────────────────────────┘
        ▲ ancorado ao topo do textarea
```
- Item destacado: fundo suave (`#f5f3f0`); dot/seta no item ativo.
- `max-h-56 overflow-y-auto`; superfície branca, borda `#dedbd6`, radius `6px`, sombra (tokens do repo).
- `z-index` acima da barra de reply (`replyingTo`).

**Modal de gestão (`/config`):** lista de cards (título + atalho + preview do corpo) com ✎/🗑, e um form de criar/editar com botão "Inserir variável".

---

## Arquivos a criar/modificar

| Ação | Arquivo |
|---|---|
| Criar | `backend/migrations/20260617_quick_replies.sql` |
| Criar | `frontend/src/app/api/quick-replies/route.ts` (GET, POST) |
| Criar | `frontend/src/app/api/quick-replies/[id]/route.ts` (PUT, DELETE) |
| Criar | `frontend/src/lib/lead-variables.ts` (resolvers extraídos + `resolveLeadVariables`) |
| Criar | `frontend/src/components/conversas/quick-reply-menu.tsx` (dropdown do `/`) |
| Criar | `frontend/src/components/config/quick-replies-modal.tsx` (gestão/CRUD) |
| Modificar | `frontend/src/components/conversas/chat-view.tsx` (gatilho, teclado, inserção, render do menu) |
| Modificar | `frontend/src/components/conversas/template-dispatch-modal.tsx` (importar `LEAD_RESOLVERS` do novo módulo) |
| Modificar | `frontend/src/app/(authenticated)/config/page.tsx` (aba + deep-link) |
| Modificar | `frontend/src/lib/types.ts` (tipo `QuickReply`) |

---

## Testes

- **Unit — gatilho:** `/(^|\s)\/(\S*)$/` abre em `/`, `texto /`, `\n/`; **não** abre em `http://x`, `e/ou` (sem espaço antes da `/`).
- **Unit — variáveis:** `resolveLeadVariables` troca `{{primeiro_nome}}` pelo primeiro nome; mantém token desconhecido intacto; texto sem `{{}}` passa igual.
- **Unit — teclado:** com `qrOpen` true, `Enter` seleciona e **não** chama `handleSend`; com `qrOpen` false, `Enter` envia (comportamento atual preservado).
- **Unit — inserção:** substitui o trecho `/token` pelo conteúdo resolvido, preservando texto antes/depois.
- **API:** CRUD das rotas `/api/quick-replies` (GET/POST/PUT/DELETE).
- **Manual:** mobile (dropdown pra cima + teclado); coexistência com modo reply; janela 24h fechada (menu não monta); deep-link abre o modal em criação; keepalive de realtime intacto.

---

## Fora de escopo (YAGNI v1)

- Privacidade/escopo por vendedor (tabela é global).
- Categorias, pastas, favoritos, ordenação manual.
- Anexos/mídia dentro da resposta rápida (só texto).
- Posicionamento do menu por pixel do caret (usamos ancoragem no input — mais robusto num `<textarea>`).
- Sincronização realtime da lista (busca ao abrir é suficiente).
- Estatísticas de uso.

---

## Riscos / Gotchas

- **Enter duplo (selecionar + enviar):** mitigado pela ordem do `handleKeyDown` (menu tratado antes do envio). Maior ponto de risco.
- **`/` legítimo no texto** (URLs, "e/ou"): a regex exige início-de-linha ou espaço antes da `/`.
- **Branches condicionais do input:** montar o menu só no branch normal (não em bloqueado/preview/gravação).
- **Keepalive de realtime** (`use-realtime-keepalive` em `authenticated-shell.tsx`) é desacoplado — não adicionar listeners globais de `keydown`/`visibilitychange` no `chat-view`; manter os listeners locais ao componente do menu e limpá-los.
- **Mobile:** teclado virtual + dropdown pra cima podem sobrepor; `max-h` + scroll e teste no `ChatView` mobile.
