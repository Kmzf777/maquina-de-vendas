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
| T4 | ~7 dias | Última chamada |

Após T4, a cadência **para** (não há T5). Cada toque, independentemente: **janela aberta →
texto livre; janela fechada → template + reopen.**

**Sem migração:** `follow_up_jobs.metadata` (jsonb) carrega o objetivo do toque; `sequence`
(int) carrega 1–4. Nenhuma coluna nova.

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
    Touch(1, timedelta(0),       (90, 210), "reengajar",      "..."),
    Touch(2, timedelta(days=1),  None,      "reforco_valor",  "..."),
    Touch(3, timedelta(days=3),  None,      "prova_social",   "..."),
    Touch(4, timedelta(days=7),  None,      "ultima_chamada", "..."),
)
```

Função pura `build_touch_jobs(now, conversation_id, lead_id, channel_id, env_tag) -> list[dict]`
que devolve os 4 dicts de job prontos para insert (com `fire_at` clampado, `sequence`,
`metadata={objetivo, objective_prompt, contexto}`). Unit-testável sem rede.

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
  FECHADA → NÃO cancela:
     - se JÁ existe awaiting_reopen pending nesta conversa → cancela este toque
       (cancel_reason="reopen_already_pending") para não empilhar templates
     - senão: dispara template aprovado de reabertura (continuar_conversa, {{primeiro_nome}},
       pt_BR), persiste o disparo (corpo renderizado + dispatch_metadata), marca o job
       awaiting_reopen com metadata.motivo/contexto = objetivo do toque.
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

1. Lead demonstra interesse e esfria → `schedule_followup` cria T1..T4 (`fire_at` clampados).
2. T1 (~2h, janela aberta) → texto livre "reengajar".
3. Lead silencia. T2 (~1 dia): janela talvez fechada → template `continuar_conversa` +
   `awaiting_reopen` (contexto="reforço de valor").
4. T3 (~3 dias): já há `awaiting_reopen` pending → `reopen_already_pending` (não empilha
   template). *(Se o lead tivesse respondido, T2..T4 já teriam sido cancelados pelo inbound e a
   IA teria retomado via `<retorno_agendado>`.)*
5. T4 (~7 dias): se ainda há awaiting_reopen pending → idem; senão dispara última chamada.
6. Lead responde dentro do TTL 7d → IA retoma o objetivo salvo; pending restantes cancelados.

---

## 5. Testes (TDD)

`cadence.py` (puro):
1. `build_touch_jobs` cria 4 jobs com `sequence` 1..4, offsets corretos, T1 com jitter na faixa,
   todos com `fire_at` dentro da janela comercial (clamp), `metadata.objetivo`/`objective_prompt`.

`service.py`:
2. `schedule_followup` insere 4 jobs (não 2); cancela pending anteriores preservando
   handoff_rescue/lp_welcome. (fake supabase, padrão `test_cold_funnel_reflex`.)

`scheduler.py`:
3. Janela ABERTA → gera texto livre com `objective_prompt` do toque repassado ao gerador.
4. Janela FECHADA, sem awaiting_reopen → dispara template, marca `awaiting_reopen`, persiste
   disparo (mock provider/`send_template`).
5. Janela FECHADA, com awaiting_reopen já pending → `reopen_already_pending` (não dispara 2º
   template).
6. Template 4xx → `reopen_template_error_<status>`; rejeição → `reopen_template_rejected`.
7. `fire_reopen_template` extraído: `_process_ai_scheduled_return` continua passando os testes
   existentes (sem regressão).
8. Guardrails atuais (deferral/length/meta-comment) seguem cancelando como hoje.

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
| Spam de templates (1 por toque em janela fechada) | Guard `reopen_already_pending`: no máximo 1 template de reabertura vivo por conversa por vez |
| Custo de template | Reusa `continuar_conversa` (utility aprovado); só dispara em janela fechada; cadência para em T4 |
| Contexto zumbi na retomada | Reuso do TTL de 7 dias já existente (`consume_reopen_context`) |
| Disparo de madrugada | `_clamp_to_business_window` em todos os `fire_at` (inalterado) |
| Rejeição/locale do template | Reuso do tratamento de erro de `_process_ai_scheduled_return` (4xx/rejeição/transitório), param **nomeado** + locale aprovado |
| Regressão no ai_scheduled_return ao extrair helper | `fire_reopen_template` coberto pelos testes existentes do ai_scheduled_return + novos |
| Lead responde no meio da escada | `meta_router` já cancela pending no inbound; reopen retoma o objetivo |

---

## 8. Arquivos afetados

| Arquivo | Mudança |
|---|---|
| `backend/app/follow_up/cadence.py` | **novo** — config-as-code dos 4 toques + `build_touch_jobs` |
| `backend/app/follow_up/service.py` | `schedule_followup`: 2→4 toques via `build_touch_jobs` |
| `backend/app/follow_up/scheduler.py` | ramo janela-fechada do follow-up genérico → `fire_reopen_template` (extraído); `_generate_followup_message` ciente de objetivo |
| `backend/tests/test_multitouch_cadence.py` | **novo** |
| (sem migração; sem frontend) | — |
