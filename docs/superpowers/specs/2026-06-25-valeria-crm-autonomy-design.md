# Autonomia total da Valéria no CRM — reflexos de sistema + tools de pipeline + cadência

Data: 2026-06-25
Status: aprovado para implementação

## Problema (causa-raiz)

Auditoria: o funil **"Valeria - Importação Leads Frios"** (`a9487d77-ae93-42fe-89b8-9747d5e9cdf4`)
acumula cards na etapa **"Disparo feito"** mesmo com leads respondendo/descartando.
Estado em prod (25/06/2026): 428 em *Frio*, **133 abertos em *Disparo feito***, 43 em
*Respondeu*, 30 em *Qualificado*, 14 abertos em *Encerrado*.

Causas concretas:

1. **Não existe reflexo de "Respondeu".** O broadcast move o card para *Disparo feito* no
   disparo (`move_to_stage_id`), mas nada o move quando o lead responde.
2. **Stages custom sem `key`.** `Frio / Disparo feito / Respondeu / Encerrado / Qualificado`
   têm `key=null` — só dá pra resolver por label (frágil a renome).
3. **Ordem ilógica.** *Qualificado* (ord 4) está depois de *Encerrado* (ord 3).
4. **`registrar_sem_interesse_atual` não fecha o card frio.** `_perdido_stage_id` só busca
   keys `perdido`/`fechado_perdido`, que **não existem** no funil frio → o card é marcado
   `closed_at` mas fica visualmente preso em *Disparo feito*.

## Objetivo

Dar 100% de autonomia à Valéria sobre o funil dela e a Blacklist, mantendo o CRM organizado
em tempo real **sem intervenção humana**, dividindo responsabilidades entre **reflexos de
sistema** (sem tokens) e **tools de IA** (decisão de negócio).

## Design

### Parte 0 — Padronização do schema (migration)

Migration `20260625_valeria_coldfunnel_stage_keys` (aplicada no prod via MCP + arquivo
committed em `backend/migrations/`):

- Adiciona keys estáveis no pipeline frio: `frio`, `disparo_feito`, `respondeu`,
  `qualificado`, `encerrado` (UPDATE por `pipeline_id` + `label`, casando o prod atual).
- Corrige a ordem: `qualificado` → ord 3, `encerrado` → ord 4.
- Idempotente: `UPDATE ... WHERE key IS NULL` / por label; reexecutável sem efeito colateral.
- O índice único `(pipeline_id, key) WHERE key IS NOT NULL` já existe; as keys são únicas
  dentro do pipeline.

### Parte 1 — Reflexo de Sistema: "Disparo feito" → "Respondeu" (sem LLM)

`leads/service.py`:

- `cold_funnel_stage_id(sb, pipeline_id, key, label_fallback) -> str | None`
  Resolve um stage por `key` (autoritativo) com fallback por `label` ILIKE.
- `advance_cold_deal_on_reply(lead_id) -> bool`
  Pega o deal aberto do lead; **se** o `stage_id` atual é o `disparo_feito` do pipeline dele
  **e** existe um sibling `respondeu`, faz UPDATE `stage_id`→respondeu (`stage='respondeu'`,
  `updated_at`). Idempotente: só avança quem está EXATAMENTE em *Disparo feito* — nunca
  regride *Respondeu/Qualificado/Encerrado* (decisão do usuário). Fail-soft (nunca levanta).
  Auto-escopado: só o funil frio tem o par disparo_feito/respondeu → não afeta outros funis.

`buffer/processor.py`:

- Chamada de `advance_cold_deal_on_reply(lead["id"])` logo após salvar o inbound do lead
  (perto de `record_broadcast_reply`), **antes** do gate de IA, em try/except fail-soft.
  Roda mesmo com `ai_enabled=false` (no-op se o card já saiu do funil frio). Zero tokens.

### Parte 2 — Autonomia de pipeline nas tools

`leads/service.py`:

- `move_deal_to_stage_key(lead_id, key, label_fallback) -> bool`
  Move o deal aberto para o stage `key` **dentro do pipeline atual do card** (não troca de
  pipeline). No-op se o pipeline não tiver aquele stage. Fail-soft.
- `_perdido_stage_id` passa a reconhecer também `encerrado` (e label "Encerrado") como
  destino de fechamento — corrige o card frio que ficava preso.

`agent/tools.py`:

- `marcar_interesse` → além de setar o flag de follow-up, chama
  `move_deal_to_stage_key(lead_id, "qualificado", "Qualificado")` (interesse real =
  qualificado). Mantém todo o comportamento de follow-up existente.
