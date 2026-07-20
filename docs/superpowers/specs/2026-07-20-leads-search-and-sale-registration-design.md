# Design/Spec — Correções de Busca de Leads e Registro de Venda

**Data:** 2026-07-20
**Branch:** `fix/leads-search-and-sale-registration`
**Origem:** 3 demandas reportadas por vendedor.

---

## Contexto

CRM "Maquina de Vendas Canastra" — Next.js 16 (App Router + Server Components), Supabase (browser client direto), FastAPI para automações. UI em shadcn/ui sobre o metapacote `radix-ui` (`import { X as XPrimitive } from "radix-ui"`).

Três queixas independentes, todas na experiência do vendedor:

1. **Busca da aba Leads não encontra alguns leads** por nome, empresa ou número.
2. **Modal de detalhe do lead não permite registrar venda** — só mostra 4 abas.
3. **No painel de vendas, ao registrar nova venda, não há busca por nome do lead** — só uma lista longa para rolar.

---

## Diagnóstico (resultado das 3 investigações)

### Demanda 1 — Busca de leads incompleta

Fluxo: a página faz **filtragem 100% client-side** sobre um array em memória. Sem busca server-side.

- `frontend/src/hooks/use-realtime-leads.ts:12-22` carrega leads com `supabase.from("leads").select("*")` **sem `.range()`/`.limit()`**. O PostgREST aplica um **teto padrão de 1000 linhas**. Se o CRM tem >1000 leads, os que estão fora das 1000 mais recentes (por `last_msg_at`) **nunca são carregados** → nenhuma busca os encontra. **Causa primária.**
- `frontend/src/app/(authenticated)/leads/page.tsx:53-60` filtra com `.toLowerCase().includes(q)`:
  - **Sem folding de acento** — buscar "jose" não acha "José", "acai" não acha "Açaí". Nomes/empresas PT-BR têm á, ã, ç, é.
  - **Telefone:** `lead.phone.includes(q)` compara a string crua contra o telefone armazenado em **13 dígitos** (`55` + DDD + 9 dígitos). Digitar `(34) 99999-8888` não casa com `5534999998888` porque a query não é reduzida a dígitos.
  - **`nome_fantasia` não é pesquisado** (só `name`, `company`, `razao_social`).

Fix: **frontend-only**. Paginar o fetch (loop de `.range`) para carregar todos os leads; e centralizar a lógica de match num helper com folding de acento + normalização de dígitos de telefone + campos extras.

### Demanda 2 — Registrar venda no detalhe do lead

- Modal: `frontend/src/components/leads/lead-detail-modal.tsx`. Config de abas em `:21-26` (`Dados Gerais`, `Campanhas`, `Tags & Notas`, `Metricas`). Já carrega `leadDeals` do lead (`:95-107`).
- **Componente de registro de venda já existe e é reutilizável:** `frontend/src/components/sales/sale-create-modal.tsx` (`SaleCreateModal`), construído em shadcn (`Dialog/Select/Input/Textarea`). Aceita `leadId` (pré-preenche o lead), oferece os deals do lead via `/api/leads/{id}/deals` e tem caminho **"+ Criar novo deal"** inline — então **lead sem deal também consegue registrar venda**.
- Persistência: `POST /api/sales` (cria deal inline via `new_deal`, insere venda, move deal para "Fechado Ganho", dispara `sale_created`). **Nenhuma mudança de backend/API/RPC necessária.**
- Precedentes de reuso: `contact-detail.tsx:277-286` (`leadId` + `conversationId` + `currentUserEmail`); `deal-detail-sidebar.tsx:256-264`; `painel-vendas/page.tsx:90-93` (`pickLead`).

Fix: **frontend-only**. Adicionar botão verde **"Registrar Venda"** no header/seção Oportunidades do `lead-detail-modal.tsx` que abre `SaleCreateModal` com `leadId={lead.id}`; `onSaved` re-busca os deals. Botão (não nova aba) por consistência com todo o resto do app.

### Demanda 3 — Selector de lead sem busca no registro de venda

- `frontend/src/components/sales/sale-create-modal.tsx:259-284`: o selector é um `<Select>` (Radix) **sem input de texto/typeahead** — renderiza todo lead como `SelectItem`, exige rolar.
- Leads carregados uma vez via `fetch("/api/leads")` (`:99-106`), **sem paginação** → lista completa já está no cliente, então **filtro client-side basta**.
- **Não há** `command.tsx`/`combobox.tsx`/`popover.tsx` em `components/ui/`, nem `cmdk`. Porém `radix-ui` (metapacote já instalado) exporta `Popover`. **Não é preciso adicionar dependência** — construir Combobox leve com Popover + Input + lista filtrada.

Fix: **frontend-only**. Adicionar `components/ui/popover.tsx` (padrão shadcn sobre `radix-ui`) e substituir só o bloco do selector por um Combobox pesquisável (nome + telefone) reusando o mesmo helper de busca da Demanda 1.

---

## Decisões de design

- **Um helper de busca compartilhado** — `frontend/src/lib/search.ts` — usado tanto pela aba Leads (Demanda 1) quanto pelo selector de vendas (Demanda 3), garantindo comportamento idêntico (acento + telefone).
- **Sem backend/migration.** Todas as correções são frontend. Não há necessidade de `unaccent`/índices porque o volume atual é filtrável no cliente após carregar todas as linhas.
- **Reuso máximo:** Demanda 2 não reimplementa nada — só liga o `SaleCreateModal` existente.
- **Popover via `radix-ui`**, sem novas dependências (`cmdk` evitado).
- **shadcn + skill `frontend-design`** obrigatórios em qualquer trabalho visual (novo Popover, Combobox, botão).

## Fora de escopo

- Busca server-side / índices trigram (só se a base crescer para dezenas de milhares).
- Mudanças no fluxo de persistência de vendas.
- Paridade mobile do botão de venda (opcional; anotado como polish).

## Critérios de aceite

1. Buscar na aba Leads por nome sem acento, por razão social/nome fantasia, e por telefone formatado encontra o lead correto; leads além dos 1000 mais recentes aparecem.
2. Abrir um lead na aba Leads mostra um botão "Registrar Venda" que abre o fluxo de venda já preenchido com o lead; ao salvar, a lista de oportunidades do lead atualiza.
3. No registro de nova venda do painel de vendas, o selector de lead permite digitar e filtrar por nome ou telefone.
4. `npm run test`, `npm run lint` e `npm run type-check` verdes no `frontend/`.
