# Frente B — Ponte pós-handoff, SLA humano/janela do rescue e follow-up D+1

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development para implementar task a task. Steps usam checkbox (`- [ ]`).

**Goal:** Fechar os três vazamentos de experiência da janela 01–02/07: (B1) lead pós-handoff que continua escrevendo no número da Valéria cai no vácuo (16 das 20 mensagens sem resposta eram pós-handoff; Maycon mandou áudio reclamando; Juliana escreveu 4× "vocês não respondem?"); (B2) João sem alerta quando não responde (Juliana: "o João visualiza e não responde" por 1h46; Edgar: 4 mensagens sem resposta até o fim da janela) e rescue de handoff pós-16h indo para o dia seguinte (Edgar 17:22 → 09:00; Davi 15:47 → 09:00); (B3) lead que recebe preço e some não recebe nenhum follow-up (Samuel/Angelo/Welita — zero jobs `standard` criados na janela; o gatilho atual depende do LLM chamar `marcar_interesse`, que não disparou nenhuma vez).

**Architecture:** B1 = função nova `_maybe_send_handoff_bridge` chamada dentro do gate `ai_enabled=false` do `processor.py` (mensagem ESTÁTICA, sem LLM — handoff encerra a conversa automática por contrato; a ponte é sinalização de roteamento); rate-limit via Redis (`_get_buffer_redis()` já existe no processor). B2 = Check 5 no `watchdog/service.py` (colunas `conversations.last_customer_message_at`/`last_seller_response_at` já existem e são mantidas pelo fluxo atual) + janela própria do rescue em `follow_up/service.py` (constante 20h em vez do clamp comercial de 16h) + tiebreaker `.order("id")` na paginação (Minor P3 da review anterior, mesmo arquivo). B3 = flag `_quote_executed` em `tools.py` (espelho de `_interest_marked`) + gatilho determinístico no bloco de agendamento do `processor.py`. Nenhuma migração de banco.

**Tech Stack:** Python 3.11, pytest (asyncio_mode=auto), Redis, supabase-py.

## Global Constraints

- Testes de `backend/` com `python -m pytest ...`; suíte ampla com `-m "not integration"`. Baseline: o número verde vigente no início da execução (~1402, confirmar). Nenhum teste existente pode quebrar.
- **Ponte NUNCA usa LLM** e NUNCA roda quando: `opt_out=true`, `stage='perdido'`, `human_control` falso/ausente, REHEARSAL_MODE, ou erro/indisponibilidade de Redis (fail-CLOSED para envio: na dúvida, silêncio — spam é pior que vácuo aqui, o watchdog Check 2 cobre o órfão).
- Textos ao lead na voz da Valéria (base.py): minúsculas, sem ponto final ".", máx 2 bolhas `\n\n`, sem emoji, sem prometer prazo/ação futura, sem pedir repetição.
- Fail-soft em tudo: nenhuma falha de ponte/SLA/gatilho pode quebrar o fluxo do processor ou do watchdog.
- `retomar_contato_vendedor` e a cadência `standard` CONTINUAM na janela comercial 09h–16h (o texto da tool promete isso ao lead). SÓ o `handoff_rescue` ganha janela própria até 20h.
- B3 não cria mecanismo novo de cadência: reusa `_schedule_followup` (idempotente, cap same-day, cancelamentos em handoff/descarte já existentes). O gatilho `interest` existente continua funcionando; o novo sinal apenas soma (`should_schedule |= price_signal`) — nunca duplicar a chamada de agendamento.
- Alertas via `create_system_alert`; dedup do Check 5 é POR CONVERSA (2h), não global — implementação: buscar alertas `handoff_sla_breach` com `created_at > now-2h` (resolved qualquer), coletar `conversation_ids` dos metadata e excluir do novo alerta; se após exclusão não sobrar conversa, não alertar.
- Comentários/logs pt-BR citando os casos reais (Juliana/Edgar/Davi/Samuel).

---

## Task 1 (B1): Mensagem-ponte pós-handoff no canal da Valéria

