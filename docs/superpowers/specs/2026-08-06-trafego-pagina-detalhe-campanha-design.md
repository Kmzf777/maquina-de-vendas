# Spec — /trafego: página de detalhe da campanha

**Data:** 2026-08-06
**Status:** pré-aprovado pelo usuário; execução via subagents

## Objetivo

Substituir o **drawer lateral** (`CampaignLeadsDrawer`, `Sheet` estreito de 5 colunas — UX
ruim) por uma **página completa e detalhada da campanha** onde dá para visualizar tudo:
KPIs, evolução no tempo (gráfico) e a lista completa de leads.

## Contexto atual
- Clicar numa linha do relatório abre `CampaignLeadsDrawer` (Sheet `sm:max-w-2xl`) que só
  lista leads (Lead, Origem, Etapa, Entrada, Venda). Curto e cramped.
- `recharts@3` já está no projeto (usado no dashboard). Reusável para o gráfico.
- Endpoints existentes: `/api/traffic/report` (agregado) e `/api/traffic/leads` (drill-down).

## Rota e navegação
- Nova rota **`frontend/src/app/(authenticated)/trafego/campanha/page.tsx`** (client), lendo
  os query params: `channel`, `campaign`, `period`, `mode`, `date_from`, `date_to`.
  (Query params — não path segments — porque campanha/canal têm espaços, acentos e parênteses
  ex.: "(sem campanha)"; `encodeURIComponent` resolve.)
- Na tabela principal, o clique numa linha passa a **navegar** (`router.push('/trafego/campanha?…')`)
  em vez de abrir o drawer. **Remover** o `CampaignLeadsDrawer` e seu uso em `page.tsx`.
- Botão **"← Voltar"** volta para `/trafego` preservando os filtros (period/mode/datas via query).
- Gate admin: a rota fica sob `(authenticated)`; a página checa `useCurrentRole` (mostra
  "Acesso restrito" p/ não-admin) e o proxy admin já cobre `/api/traffic/*`.

## Backend — endpoint dedicado
- **`GET /api/traffic/campaign?channel=&campaign=&period=&mode=&date_from=&date_to=`**
  (FastAPI `/api/traffic/campaign`; proxy admin-gated no Next, igual aos outros).
- Função **`campaign_detail(channel, campaign, period, mode, date_from, date_to)`** em
  `traffic_report.py`. Reusa `_resolve_window`/`_fetch_leads`/`_conversed_ids`/`_closer_ids`/
  `_sales_by_lead`/`_spend_by_campaign`/`build_campaign_report`/`campaign_leads`. Passos:
  1. Resolve a janela; busca os leads; **filtra** os que casam (channel, campaign).
  2. `summary`: roda `build_campaign_report` **só com os leads filtrados** → `rows[0]`
     (a única linha) = KPIs da campanha. Sem leads → summary com zeros.
  3. `leads`: `campaign_leads(...)` (já existe, reusar).
  4. `timeseries`: por dia (fuso America/Sao_Paulo, igual `conversion_analytics`), lista de
     `{date, leads, vendas, receita}` — leads contados por `created_at`, vendas/receita por
     `sold_at` das vendas dos leads filtrados. Dias sem evento = 0. Só nos dias da janela
     (ou últimos 30 se janela aberta).
  5. Retorna `{summary, leads, timeseries}`. **Fail-soft** (zeros/[] em erro).
- Função de bucketização do timeseries é **pura** (testável isolada do I/O).

## Frontend — conteúdo da página
- **Cabeçalho:** "← Voltar", badge do canal (mesmas cores do `campaign-report-table`),
  título = nome da campanha, subtítulo com período/modo.
- **KPI cards** (grid responsivo): Leads, Conversas, Foi pro closer, Clientes, Pedidos,
  Receita, Ticket médio, Taxa de conversão e — **quando canal = "Google Ads"** — Investimento
  e ROAS. (Cartões seguem a paleta; nº grande + rótulo.)
- **Gráfico (recharts):** timeseries da janela — Leads por dia + Vendas por dia (barras/linha).
  Reusar o padrão do dashboard.
- **Tabela de leads completa** (largura total, mais colunas que o drawer): Lead (nome/telefone),
  Origem (Pago/Orgânico), utm_source, utm_medium, Etapa, Conversou, Entrada, Venda (data + valor).
  Campo de **busca** client-side por nome/telefone. Sem paginação (leads de uma campanha são
  limitados); estados de loading (skeleton) e vazio.

## Componentes (isolamento)
- `frontend/src/app/(authenticated)/trafego/campanha/page.tsx` — compõe a página, faz o fetch
  de `/api/traffic/campaign`, lê query params, trata loading/erro/gate admin.
- `frontend/src/components/trafego/campaign-kpis.tsx` — grid de KPI cards (recebe `summary`).
- `frontend/src/components/trafego/campaign-timeseries.tsx` — gráfico recharts (recebe `timeseries`).
- `frontend/src/components/trafego/campaign-leads-table.tsx` — tabela completa + busca (recebe `leads`).
- `frontend/src/app/api/traffic/campaign/route.ts` — proxy admin-gated (igual report/leads).
- **Remover** `frontend/src/components/trafego/campaign-leads-drawer.tsx` e seu uso em `page.tsx`.

FRONTEND: todo agente que mexer no front usa `frontend-design` + shadcn/ui (regra do projeto).

## Tipos (contrato)
- `CampaignRow` (já existe, reusar) = summary.
- `CampaignLead` (já existe, reusar) — mover o type p/ um módulo compartilhado
  (`campaign-leads-table.tsx`) já que o drawer sai.
- `CampaignTimeseriesPoint = { date: string; leads: number; vendas: number; receita: number }`.
- `CampaignDetail = { summary: CampaignRow; leads: CampaignLead[]; timeseries: CampaignTimeseriesPoint[] }`.

## Tratamento de erros
- Backend fail-soft (summary zerado, leads [], timeseries []).
- Proxy: 401/403/502 como os outros.
- Frontend: skeleton no load; "Acesso restrito" p/ não-admin; vazio tratado; se a campanha não
  existe no período, mostra os zeros + "Nenhum lead nesta campanha".

## Testes
- Backend: `campaign_detail` retorna summary/leads/timeseries; empty-safe; a bucketização pura
  do timeseries agrupa por dia (leads por created_at, vendas por sold_at, dias sem evento = 0);
  filtro por (channel, campaign) correto. Router expõe `/api/traffic/campaign`.
- Frontend: type-check/eslint/tests verdes (proxy-coverage precisa incluir `/api/traffic` já
  coberto; a nova **página** `/trafego/campanha` é subrota de `/trafego`, já no matcher — mas
  o teste `proxy-coverage` olha diretórios de 1º nível de `app/(authenticated)`, então
  `/trafego/campanha` é coberto por `/trafego`; confirmar). Smoke da rota + gate admin.

## Fora de escopo
- Paginação/exportação da tabela de leads; filtros avançados; edição de lead na página;
  timeseries de investimento por dia (v2).

## Decisões
1. Rota por **query params** em `/trafego/campanha` (não path).
2. **Endpoint dedicado** `/api/traffic/campaign` (summary+leads+timeseries) — reusa a lógica.
3. Página com **KPIs + gráfico (recharts) + tabela completa com busca**.
4. **Remover** o drawer.
