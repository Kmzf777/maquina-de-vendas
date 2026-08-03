# Spec — `/trafego` "Relatório Campanhas" (admin)

**Data:** 2026-08-03
**Autor:** brainstorming com o usuário
**Status:** aprovado para plano

## Objetivo

Página administrativa que dá **rastreio completo de campanhas e leads**, cruzando a
atribuição já capturada (UTMs + click-ids) com as vendas registradas no CRM. Responde:
"de qual campanha/canal (Google x Meta x orgânico) veio o lead, quantos conversamos,
quantos foram pro closer e quantos compraram — e quanto faturamos por campanha".

Escopo desta entrega é **somente reportar dados que já são capturados hoje**. Não altera
o webhook de landing page, não adiciona colunas de captura (utm_content/term, landing_url,
referrer, msclkid, ttclid ficam para uma entrega futura) e não trata custo/ROAS (exige
fonte de gasto de anúncio, fora de escopo).

## Não-objetivos

- Custo por etapa / ROAS (precisa de spend do Google/Meta — não existe no sistema).
- Capturar novos campos de atribuição no webhook LP.
- Devolução de conversão às plataformas (já existe: `campaigns/conversions.py`, CAPI, CSV).

## Fontes de dados (reuso — zero mudança de schema)

| Dado | Origem |
|---|---|
| Atribuição do lead | `leads`: `utm_source`, `utm_medium`, `utm_campaign`, `gclid`, `fbclid`, `ctwa_clid`, `traffic_type`, `created_at`, `id`, `name`, `phone` |
| Conversou? | `conversations.last_customer_message_at` (não-nulo em qualquer canal do lead) |
| Etapa do funil / closer | `deals` (`lead_id`, `stage_id`, `value`, `pipeline_id`) → `pipeline_stages` (`key`, `order_index`) |
| Venda / receita | `sales` (`lead_id`, `value`, `sold_at`) |

## Regras de negócio

### Derivação de canal (prioridade por click-id)
Para cada lead, resolve **um** canal:
1. `gclid` não-vazio → **Google Ads**
2. `fbclid` **ou** `ctwa_clid` não-vazio → **Meta Ads**
3. senão, `traffic_type == 'organic'` **ou** `utm_source` não-vazio → **Orgânico** (rótulo = `utm_source` ou "Orgânico")
4. senão → **Direto / Sem atribuição**

### Agrupamento
Linha da tabela = par **(canal, utm_campaign)**. `utm_campaign` nulo/vazio → `"(sem campanha)"`.
Subtotais por canal + total geral.

### Métricas por campanha
- **Leads** — nº de leads no grupo.
- **Conversas** — nº de leads com `last_customer_message_at` preenchido.
- **Foi pro closer** — nº de leads cujo deal atingiu o stage `qualificado` **ou posterior**
  (comparação por `order_index` do stage `qualificado` dentro do pipeline do deal). Definição
  confirmada: `qualificado` = closer.
- **Vendas** — nº de leads com ≥ 1 linha em `sales`.
- **Receita** — soma de `sales.value` dos leads do grupo.
- **Ticket médio** — Receita ÷ Vendas (0 se Vendas = 0).
- **Taxa de conversão** — Vendas ÷ Leads.

### Atribuição de venda a campanha
Last-touch: a venda conta na campanha do **último clique** do lead — coerente com o que
`persist_lead_tracking` já grava (last-touch sobrescreve, vazio nunca apaga).

### Período (toggle na página — mostrar as duas visões)
- **Por entrada do lead** (default): filtra por `leads.created_at`. Cada campanha mostra os
  leads captados na janela e o que eles já compraram (mesmo que a venda tenha sido depois).
- **Por data da venda**: filtra por `sales.sold_at`. Foca receita realizada na janela.
  Nesta visão, Leads/Conversas/Closer refletem os leads que tiveram venda na janela.
- Janelas: 7d / 30d / 90d / tudo. Fuso `America/Sao_Paulo` (igual `conversion_analytics`).

## Arquitetura

