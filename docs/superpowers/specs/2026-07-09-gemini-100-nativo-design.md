# Gemini 100% nativo — erradicação da forma OpenAI (design)

**Decisão executiva (usuário, 09/07/2026):** o backend deve ser exclusivamente Gemini
nativo em todas as camadas. Nada que remeta à OpenAI — nem a fachada, nem a forma, nem
a nomenclatura (`.chat.completions`, `.choices`, `.usage`, `messages`/`tool_calls`
dicts) — pode permanecer. Execução autônoma pré-aprovada.

## Contexto medido (09/07)

O transporte já é nativo desde 4fc05eb (02/07): zero `import openai`, SDK `google-genai`
no requirements, guard test ativo. O que resta é a FORMA: a fachada
`gemini_native.py` expõe `.chat.completions.create` → `.choices/.usage`, e 6 arquivos de
app + ~33 arquivos de teste falam esse dialeto. Incidentes recentes provaram o custo da
fachada: `response_format` engolido em `**_ignored` (dossiê sem JSON mode → 1.366
gerações perdidas em 08/07) e perda do `thought_signature` no round-trip dict
(400 em TODA conversa com tool na família Gemini 3 — incidente 09/07 à tarde, caso
Tiago; corrigido paliativamente com base64 em 25c248f).

Raio de explosão: app = `orchestrator.py` (run_agent ~1000 linhas endurecidas),
`memory_manager.py`, `summary.py`, `follow_up/scheduler.py`, `main.py`,
`buffer/processor.py` (transcrição REST), `tools.py` (TOOLS_SCHEMA em shape OpenAI).
Testes = 33 arquivos mockam `chat.completions`, 10 leem `["function"]["name"]`.

**Prova de versão (curl com a chave de prod, 09/07):** a API `v1` REJEITA
`systemInstruction`, `tools`, `thinkingConfig` e `responseMimeType`
(400 "Cannot find field"). `v1` não roda agente com function calling — "v1 como
padrão" é inviável. `v1beta` é a única superfície com paridade.

## Arquitetura

### Núcleo: `app/agent/gemini_client.py` (substitui e DELETA `gemini_native.py`)

Única porta de saída para o Gemini, com vocabulário 100% nativo:

- `GenerateResult`: `.content` (o `types.Content` cru do candidato — re-anexado ao
  turno SEM round-trip por dicts, preservando `thought_signature` nativamente),
  `.text` (str|None), `.function_calls` (lista de `(name, args: dict)`),
  `.finish_reason` (nome nativo: `"STOP"`, `"MAX_TOKENS"`, ...),
  `.usage` → NÃO: `.usage_metadata` (`prompt_token_count`, `candidates_token_count`,
  `thoughts_token_count`, `cached_content_token_count`; propriedade
  `billed_output_tokens = candidates + thoughts`).
- `async generate(model, *, contents, system_instruction=None, tools=None,
  temperature=0.4, max_output_tokens=None, stop_sequences=None, thinking_off=False,
  json_mode=False) -> GenerateResult` — monta `GenerateContentConfig`
  (`system_instruction`, `thinking_config=ThinkingConfig(thinking_budget=0)` quando
  `thinking_off`, `response_mime_type="application/json"` quando `json_mode`,
  `automatic_function_calling` desabilitado). Parâmetro desconhecido = TypeError
  (nunca mais engolir kwargs).
- Helpers puros: `user_content(text)`, `model_content(text)`,
  `function_response_content(name, result_text)`, `history_to_contents(rows)`
  (linhas role/content do DB → `list[types.Content]`),
  `build_tools(declarations)` (dicts nativos → `[types.Tool]`).
- `transcribe_audio(model, audio_bytes, mime_type) -> (text, usage_metadata)` via SDK
  (substitui o REST httpx do processor; mesma contabilidade fail-soft).
