# Onda 2 — Resiliência e Inteligência da Valéria Outbound — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar as seis frentes pendentes da Onda 2: ressuscitar a cadência multi-touch (morta desde 26/06 por check constraint), D+1 "Sim-e-sumiu", estacionamento de turnos no LLM-down, ponta morta de número errado (72h→optout), tool `registrar_indicacao`, backfill do dossiê e QA diário no watchdog.

**Architecture:** Cada frente é um subsistema independente com testes próprios; nenhuma muda contrato de outra. O parking usa Redis (hash `llm:parked`) com drain no tick do worker; a cadência ganha uma variante outbound com nudge de +18h; o dossiê passa a consumir histórico completo quando não há dossiê prévio; o watchdog ganha um check diário informativo.

**Tech Stack:** Python 3.11 / FastAPI / supabase-py / redis.asyncio / pytest.

## Global Constraints

- Template HSM do João permanece INTOCADO (categoria Utilidade Meta) — humanização só em free-form.
- Todo side-effect que atesta entrega nasce no DESPACHO, nunca no enfileiramento (lição Wander 54a734a).
- Guards de dados: `isinstance(res.data, list) and res.data` (MagicMock truthiness).
- Fail-soft em todo caminho de fallback: nada pode escalar acima do turno.
- Env kill-switches para comportamento novo em produção (`LLM_PARKING`).
- Fluxo git: branch → testes → `git pull origin master` → `git push origin branch:master` (deploy automático).

---

### Task 1: Migração — relaxar `follow_up_jobs_sequence_check` (root fix da cadência morta)

**Files:**
- Create: `supabase/migrations/20260709_followup_sequence_4_touches.sql`

**Causa raiz (evidência 09/07):** constraint em prod `CHECK (sequence = ANY (ARRAY[1,2]))`; a cadência de 4 toques (f54507c, 26/06) insere sequences 1-4 → 23514 em TODO agendamento desde 26/06 (zero jobs `standard` no histograma; logs `[FOLLOWUP] Erro ao inserir jobs ... follow_up_jobs_sequence_check`).

- [ ] SQL: `ALTER TABLE follow_up_jobs DROP CONSTRAINT follow_up_jobs_sequence_check; ALTER TABLE follow_up_jobs ADD CONSTRAINT follow_up_jobs_sequence_check CHECK (sequence >= 1 AND sequence <= 9);`
- [ ] Aplicar em PROD (tshmvxxxyxgctrdkqvam) e HOMOLOG (mosbwmsqfcwqdypucgtc) via Management API.
- [ ] Verificar: re-consultar pg_constraint.

### Task 2: Cadência outbound com nudge D+1 "Sim-e-sumiu"

**Files:**
- Modify: `backend/app/follow_up/cadence.py` (OUTBOUND_NUDGE Touch + param `outbound` em build_touch_jobs)
- Modify: `backend/app/follow_up/service.py` (schedule_followup ganha `outbound: bool = False`)
- Modify: `backend/app/buffer/processor.py` (trigger outbound passa `outbound=True`)
- Test: `backend/tests/test_onda2_cadencia_outbound_2026_07_09.py`

**Interfaces:** `build_touch_jobs(now, conversation_id, lead_id, channel_id, env_tag, warm=True, outbound=False, rng=_random) -> list[dict]`; quando `outbound=True` e `warm=False`, o primeiro toque é `Touch(1, timedelta(hours=18), None, "retomar_pos_sim", ...)` seguido de CADENCE[1:]; monotonicidade MIN_GAP preservada. `schedule_followup(..., outbound=False)` repassa. Processor: `_schedule_followup(..., warm=warm, outbound=is_outbound)`.

- [ ] Testes: nudge presente com offset +18h clampado; sequences ≤ 4; warm outbound mantém T1 padrão; monotonic gap.
- [ ] Implementar; suíte de follow-up verde.

### Task 3: Parking de turnos no LLM-down (substitui handoff imediato)

**Files:**
- Create: `backend/app/buffer/parking.py`
- Modify: `backend/app/buffer/processor.py` (`_handle_llm_down` estaciona em vez de handoff quando `LLM_PARKING != off`)
- Modify: `backend/app/broadcast/worker.py` (tick chama `drain_parked_llm_turns()`)
- Test: `backend/tests/test_onda2_llm_parking_2026_07_09.py`

**Interfaces:** `park_turn(conversation: dict, lead: dict, phone: str, inbound_text: str | None) -> bool`; `drain_parked_llm_turns(now=None) -> int` (retorna nº de entradas resolvidas); Redis hash `llm:parked` field=conversation_id value=JSON {lead_id, phone, channel_id, text, stage, parked_at}. Env: `LLM_PARKING` (default on), `LLM_PARK_MAX_MINUTES` (default 30).

Regras do drain, por entrada: (a) lead com ai_enabled=false → pop sem ação (humano assumiu); (b) mensagem assistant/system mais nova que parked_at → pop (turno superseded); (c) tentativa `run_agent` → sucesso: bolhas via split_into_bubbles + send_text (gap 2s) + save_message(sent_by="agent") + pop + reset contador; (d) LLMUnavailableError: idade > LLM_PARK_MAX_MINUTES → pop + handoff `encaminhar_humano` (mesmo motivo de hoje); senão mantém; (e) exceção genérica → pop + handoff (fail-safe visível). `_handle_llm_down` continua contando/alertando (alerta com texto "estacionado p/ retry" via handoff_ativo=False) e suprimindo autoresponder ANTES de estacionar.