### Backend (`backend/app/campaigns/traffic_report.py` — módulo novo)
Funções puras de agregação (testáveis, sem I/O) + funções que tocam o banco (fail-soft, zeros em erro), no mesmo estilo de `conversion_analytics.py`.

- `derive_channel(lead) -> str` — pura; regra de canal acima.
- `build_campaign_report(leads, conv_map, deals_map, sales_map, mode) -> dict` — pura;
  recebe as coleções já buscadas e agrega em linhas (canal, campanha) + subtotais + total.
- `traffic_report(period, mode) -> dict` — I/O: busca leads do período (por `created_at`
  ou, no modo venda, os `lead_id` distintos de `sales` na janela), depois `conversations`,
  `deals`(+stages) e `sales` para esses `lead_id`, e chama `build_campaign_report`.
- `campaign_leads(channel, campaign, period, mode) -> list[dict]` — I/O: leads de uma
  campanha específica com colunas de drill-down (nome, telefone, created_at, utm_*,
  traffic_type, conversou?, stage atual, comprou?, valor).

Agregação em Python sobre o conjunto **limitado ao período**. RPC SQL fica como otimização
futura se o volume exigir (não nesta entrega).

### Endpoints FastAPI (`backend/app/campaigns/conversions_router.py` ou router novo)
- `GET /api/traffic/report?period=30d&mode=lead|sale`
- `GET /api/traffic/leads?channel=&campaign=&period=&mode=`

Ambos read-only. Sem auth no FastAPI (mesma postura dos outros endpoints internos); a
proteção admin fica na API route do Next (ver abaixo), padrão idêntico ao
`/api/conversions/dashboard`.

### Frontend
- Rota nova: `frontend/src/app/(authenticated)/trafego/page.tsx`, título **"Relatório Campanhas"**.
- **Gate admin**: API routes proxy em `frontend/src/app/api/traffic/report/route.ts` e
  `.../leads/route.ts` checam `getCurrentUser().role === 'admin'` (403/401), igual
  `api/conversions/dashboard/route.ts`. Client usa `useCurrentRole` para esconder/proteger.
- Item novo na navegação lateral (visível só para admin).
- Componentes:
  - Toggle de período (7d/30d/90d/tudo) + toggle de modo (entrada do lead × data da venda).
  - Tabela de campanhas agrupada por canal, com subtotais e total geral.
  - Clique numa linha → drawer/expansão com a lista de leads da campanha (drill-down),
    reusando estilo de tabela/badges já existentes (ex.: badge Pago/Orgânico do
    `crm-perfil-tab`).
- Seguir o design system existente (paleta `#ff5600`, `#111111`, `#faf9f6`, `#dedbd6`…).
  A skill `frontend-design` deve ser invocada antes de construir a UI (regra do projeto).

## Tratamento de erros
- Backend fail-soft: qualquer falha de fetch vira zeros na parte afetada; nunca derruba a página.
- API routes: 401 (não autenticado), 403 (não admin), 502 (backend indisponível).
- Frontend: estados de loading (skeleton) e vazio ("Nenhuma campanha no período").

## Testes
- Unit (Python, puras): `derive_channel` cobrindo as 4 prioridades; `build_campaign_report`
  com fixtures cobrindo agrupamento, subtotais, ticket/taxa com divisor zero, modo lead × venda,
  last-touch, closer por `order_index`, conversou por `last_customer_message_at`.
- Integração leve: os handlers I/O com Supabase mockado retornando zeros em exceção.
- Frontend: smoke da rota + gate admin (não-admin recebe 403/redirect).

## Suposições confirmadas
1. "Foi pro closer" = stage `qualificado` (ou posterior por `order_index`).
2. "Conversou" = `last_customer_message_at` preenchido.
3. Venda atribuída à campanha do último clique (last-touch).
4. Período mostra as duas visões (entrada do lead × data da venda) via toggle.

## Fora de escopo / entregas futuras
- Captura dos campos faltantes (utm_content/term, landing_url, referrer, msclkid, ttclid) +
  migration + handoff das LPs.
- Custo por etapa e ROAS (depende de ingestão de spend Google/Meta).
