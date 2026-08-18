# Busca Universal (`/busca`) + fix da busca em `/vendas`

Data: 2026-08-18
Status: Aprovado (aprovação verbal do usuário nesta conversa; ver checklist §9)

## 1. Problema

1. A busca por deal em `/vendas` (`frontend/src/app/(authenticated)/vendas/page.tsx:258`) filtra em memória a lista já
   carregada e falha por 5 motivos combinados:
   - só busca dentro do funil aberto (`useRealtimeDeals(selectedPipelineId)`);
   - sem paginação/`limit`, deals além do teto do PostgREST (1000 linhas) nem chegam ao browser;
   - com "Ativos" ligado, `stage.is_protected` remove o deal antes de comparar o texto;
   - sem folding de acento (`foldText` existe em `lib/search.ts` mas não é usado aqui);
   - telefone comparado cru (`lead.phone.includes(q)`), não casa `(34) 99999-8888` com `5534999998888`.
2. Não existe uma busca cross-entidade no CRM. Encontrar "aquele lead/deal/venda/conversa" exige abrir a página certa e
   adivinhar o filtro certo.

## 2. Objetivo

- Corrigir a busca local do `/vendas` (rápido, isolado).
- Criar `/busca`: página de busca universal sobre **leads, deals, vendas e conversas** (núcleo de vendas), com ênfase em
  conversas (mensagens enviadas e recebidas, nome de documento/PDF) — reaproveitando o RPC `search_customer_messages` já
  validado em `/conversas`.
- Adicionar a página ao menu lateral, grupo "Vendas", logo abaixo de "Painel de Vendas".

## 3. Fora de escopo (YAGNI)

- Cadências (`campaigns`/`campaign_enrollments`), disparos (`broadcasts`) e dados de tráfego/UTM — não fazem parte do
  núcleo de vendas pedido; podem virar uma spec própria depois.
- Ranking unificado/misturado entre tipos — o layout é em abas, não uma lista só; cada tipo ordena por sua própria
  relevância (`match_count`/`created_at`/similaridade trigram).
- Filtro por responsável/canal na `/busca` — não foi pedido; fica de fora.
- RLS novo em `leads`/`sales` — essas tabelas já são globais para qualquer role hoje (ver §5); a `/busca` mantém essa
  paridade em vez de introduzir uma restrição nova.

## 4. Fix do `/vendas` (independente, primeiro)

Troca o predicado de `filteredDeals` (`vendas/page.tsx:258`) para usar as mesmas funções já existentes em
`frontend/src/lib/search.ts`:
- nome do lead, empresa, `nome_fantasia`, título do deal → `foldText()` (accent-insensitive, já usado noutro lugar).
- telefone → comparação por dígitos (`raw.replace(/\D/g, "")`, mesmo padrão de `leadMatchesSearch`).

Continua um filtro client-side (só o funil aberto, só o que já carregou) — não resolve o teto de 1000 linhas nem a
busca cross-funil; isso é exatamente o que `/busca` resolve de verdade. É um quick-fix contido, não uma reescrita.

## 5. Escopo por role (RBAC) — paridade com o que já existe

| Entidade | Regra hoje (confirmada no código) | Aplicada em `/busca` via |
|---|---|---|
| Leads | Sem restrição — `/api/leads` e `/leads` não filtram por dono | sem filtro extra |
| Deals | Vendedor vê só pipelines próprios + universais | `getAllowedPipelineIds()` (`lib/supabase/pipeline-access.ts`) |
| Vendas | Sem restrição — `/api/sales` e `/painel-vendas` não filtram por dono | sem filtro extra |
| Conversas | Vendedor vê só canais próprios | `getAllowedChannelIds()` (`lib/supabase/channel-access.ts`) |

Falha de auth em qualquer helper → **401**, nunca lista vazia silenciosa (mesmo padrão de `channel-access.ts`).

## 6. Arquitetura — Abordagem A (fan-out no servidor)

Uma rota nova `/api/search` roda 4 buscas em paralelo (`Promise.all`) contra RPCs Postgres dedicadas — reaproveita
`search_customer_messages` (existente) e cria 3 novas: `search_leads`, `search_deals`, `search_sales`. Mesmo padrão de
`unaccent` + trigram já validado na migration `20260812_search_all_messages.sql`.

### 6.1 Migration `supabase/migrations/20260818_universal_search.sql`

**`search_leads(search_query text, max_results int DEFAULT 20)`**
- Casa por `unaccent+lower` em `name`, `company`, `razao_social`, `nome_fantasia` (trigram `LIKE`, mesmo padrão do RPC
  de mensagens) OU por dígitos de telefone (`regexp_replace(phone, '\D', '', 'g') LIKE '%' || regexp_replace(search_query, '\D', '', 'g') || '%'`,
  só quando `search_query` tiver algum dígito).
