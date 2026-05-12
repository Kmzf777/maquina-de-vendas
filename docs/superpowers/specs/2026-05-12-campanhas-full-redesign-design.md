# Campanhas — Redesign Completo do Painel de Disparos

**Data:** 2026-05-12  
**Status:** Aprovado  
**Rota:** `/campanhas` (mantida)

---

## Contexto

O painel de disparos atual apresenta problemas críticos de usabilidade:
- Sem opção de disparo sem Agente de AI (função mais utilizada)
- Template exibe apenas nome técnico, sem prévia, sem categoria Marketing/Utility
- Filtro de leads usa estágios do agente AI, ignorando funis/deals (maioria dos leads nunca passou por AI)
- Impossível saber quais leads foram disparados e quais falharam
- Criação de template sem fluxo no CRM
- Navegação confunde Disparos, Cadências e Templates sem estrutura clara

---

## 1. Estrutura de Navegação

### Página `/campanhas`

3 abas client-side controladas por query string `?tab=`:

```
[ Disparos ]  [ Cadências ]  [ Templates ]
```

- `?tab=disparos` — padrão
- `?tab=cadencias` — mantém comportamento atual
- `?tab=templates` — novo

### Sub-página `/campanhas/disparos/[id]`

Página dedicada de detalhe de disparo. Acessada ao clicar em qualquer broadcast card.

---

## 2. Aba Disparos

### Lista de Broadcasts

- Header com botão `+ Novo Disparo` → abre `CreateBroadcastModal`
- Cards com: nome, status badge colorido, barra de progresso (enviado/entregue/falhou/pendente), data de criação
- Clicar no card → navega para `/campanhas/disparos/[id]`

### Status badges

| Status | Cor |
|---|---|
| Rascunho | Cinza |
| Agendado | Azul |
| Rodando | Verde pulsante |
| Pausado | Amarelo |
| Concluído | Verde |
| Falhou | Vermelho |

---

## 3. Wizard de Criação de Disparo

Modal de criação com 4 etapas. Barra de progresso no topo.

```
[1. Configuração] ── [2. Template] ── [3. Leads] ── [4. Revisão]
```

### Etapa 1 — Configuração

- **Nome do disparo** — campo texto, obrigatório
- **Canal** — dropdown com canais Meta Cloud ativos
- **Agente de AI** — radio buttons:
  - ● Sem Agente *(padrão)*
  - ○ Usar agente do canal
  - ○ Escolher agente específico → dropdown aparece condicionalmente
- **Intervalo de envio** — dois campos numéricos (mín/máx em segundos) com texto: *"Intervalo entre mensagens para evitar bloqueio do WhatsApp"*

### Etapa 2 — Template

- Dropdown de busca por nome de template (busca client-side nos templates aprovados do canal)
- Botão `+ Criar novo template` ao lado → abre `CreateTemplateModal` por cima do wizard; ao fechar com template criado e aprovado, seleciona automaticamente
- **Card de prévia** ao selecionar template:
  - Badge de categoria: **Marketing** (laranja) / **Utility** (azul) / **Authentication** (roxo)
  - Texto completo do body renderizado
  - Variáveis auto-resolvidas do lead (ex: `first_name`) → verde com ícone ⚡, não editáveis
  - Variáveis de preenchimento manual → amarelo com campo editável inline dentro do card
  - Botões do template exibidos como chips não-clicáveis
- Opção **"Salvar como preset"** → salva `template_variables` com nome amigável via `/api/template-presets`
- Dropdown **"Carregar preset"** → preenche variáveis automaticamente

### Etapa 3 — Leads

- Contador em tempo real: *"X leads selecionados"*
- Duas abas: **Do CRM** | **Importar CSV**

**Aba Do CRM:**

Painel de filtros + tabela de leads.

Filtros disponíveis:

| Filtro | Tipo | Fonte de dados |
|---|---|---|
| Funil | Dropdown | `/api/pipelines` |
| Etapa do deal | Dropdown (carrega ao selecionar funil) | `/api/pipelines/[id]/stages` |
| Categoria do deal | Multi-select | DEAL_CATEGORIES (constante) |
| Tags | Multi-select | `/api/tags` |
| Sem deal | Toggle | Leads sem deals associados |
| Data de criação | Date range picker | `leads.created_at` |
| Busca | Texto | name, phone, company, nome_fantasia |

- Botão `Aplicar filtros` → atualiza tabela
- Checkbox por lead + `Selecionar todos os X leads filtrados`
- Tabela: nome, empresa, telefone, funil/etapa atual, tags

**Aba CSV:**
- Mantém comportamento atual (upload de arquivo)

### Etapa 4 — Revisão

- Resumo: nome, canal, agente, template, variáveis, quantidade de leads
- Botão `Criar Disparo` → cria broadcast com status `draft`
- Após criação: fecha modal, navega para a lista de disparos, card novo aparece com status Rascunho e botão `▶ Iniciar`

---

## 4. Página de Detalhe `/campanhas/disparos/[id]`

### Header

