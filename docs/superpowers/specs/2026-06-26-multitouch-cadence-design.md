# Planejador de Cadência Multi-touch Pró-ativa (Feature 3)

**Data:** 2026-06-26
**Feature:** Roadmap de Autonomia #3 — Cadência multi-touch state-based
**Status:** Design aprovado (decisões confirmadas)

---

## 1. Problema

O motor `follow_up/` nutre o lead com **exatamente 2 toques fixos** (`schedule_followup`:
seq1 jitter ~1.5–3.5h, seq2 ~23h) e, quando a **janela Meta de 24h fecha**, simplesmente
**cancela** o toque (`scheduler.py:511-525`, `cancel_reason="window_expired"`). Resultado: um
lead que esfria por mais de um dia nunca mais é nutrido — a IA fica refém da janela e desiste
em silêncio. Não há sequenciamento de objetivo por toque (Next Best Action), só "gerar uma
mensagem de follow-up genérica".

**Objetivo:** evoluir o `follow_up/` para uma **cadência multi-touch de 4 toques**, cada um com
um **objetivo** próprio, que **respeita a janela de 24h**: janela aberta → texto livre gerado
pela IA com base no objetivo + estado do funil; **janela fechada → dispara um template aprovado
pela Meta e agenda a retomada** (em vez de cancelar). Nada é descartado em silêncio.

---

## 2. Estado atual (grounding — lido no código)

| Peça | Onde | Hoje |
|---|---|---|
| Agendamento | `follow_up/service.py::schedule_followup` | cria 2 jobs fixos (seq1/seq2), clamp 09–16h seg–sex |
| Processamento | `follow_up/scheduler.py::process_due_followups` | gera msg via LLM; **janela fechada → cancela** (`window_expired`) |
| Geração de texto | `scheduler.py::_generate_followup_message(history, sequence, …)` | prompt por `sequence`, sem objetivo explícito |
| **Template + reopen (JÁ EXISTE)** | `scheduler.py::_process_ai_scheduled_return` (1083-1132) | janela fechada → dispara `continuar_conversa` (param nomeado `{{primeiro_nome}}`, `pt_BR`) → `status=awaiting_reopen`; trata erro Meta 4xx (`reopen_template_error_*`) e rejeição (`reopen_template_rejected`) |
| **Retomada (JÁ EXISTE)** | `service.py::consume_reopen_context` + `processor.py:782-785` | em todo inbound, se há `awaiting_reopen` dentro do **TTL 7 dias**, injeta `<retorno_agendado>` (motivo/contexto) e marca `sent`; fora do TTL → `expired` (anti-contexto-zumbi) |
| Cancelamento no inbound | `meta_router.py:95` | resposta do lead já cancela follow-ups pending |
| Registro de intenção de template | `templates/intent.py` | `classify_template_intent`, `dispatch_metadata` |
| Gatilho do agendamento | `processor.py:975` (gated por `marcar_interesse`/interesse) e `follow_up/router.py:69` | inalterado |
| Schema `follow_up_jobs` | DB prod | tem `sequence` int, `metadata` jsonb, `job_type`, `cancel_reason`, `status`, `sent_at` |

**Decisões confirmadas:**
- **D1 — Escopo:** evoluir **apenas** o `follow_up/`. NÃO tocar no `automation/` (motor de
  campanhas admin, já multi-touch por nós/flow-builder) — evita duplicação/colisão.
- **D2 — Definição:** **config-as-code + conteúdo por LLM**. O esqueleto da cadência (offset +
  objetivo por toque) é constante no módulo; o **texto** é gerado pelo LLM a partir do objetivo
  + estado do funil (Next Best Action). Zero conteúdo hard-coded; zero tabela de cadência nova.
- **D3 — Escada (4 toques)**, clampada a 09–16h seg–sex (`America/Sao_Paulo`):

| Toque | Offset (a partir do agendamento) | Objetivo (Next Best Action) |
|---|---|---|
| T1 | ~2h (jitter 90–210 min) | Reengajar / despertar curiosidade |
| T2 | ~1 dia útil | Reforço de valor (WIIFM) |
| T3 | ~3 dias | Prova social / quebra de objeção |
| T4 | **6 dias e 20h** (≈7d, mas seguramente < TTL de reopen de 7d — ver R3) | Última chamada |

