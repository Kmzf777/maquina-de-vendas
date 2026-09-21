# Bloquear Lead — Implementation Plan

**Goal:** Um botão em `/conversas` que bloqueia o lead: card vai para o funil Blacklist, as mensagens dele param de chegar no CRM, e ele fica incapaz de receber qualquer disparo enquanto estiver bloqueado. Com desbloqueio.

**Architecture:** Não cria conceito novo. O bloqueio É o hard opt-out que já existe (`leads.opt_out` + funil Blacklist, critério de `is_lead_blacklisted`). O trabalho é (1) fechar o furo do caminho manual, que hoje não grava `opt_out`; (2) criar o gate INBOUND, que não existe; (3) fechar os furos de OUTBOUND — a maioria no frontend Next, que fala direto com a Graph API sem passar pelo FastAPI; (4) a UI.

**Tech Stack:** Python 3 / FastAPI / Supabase (PostgREST), Next.js App Router / React / TypeScript, pytest, vitest.

---

## Contexto que o executor precisa saber

**Migrations NÃO rodam no deploy.** O GitHub Actions sobe imagem Docker. `supabase/migrations/*.sql` é executado à mão no SQL editor. Escreva tudo `IF NOT EXISTS` / `OR REPLACE`, reexecutável sem dano.

**Testes usam `unittest.mock.patch` sobre o cliente Supabase**, nunca banco real. Regra de onde patchar:
- import no topo do módulo → `patch("app.<modulo_consumidor>.<nome>")`
- import lazy dentro da função → `patch("app.<modulo_origem>.<nome>")`

Modelo mais próximo do que você vai escrever: `backend/tests/test_blacklist_outbound_guard_2026_06_25.py` (helper `_sb_for_blacklist(opt_out, has_blacklist_deal)` com `sb.table.side_effect` distinguindo tabelas). Veja também `test_optout_blacklist.py` e `test_send_text_blacklist.py`.

**Comandos:**
- backend: `cd backend && python -m pytest -q -m "not integration"` (config em `backend/pytest.ini`, `asyncio_mode = auto`)
- frontend: `cd frontend && npm test` (vitest) e `npx tsc --noEmit`
- `npm run lint` **já falha na master** (`react-hooks/set-state-in-effect`). Não é regressão sua; não tente consertar.
- CI bloqueia deploy se o pytest ficar vermelho (`.github/workflows/deploy.yml:151`).

**Vocabulário que confunde:**
- `leads.stage` = **segmento** (`atacado`, `consumo`…). NÃO é coluna do Kanban.
- `deals.stage_id` → `pipeline_stages` = **coluna do Kanban**.
- "disparo" = qualquer envio ativo (broadcast, esteira, follow-up, template manual).

**Constantes:** `BLACKLIST_PIPELINE_ID = "8988e852-2836-4add-b023-4db4d6cd0e6e"`, `BLACKLIST_STAGE_ID = "fbace13d-d788-423a-879d-ee468dff29ed"` (`backend/app/leads/service.py:1544`).

---

## Decisões de produto (confirmadas pelo usuário em 18/09/2026)

1. **A conversa de um lead bloqueado SOME do `/conversas`** — `conversations.status = 'blocked'` + filtro na listagem + tratamento do realtime para a linha não voltar em memória. Histórico continua acessível pelo funil Blacklist e pela tela de leads.
2. **Envio manual do operador também é bloqueado** — composer travado na UI **e** guarda no servidor. Não basta travar a UI: as rotas Next falam direto com `graph.facebook.com`.
3. **Desbloqueio faz parte do escopo.** A prova LGPD do bloqueio NUNCA é apagada — o desbloqueio só acrescenta um registro de revogação.

---

## Fonte da verdade do bloqueio

`leads.opt_out = true` (canônico) **OU** deal no funil Blacklist (defesa em profundidade). É exatamente o critério de `is_lead_blacklisted` (`backend/app/leads/service.py:381`). **Não crie coluna nova.**

