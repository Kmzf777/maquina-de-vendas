# Wartime: Parking de exaustão de budget/quota + Alertas que encontram o operador

**Data:** 2026-07-10 · **Escopo:** T1 + T2 do plano wartime · **Branch:** `fix/wartime-budget-parking-alerts`

## Problema

1. **Exaustão de dinheiro é tratada como outage de minutos.** `LLMBudgetExceededError`
   herda de `LLMUnavailableError` (`orchestrator.py:474`), então estouro do teto diário
   (`budget_guard`) e exaustão de quota diária do Google caem no mesmo parking de 30 min
   (`LLM_PARK_MAX_MINUTES`, `parking.py`). Como o bloqueio dura até a virada do dia, todo
   lead que responde a um disparo após o estouro é estacionado por 30 min e depois recebe
   **handoff cego definitivo** (`ai_enabled=false`) — o funil do dia inteiro é queimado.
   Repetição industrializada do incidente de 08/07 (2/9 respostas com handoff cego em
   13 min de outage).
2. **O alarme não encontra o operador.** O kill-switch de budget dispara apenas
   `logger.critical` (`budget_guard.py:68`) — sem alerta em `system_alerts`, sem aviso a
   80% do teto. Os alertas existentes (billing 131042, llm_down) só aparecem como banner
   no CRM; o operador descobre incidentes por reclamação de lead.

## O quê (comportamento-alvo)

### T1 — Modo "cofre vazio" (parking de longa duração)

- Exaustão longa (kill-switch interno, quota diária Google, billing 403 Google) é uma
  **categoria própria** de indisponibilidade, distinta de outage transitório.
- Lead que escreve durante exaustão: turno **estacionado até o reset do budget/quota**
  (não 30 min), recebe **uma** mensagem estática de espera na persona (com cooldown) e
  **nunca** sofre handoff cego dentro do prazo de reset.
- Quando o LLM volta (drain), a Valéria responde o turno normalmente relendo o histórico.
- Handoff continua existindo como **último recurso**: só após o deadline de reset + folga.

### T2 — Alertas com entrega externa

- Kill-switch de budget dispara alerta próprio (`llm_budget_exceeded`, critical) no
  momento do trip, e aviso preventivo (`llm_budget_warning`, warning) a 80% do teto —
  ambos com dedup de 1/dia.
- Todo `create_system_alert` com `severity="critical"` é despachado também para:
  (a) **Sentry** (`capture_message` — e-mail do free tier é o canal garantido) e
  (b) **WhatsApp do admin** (`ADMIN_ALERT_PHONE`) via o canal Meta ativo — best-effort.
- `severity="warning"` → só Sentry.

## Por quê (regras de negócio)

- Handoff é ação definitiva (desliga a IA); custo de um estouro de budget deve ser
  **latência**, não o funil. O drain já relê o histórico completo — resposta atrasada é
  íntegra por construção (contrato existente do parking).
- O disparo outbound é pago; cada lead que responde é o ativo mais caro da operação.
  Ghosting é inaceitável (classe apagão 01-02/07), por isso a mensagem de espera.
- Alerta que só vive no CRM não reduz MTTR. Sentry já está integrado e é grátis; o canal
  WhatsApp é da própria operação (custo: centavos/conversa; zero infra).

## Design

### T1.1 Classificação de erro (`app/agent/orchestrator.py`)

Nova hierarquia (retrocompatível — tudo continua sendo `LLMUnavailableError`):

```
LLMUnavailableError                  # transitório (comportamento atual)
└── LLMExhaustedError                # NOVO: não volta em minutos
    ├── LLMBudgetExceededError       # kill-switch interno (reclasse: agora herda de Exhausted)
    └── LLMQuotaExhaustedError       # NOVO: quota diária/billing do lado Google
```

Em `_generate_with_retry`:
- 429 cuja mensagem contém marcador de quota **diária** (`PerDay`, `per day`,
  case-insensitive) → `LLMQuotaExhaustedError` **imediato** (retry é inútil e queima RPM).
