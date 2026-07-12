# Custo de IA em Reais (R$) no dashboard /estatisticas

**Data:** 2026-07-12 · **Motivação:** conciliação de olho com o Console Google Cloud Brasil (fatura em R$ com impostos embutidos). Conciliação de referência: 11/07 — $2,39 rastreado ⇒ R$ 13,70 faturado ⇒ multiplicador efetivo **5,73** (câmbio + IOF/ISS).
**Regra de Ouro:** a visualização em dólar NÃO muda. O R$ é uma camada ADICIONAL, estimada, secundária.

## Escopo (o que ganha R$)

| Elemento | Ganha R$? | Racional |
|---|---|---|
| Card "LLM / IA" (summary) | **Sim** — linha secundária sob o valor USD | É o número que bate com a fatura Google |
| Linha "LLM / IA" da tabela de detalhamento | **Sim** — texto pequeno sob o USD | Mesmo propósito |
| Cards Marketing/Utilidade WPP e "Total Operacional" | **Não** | São fatura da META (outra moeda/nota); converter misturaria duas faturas e quebraria a conciliação |
| Gráficos diários | **Não** (intocados) | Diretriz explícita |
| Aviso âmbar "Todos os valores em USD" | Texto complementado (1 frase) para explicar a estimativa em R$ | Evita que o aviso fique factualmente errado |

## Arquitetura

1. **Camada de dados (Trilha A):** `frontend/src/lib/stats-mappers.ts` (já é o lar dos preços/constantes de custo) ganha:
   - `DEFAULT_USD_TO_BRL_WITH_TAX = 5.73` (derivado da conciliação real de 11/07, não do câmbio puro);
   - `resolveBrlMultiplier(raw?: string)` — parse defensivo do env (`NaN`/<=0 → default);
   - campo novo **`total_cost_brl`** (+ `brl_multiplier` para o rótulo) no retorno de `mapCostsSummary`, calculado com multiplicador injetado (mapper permanece puro);
   - `formatBRL(value)` — `Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" })`.
   A rota `frontend/src/app/api/stats/costs/route.ts` lê `process.env.CUSTO_IA_MULTIPLICADOR_BRL` (server-side, Node) e injeta no mapper. Rotas daily/breakdown/top-leads inalteradas.
2. **Camada visual (Trilha B):** `estatisticas/page.tsx` — no card LLM/IA, abaixo do valor USD (24px, intocado), linha `≈ R$ 13,70 · est. câmbio+impostos` em 12px cinza; na tabela, sob o USD da linha LLM/IA, `≈ R$ …` em 11px. Interface `ai` do estado ganha `total_cost_brl?: number` (opcional → tolera payload antigo em cache).
3. **Env:** `CUSTO_IA_MULTIPLICADOR_BRL` documentado em `frontend/.env.example` (default 5,73 no código — funciona sem env). Knob ajustável quando o câmbio/imposto mudar, sem deploy de código (só restart).

## Fora de escopo
Conversão dos custos Meta/WhatsApp; BRL nos gráficos; taxa de câmbio dinâmica via API externa (dependência/latência sem valor para estimativa de conciliação).

## Testes (vitest)
- `resolveBrlMultiplier`: default sem env, parse de valor válido, fallback em lixo/zero/negativo.
- `mapCostsSummary`: `total_cost_brl = round4(total_cost × mult)` e presença de `brl_multiplier`; payload USD byte-idêntico ao anterior nos campos existentes.
- `formatBRL`: "R$ 13,70" (vírgula decimal, símbolo pt-BR) — normalizando o NBSP do Intl.
