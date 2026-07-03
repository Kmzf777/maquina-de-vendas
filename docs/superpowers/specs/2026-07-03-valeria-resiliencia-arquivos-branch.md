# Arquivos da branch `feat/valeria-etapa1-watchdog` (programa Valéria — Resiliência)

> Para coordenação de time: evitar mexer nos arquivos abaixo até esta branch ir para master.
> Branch LOCAL (ainda não pushada). Base: master `cef6788`. Push será direto para master (fluxo do repo), com merge/reconciliação do master mais novo antes.

## ✅ Já alterados (commitados na branch)

**Código:**
| Arquivo | O quê |
|---|---|
| `backend/app/agent/orchestrator.py` | retry 2º degrau (temp 0.9 + nudge), call_type de retry, fallback de reengajamento por stage, guard de mídia same-turn ciente de falha |
| `backend/app/agent/tools.py` | constantes do supervisor públicas (`SUPERVISOR_NAME/PHONE`, aliases mantidos) |
| `backend/app/agent/token_tracker.py` | docstring de call_type (sem mudança de runtime) |
| `backend/app/buffer/processor.py` | contador/alerta `llm_down` no ramo `[AGENT FAILED]`; mensagem-ponte pós-handoff (`sent_by="bridge"`, cooldown Redis) |
| `backend/app/buffer/manager.py` | timers de flush supervisionados (`[BUFFER TIMER DIED]`, pop com guard de identidade) |
| `backend/app/buffer/recovery.py` **(novo)** | recovery de buffers órfãos reutilizável (startup + watchdog) |
| `backend/app/watchdog/` **(novo módulo)** | watchdog fim-a-fim: ai_unresponsive, orphan_lead_reply, followup_jobs_stuck + varredura de buffers (paginação/chunking) |
| `backend/app/main.py` | lifespan: task do watchdog + recovery importado do módulo novo |
| `backend/app/follow_up/scheduler.py` | 1 comentário (sem runtime) |

**Testes:** 12 arquivos novos `backend/tests/test_{watchdog_*,buffer_recovery_*,orchestrator_{retry2,fallback_reengage,media_once_per_turn,composto},processor_{agent_failed_llm_counter,handoff_bridge}}_2026_07_0*.py` + ajustes mecânicos em 9 existentes (contagem de chamadas por causa do retry novo; nenhum comportamento de teste enfraquecido).

**Docs:** `docs/superpowers/plans/2026-07-0{2,3}-valeria-*.md` (5 planos — sem conflito de código).

## 🔧 Em alteração AGORA (task em andamento)

- `backend/app/watchdog/service.py` — check 5 (SLA de resposta humana pós-handoff)
- `backend/app/follow_up/service.py` — janela própria do handoff_rescue (até 20h)
- novos: `backend/tests/test_watchdog_handoff_sla_2026_07_03.py`, `backend/tests/test_handoff_rescue_window_2026_07_03.py`

## 🔜 Ainda serão alterados (planejado nesta branch)

**Frente B3 (follow-up pós-preço):**
- `backend/app/agent/tools.py` (flag `_quote_executed` no `calcular_orcamento`)
- `backend/app/buffer/processor.py` (gatilho determinístico de follow-up)
- novo teste `test_processor_price_followup_2026_07_03.py`

**Frente C (prompts/tools):**
- `backend/app/agent/prompts/base.py`
- `backend/app/agent/prompts/valeria_inbound/{secretaria,consumo,atacado,private_label}.py`
- `backend/app/agent/pricing.py` (`match_products` por tokens)
- `backend/app/agent/tools.py` (mensagem de not-found do orçamento)
- `backend/app/lp_webhook/service.py` + `backend/app/leads/service.py` (higiene de nome)
- `backend/app/follow_up/scheduler.py` (fallback de nome nos templates)
- novos testes `test_prompts_frente_c_*.py`, `test_match_products_tokens_*.py`, `test_name_hygiene_*.py`

**Etapa RLS (fase 3):** só `backend/migrations/` (arquivo novo) + docs/runbook — sem código de app.

## ⚠️ Zona de conflito alto — evitar tocar até o merge

`orchestrator.py`, `processor.py`, `tools.py`, `watchdog/*`, `follow_up/{service,scheduler}.py`, `prompts/base.py`, `prompts/valeria_inbound/*`, `buffer/{manager,recovery}.py`.

## Nota de reconciliação

O master já avançou em paralelo (outra frente: `broadcast/worker.py`, migração RLS `messages/conversations`, `test_broadcast_reply_metrics.py`) — sem interseção com os arquivos acima até agora; faremos merge do master na branch antes do push, como já foi feito uma vez (`e66341b`).
