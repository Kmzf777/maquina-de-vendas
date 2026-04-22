# Fix Agent Routing and Outbound Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 bugs: (1) inbound messages silently dropped when channel has no agent profile, (2) CRM shows misleading "Padrão do canal" label, (3) outbound secretaria uses inbound greeting language, (4) outbound atacado leads with diagnosis instead of product presentation.

**Architecture:** Three independent layers — processor routing logic (Python), frontend label (TypeScript/React), and two prompt files (plain strings). No shared state between tasks; all can be implemented and committed separately.

**Tech Stack:** FastAPI (Python 3.11), Next.js 15 App Router, Tailwind CSS, OpenAI SDK

---

## Context

Branch: `fix/agent-routing-and-outbound-prompt` (from master)

### How the agent pipeline works

1. WhatsApp message arrives → `buffer/processor.py::process_buffered_messages()`
2. Processor calls `_resolve_agent_profile_id(conversation, channel)`:
   - Priority 1: `conversation.agent_profile_id` (set by broadcast worker for outbound campaigns)
   - Priority 2: `channel.agent_profiles.id` (channel default)
   - Priority 3: `None`
3. **BUG:** When result is `None`, processor returns early ("human-only mode") and the agent never runs
4. **CORRECT BEHAVIOR:** `None` means "no explicit profile set" → run the orchestrator with `agent_profile_id=None` → orchestrator defaults to `valeria_inbound`
5. The orchestrator (`orchestrator.py`) already handles `None` gracefully via `_resolve_prompt_key(None)` which returns `"valeria_inbound"`

### How agent profiles determine which prompt to use

- `agent_profile.prompt_key = "valeria_inbound"` → uses inbound prompts
- `agent_profile.prompt_key = "valeria_outbound"` → uses outbound prompts
- `agent_profile_id = None` → orchestrator hardcodes `prompt_key = "valeria_inbound"`

### Inbound vs Outbound distinction

- **Valeria Inbound**: default for ALL inbound conversations (lead messaged us first). Runs whenever no explicit outbound profile is set.
- **Valeria Outbound**: ONLY activated when a broadcast campaign explicitly sets `conversation.agent_profile_id` to a valeria_outbound profile. Never activates on its own.

---

## Task 1: Fix processor.py — remove "human-only mode" fallback

**Files:**
- Modify: `backend/app/buffer/processor.py:144-149`

The current code stops the agent when no profile is configured. Since `valeria_inbound` is always the correct default for untagged conversations, we remove the early return and let the agent run.

- [ ] **Step 1: Read the current processor code**

Open `backend/app/buffer/processor.py` and locate the section around line 144:

```python
    # Resolve agent profile: conversation takes priority over channel default
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)
    if not agent_profile_id:
        logger.info(f"No agent profile for channel {channel_id}, human-only mode")
        _update_last_msg(conversation["id"])
        return

    # Run AI agent
```

- [ ] **Step 2: Remove the early return block**

Replace the block above with:

```python
    # Resolve agent profile: conversation takes priority over channel default
    # None means no explicit profile — orchestrator defaults to valeria_inbound
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)

    # Run AI agent
```

The three lines (`if not agent_profile_id: ... return`) are deleted entirely. The `agent_profile_id` variable is kept because it's passed to `run_agent()` a few lines below.

- [ ] **Step 3: Verify the surrounding code still reads correctly**

After the edit, the block should look like:

```python
    # Resolve agent profile: conversation takes priority over channel default
    # None means no explicit profile — orchestrator defaults to valeria_inbound
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)

    # Run AI agent
    try:
        conversation["leads"] = lead
        response = await run_agent(conversation, resolved_text, agent_profile_id=agent_profile_id)
    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        _update_last_msg(conversation["id"])
        return
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/buffer/processor.py
git commit -m "fix: run valeria_inbound by default when no agent profile configured"
```

---

## Task 2: Fix contact-detail.tsx — rename "Padrão do canal" to "Valeria Inbound (padrão)"

**Files:**
- Modify: `frontend/src/components/conversas/contact-detail.tsx`

The dropdown option with `value=""` (no profile override) currently says "Padrão do canal" which is ambiguous — it could mean "agent from channel" or "no agent at all". The actual behavior is always valeria_inbound, so the label should reflect that.

- [ ] **Step 1: Locate the select element**

In `contact-detail.tsx`, find the `<select>` for the agent profile. It has this option:

```tsx
<option value="">Padrão do canal</option>
```

- [ ] **Step 2: Change the label**

Replace:
```tsx
<option value="">Padrão do canal</option>
```

With:
```tsx
<option value="">Valeria Inbound (padrão)</option>
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd /home/rafael/maquinadevendas/frontend && npx tsc --noEmit
```