- Sem parâmetro de escopo (leads são globais — §5).
- Filtro opcional `p_status text DEFAULT NULL` → `WHERE (p_status IS NULL OR status = p_status)`.
- Filtro opcional `p_created_after timestamptz, p_created_before timestamptz`.
- `RETURNS TABLE(id, name, company, phone, status, stage, created_at, nome_fantasia, cnpj, total_count bigint)` com
  `COUNT(*) OVER()` para paginação.
- Índices: reaproveita/estende os trigram existentes em `leads` se já houver (checar antes de criar duplicado); senão
  cria `idx_leads_name_trgm` etc. seguindo o padrão de `f_unaccent`.

**`search_deals(search_query text, pipeline_ids uuid[], max_results int DEFAULT 20)`**
- `pipeline_ids IS NULL` → sem restrição (admin); senão restringe a `pipeline_id = ANY(pipeline_ids)`.
- Casa por `unaccent+lower` em `title` e nos campos do lead relacionado (`name`, `company`, `nome_fantasia`) via
  `JOIN leads`, OU telefone do lead.
- Filtros opcionais: `p_pipeline_id uuid`, `p_stage_id uuid`, `p_created_after/before timestamptz`.
- `RETURNS TABLE(id, title, value, stage_id, stage_label, pipeline_id, pipeline_name, lead_id, lead_name, lead_phone, created_at, total_count bigint)`.

**`search_sales(search_query text, max_results int DEFAULT 20)`**
- Casa por `unaccent+lower` em `product`, `notes`, e nos campos do lead relacionado (nome/empresa) via `JOIN leads`, OU
  telefone do lead.
- Filtros opcionais: `p_sold_after/before timestamptz` (mapeia "Período" para `sold_at`).
- `RETURNS TABLE(id, product, value, sold_at, lead_id, lead_name, lead_phone, deal_id, deal_title, total_count bigint)`.

**`search_customer_messages` — extensão não-destrutiva**
- Adiciona parâmetro `docs_only boolean DEFAULT false` ao final da assinatura (compatível com chamadas atuais que usam
  args nomeados, como em `frontend/src/app/api/conversations/search/route.ts`).
- Quando `docs_only = true`, restringe o `WHERE` a `m.document_name IS NOT NULL`.
- Mesmo `DROP FUNCTION IF EXISTS` + `CREATE OR REPLACE` que a migration anterior já usa (assinatura muda).
- `GRANT EXECUTE` mantém `authenticated, service_role` (sem `anon`, igual hoje).

Todas as novas funções: `LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public`, `GRANT EXECUTE ... TO authenticated, service_role` — mesmo padrão de segurança do RPC existente.

### 6.2 API — `frontend/src/app/api/search/route.ts` (novo)

`GET /api/search?q=...&tab=all|leads|deals|sales|conversations&date_from=&date_to=&pipeline_id=&stage_id=&lead_status=&docs_only=&page=1`

- `q.length < 2` → responde `{ leads: {data:[],count:0}, deals: {...}, sales: {...}, conversations: {...} }` sem chamar
  nenhum RPC (mesmo corte de `MIN_QUERY_LEN` que `/api/conversations/search`).
- Resolve escopo primeiro: `getAllowedPipelineIds()` e `getAllowedChannelIds()` (podem lançar `PipelineAccessError`/
  `ChannelAccessError` → **401**, nunca `[]` silencioso — mesma regra do resto do app).
- `tab=all` (ou omitido): `Promise.all` das 4 RPCs com `max_results=5` cada — é o preview da aba "Tudo". Front usa
  `total_count` de cada resposta pra desenhar "ver todos (N) >".
- `tab=<específico>`: chama só o RPC daquele tipo, paginado. Os 3 RPCs novos recebem `p_offset int DEFAULT 0` além de
  `max_results` (paginação real no Postgres via `LIMIT/OFFSET`, sem reprocessar tudo a cada página); a rota calcula
  `p_offset = (page - 1) * limit`.
- Erros do RPC → **500** com a mensagem do Postgres (mesma regra de `/api/conversations/search`), nunca `[]` silencioso.
- Resposta sempre no formato `{ leads: {data, count}, deals: {data, count}, sales: {data, count}, conversations: {data, count} }`,
  com as chaves não solicitadas (quando `tab` é específico) vindo vazias — contrato único simplifica o hook do front.

### 6.3 Frontend

**Hook** `frontend/src/hooks/use-universal-search.ts`
- Estado: `query`, `tab`, `filters` (período, pipeline/stage, lead status, docs_only).
- Debounce de 400ms reaproveitando `frontend/src/lib/debounce.ts` (mesmo padrão do resto do repo); dispara só com
  `query.trim().length >= 2`; query vazia limpa resultados sem bater na API.
- `fetch("/api/search?...")`, guarda última `generation` (mesmo padrão anti-race de `use-realtime-deals.ts`) para
  ignorar respostas fora de ordem.

**Página** `frontend/src/app/(authenticated)/busca/page.tsx`
- Header com input de busca (autofocus) + abas `Tudo | Leads | Deals | Vendas | Conversas` (contagem por aba).
- Barra de filtros **adaptativa por aba**:
  - Tudo → só Período.
  - Leads → Período + Status.
  - Deals → Período + Funil + Etapa.
  - Vendas → Período.
  - Conversas → Período + "Só documentos/mídia".
