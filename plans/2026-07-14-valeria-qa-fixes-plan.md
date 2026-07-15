# Plano de implementação — Correções QA Valéria (14/07)

Spec: `docs/superpowers/specs/2026-07-14-valeria-qa-fixes-design.md`
Branch: `fix/valeria-qa-1407` → destino `master` (deploy de produção via push).

Ordem: funções puras (TDD) → wiring no orquestrador/tools → prompts → suíte verde → deploy.

## Fase 1 — Funções puras em `adherence.py` (TDD)
Arquivo de teste novo: `backend/tests/test_valeria_qa_fixes_2026_07_14.py`.

- [ ] `strip_kitchen_leak(text)` — remove trecho de "cozinha", preserva o resto. Casos:
  - caso Thiago (leak + "ele tem as opções…") → só o leak sai.
  - "sistema Nespresso" / "no nosso sistema de torra" → intacto (não é erro).
  - mensagem 100% leak → devolve original (fail-open).
- [ ] `media_result_is_no_send(result)` — True p/ "nao encontrada"/"nenhuma foto"; False p/
  "enfileiradas"/"ja enviada".
- [ ] `contains_open_question(text)` — True p/ "Tenho que investir?", "qual o valor?"; False
  p/ "tudo bem?", "não quero, muito caro".

## Fase 2 — Wiring no orquestrador (`orchestrator.py`)
- [ ] Importar as 3 novas funções.
- [ ] `_sanitize_assistant_text`: aplicar `strip_kitchen_leak` (com log de vazamento), na
  mesma cadeia de `strip_prohibited_phrases`.
- [ ] Loop de tools: `media_result_is_no_send` → `media_exec_failed = True` para tools de mídia.
- [ ] Guarda de fotos verbalizadas (~1543): `not media_tool_used` → `(not media_tool_used or media_exec_failed)`.
- [ ] Guarda #3: antes de `execute_tool`, abortar `registrar_sem_interesse_atual` quando
  `contains_open_question(user_text)` (função_response instrutivo + `continue`).

## Fase 3 — `tools.py`
- [ ] Reescrever os 2 retornos de "não encontrado" do `calcular_orcamento` (~1548-1556) para
  formato `[INTERNO — NÃO REPASSAR]` com instrução de tom.

## Fase 4 — Prompts (#4, #5) — subagents
- [ ] Regra de terceiro-não-é-equipe em `valeria_inbound/secretaria.py` e
  `valeria_outbound/secretaria.py`.
- [ ] Regra de não-reiniciar-com-histórico em `valeria_inbound/private_label.py` (e entrada).

## Fase 5 — Validação e deploy
- [ ] `pytest` completo (backend) verde.
- [ ] `git add` + commit descritivo.
- [ ] `git pull origin master` → `git push origin fix/valeria-qa-1407:master`.
- [ ] Confirmar Action de deploy disparada.