Expected: no output (zero errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/contact-detail.tsx
git commit -m "fix: rename 'Padrão do canal' to 'Valeria Inbound (padrão)' in agent dropdown"
```

---

## Task 3: Fix outbound secretaria — remove inbound greeting language from ETAPA 1

**Files:**
- Modify: `backend/app/agent/prompts/valeria_outbound/secretaria.py`

The ETAPA 1 body currently uses "vi que voce demonstrou interesse nos nossos cafes, queria entender melhor sua demanda" — this is **inbound language** (implying the lead came to us with interest). In an outbound context, WE initiated the contact, not the lead. This phrase must be replaced with outbound-appropriate language that positions Café Canastra proactively.

- [ ] **Step 1: Open the file and locate ETAPA 1**

In `backend/app/agent/prompts/valeria_outbound/secretaria.py`, find:

```
## ETAPA 1: APRESENTACAO E COLETA DE NOME

**Comportamento:** Apresente-se de forma educada, acolhedora e levemente descontraida.

**Objetivo:** Coletar o nome completo do cliente.

**Acoes:**
1. Cumprimente o cliente de forma calorosa
2. Apresente-se como sendo da Cafe Canastra
3. Solicite o nome do cliente de maneira natural
4. EXECUTE a ferramenta salvar_nome assim que receber o nome

Exemplos:
- "oi, tudo bem? aqui e a Valeria, do comercial da Cafe Canastra"
- "vi que voce demonstrou interesse nos nossos cafes, queria entender melhor sua demanda"
- "com quem eu to falando?"
```

- [ ] **Step 2: Replace the inbound examples with outbound examples**

Replace only the `Exemplos:` block within ETAPA 1:

```
Exemplos:
- "oi, tudo bem? aqui e a Valeria, do comercial da Cafe Canastra"
- "somos uma torrefacao de cafes especiais da Serra da Canastra — trabalhamos com atacado, private label e exportacao"
- "queria bater um papo rapidinho pra entender se faz sentido pra voce"
- "com quem eu to falando?"
```

The key change: remove "vi que voce demonstrou interesse nos nossos cafes" (inbound) and add a brief positioning line about what Café Canastra does, making it clear this is an active outreach.

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/prompts/valeria_outbound/secretaria.py
git commit -m "fix: remove inbound language from outbound secretaria ETAPA 1 greeting"
```

---

## Task 4: Fix outbound atacado — lead with product for new leads, diagnosis is secondary

**Files:**
- Modify: `backend/app/agent/prompts/valeria_outbound/atacado.py`

**Root cause of the "enrustido" problem:** ETAPA 0 for new leads currently says "siga o funil normalmente a partir da Etapa 1" which goes into the DIAGNÓSTICO DE DOR (pain diagnosis) — lots of questions about current suppliers, problems, etc. For an outbound agent that reached out to a hotel that said "quero comprar para o meu negócio", asking "seu fornecedor atual entende suas necessidades?" before even showing a product is backwards. A real outbound seller would pitch the product first, then qualify.

**New flow for outbound atacado — new lead:**
1. Acknowledge briefly (café especial, fazenda, Serra da Canastra)
2. Offer to show the catalog immediately
3. If yes → go to ETAPA 2 (product presentation + photos)
4. ETAPA 1 (pain diagnosis) is reserved for leads who say they're happy with their current supplier

- [ ] **Step 1: Open the file and locate ETAPA 0**

In `backend/app/agent/prompts/valeria_outbound/atacado.py`, find:

```
## ETAPA 0: VERIFICACAO DE CONTEXTO

ANTES de qualquer outra etapa:
- Lead JA conversou sobre atacado: "da ultima vez a gente falava de [produto/volume] — ainda faz sentido?"
- Lead MUDOU de ideia: acolhe sem resistencia, execute mudar_stage se necessario.
- Lead NOVO no atacado: siga o funil normalmente a partir da Etapa 1.

POSTURA: voce apresenta ativamente. Nao aguarda o lead manifestar dor espontaneamente — voce provoca a reflexao.
```

- [ ] **Step 2: Replace ETAPA 0 entirely**

```
## ETAPA 0: CONTEXTO DE ABORDAGEM ATIVA

Voce foi ativado via campanha — voce iniciou o contato. Leia o historico antes de qualquer coisa.

- Lead COM historico de atacado: retome pelo que foi discutido. "da ultima vez a gente falava de [produto/volume] — ainda faz sentido pro seu negocio?"
- Lead MUDOU de ideia: acolhe sem resistencia, execute mudar_stage se necessario.
- Lead NOVO no atacado (sem historico, vindo da secretaria):
  NAO inicie com perguntas sobre fornecedor atual ou dor. Va direto ao produto:
  1. Contextualize em 1 frase: "cafe especial direto da fazenda, Serra da Canastra — trabalhamos com varios [tipo do negocio do lead] por aqui"
  2. Oferea mostrar o catalogo: "posso te mostrar os produtos e precos que temos pro seu segmento?"
  3. Se o lead confirmar (SIM, PODE, QUERO) → va para ETAPA 2 diretamente (produto + fotos)
  4. Se o lead fizer uma PERGUNTA PROPRIA → responda e encaminhe para ETAPA 2
  5. Se o lead demonstrar RESISTENCIA ou dizer que ja tem fornecedor → use ETAPA 1.1

POSTURA: voce nao espera o lead manifestar dor. Voce apresenta o produto, envia as fotos, cria desejo — e so entao qualifica se necessario.
```

- [ ] **Step 3: Update ETAPA 1 label to clarify it's for resistance only**

Find the beginning of ETAPA 1:

```
## ETAPA 1: DIAGNOSTICO DE DOR

Gatilho: O cliente indica que esta buscando cafe para seu negocio.
```

Replace only the gatilho line:

```
## ETAPA 1: DIAGNOSTICO DE DOR

Gatilho: Lead demonstra resistencia, diz que ja tem fornecedor, ou nao reage ao catalogo com interesse claro.
```

This repositions the pain diagnosis as a fallback for resistant leads, not the default opening.

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/prompts/valeria_outbound/atacado.py
git commit -m "fix: outbound atacado leads with product pitch for new leads, diagnosis is fallback"
```

---

## Self-Review

**Spec coverage:**
- ✅ Task 1 covers "não existe agente padrão" — processor no longer drops messages without a profile
- ✅ Task 2 covers "CRM shows confusing label" — renamed to "Valeria Inbound (padrão)"
- ✅ Task 3 covers "outbound secretaria uses inbound language" — removed "demonstrou interesse"
- ✅ Task 4 covers "outbound muito enrustido" — new leads see product before diagnosis

**Placeholder scan:** No TBDs, all code blocks are complete.

**Type consistency:** No new types introduced. Only string changes in prompts and one label change in TSX.
