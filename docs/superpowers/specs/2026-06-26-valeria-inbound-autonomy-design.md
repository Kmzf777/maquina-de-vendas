# Autonomia Global da Valéria (Inbound) — Design 2026-06-26

## Problema
A autonomia de CRM entregue em 2026-06-25 foi escopada ao funil frio (outbound). Auditoria
2026-06-26 confirmou que o **lead inbound orgânico não tem card em funil nenhum** durante a
conversa: `get_or_create_lead` cria só a linha em `leads` (stage=`pending`), e o card só nasce
no evento terminal (handoff/opt-out/perda). Além disso, o vocabulário de `key` dos funis da
Valéria era inconsistente ("Morno" = `proposta` num funil, `contato` noutro), então o reflexo
de reply e as tools de stage só funcionavam no funil frio.

## Decisões aprovadas
1. **Card no funil do segmento, com criação adiada**: o card nasce quando a IA classifica o
   segmento (`mudar_stage`), no funil correspondente (`CATEGORY_PIPELINE_NAMES`).
2. **Vocabulário de `key` unificado** em todos os funis da Valéria (mapeamento Seção 1).

## Seção 1 — Mapeamento canônico de `key` (migration 20260626)
| Conceito → key | Atacado / Private Label / Exportação | Consumo |
|---|---|---|
| `entrada` | "Entrada" (Atacado/PL) | — |
| `novo` | "Novo (Frio)" | "Novo (Frio)" |
| `respondeu` | **"Morno"** (era proposta/contato) | **"Morno"** |
| `qualificado` | **"Quente (Fechar)"** (era negociacao/proposta) | **"Quente"** |
| `fechado_ganho` | "Fechado Ganho" | "Fechado Ganho" |
| `perdido` | "Perdido" | "Perdido" |

Coluna-lixo "Novo Stage" (Atacado, vazia) removida. Funil frio mantém suas keys
(`frio`/`disparo_feito`/`respondeu`/`qualificado`/`encerrado`). As keys antigas não eram
referenciadas em código; só `stage_id_by_key`/`_perdido_stage_id` leem `key`.

## Seção 2 — Criação adiada (`mudar_stage`)
`ensure_segment_deal(lead_id, segment)` (em `leads/service.py`): só para segmentos conhecidos,
no-op se já existe deal aberto. Invocado fail-soft por `mudar_stage` após `update_lead`.

## Seção 3 — Generalização de reflexo e qualificação
- `advance_cold_deal_on_reply` → **`advance_deal_on_reply`**: avança para `respondeu` a partir
  de qualquer stage de pré-resposta (`disparo_feito`/`frio`/`entrada`/`novo`). Nunca regride.
- `marcar_interesse` → **create-or-move** via `mark_deal_qualificado(lead_id, segment)`: sem
  card, cria no funil do segmento e move para `qualificado`; com card, só move.

## Testes
`tests/test_inbound_autonomy_2026_06_26.py` (10 testes) + ajustes em
`test_cold_funnel_reflex_2026_06_25.py` e `test_pipeline_autonomy_tools_2026_06_25.py`.
Suíte completa: 1001 passed / 3 skipped.

## Fora de escopo (constraint conhecida)
Reflexo só age quando há card. Lead inbound antes da classificação de segmento permanece sem
card (de propósito — funil indefinido). Janela 24h Meta inalterada por este trabalho.