No **gate inbound** (caminho quente, roda em toda mensagem recebida) consulte **só `lead["opt_out"]`**, que `get_or_create_lead` já traz em memória via `select("*")` — custo zero. O braço "deal na Blacklist" custaria 1 query por mensagem e é dispensável porque a migration faz backfill de `opt_out=true` em todo lead que já tem card na Blacklist, e o `block_lead` novo sempre grava os dois.

---

## Estrutura de arquivos

**Criar:**
- `supabase/migrations/20260918_bloquear_lead.sql`
- `frontend/src/lib/supabase/lead-blocked.ts` — helper compartilhado das rotas Next
- `frontend/src/app/api/leads/[id]/block/route.ts`, `.../unblock/route.ts`
- `backend/tests/test_bloquear_lead_2026_09_18.py`
- `backend/tests/test_bloqueio_inbound_gate_2026_09_18.py`
- `backend/tests/test_bloqueio_disparo_guards_2026_09_18.py`
- `frontend/src/lib/supabase/lead-blocked.test.ts`

**Modificar:** `backend/app/leads/service.py`, `backend/app/leads/router.py`, `backend/app/buffer/processor.py`, `backend/app/broadcast/worker.py`, `backend/app/follow_up/scheduler.py`, `backend/app/campaigns/router.py`, `backend/app/automation/triggers.py`, `backend/app/automation/test_runner.py`, `backend/app/channels/router.py`, `backend/app/button_flow/runner.py`, `frontend/src/app/api/conversations/route.ts`, `frontend/src/app/api/conversations/[id]/{send,send-template,send-media,react}/route.ts`, `frontend/src/app/api/broadcasts/[id]/leads/route.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/supabase/conversation-enrichment.ts`, `frontend/src/app/(authenticated)/conversas/page.tsx`, `frontend/src/components/conversas/chat-header.tsx`, `frontend/src/components/conversas/chat-view.tsx`

---

## Ondas de execução

- **Onda 1** (arquivos disjuntos, paralelo): Task 1 (migration + service + router) ‖ Task 2 (gate inbound) ‖ Task 3 (guards de disparo backend)
- **Onda 2** (depende dos endpoints da Task 1): Task 4 (rotas Next) ‖ Task 5 (UI React)

---

## Task 1 — Migration + `block_lead`/`unblock_lead` + endpoints

**Files:** criar `supabase/migrations/20260918_bloquear_lead.sql`, `backend/tests/test_bloquear_lead_2026_09_18.py`; modificar `backend/app/leads/service.py`, `backend/app/leads/router.py`.

### 1.1 Migration
Idempotente. Três blocos:
1. **Backfill** `UPDATE leads l SET opt_out = true FROM deals d WHERE d.lead_id = l.id AND d.pipeline_id = '8988e852-…' AND l.opt_out = false;` — é o bloco que ficou comentado em `20260616_leads_opt_out.sql:18-25`. Sem ele o gate inbound (que só lê `opt_out`) deixaria passar os leads bloqueados antes desta entrega. **Não** preencha `opt_out_at/channel/evidence` no backfill: são leads sem prova conhecida, e forjar evidência é pior que a lacuna (mesmo princípio de `20260909_recuperacao_stages_optout.sql`).
2. **Índices:** `CREATE INDEX IF NOT EXISTS idx_leads_opt_out ON leads(id) WHERE opt_out;` e `CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);`
3. `NOTIFY pgrst, 'reload schema';`

Documente no cabeçalho que ela NÃO é aplicada pelo deploy.

### 1.2 `block_lead(lead_id, *, by=None, reason=None) -> dict` em `leads/service.py`
Coloque perto de `apply_optout_side_effects` (:1684). Comportamento:
- Lê o lead. Não existe → `ValueError`.
- **Idempotente:** já bloqueado (`opt_out` true) → devolve `{"blocked": True, "already": True}` sem efeitos.
- **Snapshot para o desbloqueio**, montado ANTES de mover qualquer coisa:
  `{"ai_enabled": <atual>, "deals": [{"id", "pipeline_id", "stage_id"}, …], "conversations": [{"id", "status"}, …]}`
