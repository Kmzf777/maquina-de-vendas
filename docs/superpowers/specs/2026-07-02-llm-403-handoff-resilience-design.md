# Spec — Resiliência: 403 (billing) → handoff humano (não silêncio)

**Data:** 2026-07-02

## Problema (forense)

No incidente de 2026-07-02, o Gemini passou a responder `403 PERMISSION_DENIED`
("Lightning dunning decision is deny" — bloqueio de faturamento). Em
`orchestrator._create_with_retry`, o handler de `openai.APIStatusError` classifica como
retentável **apenas** `429` e `5xx`; qualquer outro 4xx (inclusive **403**) é **relançado cru**.
Resultado: `run_agent` propaga a exceção, o processor cai no ramo genérico `except Exception`
→ `[AGENT FAILED]` → **falha silenciosa** (lead fantasmado), SEM handoff ao humano e SEM
alerta `llm_down`. Confirmado no incidente: os 4 primeiros leads foram engolidos em silêncio.

## Requisito

Um `403` (billing/permissão negada) do provedor de LLM deve ser tratado como
**indisponibilidade do LLM** — exatamente como `429`/`5xx` já são — resultando em
`LLMUnavailableError` ao esgotar os retries. Isso reaproveita, sem alteração, o fluxo
downstream **já existente** no processor:
`except LLMUnavailableError` → `_handle_llm_down` → `encaminhar_humano` (handoff ao João,
desliga IA, cria deal, cancela follow-ups, envia cartão) **+** `_fire_llm_down_alert`
(grava `llm_down` em `system_alerts`, dedup 1/h).

## Escopo (mínimo)

- **Única mudança de código:** a classificação de status em
  `backend/app/agent/orchestrator.py::_create_with_retry` — incluir `403` no mesmo balde
  de `429`/`5xx` (retry com backoff → `LLMUnavailableError` ao esgotar).
- **NENHUMA** mudança no processor (o downstream já funciona), nem em `_handle_llm_down`,
  `_fire_llm_down_alert`, `encaminhar_humano`.

## Fora de escopo (não fazer)

- Novos sistemas/pipelines de alerta ou notificação.
- Redesenho da política de retry (backoff, nº de tentativas) — permanece igual.
- Curto-circuitar 403 sem retry — mantemos paridade com o comportamento de `429`
  (retry-then-unavailable) para minimizar a mudança.
- Tratar outros 4xx (400/401/404) — continuam relançados crus.

## Comportamento esperado (contrato de teste)

- `403` seguido de sucesso → retorna a resposta (foi retentado).
- `403` persistente (esgota tentativas) → levanta `LLMUnavailableError`.
- `400` persistente → relançado cru como `openai.BadRequestError` (inalterado).
- `429`/`5xx` → inalterado (regressão coberta pelos testes existentes).
