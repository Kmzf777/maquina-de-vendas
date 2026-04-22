# ValerIA CRM Kanban — Design Spec

**Data:** 2026-03-26
**Status:** Aprovado

---

## Visao Geral

CRM com Kanban duplo para o vendedor da Cafe Canastra. O agente IA (ValerIA) qualifica leads automaticamente via WhatsApp. Quando o lead esta pronto, e encaminhado ao vendedor que continua a conversa pelo CRM. O CRM le tudo de um unico Supabase, independente do canal de origem (Evolution API ou Meta Cloud API).

## Stack

- **Frontend:** Next.js 14 (App Router) + Tailwind CSS
- **Deploy:** Vercel
- **Banco:** Supabase (Postgres + Realtime)
- **Auth:** Supabase Auth (email/senha)
- **Canais:** Evolution API + Meta Cloud API (campo `channel` no lead)

---

## Arquitetura

```
┌─────────────────────────────────────────────────┐
│              Vercel (Next.js)                    │
│                                                  │
│  /dashboard ──── Metricas & Funil                │
│  /qualificacao ─ Kanban agente (read-only)       │
│  /vendas ─────── Kanban vendedor (ativo)         │
│  /campanhas ──── Gestao de campanhas             │
│  /config ─────── Configuracoes                   │
│                                                  │
│  /api/chat/send ── Proxy → Evolution/Meta API    │
│                                                  │
└──────────┬──────────────────┬────────────────────┘
           │                  │
    Supabase Client      API Routes
    (browser, realtime)  (server-side)
           │                  │
    ┌──────▼──────┐    ┌──────▼───────────┐
    │  Supabase   │    │  Evolution API   │
    │  DB + Real  │    │  Meta Cloud API  │
    │  time       │    │  (por channel)   │
    └─────────────┘    └──────────────────┘
```

O backend FastAPI continua rodando normalmente (webhooks, agente, buffer). O CRM le direto do Supabase com Realtime subscriptions. Quando o agente salva uma mensagem ou muda um stage, o CRM atualiza instantaneamente.

---

## Mudancas no Banco de Dados

Adicionar a tabela `leads`:

```sql
ALTER TABLE leads ADD COLUMN seller_stage text DEFAULT 'novo';
-- valores: novo, em_contato, negociacao, fechado, perdido

ALTER TABLE leads ADD COLUMN assigned_to uuid REFERENCES auth.users(id);
-- id do vendedor (Supabase Auth)

ALTER TABLE leads ADD COLUMN human_control boolean DEFAULT false;
-- true = agente parou, vendedor conversa

ALTER TABLE leads ADD COLUMN channel text DEFAULT 'evolution';
-- valores: evolution, meta
```

**Nota:** `human_control` e setado para `true` quando o agente executa `encaminhar_humano`. O campo `seller_stage` e controlado exclusivamente pelo vendedor via drag & drop no Kanban.

---

## Paginas

### 1. Dashboard (`/dashboard`)

#### KPIs (cards no topo)

| Metrica | Calculo |
|---------|---------|
| Leads hoje | `created_at >= hoje` |
| Aguardando vendedor | `human_control=true AND seller_stage='novo'` |
| Tempo medio de qualificacao | Media de `encaminhar_humano timestamp - created_at` |
| Taxa de conversao | `seller_stage='fechado' / total com human_control=true` |

#### Funil Visual

Barras horizontais mostrando volume por stage do agente:

```
Secretaria ████████████████████ 120
Atacado    ██████████████       85
Priv Label ████████             45
Exportacao ███                  18
Consumo    ██                   12
                    ↓
Convertidos ███████             52
```

#### Metricas de Campanha

Tabela por campanha:
- Nome, status, data de inicio
- Enviados / Total (barra de progresso)
- Taxa de resposta (replied / sent)
- Taxa de qualificacao (encaminhados / replied)

#### Filtros

- Periodo: hoje, 7 dias, 30 dias, custom
- Por campanha
- Por stage

---

### 2. Kanban Qualificacao (`/qualificacao`)

**Read-only.** Mostra o trabalho do agente em tempo real.

#### Colunas

| Secretaria | Atacado | Private Label | Exportacao | Consumo |

#### Card do lead

```
┌─────────────────────────┐
│ Joao da Padaria         │
│ (34) 99999-9999         │
│ Padaria Central         │
│                         │
│ "me manda a tabela..."  │
│ ha 5 min                │
└─────────────────────────┘
```

Campos: nome, telefone, empresa, ultima mensagem (truncada), tempo no stage.

#### Chat (somente leitura)

Click no card abre painel lateral com historico completo da conversa do agente. Sem input de texto. Atualiza em tempo real via Supabase Realtime na tabela `messages`.

---

### 3. Kanban Vendas (`/vendas`)

**Ativo.** Funil do vendedor com drag & drop.

#### Colunas

| Novo | Em Contato | Negociacao | Fechado | Perdido |

#### Mecanica