- Grava com **degradação em duas tentativas**, copiando `button_flow/effects.py::_aplicar_optout` (:114-144): primeiro o completo (`ai_enabled=False, opt_out=True` + `opt_out_at`, `opt_out_channel="manual_crm"`, `opt_out_evidence`), e se o PostgREST devolver PGRST204 (colunas de evidência ausentes), regrava só `{"ai_enabled": False, "opt_out": True}`. Perder a evidência é problema de auditoria; perder o `opt_out` é continuar disparando para quem pediu para sair.
  - Monte a evidência com `app.button_flow.effects._campos_de_evidencia(evidencia, conversation_id=…, lead_id=…)` passando `canal="manual_crm"` (a função já prevê esse valor) **ou** escreva o equivalente inline se o import cruzado incomodar. Inclua o snapshot em `opt_out_evidence["restore"]` e `by`/`reason`.
- `apply_optout_side_effects(lead_id, lead.get("phone",""), reason="block_manual")` — Blacklist + cancela enrollments + cancela follow-ups.
- Marca as conversas: `conversations.status = 'blocked'` e `unread_count = 0` para todas as conversas do lead (senão a conversa continua somando badge de não lida).
- `save_message(lead_id, "system", "[bloqueio] …")` — fail-soft.
- Retorna `{"blocked": True, "already": False, "deals": n, "conversations": m}`.
- **Fail-soft em tudo que é efeito colateral; fail-hard só na gravação do `opt_out`.**

### 1.3 `unblock_lead(lead_id, *, by=None) -> dict`
- Lê o lead e o snapshot de `opt_out_evidence.restore`.
- `opt_out=False` e `ai_enabled` restaurado do snapshot (default `True` se não houver).
- **NUNCA apague `opt_out_at`, `opt_out_channel` nem a evidência original.** Acrescente `opt_out_evidence["revogado"] = {"em": <iso>, "por": by}` preservando o resto do jsonb.
- Restaura cada deal do snapshot (`pipeline_id`/`stage_id` de origem). Deals que estão na Blacklist e **não** têm origem no snapshot (lead bloqueado antes desta entrega) NÃO devem ser adivinhados: conte-os e devolva em `deals_pendentes`. Enquanto existirem, `is_lead_blacklisted` continua `True` e o lead segue efetivamente bloqueado — o comportamento seguro. A UI avisa o operador para mover o card no Kanban.
- Restaura `conversations.status` do snapshot (default `'active'`).
- `save_message(lead_id, "system", "[desbloqueio] …")`.
- Retorna `{"blocked": False, "deals_restaurados": n, "deals_pendentes": m}`.

### 1.4 Endpoints em `leads/router.py`
- `POST /api/leads/{lead_id}/block` → `block_lead`
- `POST /api/leads/{lead_id}/unblock` → `unblock_lead`
- `GET /api/leads/{lead_id}/blocked` → `{"blocked": is_lead_blacklisted(lead_id)}`
- **`POST /api/leads/{lead_id}/optout` passa a delegar para `block_lead`.** Hoje (`router.py:87-105`) ele só faz `ai_enabled=False` + side effects e **nunca grava `opt_out=True`** — o bloqueio manual depende só do fallback "tem deal na Blacklist" e evapora se alguém arrastar o card no Kanban. Manter a rota (há chamador em `chat-view.tsx:190` e possivelmente scripts) mas com o corpo correto.

