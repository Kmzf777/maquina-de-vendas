# Dashboard de Custos Operacionais — Spec

**Data:** 2026-05-23
**Branch:** `feat/dashboard-custos`
**Rota:** `/estatisticas`

---

## Contexto

A página `/estatisticas` exibe atualmente apenas custos de IA (token_usage). O objetivo é transformá-la em um dashboard financeiro completo que cubra **duas fontes de custo**:

1. **WhatsApp / Meta Cloud API** — apenas `send_template` com `success=true` é cobrado:
   - Marketing: **$0.0617 / mensagem**
   - Utility: **$0.0067 / mensagem**
2. **LLM / IA (Gemini/GPT)** — já rastreado via tabela `token_usage` e endpoints `/api/stats/costs*`.

---

## Fontes de dados

### Custos de WhatsApp

Tabela `meta_webhook_logs`:
- Filtro: `direction = 'outbound'`, `request_type = 'send_template'`, `success = true`
- Extração do nome do template: `payload -> 'template' ->> 'name'`
- JOIN com `message_templates` (coluna `category`: `MARKETING` ou `UTILITY`) pelo nome do template
- Templates sem match em `message_templates` → fallback: `MARKETING` (conservador)

Constantes de preço (definidas no backend):
```python
WHATSAPP_MARKETING_PRICE = 0.0617
WHATSAPP_UTILITY_PRICE   = 0.0067
```

### Custos de IA

Endpoints existentes em `/api/stats/` (sem modificação):
- `GET /api/stats/costs` → resumo: `total_cost`, `total_calls`, `total_tokens`
- `GET /api/stats/costs/daily` → série temporal diária

---

## Novos endpoints de backend

### `GET /api/stats/whatsapp`

Query params: `start_date`, `end_date`

Lógica:
1. Seleciona todos os `meta_webhook_logs` com `direction='outbound'`, `request_type='send_template'`, `success=true`, no período
2. Extrai `payload -> 'template' ->> 'name'` de cada linha
3. Busca `message_templates` filtrando pelos nomes encontrados → mapa `name → category`
4. Classifica cada log como MARKETING ou UTILITY
5. Calcula custos

Resposta:
```json
{
  "marketing_count": 412,
  "marketing_cost": 25.42,
  "utility_count": 87,
  "utility_cost": 0.58,
  "total_whatsapp_cost": 26.00
}
```

### `GET /api/stats/whatsapp/daily`

Query params: `start_date`, `end_date`

Resposta:
```json
{
  "data": [
    { "date": "2026-05-01", "marketing_cost": 3.20, "utility_cost": 0.07, "total": 3.27 }
  ]
}
```

Ambos os endpoints ficam em `backend/app/stats/router.py` com `require_role(["admin"])` já herdado pelo router.

---

## Frontend — Layout

### Cabeçalho
- Título: "Custos Operacionais"
- Subtítulo: "WhatsApp + IA"
- Filtros de período: Hoje / 7 dias / 30 dias / Personalizado (dois date inputs)

### Cards de resumo (4 shadcn `Card`)
| Card | Valor |
|------|-------|
| Marketing WPP | `marketing_cost` formatado em USD |
| Utilidade WPP | `utility_cost` formatado em USD |
| LLM / IA | `ai_cost` formatado em USD |
| Total Operacional | soma dos 3 |

### Gráfico — Custo diário combinado (recharts `LineChart`)
- Eixo X: data
- 3 linhas: Marketing WPP, Utilidade WPP, IA — cores distintas
- Tooltip com valor em USD

### Tabela de detalhes (shadcn `Table`)
| Categoria | Qtd. | Tokens/Chamadas | Custo |
|-----------|------|-----------------|-------|
| Marketing WPP | N msgs | — | $X.XX |
| Utilidade WPP | N msgs | — | $X.XX |
| LLM / IA | N chamadas | X tokens (N input / N output) | $X.XX |
| **Total** | | | **$X.XX** |

### Loading state
- 4 shadcn `Skeleton` no lugar dos cards
- Skeleton no lugar do gráfico (altura fixa)
- Skeleton no lugar da tabela (3 linhas)

---

## Componentes shadcn a adicionar

Os seguintes componentes precisam ser instalados via CLI do shadcn:
- `card`
- `table`
- `skeleton`

O projeto já tem: `button`, `badge`, `switch`, `tooltip`.

---

## Dados em paralelo

O `fetchData()` do frontend chama em `Promise.all`:
1. `GET /api/stats/costs?{params}` → custos de IA
2. `GET /api/stats/whatsapp?{params}` → custos de WhatsApp (resumo)
3. `GET /api/stats/costs/daily?{params}` → série diária de IA
4. `GET /api/stats/whatsapp/daily?{params}` → série diária de WhatsApp

O frontend combina as duas séries diárias num único array para o gráfico.

---

## Arquivos modificados / criados

| Arquivo | Mudança |
|---------|---------|
| `backend/app/stats/router.py` | Adiciona 2 endpoints: `/whatsapp` e `/whatsapp/daily` |
| `frontend/src/app/(authenticated)/estatisticas/page.tsx` | Reescrita completa |
| `frontend/src/components/ui/card.tsx` | Novo (shadcn add card) |
| `frontend/src/components/ui/table.tsx` | Novo (shadcn add table) |
| `frontend/src/components/ui/skeleton.tsx` | Novo (shadcn add skeleton) |

---

## Fora de escopo

- Tabela "Top Leads por Custo" (removida — não é foco financeiro operacional)
- Gráficos "por Stage" e "por Modelo" (removidos — não são custo operacional)
- Custo de mensagens `send_text`, `send_image`, `send_audio` (confirmado: gratuitos)
- Integração Evolution API (ignorada conforme CLAUDE.md)
- Sistema de billing/faturamento no banco de dados
