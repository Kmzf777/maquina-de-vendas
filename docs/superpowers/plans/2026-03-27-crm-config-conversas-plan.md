# Implementation Plan: CRM /config e /conversas

**Spec:** `docs/superpowers/specs/2026-03-27-crm-config-conversas-design.md`
**Date:** 2026-03-27

---

## Step 1: Database — Criar tabelas tags e lead_tags

**Arquivo:** `backend-evolution/migrations/002_tags.sql`

```sql
CREATE TABLE IF NOT EXISTS tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  color TEXT NOT NULL DEFAULT '#8b5cf6',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lead_tags (
  lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
  tag_id UUID REFERENCES tags(id) ON DELETE CASCADE,
  PRIMARY KEY (lead_id, tag_id)
);
```

Executar no Supabase SQL Editor ou via migration.

**Verificação:** Confirmar que as tabelas existem no Supabase.

---

## Step 2: Types e Constants — Atualizar tipos TypeScript

**Arquivo:** `crm/src/lib/types.ts`

Adicionar:
```typescript
export interface Tag {
  id: string;
  name: string;
  color: string;
  created_at: string;
}

export interface EvolutionChat {
  id: string;
  remoteJid: string;
  pushName: string | null;
  profilePicUrl: string | null;
  lastMessage: {
    content: string;
    timestamp: number;
  } | null;
  unreadCount: number;
}

export interface EvolutionMessage {
  key: {
    remoteJid: string;
    fromMe: boolean;
    id: string;
  };
  message: {
    conversation?: string;
    imageMessage?: { caption?: string; url?: string };
    audioMessage?: { url?: string };
    documentMessage?: { fileName?: string; url?: string };
  };
  messageTimestamp: number;
  pushName?: string;
}
```

**Arquivo:** `crm/src/lib/constants.ts`

Adicionar:
```typescript
export const CONVERSATION_TABS = [
  { key: "todos", label: "Todos" },
  { key: "atacado", label: "Atacado" },
  { key: "private_label", label: "Private Label" },
  { key: "exportacao", label: "Exportação" },
  { key: "consumo", label: "Consumo" },
  { key: "pessoal", label: "Pessoal" },
] as const;
```

**Verificação:** `npm run build` sem erros de tipo.

---

## Step 3: API Routes — Tags CRUD

**Arquivos novos:**
- `crm/src/app/api/tags/route.ts` — GET (list) + POST (create)
- `crm/src/app/api/tags/[id]/route.ts` — PUT (edit) + DELETE
- `crm/src/app/api/leads/[id]/tags/route.ts` — POST (add/remove tag de lead)

Padrão de autenticação: copiar de `crm/src/app/api/chat/send/route.ts` — criar supabase server client, verificar auth com anon key, operar com service role key.

**Verificação:** Testar via curl/Postman as rotas de tags.

---

## Step 4: API Routes — Evolution API Proxy

**Arquivos novos:**
- `crm/src/app/api/evolution/status/route.ts` — GET connectionState
- `crm/src/app/api/evolution/connect/route.ts` — POST cria instância + retorna QR
- `crm/src/app/api/evolution/disconnect/route.ts` — POST desconecta
- `crm/src/app/api/evolution/chats/route.ts` — GET lista chats
- `crm/src/app/api/evolution/messages/[phone]/route.ts` — GET mensagens de um chat
- `crm/src/app/api/evolution/send/route.ts` — POST envia msg + auto-cria lead

**Cada rota segue o padrão:**
1. Verificar auth (Supabase)
2. Derivar nome da instância: `seller-{user.id}`
3. Chamar Evolution API com apikey do env
4. Retornar resultado

**Endpoints da Evolution API usados:**
- `GET /instance/connectionState/{instance}` — status
- `POST /instance/create` — criar instância
- `GET /instance/connect/{instance}` — gerar QR code
- `DELETE /instance/logout/{instance}` — desconectar
- `POST /chat/findChats/{instance}` — listar chats
- `POST /chat/findMessages/{instance}` — buscar mensagens
- `POST /message/sendText/{instance}` — enviar texto

**Variáveis de ambiente necessárias (já existem no .env):**
- `EVOLUTION_API_URL`
- `EVOLUTION_API_KEY`

**Verificação:** Testar cada rota via curl. Verificar que QR code retorna base64.

---

## Step 5: Página /config — Refatorar com Abas

**Arquivo:** `crm/src/app/(authenticated)/config/page.tsx` — reescrever

Estrutura:
- State `activeTab`: "whatsapp" | "tags" | "senha"
- 3 abas no topo com estilo de tab bar
- Renderiza componente correspondente

