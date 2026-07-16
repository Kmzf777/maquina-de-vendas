# Plano Mestre — Backlog UX / LLM / Contexto (8 itens)

> **Para workers agênticos:** SUB-SKILL OBRIGATÓRIA: usar `superpowers:subagent-driven-development` para executar tarefa-a-tarefa (subagente implementador + revisão de spec + revisão de qualidade). Passos usam checkbox (`- [ ]`).

**Goal:** Corrigir 7 bugs de UX/LLM/lógica de negócio e entregar 1 melhoria de UI (agregação de conversas), focados **exclusivamente na API oficial da Meta** (Evolution é ignorada).

**Arquitetura:** Backend FastAPI (`backend/app`), Supabase Postgres (produção `tshmvxxxyxgctrdkqvam`), Frontend Next.js (App Router, `frontend/src`). Pipeline: webhook Meta → buffer → orchestrator (Gemini) → humanizer → envio.

**Tech Stack:** Python 3.11/FastAPI, Supabase (PostgREST sync), Next.js/React/TS, Gemini via OpenAI-compat.

**Decisões aprovadas pelo usuário:**
- **2b:** gate de follow-up via nova tool `marcar_interesse` (determinístico).
- **Item 4:** correção apenas como **agregação na UI por lead** — backend de roteamento intacto.

**Restrições de produção:**
- Branch local atual: `fix/disparo-valeria-outbound-10h`. Trabalhar nela (ou nova branch a partir dela). **Sem push** sem autorização expressa.
- **Ignorar Evolution API totalmente.** Não tocar configurações de RLS.
- Working tree tem mudanças pré-existentes não relacionadas (frontend/docs) — não commitar junto.

---

## Mapa de Arquivos (o que cada tarefa toca)

| Camada | Arquivo | Responsabilidade nesta entrega |
|---|---|---|
| DB | `backend/migrations/` (novo .sql) | Índice em `messages.wamid`; (sem DDL de RLS) |
| Backend ctx | `backend/app/agent/orchestrator.py` | Injetar texto citado/reação no histórico; tratamento pós-tool de mídia |
| Backend ctx | `backend/app/conversations/service.py` | `get_history` retornar `wamid`, `quoted_wamid`, `message_type`, `metadata`; helper de resolução de citação |
| Backend tools | `backend/app/agent/tools.py` | Nova tool `marcar_interesse`; `registrar_optout` → mover deals p/ Blacklist; novo helper de blacklist |
| Backend tools | `backend/app/leads/service.py` (ou `deals`) | Helper `move_lead_deals_to_blacklist()` |
| Backend LLM | `backend/app/humanizer/splitter.py` | Dividir só por `\n\n` (parágrafo) + clamp a 3 bolhas |
| Backend LLM | `backend/app/agent/prompts/base.py` | Reforço bolhas; correção de nome; fechamento pós-mídia; quando chamar `marcar_interesse` |
| Backend LLM | `backend/app/buffer/processor.py` | Só agenda follow-up se interesse marcado |
| Backend LLM | `backend/app/follow_up/service.py` | (suporte ao gate de interesse, se necessário) |
| Frontend | `frontend/src/app/api/conversations/[id]/messages/route.ts` | Resolver citação/reação via fetch da original quando ausente no lote |
| Frontend | `frontend/src/components/conversas/message-bubble.tsx` | Mostrar alvo da reação; bloco de citação robusto |
| Frontend | `frontend/src/lib/types.ts` | Tipos para reação-alvo e citação resolvida |
| Frontend | Lista de conversas (`frontend/src/app/.../conversas`) | Agregar conversas por lead (item 4) |
| Frontend | (novo) botão "Parar mensagens" + endpoint | Aciona opt-out/blacklist manual |

---

## FASE 0 — Forense (Item 4) — CONCLUÍDA (read-only)

