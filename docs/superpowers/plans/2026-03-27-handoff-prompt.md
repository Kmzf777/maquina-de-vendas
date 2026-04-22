# Prompt de Handoff — Implementação CRM /config e /conversas

Você vai implementar duas novas páginas no CRM ValerIA: **/config** (refatorada com abas) e **/conversas** (WhatsApp Web clone). Tudo está documentado — siga os docs ao pé da letra.

---

## Documentos obrigatórios — LEIA ANTES DE QUALQUER CÓDIGO

1. **Spec completo:** `docs/superpowers/specs/2026-03-27-crm-config-conversas-design.md`
2. **Plano de implementação:** `docs/superpowers/plans/2026-03-27-crm-config-conversas-plan.md`
3. **IMPORTANTE — Next.js:** Leia `crm/AGENTS.md` e `crm/CLAUDE.md`. Esta versão do Next.js (16.2.1) tem breaking changes. Antes de escrever qualquer código, leia os guides em `crm/node_modules/next/dist/docs/` para entender as APIs atuais. Não confie no seu treinamento sobre Next.js — as APIs podem ter mudado.

---

## Contexto do Projeto

ValerIA é um CRM para vendedores de café especial (Café Canastra). O sistema tem:

- **Backend Python (FastAPI)** em `backend-evolution/` — agente IA que conversa com leads via WhatsApp (Evolution API + OpenAI)
- **Frontend Next.js 16.2.1** em `crm/` — CRM com dashboard, qualificação (kanban), vendas, campanhas
- **Supabase** como banco de dados e auth
- **Evolution API v2** como provider de WhatsApp
- **Tailwind CSS** para estilização (sem bibliotecas UI externas)

O vendedor precisa:
1. Conectar seu WhatsApp pessoal via QR code na página /config
2. Gerenciar tags personalizadas em /config
3. Ver TODAS as conversas do WhatsApp dele (leads + pessoais) na página /conversas, estilo WhatsApp Web
4. Atribuir tags e criar leads a partir de conversas

---

## O que implementar (8 steps, em ordem)

### Step 1: Criar tabelas no Supabase
- Criar arquivo `backend-evolution/migrations/002_tags.sql`
- Tabela `tags` (id uuid PK default gen_random_uuid(), name text NOT NULL, color text NOT NULL default '#8b5cf6', created_at timestamptz default now())
- Tabela `lead_tags` (lead_id uuid FK→leads.id ON DELETE CASCADE, tag_id uuid FK→tags.id ON DELETE CASCADE, PK composta (lead_id, tag_id))

### Step 2: Atualizar types e constants
- Em `crm/src/lib/types.ts` — adicionar interfaces: Tag, EvolutionChat, EvolutionMessage (ver plano para detalhes dos campos)
- Em `crm/src/lib/constants.ts` — adicionar CONVERSATION_TABS: Todos, Atacado, Private Label, Exportação, Consumo, Pessoal

### Step 3: API Routes — Tags CRUD
Criar:
- `crm/src/app/api/tags/route.ts` — GET (listar todas) + POST (criar nova tag com name e color)
- `crm/src/app/api/tags/[id]/route.ts` — PUT (editar tag) + DELETE (excluir tag + cascade)
- `crm/src/app/api/leads/[id]/tags/route.ts` — POST com body `{ tagIds: string[] }` para sincronizar tags de um lead

**Padrão de auth:** Copiar o padrão de `crm/src/app/api/chat/send/route.ts`:
- Criar supabase client com service role key para operações
- Criar supabase client com anon key para verificar auth (getUser)
- Retornar 401 se não autenticado

### Step 4: API Routes — Evolution API Proxy
Criar 6 rotas que fazem proxy para a Evolution API. O frontend NUNCA fala direto com a Evolution API.

- `crm/src/app/api/evolution/status/route.ts` — GET
  - Chama `GET {EVOLUTION_API_URL}/instance/connectionState/seller-{user.id}` com header `apikey`
  - Retorna `{ connected: boolean, number?: string }`

- `crm/src/app/api/evolution/connect/route.ts` — POST
  - Tenta conectar: `GET {EVOLUTION_API_URL}/instance/connect/seller-{user.id}`
  - Se instância não existe (404), cria com `POST {EVOLUTION_API_URL}/instance/create` body `{ instanceName: "seller-{user.id}", qrcode: true, integration: "WHATSAPP-BAILEYS" }`
  - Retorna `{ qrcode: string }` (base64)

- `crm/src/app/api/evolution/disconnect/route.ts` — POST
  - Chama `DELETE {EVOLUTION_API_URL}/instance/logout/seller-{user.id}`

- `crm/src/app/api/evolution/chats/route.ts` — GET
  - Chama `POST {EVOLUTION_API_URL}/chat/findChats/seller-{user.id}`
  - Retorna lista de chats

- `crm/src/app/api/evolution/messages/[phone]/route.ts` — GET
  - Chama `POST {EVOLUTION_API_URL}/chat/findMessages/seller-{user.id}` com body `{ where: { key: { remoteJid: "{phone}@s.whatsapp.net" } } }`
  - Retorna mensagens