**Files:**
- Modify: `backend/app/buffer/processor.py`
- Test: `backend/tests/test_processor_handoff_bridge_2026_07_03.py`

**Design:**

1. Constantes no processor:

```python
# Ponte pós-handoff (Frente B — casos Maycon/Juliana 01-02/07): depois do handoff a IA
# fica muda no canal da Valéria e o lead que continua escrevendo aqui cai no vácuo.
# A ponte é uma sinalização ESTÁTICA de roteamento (sem LLM — handoff encerra a conversa
# automática por contrato), com cooldown pra nunca virar spam.
_BRIDGE_COOLDOWN_SECONDS = 4 * 3600      # 1 ponte a cada 4h por conversa
_BRIDGE_CARD_COOLDOWN_SECONDS = 24 * 3600  # cartão do João no máx 1x/24h por conversa
_BRIDGE_TEXT = (
    "seu atendimento tá com o João agora\n\n"
    "se preferir, chama ele direto no contato que te mandei aqui em cima que ele te responde por lá"
)
```

2. `async def _maybe_send_handoff_bridge(lead, phone, conversation, channel, provider) -> bool` (retorna se enviou; SEMPRE fail-soft):
   - Condições (todas): `lead.get("human_control") is True`; `not lead.get("opt_out")`; `lead.get("stage") != "perdido"`; `os.environ.get("REHEARSAL_MODE") != "true"`.
   - Cooldown: `SET bridge:{conversation_id} 1 NX EX _BRIDGE_COOLDOWN_SECONDS` via `_get_buffer_redis()`; se a chave já existia OU Redis falhar → NÃO envia (fail-closed, logado em debug).
   - Envio: `send_to = resolve_send_target(lead, phone)`; `provider.send_text(send_to, _BRIDGE_TEXT)`; persistir com `save_message(conversation_id, lead_id, "assistant", _BRIDGE_TEXT, conversation.get("stage"), sent_by="bridge", wamid=extract_wamid(...))`.
   - Cartão: `SET bridge_card:{conversation_id} 1 NX EX _BRIDGE_CARD_COOLDOWN_SECONDS`; se adquiriu → `provider.send_contact(send_to, contact_name="João - Café Canastra", contact_phone="553491461669")` + system message `"[ponte] cartão de contato de João - Café Canastra reenviado"` (constantes do supervisor: importar/reusar as de `app.agent.tools` — `_SUPERVISOR_NAME`/`_SUPERVISOR_PHONE` — em vez de duplicar literais; se preferir não importar privados, promova-os a públicos em tools.py `SUPERVISOR_NAME/SUPERVISOR_PHONE` mantendo aliases).
   - Log `[BRIDGE]` com conversation_id e o que saiu (texto/cartão).
3. Ponto de inserção: dentro do gate existente `if not lead.get("ai_enabled", True):` (o gate de canal humano e o kill switch retornam ANTES — a ponte só existe no canal de IA). Chamar a ponte, depois manter `_update_last_msg` + `return` exatamente como hoje. O save da mensagem do usuário e o incremento de `unread_count` já aconteceram antes do gate (CRM continua vendo tudo).

- [ ] **Step 1: Testes que falham** — fakes no estilo dos testes de processor existentes (estudar `test_processor_llm_down_handoff_2026_07_01.py` + o FakeRedis de `test_buffer_recovery_hardening_2026_07_02.py`):
  1. **Caso Juliana:** lead `ai_enabled=false, human_control=true, opt_out=false, stage='atacado'`, canal ai → ponte enviada 1×, salva com `sent_by="bridge"`, cartão enviado (primeira vez) + system message; IA NÃO roda (`run_agent` não chamado).
  2. Segunda mensagem 5 min depois (chave de cooldown existente no FakeRedis) → NADA enviado; fluxo retorna normal.
  3. `stage='perdido'` (descartado) → nada; `opt_out=true` → nada; `human_control=false` (órfão Rafael) → nada (Check 2 do watchdog é quem cobre).
  4. Redis lançando → nada enviado, sem exceção propagada.
  5. REHEARSAL_MODE=true → nada.
  6. Cartão: com `bridge_card:` já setado e `bridge:` livre → só texto, sem cartão.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar e ver passar** + regressão `-k "processor or bridge"`.
