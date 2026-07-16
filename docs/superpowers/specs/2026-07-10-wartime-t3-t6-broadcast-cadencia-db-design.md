# Wartime lote final: pre-flight de template (T3), auto-resume de billing (T4), alarme de cadência morta (T5), retry uniforme de DB (T6)

**Data:** 2026-07-10 · **Branch:** `fix/wartime-t3-t6` · **Depende de:** infraestrutura de
alertas do T2 (`create_system_alert` critical → Sentry + WhatsApp admin), já em produção.

## Contexto pós-merge (10/07 noite)

O merge remoto de hoje alterou o terreno: (a) `app/db/supabase.py` já tem `run_with_retry`
(transporte, 3 tentativas) e `db_call` (to_thread), aplicados em processor/meta_router/
meta_audit — o T6 vira **extensão de cobertura**, não criação; (b) o reopen do follow-up
acabou de ganhar template novo (`utilidade_geral_confirmacao_v1`, en_US) com gate de
categoria e params determinísticos (spec `2026-07-10-reopen-template-coerencia-design.md`)
— o T3 **não toca o reopen** para não colidir com esse trabalho ativo; o validador fica
exposto para adoção futura.

## T3 — Pre-flight de template no broadcast

### Problema
`POST /broadcasts/{id}/start` (`broadcast/router.py:195`) valida billing e pendências,
mas **zero validação de template**: nome inexistente, locale divergente do aprovado
(`template_language_code` default pt_BR vs aprovação en_US → 404/#132001) e contagem de
params errada (#132000) só explodem NO MEIO da campanha, lead a lead — classe dos
incidentes reativacao_* (5 params vs 1) e automacao_valeria_to_joao (pt_BR → 404).

### Design
Novo módulo `app/templates/preflight.py`:

```
validate_template_for_broadcast(template_name, template_language_code,
                                template_variables, channel) -> list[str]
```
Retorna lista de erros legíveis em PT-BR (vazia = aprovado). Checagens, nesta ordem:
1. **Existência/aprovação:** template em `message_templates` com `status='approved'`
   (lookup local; fallback Meta API com auto-sync, reutilizando o padrão de
   `_render_template_body` em `broadcast/worker.py:178`). Ausente → erro.
2. **Locale:** `template_language_code` do broadcast == `language` da aprovação.
   Divergente → erro citando os dois valores (armadilha conhecida de locale).
3. **Params do BODY:** extrai placeholders do texto aprovado (`{{1}}..{{n}}` posicional
   OU `{{nome}}` nomeado) e compara com `template_variables` (excluindo chaves `__*`):
   contagem exata p/ posicional, conjunto exato de nomes p/ nomeado, e coerência do
   `__params_type__` com o formato dos placeholders.
4. **Header:** template com header de mídia exige `__header_url__`; header TEXT com
   placeholder → erro (não suportado pelo builder atual); header fornecido sem header
   no template → erro.

**Fail-closed com escape hatch:** se o template não puder ser verificado (DB e Meta API
fora), o start é BLOQUEADO com erro explicando — disparo em massa às cegas é exatamente
o incidente que queremos matar. `PREFLIGHT_TEMPLATE=off` (env) desliga o gate inteiro
sem deploy (kill-switch padrão do repo).

Integração:
- `/start`: erros → `HTTPException(400, "Disparo bloqueado pelo pre-flight: …")`,
  status do broadcast intocado. Mensagem lista TODOS os erros (não só o primeiro).
- **Send-side (defesa em profundidade,** `broadcast/worker.py`**):** erro Meta da classe
  template (códigos 132000/132001/132005/132007/132012, e 404 de template) →
  `mark_broadcast_lead_failed` SEM requeue; contador de erros de template consecutivos
  por broadcast (in-memory do loop de lotes); ao atingir 3 → pausa o broadcast
  (`status='paused'`) + `create_system_alert("broadcast_template_error", …,
  severity="critical")` — chega no WhatsApp/Sentry via T2. Mata a classe "queimar a
  lista inteira com template quebrado" e o loop infinito de retry.

## T4 — Auto-resume de broadcast pausado por billing

### Problema
`pause_broadcast_for_billing` (`broadcast/service.py:29`) pausa; **não existe resume**.
O health check horário (`follow_up/scheduler.py:187`) já auto-resolve o alerta de
billing quando a Meta volta a responder OK — mas os broadcasts ficam pausados até
alguém lembrar. Janela de disparo perdida + toil.

### Design
- **Marcador sem migração** (wartime: código deploya sozinho, migração é manual — não
  criar acoplamento): ao pausar por billing, grava chave Redis
  `billing:paused_broadcast:{id}` (TTL 7 dias, best-effort). Redis fora no momento do
  pause → marcador perdido → resume manual (status quo, sem regressão).
- **Resume:** no ramo do health check que auto-resolve os alertas de billing
  (`follow_up/scheduler.py:276-297`), varrer `billing:paused_broadcast:*`; para cada id
  com `broadcasts.status == 'paused'` → `status='running'` + `emit_event("broadcasts")`
  (wake-up do worker) + DEL da chave + `create_system_alert("broadcast_auto_resumed",
  …, severity="warning")` (visibilidade: o operador sabe que voltou sozinho).
  Broadcast não-paused (operador mexeu) → só DEL da chave (a decisão humana vence).
- Nova função `resume_broadcasts_after_billing()` em `broadcast/service.py`; o hook no
  scheduler é 1 chamada fail-soft (não pode quebrar o health check).

## T5 — Alarme de cadência morta (watchdog)

### Problema
A cadência 4-touch ficou morta por 13 dias (26/06→09/07: constraint 23514 engolia o
INSERT como warning — os jobs **nunca eram criados**, então o check de "stuck" de 2h,
que olha jobs existentes, nunca dispara). O QA diário reporta `followups_enviados`
agregado (`watchdog/service.py:645`) — informativo, sem alarme.

### Design
Novo check no watchdog (`watchdog/service.py`), padrão dos existentes:
- `check_cadence_dead(now)`: dispara `create_system_alert("cadence_dead", …,
  severity="critical")` quando, na janela das últimas 24h, **(a)** a operação está viva
  (existem mensagens `assistant` novas — a Valéria conversou) **e (b)** ZERO linhas
  foram criadas em `follow_up_jobs`. A combinação separa "cadência morta" de "dia sem
  tráfego". Dedup 1/24h (padrão dos alertas). Roda no ciclo normal do watchdog, mas só
  avalia entre 08h-20h BRT (evita falso positivo de madrugada).
- **Histograma por `job_type` no QA diário:** `_qa_collect_metrics` ganha breakdown de
  jobs criados e executados nas 24h por tipo (cadência, handoff_rescue, lp_welcome,
  ai_scheduled_return, nudge…), anexado à mensagem do QA. -1 = indisponível (padrão).
- Severity critical → chega no WhatsApp/Sentry via T2 sem trabalho extra.

## T6 — Retry uniforme de Supabase (extensão de cobertura)

### Problema
`run_with_retry`/`db_call` existem e cobrem processor/meta_router/meta_audit, mas os
hot paths de ESCRITA fora deles seguem a 1 tentativa: um GOAWAY durante rajada de
disparo perde um `save_message`/`update_lead`/mark de broadcast silenciosamente.

### Design (mecânico, sem mudança de contrato)
- `conversations/service.py`: `save_message` e `update_conversation` — corpo envolvido
  em `run_with_retry(lambda: …, label=…)`.
- `leads/service.py`: `update_lead` — idem.
- `broadcast/service.py`: `mark_broadcast_lead_sent/failed/delivered`,
  `increment_broadcast_*`, `requeue_broadcast_lead`, `save_broadcast_lead_wamid` — idem
  (executado pelo subagente do domínio broadcast p/ evitar conflito de arquivo).
- Regra: retry SÓ em `httpx.TransportError` (contrato do helper — 4xx/5xx de aplicação
  nunca são mascarados); a função refaz o request inteiro por tentativa. Sem retry em
  leituras (falha de leitura já tem fallbacks locais nos callers).

## Fora de escopo
Reopen do follow-up (trabalho remoto ativo — validador exposto, adoção futura);
migrações de schema; CRM/Next.js; scripts one-off.

## Critérios de aceite
1. Start de broadcast com template inexistente / locale errado / params errados / header
   incoerente → 400 com TODOS os erros legíveis; status intocado; `PREFLIGHT_TEMPLATE=off`
   pula o gate.
2. Send com erro 132000/132001 → lead failed sem requeue; 3 consecutivos → broadcast
   pausado + alerta critical. Nunca loop infinito.
3. Billing normalizado → broadcasts pausados por billing (e SÓ eles) voltam a `running`
   com wake-up + alerta warning; broadcast mexido pelo operador não é ressuscitado.
4. 24h com conversas assistant e zero `follow_up_jobs` criados → alerta `cadence_dead`
   critical (dedup 24h); dia sem tráfego → silêncio; QA diário mostra breakdown por
   job_type.
5. Hot writes listados sobrevivem a `httpx.RemoteProtocolError` transitório (retry) e
   NÃO retentam em erro HTTP de aplicação.
6. Suíte existente de broadcast/followup/watchdog/conversations passa sem regressão.
