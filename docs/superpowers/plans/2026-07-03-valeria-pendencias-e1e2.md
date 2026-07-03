# Pendências pós-review — robustez do watchdog + follow-ups do orchestrator

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para implementar task a task. Steps usam checkbox (`- [ ]`).

**Goal:** Fechar os follow-ups rastreados nos reviews finais das Etapas 1 e 2: (1) a janela candidata do watchdog (`limit(500)` order-desc) pode dar MISS completo de conversa fantasma sob rajada — paginar; o passo 3 (replies) sem order/limit é vulnerável a truncamento server-side — ordenar desc + limitar (direção segura); embeds carregam campos não usados; (2) `media_tool_used` marca INTENÇÃO — se a execução de mídia falhar (exceção), o guard same-turn bloqueia a re-execução legítima no retry; (3) dois testes de composto que a Etapa 2 criou e não pinou; (4) quatro comentários/log imprecisos.

**Architecture:** Task 1 em `backend/app/watchdog/service.py`; Task 2 em `backend/app/agent/orchestrator.py` (+ 2 linhas de docstring/comentário em `token_tracker.py` e `follow_up/scheduler.py`). Nenhuma migração; nenhum comportamento de caminho feliz alterado.

## Global Constraints

- Testes de `backend/` com `python -m pytest ...`; suíte ampla com `-m "not integration"`. Baseline: 1392 passed. Nenhum teste existente pode quebrar (ajustes só se um teste pinava o comportamento corrigido — listar no report).
- Watchdog continua 100% read-only (exceto system_alerts), fail-soft por check, constantes nomeadas.
- Orchestrator: NÃO alterar retry2, fallbacks, sanitizer, guarda de handoff, dedup DB das tools.
- Comentários/logs pt-BR no estilo dos arquivos.

---

## Task 1: Watchdog — paginação da janela candidata + chunking de ids + replies bounded + embeds enxutos

**Files:**
- Modify: `backend/app/watchdog/service.py`
- Test: `backend/tests/test_watchdog_pagination_2026_07_03.py` (novo) + ajustes mínimos em `test_watchdog_checks_2026_07_02.py` SÓ se algum assert pinar o formato antigo das queries (listar no report)

**Design:**

1. Constantes novas: `CANDIDATE_PAGE_SIZE = 500` (substitui o uso direto de `CANDIDATE_MESSAGE_LIMIT` no passo 1 — manter a constante antiga como alias ou removê-la e atualizar referências), `CANDIDATE_MAX_PAGES = 10` (teto de segurança: 5.000 msgs/24h é ordem de grandeza acima do volume atual; se o teto for atingido, logar warning `[WATCHDOG] janela candidata truncada em N páginas`), `ID_CHUNK_SIZE = 100`, `REPLIES_FETCH_LIMIT = 1000`.
2. Passo 1 (`_find_unanswered_conversations`): loop de paginação com `.order("created_at", desc=True).range(offset, offset + CANDIDATE_PAGE_SIZE - 1)` até página vazia/parcial ou `CANDIDATE_MAX_PAGES`. A redução "última user msg por conversa" continua em Python (dict por conversation_id com max por `_parse_ts` — já é order-independent).
3. Passos 2 e 3: TODO `.in_("id"/"conversation_id", ids)` passa a iterar em chunks de `ID_CHUNK_SIZE` (helper `_chunked(seq, n)`), agregando resultados — elimina o risco de URL gigante com 500+ UUIDs.
4. Passo 3 (replies): adicionar `.order("created_at", desc=True).limit(REPLIES_FETCH_LIMIT)` POR CHUNK. Direção segura por construção: as replies mais NOVAS são as que CLAREIAM violações; truncar as antigas só pode gerar falso positivo (alerta a mais), nunca esconder violação — documentar isso em comentário.
5. Embeds enxutos: Check 1 passa a pedir só `leads!inner(ai_enabled)`; Check 2 só `leads!inner(ai_enabled, human_control, opt_out)`; remover `name`/`opt_out` não consumidos do Check 1.