- 403 (billing/permissão): mantém os 3 retries atuais; ao esgotar, levanta
  `LLMQuotaExhaustedError` (histórico: 403 nunca é transitório de segundos).
- 429 rate-limit comum e 5xx: comportamento atual intocado (`LLMUnavailableError`).

### T1.2 Parking com deadline por entrada (`app/buffer/parking.py`)

- `park_turn(..., reason)` com `reason ∈ {"transient", "budget", "quota"}`; a entrada no
  hash ganha `reason` e `deadline` (ISO):
  - `transient` → `parked_at + LLM_PARK_MAX_MINUTES` (30, atual).
  - `budget` → próxima meia-noite **UTC** (reset do `budget_guard`) +
    `LLM_PARK_EXHAUSTED_GRACE_MINUTES` (default 30).
  - `quota` → próxima meia-noite **America/Los_Angeles** (reset das quotas diárias da
    Gemini API) + a mesma folga.
  - Ambos exaustos: teto duro `parked_at + LLM_PARK_EXHAUSTED_MAX_HOURS` (default 26h).
- **Retrocompatibilidade:** entrada sem `deadline`/`reason` (estacionada por versão
  anterior) usa o comportamento antigo (`parked_at + 30min`, transient).
- **Mensagem de espera:** ao estacionar com reason exausto, envia UMA mensagem estática
  na persona (minúsculas, sem prometer prazo):
  `"oi! me desculpa a demora, tô finalizando uns atendimentos aqui 🙈 já te respondo, tá?"`
  — via provider do canal da conversa, com `save_message` (aparece no CRM), guardada por
  cooldown Redis `llm:hold_msg:{conversation_id}` (SETNX, TTL
  `LLM_HOLD_MSG_COOLDOWN_HOURS`, default 6h). Suprimida em `REHEARSAL_MODE`. Fail-soft:
  falha no envio não impede o estacionamento. A janela de 24h da Meta está aberta por
  construção (o lead acabou de escrever).
- **Drain econômico:** para entradas exaustas:
  - `reason="budget"`: se `budget_guard.is_exceeded()` ainda for True → pula a entrada
    sem chamar a API (check cacheado, custo zero).
  - `reason="quota"`: throttle de retry — só tenta a cada `LLM_PARK_RETRY_MINUTES`
    (default 5), gravando `last_attempt_at` na entrada (hset), para não queimar RPM a
    cada tick de 30s.
  - Passado o `deadline` com LLM ainda fora → handoff visível (caminho atual). Guards
    existentes (IA desligada, atividade mais nova) intocados.

### T1.3 Processor (`app/buffer/processor.py`)

- `_handle_llm_down(..., reason="transient")`; os callsites que capturam as exceções do
  agente mapeiam o tipo → reason (`LLMBudgetExceededError`→"budget",
  `LLMQuotaExhaustedError`→"quota", demais→"transient").
- Com `reason="budget"`, **suprime** o alerta `llm_down` (o alerta dedicado de budget do
  T2 já cobre; evita ruído duplo). Contador de falhas consecutivas continua rodando.
- Fallback inalterado: parking off ou Redis fora → handoff imediato (como hoje).

### T2.1 Alertas de budget (`app/agent/budget_guard.py`)