- `crm/src/app/api/evolution/send/route.ts` — POST
  - Body: `{ phone: string, text: string }`
  - Envia via `POST {EVOLUTION_API_URL}/message/sendText/seller-{user.id}` body `{ number: phone, text }`
  - **Auto-criação de lead:** Verifica se existe lead com esse phone no Supabase. Se não existe, cria com `{ phone, name: null, status: "active", stage: "secretaria", seller_stage: "novo", human_control: true, channel: "evolution" }`
  - Retorna `{ ok: true, lead?: Lead }`

Variáveis de ambiente (já existem no .env):
- `EVOLUTION_API_URL`
- `EVOLUTION_API_KEY`

### Step 5: Página /config — Refatorar com 3 abas
Reescrever `crm/src/app/(authenticated)/config/page.tsx` com sistema de abas.

Criar 3 componentes:

**`crm/src/components/config/whatsapp-tab.tsx`:**
- No mount: `GET /api/evolution/status`
- Se desconectado: botão "Conectar" → `POST /api/evolution/connect` → renderiza QR code (img src base64)
- Polling: `setInterval` 3s chamando `/api/evolution/status` enquanto QR visível
- Timeout 60s: mostra "QR expirado" + botão "Gerar novo"
- Se conectado: badge verde "Conectado", número do telefone, botão "Desconectar"
- Desconectar: `POST /api/evolution/disconnect` → volta pro estado desconectado

**`crm/src/components/config/tags-tab.tsx`:**
- No mount: `GET /api/tags` para listar
- Cada tag: chip com cor + nome + botão editar (lápis) + botão excluir (lixeira)
- Botão "+ Nova Tag" abre form inline: input text nome + input type="color" + botão salvar
- Editar: transforma chip em form inline (mesmo layout)
- Excluir: confirm() antes de deletar
- `POST /api/tags` para criar, `PUT /api/tags/{id}` para editar, `DELETE /api/tags/{id}` para excluir

**`crm/src/components/config/password-tab.tsx`:**
- Extrair a lógica atual do config/page.tsx (form de troca de senha)
- Sem alterações na funcionalidade

### Step 6: Sidebar — Adicionar "Conversas"
Em `crm/src/components/sidebar.tsx`, adicionar no array NAV_ITEMS entre "Vendas" e "Campanhas":
```typescript
{ href: "/conversas", label: "Conversas" },
```

### Step 7: Página /conversas — 3 painéis WhatsApp Web
Criar `crm/src/app/(authenticated)/conversas/page.tsx`

**Layout:** flex container, h-screen, 3 painéis
- Theme escuro (bg-gray-950)

**State principal na page.tsx:**
- `chats: EvolutionChat[]` — lista de chats da Evolution
- `leads: Lead[]` — leads do Supabase (para cruzar com chats)
- `tags: Tag[]` — tags para o painel de detalhes
- `selectedPhone: string | null` — chat selecionado
- `activeTab: string` — aba de filtro ativa

**No mount:**
- `GET /api/evolution/chats` → seta chats
- Buscar leads do Supabase (client-side) → seta leads
- `GET /api/tags` → seta tags

**Componente `crm/src/components/conversas/chat-list.tsx`:**
- Largura: w-80 (320px)
- Barra de busca no topo
- Abas pill: Todos | Atacado | Private Label | Exportação | Consumo | Pessoal
- Lista de chats filtrada pela aba ativa:
  - Cruzar remoteJid do chat com phone do lead para saber o stage
  - Sem lead → "Pessoal"
  - "Todos" mostra tudo
- Cada item: avatar (inicial, cor por stage), nome (lead.name ou pushName), preview última msg, horário, badge não lidas
- Ordenar por timestamp da última mensagem (mais recente no topo)
- Click → seta selectedPhone

**Componente `crm/src/components/conversas/chat-view.tsx`:**
- flex-1 (ocupa espaço restante)
- Header: avatar + nome + telefone + tags como badges
- Ao receber phone: `GET /api/evolution/messages/{phone}`
- Bolhas: fromMe=true → direita (bg-violet-600), fromMe=false → esquerda (bg-gray-800)
- Extrair texto de: message.conversation || message.imageMessage?.caption || "[Mídia]"
- Imagens: renderizar inline com img tag
- Áudio: `<audio>` player
- Input: textarea com placeholder "Digitar mensagem..."
  - Enter → envia (POST /api/evolution/send com phone e text)
  - Shift+Enter → nova linha
- Auto-scroll para última mensagem

**Componente `crm/src/components/conversas/contact-detail.tsx`:**
- Largura: w-80 (320px)
- Se é lead (cruzar phone com leads):
  - Avatar grande + nome + telefone
  - Info: empresa, stage, seller_stage, criado em
  - Tags: chips coloridos + botão "+ tag" (dropdown com tags disponíveis)
  - Ações: dropdown para mudar seller_stage
- Se não é lead:
  - Avatar + pushName + telefone
  - Label "Contato pessoal"
  - Botão "Criar Lead" → POST /api/evolution/send cria automaticamente, ou chamar direto o Supabase