- [ ] Testes RED: park grava no Redis fake; _handle_llm_down estaciona (não chama execute_tool) com parking on; com LLM_PARKING=off comportamento atual (handoff); drain: sucesso envia+salva+pop; expiração → handoff; superseded → pop sem envio; ai_enabled=false → pop.
- [ ] Implementar; verde.

### Task 4: Tool `registrar_numero_errado` + job de ponta morta 72h

**Files:**
- Modify: `backend/app/agent/tools.py` (schema + executor + stage list secretaria)
- Modify: `backend/app/agent/prompts/valeria_outbound/secretaria.py` (frame NUMERO ERRADO chama a tool)
- Modify: `backend/app/broadcast/worker.py` (job `process_wrong_number_deadends()` no tick)
- Test: `backend/tests/test_onda2_numero_errado_2026_07_09.py`

**Interfaces:** tool `registrar_numero_errado(contexto: str)` → grava `lead.metadata.wrong_number_at` (ISO) + system message `[registrar_numero_errado]`. `process_wrong_number_deadends(now=None) -> int`: leads com `metadata->>wrong_number_at` não-nulo e `opt_out=false`; se `last_customer_message_at > wrong_number_at` → limpa marcador (pessoa respondeu); se `wrong_number_at < now-72h` → `apply_optout_side_effects` + lead_note "ponta morta de número errado".

- [ ] Testes: executor grava marcador; job optout após 72h; job limpa marcador quando lead respondeu; <72h no-op.
- [ ] Implementar; verde.

### Task 5: Tool `registrar_indicacao` (playbook referral)

**Files:**
- Modify: `backend/app/agent/tools.py` (schema + executor + stage lists secretaria/atacado/private_label)
- Modify: `backend/app/agent/prompts/valeria_outbound/secretaria.py` (seção INDICAÇÃO instrui a tool)
- Test: `backend/tests/test_onda2_registrar_indicacao_2026_07_09.py`

**Interfaces:** `registrar_indicacao(contexto: str, nome: str = "", telefone: str = "")` → lead_note "🤝 [INDICAÇÃO] ...", `metadata.referral={nome, telefone, contexto, at}`, tag "indicacao" via add_tags_to_lead, system message `[registrar_indicacao]`. Não cria lead novo (decisão do vendedor humano).

- [ ] Testes: nota + metadata + tag + system msg; campos opcionais vazios ok.
- [ ] Implementar; verde.

### Task 6: Dossiê — histórico completo quando não há dossiê prévio + script de backfill

**Files:**
- Modify: `backend/app/agent/memory_manager.py` (`refresh_lead_memory`: `since=None` quando `rolling_summary` vazio; cap `delta[-200:]`)
- Create: `backend/scripts/backfill_dossies.py`
- Test: `backend/tests/test_onda2_dossie_backfill_2026_07_09.py`

**Interfaces:** comportamento novo de `refresh_lead_memory`: lead sem `rolling_summary` → `get_history(lead_id, since=None)` (histórico completo, capado nas últimas 200 msgs); lead com dossiê → delta como hoje. Script: `python -m scripts.backfill_dossies --limit N [--dry-run]` — seleciona leads `rolling_summary is null` com `last_customer_message_at` não-nulo, mais recentes primeiro, chama `refresh_lead_memory` com pausa de 2s.

- [ ] Testes: sem dossiê → get_history chamado com since=None e delta capado; com dossiê → since=watermark (comportamento atual pinado).
- [ ] Implementar; verde. Execução do script em prod é passo operacional pós-deploy (docker exec na VPS).

### Task 7: QA diário de aderência no watchdog

**Files:**
- Modify: `backend/app/watchdog/service.py` (check `check_daily_qa(now)` + wiring no loop)
- Test: `backend/tests/test_onda2_daily_qa_2026_07_09.py`

**Interfaces:** `check_daily_qa(now: datetime) -> bool` (True quando publicou) — roda só entre 07:00-08:00 BRT; dedup: nenhum alerta `daily_qa_report` criado hoje (BRT). Métricas de D-1 (janela BRT→UTC): respostas da IA (messages assistant sent_by in agent/followup), inbounds, correções de pergunta repetida (token_usage call_type=response_retry), handoffs (`[encaminhar_humano]` em system), opt-outs (`[registrar_optout]`), template dedup/hot-lead skips (broadcast_leads error_message), dossiês atualizados (rolling_summary_updated_at na janela). Publica system_alert type `daily_qa_report`, severity "info".

- [ ] Testes: fora da janela → no-op sem DB; dedup do dia → no-op; janela limpa → create_system_alert com metadata das contagens.
- [ ] Implementar; verde.

### Task 8: Verificação final e deploy

- [ ] Suíte completa verde (pytest tests/ — baseline 1806 passed).
- [ ] Commit(s) na branch `feat/onda2-resiliencia`; `git pull origin master`; `git push origin feat/onda2-resiliencia:master`.
- [ ] Acompanhar GitHub Action "Deploy to VPS" até completed success.
- [ ] Rodar backfill do dossiê em prod (docker exec, --limit 60) e verificar `leads.rolling_summary` populando.
- [ ] Atualizar memória persistente (auditoria + regressão da cadência).
