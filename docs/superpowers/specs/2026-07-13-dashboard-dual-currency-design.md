# Dashboard multi-moeda (USD + BRL) — design

**Data:** 2026-07-13
**Status:** aprovado
**Escopo:** `/dashboard` (frontend Next) + serviço de câmbio (backend FastAPI)

## Problema

A diretriz de negócio exige que todo valor financeiro do `/dashboard` apareça
simultaneamente em dólar e em real. A auditoria da árvore do painel mostrou que os
valores **não estão todos na mesma moeda de origem**:

| Superfície | Componente | Moeda nativa | Origem |
|---|---|---|---|
| KPI "Custo IA por handoff" | `dashboard/page.tsx` | **USD** | `dashboard_kpis.cost_per_handoff_usd` (custo de token Gemini) |
| KPI "Custo por atendimento" | `dashboard/page.tsx` | **USD** | `dashboard_kpis.cost_per_atendimento_usd` |
| KPI "Valor em vendas" | `dashboard/conversions-section.tsx` | **BRL** | `/api/conversions/dashboard` → `kpis.purchase_value` (CAPI) |
| Gráfico "Valor por origem" | `dashboard/conversions-section.tsx` | **BRL** | `value_by_traffic` |

Portanto a conversão é **bidirecional** (USD→BRL nos custos, BRL→USD nas vendas) e
nenhum dos lados chega do backend com a segunda moeda. Não existe nenhuma lógica de
câmbio no repositório hoje.

## Decisões

1. **Taxa viva, cacheada** (não constante em env). Fonte: AwesomeAPI
   (`economia.awesomeapi.com.br/json/last/USD-BRL`), cache Redis de 6h,
   **stale-if-error** — mesma disciplina do `app/agent/catalog.py`, que já serve
   preço velho em vez de derrubar o consumidor quando a fonte cai.
2. **BRL é a moeda em destaque em TODOS os cards**, inclusive nos de custo de IA que
   são nativos em USD. O público do painel pensa em reais. O valor nativo nunca some:
   aparece na linha secundária junto com a taxa usada.
3. **A conversão é sempre derivada do valor nativo**, nunca de um valor já convertido.

## Arquitetura

### Backend — `app/fx/`

Módulo raso com uma responsabilidade: devolver a cotação USD→BRL.

```
get_usd_brl() -> FxRate(rate: float, date: str, stale: bool, source: str)
```

Cadeia de resolução, nesta ordem:

1. Cache Redis (`fx:usd_brl`, TTL 6h) → serve e retorna.
2. Miss → busca AwesomeAPI (timeout 5s) → grava cache → serve.
3. Erro na API → serve o **último valor bom** (chave `fx:usd_brl:last`, sem TTL) com
   `stale=true`. Esta é a rede de segurança que impede o painel de ficar sem número.
4. Sem cache nem último-bom → `FX_USD_BRL_FALLBACK` do env (default `5.50`), com
   `stale=true` e `source="fallback"`.

O passo 4 nunca retorna erro HTTP: um painel sem custo é pior que um painel com custo
aproximado **desde que a interface diga que é aproximado** — daí o campo `stale`.

Rota: `GET /api/fx/rate` (router novo em `app/fx/router.py`, registrado no `main.py`).
Proxy Next: `frontend/src/app/api/dashboard/fx/route.ts`, mesmo padrão de
`api/conversions/dashboard/route.ts`.

### Frontend — `components/dashboard/currency.ts`

Módulo único de moeda. Substitui o `fmtUSD` artesanal do `format.ts` (que usava
`toFixed` manual) e o `fmtBRL` duplicado dentro de `conversions-section.tsx`.

```ts
fmtUSD(v: number | null): string   // Intl en-US/USD  → "$1,234.56"
fmtBRL(v: number | null): string   // Intl pt-BR/BRL  → "R$ 1.234,56"
usdToBrl(usd, rate): number
brlToUsd(brl, rate): number
dualFromUsd(usd, fx): { primary, secondary }  // primary = BRL, secondary = USD + taxa
dualFromBrl(brl, fx): { primary, secondary }  // primary = BRL, secondary = USD + taxa
```

`primary` sempre BRL; `secondary` sempre `"$X · câmbio 5,50"` (com sufixo
`" (aprox.)"` quando `fx.stale`). Valor nulo → `"—"` em ambos (nunca `NaN`, nunca
`R$ 0,00`, que seria mentira financeira).

Sem componente novo: `KpiCard` já tem `value` + `subtitle`, que mapeiam exatamente em
`primary` + `secondary`.

### Render

- Os 2 KPIs de custo: `value={dual.primary}` / `subtitle={dual.secondary}`.
- "Valor em vendas": idem, via `dualFromBrl`.
- Gráfico "Valor por origem": **eixo permanece em BRL** (empilhar dois símbolos num
  tick de eixo é ilegível); o tooltip mostra as duas moedas.
- A taxa é buscada como um 5º bloco no `refresh()` do `page.tsx`, com o mesmo
  `BlockState`. Enquanto a taxa não chega, os cards mostram só a moeda nativa — o
  painel nunca bloqueia esperando câmbio.

## Testes (TDD, antes do código)

**Frontend (`currency.test.ts`, vitest):**
- `fmtUSD(1234.56)` → `"$1,234.56"`; `fmtBRL(1234.56)` → `"R$ 1.234,56"` (NBSP do Intl normalizado).
- Custo micro (`0.0042`) não colapsa em `$0.00`.
- `usdToBrl`/`brlToUsd` exatos e round-trip dentro de 1 centavo.
- `null` → `"—"` em ambos os formatadores e nos duais.
- `stale=true` marca a linha secundária como aproximada.

**Backend (`test_fx_service.py`, pytest):**
- Cache hit não chama a API.
- API fora → serve último-bom com `stale=true`.
- Sem cache nem último-bom → fallback do env, `stale=true`, sem exceção.

## Não-escopo

- Histórico de câmbio / conversão com a taxa do dia da transação (o valor convertido é
  sempre à taxa de hoje). Se auditoria contábil exigir taxa histórica, isso vira uma
  coluna `fx_rate` gravada no momento do evento — outro projeto.
- Outras páginas (`/estatisticas`, `/vendas`) permanecem intocadas.
