# Melhorias no Sistema de Registro de Vendas — Design

**Data:** 2026-06-17
**Branch:** `worktree-feat+melhorias-registro-vendas` (worktree isolado)
**Status:** Aprovado pelo usuário (design e plano pré-aprovados; executar via subagents)

## Contexto

O sistema separa duas entidades:

- **Deal** (`deals`): card/oportunidade no funil Kanban (`/vendas`). Tem estágios, valor estimado, categoria.
- **Venda** (`sales`): registro de faturamento consumado. Alimenta o Painel de Vendas (`/painel-vendas`) e as métricas (faturamento, ticket médio, ciclo de recompra).

Uma venda **pode** estar vinculada a um deal hoje (opcional). Único ponto de registro atual: o "+" minúsculo na seção "Vendas" do perfil do contato em `/conversas`.

shadcn/ui já está instalado (`components.json`, estilo `radix-nova`, base `neutral`, `src/components/ui/*`), mas o sistema de vendas foi feito com Tailwind cru numa paleta quente própria (`#faf9f6` / `#dedbd6` / `#111111`).

## Objetivo

1. Toda venda passa a ser **obrigatoriamente vinculada a um deal**.
2. Em `/vendas`, ao abrir um deal, um botão **verde e chamativo "Finalizar Venda"**.
3. Em `/conversas`, tornar o registro de venda **mais chamativo** (botão verde, não um "+").
4. Aplicar melhorias de qualidade: **editar/excluir venda na UI**, **registrar venda no Painel**, **paginar/otimizar a métrica de recompra**.
5. UI reescrita com **primitivos shadcn**, estilizados para casar com a **paleta quente atual**.

## Decisões travadas (perguntas de brainstorming)

- **Lead sem deal:** o modal de venda permite **criar um deal inline** (título + funil); a venda nasce vinculada. O fluxo nunca trava.
- **Escopo agora:** editar/excluir venda, registrar no Painel, paginar recompra. **Fora de escopo:** catálogo de produtos (projeto próprio futuro).
- **Visual:** primitivos shadcn estilizados na paleta quente atual.
- **Vínculo deal:** **Opção A — orquestração no servidor (atômica).** `POST /api/sales` cria deal+venda numa só chamada quando o deal é novo.

## Arquitetura

### Modelo de dados / regra de negócio

- Venda **sempre** vinculada a um deal — validado na **API + UI**.
- A coluna `sales.deal_id` permanece **nullable no banco** (vendas históricas sem deal continuam válidas; legado documentado). A obrigatoriedade é regra de aplicação, não constraint de schema, para não quebrar dados existentes.
- Sem migration de schema obrigatória nesta leva (exceto a RPC de recompra — ver abaixo). A criação de deal usa o pipeline/stage já existentes.

### API: `POST /api/sales` (alterado)

Aceita **um destes** para o vínculo:
- `deal_id`: id de deal existente; **ou**
- `new_deal: { title: string, pipeline_id: string }`: dados de um deal novo.

Comportamento:
1. Valida `lead_id`, `product`, `value` (como hoje) **+** que exista `deal_id` OU `new_deal`. Sem nenhum → 400.
2. Se `new_deal`: cria o deal (reaproveitando a lógica de stage do `POST /api/deals` — primeiro stage não-protegido do pipeline) e usa o id resultante.
3. Insere a venda com o `deal_id` resolvido.
4. Move o deal para `fechado_ganho` + `closed_at` (comportamento que já existe).
5. Dispara o evento `sale_created` para o backend de automação (fire-and-forget, como hoje).

A criação deve ser resiliente: se a criação do deal falhar, retorna erro **sem** inserir a venda (nunca venda órfã).

### API: recompra otimizada

A métrica `avg_repurchase_cycle_days` hoje carrega **toda** a tabela `sales` no Node. Migrar o cálculo para uma **RPC Postgres** (`get_avg_repurchase_cycle_days`) que agrega no banco (média dos intervalos entre vendas consecutivas por lead). `GET /api/sales/metrics` chama a RPC em vez de iterar em memória.

- Migration SQL nova em `frontend/src/db/migrations/` definindo a função.
- **Aplicação no Supabase fica pendente** (registrar no spec/memory como pendência operacional, igual às migrations anteriores).

