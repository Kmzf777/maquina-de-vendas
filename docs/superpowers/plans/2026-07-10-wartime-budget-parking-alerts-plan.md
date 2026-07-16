# Plano de Implementação — Wartime T1 (Parking de exaustão) + T2 (Alertas externos)

**Spec:** `docs/superpowers/specs/2026-07-10-wartime-budget-parking-alerts-design.md`
**Branch:** `fix/wartime-budget-parking-alerts`
**Execução:** 2 pacotes de trabalho independentes (arquivos disjuntos), despachados em
paralelo via subagentes. Validação final consolidada com a suíte hermética.

---

## Pacote A — T1: Parking de exaustão (Subagente LLM/Parking)

**Arquivos:** `backend/app/agent/orchestrator.py`, `backend/app/buffer/parking.py`,
`backend/app/buffer/processor.py`, testes novos + ajuste dos existentes.

- [ ] A1. `orchestrator.py`: adicionar `LLMExhaustedError(LLMUnavailableError)` e
      `LLMQuotaExhaustedError(LLMExhaustedError)`; reclassificar `LLMBudgetExceededError`
      para herdar de `LLMExhaustedError`. Docstrings no padrão do arquivo (PT-BR,
      referência de incidente).
- [ ] A2. `_generate_with_retry`: (a) 429 com marcador de quota diária (`per day`/`PerDay`,
      case-insensitive, em `str(exc)`) → `LLMQuotaExhaustedError` imediato;
      (b) ao esgotar retries com último erro 403 ou 429-diário → `LLMQuotaExhaustedError`
      em vez de `LLMUnavailableError`. Demais caminhos intocados.
- [ ] A3. `parking.py::park_turn`: parâmetro `reason="transient"`; gravar `reason` e
      `deadline` na entrada (transient: parked_at+`LLM_PARK_MAX_MINUTES`; budget: próxima
      00:00 UTC + `LLM_PARK_EXHAUSTED_GRACE_MINUTES`; quota: próxima 00:00
      America/Los_Angeles (zoneinfo) + folga; exaustos com teto
      `LLM_PARK_EXHAUSTED_MAX_HOURS`).
- [ ] A4. `parking.py`: mensagem de espera — constante `_HOLD_MSG` (persona, minúsculas);
      envio no park quando reason exausto, com SETNX `llm:hold_msg:{conv_id}` TTL
      `LLM_HOLD_MSG_COOLDOWN_HOURS`, `save_message` no banco, skip em REHEARSAL_MODE,
      fail-soft total (falha de envio não impede o park).
- [ ] A5. `parking.py::drain_parked_llm_turns`: usar `deadline` por entrada (fallback
      legado: parked_at+30min quando ausente); reason=budget + `budget_guard.is_exceeded()`
      → skip sem API call; reason=quota → throttle via `last_attempt_at` na entrada
      (`LLM_PARK_RETRY_MINUTES`); expiração → handoff (caminho atual); guards existentes
      intocados.
- [ ] A6. `processor.py::_handle_llm_down`: parâmetro `reason="transient"`; callsites que
      capturam exceções do agente mapeiam tipo→reason; reason="budget" suprime
      `_fire_llm_down_alert` (alerta dedicado do Pacote B cobre).
- [ ] A7. Testes (padrão do repo, fakes de `tests/gemini_fakes.py` onde couber):
      classificação (429-diário imediato, 403 pós-retry, 429 comum inalterado); deadline
      por reason; mensagem de espera (1x, cooldown, rehearsal); drain (skip budget,
      throttle quota, handoff só pós-deadline, entrada legada); processor (budget → park
      sem handoff e sem llm_down).
- [ ] A8. Rodar targeted: `pytest -q tests/ -k "parking or llm_down or generate_with_retry
      or budget" -m "not integration"` + suíte de orchestrator afetada. Zero regressão.

## Pacote B — T2: Alertas de budget + despacho externo (Subagente Mensageria/Alertas)

**Arquivos:** `backend/app/agent/budget_guard.py`, `backend/app/alerts/service.py`,
testes novos.

- [ ] B1. `budget_guard.py`: `fire_budget_alert(spend, limit)` e
      `fire_budget_warning(spend, limit)` (delegam a `alerts.service`), com dedup
      in-process por dia UTC + dedup no banco (1 não-resolvido/24h, padrão
      `fire_billing_alert`). Trip → `llm_budget_exceeded` critical; ≥80% sem trip →
      `llm_budget_warning` warning. Chamados de `is_exceeded()` sem custo extra no caminho
      quente (flag antes de query).
- [ ] B2. `budget_guard.py`: virada do dia com gasto < teto → auto-resolve alertas
      `llm_budget_*` abertos (fail-soft, 1x/dia).
- [ ] B3. `alerts/service.py`: `_notify_external(...)` chamado por `create_system_alert`:
      critical → Sentry `capture_message(level="error")` + WhatsApp admin; warning → só
      Sentry. Import do sentry guardado (padrão `observability.py`); sem DSN = no-op.
- [ ] B4. WhatsApp: `ADMIN_ALERT_PHONE` (ausente = skip), canal `ALERT_CHANNEL_ID` →
      `get_channel_by_id` senão `get_active_channel()`; `provider.send_text(phone,
      "🚨 {title}\n\n{message}")`; agendamento `get_running_loop().create_task` com
      fallback `asyncio.run`; skip em REHEARSAL_MODE; fail-soft total (import tardio de
      channels/registry para não criar ciclo).
- [ ] B5. Testes: trip dispara critical 1x/dia (dedup in-process e DB); 80% dispara
      warning; auto-resolve na virada; `_notify_external` roteia por severity; WhatsApp
      no-op sem env; falha de envio não escala; Sentry ausente = no-op.
- [ ] B6. Rodar targeted: `pytest -q tests/ -k "budget or alert" -m "not integration"`.
      Zero regressão.

## Validação consolidada (Etapa 4 — orquestrador)

- [ ] V1. `pytest -q -m "not integration"` completo no backend (mesmo gate do CI).
- [ ] V2. `python -m compileall backend/app` + smoke `Settings()` (mesmo smoke do deploy).
- [ ] V3. Revisão do diff consolidado (interação A6 ↔ B1: budget park sem alerta duplo).
- [ ] V4. Atualizar `backend/.env.example` com os novos knobs documentados.

## Riscos e mitigação

- **Interseção A/B:** arquivos 100% disjuntos; único acoplamento é semântico (A6 suprime
  llm_down para budget PORQUE B1 cria o alerta dedicado) — verificado em V3.
- **Retrocompat de parking:** entradas antigas no Redis durante o deploy → fallback legado
  (A5) cobre.
- **Hot path:** alerta de budget só toca o banco 1x/dia (flag in-process primeiro).
