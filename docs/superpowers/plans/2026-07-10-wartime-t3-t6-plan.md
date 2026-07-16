# Plano de Implementação — Wartime T3+T4+T6b (broadcast), T5 (watchdog), T6a (DB retry)

**Spec:** `docs/superpowers/specs/2026-07-10-wartime-t3-t6-broadcast-cadencia-db-design.md`
**Branch:** `fix/wartime-t3-t6`
**Execução:** 3 pacotes com fronteiras de arquivo disjuntas, em paralelo.

---

## Pacote C1 — Broadcast/Meta (T3 + T4 + T6 parte broadcast)

**Arquivos:** `backend/app/templates/preflight.py` (novo), `backend/app/broadcast/router.py`,
`backend/app/broadcast/worker.py`, `backend/app/broadcast/service.py`,
`backend/app/follow_up/scheduler.py` (SOMENTE o ramo de auto-resolve de billing,
~linhas 276-297), `backend/.env.example`, testes.

- [ ] C1.1 `app/templates/preflight.py`: `validate_template_for_broadcast(...)` com as 4
      checagens da spec (existência/aprovação, locale, params do BODY
      posicional/nomeado/`__params_type__`, header). Extração de placeholders por regex
      sobre o texto do BODY aprovado. Erros legíveis PT-BR. Fail-closed com
      `PREFLIGHT_TEMPLATE=off` como kill-switch. Lookup local com fallback Meta API +
      auto-sync (reusar o padrão de `_render_template_body` — extrair helper se
      necessário, sem quebrar o call-site existente).
- [ ] C1.2 `broadcast/router.py::start_broadcast`: chamar o preflight após o guard de
      billing; erros → HTTPException 400 listando todos.
- [ ] C1.3 `broadcast/worker.py`: classe de erro de template no send (132000/132001/
      132005/132007/132012/404-template) → `mark_broadcast_lead_failed` sem requeue +
      contador consecutivo por broadcast; >=3 → pausa + `create_system_alert(
      "broadcast_template_error", severity="critical")`. Sucesso de send zera o contador.
- [ ] C1.4 T4: `broadcast/service.py::pause_broadcast_for_billing` grava marcador Redis
      `billing:paused_broadcast:{id}` TTL 7d best-effort; nova
      `resume_broadcasts_after_billing()` (varre marcadores, resume só `status='paused'`,
      `emit_event("broadcasts")`, DEL, alerta warning `broadcast_auto_resumed`; paused
      manual → só DEL). Hook fail-soft de 1 chamada no ramo de auto-resolve do health
      check em `follow_up/scheduler.py` (mexer APENAS nesse ramo — o arquivo tem
      desenvolvimento remoto ativo).
- [ ] C1.5 T6b: envolver os marks/increments/requeue de `broadcast/service.py` em
      `run_with_retry` (transporte só).
- [ ] C1.6 Testes: preflight (4 checagens × ok/erro, kill-switch, fail-closed sem
      DB/Meta), start bloqueado, send-side (classe template sem requeue, pausa no 3º,
      reset no sucesso), auto-resume (só paused, marcador consumido, alerta), retry dos
      marks. Rodar `pytest -q tests -k "broadcast or preflight or template" -m "not
      integration"`.

## Pacote C2 — Watchdog (T5)

**Arquivos:** `backend/app/watchdog/service.py`, testes.

- [ ] C2.1 `check_cadence_dead(now)`: padrão dos checks existentes (`check_ai_unresponsive`
      etc.); condição = janela 08h-20h BRT E existe mensagem `assistant` nas últimas 24h
      E zero `follow_up_jobs` com `created_at` nas últimas 24h → alerta `cadence_dead`
      critical, dedup 1/24h (padrão dos alertas do repo). Fail-open em erro de query.
- [ ] C2.2 Registrar o check no ciclo do watchdog (onde os demais são chamados).
- [ ] C2.3 QA diário: breakdown por `job_type` (criados e executados 24h) em
      `_qa_collect_metrics` + mensagem (padrão -1 = indisponível).
- [ ] C2.4 Testes: dispara nas condições exatas; silêncio sem tráfego assistant; silêncio
      fora do horário; dedup; QA com breakdown. Rodar `pytest -q tests -k "watchdog or
      cadence or qa" -m "not integration"`.

## Pacote C3 — DB retry (T6a)

**Arquivos:** `backend/app/conversations/service.py`, `backend/app/leads/service.py`, testes.

- [ ] C3.1 `save_message` e `update_conversation`: corpo em `run_with_retry(lambda: ...,
      label="save_message"/"update_conversation")`. Sem mudança de assinatura/retorno.
- [ ] C3.2 `update_lead`: idem (`label="update_lead"`).
- [ ] C3.3 Testes: `httpx.RemoteProtocolError` transitório → retry e sucesso; erro de
      aplicação (HTTPStatusError/APIError) → NÃO retenta e propaga como hoje. Rodar
      `pytest -q tests -k "conversations or leads or retry" -m "not integration"`.

## Validação consolidada

- [ ] V1. `pytest -q -m "not integration"` completo (1 falha conhecida e pré-existente:
      `test_worker_runtime::test_run_periodic_isola_excecao_e_continua`, timing/Windows —
      qualquer OUTRA falha bloqueia).
- [ ] V2. `python -m compileall app` + smoke de import dos módulos tocados.
- [ ] V3. Revisão do diff consolidado (C1.4 é o único ponto que toca arquivo de
      desenvolvimento remoto ativo — conferir se o hook ficou contido no ramo).
- [ ] V4. `.env.example` com `PREFLIGHT_TEMPLATE` documentado.

## Riscos
- `follow_up/scheduler.py` recebeu 3 commits remotos hoje — C1.4 é 1 chamada fail-soft
  num ramo estável; qualquer conflito de merge na subida se resolve a favor do remoto.
- Marcador Redis do T4: perda do marcador = resume manual (status quo), nunca resume
  errado.