Após T4, a cadência **para** (não há T5). Cada toque, independentemente: **janela aberta →
texto livre; janela fechada → template (se for o 1º) ou refresh do contexto de reabertura.**
Nenhum toque é "amarrado" a uma modalidade — cada um decide pela janela **viva** no momento do
disparo (o 1º template pode sair em T1, T2 ou T3, conforme quando a janela de fato fechar).

**Sem migração:** `follow_up_jobs.metadata` (jsonb) carrega o objetivo do toque; `sequence`
(int) carrega 1–4. Nenhuma coluna nova.

### Revisão de arquitetura (blockers desta versão)

- **R1 — Cadência fantasma (dead code em T3/T4):** com a trava `reopen_already_pending`
  original, se T2 fechasse a janela e marcasse `awaiting_reopen`, T3 e T4 apenas se cancelariam
  → "prova social" e "última chamada" morreriam no T2. **Correção:** o toque que encontra um
  `awaiting_reopen` já vivo **NÃO cancela cego** — ele **sobrescreve** o `metadata.contexto`/
  `motivo` do job de reabertura com o SEU objetivo (escalado) e se encerra
  (`cancel_reason="reopen_context_refreshed"`). Assim, se o lead responder no dia 4, a IA retoma
  com a estratégia mais recente. Garante 1 template vivo por conversa **e** preserva a escalada.
- **R2 — Colisão de clamp (encavalamento noite/fim de semana):** clampar cada offset
  isoladamente colapsa toques na mesma fronteira (ex.: lead esfria sex 23h → T1 e T2 caem ambos
  seg 09h). **Correção:** `build_touch_jobs` calcula os `fire_at` de forma **monotônica com
  `MIN_GAP`** — após clampar Tn, se `Tn <= fire_at(Tn-1) + MIN_GAP`, empurra para
  `clamp(fire_at(Tn-1) + MIN_GAP)`. Garante ordem e espaçamento mínimo sem precisar de
  business-hours-math completa.
- **R3 — T4 vs TTL de reopen:** o TTL de 7 dias é medido do **disparo do template** (`sent_at`)
  e é **lazy** (só no inbound), então a colisão real é marginal; ainda assim, alinhar T4 na
  fronteira exata torna o raciocínio frágil. **Correção (defensiva):** T4 = `days=6, hours=20`.

---

## 3. Arquitetura proposta

### 3.1 Config-as-code da cadência (`follow_up/cadence.py`, novo — leaf module)

```python
@dataclass(frozen=True)
class Touch:
    sequence: int
    offset: timedelta          # a partir do instante de agendamento
    jitter_minutes: tuple[int, int] | None  # só T1 (humaniza o 1º toque)
    objective: str             # rótulo curto do Next Best Action
    objective_prompt: str      # diretriz injetada no gerador de texto / contexto de reopen

CADENCE: tuple[Touch, ...] = (
    Touch(1, timedelta(0),                   (90, 210), "reengajar",      "..."),
    Touch(2, timedelta(days=1),              None,      "reforco_valor",  "..."),
    Touch(3, timedelta(days=3),              None,      "prova_social",   "..."),
    Touch(4, timedelta(days=6, hours=20),    None,      "ultima_chamada", "..."),  # R3
)

MIN_GAP = timedelta(hours=2)   # R2: espaçamento mínimo entre toques consecutivos
```

Função pura `build_touch_jobs(now, conversation_id, lead_id, channel_id, env_tag) -> list[dict]`
que devolve os 4 dicts de job prontos para insert (`fire_at`, `sequence`,
`metadata={objetivo, objective_prompt, contexto}`). Unit-testável sem rede.

**Cálculo monotônico do `fire_at` (R2):** itera os toques em ordem; para cada Tn,
`alvo = _clamp_to_business_window(now + offset(+jitter))`; se houver um Tn-1 e
`alvo <= fire_at(Tn-1) + MIN_GAP`, então `alvo = _clamp_to_business_window(fire_at(Tn-1) + MIN_GAP)`;
guarda `fire_at(Tn)=alvo`. Garante ordem estrita e espaçamento ≥ MIN_GAP mesmo quando o clamp
empurra vários toques para a mesma abertura comercial (seg 09h após um fim de semana).

### 3.2 `schedule_followup` (refator em `service.py`)

- Mantém: verificação de conversa, cancelamento idempotente de pending (preserva
  `handoff_rescue`/`lp_welcome`), `env_tag`, clamp de janela comercial.