**Achado (documentado, sem ação de código no backend):**
- Leads `5562991509522` e `5531988172133` possuem **2 conversas cada, em 2 canais Meta distintos** (`a3a607b1-…` e `6e51629d-…`).
- O disparo (`Disparo-Ja-chamados`, 26/05) e todo o histórico vivem na conversa do canal `a3a607b1` (status `template_sent`).
- Em 15/06 chegou uma auto-resposta de ausência do próprio lead pelo canal `6e51629d`, criando uma **conversa nova e vazia**; a Valéria respondeu nela, sem o disparo/histórico.
- **Conclusão:** não é perda de dados — é **fragmentação de conversa por lead×canal**. O disparo existe no banco, mas em outra conversa que a UI não exibe junto.
- **Correção escolhida:** agregação na UI (Fase 3, Tarefa 3.4). Backend de roteamento permanece intacto.

- [ ] **0.1** Registrar o achado forense como nota no `docs/` e na memória do projeto (`feedback`/`project`). Sem código.

---

## FASE 1 — DB & Injeção de Contexto (Backend)

Objetivo: a LLM passa a "enxergar" o que foi respondido (reply) e o que foi reagido (reaction); base de dados pronta para blacklist e dedup.

### Tarefa 1.1 — `get_history` expõe campos de contexto
**Files:** Modify `backend/app/conversations/service.py` (`get_history`, ~L207); Test `backend/tests/test_get_history_context.py` (novo).

- Hoje `get_history` seleciona apenas `role, content, stage, created_at`. O orchestrator não recebe `wamid`/`quoted_wamid`/`message_type`/`metadata`, então não tem como saber o que foi citado/reagido.
- [ ] Estender o `select` para incluir `wamid, quoted_wamid, message_type, metadata`.
- [ ] Teste: `get_history` retorna esses campos (mock supabase) — falha antes, passa depois.
- [ ] Garantir que callers existentes não quebram (campos extras são ignorados onde não usados).
- [ ] Commit: `feat(conversations): get_history expõe wamid/quoted/message_type/metadata p/ contexto`.

### Tarefa 1.2 — Resolver texto citado (reply) no histórico do orchestrator
**Files:** Modify `backend/app/agent/orchestrator.py` (montagem de `messages`, ~L144-162); helper novo em `conversations/service.py` (`resolve_quoted_text(quoted_wamid) -> str|None`); Test `backend/tests/test_orchestrator_reply_context.py`.

- Abordagem: ao montar o histórico, para a mensagem do usuário que tem `quoted_wamid`, buscar o `content` da mensagem original (lookup por `wamid` em `messages`) e **prefixar** uma marcação no texto que vai à LLM, ex: `[Em resposta a: "<texto original truncado>"] <texto do lead>`.
- [ ] Helper `resolve_quoted_text` (fail-open: retorna None se não achar) — com teste (achou / não achou / erro).
- [ ] No orchestrator, aplicar a marcação só ao turno do usuário que tem `quoted_wamid`. Não alterar o que é salvo no banco — é enriquecimento só para o prompt.
- [ ] Teste: histórico com `quoted_wamid` válido injeta o trecho citado no `messages` enviado à LLM.
- [ ] Commit: `feat(agent): injeta texto citado (reply) no contexto do orchestrator`.

### Tarefa 1.3 — Resolver alvo da reação no histórico do orchestrator
**Files:** Modify `backend/app/agent/orchestrator.py`; reaproveitar lookup por `wamid`; Test `backend/tests/test_orchestrator_reaction_context.py`.

- Mensagens de reação chegam com `message_type='reaction'` e `metadata={emoji, target_wamid}`. Hoje viram texto cru no histórico (`[reaction: meta_b64=...]`) e a LLM não entende.
- [ ] Ao montar o histórico, para item com `message_type='reaction'`, traduzir para texto legível: `[O lead reagiu com <emoji> à mensagem: "<texto do target truncado>"]`, resolvendo `target_wamid` → conteúdo.
- [ ] Teste: reação no histórico é convertida em linha legível com emoji + trecho alvo.
- [ ] Commit: `feat(agent): traduz reações (emoji + alvo) no contexto do orchestrator`.

