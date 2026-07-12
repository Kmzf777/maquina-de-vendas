# Diagnóstico Completo de Custos LLM — Auditoria 360°

**Data:** 2026-07-12
**Escopo:** todo consumo Gemini do projeto (turno principal, workers de background, CI/rehearsal, scripts), cruzado com a telemetria real de produção (`token_usage`, período pós-fix 09/07 01:00 UTC → 12/07).
**Método:** 4 varreduras paralelas de código (montagem de prompt; loop/retries; consumidores de background; config/preços/cache) + quantificação read-only no Supabase de produção e homolog + histórico do GitHub Actions.
**Status:** somente diagnóstico. Nenhuma alteração de código foi feita.

---

## 1. Baseline econômico medido (produção, 3,5 dias pós-fix)

| Métrica | Valor |
|---|---|
| Gasto total | $4,9151 (≈ $1,40/dia) |
| Custo por atendimento | média $0,077 / mediana $0,071 / máx $0,23 |
| Participação do INPUT no custo | ~96% |
| Família `response*` no custo | 97,9% ($4,81) |
| Chamadas LLM por turno de conversa | **média 3,16 / máximo 18** |
| Input por turno | média 102.624 tokens (~33K × 3,16 chamadas) |
| Cache hit (implicit) nas respostas | **9,9%** (1,35M de 13,6M tokens) |
| Retries (`response_retry`+`retry2`) | $0,51 (10,4%) para **2.294 tokens úteis de saída** |
| Thoughts (thinking) | 78% do output das respostas (77,9K de 99,7K tokens ≈ 4% do custo total) |
| Homolog/dev (mesma família de faturas) | **0 chamadas desde 05/07** — 100% da conta é produção |

**Concentração decisiva:** turnos com ≥5 chamadas LLM são **23% dos turnos mas 51% do custo de resposta**:

| Chamadas no turno | Turnos | % turnos | Custo | % custo |
|---|---|---|---|---|
| 1–2 | 90 | 59% | $1,35 | 28% |
| 3–4 | 28 | 18% | $0,99 | 21% |
| 5–6 | 21 | 14% | $1,25 | 26% |
| 7+ (até 18) | 13 | 9% | $1,22 | 25% |

---

## 2. Falhas conceituais (as causas por trás dos ralos)

**A. Cache por acidente, não por arquitetura.** O sistema confia 100% no implicit caching do Gemini, mas o prompt foi desenhado para leitura humana, não para cache: o bloco volátil `<context>` (data, saudação, nome, CRM, dossiê) fica no **meio** do system prompt, com ~7,7K tokens estáticos (stage + catálogo + FINAL_INSTRUCTION) **depois** dele (`orchestrator.py:716-719`). Resultado medido: hit-rate de 9,9% quando o prefixo estático teórico é de 22K+ tokens. Ninguém monitorava esse número até esta auditoria.

**B. Retry como estratégia, não como exceção.** A escada de retries (silencioso → Change-B → retry2 temp 0,9 → loop-guard → repeat-fix, `orchestrator.py:932-1375`) trata o sintoma "resposta vazia" reenviando o prompt inteiro de ~33K tokens até 10-11 vezes num único turno — e o processor ainda re-executa o `run_agent` inteiro ×3 em exceção genérica (`processor.py:1422-1539`). 10,5% das chamadas iniciais caem em retry. **Causa raiz provável e nunca atacada:** a 1ª chamada roda com thinking LIGADO (`LLM_INITIAL_THINKING` default `on`, `orchestrator.py:518`) compartilhando o budget de `MAX_OUTPUT_TOKENS=4096` — thinking come o budget e a resposta sai vazia (padrão já documentado no incidente de thinking tokens). Pagamos o thinking, pagamos o vazio e pagamos o retry.

**C. Tamanho único para qualquer turno.** "ok, obrigado" e uma negociação de preço multi-tool custam o mesmo: `gemini-2.5-flash` + persona completa de ~30K tokens + 12–15 tools (~4–5K tokens). Não existe roteamento por complexidade (`orchestrator.py:53,769`).