### 1.5 Testes (`test_bloquear_lead_2026_09_18.py`)
- `block_lead` grava `opt_out=True` **e** `ai_enabled=False`.
- Degradação PGRST204: primeira gravação falha → regrava só o booleano; `opt_out` sobrevive.
- Idempotência: bloquear duas vezes não duplica efeitos e não sobrescreve o snapshot original.
- `block_lead` chama `apply_optout_side_effects` e zera `unread_count`.
- `unblock_lead` restaura `pipeline_id`/`stage_id` do snapshot e **preserva** `opt_out_at`/`opt_out_channel`/evidência original.
- `unblock_lead` sem snapshot devolve `deals_pendentes > 0` e NÃO inventa destino.
- `POST /optout` agora resulta em `opt_out=True` (regressão do furo).

---

## Task 2 — Gate inbound

**Files:** modificar `backend/app/buffer/processor.py`; criar `backend/tests/test_bloqueio_inbound_gate_2026_09_18.py`.

`process_buffered_messages` (`processor.py:1286`) é o **único estreitamento por onde passam todos os caminhos inbound**: `meta_router.py:620`, o legado `webhook/router.py:147`, `buffer/flusher.py:30` e `buffer/recovery.py:87`.

Insira o gate **dentro do `try` de setup, logo após `lead = get_or_create_lead(phone)` (linha 1292) e ANTES de `get_channel_by_id`/`get_or_create_conversation`**:

```python
        # BLOQUEIO: lead bloqueado não entra no CRM. Posição deliberada — ANTES de
        # get_or_create_conversation (1301), de save_message (1367), do unread_count++ (1483)
        # e de advance_deal_on_reply (1404), que moveria o card de volta para 'Respondeu'
        # e desfaria a ida para a Blacklist. Também evita _resolve_media (1323), o item
        # mais caro do turno. Só `opt_out` (já em memória, custo zero); o braço "deal na
        # Blacklist" fica fora do caminho quente — a migration 20260918 faz o backfill.
        if lead.get("opt_out"):
            logger.info("[BLOQUEADO] inbound descartado — lead %s (phone %s)", lead["id"], phone)
            return
```

**Consequência a documentar no código:** mensagens recebidas durante o bloqueio são descartadas em definitivo — não ficam em `messages` nem reaparecem no desbloqueio. É exatamente o comportamento pedido ("suas mensagens não chegam no CRM"), mas precisa estar escrito para ninguém tratar como bug depois.

**Não** coloque o gate em `meta_router.py` antes do parse: ali só existe o `from` cru, identificar o lead exigiria normalizar telefone e consultar o Supabase **dentro do request que precisa devolver 200 à Meta** — lentidão vira retry da Meta.

Testes: lead com `opt_out=True` → `get_or_create_conversation` e `save_message` não são chamados; lead normal → fluxo segue. Use `patch("app.buffer.processor.get_or_create_lead", …)`.

---

## Task 3 — Guards de disparo no backend

**Files:** modificar `backend/app/broadcast/worker.py`, `backend/app/follow_up/scheduler.py`, `backend/app/campaigns/router.py`, `backend/app/automation/triggers.py`, `backend/app/automation/test_runner.py`, `backend/app/channels/router.py`, `backend/app/button_flow/runner.py`; criar `backend/tests/test_bloqueio_disparo_guards_2026_09_18.py`.

Já estão cobertos (não mexa): broadcast loop principal (`worker.py:1694`), broadcast camada 1 (`router.py:130/170`), `campaigns/worker.py:55`, `automation/engine.py:448`.

Feche, **em ordem de gravidade**:

