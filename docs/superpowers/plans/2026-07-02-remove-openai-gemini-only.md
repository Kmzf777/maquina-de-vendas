# Plano — Abortar migração OpenAI, consolidar 100% no Gemini

**Data:** 2026-07-02
**Branch:** `chore/valeria-gemini-only` (baseada em `origin/master` = produção)
**Contexto:** A migração para OpenAI (gpt-5-mini + Whisper) vive SÓ na branch
`worktree-hotfix+valeria-openai-gpt5mini` e NUNCA foi deployada (nenhum dos commits
`60661dd`/`4584c14`/`323f07b`/`94d28b1` está em `origin/master`). Logo: **não há revert
a fazer** — a branch é descartada. Este plano limpa o resíduo de OpenAI que AINDA existe
em produção e força todo processamento LLM para `gemini-2.5-flash`.

## Decisão de escopo (confirmada pelo usuário)

Remover a OpenAI **como provedor/destino**: nenhum tráfego para `gpt-*`, Whisper,
ou `api.openai.com` real; sem `openai_api_key`. **MANTER** o SDK `openai`
(`AsyncOpenAI`) exclusivamente como TRANSPORTE do Gemini via endpoint OpenAI-compat
(`https://generativelanguage.googleapis.com/v1beta/openai/`) — que é como a produção
já roda hoje. NÃO reescrever para o SDK nativo `google-generativeai`.

## Global Constraints (lente de revisão)

- **Modelo único de texto/resumo/follow-up/memória:** `gemini-2.5-flash`.
- **Transcrição de áudio:** já usa Gemini `generateContent` (`processor._transcribe_audio`,
  `settings.transcription_model="gemini-2.5-flash"`). NÃO alterar esse caminho ativo.
- **PRESERVAR** `import openai` + `from openai import AsyncOpenAI` (transporte + tipos de
  exceção usados em `_create_with_retry`). PRESERVAR `_get_gemini()`, `_GEMINI_BASE_URL`,
  `get_ai_client`, `_gemini_thinking_off`, retry GOAWAY, sanitização anti-tool_code.
- **REMOVER** qualquer caminho para OpenAI real: `_get_openai()`, `settings.openai_api_key`,
  `_OPENAI_MODEL_PREFIXES`, `_is_valid_openai_model`, roteamento condicional gpt-* → OpenAI,
  `whisper-1`, `gpt-4o`, `audio.transcriptions`.
- Qualquer `model` de agent_profile que NÃO seja `gemini-*` deve ser coagido para
  `gemini-2.5-flash` em runtime (log de warning), nunca roteado para OpenAI.
- Comentários/URLs que contêm a substring "openai" por descreverem o endpoint
  **OpenAI-compat do Gemini** são legítimos e devem permanecer.
- Testes: `python -m pytest` rodado a partir de `backend/`. Suíte inteira deve passar.
- Fluxo git do projeto: sem PR; push final direto para `master` mediante autorização.

## Task 1 — Colapsar o roteamento LLM para Gemini-only (orchestrator)

**Arquivos:** `backend/app/agent/orchestrator.py`, `backend/tests/test_orchestrator_gemini.py`
**TDD.**

1. Atualizar `tests/test_orchestrator_gemini.py`:
   - Substituir `test_get_client_roteia_openai_para_cliente_openai` por
     `test_get_client_roteia_qualquer_modelo_para_gemini`: `_get_client("gpt-4.1-mini")`,
     `_get_client("modelo-desconhecido")` e `_get_client("gemini-2.5-flash")` TODOS retornam
     o cliente Gemini (patch `_get_gemini`); não existe mais `_get_openai` para patchar.
   - Manter `test_is_gemini_model_*` e `test_run_agent_usa_cliente_gemini_*`.
   - Adicionar teste de coerção de modelo: um profile com `model="gpt-4.1"` faz `run_agent`
     resolver para `gemini-2.5-flash` (via `mock_get_client.assert_called_with("gemini-2.5-flash")`).
