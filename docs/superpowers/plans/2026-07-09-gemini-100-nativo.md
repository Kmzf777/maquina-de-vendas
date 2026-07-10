# Gemini 100% Nativo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Erradicar a forma OpenAI (`.chat.completions/.choices/.usage`, messages/tool_calls dicts) — backend 100% google-genai nativo, com JSON mode real e fallback de versão estruturado.

**Architecture:** Núcleo único `app/agent/gemini_client.py` (GenerateResult nativo + generate() + helpers de Content + transcribe_audio + fallback v1 texto-puro); `run_agent` opera sobre `system_instruction + list[types.Content]`; TOOLS nativos; 33 arquivos de teste convertidos via `tests/gemini_fakes.py`.

**Tech Stack:** google-genai SDK, pytest. Spec: docs/superpowers/specs/2026-07-09-gemini-100-nativo-design.md (contratos exatos lá).

## Global Constraints
- Proibido em app/: `chat.completions`, `.choices`, `completions.create`, `openai` (guard test amplia).
- Contratos EXTERNOS de run_agent/processor/scheduler intactos (retornos, exceções LLMUnavailableError, fail-softs).
- Cada teste convertido preserva a INTENÇÃO original (incidentes reais) — proibido enfraquecer asserts.
- token_usage (DB) mantém colunas atuais; alimentação vem de usage_metadata nativo.
- `finish_reason` passa a vocabulário nativo: `"MAX_TOKENS"` substitui `"length"` em app e testes.

### Task 1 (inline/dono): núcleo `gemini_client.py` + unit tests + `tests/gemini_fakes.py`
Files: Create `backend/app/agent/gemini_client.py`, `backend/tests/test_gemini_client_2026_07_09.py`, `backend/tests/gemini_fakes.py`.
Produces: `GenerateResult(content, text, function_calls:list[FunctionCall(name,args)], finish_reason, usage_metadata)`; `generate(model, *, contents, system_instruction, tools, temperature, max_output_tokens, stop_sequences, thinking_off, json_mode)`; `user_content/model_content/function_response_content/history_to_contents/build_tools`; `transcribe_audio(model, audio_bytes, mime)`; `is_transient_error`; fallback v1 (404 falso-sunset, só sem tools/json); `get_genai_client(api_version)` singleton por versão.
- [ ] RED: testes de conversões, parse, fallback (cliente v1beta lança 404 sunset → chama v1), json_mode seta response_mime_type, thinking_off seta budget 0, TypeError p/ kwarg desconhecido.
- [ ] GREEN + commit.

### Task 2 (inline/dono): reescrita do `run_agent` (orchestrator.py)
Files: Modify `backend/app/agent/orchestrator.py` (remove import de gemini_native; `_generate_with_retry` sobre `generate()`; loop ReAct com contents nativos; guards 1:1; usage nativo; `MAX_TOKENS`). Delete `backend/app/agent/gemini_native.py` (após Tasks 3-4 migrarem seus imports).
- [ ] Conversão 1:1 dos ramos; suíte de orchestrator ainda VERMELHA (mocks antigos) — esperado até Task 5.
- [ ] Commit.

### Task 3 (subagente A): memory_manager + summary + main.py
Modify: `app/agent/memory_manager.py` (generate + json_mode=True; _gemini_thinking_off vira thinking_off=True), `app/agent/summary.py`, `app/main.py` (health via generate). Atualizar testes próprios: test_memoria_dossie_fence, test_memory_model_routing, test_agent_summary, test_finops_cached_tokens (parte memory/summary).
- [ ] Testes próprios verdes.

### Task 4 (subagente B): scheduler follow-up + transcrição do processor
Modify: `app/follow_up/scheduler.py` (`_generate_followup_message` via generate; corte por `finish_reason=="MAX_TOKENS"`), `app/buffer/processor.py` (`_transcribe_audio` → gemini_client.transcribe_audio; remove _GEMINI_GENERATE_URL/httpx dessa rota). Testes: test_followup_thinking_deferral, test_transcricao_finops e correlatos.
- [ ] Testes próprios verdes.

### Task 5 (subagentes C/D/E): conversão da suíte de orchestrator/processor (lotes)
33 arquivos com mocks `chat.completions` divididos em 3 lotes alfabéticos. RECEITA (verbatim no prompt do subagente): trocar `patch("app.agent.orchestrator._get_client")` + first_msg/.choices por `patch("app.agent.orchestrator.generate", new=AsyncMock(side_effect=[...]))` com fakes de `tests/gemini_fakes.py`; `_make_tool_call(name,args)` → `fake_tool_call(name,args)`; asserts de call_count preservados; `finish_reason "length"` → `"MAX_TOKENS"`; `["function"]["name"]` → `["name"]` onde tocar TOOLS.
- [ ] Cada lote 100% verde no próprio escopo.

### Task 6 (subagente F): TOOLS nativos + guard test
Modify `app/agent/tools.py` (TOOLS_SCHEMA→TOOL_DECLARATIONS shape FunctionDeclaration; get_tools_for_stage filtra por name; consumidores ajustados), `tests/test_no_openai_provider_2026_07_02.py` (banir chat.completions/.choices/completions.create em app/), testes de tools (10 arquivos `["function"]["name"]`).
- [ ] Verde.

### Task 7 (inline/dono): fechamento
- [ ] Deletar gemini_native.py + test_facade_thought_signature (substituído por teste nativo equivalente no núcleo).
- [ ] Suíte completa 100% verde.
- [ ] Validação E2E no container: round-trip com tool em gemini-2.5-flash E gemini-3.5-flash + dossiê JSON mode (script repro atualizado p/ API nativa).
- [ ] Push → master, deploy, smoke com tráfego real; memória do projeto atualizada.