1. **`broadcast/worker.py:917`** — `_retry_single_undelivered` reenvia template horas/dias depois do disparo original (exatamente a janela em que o opt-out acontece) e não tem guard, no mesmo arquivo que tem o guard modelo 400 linhas acima. Reuse `_blacklist_guardrail(lead)` (definido em `:522`); o `lead` vem de `bl["leads"]` (`:873`). O claim atômico já rodou — marque e `return`.
2. **`follow_up/scheduler.py:839`** — `_lead_stop_reason` é o backstop único de 6 caminhos de envio, mas lê só `leads.opt_out` e `metadata.blacklisted_at`; **não** consulta deal na Blacklist. Some `is_lead_blacklisted(lead["id"])` → motivo `"blacklisted"`. Atenção a `_STOP_REASON_EXEMPT_JOB_TYPES` (`:874`): a isenção é só de `ai_disabled`, `blacklisted` já não é isento — confirme que continua assim.
3. **`follow_up/scheduler.py:171`** — `send_joao_handoff_template` envia fora do loop que tem o backstop (chamado por `agent/tools.py:1799`). Guard no topo, junto do `if not lead_phone`.
4. **`campaigns/router.py:240`** — `api_enroll_lead` não checa camada 1: o operador vê "matriculado com sucesso" e a esteira nunca envia (silêncio confuso). `raise HTTPException(409, "Lead bloqueado")` junto do `is_already_enrolled`.
5. **`automation/triggers.py:323`** — `_safe_enroll` é o ponto comum de todos os gatilhos que hoje não checam (só `deal_stage_stagnation` checa, em `:297`). Guard ali.
6. **`button_flow/runner.py:190`** — `_motivo_para_nao_rodar` devolve motivo `"blacklist"`. **Ponha o guard aqui e NÃO em `_enviar` (`:412`)**: `effects.py` grava `opt_out=true` no próprio clique de "Parar mensagens", e um guard ingênuo em `_enviar` engoliria a mensagem de confirmação do opt-out.
7. **`automation/test_runner.py:217/233`** e **`channels/router.py:80`** — superfícies menores, mas abertas. Em `channels/router.py` resolva o lead pelo `conversation_id` que já é consultado em `:87-96`.

Todos os guards: log em nível INFO/WARNING dizendo qual caminho foi barrado e para qual lead. Fail-open na *checagem* (erro de consulta não bloqueia o envio), espelhando `is_lead_blacklisted` — a proteção vem das camadas somadas, não de fail-closed.

Testes: um por guard, no estilo de `test_blacklist_outbound_guard_2026_06_25.py` — provar que o `send_*` **não** é chamado com lead bloqueado e **é** chamado com lead normal.

---

## Task 4 — Rotas Next (o furo maior)

**Files:** criar `frontend/src/lib/supabase/lead-blocked.ts` + `.test.ts`, `frontend/src/app/api/leads/[id]/block/route.ts`, `.../unblock/route.ts`; modificar `frontend/src/app/api/conversations/route.ts`, `.../conversations/[id]/{send,send-template,send-media,react}/route.ts`, `.../broadcasts/[id]/leads/route.ts`.

Estas rotas **não passam pelo FastAPI nem pelo `MetaCloudClient`** — montam o POST para `graph.facebook.com` com o token lido do Supabase. Nenhum guard de backend as cobre.

### 4.1 Helper `lead-blocked.ts`
```ts
export const BLACKLIST_PIPELINE_ID = "8988e852-2836-4add-b023-4db4d6cd0e6e";
/** true se o lead está bloqueado: leads.opt_out OU deal no funil Blacklist. */
export async function isLeadBlocked(supabase, leadId: string): Promise<boolean>
```
Mesmo critério de `is_lead_blacklisted`. **Fail-open** em erro de consulta (não trave envio por falha de checagem), com `console.warn`.

### 4.2 Guards, por gravidade
1. **`send-template/route.ts:46`** — disparo ATIVO fora da janela de 24h para quem pediu para sair. É o que mais se parece com o que provoca banimento na Meta. Guard antes de `sendTemplateViaMeta`. `conv.leads` já é selecionado em `:20`.
2. **`broadcasts/[id]/leads/route.ts:31`** — o CRM insere direto em `broadcast_leads` com service-role e **contorna a camada 1 inteira** do broadcast (`quick-send-modal`, `create-broadcast-modal`, `broadcast-detail` usam esta rota, nenhuma chama o FastAPI). Filtre os bloqueados antes do INSERT e devolva `skipped_blacklist: n`, espelhando o contrato do backend.
3. **`send/route.ts:105`** e **`send-media/route.ts:192`** — envio manual. Bloquear (decisão 2). Devolva **403** com `{"error": "Lead bloqueado — desbloqueie para voltar a conversar."}`.
4. **`react/route.ts:70`** — mesma coisa, prioridade baixa.

