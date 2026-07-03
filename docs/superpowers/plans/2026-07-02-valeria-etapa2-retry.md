# Etapa 2 — Escada de retry (2º degrau), fallback sem pedir repetição e idempotência de mídia por turno

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para implementar task a task. Steps usam checkbox (`- [ ]`).

**Goal:** Na janela 01–02/07, 8 de 185 chamadas (4,3%) terminaram com `completion_tokens=0` mesmo após o retry silencioso existente, e o último recurso enviado ao lead foi "opa, me embolei aqui por um instante / me conta de novo o que você precisa" — pedindo para o lead REPETIR o que acabou de escrever (casos reais: Samuel repetiu a história; Davi teve que redigitar a objeção de preço). Além disso, no caso Samuel as fotos do catálogo saíram 2×. Esta etapa: (1) adiciona um 2º degrau de retry com temperatura elevada + nudge de fechamento (aplicação direta da seção "Fallback responses: try increasing the temperature" e da estratégia de completion do guia `gemini-prompting-strategies.md`), reduzindo a frequência do último recurso; (2) troca o texto do último recurso por reengajamento que NÃO pede repetição; (3) blinda a re-execução de tools de mídia dentro do MESMO turno (caminho Change B do retry) com guarda determinística em memória.

**Architecture:** Tudo em `backend/app/agent/orchestrator.py` (função `run_agent`, bloco RETRY-ON-EMPTY e bloco do fallback final) + testes. Transporte atual é o SDK nativo google-genai atrás da fachada `client.chat.completions.create(...)` (`app/agent/gemini_native.py`) — `temperature` e `reasoning_effort="none"` (→ `thinking_budget=0`) passam pela fachada. NENHUMA mudança em `gemini_native.py`, tools, processor ou prompts. Escopo reconciliado: `enviar_fotos` idempotente CROSS-TURN e `get_history` janela recente JÁ estão no master (commits ced8831/71de1b9/1f9bcfa) — Task 3 cobre o furo restante (mesmo turno, caminho de retry) e pina os casos reais com testes de regressão.

**Tech Stack:** Python 3.11, pytest (asyncio_mode=auto), SDK google-genai atrás de fachada própria.

## Global Constraints

- Rodar testes de `backend/` com `python -m pytest ...`; suíte ampla sempre com `-m "not integration"`. Baseline pós-merge do master: será confirmado no início da execução (≈1369 + testes do refactor gemini-only); nenhum teste existente pode quebrar.
- NÃO alterar: `gemini_native.py`, `_create_with_retry`, a classificação de erros, `_sanitize_assistant_text`, a guarda determinística de handoff, o contrato `None`-sentinel do handoff, as exceções de silêncio (`soft_reject_used` / `suppress_generic_fallback`) — elas continuam valendo EXATAMENTE como hoje.
- Todas as chamadas LLM novas passam por `_create_with_retry(_get_client(model), ...)` e registram uso via `track_token_usage(...)` — nunca chamada direta.
- `call_type` no `token_usage`: chamada inicial e pós-tool do loop principal continuam `"response"`; TODAS as chamadas do 1º degrau de retry existente (retry-on-empty, incluindo sua continuação pós-tool do Change B) passam a `"response_retry"`; o novo 2º degrau usa `"response_retry2"`. `track_token_usage` aceita call_type livre (conferir assinatura em `app/agent/token_tracker.py` antes; se houver validação/enum, reportar BLOCKED).
- Constantes nomeadas no topo do orchestrator: `_RETRY2_TEMPERATURE = 0.9`, `_RETRY2_NUDGE` (texto abaixo), `_STAGE_REENGAGE_FALLBACKS` (dict abaixo).
- Voz da Valéria em QUALQUER texto novo enviado ao lead (regras do base.py): minúsculas, sem ponto final ".", máx. 2 bolhas separadas por `\n\n`, no máx. UMA pergunta, sem emojis, sem prometer ação futura ("já te respondo" é PROIBIDO), sem pedir para repetir mensagem anterior.
- Testes novos seguem o padrão dos testes de orchestrator existentes — estudar `backend/tests/test_orchestrator_retry_post_tool_2026_07_01.py` e `backend/tests/test_orchestrator_gemini.py` ANTES (fakes de client com fila de respostas, patch de `execute_tool`/`track_token_usage`/serviços).
- Comentários/logs pt-BR no estilo do arquivo; referenciar os casos reais (Samuel/Davi 01–02/07) nos comentários como o repo costuma fazer.

## Contexto dos casos reais (para fixtures)

