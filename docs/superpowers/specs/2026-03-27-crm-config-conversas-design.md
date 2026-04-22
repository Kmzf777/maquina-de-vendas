# Design: CRM /config e /conversas

**Data:** 2026-03-27
**Escopo:** Página de configurações com conexão WhatsApp + gerenciamento de tags, e página de conversas estilo WhatsApp Web.

---

## Contexto

O CRM ValerIA atende 1 vendedor que precisa:
1. Conectar seu WhatsApp pessoal via QR code da Evolution API
2. Gerenciar tags personalizadas para classificar leads
3. Visualizar e responder todas as conversas do WhatsApp (leads + pessoais) numa interface estilo WhatsApp Web dentro do CRM

As instâncias do agente IA (Meta oficial + Evolution API) são gerenciadas no código — não passam pelo CRM.

---

## 1. Página /config — Abas Horizontais

Layout com 3 abas: **WhatsApp | Tags | Senha**

### 1.1 Aba WhatsApp

**Fluxo de conexão:**
1. Ao abrir, chama `GET /api/evolution/status` para verificar `connectionState`
2. Se **desconectado**: mostra botão "Conectar"
   - Clique chama `POST /api/evolution/connect`
   - Se instância não existe, cria via Evolution API (`POST /instance/create`)
   - Retorna QR code base64 → renderiza na tela
   - Polling a cada 3s em `/api/evolution/status` até conectar
   - Timeout de 60s → mostra botão "Gerar novo QR"
3. Se **conectado**: mostra status verde, número conectado, botão "Desconectar"
   - Desconectar chama `POST /api/evolution/disconnect`

**Detalhes da instância:**
- Nome da instância: `seller-{user_id}` (derivado do Supabase Auth)
- Webhook da instância configurado automaticamente na criação para receber events no backend

### 1.2 Aba Tags

- Lista de tags existentes com nome + cor (chip colorido)
- Botão "+ Nova Tag" → form inline (input nome + color picker)
- Cada tag tem botões editar (lápis) e excluir (lixeira)
- Confirmação ao excluir (remove de todos os leads associados)
- Tags salvas na tabela `tags` no Supabase

### 1.3 Aba Senha

- Mantém implementação atual (troca de senha via Supabase Auth)
- Sem alterações

---

## 2. Página /conversas — 3 Painéis

Layout de 3 painéis lado a lado, ocupando 100% da viewport (sem scroll vertical na página):
- **Esquerdo (~300px):** Lista de conversas
- **Central (flex):** Chat ativo
- **Direito (~320px):** Detalhes do contato

### 2.1 Painel Esquerdo — Lista de Conversas

**Dados:** Busca chats via `GET /api/evolution/chats`

**Abas de filtro:**
- Todos | Atacado | Private Label | Exportação | Consumo | Pessoal
- Filtro cruza número do chat com tabela `leads` no Supabase
- Se não tem lead associado → aparece na aba "Pessoal"
- Aba "Todos" mostra tudo

**Cada item da lista:**
- Avatar (inicial do nome, cor baseada no stage)
- Nome (push_name da Evolution, ou nome do lead se existir)
- Preview da última mensagem (truncada)
- Horário da última mensagem
- Badge de mensagens não lidas
- Ordenado por última mensagem (mais recente no topo)

**Busca:** Barra de busca no topo filtra por nome ou número

### 2.2 Painel Central — Chat

**Dados:** Ao selecionar conversa, busca mensagens via `GET /api/evolution/messages/[phone]`

**Layout de mensagens:**
- Bolhas: enviadas à direita (roxo/violeta), recebidas à esquerda (cinza escuro)
- Suporte a: texto, imagens (renderiza inline), áudio (player), documentos (link download)
- Horário em cada bolha
- Scroll infinito para mensagens antigas (paginação)

**Input de mensagem:**
- Campo de texto na parte inferior com botão enviar
- Envia via `POST /api/evolution/send`
- Enter para enviar, Shift+Enter para nova linha