- [ ] **Step 1: Testes que falham** — `test_watchdog_pagination_2026_07_03.py` (reusar o FakeSupabase do arquivo de testes existente — importar/estender, não duplicar verbatim; se precisar de suporte a `.range()`, adicionar ao fake existente):
  1. **MISS-completo corrigido:** 1 conversa fantasma (candidata antiga) + >500 mensagens respondidas mais novas na janela → com paginação, a fantasma É detectada (era o miss do review).
  2. Teto de páginas: fake com páginas infinitas → para em `CANDIDATE_MAX_PAGES` e loga truncamento (caplog).
  3. Chunking: >100 conversation_ids → passo 2/3 chamados em múltiplos chunks (fake registra as chamadas), resultado agregado correto.
  4. Replies bounded: fake verifica que a query de replies recebe order desc + limit; violação continua detectada quando a reply que clarearia está no topo (mais nova).
  5. Embeds: asserts de que o select do Check 1 não pede `name`/`opt_out` (capturar a string de select no fake).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar e ver passar** + regressão `-k "watchdog"` completa.
- [ ] **Step 5: Commit** — `fix(watchdog): paginacao da janela candidata + chunking de ids + replies bounded (follow-up review E1)`.

---

## Task 2: Orchestrator — guard de mídia ciente de falha + 2 testes de composto + comentários imprecisos

**Files:**
- Modify: `backend/app/agent/orchestrator.py`, `backend/app/agent/token_tracker.py` (docstring), `backend/app/follow_up/scheduler.py` (1 comentário)
- Test: `backend/tests/test_orchestrator_composto_2026_07_03.py` (novo)

**Design:**

1. **Flag de falha de execução de mídia** (`media_exec_failed`, default False): no loop principal E no caminho Change B, quando `func_name in _MEDIA_TOOL_NAMES` e `execute_tool` LEVANTA exceção (o ramo `except Exception` já existente que devolve result "erro ao executar ..."), setar `media_exec_failed = True`. O guard same-turn do Change B passa de `media_tool_used` para `media_tool_used and not media_exec_failed` — re-execução legítima após falha deixa de ser bloqueada. `media_tool_used` (intenção) continua intocado para o fallback de mídia (mudança de semântica do fallback foi explicitamente adiada pelo review — comentar isso).
2. **Testes de composto** (fila fake estilo `test_orchestrator_retry2_2026_07_02.py`):
   - (a) mídia executa OK no loop principal → pós-tool vazio → retry1 vazio → retry2 devolve TEXTO → `run_agent` retorna o texto (texto real vence o fallback de mídia).
   - (b) guard same-turn dispara (mídia já ok no turno) → continuação Change B vazia → retry2 RODA (`response_retry2` presente na ordem de call_types).
   - (c) NOVO comportamento: mídia FALHA no loop principal (execute_tool raise) → retry1 recupera a mesma tool → executa (execute_tool chamado 2×; guard não bloqueia após falha).
3. **Comentários/log** (mesmo commit):
   - orchestrator: comentário do skip do retry2 (~"o destino do turno já é o silêncio") corrigido para "o destino é silêncio OU um fallback contextual estático (mídia/transição) que não depende do retry2";
   - orchestrator: logs finais "vazio após retry" → "vazio após todos os retries";
   - `token_tracker.py` docstring: listar `response`, `response_retry`, `response_retry2`, `followup`, `classification`, `media_description`, `media_transcription` (conferir a lista real via grep de `call_type=` no repo antes de escrever);
   - `follow_up/scheduler.py:~1179`: atualizar o comentário que cita o texto antigo do fallback para referenciar a constante `_SAFETY_FALLBACK_GENERIC` atual (sem citar literal).

- [ ] **Step 1: Testes que falham** (o caso (c) é o RED principal — hoje o guard bloqueia; (a)/(b) devem passar já no estado atual OU falhar por gap de fixture — validar e reportar qual).
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** (flag + guard + comentários).
- [ ] **Step 4: Rodar e ver passar** + regressão `-k "orchestrator or retry or media"` + suíte completa.
- [ ] **Step 5: Commit** — `fix(orchestrator): guard de midia ciente de falha + testes de composto + comentarios (follow-up review E2)`.