**D. Prompt que cresce por acreção.** Cada incidente colou uma regra nova sem orçamento de tokens: regra de preço em **3 lugares** (`base.py:223-234`, `orchestrator.py:676-690`, `atacado.py:38-59`), circuit breaker em 3 (`base.py:604-645`, `atacado.py:12-16`, `tools.py:258`), handoff/despedida duplicado entre regras 16/16b e a descrição da tool, CHECKLIST de 30 itens (~2K tokens) que reafirma as regras 1–35 do mesmo prompt (`base.py:1064-1099`). Descrições de tools de até 1.606 chars repetem regras do base (`tools.py:247-268`).

---

## 3. Plano de ataque — ordenado por ROI (economia ÷ esforço)

### P0 — Knobs de env, zero código (fazer primeiro)

**#1. Desligar thinking da 1ª chamada: `LLM_INITIAL_THINKING=off`**
- **Ralo:** thoughts = 78% do output das respostas (~$0,19/período) + hipótese forte de ser a causa dos 10,5% de respostas vazias que alimentam a escada de retry ($0,51/período). Todos os retries já rodam com thinking OFF e funcionam — o sistema já opera majoritariamente sem thinking.
- **Ação:** setar a env em produção; monitorar por 48h a taxa de `response_retry` (deve CAIR se a hipótese estiver certa) e a qualidade (guard de adherence / daily_qa).
- **Economia estimada:** 10–14% do gasto total. **Esforço:** 1 linha de env, reversível na hora.
- **Risco:** perda de qualidade em turnos complexos — medir antes de aceitar; se a qualidade cair, alternativa é thinking budget fixo baixo (exige código).

**#2. Armar o kill-switch de custo diário: `LLM_DAILY_COST_LIMIT_USD`**
- **Ralo (latente):** hoje = `0` = desligado (`budget_guard.py:40`). O loop do rolling_summary (corrigido em 53bcdf2) queimou ~R$149 antes de detecção manual — a classe de falha "runaway invisível" continua sem trava.
- **Ação:** setar ~3× o pico diário observado (ex.: `8` USD). Parking/alerta já existem (T1/T2 wartime).
- **Economia:** $0 no dia a dia, teto no dia do desastre. **Esforço:** 1 env.

### P1 — PRs pequenos, ganho estrutural

**#3. Reordenar o prompt para maximizar o prefixo cacheável**
- **Ralo:** hit-rate 9,9%. Dois defeitos: (a) stage+catálogo+FINAL_INSTRUCTION (~7,7K tokens estáticos-por-stage) vêm DEPOIS do `<context>` volátil (`orchestrator.py:716-719`) — nunca cacheiam cross-lead; (b) `Hoje é: {data}` e `Saudacao sugerida` dentro do `<context>` (`base.py:1131-1132`) resetam o cache diariamente/na virada de hora até para o MESMO lead.
- **Ação:** ordem nova = base estático → stage → preâmbulo do catálogo → FINAL_INSTRUCTION → **bloco volátil por último** (catálogo dinâmico + context). Avaliar remover a data do system (ela pode viajar no primeiro content do usuário). Prefixo cacheável cross-lead (mesmo stage): 22,3K → ~30K tokens.
- **Economia estimada:** hit-rate 10% → 30–45% ⇒ **12–18% do gasto total** (token cacheado custa 25%). **Esforço:** pequeno — reordenar concatenação em `build_system_prompt` + mover 2 linhas do template + rodar a suíte (prompts têm testes estruturais).
- **Risco:** sensibilidade do modelo à ordem dos blocos — validar com rehearsal/QA antes do push.