**Componentes novos:**
- `crm/src/components/config/whatsapp-tab.tsx`
  - Chama `GET /api/evolution/status` no mount
  - Se desconectado: botão "Conectar" → `POST /api/evolution/connect` → mostra QR code
  - Polling 3s em `/api/evolution/status` enquanto QR visível
  - Se conectado: badge verde, número, botão "Desconectar"

- `crm/src/components/config/tags-tab.tsx`
  - Lista tags via `GET /api/tags`
  - Form inline para criar nova tag (nome + color input)
  - Botões editar/excluir em cada tag
  - Color picker simples (input type="color")

- `crm/src/components/config/password-tab.tsx`
  - Extrair código atual de config/page.tsx para este componente
  - Sem alterações na lógica

**Verificação:** Navegar para /config, verificar que as 3 abas funcionam. Conectar QR code. CRUD de tags.

---

## Step 6: Sidebar — Adicionar link Conversas

**Arquivo:** `crm/src/components/sidebar.tsx`

Adicionar item no NAV_ITEMS entre "Vendas" e "Campanhas":
```typescript
{ href: "/conversas", label: "Conversas" },
```

**Verificação:** Sidebar mostra "Conversas" e navega corretamente.

---

## Step 7: Página /conversas — Layout 3 Painéis

**Arquivo novo:** `crm/src/app/(authenticated)/conversas/page.tsx`

**IMPORTANTE:** A página /conversas precisa ocupar 100% da viewport sem scroll da página. O layout pai em `(authenticated)/layout.tsx` aplica `p-6` no main — esta página precisa override para não ter padding e ocupar a tela toda. Usar classes para remover padding ou ajustar o layout.

Estrutura da página:
- Container flex com h-full (3 painéis)
- State: `selectedChat`, `selectedLead`, `activeTab`

**Componentes novos:**

### `crm/src/components/conversas/chat-list.tsx`
- Props: `chats`, `leads`, `activeTab`, `selectedChat`, `onSelectChat`, `onTabChange`
- Barra de busca no topo
- Tabs de filtro (Todos, Atacado, PL, Exportação, Consumo, Pessoal)
- Lista de conversas com avatar (inicial), nome, preview, horário, badge não lidas
- Cruza chats (Evolution) com leads (Supabase) para filtrar por stage
- Chats sem lead associado → aba "Pessoal"

### `crm/src/components/conversas/chat-view.tsx`
- Props: `phone`, `instanceName`
- Busca mensagens via `GET /api/evolution/messages/{phone}`
- Bolhas: enviadas (direita, roxo) / recebidas (esquerda, cinza escuro)
- Renderiza texto, imagens inline, audio player, documentos como link
- Input de mensagem no footer → `POST /api/evolution/send`
- Enter envia, Shift+Enter nova linha
- Auto-scroll para última mensagem

### `crm/src/components/conversas/contact-detail.tsx`
- Props: `phone`, `lead`, `tags`, `onTagAdd`, `onTagRemove`, `onCreateLead`
- Se é lead: nome, empresa, phone, stage, seller_stage, tags (chips), data
- Se não é lead: push_name, phone, botão "Criar Lead"
- Seção tags: chips coloridos + dropdown "+ tag"
- Ações: mudar seller_stage (dropdown)

**Verificação:** Navegar para /conversas. Verificar que lista carrega chats. Selecionar conversa mostra mensagens. Enviar mensagem. Painel de detalhes mostra info correta.

---

## Step 8: Ajustar Layout para /conversas full-screen

**Arquivo:** `crm/src/app/(authenticated)/layout.tsx`

A página /conversas precisa de tratamento especial — sem padding, altura 100vh. Opções:
1. Condicional no layout baseado no pathname (usar `usePathname`)
2. A página /conversas usar margin negativo para compensar o padding

Abordagem recomendada: tornar o layout client component (já usa Sidebar que é client), checar pathname, remover padding se `/conversas`.

**Verificação:** /conversas ocupa tela toda. Outras páginas mantêm padding normal.

---

## Ordem de Execução

1. Step 1 (DB) — independente
2. Step 2 (Types) — independente
3. Step 3 (Tags API) — depende de Step 1 e 2
4. Step 4 (Evolution API) — depende de Step 2
5. Step 5 (/config page) — depende de Step 3 e 4
6. Step 6 (Sidebar) — independente
7. Step 7 (/conversas page) — depende de Step 4 e 6
8. Step 8 (Layout adjust) — depende de Step 7

Steps 1, 2, 6 podem ser feitos em paralelo.
Steps 3 e 4 podem ser feitos em paralelo (após 1 e 2).
Steps 5 e 7 podem ser feitos em paralelo (após 3 e 4).