- No trip do kill-switch: `fire_budget_alert(spend, limit)` → alerta
  `llm_budget_exceeded` (critical), mensagem com gasto/teto e instrução ("chamadas
  bloqueadas até a virada do dia UTC; turnos estão sendo estacionados").
- A 80% do teto (sem trip): `llm_budget_warning` (warning), 1x/dia.
- Dedup em duas camadas: flag in-process por dia UTC (caminho quente não toca o banco) +
  query de dedup no banco (1 não-resolvido/24h, padrão `fire_billing_alert`). Fail-soft.
- Virada do dia com gasto < teto: auto-resolve alertas `llm_budget_*` abertos (fail-soft).

### T2.2 Despacho externo (`app/alerts/service.py`)

- `create_system_alert` ganha um hook `_notify_external(type, title, message, severity)`:
  - `critical` → `sentry_sdk.capture_message(..., level="error")` + WhatsApp ao admin.
  - `warning` → só Sentry (`level="warning"`).
  - Sentry: import guardado (mesmo padrão fail-open de `observability.py`); sem DSN = no-op.
  - WhatsApp: `ADMIN_ALERT_PHONE` (dígitos E.164; ausente = skip), canal =
    `ALERT_CHANNEL_ID` → `get_channel_by_id`, senão `get_active_channel()`;
    `provider.send_text(phone, "🚨 {title}\n\n{message}")`. Despacho async fail-soft:
    `get_running_loop().create_task(...)`; sem loop → `asyncio.run`. Skip em
    `REHEARSAL_MODE`.
- **Limitação documentada:** free-form só entrega com a janela de 24h do admin aberta
  (o admin deve mandar uma mensagem ao número da Valéria e fixar a conversa; o canal
  **garantido** é o e-mail do Sentry). Template de utilidade aprovado
  (`ALERT_TEMPLATE_NAME`) fica como evolução futura — fora de escopo.
- O hook herda o dedup dos callers (billing 1/h, llm_down 1/h, budget 1/dia) — sem novo
  mecanismo de rate-limit.

## Novos knobs de env (todos com default seguro; nenhum exige deploy coordenado)

| Env | Default | Papel |
|---|---|---|
| `LLM_PARK_EXHAUSTED_GRACE_MINUTES` | 30 | folga pós-reset antes do deadline |
| `LLM_PARK_EXHAUSTED_MAX_HOURS` | 26 | teto duro do parking exausto |
| `LLM_PARK_RETRY_MINUTES` | 5 | throttle de retry do drain p/ reason=quota |
| `LLM_HOLD_MSG_COOLDOWN_HOURS` | 6 | cooldown da mensagem de espera por conversa |
| `ADMIN_ALERT_PHONE` | (vazio=off) | WhatsApp do operador p/ alertas critical |
| `ALERT_CHANNEL_ID` | (vazio) | canal Meta p/ envio de alerta; fallback `get_active_channel()` |

Pré-existentes que o T0 valida na VPS: `LLM_DAILY_COST_LIMIT_USD` (0=kill-switch OFF),
`LLM_PARKING` (≠off), `SENTRY_DSN`.

## Fora de escopo (explícito)

Template de utilidade aprovado para alerta; auto-resume de broadcast (T4); pre-flight de
template (T3); detector de cadência (T5); retry uniforme Supabase (T6); qualquer mudança
no CRM/Next.js.

## Critérios de aceite / testes

1. 429 "per day" → `LLMQuotaExhaustedError` na 1ª tentativa (sem retries); 429 comum e
   5xx → comportamento atual; 403 → exausto após 3 retries.
2. Budget estourado + lead escreve → turno estacionado com `reason="budget"`, deadline na
   virada UTC + folga, mensagem de espera enviada 1x (cooldown respeitado, suprimida em
   rehearsal), **nenhum** handoff, **nenhum** alerta `llm_down`.
3. Drain com budget ainda estourado → entrada pulada sem chamada de API; budget liberado
   → turno respondido e entrada removida; deadline vencido com LLM fora → handoff visível.
4. Entrada legada (sem `deadline`) → comportamento antigo (30 min).
5. Trip do kill-switch → alerta `llm_budget_exceeded` critical (1/dia); 80% → warning
   (1/dia); virada do dia → auto-resolve.
6. Alerta critical → `capture_message` chamado quando Sentry disponível + `send_text` ao
   `ADMIN_ALERT_PHONE` quando configurado; sem env → no-op silencioso; falha de envio
   nunca escala.
7. Suíte existente de parking/orchestrator/llm-down passa sem alteração de contrato
   (subclasses preservam `except LLMUnavailableError`).