- Versão de API: cliente default **v1beta** (`GEMINI_API_VERSION` env override).
  Fallback estruturado: erro 404 com assinatura de falso-sunset ("no longer
  available") em chamada SEM tools e SEM json_mode → retry único num cliente `v1`
  (modo-degradado texto puro, limitação documentada pela prova acima). Com
  tools/json, o erro sobe — o parking/handoff do processor é a rede.
- `is_transient_error(exc)` (429/5xx/conexão/timeout) para o retry do orchestrator.

### `tools.py`: declarações nativas

`TOOLS_SCHEMA` (shape `{"type":"function","function":{...}}`) vira
`TOOL_DECLARATIONS: list[dict]` no shape de `FunctionDeclaration`
(`{"name","description","parameters"}`). `get_tools_for_stage(stage)` filtra por
`d["name"]`. O orchestrator converte por turno via `build_tools`.

### `run_agent` (reescrita interna, contratos externos intactos)

Estado do turno: `system_instruction: str` + `contents: list[types.Content]`
(histórico via `history_to_contents` + `user_content(texto)`). Loop ReAct:
`result = await _generate_with_retry(...)`; com `result.function_calls` → executa
tools → `contents.append(result.content)` +
`contents.append(function_response_content(...))` → próxima geração com
`thinking_off=True`. TODOS os guards preservados 1:1 (retry-on-empty via
`result.text` vazio, sanitizer, guarda de pergunta repetida, strip de tool_code
vazado, handoff verbal, dedup, telemetria PROMPT ECHO); `_track_usage` alimentado por
`usage_metadata` (colunas do `token_usage` no banco NÃO mudam — são nomenclatura
nossa de persistência, não objeto de SDK). `finish_reason == "length"` vira
`== "MAX_TOKENS"` aqui e no scheduler.

### Consumidores

`memory_manager.generate_rolling_summary` → `generate(..., json_mode=True)` (fecha a
lacuna REAL do JSON; parse tolerante a cercas permanece como defesa em profundidade).
`summary.py`, `scheduler._generate_followup_message` (guard de corte por
`"MAX_TOKENS"`), `main.py` (health), `processor._transcribe_audio` →
`gemini_client.transcribe_audio`.

### Guard test ampliado

`test_no_openai_provider` passa a proibir em `app/`: `chat.completions`, `.choices`,
`completions.create`, `AsyncOpenAI`, `import openai`. `gemini_native.py` deletado.

### Testes (~33 arquivos)

Helper compartilhado `tests/gemini_fakes.py`: `fake_text(text, finish="STOP",
usage=...)`, `fake_tool_call(name, args)`, `install_fake_generate(monkeypatch,
results: list)` — cada teste que hoje monta `first_msg.tool_calls/.content` +
`AsyncMock(side_effect=[r1, r2])` converte mecanicamente para a lista de
`GenerateResult` fakes. Receita única aplicada por subagentes, arquivo a arquivo,
preservando a INTENÇÃO de cada teste (cada um codifica um incidente real).

## Execução (subagent-driven)

Núcleo de risco por mim (inline): design, plano, `gemini_client.py` + unit tests +
`gemini_fakes.py` + reescrita do `run_agent` + validação ao vivo no container
(round-trip com tool em 2.5 E 3.5 + JSON mode). Subagentes em paralelo depois do
núcleo: (A) memory_manager+summary+main+testes próprios; (B) scheduler+transcrição do
processor+testes próprios; (C..E) conversão da suíte de orchestrator em lotes com a
receita; (F) TOOLS_SCHEMA nativo + guard test + testes de tools. Fechamento: suíte
100% verde, push→master (deploy), repro E2E no container, smoke com tráfego real.

## Critérios de aceite

Zero ocorrências de `chat.completions`/`.choices`/`completions.create` em `app/`;
`gemini_native.py` inexistente; suíte 100% verde; round-trip com tool passa em
gemini-2.5-flash E gemini-3.5-flash no container de produção (com thought_signature
nativo, sem base64); dossiê gerado com `response_mime_type` JSON; transcrição via SDK;
fallback v1 coberto por teste unitário com o erro do falso-sunset simulado.

## Riscos e mitigação

O `run_agent` codifica ~15 incidentes de produção — a conversão é 1:1 por construção
(mesmos ramos, mesmos guards, só o dialeto muda) e a suíte convertida é o detector de
regressão. O risco residual (comportamento do SDK vivo) é coberto pela validação
E2E no container ANTES do deploy, nos dois modelos. Rollback: revert do merge.