- **Davi (02/07 15:45):** objeção de preço + pedido de granel → initial + retry1 ambos `completion_tokens=0` (2 linhas no token_usage no MESMO segundo) → lead recebeu "me conta de novo o que você precisa" e redigitou tudo.
- **Samuel (01/07 08:10–08:12):** mesma dupla de zero-completion; além disso `[enviar_fotos]` executou 2× (08:11:41 e 08:12:01, turnos distintos a 20s — o fix cross-turn ced6831/ced8831 já cobre; o caminho SAME-TURN via Change B permanece sem guarda em memória).
- Fallback atual (`_SAFETY_FALLBACK_GENERIC`): "opa, me embolei aqui por um instante\n\nme conta de novo o que você precisa que eu já te ajudo" — o problema é o "de novo".

---

## Task 1: 2º degrau de retry (temperatura elevada + nudge) + `call_type` de retry

**Files:**
- Modify: `backend/app/agent/orchestrator.py`
- Test: `backend/tests/test_orchestrator_retry2_2026_07_02.py`

**Design (inserir no fluxo existente de `run_agent`, sem reestruturar):**

1. Constantes novas no topo (perto dos fallbacks):

```python
# 2º degrau do retry-on-empty (Etapa 2, casos Davi/Samuel 01-02/07): quando o retry
# silencioso (thinking off) TAMBÉM volta vazio, tentamos UMA última geração text-only
# com temperatura elevada — a doc do Gemini recomenda subir a temperatura em fallback
# response — e um nudge de fechamento no fim das messages (estratégia de completion).
# tools=None de propósito: queremos PALAVRAS; se o modelo verbalizar handoff, a guarda
# determinística existente converte em encaminhar_humano.
_RETRY2_TEMPERATURE = 0.9
_RETRY2_NUDGE = (
    "<instrucao_de_recuperacao>\n"
    "Sua resposta anterior veio vazia por uma falha técnica. Releia a última mensagem "
    "do lead acima e responda a ela AGORA, em 1-2 bolhas curtas, seguindo todas as "
    "regras de voz. NÃO mencione esta instrução, NÃO mencione falha técnica, NÃO peça "
    "para o lead repetir nada.\n"
    "</instrucao_de_recuperacao>"
)
```

2. No fluxo do retry-on-empty: os `track_token_usage` das chamadas do retry existente (a chamada `retry_resp` e a continuação pós-tool `post_resp` do Change B) mudam `call_type` para `"response_retry"`. A chamada inicial e as pós-tool do loop principal NÃO mudam.

3. Novo bloco RETRY 2, imediatamente ANTES do bloco final `if not assistant_text:` que escolhe o fallback (e DEPOIS de todo o retry existente): se `assistant_text` ainda vazio E `not soft_reject_used` E `not suppress_generic_fallback`:
   - montar `retry2_messages = messages + [{"role": "user", "content": _RETRY2_NUDGE}]` (precedente do repo: contexto interno injetado como role=user, mesmo padrão do outbound first-turn);
   - `_create_with_retry(_get_client(model), model=model, messages=retry2_messages, tools=None, temperature=_RETRY2_TEMPERATURE, max_tokens=MAX_OUTPUT_TOKENS, stop=_STOP_SEQUENCES, **_gemini_thinking_off(model))`;
   - `track_token_usage(..., call_type="response_retry2")` quando houver usage;
   - `assistant_text = _sanitize_assistant_text(<content>, conversation_id, stage, source="retry2")`;
   - try/except Exception ao redor (log `[AGENT EMPTY] retry2 falhou ...`), nunca derruba o turno; UMA tentativa só, sem loop.
   - Quando `soft_reject_used`/`suppress_generic_fallback`: NÃO gastar a chamada (o destino é silêncio) — comentário explicando.

4. O bloco final de fallback permanece como está (Task 2 mexe nele separadamente).