### Tarefa 1.4 — Índice em `messages.wamid` (suporte a dedup/lookup)
**Files:** Create `backend/migrations/<n>_index_messages_wamid.sql`.

- Os lookups por `wamid` (dedup da fase anterior + reply/reaction acima) fazem seq scan hoje (sem índice).
- [ ] Migration: `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_messages_wamid ON public.messages(wamid) WHERE wamid IS NOT NULL;`
- [ ] **Não aplicar automaticamente em produção** — apresentar o SQL ao usuário para execução manual (segue diretriz de DB de produção). Documentar no plano de execução.
- [ ] Commit: `chore(db): migration de índice parcial em messages.wamid (aplicar manualmente)`.

---

## FASE 2 — Agent Tools & Lógica do LLM

### Tarefa 2.1 — Humanizer: corrigir bolhas excessivas (Item 2a)
**Files:** Modify `backend/app/humanizer/splitter.py`; Test `backend/tests/test_splitter_bubbles.py`.

- Raiz: `splitter.py` faz `text.replace("\\n\\n","\n").replace("\\n","\n")` e depois `split("\n")` → cada quebra simples vira bolha (6-7 bolhas).
- Abordagem: tratar **`\n\n` (parágrafo) como o ÚNICO separador de bolha**; `\n` simples vira espaço/quebra dentro da mesma bolha. Aplicar **clamp rígido a 3 bolhas** (juntar excedente na última, ou descartar conforme decisão de implementação — recomendo juntar para não perder conteúdo). Manter a normalização do literal `\n` textual e o safety de `R$`.
- [ ] Teste (falha primeiro): entrada com 6 quebras simples → ≤3 bolhas; entrada com 5 parágrafos → 3 bolhas (excedente unido); literal `\n` textual tratado; `R$` preservado.
- [ ] Implementar split por `\n\n`, normalizando `\n` simples; clamp a 3.
- [ ] Commit: `fix(humanizer): bolhas apenas por parágrafo (\n\n) + clamp a 3 (anti-fragmentação)`.

### Tarefa 2.2 — Tool `marcar_interesse` + gate de follow-up (Item 2b)
**Files:** Modify `backend/app/agent/tools.py` (schema + executor + `get_tools_for_stage`); Modify `backend/app/buffer/processor.py` (gate antes de `schedule_followup`, ~L444-453); Modify `backend/app/agent/prompts/base.py` (quando chamar); Test `backend/tests/test_marcar_interesse.py`, `backend/tests/test_followup_gate.py`.

- Decisão aprovada: follow-up só se a LLM sinalizar interesse claro via tool.
- Abordagem: nova tool `marcar_interesse(nivel?: "morno"|"quente", motivo)`; executor persiste flag (ex: `leads.metadata.interest_marked_at` ou coluna dedicada / `conversations`). O `processor` só chama `schedule_followup` se a flag estiver setada para a conversa/lead **nesta interação**.
- [ ] Definir onde persistir o sinal (recomendo `conversations` ou `leads.metadata` — confirmar na execução). Sem DDL pesado se usar `metadata`.
- [ ] Tool schema + executor (com teste: chamada seta o sinal).
- [ ] `processor`: ler sinal e condicionar o agendamento (teste: sem sinal → não agenda; com sinal → agenda).
- [ ] Adicionar `marcar_interesse` aos stages relevantes em `get_tools_for_stage`.
- [ ] Prompt: instruir a chamar `marcar_interesse` só em interesse genuíno (perguntou preço/quer fechar/pediu detalhes de compra), não em mera resposta educada.
- [ ] Commits atômicos: (a) tool; (b) gate no processor; (c) prompt.