- [ ] **Step 5: Commit** — `feat(processor): mensagem-ponte pos-handoff no canal da Valeria (Frente B1, casos Maycon/Juliana)`.

---

## Task 2 (B2): SLA de resposta humana pós-handoff + janela própria do rescue + tiebreaker

**Files:**
- Modify: `backend/app/watchdog/service.py`, `backend/app/follow_up/service.py`
- Test: `backend/tests/test_watchdog_handoff_sla_2026_07_03.py`, `backend/tests/test_handoff_rescue_window_2026_07_03.py`

**Design:**

1. **Check 5 — `check_handoff_sla(now) -> int`** no watchdog:
   - Constantes: `HANDOFF_SLA_MINUTES = 20`, `HANDOFF_SLA_LOOKBACK_HOURS = 24`, `HANDOFF_SLA_DEDUP_HOURS = 2`, janela útil `SLA_WINDOW_START = time(8,0)` / `SLA_WINDOW_END = time(20,0)` em `America/Sao_Paulo` (fora dela o check retorna 0 sem consultar o banco).
   - Query: `conversations.select("id, lead_id, last_customer_message_at, last_seller_response_at, channels!inner(mode), leads!inner(name)").eq("channels.mode", "human")` — filtrar em Python: `last_customer_message_at` não nulo, dentro do lookback, `now - last_customer_message_at > SLA` e (`last_seller_response_at` nulo OU `< last_customer_message_at`), timestamps SEMPRE via `_parse_ts`.
   - Dedup por conversa: buscar `system_alerts` `type='handoff_sla_breach'` com `created_at >= now-2h` (qualquer resolved), unir os `conversation_ids` dos metadata, excluir; se sobrar 0 → sem alerta.
   - Alerta: `create_system_alert("handoff_sla_breach", "Lead aguardando resposta humana pós-handoff", "<n> conversa(s) no canal humano com mensagem do lead sem resposta há mais de 20min (ex.: <primeiros nomes>). Casos reais: Juliana 02/07 ('o João visualiza e não responde').", severity="warning", metadata={"conversation_ids": [...]})`.
   - Registrar no loop `run_watchdog` como 4º check (mesmo padrão to_thread + try/except próprio).
2. **Janela própria do rescue** em `follow_up/service.py`: nova `_clamp_to_rescue_window(target)` com `_RESCUE_START = time(9,0)` / `_RESCUE_END = time(20,0)`, dias úteis (mesma lógica do clamp atual, trocando o fim); `schedule_handoff_rescue` passa a usá-la (docstring atualizada citando Edgar/Davi). `_clamp_to_business_window` continua intocada para todo o resto.
3. **Tiebreaker** (Minor P3 pendente): na paginação do passo 1 de `_find_unanswered_conversations`, `.order("created_at", desc=True).order("id", desc=True)` + atualizar o fake se necessário (aditivo).

- [ ] **Step 1: Testes que falham**:
  1. **Caso Juliana:** conversa canal humano, `last_customer_message_at = now-30min`, `last_seller_response_at = now-2h` → 1 violação + alerta warning com o id nos metadata.
  2. `last_seller_response_at > last_customer_message_at` (João respondeu) → 0. `last_customer_message_at = now-10min` (< SLA) → 0. Canal ai → 0.
  3. Fora da janela útil (mock de `now` às 23h locais) → 0 sem query (fake registra zero chamadas).
  4. Dedup por conversa: alerta recente com o mesmo conversation_id nos metadata → não re-alerta; conversa NOVA violada junto → alerta só com a nova.
  5. **Caso Edgar:** `schedule_handoff_rescue` com now=17:22 local → fire_at 17:37 MESMO dia; **caso Davi:** 15:47 → 16:02 mesmo dia (antes ia p/ 09h+1d); 19:50 → próximo dia útil 09h; sábado → segunda 09h; `retomar_contato_vendedor`/cadência standard continuam clampando em 16h (teste de não-regressão usando `_clamp_to_business_window`).
  6. Tiebreaker: fake captura `.order("id")` na paginação.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar e ver passar** + regressão `-k "watchdog or rescue or handoff"`.
