# Etapa 1 — Watchdog fim-a-fim + hardening do buffer + contador em [AGENT FAILED]

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para implementar task a task. Steps usam checkbox (`- [ ]`).

**Goal:** O apagão de 01–02/07 (leads sem resposta por até 21h) foi invisível: mensagens salvas, `mark_read` ok, 1–2 pulsos de `typing_on` e morte silenciosa do turno em ~10–20s (assinatura de `run_agent` falhando rápido 3× no caminho genérico `[AGENT FAILED]`, que não conta no alerta `llm_down`). Esta etapa torna QUALQUER variante desse silêncio detectável (watchdog fim-a-fim lendo o banco), endurece os timers do buffer (única infra sem supervisão) e fecha o buraco de observabilidade do `[AGENT FAILED]`.

**Architecture:** (1) novo módulo `app/watchdog/service.py` com loop asyncio no lifespan (mesmo padrão do `run_flusher`), 3 checks de banco + varredura periódica de buffers órfãos; (2) `app/buffer/recovery.py` extraído de `main.py::_recover_orphaned_buffers` com guarda `require_no_deadline` para uso periódico seguro; (3) try/except/finally em `manager.py::_wait_and_flush`; (4) contador `llm:consecutive_failures` também incrementado no ramo `[AGENT FAILED]` do processor. Nenhuma migração de banco. Nenhuma mudança de comportamento no caminho feliz.

**Tech Stack:** Python 3.11, FastAPI lifespan, redis.asyncio, supabase-py (PostgREST — sem SQL cru), pytest (asyncio_mode=auto).

## Global Constraints

- Rodar testes com `python -m pytest ...` a partir de `backend/`, sempre com `-m "not integration"` quando rodar a suíte ampla.
- Baseline atual: 1344 passed. Nenhum teste existente pode quebrar.
- Alertas SEMPRE via `app.alerts.service.create_system_alert`, com dedup "1 alerta não-resolvido do mesmo type por hora" espelhando `processor._fire_llm_down_alert`. Fail-soft: falha no check de dedup → loga e cria o alerta mesmo assim; falha no insert já é engolida por `create_system_alert`.
- Watchdog é 100% read-only no banco (exceto inserts em `system_alerts`). Erro em um check NUNCA derruba os outros nem o loop.
- `REHEARSAL_MODE=true` desliga o watchdog (loop só dorme) — mesmo padrão de `schedule_handoff_rescue`.
- Timestamps do Supabase: comparar SEMPRE via `datetime.fromisoformat(ts.replace("Z", "+00:00"))` (nunca comparação de string — microsegundos/offset variam).
- Escopo de ambiente: checks de `follow_up_jobs` filtram `env_tag` = `"dev" if get_settings().is_dev_env else "production"` (mesmo `_ENV_TAG` de `follow_up/service.py`).
- NÃO alterar: a classificação de status em `_create_with_retry` (403 já tratado — commit 02f26af), `_handle_llm_down`, `encaminhar_humano`, fluxo de re-coalescing.
- No ramo `[AGENT FAILED]` NÃO adicionar handoff automático — apenas contador+alerta (o handoff automático é exclusivo de `LLMUnavailableError`, decisão do plano aprovado).
- Constantes nomeadas no topo do módulo (sem números mágicos inline): `WATCHDOG_INTERVAL_SECONDS=60`, `AI_UNRESPONSIVE_GRACE_MINUTES=5`, `AI_UNRESPONSIVE_LOOKBACK_HOURS=24`, `ORPHAN_REPLY_GRACE_MINUTES=30`, `STUCK_JOB_HOURS=2`, `ALERT_DEDUP_HOURS=1`.
- Novos testes seguem o padrão de mocks do repo: estudar `backend/tests/test_processor_llm_down_handoff_2026_07_01.py` e `backend/tests/conftest.py` ANTES de escrever (fakes de supabase por tabela + AsyncMock; nada de rede real).

## Contexto de produção que motivou os checks (casos reais, para fixtures)

