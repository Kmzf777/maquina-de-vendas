# /trafego — Relatório geral das campanhas (design)

Data: 24/09/2026 · Status: aprovado pelo usuário

## Objetivo

Entre o cabeçalho da página `/trafego` e a tabela de campanhas, mostrar um relatório
geral do período filtrado, usando só dados que o CRM já tem:

1. **Funil geral** — Leads → Conversa → Closer → Cliente, com taxa de passagem de cada
   etapa e o gargalo (etapa com menor taxa).
2. **Custo por etapa** — CPL, custo por conversa, custo por closer, CAC (só canais pagos).
3. **Funil por canal** — Google Ads, Meta Ads, Orgânico, Sem rastreio lado a lado.
4. **Tempo e qualidade** — mediana de dias até a 1ª compra, recompra, % sem rastreio,
   % de leads pagos não atribuídos.

Fora de escopo: motivo de perda, clique no canal filtrando a tabela, séries temporais.
Sem migration.

## Definições (as mesmas da tabela — não redefinir)

- **Conversa** = o cliente falou (`conversations.last_customer_message_at` não nulo).
- **Closer** = deal em etapa de `order_index >=` o da etapa `key='qualificado'` do funil.
- **Cliente** = lead distinto com ≥1 venda (`sales`). Pedidos = nº de vendas.
- **Canais pagos** = `"Google Ads"` e `"Meta Ads"`.

## Arquitetura

Uma requisição só (`GET /api/traffic/report`), que passa a devolver `summary` ao lado de
`rows`/`total`/`channel_subtotals`. Resumo e tabela nascem do mesmo conjunto de dados e
não divergem.

### Backend — `backend/app/campaigns/traffic_report.py`

- `_sales_by_lead` passa a guardar também `first_sold_at` (menor `sold_at`, comparação de
  string ISO, igual ao `last_sold_at`). Aditivo.
- Nova função pura `build_report_summary(report, leads, sales_by_lead) -> dict`.
- `traffic_report` faz `report["summary"] = build_report_summary(report, leads, sales)`.
- `_empty_report` inclui `"summary": build_report_summary(<o próprio vazio>, [], {})` para o
  contrato ter sempre o mesmo formato.

### Contrato de `summary`

Taxas são frações 0..1 arredondadas a 4 casas; `None` quando o denominador é 0.
Valores em R$ arredondados a 2 casas; `None` quando o denominador é 0 ou não há investimento.

```json
{
  "funnel": {
    "leads": 0, "conversas": 0, "closer": 0, "clientes": 0,
    "taxa_conversa": null,   // conversas / leads
    "taxa_closer": null,     // closer / conversas
    "taxa_cliente": null,    // clientes / closer
    "taxa_total": null,      // clientes / leads
    "gargalo": null          // "conversa" | "closer" | "cliente" | null — menor taxa não nula; empate → a primeira na ordem
  },
  "cost": {
    "investimento": 0.0, "receita": 0.0, "roas": null,
    "leads": 0, "conversas": 0, "closer": 0, "clientes": 0,   // SÓ canais pagos
    "cpl": null, "custo_conversa": null, "custo_closer": null, "cac": null
  },
  "channels": [
    { "channel": "Google Ads", "leads": 0, "conversas": 0, "closer": 0, "clientes": 0,
      "receita": 0.0, "investimento": 0.0, "roas": null,
      "taxa_conversa": null, "taxa_closer": null, "taxa_cliente": null, "taxa_total": null }
  ],
  "timing_quality": {
    "dias_ate_compra_mediana": null,  // float, 1 casa
    "amostra_dias": 0,                // nº de clientes que entraram na mediana
    "pedidos_por_cliente": null,      // pedidos / clientes, 2 casas
    "recompra_pct": null,             // clientes com >1 pedido / clientes
    "sem_rastreio_pct": null,         // leads "Sem rastreio" / leads
    "nao_atribuido_pct": null         // leads pagos em linha "(não atribuído)…" / leads pagos
  }
}
```

Regras:

- `funnel` vem de `report["total"]`.
- `cost`: soma de `channel_subtotals` dos canais pagos. O divisor é SEMPRE a contagem dos
  canais pagos — dividir o gasto por leads orgânicos faria o CPL parecer mais barato.
  `cpl = investimento / leads`, `custo_conversa = investimento / conversas`, etc.; `roas =
  receita / investimento`. Com `investimento == 0` todos os custos e o ROAS são `None`.
