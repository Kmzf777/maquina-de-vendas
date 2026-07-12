# FinOps P0+P1 — Thinking condicional, kill-switch armado e prompt cache-first

**Data:** 2026-07-12 · **Origem:** `docs/superpowers/reports/diagnostico_completo_custos_llm.md` (P0 #1/#2 e P1 #3/#5 aprovados pelo usuário; P2/P3 explicitamente adiados)
**Restrição inegociável:** objetivo estritamente financeiro. Nenhum byte de CONTEÚDO de prompt muda — apenas ordem de blocos e política de thinking/orçamento. A Valéria fala exatamente igual.

## 1. P0-A — Política de thinking da 1ª chamada (inversão com fallback condicional)

**Problema medido:** a 1ª chamada é a única com thinking ligado (`LLM_INITIAL_THINKING` default `on`); thinking divide o budget de `MAX_OUTPUT_TOKENS=4096` e "queima o budget pensando" (causa documentada no próprio código, `orchestrator.py` bloco RETRY-ON-EMPTY) → 10,5% das iniciais voltam vazias → escada de retry re-paga o prompt de ~33K tokens. Retries = 10,4% do gasto; thoughts = 78% do output das respostas.

**Análise de segurança (a pergunta "cálculo de preço precisa de thinking?"):**
- O texto monetário visível ao lead (pós `calcular_orcamento`) JÁ é gerado com thinking OFF hoje (todas as chamadas pós-tool desligam thinking desde `test_gemini_thinking_off_post_tool.py`).
- As respostas de retry (thinking OFF) já são enviadas a leads reais diariamente — qualidade sem thinking é comportamento corrente, não experimento.
- O único papel exclusivo do thinking hoje é a SELEÇÃO de tools na 1ª chamada.

**Decisão (fallback condicional, opção sugerida pelo usuário):**
- Default invertido: `LLM_INITIAL_THINKING` passa a `off` (código e `.env.example`).
- **Fallback condicional:** no retry-on-empty silencioso (`response_retry`), o thinking usa a política OPOSTA à da 1ª chamada do turno: se a inicial rodou OFF (novo default) e veio vazia/degenerada, o retry roda com thinking LIGADO — turnos genuinamente difíceis ganham o budget de raciocínio na 2ª tentativa, sem pagar thinking nos ~90% de turnos normais.
- Rollback integral sem deploy: `LLM_INITIAL_THINKING=on` restaura o comportamento atual byte a byte (inicial ON, retry OFF).
- `retry2`/loop-guard/pós-tool: inalterados (thinking OFF).

**Métricas de aceite (48h pós-deploy):** taxa de `response_retry` ≤ atual (10,5%); share de thoughts em `response` ↓; adherence/daily_qa sem regressão.

## 2. P0-B — Kill-switch de orçamento armado

- `daily_cost_limit_usd()` (budget_guard.py): default de env ausente muda de `0` (desligado) para **`8`** USD/dia (~3× o pico diário observado de $2,39). Mudar o default no CÓDIGO garante produção armada sem depender de editar o `.env` do servidor.
- `LLM_DAILY_COST_LIMIT_USD=8` documentado em `.env.example` e setado em `.env.local` (dev).
- `0` explícito continua desligando (semântica preservada para quem QUER desarmar).
- Toda a máquina downstream (parking, alertas WhatsApp/Sentry, auto-resume na virada) já existe (wartime T1/T2) — só o teto estava desarmado.

## 3. P1 — Reordenação do prompt para caching (hit 9,9% → alvo 30–45%)

**Problema:** ordem atual `base(estático+<context> volátil) → stage → catálogo → FINAL_INSTRUCTION` deixa ~7,7K tokens estáticos-por-stage ATRÁS do bloco volátil — prefixo cacheável cross-lead para em ~22,3K tokens.

**Nova ordem (garantia de que o volátil fica no fim da cadeia):**
```
BASE_STATIC (76,5K chars, zero placeholders — vira constante de módulo)
→ stage_prompt (estático por stage)
→ catálogo (TTL 5min — quase-estático)
→ build_context_block(...)  ← ÚNICO bloco volátil (data, saudação, nome, CRM, dossiê)
→ FINAL_INSTRUCTION (estática, 259 chars — permanece literalmente a última tag, invariante XML preservada)
```
O prefixo byte-idêntico cross-lead (mesmo stage) passa a cobrir base+stage+catálogo (~30K tokens). Os únicos bytes pós-prefixo são context (~0,5–2K) + FINAL_INSTRUCTION.

**Implementação sem mudança de conteúdo:**
- `base.py`: o f-string gigante é fatiado no limite `</examples>\n\n<context>` (verificado: ZERO placeholders e zero `{{` no trecho estático) → `BASE_STATIC` (string plana de módulo) + `build_context_block()` (lógica volátil atual, inalterada). `build_base_prompt()` é mantida como `BASE_STATIC + "\n\n" + build_context_block(...)` — **byte-idêntica ao formato histórico** (compat com leads/service, scripts e ~35 arquivos de teste).
- `orchestrator.build_system_prompt()`: monta a nova ordem usando as duas peças.
- A data (`Hoje e: …`) PERMANECE no prompt (regra de negócio de contexto temporal intocada) — mas agora só invalida o sufixo volátil, não o prefixo.

## 4. Rehearsal — custo sob controle ANTES de armar

- **Causa raiz das 3 falhas (10–12/07):** os 4 secrets estão VAZIOS; o guard `require_isolated_gemini_key` aborta antes de qualquer chamada (custo real até hoje: $0).
- Cron: `0 9 * * *` (diário) → **`0 9 * * 2,5`** (ter/sex 06:00 BRT) — quando armado, o run completo (10 arquétipos × ≤20 turnos × persona ~30K + juiz 2.5-pro) custa ~$2–5; 2×/semana limita a ~$4–10/semana vs ~$14–35/semana.
- Secrets: `REHEARSAL_SUPABASE_URL` e `REHEARSAL_SUPABASE_SERVICE_KEY` (homolog) serão preenchidos nesta entrega. `REHEARSAL_GEMINI_API_KEY` e `GEMINI_API_KEY_DEV` exigem 2 chaves Gemini NOVAS e isoladas (Google AI Studio) — só o usuário pode criá-las; o gate continua abortando barato até lá.

## 5. Testes

- Atualizar pins de política: `test_llm_cost_guards_2026_07_07.py` (default budget/thinking), `test_gemini_thinking_off_post_tool.py` (1ª chamada agora OFF por default; variante `LLM_INITIAL_THINKING=on` preserva o caminho antigo).
- Novo `test_finops_p0_p1_2026_07_12.py`: (a) prefixo cross-lead de `build_system_prompt` byte-idêntico até o fim do catálogo; (b) `<context>` depois do catálogo e antes de `<final_instruction>`; (c) fallback condicional do retry (inicial OFF vazia → retry com thinking ON; env `on` → retry OFF como hoje); (d) default do budget = 8 e `0` desarma.
- Gate: suíte pytest completa verde (as ~35 suítes de aderência de prompt validam que o CONTEÚDO não mudou).

## Fora de escopo (P2/P3 — não fazer)

Compressão de TOOLS_SCHEMA, cap de histórico, dedup do base prompt, voice_card em ai_reengage, roteamento por complexidade, explicit caching, correção do glob stale do summary do rehearsal.