### Tarefa 2.3 — `registrar_optout` move lead para Blacklist (Item 1b - backend)
**Files:** Modify `backend/app/agent/tools.py` (`registrar_optout`, ~L328); novo helper `move_lead_deals_to_blacklist()` em `backend/app/leads/service.py` (ou `deals`); Test `backend/tests/test_optout_blacklist.py`.

- Hoje `registrar_optout` só faz `ai_enabled=False`. Precisa também **tirar de funis ativos e jogar no funil Blacklist**.
- Dados confirmados: pipeline Blacklist `8988e852-2836-4add-b023-4db4d6cd0e6e`, stage `fbace13d-d788-423a-879d-ee468dff29ed`.
- Abordagem: helper que, para o lead, atualiza os `deals` para o pipeline/stage Blacklist (mover, não duplicar — padrão já usado no broadcast worker: update por `lead_id`). Cancelar follow-ups pendentes (já existe `cancel_followups_by_phone`).
- [ ] Helper `move_lead_deals_to_blacklist(lead_id)` (IDs como constantes nomeadas; fail-soft com log) + teste.
- [ ] `registrar_optout`: após `ai_enabled=False`, chamar o helper + cancelar follow-ups. Teste do fluxo completo.
- [ ] Commit: `feat(tools): opt-out move lead para funil Blacklist e cancela follow-ups`.

### Tarefa 2.4 — Atualização de nome quando o lead corrige (Item 1a)
**Files:** Modify `backend/app/agent/prompts/base.py` (instrução); confirmar `salvar_nome` em `tools.py` (já faz `update_lead(name=...)`); Test `backend/tests/test_salvar_nome_correcao.py` (comportamento via prompt é difícil de testar unitariamente — cobrir o executor).

- `salvar_nome` já existe e dá UPDATE no CRM. O gap é de **prompt**: quando o lead diz "não sou o fulano / meu nome é X", a Valéria deve perguntar/!confirmar o nome e chamar `salvar_nome` com o novo valor.
- [ ] Prompt: adicionar regra explícita de correção de identidade → perguntar nome correto → `salvar_nome(novo_nome)`; nunca insistir no nome antigo.
- [ ] Teste do executor `salvar_nome` (update chamado com novo nome) — garante a ferramenta-alvo.
- [ ] Commit: `feat(prompt): corrige/atualiza nome do lead via salvar_nome quando há correção`.

### Tarefa 2.5 — Fechamento pós-function-call de mídia (Item 2c)
**Files:** Modify `backend/app/agent/orchestrator.py` (tratamento pós-tool, ~L287-324); Modify `backend/app/agent/prompts/base.py`; Test `backend/tests/test_orchestrator_post_tool_media.py`.

- Contexto: o loop já reenvia o resultado da tool à LLM; a fase anterior corrigiu o `[AGENT EMPTY AFTER TOOLS]` com `max_tokens=4096` + safety message genérica. O backlog pede uma **mensagem de fechamento contextual** após `enviar_fotos`/`enviar_foto_produto` (a conversa não pode "morrer").
- Abordagem: garantir que, após tools de mídia, a segunda chamada (sem tools) produza uma continuação real; o `result` da tool já é informativo ("X fotos enfileiradas"). Reforçar via prompt para sempre fechar com pergunta após enviar mídia. Avaliar tornar a safety message menos genérica para o caso de mídia.
- [ ] Teste: após `enviar_fotos`, o orchestrator retorna texto não-vazio de continuação (mock LLM).
- [ ] Prompt: regra "após enviar fotos, comente e faça 1 pergunta de avanço (qual chamou atenção?)".
- [ ] Commit: `fix(agent): garante mensagem de fechamento/continuação após tools de mídia`.

---

## FASE 3 — Frontend (UI)

### Tarefa 3.1 — Reply: resolver e exibir mensagem original (Item 3a)
**Files:** Modify `frontend/src/app/api/conversations/[id]/messages/route.ts` (~L198-218); Modify `frontend/src/components/conversas/message-bubble.tsx` (`QuotedBlock`); `frontend/src/lib/types.ts`.