- Troca os 2 jobs fixos por `build_touch_jobs(...)` (os 4 toques). Cada job grava em
  `metadata`: `objetivo`, `objective_prompt`, e `contexto` (= objetivo, para o reopen reusar
  `consume_reopen_context` sem alteração). Insert único em lote.

### 3.3 `process_due_followups` — ramo genérico (refator em `scheduler.py`)

O ramo genérico (após os `job_type` especializados) passa a ramificar por **estado da janela**,
no lugar do `cancel("window_expired")`:

```
guards atuais (followup_enabled, mode=human) — inalterados
janela 24h (last_customer_message_at da conversa):
  ABERTA  → caminho atual (texto livre), MAS passando o objetivo do toque ao gerador
  FECHADA → NÃO cancela cego:
     - se JÁ existe awaiting_reopen pending nesta conversa (R1, anti-cadência-fantasma):
         SOBRESCREVE metadata.contexto/motivo desse job com o objetivo DESTE toque (escalada)
         e encerra este toque com cancel_reason="reopen_context_refreshed". NÃO dispara 2º
         template. → o lead recebe no máx. 1 template; ao responder, a IA retoma com a
         estratégia mais recente (ex.: "última chamada" no dia 6).
     - senão (primeiro fechamento da cadência): dispara template aprovado de reabertura
       (continuar_conversa, {{primeiro_nome}}, pt_BR), persiste o disparo (corpo renderizado +
       dispatch_metadata), marca o job awaiting_reopen com metadata.motivo/contexto = objetivo
       do toque.
       Trata erro Meta exatamente como _process_ai_scheduled_return: 4xx →
       reopen_template_error_<status>; RuntimeError de rejeição → reopen_template_rejected
       (+ system_alert, degradação graciosa); 5xx/transitório → retry no próximo tick.
```

**Extração para reuso:** a lógica de "janela fechada → template + awaiting_reopen" já existe
inline em `_process_ai_scheduled_return`. Extrair para um helper compartilhado
`fire_reopen_template(job, lead, channel, conversation_id, now) -> bool` em `scheduler.py`, e
chamá-lo de ambos os caminhos (ai_scheduled_return e follow-up genérico). Não duplica a regra
crítica de template/locale/erro.

### 3.4 Geração de texto ciente de objetivo

