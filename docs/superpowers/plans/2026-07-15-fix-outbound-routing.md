# Plano — Correções de Roteamento Outbound (15/07/2026)

Spec: `docs/superpowers/specs/2026-07-15-fix-outbound-routing.md`
Branch: `fix/outbound-routing-1507` → destino `master` (deploy prod no push).

## Trilha A — Prompts + tool (sem I/O novo além do alerta)

### A1. `backend/app/agent/prompts/valeria_outbound/playbook.py`
- Adicionar **LEI 5 — PEDIDO DIRETO SE ATENDE PRIMEIRO** no bloco `POSTURA_HUNTER` (antes da LEI 4 anti-carimbo).
- Reforçar **LEI 1** com exemplos banidos literais de premissa inventada (`"você já compra da gente, né?"`) e a alternativa neutra.

### A2. `backend/app/agent/prompts/base.py`
- Depois do bloco "FRUSTRACAO / DESISTENCIA / RECLAMACAO DE ROBO", adicionar bloco **RECLAMACAO SOBRE ATENDIMENTO HUMANO / PEDIDO NAO ENTREGUE** → `escalar_reclamacao(motivo=…)`. Distinguir de reclamação de robô (que segue `encaminhar_humano`).

### A3. `backend/app/agent/tools.py`
- Novo handler `async def _t_escalar_reclamacao(ctx)`:
  1. `create_system_alert(type="lead_complaint_escalation", severity="critical", title, message, metadata)` — fail-soft.
  2. `append_lead_observation(lead_id, "⚠️ [ESCALONAMENTO] …")`.
  3. cascata `await ctx.invoke("encaminhar_humano", {"vendedor":"Joao Bras","motivo":"ESCALONAMENTO — reclamação sobre atendimento (revisar com prioridade)","mensagem_despedida": <despedida empática do arg ou default>})`.
  4. retorna string de resultado.
- Registrar `Tool(name="escalar_reclamacao", stages=_STAGES_TODOS, effects=ToolEffects(disables_ai=True, may_cascade_to=("encaminhar_humano",)), handler=_t_escalar_reclamacao)` com schema `{motivo, mensagem_despedida}`.

## Trilha B — Ponte escudo seguro

### B1. `backend/app/buffer/processor.py`
- Novo `_BRIDGE_COMPLAINT_TOKENS` + `_looks_like_complaint(text)` (função pura, mesma normalização das outras).
- Novos textos: `_BRIDGE_ACK_TEXT` (aviso de recebimento) e `_BRIDGE_ESCALATION_TEXT` (aviso de escalonamento).
- Novos cooldowns: `_BRIDGE_ACK_COOLDOWN_SECONDS = 3600`, `_BRIDGE_ESCALATION_COOLDOWN_SECONDS = 12*3600`.
- Reescrever a escada de decisão em `_maybe_send_handoff_bridge`, após o social-closing:
  1. `_looks_like_complaint` → escalonar (alerta crítico, cooldown 12h) + `_BRIDGE_ESCALATION_TEXT` + marcador. Return True.
  2. `_looks_like_business_question` → `_BRIDGE_ACK_TEXT` (cooldown ack 1h) + marcador. Return True.
  3. vácuo puro → carimbo `_BRIDGE_TEXT` (comportamento atual).
- Tudo fail-soft; alerta best-effort (nunca escala).

## Trilha de Testes

- `backend/tests/test_bridge_business_question_2026_07_11.py` — **reescrever** para o novo contrato (ack em vez de silêncio); manter os testes puros de `_looks_like_business_question`.
- `backend/tests/test_bridge_escalation_complaint_2026_07_15.py` — **novo**: `_looks_like_complaint` (puro) + ponte escalona reclamação (alerta disparado, texto de escalonamento, cooldown).
- `backend/tests/test_escalar_reclamacao_2026_07_15.py` — **novo**: tool dispara alerta + cascata para encaminhar_humano.
- `backend/tests/test_outbound_pedido_direto_2026_07_15.py` — **novo**: aderência LEI 5 presente em todos os estágios outbound + LEI 1 reforçada.

## Validação
- `pytest` completo no backend. Alvo: verde total. Foco em não quebrar aderência outbound e a suíte de ponte/handoff.

## Deploy
- Estando verde: `git add` + commit; `git pull origin master`; `git push origin fix/outbound-routing-1507:master`.

## Ordem de execução
A3 (tool) → A1/A2 (prompts) → B1 (ponte) → testes → pytest → deploy.