- Hoje o `quoted_message` só é resolvido se a original estiver no lote carregado e com `wamid` batendo; senão exibe "Mensagem original não disponível".
- Abordagem: quando `quoted_wamid`/`quoted_message_id` não resolver no lote, fazer um lookup adicional em `messages` por `wamid` (ou id) e anexar `quoted_message`. Fallback de UI permanece, mas raro.
- [ ] Backend route: lookup suplementar por wamid quando ausente no mapa (uma query batch para os wamids não resolvidos).
- [ ] UI: `QuotedBlock` mostra autor + trecho; manter fallback.
- [ ] Commit: `fix(ui): resolve mensagem original de replies via lookup por wamid`.

### Tarefa 3.2 — Reações: exibir mensagem-alvo (Item 3b)
**Files:** Modify `frontend/src/components/conversas/message-bubble.tsx` (bloco `isReaction`, ~L390-398); route como 3.1 para anexar alvo; `types.ts`.

- Hoje mostra só "Reagiu: 👍". Deve mostrar a mensagem-alvo.
- Abordagem: resolver `metadata.target_wamid` → conteúdo da original (mesma infra de lookup da 3.1) e renderizar "Reagiu com 👍 a: <trecho>".
- [ ] Backend: anexar alvo da reação (resolvido por `target_wamid`).
- [ ] UI: renderizar emoji + trecho-alvo.
- [ ] Commit: `fix(ui): reação exibe emoji e mensagem-alvo`.

### Tarefa 3.3 — Botão "Parar mensagens" (Item 1b - frontend)
**Files:** novo botão na view de conversa (`frontend/src/components/conversas/chat-view.tsx`); novo endpoint `frontend/src/app/api/conversations/[id]/optout/route.ts` (ou backend FastAPI route); reusa o helper de blacklist da Tarefa 2.3.

- Não existe hoje. O botão deve **tirar de funis ativos + jogar no Blacklist imediatamente** (manual, pelo operador).
- [ ] Endpoint que aciona: `ai_enabled=False` + `move_lead_deals_to_blacklist` + cancelar follow-ups (reuso do backend).
- [ ] Botão na UI com confirmação; feedback de sucesso.
- [ ] Commit: `feat(ui): botão Parar mensagens (opt-out + Blacklist imediato)`.

### Tarefa 3.4 — Agregação de conversas por lead na UI (Item 4)
**Files:** lista de conversas (`frontend/src/app/(...)/conversas` + componentes); possivelmente API de listagem.

- Decisão aprovada: backend intacto; UI agrupa conversas do mesmo lead (mesmo telefone) para que o disparo (em outra conversa/canal) apareça junto.
- Abordagem: na listagem, agrupar por `lead_id`/`phone`; ao abrir, mesclar/mostrar as conversas do lead (ou indicar e permitir navegar). Definir UX exata na execução (merge vs. abas) — recomendo merge cronológico read-only por telefone.
- [ ] Agrupar conversas por lead na listagem.
- [ ] Exibição unificada do histórico do lead (todas as conversas/canais).
- [ ] Commit: `feat(ui): agrega conversas por lead (expõe disparo em canal distinto)`.

---

## Ordem de execução recomendada
Fase 1 (1.1→1.2→1.3→1.4) → Fase 2 (2.1→2.2→2.3→2.4→2.5) → Fase 3 (3.1→3.2→3.3→3.4).
Cada tarefa: subagente implementador (TDD) → revisão de spec → revisão de qualidade → commit. Sem push.

## Pontos a confirmar na execução (não bloqueiam o plano)
- 2.2: onde persistir o sinal de interesse (`leads.metadata` vs coluna/`conversations`).
- 2.1: excedente de bolhas — juntar na 3ª (recomendado) vs. truncar.
- 3.4: UX de agregação (merge cronológico vs. abas por canal).