- Ao adicionar/remover tag: `POST /api/leads/{id}/tags`

### Step 8: Ajustar layout para /conversas full-screen
Em `crm/src/app/(authenticated)/layout.tsx`:
- Tornar client component ("use client")
- Usar `usePathname()` para detectar `/conversas`
- Se pathname === "/conversas": main sem padding, sem overflow-auto
- Demais páginas: mantém `p-6 overflow-auto` como hoje

---

## Referências de código existentes — USE COMO PADRÃO

| O que | Arquivo | Por que olhar |
|-------|---------|---------------|
| Auth em API route | `crm/src/app/api/chat/send/route.ts` | Padrão exato de auth com service role + anon key |
| Supabase browser client | `crm/src/lib/supabase/client.ts` | Como criar client no frontend |
| Supabase server client | `crm/src/lib/supabase/server.ts` | Como criar client em server components |
| Chat component | `crm/src/components/chat-active.tsx` | Referência de UI de chat (bolhas, input, envio) |
| Types | `crm/src/lib/types.ts` | Interfaces existentes |
| Constants | `crm/src/lib/constants.ts` | Padrão de stages e cores |
| Sidebar | `crm/src/components/sidebar.tsx` | Onde adicionar "Conversas" |
| Layout | `crm/src/app/(authenticated)/layout.tsx` | Layout que precisa ajustar |
| Config atual | `crm/src/app/(authenticated)/config/page.tsx` | Código de senha a extrair |
| WhatsApp client backend | `backend-evolution/app/whatsapp/client.py` | Referência dos endpoints Evolution API |

---

## Endpoints da Evolution API v2 (referência rápida)

Base URL: env `EVOLUTION_API_URL`. Header obrigatório: `apikey: {EVOLUTION_API_KEY}`.

| Ação | Método | Endpoint | Body |
|------|--------|----------|------|
| Status | GET | `/instance/connectionState/{instance}` | — |
| Criar instância | POST | `/instance/create` | `{ instanceName, qrcode: true, integration: "WHATSAPP-BAILEYS" }` |
| Conectar (QR) | GET | `/instance/connect/{instance}` | — |
| Desconectar | DELETE | `/instance/logout/{instance}` | — |
| Listar chats | POST | `/chat/findChats/{instance}` | `{}` |
| Buscar msgs | POST | `/chat/findMessages/{instance}` | `{ where: { key: { remoteJid: "55XX@s.whatsapp.net" } } }` |
| Enviar texto | POST | `/message/sendText/{instance}` | `{ number, text }` |

---

## Estilo visual

### /config (tema claro — igual resto do CRM)
- Background: bg-white, borders: border-gray-200
- Tabs: border-bottom style, tab ativa com cor roxa
- Cards: bg-white rounded-lg shadow-sm border
- Botões: bg-gray-900 text-white (primário), border border-gray-300 (secundário)

### /conversas (tema escuro — WhatsApp style)
- Background geral: bg-gray-950
- Painel esquerdo: bg-gray-900, border-r border-gray-800
- Painel central: bg-gray-950
- Painel direito: bg-gray-900, border-l border-gray-800
- Bolhas enviadas: bg-violet-600 text-white
- Bolhas recebidas: bg-gray-800 text-gray-100
- Input: bg-gray-800 text-white rounded-full
- Abas filtro: pills, ativa bg-violet-600, inativa text-gray-400
- Avatar: iniciais em círculo colorido (cor baseada no stage)

---

## Ordem de execução recomendada

```
Paralelo 1: Step 1 (DB) + Step 2 (Types) + Step 6 (Sidebar)
Paralelo 2: Step 3 (Tags API) + Step 4 (Evolution API)
Paralelo 3: Step 5 (/config) + Step 7 (/conversas)
Sequencial: Step 8 (Layout adjust)
```

Commite após cada step. Teste cada API route antes de construir o frontend que a consome.

---

## Checklist final

- [ ] Tabelas tags e lead_tags criadas no Supabase
- [ ] Types e constants atualizados
- [ ] 4 API routes de tags funcionando (GET, POST, PUT, DELETE + lead_tags)
- [ ] 6 API routes de Evolution funcionando (status, connect, disconnect, chats, messages, send)
- [ ] /config com 3 abas (WhatsApp, Tags, Senha) funcionando
- [ ] QR code aparece e polling detecta conexão
- [ ] CRUD de tags funcionando
- [ ] Sidebar com link "Conversas"
- [ ] /conversas carrega lista de chats da Evolution API
- [ ] Filtro por abas funciona (cruza chats com leads)
- [ ] Chat mostra mensagens e permite enviar
- [ ] Painel de detalhes mostra info do lead ou "Criar Lead"
- [ ] Auto-criação de lead ao enviar mensagem para número sem lead
- [ ] Tags podem ser adicionadas/removidas do painel de detalhes
- [ ] /conversas ocupa tela toda (sem padding do layout pai)
- [ ] Outras páginas mantêm layout normal