### Frontend — modal de venda unificado (`SaleCreateModal` → reescrito)

Componente único com shadcn (`Dialog`, `Button`, `Select`, `Input`, `Label`, `Textarea`, `AlertDialog`), estilizado na paleta quente. Modos/contextos:

- **Modo criar** com 3 contextos de abertura:
  - **a) a partir de um deal** (`/vendas`): deal **fixo/travado**, sem seletor.
  - **b) a partir do perfil** (`/conversas`): lead fixo; seletor de deal existente **ou** "criar novo deal" inline.
  - **c) a partir do Painel** (`/painel-vendas`): **seletor de lead** primeiro, depois deal (existente ou inline).
- **Modo editar**: pré-preenche a venda; salva via `PATCH /api/sales/[id]`.

Campos: produto*, valor*, data (default hoje), vendedor (dropdown `/api/users`), deal (conforme contexto), observação.
Seção de criação inline de deal: título do deal + funil (`/api/pipelines`).

### Frontend — `/vendas` (DealDetailSidebar)

Botão **verde proeminente "Finalizar Venda"** no topo do conteúdo do sidebar (acima dos detalhes), visível no modo visualização. Abre o `SaleCreateModal` no contexto (a) com o deal travado. Verde = token de sucesso do shadcn ajustado à paleta.

### Frontend — `/conversas` (CrmPerfilTab)

O "+" da seção "Vendas" vira um **botão verde "Registrar Venda"** (mesmo padrão visual do botão de `/vendas`). Abre o `SaleCreateModal` no contexto (b).

### Frontend — `/painel-vendas`

- Botão **"Registrar Venda"** no topo da página → `SaleCreateModal` contexto (c).
- Tabela (`SalesTable`) ganha ações por linha: **editar** (abre modal modo editar) e **excluir** (`AlertDialog` → `DELETE /api/sales/[id]`).
- Lista de vendas do perfil em `/conversas` também ganha editar/excluir.

## Componentes / unidades

| Unidade | Responsabilidade | Depende de |
|---|---|---|
| `POST /api/sales` | Criar venda + (opcional) deal atômico, mover deal, disparar automação | supabase, lógica de stage |
| RPC `get_avg_repurchase_cycle_days` + `GET /api/sales/metrics` | Métricas agregadas no banco | Postgres |
| `SaleCreateModal` (shadcn) | Criar/editar venda nos 3 contextos + criar deal inline | `/api/sales`, `/api/users`, `/api/pipelines`, `/api/leads/[id]/deals` |
| `DealDetailSidebar` | Botão "Finalizar Venda" | `SaleCreateModal` |
| `CrmPerfilTab` | Botão verde "Registrar Venda" + editar/excluir na lista | `SaleCreateModal` |
| `PainelVendasPage` + `SalesTable` | Botão "Registrar Venda" + ações editar/excluir por linha | `SaleCreateModal` |

## Tratamento de erros

- API: 400 quando falta vínculo de deal; 422 quando o funil não tem stage disponível para criar deal inline; 500 em erro de banco. Nunca persistir venda sem deal resolvido.
- UI: mensagens inline no modal; `AlertDialog` confirma exclusão; estados de loading nos botões.

## Testes / verificação

- API: criar venda com `deal_id`; criar venda com `new_deal` (verifica deal criado + venda + deal em `fechado_ganho`); rejeitar sem vínculo; editar; excluir.
- RPC de recompra: resultado equivalente ao cálculo antigo para um dataset de exemplo.
- Frontend: build (`next build`/lint) limpo; smoke manual dos 3 contextos + editar/excluir.

## Uso de agentes (execução)

A execução é via **subagents**, em worktree isolado. Todo agente que mexer no frontend **deve usar a skill `frontend-design` e os primitivos shadcn**. Os pontos visuais (botão verde no deal, botão de registro no chat/painel, modal unificado) são desenhados pelos agentes frontend-design seguindo a paleta quente.

## Fora de escopo (futuro)

- Catálogo/normalização de produtos.
- `sold_by` como FK para usuário (hoje é texto/email).
- Múltiplos itens / quantidade / desconto por venda.
- Constraint `NOT NULL` em `sales.deal_id` (exigiria backfill do legado).