- **Welita (Check 1):** mensagem do lead 01/07 17:41 salva, canal `mode='ai'`, `ai_enabled=true`, resposta só 02/07 14:45 (21h). Nenhum alerta existiu.
- **Rafael Reis Silva (Check 2):** lead com `ai_enabled=false`, `human_control=false`, `opt_out=false` respondeu "oii" ao disparo de LP e ficou 25h+ sem qualquer resposta (nem IA nem humano).
- **Jobs presos (Check 3):** 4 jobs `standard` `pending` com `fire_at` de 26/05 (env_tag=dev, "Rehearsal Lead") apodreceram invisíveis. A limpeza deles em prod é operação manual pendente (MCP read-only): `UPDATE follow_up_jobs SET status='cancelled', cancel_reason='stale_dev_rehearsal_cleanup_2026-07-02' WHERE id IN ('ba0bdfa5-2d3a-40cd-9ee8-e8617a098045','5555dbe9-81db-49a6-9149-6b1822f8dcb3','b9d23e5e-e9d4-4e04-8916-d706e62d4f21','d951987a-4314-4a9a-9989-ac4d2610a286') AND status='pending';`
- **Apagão (Check 4 + buffer):** durante o gap houve `mark_read` + 1–2 `typing_on` por turno e zero `send_text`/`token_usage`/alerta → morte rápida no caminho genérico do processor. A rajada de recuperação (14:45) coincide com restart; `_recover_orphaned_buffers` só roda no startup e os timers `_wait_and_flush` morrem sem log.

---

## Task 1: Buffer hardening — timer supervisionado + recovery reutilizável

**Files:**
- Create: `backend/app/buffer/recovery.py`
- Modify: `backend/app/main.py` (remover `_recover_orphaned_buffers` local; importar do novo módulo)
- Modify: `backend/app/buffer/manager.py` (`_wait_and_flush`)
- Test: `backend/tests/test_buffer_recovery_hardening_2026_07_02.py`

**Interfaces:**
- Produces: `async def recover_orphaned_buffers(redis, *, require_no_deadline: bool = False, source: str = "startup") -> int` — mesma semântica da função atual de `main.py` (scan `buffer:*`, pula sufixos `:lock`/`:deadline`, pula chave malformada, pula se `:lock` existe, drena lista + `pending_wamid`/`pending_quoted`, `asyncio.create_task(process_buffered_messages(...))`, retorna quantos buffers recuperou; logs `[BUFFER RECOVERY]` incluem `source`). NOVO comportamento opcional: com `require_no_deadline=True`, também pula quando `buffer:{phone}:{channel_id}:deadline` existe (não briga com timer vivo — deadline presente = janela de buffer ainda ativa).
- `main.py` chama `await recover_orphaned_buffers(app.state.redis, require_no_deadline=False, source="startup")` — comportamento de startup preservado byte-a-byte nos efeitos.
- `manager.py::_wait_and_flush`: corpo inteiro em `try/except Exception` → `logger.error("[BUFFER TIMER DIED] phone=%s channel=%s: %s", phone, channel_id, exc, exc_info=True)` sem propagar; `finally` garante `_active_timers.pop(timer_key, None)` (hoje o pop só acontece no caminho feliz — timer que morre vaza referência).

- [ ] **Step 1: Testes que falham** — `test_buffer_recovery_hardening_2026_07_02.py` com um FakeRedis mínimo (dict-backed: `scan`, `exists`, `lrange`, `delete`, `get`, `rpush` conforme necessário; métodos async). Casos:
  1. timer morto: FakeRedis cujo `exists` lança `RuntimeError` → `await _wait_and_flush(...)` NÃO propaga; `caplog` contém `[BUFFER TIMER DIED]`; `_active_timers` não contém a key.
  2. `recover_orphaned_buffers(require_no_deadline=True)` com `buffer:X:Y:deadline` presente → NÃO drena (lista permanece, `process_buffered_messages` não chamado — patch com AsyncMock).
  3. `require_no_deadline=True`, sem lock/deadline, lista com 1 item e `pending_wamid`/`pending_quoted` setados → drena: deleta chaves, chama `process_buffered_messages(phone, combined, channel_id, wamid=..., quoted_wamid=...)`, retorna 1. (Para determinismo: patch `asyncio.create_task` para executar/registrar a coroutine.)
  4. `require_no_deadline=False` (startup) com deadline presente e sem lock → DRENA (comportamento atual preservado).
  5. chave com `:lock` presente → pula; chave malformada `buffer:soUmaParte` → pula sem erro.
- [ ] **Step 2: Rodar e ver falhar** — `python -m pytest tests/test_buffer_recovery_hardening_2026_07_02.py -q` (import error / asserts).
- [ ] **Step 3: Implementar** — criar `recovery.py` (mover lógica de `main.py`, adicionar guarda deadline + `source` no log), atualizar `main.py` (import + chamada; apagar função local), endurecer `_wait_and_flush` (try/except/finally).
- [ ] **Step 4: Rodar e ver passar** — o arquivo novo + `python -m pytest tests -q -m "not integration" -k "buffer or manager or recoalesce"` (regressão da área).
- [ ] **Step 5: Commit** — `git add backend/app/buffer/recovery.py backend/app/buffer/manager.py backend/app/main.py backend/tests/test_buffer_recovery_hardening_2026_07_02.py` + commit `feat(buffer): timers supervisionados + recovery de orfaos reutilizavel (Etapa1 A1)`.