- Estado vazio (query curta): instrução "Digite ao menos 2 caracteres". Sem resultados: "Nada encontrado para "X"".
- Erro (401/500 da API): mensagem de erro visível, mantém o último resultado bom na tela (nunca zera silenciosamente —
  mesmo princípio de `channel-access.ts`).
- Clique num resultado → navega para a página existente do item via `router.push` com query param (ver §7).

**Componentes** `frontend/src/components/search/`: `search-input.tsx`, `search-tabs.tsx`, `search-filters-bar.tsx`,
`search-result-row-{lead,deal,sale,conversation}.tsx` (uma linha de resultado por tipo, cada um sabe seu próprio link
de destino).

**Sidebar** (`frontend/src/components/sidebar.tsx`): novo item no grupo "Vendas", logo após `/painel-vendas`:
```ts
{ href: "/busca", label: "Busca", icon: <svg .../* lupa */ /> }
```
Sem `roles` (visível pra admin e vendedor).

**`frontend/src/lib/auth/roles.ts`**: adiciona `/busca` em `ROLE_PAGES.admin` e `ROLE_PAGES.vendedor`.

## 7. Navegação — deep-links (trabalho novo necessário)

Hoje só `/conversas` sabe abrir um item via URL (`?lead_id=`, padrão em `conversas/page.tsx:159-169`: lê
`searchParams` depois que a lista carrega, acha o item, seta estado, `router.replace()` limpa a URL). `/leads`,
`/vendas` e `/painel-vendas` **não têm** esse mecanismo — é pré-requisito pra "ir para a página existente do item"
funcionar pros 3 tipos que faltam.

- **`GET /api/leads/[id]`, `GET /api/deals/[id]`, `GET /api/sales/[id]`** — não existem hoje (só `PATCH`/`DELETE`).
  Adicionar `GET` simples em cada rota (select por id, 404 se não achar). Necessário porque o item buscado pode estar
  fora do filtro/período/página atualmente carregado na lista da página de destino.
- **`/leads?lead_id=<id>`**: mesmo padrão de `/conversas` — busca o lead via `GET /api/leads/[id]` (não depende da
  lista já carregada), seta `selectedLead`, `router.replace("/leads")`.
- **`/vendas?deal_id=<id>`**: busca o deal via `GET /api/deals/[id]` pra saber o `pipeline_id`; se `pipeline_id` !==
  `selectedPipelineId` atual, chama `setSelectedPipelineId`; quando `deals` (do `useRealtimeDeals`) contiver o id,
  `setSelectedDealId`, `router.replace("/vendas")`.
- **`/painel-vendas?sale_id=<id>`**: busca a venda via `GET /api/sales/[id]` diretamente (independe do filtro de
  período `from/to` da lista atual), `setEditingSale`, `router.replace("/painel-vendas")`.
- Conversas: reusa o padrão já existente (`?lead_id=`) — resultado de conversa na `/busca` linka para
  `/conversas?lead_id=<lead_id_da_conversa>`.

## 8. Testes

- `lib/search.ts` (fix do `/vendas`): teste de unidade pro novo predicado de `filteredDeals` (acento, telefone
  formatado, funil ativo/inativo) — TDD conforme `superpowers:test-driven-development`.
- RPCs novas: teste de integração (ou teste da rota `/api/search` com Supabase local) cobrindo cada entidade,
  paginação (`p_offset`), filtros e o corte de `docs_only`.
- `/api/search`: teste de rota cobrindo `q` curto (resposta vazia sem chamar RPC), 401 de auth, 500 de RPC, `tab=all`
  vs `tab` específico.
- Deep-links: teste de unidade por página (`/leads`, `/vendas`, `/painel-vendas`) cobrindo o novo `useEffect` de
  parse de `searchParams` — mesmo padrão de qualquer teste já existente para o deep-link de `/conversas`, se houver.
- `roles.ts`: cobrir `/busca` no teste de cobertura de rotas por role, se existir um (`proxy-coverage.test.ts`).

## 9. Checklist de aprovação

- [x] Escopo (núcleo de vendas: leads, deals, vendas, conversas) — aprovado pelo usuário.
- [x] Layout em abas por tipo — aprovado pelo usuário.
- [x] Filtros (período; funil/etapa/status; só documentos) — aprovados pelo usuário.
- [x] RBAC com paridade ao comportamento atual por entidade (não uniforme) — aprovado pelo usuário nesta conversa.
- [x] Busca ao vivo com debounce, mínimo 2 caracteres — aprovado pelo usuário.
- [x] Clique navega pra página existente do item (deep-link) — aprovado pelo usuário.
- [x] Abordagem A (RPCs dedicadas + fan-out no servidor) — aprovada pelo usuário.
- [x] Usuário aprovou seguir direto para plano de implementação e execução via subagents, sem gate adicional de
      revisão do spec escrito.