Amplie os `select` existentes para trazer `leads(id, phone, opt_out)` em vez de fazer query nova onde der.

### 4.3 Listagem some
`api/conversations/route.ts:157-161`: acrescente `.neq("status", "blocked")` à query. Não mexa no merge de chats da Evolution (`:182-236`).

### 4.4 Proxies `block`/`unblock`
Espelhe `frontend/src/app/api/leads/[id]/optout/route.ts` (mesmo tratamento de `FASTAPI_URL` e de erro 502).

---

## Task 5 — UI React

**Files:** modificar `frontend/src/lib/types.ts`, `frontend/src/lib/supabase/conversation-enrichment.ts`, `frontend/src/app/(authenticated)/conversas/page.tsx`, `frontend/src/components/conversas/chat-header.tsx`, `frontend/src/components/conversas/chat-view.tsx`.

### 5.1 Dado
- `Lead` (`types.ts:1`): acrescente `opt_out?: boolean`.
- `conversationSelect()` (`conversation-enrichment.ts:5-6`): inclua `opt_out` nos campos do lead. Sem isso a UI não sabe que o lead está bloqueado.

### 5.2 Realtime (`conversas/page.tsx:243-270`)
O patch de UPDATE hoje não olha `status`: sem tratamento, a conversa recém-bloqueada continuaria na lista em memória até um refetch. **No UPDATE, se `status === 'blocked'`, remova a linha da lista — o mesmo tratamento já dado ao DELETE.** Se a conversa removida era a selecionada, limpe a seleção.

### 5.3 Ação
- `chat-header.tsx`: o item "Parar mensagens" (`:199-224`) vira **"Bloquear lead"**, e quando o lead já está bloqueado vira **"Desbloquear lead"**. Props novas: `blocked: boolean`, `onUnblock`. Mantenha o padrão visual do menu (ícone vermelho + `hover:bg-red-50`).
- `chat-view.tsx`: `handleBlock` substitui `handleOptOut` (`:178-201`) chamando `POST /api/leads/{id}/block`; `handleUnblock` chama `/unblock`. Confirmação enumerando os efeitos:
  > Bloquear este lead?
  > • Os cards vão para o funil Blacklist
  > • As mensagens dele param de chegar no CRM (as recebidas durante o bloqueio são descartadas)
  > • Ele não recebe mais nenhum disparo
  > • A Valéria é desativada e os follow-ups são cancelados
  >
  > Reversível pelo botão "Desbloquear lead".
- No retorno do `/unblock`, se `deals_pendentes > 0`, avise que N card(s) continuam na Blacklist e precisam ser movidos no Kanban.

### 5.4 Composer travado
Em `chat-view.tsx`, quando `lead?.opt_out` for true, substitua a área de input pela faixa:
> 🚫 Lead bloqueado — envio desabilitado. Desbloqueie para voltar a conversar.

Reaproveite o mecanismo de `isInputBlocked` que já existe (`handleSend` já consulta em `:203`). Trave também o botão de template e o de mídia.

### 5.5 Testes vitest
Cubra o helper `isLeadBlocked` e a regra do realtime (UPDATE com `status='blocked'` remove a linha). `frontend/src/lib/contact-search.test.ts` é o modelo de estilo.

---

## Verificação final

1. `cd backend && python -m pytest -q -m "not integration"` — verde.
2. `cd frontend && npm test` e `npx tsc --noEmit` — verdes.
3. Revisar que nenhum `console.log`/`print` de depuração ficou.
4. Migration revisada à mão (não há harness de SQL) e **aplicada no Supabase antes do push**, senão o backfill não existe e leads legados bloqueados continuam entrando no CRM.