- Leads chegam na coluna "Novo" automaticamente quando agente executa `encaminhar_humano` (seta `human_control=true`, `seller_stage='novo'`)
- Badge piscando em leads novos nao lidos
- Drag & drop entre colunas atualiza `seller_stage` no Supabase
- Contador de leads por coluna no header

#### Card do lead

```
┌─────────────────────────┐
│ 🔴 Joao da Padaria      │
│ Atacado · ha 2h         │
│                         │
│ "quanto custa o kg?"    │
│ 3 nao lidas             │
└─────────────────────────┘
```

Campos: nome, stage de origem do agente, tempo parado, ultima mensagem, contador de nao lidas.

#### Chat (ativo)

Click no card abre chat completo:

```
┌──────────────────────────────────────────────┐
│  ← Voltar    Joao da Padaria    [Dados]      │
│              Atacado · Em Contato             │
├──────────────────────────────────────────────┤
│                                              │
│  [Agente] Ola Joao, tudo bem?        14:01   │
│                                              │
│           Oi, tudo sim!       [Lead] 14:02   │
│                                              │
│  [Agente] Qual seu interesse?        14:03   │
│                                              │
│  ── Vendedor assumiu o chat ──               │
│                                              │
│  [Vendedor] Joao, aqui e o Pedro...  14:30   │
│                                              │
│           Me manda a tabela  [Lead] 14:31   │
│                                              │
├──────────────────────────────────────────────┤
│  [  Digite uma mensagem...        ] [Enviar] │
└──────────────────────────────────────────────┘
```

- Historico completo: fase do agente + fase do vendedor
- Divider visual marcando onde o vendedor comecou
- Mensagens do agente com badge/cor diferente das do vendedor
- Input de texto envia via Next.js API route → Evolution API ou Meta Cloud API (baseado no `channel` do lead)
- Mensagens novas do lead em tempo real (Supabase Realtime)
- Indicador de nao lidas no card do Kanban

#### Sidebar de dados

Painel lateral com:
- Nome, telefone, empresa
- Stage do agente, stage do vendedor
- Campanha de origem
- Canal (Evolution / Meta)
- Data de criacao, ultima mensagem
- Botao "Marcar como perdido"

---

### 4. Campanhas (`/campanhas`)

Interface visual para o sistema de campanhas existente no backend.

#### Listagem

Tabela com: nome, status (badge colorido), progresso (barra), taxa de resposta.

#### Criar Campanha

Formulario:
- Nome da campanha
- Template (dropdown dos templates aprovados pela Meta)
- Intervalo entre envios (min/max em segundos)
- Upload de CSV com leads

#### Controles

- Iniciar / Pausar (chama endpoints FastAPI existentes)
- Progresso em tempo real via Supabase Realtime nos contadores

#### Sem mudancas no backend

Tudo ja existe nas rotas FastAPI. Next.js API routes fazem proxy.

---

### 5. Configuracoes (`/config`)

- Perfil do vendedor (nome, email, senha)
- Buffer on/off (endpoint existente `/api/buffer`)
- Notificacoes (som/badge quando lead novo chega no Kanban vendas)

---

## Navegacao

```
Sidebar fixa:
├── Dashboard
├── Qualificacao (Kanban agente)
├── Vendas (Kanban vendedor)
├── Campanhas
└── Configuracoes
```

---

## Real-time (Supabase Realtime)

| Subscription | Onde usa |
|---|---|
| `leads` (INSERT/UPDATE) | Kanban qualificacao, Kanban vendas, Dashboard KPIs |
| `messages` (INSERT) | Chat read-only, Chat ativo |
| `campaigns` (UPDATE) | Campanhas progresso, Dashboard metricas |

---

## Autenticacao

- Supabase Auth com email/senha
- 1 vendedor por agora, sem roles
- Row Level Security (RLS) no Supabase para proteger dados
- Session gerenciada pelo Supabase client no Next.js

---

## Roteamento de Mensagens (Chat Vendedor)

Quando o vendedor envia mensagem:

```
1. Frontend envia POST /api/chat/send { leadId, text }
2. API route busca lead no Supabase → pega phone + channel
3. Se channel = "evolution":
   → POST Evolution API /message/sendText
4. Se channel = "meta":
   → POST graph.facebook.com/.../messages
5. Salva mensagem na tabela messages (role='assistant', vendedor=true)
6. Supabase Realtime notifica o chat
```

**Nota:** mensagens do vendedor sao salvas com um campo adicional `sent_by` para diferenciar de mensagens do agente.

Mudanca na tabela `messages`:

```sql
ALTER TABLE messages ADD COLUMN sent_by text DEFAULT 'agent';
-- valores: agent, seller
```

---

## Responsividade

- Desktop-first (vendedor trabalha no computador)
- Chat funcional no mobile para emergencias
- Kanban com scroll horizontal no mobile

---

## Fora de escopo (por agora)

- Multiplos vendedores / roles / distribuicao
- Envio de midia pelo chat do vendedor (somente texto)
- Relatorios exportaveis (PDF/Excel)
- Integracao com outros CRMs
- App mobile nativo
