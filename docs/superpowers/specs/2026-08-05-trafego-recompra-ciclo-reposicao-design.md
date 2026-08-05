# Spec — /trafego: recompra (Pedidos) + ciclo de reposição

**Data:** 2026-08-05
**Status:** aprovado nas decisões; pendente review do spec escrito

## Objetivo

Evoluir o Relatório Campanhas (/trafego) e o ciclo de vida de oportunidades:
1. Dar visibilidade de **recompra** por campanha sem quebrar a taxa de conversão.
2. Expor **datas** por lead (entrada no CRM e data da venda).
3. Renomear o canal "Direto" para "Sem rastreio".
4. Implementar a regra de ciclo: **todo deal que entra em `fechado_ganho` gera uma nova
   oportunidade de reposição** (+ backfill dos que já ganharam e estão sem oportunidade).

## Contexto verificado (como funciona hoje)

- O relatório agrega por **lead**, não por deal: `Vendas` = leads distintos com ≥1 linha em
  `sales`; `Receita` = soma de todas as vendas do lead. Um lead que comprou 2× conta Vendas=1.
- **Nem todo lead tem deal** (nascem em LP-dispatch, handoff/qualificação, import, inline na
  venda). Decisão: **manter o sistema atual de criação de deals** — não criar deal para todo
  lead na entrada.
- **Registrar venda** (`/api/sales` POST): exige deal, insere em `sales`, move o deal para
  `fechado_ganho` (`closed_at`). **Não cria deal de reposição hoje.**
- Datas: entrada = `leads.created_at`; venda = `sales.sold_at`.

## Peças

### A — Renomear "Direto" → "Sem rastreio" (companion, em implementação)
`derive_channel` retorna `"Sem rastreio"` no lugar de `"Direto"`; badge no front e testes
atualizados. Sem impacto na lógica.

### B — Datas no drill-down (companion, em implementação)
`campaign_leads` passa a devolver `sold_at` (última venda do lead, respeitando o modo);
`created_at` já existe. O drawer de leads mostra colunas **Entrada** e **Venda** (dd/MM/yyyy).

### C — Recompra no relatório (Pedidos + Clientes)

Na ótica de gestão de campanha, a taxa de conversão deve permanecer **por lead** (aquisição).
A recompra vira uma coluna própria.

- Renomear a métrica atual **`vendas` → `clientes`** (leads distintos que compraram) — base da conversão.
- Adicionar **`pedidos`** = nº de vendas (linhas em `sales`) do grupo — pode ser > `clientes`.
- **`ticket_medio`** passa a ser `receita ÷ pedidos` (era ÷ clientes).
- **`conversao`** = `clientes ÷ leads` (inalterada, ≤ 100%).
- Backend `build_campaign_report`: cada `row`, o `total` e cada `channel_subtotals[canal]`
  ganham `clientes` (= antigo vendas) e `pedidos` (soma de `sales_by_lead[lead]["count"]` do grupo).
- Frontend `campaign-report-table.tsx`: colunas **Clientes** e **Pedidos**; ticket já vem calculado.
- Fonte: tabela `sales` — **independe do D**. Respeita o toggle de modo (lead × venda).

### D — Ciclo de reposição

**Regra:** quando um deal entra em `fechado_ganho`, garantir que o lead tenha uma
**oportunidade aberta**; se não tiver, criar um novo deal no **pipeline de Reposição**
(primeira etapa), de forma idempotente.

- **Helper central** `ensure_reposicao_deal(lead_id)` (backend, `app/leads/service.py` ou
  módulo novo) = `create_deal(lead_id, title="Reposição", pipeline_name=<REPOSICAO_PIPELINE>,
  stage_label=<primeira etapa>, dedupe_open=True)`. O `dedupe_open=True` já reaproveita
  qualquer deal aberto do lead → nunca duplica; rodar 2× é seguro.
- **Gatilhos** (todos os caminhos que levam um deal a `fechado_ganho` chamam o helper):
  1. `automation/triggers.py`: no `deal_stage_enter`, se o stage de destino tem
     `key == "fechado_ganho"` → `ensure_reposicao_deal(lead_id)` (cobre drag no Kanban via
     `/api/deals/[id]`, que já emite `deal_stage_enter`).
  2. `automation/triggers.py`: no evento `sale_created` (emitido por `/api/sales`) →
     `ensure_reposicao_deal(lead_id)` (cobre registrar venda, que move o deal direto sem
     emitir `deal_stage_enter`).
  3. Backend `campaigns/sales.py::mark_deal_won` (endpoint `/won`) → chamar o helper após
     marcar ganho.
- **Backfill:** script `backend/scripts/backfill_reposicao_deals.py` que roda
  `ensure_reposicao_deal(lead_id)` para todo lead com ≥1 deal `fechado_ganho` e **sem deal
  aberto**. Idempotente (dedupe_open). Loga quantos criou.
- **Pipeline de Reposição:** `REPOSICAO_PIPELINE_NAME = "Reposição - João"` (decidido).
  Resolvido por nome em `create_deal(pipeline_name=...)`. Se o pipeline não existir no
  ambiente (ex.: homolog), `create_deal` cai no fallback (1º pipeline por order_index),
  garantindo que roda em dev/homolog sem quebrar.
- **Fail-soft:** o helper e os gatilhos nunca podem derrubar o fluxo de venda/Kanban — erro
  ao criar o deal de reposição é logado e engolido.

## Tratamento de erros
- Report backend fail-soft (zeros/[]), como já é.
- `ensure_reposicao_deal` e gatilhos: try/except, log, nunca levantam.
- Backfill: continua no próximo lead em caso de erro individual; sumariza ao final.

## Testes
- `build_campaign_report`: `clientes` (distintos) × `pedidos` (linhas de venda) com um lead
  que comprou 2× → clientes=1, pedidos=2, ticket=receita/2; total e channel_subtotals somam
  pedidos; conversão = clientes/leads ≤ 1.
- `campaign_leads`: inclui `sold_at`.
- `ensure_reposicao_deal`: cria quando não há deal aberto; no-op quando há (dedupe); usa o
  pipeline de reposição quando existe, fallback quando não.
- Gatilho: `deal_stage_enter` em `fechado_ganho` chama o helper; outros stages não.
- Backfill: cria para lead com fechado_ganho sem deal aberto; pula quem já tem aberto.
- Frontend: type-check/eslint/tests verdes; colunas Clientes/Pedidos e datas renderizam.

## Decisões confirmadas
1. Manter o sistema atual de criação de deals (NÃO criar deal para todo lead na entrada).
2. C = coluna "Pedidos" + "Clientes" (conversão continua por lead).
3. D = deal de reposição no pipeline **"Reposição - João"** após `fechado_ganho` + backfill.

## Fora de escopo
- Criar deal para todo lead na entrada (descartado).
- Custo/ROAS; captura de novos campos de UTM no webhook.