- Nome do disparo + badge de status
- Botões contextuais por status:
  - **Rascunho:** `▶ Iniciar` | `Excluir`
  - **Rodando:** `⏸ Pausar`
  - **Pausado:** `▶ Retomar` | `Excluir`
  - **Concluído/Falhou:** `↩ Retentar Falhas` (se houver leads com falha)

### Cards de métricas

```
[ Total ]  [ Enviado ]  [ Entregue ]  [ Falhou ]  [ Pendente ]
```

### Tabela de leads

Abas de filtro rápido:
```
[ Todos (N) ]  [ Enviado (N) ]  [ Entregue (N) ]  [ Falhou (N) ]  [ Pendente (N) ]
```

Colunas: Nome | Telefone | Status | Enviado em | Erro

### Botão "Retentar Falhas"

- Visível sempre que existem leads com status `failed`
- Abre o `CreateBroadcastModal` pré-preenchido:
  - Mesmo canal, template e variáveis
  - Etapa 3 já com os leads falhos selecionados
  - Usuário só revisa e confirma

---

## 5. Aba Templates

### Lista de Templates

Tabela com colunas: Nome amigável | Nome técnico | Categoria | Status | Idioma | Criado em

| Status | Badge |
|---|---|
| Aprovado | Verde |
| Pendente aprovação | Amarelo |
| Rejeitado | Vermelho com botão "Ver motivo" |

- Botão `+ Novo Template` → abre `CreateTemplateModal`

### Modal de Criação de Template (`CreateTemplateModal`)

Acessível de dois pontos: aba Templates e wizard de disparo (Etapa 2).

Campos:
1. **Nome técnico** — slug sem espaços, validação em tempo real (só letras minúsculas, números e underscores)
2. **Nome amigável** — exibição no CRM
3. **Categoria** — radio: `● Marketing` / `○ Utility`
4. **Idioma** — dropdown, padrão `pt_BR`
5. **Corpo da mensagem** — textarea com instrução inline: *"Use {{nome_variavel}} para variáveis. Ex: Olá, {{first_name}}!"*
   - Preview ao vivo renderizado abaixo do textarea
   - Variáveis detectadas automaticamente listadas como chips de confirmação
6. **Botões** (opcional) — até 3 botões de resposta rápida, adicionar/remover dinamicamente

Ao submeter:
- POST para Meta API via `/api/templates` (backend encaminha para Meta)
- Template aparece na lista com status **Pendente aprovação**
- Status atualiza via polling ou webhook quando Meta aprovar/rejeitar
- Se aberto a partir do wizard, ao fechar seleciona o template automaticamente se aprovado

---

## 6. Impacto em Componentes Existentes

| Componente atual | Ação |
|---|---|
| `create-broadcast-modal.tsx` | Reescrever completamente — novo wizard 4 etapas |
| `broadcast-list.tsx` | Atualizar cards para navegar para sub-página |
| `broadcast-card.tsx` | Adicionar navegação, remover ações que vão para detalhe |
| `campaigns-tabs.tsx` | Adicionar aba Templates, renomear estrutura |
| `lead-selector.tsx` | Reescrever filtros — adicionar funil, etapa, categoria, data, sem deal |
| `quick-send-modal.tsx` | Mantém sem alteração |
| `campaigns-dashboard.tsx` | Mantém sem alteração |
| Novo: `broadcast-detail-page.tsx` | Criar — sub-página `/campanhas/disparos/[id]` |
| Novo: `create-template-modal.tsx` | Criar — modal de criação de template |
| Novo: `templates-tab.tsx` | Criar — lista de templates com status |

---

## 7. Impacto em API / Backend

### Novas rotas necessárias

| Rota | Método | Propósito |
|---|---|---|
| `/api/pipelines` | GET | Listar funis para filtro de leads |
| `/api/pipelines/[id]/stages` | GET | Listar etapas de um funil |
| `/api/templates` | GET/POST | Listar e criar templates via Meta API |
| `/api/templates/[id]/status` | GET | Consultar status de aprovação |

### Rotas existentes que precisam de atualização

| Rota | Mudança |
|---|---|
| `/api/broadcasts/[id]/leads` | Adicionar filtros por funil, etapa, categoria, tags, data, sem_deal |
| `/api/leads` | Suportar filtro `pipeline_id`, `stage_id`, `deal_category`, `no_deal`, `created_after`, `created_before` |

---

## 8. Decisões de Arquitetura

- **Modais para criação** (wizard, template) — leves, focados, sem URL própria
- **Sub-página para detalhe** — `/campanhas/disparos/[id]` suporta listas grandes de leads, URL compartilhável, browser back funciona
- **Abas por query string** — `?tab=templates` permite deep link direto
- **"Sem Agente" como padrão** — radio button pré-selecionado, elimina o bug atual onde todo disparo força um agente
- **Variáveis auto-resolvidas** — `first_name`, `lead_name`, `phone` resolvem do lead no backend; exibir como não-editáveis no frontend para evitar confusão
- **Polling de status de template** — consultar `/api/templates/[id]/status` a cada 30s enquanto status for `pending`