**#4. Deduplicar tool-call repetida e conter turnos patológicos**
- **Ralo:** 51% do custo de resposta em turnos com ≥5 chamadas (máx 18). Cada iteração do loop ReAct reenvia system prompt + contents CRESCENTE sem nenhum encolhimento (`orchestrator.py:923-996`); pós-MAX_TOOL_ITERATIONS ainda há a chamada loop-guard pagando tudo de novo (`orchestrator.py:932-945`).
- **Ação (investigar antes de mexer):** extrair dos logs QUAIS tools loopam nos turnos 7+ (suspeitos históricos: re-execução por eco de thought_signature, tools idempotentes chamadas em série). Candidatos: no-op/dedup de tool repetida com os mesmos args no mesmo turno; avaliar `MAX_TOOL_ITERATIONS` 5→3 (a distribuição mostra que turnos legítimos raramente passam de 4 rodadas).
- **Economia estimada:** 10–20% do custo de resposta. **Esforço:** médio (análise + guarda determinística + testes).

**#5. Rehearsal: consertar E definir política de custo ANTES de armar**
- **Estado real:** o gate diário **falhou em 10, 11 e 12/07** (3/3 execuções) — custo $0, valor $0 (provável causa: os 4 secrets pendentes do `rehearsal.yml`). Quando funcionar, cada run = 10 arquétipos × até 20 turnos × persona completa (~30K tokens/chamada, loop ReAct) + juiz **gemini-2.5-pro** — estimativa **$2–5/run, DIÁRIO, invisível** (chaves isoladas, sem `track_token_usage` no ator/juiz — `gemini_actor.py`).
- **Ação:** ao consertar os secrets, mudar o cron de diário para 2×/semana + `workflow_dispatch` pré-deploy, e logar o custo do run no summary do CI.
- **Economia:** evita criar um ralo NOVO maior que a própria produção. **Esforço:** 1 linha de cron + secrets.

**#6. `qualification_summary` → flash-lite**
- **Ralo:** tarefa mecânica (briefing de handoff) herdando o modelo do agente (flash), com histórico completo e 4096 de output (`summary.py:109-119`). Só $0,037/período, mas o padrão já existe (`MEMORY_MODEL`/`TRANSCRIPTION_MODEL` env-revertíveis).
- **Economia:** ~0,7% do gasto. **Esforço:** trivial (mesmo padrão de env). ROI alto pela facilidade, impacto pequeno.

### P2 — PRs médios (fazer após medir o efeito de P0/P1)

**#7. Comprimir TOOLS_SCHEMA (~4–5K tokens por chamada, toda chamada)**
- Descrições-romance: `encaminhar_humano` 1.606+969 chars, `registrar_sem_interesse_atual` 1.204+749, `retomar_contato_vendedor` 923 (`tools.py:208-671`) — grande parte repete regras que JÁ estão no base prompt. Alvo: −40% ⇒ ~−2K tokens/chamada ≈ −6% do input. **Risco:** comportamento das tools é sensível às descriptions — exige rehearsal verde antes/depois. *(Nota: tools são parâmetro separado do system_instruction; confirmar se entram no prefixo cacheável — se não entrarem, a compressão vale integral.)*

**#8. `ai_reengage`/`ai_scheduled_return` com contexto reduzido**
- Ambos usam `run_agent` completo (persona ~21–30K + loop ReAct) para gerar 1–2 bolhas de reengajamento (`scheduler.py:1131,1272`) — o mesmo desperdício que o follow-up padrão tinha antes do voice_card (−90% input naquele caso). Volume hoje é baixo; cresce linearmente com a cadência 4-touch. Avaliar voice_card + subset mínimo de tools.

**#9. Histórico: cap por tokens e janela útil real**
- `get_history(limit=60)` fixo, sem cap de tokens (`orchestrator.py:799`, `service.py:396-410`); as 60 linhas INCLUEM system-rows que são descartadas na montagem (`orchestrator.py:831-832`) — paga-se a janela cheia e usa-se menos. Conversas longas re-pagam a cauda inteira a cada chamada × 3,16 chamadas/turno. Ação: filtrar system-rows na query + cap por tokens (~8–10K). Economia: 5–10% em conversas longas. **Risco:** perda de memória conversacional — o dossiê (rolling_summary) existe exatamente para compensar; validar que está populado antes (GAP conhecido: backfill pendente p/ leads antigos).