---

## Task 2: Watchdog fim-a-fim (`app/watchdog/service.py` + wiring no lifespan)

**Files:**
- Create: `backend/app/watchdog/__init__.py` (vazio), `backend/app/watchdog/service.py`
- Modify: `backend/app/main.py` (lifespan: criar/cancelar `watchdog_task` espelhando o flusher)
- Test: `backend/tests/test_watchdog_checks_2026_07_02.py`

**Interfaces (consome):** `get_supabase()` (`app.db.supabase`), `create_system_alert` (`app.alerts.service`), `recover_orphaned_buffers` (`app.buffer.recovery`, Task 1), `get_settings().is_dev_env`.

**Design (funções puras de check, testáveis sem o loop):**

```python
async def run_watchdog(app) -> None            # loop: a cada tick chama os 4 itens, cada um em try/except próprio
def check_ai_unresponsive(now) -> int          # Check 1 — retorna nº de conversas em violação (0 = ok)
def check_orphan_lead_reply(now) -> int        # Check 2
def check_stuck_followup_jobs(now) -> int      # Check 3
def _alert_recently_fired(alert_type) -> bool  # dedup: system_alerts type=X, resolved=false, created_at > now-1h
def _parse_ts(value) -> datetime               # fromisoformat com replace("Z","+00:00")
```

**Check 1 — `ai_unresponsive` (caso Welita), estratégia PostgREST em 3 passos (sem NOT EXISTS):**
1. Candidatas: `messages.select("conversation_id, created_at").eq("role","user").gte("created_at", now-24h).lte("created_at", now-5min).order("created_at", desc=True).limit(500)`; em Python, reduzir à ÚLTIMA mensagem de user por `conversation_id`.
2. Escopo: `conversations.select("id, channels!inner(mode), leads!inner(ai_enabled, opt_out, name)").in_("id", ids)`; manter só `mode=='ai'` e `ai_enabled is True`.
3. Respostas: `messages.select("conversation_id, created_at").in_("conversation_id", ids_restantes).in_("role", ["assistant","system"]).gte("created_at", <menor created_at candidato>)`; em Python, conversa está violada se NÃO existe resposta com `_parse_ts(resp) > _parse_ts(candidata)`.
Violadas > 0 e sem dedup → `create_system_alert("ai_unresponsive", "IA sem resposta a leads", f"{n} conversa(s) com mensagem de lead sem resposta há mais de {GRACE}min no canal de IA. Verifique backend/worker/LLM (apagão 01-02/07 teve essa assinatura).", severity="critical", metadata={"conversation_ids": ids[:10]})`.

**Check 2 — `orphan_lead_reply` (caso Rafael):** mesmo esqueleto do Check 1, com filtro de lead `ai_enabled is False and human_control is False and opt_out is False` (buscar `leads!inner(ai_enabled, human_control, opt_out, name)`), grace 30min, `severity="warning"`, type `orphan_lead_reply`, mensagem citando que o lead respondeu com IA desligada e sem dono. Pós-handoff (`human_control=true`) NÃO alerta (é o estado esperado; a ponte B1 é outra etapa).

**Check 3 — `followup_jobs_stuck`:** `follow_up_jobs.select("id, job_type, fire_at").eq("status","pending").eq("env_tag", _ENV_TAG).lte("fire_at", now-2h).limit(50)` → alerta `followup_jobs_stuck` (warning) com count e job_types distintos em metadata.

**Loop `run_watchdog(app)`:** se `os.environ.get("REHEARSAL_MODE") == "true"`: apenas `await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)` por tick. Senão: cada check em try/except (log `[WATCHDOG] check X falhou: ...`), depois `await recover_orphaned_buffers(app.state.redis, require_no_deadline=True, source="watchdog")` (também em try/except), depois sleep. `asyncio.CancelledError` → re-raise.

**Wiring `main.py`:** `watchdog_task = asyncio.create_task(run_watchdog(app))` logo após o flusher; no shutdown, cancel + `await` com supressão de `CancelledError` (idêntico ao flusher).