- `channels`: ordem fixa Google Ads, Meta Ads, Orgânico, Sem rastreio; qualquer outro
  canal que apareça vai depois, em ordem alfabética. Canal com `leads == 0` e
  `investimento == 0` é omitido. Invariante: soma de `leads` dos canais == `funnel.leads`.
- `dias_ate_compra_mediana`: para cada lead de `leads` com venda que tenha
  `first_sold_at` e `created_at` parseáveis, `dias = (first_sold_at - created_at) / 86400 s`.
  **Descartar dias < 0**: os 1.208 leads importados do Bling têm `created_at` = data da
  importação, e as compras deles são anteriores. Parse com `datetime.fromisoformat`
  aceitando sufixo `Z`; valor inválido é ignorado, nunca levanta.
- `nao_atribuido_pct`: leads das linhas de canal pago cujo `campaign` começa com
  `_UNATTRIBUTED`, sobre leads pagos.
- `sem_rastreio_pct`: `channel_subtotals["Sem rastreio"].leads / total.leads`.
- Função pura e sem I/O. Falha dentro de `traffic_report` segue o fail-soft existente.

### Modo "Por venda"

No modo `sale`, a base já é só de quem comprou, então as taxas do funil ficam perto de 100%
e não informam nada. O backend calcula igual. O frontend mostra no lugar das taxas o aviso
"No modo Por venda a base já é quem comprou — leia o funil no modo Por lead" e mantém custo,
canais e tempo.

### Frontend

- `frontend/src/lib/traffic-summary.ts` — tipos do contrato (`ReportSummary` etc.),
  formatadores (`fmtBRLOrDash`, `fmtPctOrDash`, `fmtDays`) e `collapsedLine(summary)`
  (`"1.240 leads → 612 conversas → 188 closer → 41 clientes"`). Com testes Vitest.
- `frontend/src/components/trafego/report-summary.tsx` — `ReportSummary` (props:
  `summary`, `mode`). Cabeçalho "Relatório geral" com botão Recolher/Expandir.
  - **Expandido:** 4 faixas — Funil (barras horizontais proporcionais a `leads`, % de
    passagem entre barras, gargalo destacado), Custo por etapa (5 números), Canais
    (mini-funil por canal com a cor do `ChannelBadge`), Tempo e qualidade (4 números, com
    `amostra_dias` como legenda da mediana).
  - **Recolhido:** uma linha com `collapsedLine`.
  - Estado lembrado em `localStorage` (`trafego:summary-collapsed`), sempre em try/catch;
    padrão expandido.
  - Paleta da página (`#dedbd6`, `#111111`, `#7b7b78`, `#faf9f6`; cores de canal iguais
    às do `ChannelBadge`). Uma coluna no celular.
- `frontend/src/app/(authenticated)/trafego/page.tsx` — `Report` ganha
  `summary?: ReportSummary`. O bloco entra no topo da área de conteúdo, acima da tabela,
  e usa o mesmo `report` (nenhum fetch novo). Carregando: skeleton de altura fixa. Sem
  `summary` (backend antigo/erro): o bloco não aparece e a tabela continua.
  - Layout: a área de conteúdo passa a rolar (`overflow-y-auto`); o bloco é
    `flex-shrink-0` e a tabela ganha `min-h-[420px]`, para não ser espremida pelo resumo
    expandido. O thead sticky continua funcionando porque a tabela mantém a própria
    rolagem.

## Testes

- `backend/tests/test_traffic_report_summary.py` (pytest, função pura): funil e
  gargalo; divisões por zero (relatório vazio); só orgânico → custos `None`; CPL usa só
  leads pagos; dias negativos descartados, mediana com amostra; datas inválidas ignoradas;
  `nao_atribuido_pct`; ordem e omissão de canais; invariante soma dos canais == total;
  `_sales_by_lead` com `first_sold_at` (com stub do supabase); `traffic_report` inclui
  `summary`, e `_empty_report` também.
- `frontend/src/lib/traffic-summary.test.ts` (Vitest): formatadores com `null`,
  `collapsedLine`.