`_generate_followup_message(history, sequence, lead_id, stage, objective_prompt=None)`: quando
`objective_prompt` é fornecido, ele entra no system prompt do gerador como a **Next Best
Action** daquele toque (ex.: "este é o toque de PROVA SOCIAL: traga um caso real/curto e uma
pergunta de reflexão; não repита o que já foi dito"). Sem `objective_prompt`, comportamento
atual (retrocompat). Todos os guardrails existentes seguem (deferral marker, `length`,
meta-comment, newline sanitize).

### 3.5 Retomada (reuso total, zero código novo)

Quando o lead responde a qualquer template de reabertura, `consume_reopen_context`
(`processor.py:782`) já injeta o `<retorno_agendado>` com o objetivo salvo e marca `sent`; o
`meta_router` já cancela os toques pending restantes. A cadência "morre" naturalmente assim que
o lead reengaja — exatamente o comportamento desejado.

---

## 4. Fluxo (exemplo)

1. Lead demonstra interesse e esfria → `schedule_followup` cria T1..T4 (`fire_at` monotônicos,
   clampados, espaçados ≥ MIN_GAP).
2. T1 (~2h, janela aberta) → texto livre "reengajar".
3. Lead silencia. T2 (~1 dia, janela fechada) → template `continuar_conversa` +
   `awaiting_reopen` (contexto="reforço de valor").
4. T3 (~3 dias): já há `awaiting_reopen` → **sobrescreve** o contexto desse job para
   "prova_social" e encerra (`reopen_context_refreshed`). Não dispara 2º template.
5. T4 (~6d20h): idem → contexto vira "última chamada". (Se em qualquer ponto o lead tivesse
   respondido, o inbound já cancelaria os toques pending e a IA retomaria via
   `<retorno_agendado>`.)
6. Lead responde dentro do TTL 7d → IA retoma com o objetivo MAIS RECENTE ("última chamada");
   pending restantes cancelados pelo inbound.

---

## 5. Testes (TDD)

`cadence.py` (puro):
1. `build_touch_jobs` cria 4 jobs com `sequence` 1..4, offsets corretos (T4 = 6d20h), T1 com
   jitter na faixa, todos com `fire_at` dentro da janela comercial (clamp),
   `metadata.objetivo`/`objective_prompt`.
2. **R2 — monotonia/espaçamento:** cenário "lead esfria sexta 23h" → T1 e T2 NÃO colidem; cada
   `fire_at(Tn) >= fire_at(Tn-1) + MIN_GAP` e todos dentro da janela comercial; ordem estrita.

`service.py`:
3. `schedule_followup` insere 4 jobs (não 2); cancela pending anteriores preservando
   handoff_rescue/lp_welcome. (fake supabase, padrão `test_cold_funnel_reflex`.)

`scheduler.py`:
4. Janela ABERTA → gera texto livre com `objective_prompt` do toque repassado ao gerador.
5. Janela FECHADA, sem awaiting_reopen → dispara template, marca `awaiting_reopen`, persiste
   disparo (mock provider/`send_template`).
6. **R1 — refresh:** Janela FECHADA, com awaiting_reopen já pending → SOBRESCREVE
   `metadata.contexto` do job de reabertura com o objetivo deste toque e encerra
   (`reopen_context_refreshed`); NÃO dispara 2º template; o job awaiting_reopen segue vivo com o
   contexto novo.
7. **R3/3a — modalidade decidida pela janela viva:** T2 com janela aberta por segundos → texto
   livre; T3 (janela já fechada) → 1º template. (O 1º template pode sair em T2 OU T3.)
8. Template 4xx → `reopen_template_error_<status>`; rejeição → `reopen_template_rejected`.
9. `fire_reopen_template` extraído: `_process_ai_scheduled_return` continua passando os testes
   existentes (sem regressão).
10. Guardrails atuais (deferral/length/meta-comment) seguem cancelando como hoje.

Rodar a suíte completa — sem regressão em `test_*followup*`, `test_agendar_retorno_*`,
`test_24h_window_*`.

---

## 6. Escopo / YAGNI

**Dentro:** `cadence.py` (config + builder), refator de `schedule_followup` (2→4 toques),
ramo de janela fechada do follow-up genérico (template+reopen via helper extraído), geração de
texto ciente de objetivo, testes.

**Fora:** motor `automation/` (D1); cadência editável por UI/admin (D2 — seria reescrever o
automation); novos templates Meta (reusa `continuar_conversa` já aprovado); mudanças no frontend
(nenhuma UI nova nesta feature); migração de schema (metadata jsonb já comporta).

---

## 7. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Spam de templates (1 por toque em janela fechada) | Só o 1º fechamento dispara template; toques seguintes fazem **refresh de contexto** (R1) — máx. 1 template vivo por conversa |
| Cadência fantasma (T3/T4 mortos) — R1 | Toque com awaiting_reopen vivo sobrescreve o contexto (escalada) em vez de cancelar; resumo usa o objetivo mais recente |
| Encavalamento de toques no clamp (noite/fds) — R2 | `build_touch_jobs` monotônico com `MIN_GAP` (≥2h, re-clampado) garante ordem e espaçamento |
| Custo de template | Reusa `continuar_conversa` (utility aprovado); só dispara em janela fechada; cadência para em T4 |
| Contexto zumbi na retomada | Reuso do TTL de 7 dias já existente (`consume_reopen_context`) |
| T4 colidir com a fronteira do TTL — R3 | T4 em 6d20h, seguramente < 7d; TTL é medido do disparo do template e é lazy (só no inbound) |
| Disparo de madrugada | `_clamp_to_business_window` em todos os `fire_at` (inalterado) |
| Rejeição/locale do template | Reuso do tratamento de erro de `_process_ai_scheduled_return` (4xx/rejeição/transitório), param **nomeado** + locale aprovado |
| Regressão no ai_scheduled_return ao extrair helper | `fire_reopen_template` coberto pelos testes existentes do ai_scheduled_return + novos |
| Lead responde no meio da escada | `meta_router` já cancela pending no inbound; reopen retoma o objetivo mais recente |

---

## 8. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `backend/app/follow_up/cadence.py` | **novo** — config-as-code dos 4 toques + `build_touch_jobs` |
| `backend/app/follow_up/service.py` | `schedule_followup`: 2→4 toques via `build_touch_jobs` |
| `backend/app/follow_up/scheduler.py` | ramo janela-fechada do follow-up genérico → `fire_reopen_template` (extraído); `_generate_followup_message` ciente de objetivo |
| `backend/tests/test_multitouch_cadence.py` | **novo** |
| (sem migração; sem frontend) | — |