- [ ] **Step 1: Testes que falham** — `test_watchdog_checks_2026_07_02.py` (fakes de supabase por tabela, espelhando conftest/estilo do repo):
  1. **Welita:** user msg 21h atrás, canal ai, `ai_enabled=true`, sem resposta → `check_ai_unresponsive` retorna 1 e insere alerta `ai_unresponsive` (capturar insert no fake).
  2. resposta `assistant` posterior → 0, sem alerta; resposta `system` posterior (descarte) → 0, sem alerta.
  3. user msg 2min atrás (< grace) → 0.
  4. dedup: alerta `ai_unresponsive` não-resolvido criado há 10min já existe → check detecta violação mas NÃO insere segundo alerta.
  5. canal `mode='human'` → 0; lead `ai_enabled=false` → 0 (não é escopo do Check 1).
  6. **Rafael:** `ai_enabled=false, human_control=false, opt_out=false`, msg 40min atrás sem resposta → `check_orphan_lead_reply` retorna 1 + alerta warning; variantes `human_control=true` → 0; `opt_out=true` → 0.
  7. job `pending` com `fire_at` 3h atrás e `env_tag` do ambiente → 1 + alerta; `env_tag` diferente → 0.
  8. `run_watchdog` com REHEARSAL_MODE=true → nenhum check chamado em 1 tick (patch dos checks + sleep que levanta CancelledError no 1º await para encerrar o loop).
  9. `run_watchdog` tick normal → chama os 3 checks + `recover_orphaned_buffers(..., require_no_deadline=True, source="watchdog")` mesmo se o 1º check lançar (isolamento de falha).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `service.py` + wiring em `main.py`.
- [ ] **Step 4: Rodar e ver passar** + regressão: `python -m pytest tests -q -m "not integration" -k "watchdog or buffer or main"`.
- [ ] **Step 5: Commit** — `feat(watchdog): deteccao fim-a-fim de inbound sem resposta + leads orfaos + jobs presos (Etapa1 A1)`.

---

## Task 3: Contador llm_down no ramo genérico `[AGENT FAILED]` (Check 4)

**Files:**
- Modify: `backend/app/buffer/processor.py` (ramo `else` do loop de tentativas em `process_buffered_messages`, junto do log `[AGENT FAILED]`, ~L922-930)
- Test: `backend/tests/test_processor_agent_failed_llm_counter_2026_07_02.py`

**Interfaces:** consome `_record_llm_failure`, `_fire_llm_down_alert`, `_LLM_DOWN_ALERT_THRESHOLD` (todos já existem no próprio processor). O caminho de sucesso já chama `_reset_llm_failures()` — inalterado.

**Mudança exata:** dentro do `else` (todas as `_AGENT_MAX_ATTEMPTS` esgotadas), após o `logger.error(...)` e ANTES de `pop_interest_marked`/return, adicionar bloco fail-soft:

```python
try:
    _count = await _record_llm_failure()
    if _count >= _LLM_DOWN_ALERT_THRESHOLD:
        _fire_llm_down_alert(_count)
except Exception as _exc:
    logger.warning("[LLM DOWN] falha ao registrar contador pós-AGENT FAILED: %s", _exc)
```

Atualizar o comentário do `_LLM_FAILURE_KEY` mencionando que o contador cobre ambos os ramos (LLMUnavailableError E [AGENT FAILED] genérico — assinatura do apagão 01-02/07: 400/401 relançado cru ou exceção pré-API morre aqui sem rastro).

- [ ] **Step 1: Testes que falham** — espelhar mocks de `test_processor_llm_down_handoff_2026_07_01.py`:
  1. `run_agent` lança `RuntimeError` 3×, `asyncio.sleep` mockado → `_record_llm_failure` chamado exatamente 1× ao esgotar; com retorno 3 (>= threshold) → `_fire_llm_down_alert(3)` chamado.
  2. retorno 1 (< threshold) → `_fire_llm_down_alert` NÃO chamado.
  3. NÃO chama `execute_tool`/handoff nesse ramo (assert de não-chamada — diferencia do ramo LLMUnavailableError).
  4. `_record_llm_failure` lançando → função retorna normalmente (fail-soft), log de warning presente.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** (bloco acima + comentário).
- [ ] **Step 4: Rodar e ver passar** + regressão: `python -m pytest tests/test_processor_agent_failed_llm_counter_2026_07_02.py tests/test_processor_llm_down_handoff_2026_07_01.py tests/test_llm_retry_resilience_2026_07_01.py -q`.
- [ ] **Step 5: Commit** — `fix(processor): [AGENT FAILED] generico agora conta no llm_down (buraco do apagao 01-02/07) (Etapa1 A1)`.

## Follow-ups pós-review final (rastreados, NÃO bloqueiam este merge)
- [ ] check_ai_unresponsive: janela candidata `limit(500)` order-desc pode gerar MISS completo de conversa fantasma sob rajada >500 msgs respondidas/24h — fix correto é paginação/chunking do passo 1 + `.in_()` em lotes (review final, Issue 3).
- [ ] passo 3 (fetch de respostas) sem `.order`/`.limit` explícitos — adicionar junto da paginação acima (Issue 5).
- [ ] `leads(name)`/`opt_out` buscados e não usados nos embeds dos checks — enxugar na próxima passada (Issue 6).