- `registrar_sem_interesse_atual` → inalterado no código da tool; passa a fechar o card frio
  em *Encerrado* por consequência do `_perdido_stage_id` estendido.
- `registrar_optout` → Blacklist (inalterado).
- `encaminhar_humano` → pipeline do vendedor (inalterado; é o handoff/fechamento forte).

Mapa de autonomia resultante:

| Sinal do lead | Tool/reflexo | Destino do card |
|---|---|---|
| Responde ao disparo | reflexo (sem LLM) | Disparo feito → Respondeu |
| Interesse comercial real | `marcar_interesse` | → Qualificado |
| Handoff / pronto p/ fechar | `encaminhar_humano` | → pipeline do vendedor |
| Sem interesse definitivo (soft) | `registrar_sem_interesse_atual` | → Encerrado |
| Opt-out explícito (hard) | `registrar_optout` | → Blacklist |

### Parte 3 — Cadência autônoma: `agendar_retorno`

`agent/tools.py` — nova tool, schema tipado e claro (gemini-prompting-strategies):

- `data_hora` (string, obrigatório): ISO 8601 com timezone, ex.
  `2026-06-27T14:00:00-03:00`. Se vier naïve, assume America/Sao_Paulo.
- `motivo` (string, obrigatório): por que/quando o lead pediu (ex. "lead disse que fala
  sexta").
- `contexto` (string, opcional): contexto extra p/ a Valéria usar na volta.

Executor `agendar_retorno`:

1. Parseia `data_hora` (falha → retorna string de erro instruindo o modelo a corrigir).
2. Rejeita datas no passado; teto de horizonte 30 dias.
3. Clampa na janela comercial (`_clamp_to_business_window`).
4. Insere `follow_up_jobs` com `job_type='ai_scheduled_return'`, `sequence=1`, `fire_at`,
   `conversation_id`, `lead_id`, `channel_id` (via `get_channel_for_lead`), `env_tag`,
   `metadata={motivo, contexto, lead_name, scheduled_by:'agendar_retorno'}`.
5. **Não** desativa a IA. Retorna confirmação com o horário local p/ a Valéria se despedir
   naturalmente.

`follow_up/scheduler.py` — `_process_ai_scheduled_return(job, now)`, roteado em
`process_due_followups` por `job_type=='ai_scheduled_return'`:

- Re-lê o lead; guards: canal humano → cancela; `ai_enabled=false` → cancela.
- **Janela 24h ABERTA** → roda a Valéria (`run_agent`, persona outbound
  `AI_REENGAGE_PROFILE_ID`) sobre um prompt sintético montado do `motivo/contexto`, envia
  as bolhas (mesmo padrão de `_process_ai_reengage`).
- **Janela 24h FECHADA** → se `metadata` tiver `template_name`/`language_code` configurados,
  dispara o template aprovado p/ reabrir a janela (seam data-configurável); senão cancela
  com `window_expired_no_template` (logado). *Constraint conhecida:* retornos multi-dia
  exigem template aprovado configurado; retornos dentro de 24h são 100% AI free-text.

`follow_up/service.py`:

- `schedule_ai_return(conversation_id, lead_id, channel_id, fire_at, metadata) -> datetime`
  Insere o job (reuso do padrão de `schedule_handoff_rescue`).

### Parte 4 — Testes (TDD)

`backend/tests/`:

- `test_cold_funnel_reflex_2026_06_25.py`: avança só de Disparo feito; idempotência; no-op
  fora do funil frio; fail-soft.
- `test_pipeline_autonomy_tools_2026_06_25.py`: `marcar_interesse`→qualificado;
  `_perdido_stage_id` reconhece encerrado.
- `test_agendar_retorno_2026_06_25.py`: parse/clamp/validação; insere job correto; handler
  janela aberta (AI) vs fechada (template/cancel).

Rodar `cd backend && python -m pytest -q` — suíte verde.

## Invariantes preservadas

- Assinaturas e gatilhos das tools existentes (canon.md) inalterados, exceto o **acréscimo**
  do movimento de card em `marcar_interesse` e a nova tool `agendar_retorno`.
- HARD opt-out (Blacklist) vs SOFT rejection (Encerrado) mantidos e reforçados.
- Paridade dev/prod: resolução por `key` com fallback por label → roda em homolog (sem as
  pipelines da Valéria) sem modificação.

## Fora de escopo (YAGNI)

- Renomear labels visíveis dos stages.
- Reorganizar os funis de produto (Atacado/Private Label/Consumo/Exportação).
- Tool dedicada separada p/ "Qualificado"/"Encerrado" (piggyback nas tools existentes é
  mais limpo p/ o Gemini — menos tools, gatilhos mais claros).