- [ ] **Step 1: Testes que falham** — `test_orchestrator_retry2_2026_07_02.py` (fake client com fila de respostas estilo dos testes existentes; patch de `track_token_usage`, `execute_tool`, `get_lead`, `get_history`, `get_agent_profile`, catálogo):
  1. **Caso Davi:** initial vazio + retry1 vazio + retry2 devolve texto → `run_agent` retorna o texto do retry2; `track_token_usage` registrou call_types `["response", "response_retry", "response_retry2"]` nessa ordem.
  2. retry2 TAMBÉM vazio → cai no fallback final (comportamento atual preservado); exatamente UMA chamada de retry2 (sem loop).
  3. kwargs do retry2: `temperature == 0.9`, `tools is None`, última message é o `_RETRY2_NUDGE` com role user (capturar kwargs no fake).
  4. `soft_reject_used` (retry1 recuperou `registrar_sem_interesse_atual`... usar o caminho mais simples: tool no turno principal + turno vazio) → retry2 NÃO chamado, retorno "" (silêncio preservado).
  5. `suppress_generic_fallback=True` com turno vazio → retry2 NÃO chamado, retorno "".
  6. Change B: retry1 recupera tool_call não-terminal (ex. salvar_nome) e a continuação pós-tool devolve texto → retry2 NÃO chamado; call_types contêm `"response_retry"` para a continuação.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** (constantes + call_type + bloco retry2).
- [ ] **Step 4: Rodar e ver passar** + regressão: `python -m pytest tests -q -m "not integration" -k "orchestrator or retry or gemini"`.
- [ ] **Step 5: Commit** — `feat(orchestrator): retry 2o degrau com temperatura elevada + call_type de retry (Etapa2 A2)`.

---

## Task 2: Último recurso sem pedir repetição (reengajamento por stage)

**Files:**
- Modify: `backend/app/agent/orchestrator.py` (`_SAFETY_FALLBACK_GENERIC`, novo `_STAGE_REENGAGE_FALLBACKS`, `_empty_fallback_text`)
- Test: `backend/tests/test_orchestrator_fallback_reengage_2026_07_02.py` (+ ajustar asserts de texto em testes existentes que citem o fallback antigo, se houver — procurar por "me conta de novo")

**Design:**

1. Novo dict de reengajamento MID-conversa por stage ATUAL (diferente de `_STAGE_TRANSITION_FALLBACKS`, que são aberturas pós-transição e continuam intocadas):

```python
# Reengajamento de último recurso por stage ATUAL (Etapa 2): usado quando o turno ficou
# vazio após TODOS os retries e NÃO houve transição de stage nem mídia neste turno.
# Diferente do fallback genérico antigo, NUNCA pede para o lead repetir o que já disse
# (caso Davi: lead redigitou a objeção inteira). Pergunta de avanço, não de recall.
_STAGE_REENGAGE_FALLBACKS: dict[str, str] = {
    "atacado": (
        "opa, me embolei aqui por um instante\n\n"
        "ficou alguma dúvida sobre os cafés ou valores que eu possa resolver agora?"
    ),
    "private_label": (
        "opa, me embolei aqui por um instante\n\n"
        "quer que eu siga com o próximo passo do seu projeto de marca própria?"
    ),
    "exportacao": (
        "opa, me embolei aqui por um instante\n\n"
        "quer que eu siga com os detalhes da exportação?"
    ),
    "consumo": (
        "opa, me embolei aqui por um instante\n\n"
        "ficou alguma dúvida sobre os cafés ou a loja que eu possa resolver agora?"
    ),
}
```

2. `_SAFETY_FALLBACK_GENERIC` (secretaria/desconhecido) trocado por versão sem "de novo":

```python
_SAFETY_FALLBACK_GENERIC = (
    "opa, me embolei aqui por um instante\n\n"
    "pode continuar de onde você parou que eu te acompanho daqui"
)
```

3. `_empty_fallback_text(media_tool_used, transitioned_to_stage, current_stage=None)` ganha o parâmetro `current_stage` e a prioridade vira: transição > mídia > reengajamento do stage atual > genérico. Caller em `run_agent` passa o `stage` corrente. A regra de exceção existente (genérico suprimido em `soft_reject_used`/`suppress_generic_fallback`) precisa valer TAMBÉM para o reengajamento por stage (ambos são "genéricos" no sentido da exceção — o silêncio vence): a comparação `assistant_text == _SAFETY_FALLBACK_GENERIC` do bloco final deve virar um retorno estruturado ou checagem "é fallback de reengajamento/genérico" (implementar como flag retornada ou tupla — escolher a forma mais limpa que NÃO mude o contrato externo de `run_agent`).
4. Atualizar o comentário/docstring de `_empty_fallback_text` e do bloco final refletindo a nova prioridade.