- [ ] **Step 5: Commit** — `feat(watchdog+followup): SLA pos-handoff (check 5) + rescue ate 20h + tiebreaker paginacao (Frente B2, casos Juliana/Edgar/Davi)`.

---

## Task 3 (B3): Gatilho determinístico de follow-up quando o turno cotou preço

**Files:**
- Modify: `backend/app/agent/tools.py`, `backend/app/buffer/processor.py`
- Test: `backend/tests/test_processor_price_followup_2026_07_03.py`

**Design:**

1. **tools.py** — espelho de `_interest_marked`:

```python
# Sinal determinístico "este turno cotou preço" (Frente B3 — casos Samuel/Angelo 01-02/07:
# leads receberam preço, sumiram e NENHUM follow-up foi agendado porque o gatilho dependia
# do LLM chamar marcar_interesse). Setado quando calcular_orcamento resolve valores;
# consumido pelo processor no bloco de agendamento.
_quote_executed: dict[str, bool] = {}

def pop_quote_executed(conversation_id: str) -> bool: ...
```

   Setar `_quote_executed[conversation_id] = True` em `calcular_orcamento` nos DOIS retornos com valores (subtotal-sem-UF e orçamento completo), NUNCA nos retornos de erro/validação/desambiguação.
2. **processor.py** — no bloco de agendamento existente (`if conversation.get("followup_enabled", True) and channel and not handoff_aborted and not superseded:`):
   - Consumir `quote_flag = pop_quote_executed(conversation["id"])` JUNTO do `pop_interest_marked` existente (mesmo ponto, antes dos early-returns, para nunca vazar para o próximo turno — inclusive nos caminhos handoff/empty/recoalesce onde `pop_interest_marked` já é drenado: drenar a nova flag nos MESMOS pontos).
   - Sinal de preço: `price_signal = quote_flag or ("R$" in (response or ""))`.
   - Novo gatilho: `if not should_schedule and agent_persona == "valeria_inbound" and price_signal:` → re-checar `ai_enabled` fresco (mesmo guard do gatilho outbound) → `should_schedule = True; reason = "inbound cotou preço"`; `warm=True`.
   - `interest` continua com precedência (warm=bool(interest) preservado quando interest existir; para o gatilho novo, warm=True).
3. Comentário citando que a cadência já tem cap same-day/idempotência e é cancelada em handoff/descarte — nada disso muda.

- [ ] **Step 1: Testes que falham** (mocks estilo processor: `_schedule_followup` patchado, fila do agente fake):
  1. **Caso Samuel:** persona inbound, response com "R$26,70" → `_schedule_followup` chamado com warm=True; reason logada.
  2. `calcular_orcamento` executado no turno (flag) com response SEM "R$" (ex. só o breakdown na tool message) → agenda mesmo assim.
  3. Response sem preço nem flag (secretaria small talk) → NÃO agenda (a menos que interest — regressão do gatilho antigo com interest continua agendando).
  4. `ai_enabled` virou false no meio (re-check) → não agenda.
  5. Persona outbound com R$ → comportamento ATUAL preservado (outbound já agenda pelo gatilho engajou-e-esfriou — sem dupla chamada; assert de UMA chamada só).
  6. Flag drenada nos caminhos de early-return (handoff/empty/recoalesce) — não vaza para o turno seguinte.
- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar e ver passar** + regressão `-k "processor or followup or quote"` + suíte completa.
- [ ] **Step 5: Commit** — `feat(followup): gatilho deterministico pos-preco no inbound (Frente B3, casos Samuel/Angelo)`.