2. Em `orchestrator.py`:
   - Remover global `_openai_client`, constante `_OPENAI_MODEL_PREFIXES`, função
     `_is_valid_openai_model`, função `_get_openai`.
   - `_get_client(model)` → sempre `return _get_gemini()` (mantém assinatura/callers).
   - Resolução de modelo (~L565): coagir qualquer modelo não-`gemini-*` para `DEFAULT_MODEL`
     com `logger.warning(...)`; remover o ramo `_is_valid_openai_model`. Manter o log
     "Using Gemini model ... via OpenAI-compatible API" (descreve o transporte compat).
   - PRESERVAR `import openai`, `AsyncOpenAI`, `_get_gemini`, `_create_with_retry`.

**Verificação:** `python -m pytest tests/test_orchestrator_gemini.py tests/test_orchestrator_human_control.py -q` verde.

## Task 2 — Remover a superfície de provedor OpenAI (config / main / media / router / seed)

**Arquivos:** `backend/app/config.py`, `backend/app/main.py`,
`backend/app/whatsapp/media.py` (DELETAR), `backend/app/agent_profiles/router.py`,
`backend/scripts/seed_valeria_profile.py`.

1. **Deletar** `backend/app/whatsapp/media.py` inteiro — código OpenAI morto
   (`whisper-1`, `gpt-4o`, `_get_openai`). Confirmar que nenhum módulo o importa
   (grep já confirmou: sem callers; o áudio ativo usa `provider.download_media` +
   `processor._transcribe_audio`).
2. `config.py`: remover o campo `openai_api_key` das DUAS classes `Settings`
   (ramo Pydantic v2 e v1). Manter `gemini_api_key` e `transcription_model`.
3. `main.py` `/debug/agent`: remover todo o bloco de teste de conectividade OpenAI
   (`settings.openai_api_key`, `AsyncOpenAI(api_key=oai_key)`, `model="gpt-4.1-mini"`,
   chaves `openai_*` no dict). Substituir por um ping ao Gemini via
   `get_ai_client("gemini-2.5-flash")` reportando `gemini_key_set` + `gemini_test`.
   NÃO deve restar referência a `settings.openai_api_key` (o campo deixou de existir).
4. `agent_profiles/router.py`: `ProfileCreate.model` default `"gpt-4.1"` → `"gemini-2.5-flash"`.
5. `scripts/seed_valeria_profile.py`: se houver default/valor de `model` `gpt-*`,
   trocar por `gemini-2.5-flash`.

**Verificação:** `python -c "from app.config import settings; from app.main import app"`
importa sem erro; `python -m pytest -q` sem regressão de import.

## Task 3 — Guard de regressão "sem provedor OpenAI" + suíte verde

**Arquivo:** novo `backend/tests/test_no_openai_provider_2026_07_02.py`.

1. Teste que varre `backend/app/**/*.py` e afirma que NENHUM arquivo contém os
   marcadores de PROVEDOR OpenAI (não o transporte): `settings.openai_api_key`,
   `openai_api_key` como campo, `_get_openai`, `whisper`, `audio.transcriptions`,
   e literais de modelo `"gpt-` / `'gpt-` / `model="gpt`. Permitir explicitamente:
   `import openai`, `from openai import`, `AsyncOpenAI`, a substring "openai" em URLs
   (`generativelanguage.googleapis.com/v1beta/openai/`) e em comentários "OpenAI-compat".
2. Rodar a suíte inteira `python -m pytest -q` a partir de `backend/` e corrigir
   qualquer fallout (ex.: testes que ainda importam `app.whatsapp.media`).

**Verificação:** `python -m pytest -q` — suíte inteira verde.

## Fora de escopo (registrado)

- `token_tracker.py` tem comentários mencionando `gpt-4.1`/Whisper (cosmético) — opcional.
- Linhas do DB `agent_profiles.model` em produção com `gpt-*` são cobertas pela coerção
  de runtime da Task 1 (não requer mudança de dados para correção). Não alterar dados de
  produção neste plano.
- Migrations históricas (`00x_*.sql`, `20260417_*`) NÃO são editadas (histórico imutável).