### P3 — Alto esforço / ROI menor depois do cache (não começar por aqui)

**#10. Dedup do base prompt** — triplicações (§2.D) + CHECKLIST 30 itens: alvo −20% do base (~4,5K tokens). Foi deliberadamente adiado na auditoria de 08/07 porque o caching tornaria token repetido barato — decisão continua correta, MAS só depois do #3 entregar hit-rate real. Risco comportamental alto (cada regra nasceu de um incidente).

**#11. Roteamento por complexidade** — flash-lite para turnos triviais (saudação, confirmação). Potencial grande em escala, risco de qualidade real. Só se o volume pós-disparo-em-massa justificar.

**#12. Explicit context caching** — **contra-intuitivo: NÃO vale a pena no volume atual.** Storage de cache explícito custa ~$1/M tokens/hora; manter 30K tokens vivos 12h/dia ≈ $0,36/dia de storage para economizar ~$0,50/dia de input — margem apertada e complexidade alta. Com 100+ atendimentos/dia a conta inverte com folga. Reavaliar ao escalar o outbound. (O #3 entrega a maior parte do ganho de graça via implicit.)

---

## 4. Higiene e governança (baixo custo, previne sangria futura)

| Item | Fato | Ação |
|---|---|---|
| Preços 3.5/3.1 não versionados | Nenhuma migração tem pricing p/ `gemini-3.5-flash`/`3.1-flash-lite` (a linha do 3.5 em prod foi manual, durante o incidente do falso sunset). Modelo sem pricing ⇒ `total_cost=0` **silencioso** (`token_tracker.py:94-96`) | Regra: troca de modelo exige migração de pricing no MESMO commit (mesma classe da lição da cadência morta por constraint) |
| `total_cost_override` morto | Nenhum call site usa (`token_tracker.py:58`) | Remover na próxima passada |
| Trabalho pago e descartado | Supersede pós-`run_agent` (janela de pacing 5–35s, `processor.py:1620-1628`) e retry ×3 do processor descartam chamadas já faturadas | Adicionar contador de descarte na telemetria ANTES de decidir se vale otimizar |
| Rehearsal sem telemetria | Ator/juiz não trackeiam (`gemini_actor.py`) | Logar custo estimado no summary do run |
| Preços 2.5 conferidos | model_pricing = tabela oficial Google ($0,30/$2,50 flash; $0,10/$0,40 lite; $1,25/$10 pro); `CACHED_INPUT_PRICE_FACTOR=0.25` correto | Nada — telemetria confiável ✓ |
| candidateCount / topP | Default 1 candidato, sem multi-sampling | Nada ✓ |

**Já bem feito (não regredir):** dossiê delta-only + watermark que avança mesmo sem mudança; voice_card no follow-up padrão (−90%); flash-lite em transcrição/dossiê; thinking OFF em todas as chamadas mecânicas; placeholders de mídia no histórico; dossiê injetado 1× (sem duplicação no histórico); coalescing 15/60s; abort pré-lock sem custo LLM; catálogo TTL 5min stale-if-error; healthcheck com `max_output_tokens=8`.

---

## 5. Projeção consolidada

| Fase | Economia estimada | Custo/atendimento projetado |
|---|---|---|
| Hoje | — | ~R$ 0,47 |
| Após P0 (#1) | −10–14% | ~R$ 0,40 |
| Após P1 (#3, #4) | −25–35% acumulado | ~R$ 0,31–0,35 |
| Após P2 (#7, #9) | −40–50% acumulado | **~R$ 0,24–0,28** |

A sequência importa: **#1 e #3 primeiro** (mudam a base sobre a qual tudo é medido), depois re-medir hit-rate/taxa de retry com a telemetria já existente (`cached_tokens`, `response_retry*`) e só então decidir quanto de P2/P3 vale o risco comportamental.