**Extras:**
- Indicador de "digitando..." (se disponível via webhook presence)
- Auto-scroll para última mensagem ao abrir conversa

### 2.3 Painel Direito — Detalhes do Contato

**Se é lead (existe na tabela `leads`):**
- Avatar + nome + telefone
- Stage do agente (secretaria, atacado, etc.)
- Seller stage (novo, em_contato, negociacao, etc.)
- Empresa
- Data de criação
- Tags (chips coloridos) + botão "+ tag" (dropdown com tags de /config)
- Botão de ação: mudar stage/seller_stage (dropdown)

**Se não é lead:**
- Avatar + push_name + telefone
- Mensagem: "Contato pessoal"
- Botão "Criar Lead" (cria com status active, seller_stage novo)
- Após criar: painel atualiza para exibir campos de lead

**Auto-criação de lead:**
- Quando vendedor envia mensagem para número sem lead associado
- API `/api/evolution/send` verifica existência do lead
- Se não existe → cria lead (phone, push_name, status="active", seller_stage="novo")
- Painel direito atualiza automaticamente

---

## 3. API Routes (Next.js)

Todas as rotas de Evolution fazem **proxy autenticado** — o frontend nunca fala direto com a Evolution API. Chaves ficam server-side.

### 3.1 Evolution Proxy Routes

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/evolution/status` | Verifica connectionState da instância do vendedor |
| POST | `/api/evolution/connect` | Cria instância (se necessário) + retorna QR code base64 |
| POST | `/api/evolution/disconnect` | Desconecta instância |
| GET | `/api/evolution/chats` | Lista todos os chats da instância |
| GET | `/api/evolution/messages/[phone]` | Busca mensagens de um chat específico |
| POST | `/api/evolution/send` | Envia mensagem (text, image, audio, doc) + auto-cria lead se necessário |

**Autenticação:** Todas verificam sessão Supabase antes de executar.

**Instância:** Nome derivado do user_id: `seller-{user_id}`

### 3.2 Tags Routes

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/tags` | Lista tags do usuário |
| POST | `/api/tags` | Cria nova tag (name, color) |
| PUT | `/api/tags/[id]` | Edita tag |
| DELETE | `/api/tags/[id]` | Exclui tag + remove associações |

### 3.3 Lead Tags Route

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/leads/[id]/tags` | Adiciona/remove tags de um lead |

---

## 4. Banco de Dados — Novas Tabelas

### 4.1 Tabela `tags`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| id | uuid (PK) | ID da tag |
| name | text | Nome da tag |
| color | text | Cor hex (#8b5cf6) |
| created_at | timestamptz | Data de criação |

### 4.2 Tabela `lead_tags`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| lead_id | uuid (FK → leads.id) | |
| tag_id | uuid (FK → tags.id) | |
| PK | (lead_id, tag_id) | Composta |

**ON DELETE CASCADE** em ambas as foreign keys.

### 4.3 Alterações em tabelas existentes

Nenhuma alteração nas tabelas `leads`, `messages` ou `campaigns`.

---

## 5. Sidebar — Navegação

Adicionar item "Conversas" na sidebar existente, entre "Vendas" e "Campanhas":
- Ícone: chat/message icon
- Rota: `/conversas`

---

## 6. Decisões Técnicas

- **Conversas via Evolution API, não banco:** Mensagens não são persistidas no Supabase. Chats e mensagens são carregados sob demanda da Evolution API. Apenas dados de CRM (leads, tags) ficam no banco.
- **Proxy server-side:** Frontend chama API routes do Next.js que fazem proxy para a Evolution API. Nunca expõe chaves da Evolution ao client.
- **Instância por usuário:** Nome `seller-{user_id}` permite escalar para múltiplos vendedores no futuro sem mudança de arquitetura.
- **Auto-criação de lead:** Reduz fricção — vendedor não precisa criar lead manualmente, basta responder.
- **Polling para QR code:** Simples e confiável. 3s de intervalo é rápido o suficiente para UX fluida.
