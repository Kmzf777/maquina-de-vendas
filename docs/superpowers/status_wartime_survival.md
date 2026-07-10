# Status — Pacote de Sobrevivência Wartime (T0–T6)

**Concluído em:** 2026-07-10/11 · **Em produção:** pushes `de322b4` (T1+T2) e `984435e` (T3–T6)
**Specs:** `specs/2026-07-10-wartime-budget-parking-alerts-design.md` · `specs/2026-07-10-wartime-t3-t6-broadcast-cadencia-db-design.md`

## Missão

Operação em modo sobrevivência: a única métrica é **Valéria convertendo leads B2B via
outbound todos os dias, sem quebrar**. O pacote ataca a causa nº 1 de incêndio operacional:
degradação silenciosa quando dinheiro/quota acaba (LLM, Meta, banco).

## Nova baseline de resiliência

- **T0 — Config armada na VPS:** `LLM_DAILY_COST_LIMIT_USD` > 0 (kill-switch ativo),
  `ADMIN_ALERT_PHONE`, `SENTRY_DSN`; janela de 24h do admin aberta com a Valéria.
- **T1 — Exaustão de dinheiro vira LATÊNCIA, não funil queimado:** estouro de budget
  interno ou quota diária do Google estaciona o turno até o reset (00:00 UTC / 00:00
  Pacific) com mensagem de espera na persona (1x/6h). Handoff cego deixou de ser o
  destino padrão; é último recurso pós-deadline. Drain econômico: zero chamada de API
  com budget estourado; throttle de 5min para quota.
- **T2 — Alarme que encontra o operador:** todo alerta critical (budget, billing Meta,
  LLM fora, template, cadência) chega por **Sentry (e-mail, garantido)** e **WhatsApp do
  admin (best-effort)**. Aviso preventivo a 80% do teto diário. Fim do "descobrir pelo
  lead reclamando".
- **T3 — Broadcast não queima mais lista:** pre-flight fail-closed no start (template
  existe/aprovado, locale, params, header — todos os erros de uma vez, 400 legível;
  kill-switch `PREFLIGHT_TEMPLATE=off`) + circuit breaker no envio (erro de template ×3
  → pausa + alerta critical, sem requeue, sem loop infinito).
- **T4 — Billing normalizado = disparo retoma sozinho:** broadcast pausado por 131042 é
  marcado (Redis, TTL 7d) e o health check horário o retoma quando a Meta volta a
  responder OK, com alerta de visibilidade. Pausa manual do operador sempre vence.
- **T5 — Cadência morta é alarme no mesmo dia:** watchdog Check 6 (`cadence_dead`):
  Valéria conversou nas últimas 24h + zero `follow_up_jobs` criados → alerta critical.
  Detecta o modo de morte real do incidente 26/06→09/07 (13 dias sem cadência, invisível).
  QA diário com breakdown criados/executados por job_type.
- **T6 — Rajada de disparo não perde writes:** `run_with_retry` (só transporte:
  GOAWAY/ConnectionTerminated) nos hot writes — `save_message`, `update_conversation`,
  `update_lead`, marks/increments de broadcast.

## Garantias de processo

- 111 testes novos; suíte completa **2.055 passed, 0 failed** no consolidado.
- Zero migração de schema (nenhum acoplamento deploy-automático ↔ migração manual).
- Todo mecanismo novo tem kill-switch por env, sem deploy.

## Limitações conhecidas (aceitas em wartime)

- Alerta WhatsApp é best-effort (exige janela 24h aberta); canal garantido = Sentry.
- Pauses de billing inline do worker (defense-in-depth) não gravam marcador de
  auto-resume — resume manual nesses caminhos (extensão trivial futura).
- Flaky local Windows: `test_worker_runtime::test_run_periodic_isola_excecao_e_continua`
  (timing; verde no CI Linux).

## Próximo checkpoint fora do escopo wartime

Migração Gemini 2.5 → 3.x: iniciar em **meados de setembro/2026** (sunset 16/10/2026);
smoke obrigatório = round-trip de 2 chamadas com tool (eco de `thought_signature`).