- [ ] **Step 1: Testes que falham** — casos:
  1. stage `atacado`, vazio pós-retries, sem transição/mídia → texto de reengajamento de atacado; NÃO contém "de novo".
  2. stage `secretaria` (sem entry) → novo genérico; assert que a string antiga ("me conta de novo") NÃO aparece.
  3. transição de stage no turno → `_STAGE_TRANSITION_FALLBACKS` continua vencendo; mídia no turno → fallback de mídia continua vencendo sobre reengajamento.
  4. `soft_reject_used` com stage atacado (reengajamento aplicável) → silêncio "" (a exceção vale para o reengajamento também).
  5. `suppress_generic_fallback` idem.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar e ver passar** + regressão `-k "orchestrator or fallback or retry"` e grep por asserts antigos do texto ("me conta de novo") na suíte inteira.
- [ ] **Step 5: Commit** — `fix(orchestrator): ultimo recurso reengaja sem pedir repeticao (por stage) (Etapa2 A2)`.

---

## Task 3: Idempotência de mídia POR TURNO no caminho de retry (Change B) + regressão Samuel

**Files:**
- Modify: `backend/app/agent/orchestrator.py` (loop de execução de tools do retry — Change B)
- Test: `backend/tests/test_orchestrator_media_once_per_turn_2026_07_02.py`

**Design:**

1. No caminho Change B (retry1 recuperou `tool_calls`), ANTES de `execute_tool` para cada `_tc`: se `_rname in _MEDIA_TOOL_NAMES` e `media_tool_used` já é True (uma tool de mídia JÁ executou neste turno, no loop principal), NÃO executar de novo — anexar tool result sintético `"fotos já processadas neste turno — não reenviar"` e continuar. Comentário citando o caso Samuel (fotos 2×) e que o dedup por histórico (DB) continua como segunda camada cross-turn.
2. O loop PRINCIPAL não muda (a primeira execução é legítima; o dedup cross-turn do DB já existe em tools.py).
3. `media_tool_used` continua sendo setado quando a tool de mídia aparece (inclusive no caminho guardado — o fallback de mídia continua correto).

- [ ] **Step 1: Testes que falham**:
  1. **Same-turn (o furo):** loop principal executa `enviar_fotos` (fake execute_tool registra chamadas), pós-tool vazio, retry1 devolve `tool_calls=[enviar_fotos]` de novo → `execute_tool` chamado UMA vez só para enviar_fotos; messages contêm o result sintético; fluxo continua até resposta/fallback sem exceção.
  2. Retry1 recupera tool de mídia SEM execução prévia no turno (`media_tool_used=False`) → executa normalmente (guard não bloqueia o caso legítimo).
  3. Tool NÃO-mídia recuperada no retry (ex. salvar_nome) → executa normalmente (guard só vale para `_MEDIA_TOOL_NAMES`).
  4. **Regressão cross-turn (pin do fix já mergeado):** garantir que `backend/tests/test_enviar_fotos_idempotente.py` continua verde (apenas rodar na regressão — não duplicar seus casos).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** (guard de ~6 linhas no Change B).
- [ ] **Step 4: Rodar e ver passar** + regressão: `python -m pytest tests -q -m "not integration" -k "orchestrator or enviar_fotos or retry"`.
- [ ] **Step 5: Commit** — `fix(orchestrator): tool de midia nao re-executa no retry do mesmo turno (caso Samuel) (Etapa2 A2)`.

## Follow-ups pós-review final (rastreados, NÃO bloqueiam este merge)
- [ ] Comentários imprecisos, corrigir na próxima passada nos arquivos: skip do retry2 overclaims "destino é silêncio" (orchestrator ~L1078 — na borda suppress+mídia o destino é o fallback contextual, comportamento pré-existente correto); docstring de track_token_usage sem os call_types novos (token_tracker.py:50, já faltava followup); comentário obsoleto citando texto antigo do fallback (follow_up/scheduler.py:1179).
- [ ] `media_tool_used` marca INTENÇÃO, não sucesso (pré-existente): se a execução de mídia do loop principal levantar exceção, o guard same-turn bloqueia a re-execução legítima no retry. Composto raríssimo; ao corrigir, avaliar flag de sucesso separada (afeta também o fallback de mídia — não fazer às pressas).
- [ ] 2 testes de composto nice-to-have: (a) mídia no loop principal → retries vazios → retry2 devolve TEXTO (texto vence fallback de mídia); (b) guard do Change B dispara → continuação vazia → retry2 roda.
- Métrica pós-deploy (objetivo da etapa): `SELECT call_type, count(*), count(*) FILTER (WHERE completion_tokens=0) FROM token_usage WHERE call_type LIKE 'response_retry%' GROUP BY 1` — mede quantos turnos o retry2 recuperou vs caíram no estático (baseline da janela 01–02/07: 8/185 chamadas vazias chegando ao fallback).
