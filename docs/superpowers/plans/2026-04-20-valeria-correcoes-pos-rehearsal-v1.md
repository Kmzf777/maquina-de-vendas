# Valéria Correções Pós-Rehearsal v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corrigir falhas estruturais identificadas no primeiro rehearsal completo (A1–A4 failed) para atingir pelo menos 4/5 arquétipos com hard-checks passando e bot_score médio ≥ 6/10 na próxima rodada.

**Architecture:** As falhas têm **duas naturezas**: (1) **instrumentação**: o orchestrator muda de stage em memória mas não registra o evento, e as tools salvam system messages em português livre — o rehearsal verifier não consegue detectar stages visitadas nem tool calls específicas. (2) **comportamento do LLM**: o prompt não tem política de amostras (gera contradição no A1), não obriga responder-antes-de-qualificar (A2 ignora pergunta 2x), não restringe `encaminhar_humano` (A3/A4 usam como fuga), e o `agent_profile.model` está inválido (`gemini-2.0-flash` → fallback silencioso para `gpt-4.1-mini`). O plano corrige as duas frentes e encerra com uma execução completa de rehearsal para validar as métricas.

**Tech Stack:** FastAPI backend (Python 3.11), Supabase Postgres, OpenAI SDK, Gemini 2.5 Pro (actor/judge), pytest, Next.js 16 App Router (frontend), Docker Swarm (produção — este plano opera só em dev).

---

## Convenções deste plano

- **Marker de evento estruturado**: system messages de eventos ganham prefixo machine-readable:
  - Mudança de stage: `[event:stage] stage alterado para: {stage}`
  - Execução de tool: `[tool:{nome}] {texto em português para humanos}`
- Frontend faz *strip* desses prefixos na renderização, portanto o usuário final **nunca vê** `[tool:…]` / `[event:…]`.
- O rehearsal runner e o verifier usam os prefixos como fonte de verdade.
- Retrocompatibilidade do runner: o padrão de português `"stage alterado para"` continua funcionando, então o evento novo é superset do antigo.

---

## File Structure

Arquivos tocados (em ordem de dependência):

- **MODIFY** `backend/app/agent/tools.py` — prefixar system messages das tools com `[tool:X]`.
- **MODIFY** `backend/app/agent/orchestrator.py` — emitir `[event:stage]` depois de `mudar_stage`.
- **MODIFY** `backend/app/agent/prompts/base.py` — política de amostras, regra *answer-before-qualify*, regras de uso de `encaminhar_humano`.
- **MODIFY** `backend/app/agent/prompts/valeria_inbound/atacado.py` — ETAPA 4 (fechamento) mais explícita.
- **MODIFY** `backend/app/agent/prompts/valeria_inbound/private_label.py` — handoff explícito.
- **MODIFY** `backend/app/agent/prompts/valeria_inbound/exportacao.py` — handoff explícito.
- **MODIFY** `backend/scripts/rehearsal/archetypes.py` — fix nome do check em A1 (`enviar_foto` → `enviar_foto_produto` ou manter prefix match).
- **MODIFY** `frontend/src/components/conversas/chat-view.tsx` — strip de prefixes nas system messages.
- **CREATE** `backend/tests/test_tools_event_markers.py` — TDD para prefixos `[tool:X]`.
- **CREATE** `backend/tests/test_orchestrator_stage_event.py` — TDD para emissão de `[event:stage]`.
- **MODIFY** `backend/tests/test_rehearsal_verifier.py` — cobrir o caso `has_tool_call` com o novo formato.
- **SQL** em Supabase (execução manual via MCP): resetar `agent_profiles.model` inválido.

---

# Parte 1 — Infra de verificação (instrumentação)

### Task 1.1: Prefixar system messages das tools com `[tool:X]`

**Files:**
- Modify: `backend/app/agent/tools.py:193` (encaminhar_humano), `backend/app/agent/tools.py:225` (enviar_fotos), `backend/app/agent/tools.py:252` (enviar_foto_produto), `backend/app/agent/tools.py:266-271` (registrar_pedido_simples)
- Create: `backend/tests/test_tools_event_markers.py`

- [ ] **Step 1: Escrever o teste que vai falhar**

Crie `backend/tests/test_tools_event_markers.py`:

```python
"""Tools que produzem system messages devem prefixar com [tool:X]
para que o rehearsal verifier consiga fazer matching determinístico."""
import pytest
from unittest.mock import patch

from app.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_encaminhar_humano_saves_tool_marker():
    with patch("app.agent.tools.update_lead") as _ul, \
         patch("app.agent.tools.create_deal") as _cd, \
         patch("app.agent.tools.save_message") as mock_save:
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "fechamento"},
            lead_id="lead-1",
            phone="+55...",
            conversation_id="conv-1",
        )
    assert mock_save.called
    args, kwargs = mock_save.call_args
    content = args[2]
    assert content.startswith("[tool:encaminhar_humano]")
    assert "Joao Bras" in content
    assert "fechamento" in content


@pytest.mark.asyncio
async def test_registrar_pedido_simples_saves_tool_marker():
    with patch("app.agent.tools.create_deal") as _cd, \
         patch("app.agent.tools.save_message") as mock_save:
        await execute_tool(
            "registrar_pedido_simples",
            {"categoria": "atacado", "produto": "Classico", "volume_kg": 20, "observacoes": "sem pressa"},
            lead_id="lead-1",
            phone="+55...",
            conversation_id="conv-1",
        )
    args, _kw = mock_save.call_args
    content = args[2]
    assert content.startswith("[tool:registrar_pedido_simples]")
    assert "Classico" in content
    assert "20kg" in content


@pytest.mark.asyncio
async def test_enviar_fotos_saves_tool_marker(tmp_path, monkeypatch):
    # create a fake photos dir with one file
    cat_dir = tmp_path / "atacado"
    cat_dir.mkdir()
    (cat_dir / "foto_1.jpg").write_bytes(b"\xff\xd8\xff")
    monkeypatch.setattr(
        "app.agent.tools.Path",
        lambda *a, **kw: tmp_path if a == () else __import__("pathlib").Path(*a, **kw),
    )
    # easier path: monkeypatch photos dir resolution directly
    with patch("app.agent.tools.get_active_channel", return_value="whatsapp"), \
         patch("app.agent.tools.get_provider") as mock_get_provider, \
         patch("app.agent.tools.save_message") as mock_save:
        mock_get_provider.return_value.send_image_base64 = _AsyncNoop()
        # Patch the __file__-based photos_dir resolution
        with patch("app.agent.tools.Path") as MP:
            fake_file = tmp_path / "app" / "agent" / "tools.py"
            fake_file.parent.mkdir(parents=True)
            fake_file.write_text("")
            MP.return_value.parent.parent.__truediv__.side_effect = lambda p: tmp_path / p
            await execute_tool(
                "enviar_fotos",
                {"categoria": "atacado"},
                lead_id="lead-1",
                phone="+55",
                conversation_id="conv-1",
            )
    if mock_save.called:
        content = mock_save.call_args[0][2]
        assert content.startswith("[tool:enviar_fotos]")


class _AsyncNoop:
    async def __call__(self, *a, **kw):
        return None
```

Observação: o terceiro teste é complexo por causa do `Path(__file__).parent.parent / "photos"`. **Simplificação aceitável**: mantenha apenas os dois primeiros testes (`encaminhar_humano` e `registrar_pedido_simples`). Os outros são cobertos pela revisão manual de código e pelo rehearsal end-to-end em Parte 4.

Versão final do arquivo (mantenha só os dois testes):

```python
"""Tools que produzem system messages devem prefixar com [tool:X]
para que o rehearsal verifier consiga fazer matching determinístico."""
import pytest
from unittest.mock import patch

from app.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_encaminhar_humano_saves_tool_marker():
    with patch("app.agent.tools.update_lead"), \
         patch("app.agent.tools.create_deal"), \
         patch("app.agent.tools.save_message") as mock_save:
        await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "fechamento"},
            lead_id="lead-1",
            phone="+55...",
            conversation_id="conv-1",
        )
    content = mock_save.call_args[0][2]
    assert content.startswith("[tool:encaminhar_humano]")
    assert "Joao Bras" in content
    assert "fechamento" in content


@pytest.mark.asyncio
async def test_registrar_pedido_simples_saves_tool_marker():
    with patch("app.agent.tools.create_deal"), \
         patch("app.agent.tools.save_message") as mock_save:
        await execute_tool(
            "registrar_pedido_simples",
            {"categoria": "atacado", "produto": "Classico", "volume_kg": 20, "observacoes": "sem pressa"},
            lead_id="lead-1",
            phone="+55...",
            conversation_id="conv-1",
        )
    content = mock_save.call_args[0][2]
    assert content.startswith("[tool:registrar_pedido_simples]")
    assert "Classico" in content
    assert "20kg" in content
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
cd backend && pytest tests/test_tools_event_markers.py -v
```

Esperado: FAIL em ambos com `AssertionError: 'Lead encaminhado para…' does not start with '[tool:encaminhar_humano]'`.

- [ ] **Step 3: Implementar os prefixos em `tools.py`**

Em `backend/app/agent/tools.py`, substitua as 4 chamadas de `save_message`:

Linha 193 (encaminhar_humano):

```python
save_message(lead_id, "system", f"[tool:encaminhar_humano] Lead encaminhado para {args.get('vendedor', 'Vendedor')}: {motivo}", conversation_id=conversation_id)
```

Linha 225 (enviar_fotos):

```python
save_message(lead_id, "system", f"[tool:enviar_fotos] Fotos de {categoria} enviadas ({sent}/{len(photos)})", conversation_id=conversation_id)
```

Linha 252 (enviar_foto_produto):

```python
save_message(lead_id, "system", f"[tool:enviar_foto_produto] Foto de {produto} enviada", conversation_id=conversation_id)
```

Linhas 266–271 (registrar_pedido_simples):

```python
save_message(
    lead_id,
    "system",
    f"[tool:registrar_pedido_simples] Pedido registrado: {title}. Obs: {obs}" if obs else f"[tool:registrar_pedido_simples] Pedido registrado: {title}",
    conversation_id=conversation_id,
)
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
cd backend && pytest tests/test_tools_event_markers.py -v
```

Esperado: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/test_tools_event_markers.py
git commit -m "feat(tools): prefixar system messages com [tool:X] para rehearsal verifier"
```

---

### Task 1.2: Emitir `[event:stage]` após `mudar_stage`

**Files:**
- Modify: `backend/app/agent/orchestrator.py:136-143`
- Create: `backend/tests/test_orchestrator_stage_event.py`

- [ ] **Step 1: Escrever o teste que vai falhar**

Crie `backend/tests/test_orchestrator_stage_event.py`:

```python
"""Ao executar mudar_stage o orchestrator deve gravar um system message
[event:stage] para que o rehearsal runner detecte stages visitadas."""
import json
import pytest
from unittest.mock import patch, MagicMock

from app.agent import orchestrator


@pytest.mark.asyncio
async def test_mudar_stage_emits_event_system_message():
    tool_call = MagicMock()
    tool_call.id = "call-1"
    tool_call.function.name = "mudar_stage"
    tool_call.function.arguments = json.dumps({"stage": "atacado"})

    first_msg = MagicMock()
    first_msg.tool_calls = [tool_call]
    first_msg.content = None
    first_msg.model_dump.return_value = {"role": "assistant", "tool_calls": [{"id": "call-1"}]}

    second_msg = MagicMock()
    second_msg.tool_calls = None
    second_msg.content = "ok, seguindo"

    resp1 = MagicMock()
    resp1.choices = [MagicMock(message=first_msg)]
    resp1.usage = None
    resp2 = MagicMock()
    resp2.choices = [MagicMock(message=second_msg)]
    resp2.usage = None

    client = MagicMock()
    async def _create(**kw):
        if _create.calls == 0:
            _create.calls += 1
            return resp1
        return resp2
    _create.calls = 0
    client.chat.completions.create = _create

    with patch("app.agent.orchestrator._get_openai", return_value=client), \
         patch("app.agent.orchestrator.execute_tool", return_value="Stage alterado para: atacado"), \
         patch("app.agent.orchestrator.save_message") as mock_save, \
         patch("app.agent.orchestrator.build_system_prompt", return_value="SYSTEM"), \
         patch("app.agent.orchestrator.get_tools_for_stage", return_value=[]), \
         patch("app.agent.orchestrator.track_token_usage"):
        await orchestrator.run_agent(
            lead={"id": "lead-1", "phone": "+55..."},
            conversation_id="conv-1",
            stage="secretaria",
            history=[],
            user_message="oi",
            lead_id="lead-1",
        )

    stage_saves = [c for c in mock_save.call_args_list
                   if "[event:stage]" in (c[0][2] if len(c[0]) >= 3 else "")]
    assert stage_saves, "Esperava ao menos um system message [event:stage]"
    content = stage_saves[0][0][2]
    assert "atacado" in content
```

Observação sobre a assinatura de `run_agent`: ajuste os kwargs no teste para bater com a assinatura real em `backend/app/agent/orchestrator.py`. Se a assinatura for diferente da suposta aqui, leia o arquivo e troque o dict passado — **sem** mudar a lógica do teste.

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
cd backend && pytest tests/test_orchestrator_stage_event.py -v
```

Esperado: FAIL `AssertionError: Esperava ao menos um system message [event:stage]`.

- [ ] **Step 3: Implementar a emissão do evento**

Em `backend/app/agent/orchestrator.py`, no topo do arquivo garanta o import (se ainda não existir):

```python
from app.db.messages import save_message
```

Substitua o bloco das linhas 136–143 por:

```python
        # If mudar_stage was called, update in-memory state so the next API call
        # uses the correct stage prompt and tools — prevents infinite transition loop.
        for tc in message.tool_calls:
            if tc.function.name == "mudar_stage":
                new_stage = json.loads(tc.function.arguments).get("stage", stage)
                stage = new_stage
                tools = get_tools_for_stage(stage)
                system_prompt = build_system_prompt(lead, stage, prompt_key=prompt_key, lead_context=lead_context)
                messages[0] = {"role": "system", "content": system_prompt}
                try:
                    save_message(
                        conversation_id,
                        lead_id,
                        "system",
                        f"[event:stage] stage alterado para: {new_stage}",
                    )
                except Exception as e:
                    logger.warning(f"Failed to persist stage event for lead {lead_id}: {e}")
                break
```

> **Atenção à assinatura de `save_message`**: o projeto usa duas convenções. Em `tools.py` a chamada é `save_message(lead_id, "system", content, conversation_id=...)`. Em `processor.py` é `save_message(conversation_id, lead_id, role, content, stage)`. Leia a definição de `save_message` antes de editar e use a assinatura exata. Se necessário, ajuste o snippet acima para bater com o import real do orchestrator.

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
cd backend && pytest tests/test_orchestrator_stage_event.py -v
```

Esperado: PASS.

- [ ] **Step 5: Rodar a suite toda para garantir que nada quebrou**

```bash
cd backend && pytest -q
```

Esperado: todos os testes verdes. Se algo quebrar, investigue e corrija antes de commitar.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agent/orchestrator.py backend/tests/test_orchestrator_stage_event.py
git commit -m "feat(agent): emitir [event:stage] apos mudar_stage para rehearsal verifier"
```

---

### Task 1.3: Fix do hard-check de A1 (`has_tool_call("enviar_foto")`)

**Files:**
- Modify: `backend/scripts/rehearsal/archetypes.py:90`

**Contexto**: o check usa `if name in content.lower()`. Com o novo prefixo `[tool:enviar_foto_produto]` ou `[tool:enviar_fotos]`, a string `"enviar_foto"` é substring de ambos. Funciona por acaso — mas deixe explícito.

- [ ] **Step 1: Ler o arquivo para confirmar que o comportamento atual basta**

```bash
# Verificar linha 90 em archetypes.py
```

```python
A1 = Archetype(
    id="A1",
    ...
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("enviar_foto"),   # matches enviar_fotos OR enviar_foto_produto
        transcript_matches(r"\d+\s*(kg|quilos?)", "mencao de volume em kg"),
    ],
)
```

- [ ] **Step 2: Adicionar comentário explícito**

Substitua a linha por:

```python
        has_tool_call("enviar_foto"),  # prefix match: [tool:enviar_fotos] e [tool:enviar_foto_produto]
```

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/rehearsal/archetypes.py
git commit -m "docs(rehearsal): comentar prefix-match de has_tool_call('enviar_foto') em A1"
```

---

### Task 1.4: Atualizar teste do verifier para o novo formato

**Files:**
- Modify: `backend/tests/test_rehearsal_verifier.py`

- [ ] **Step 1: Ler o teste atual**

Leia `backend/tests/test_rehearsal_verifier.py` e identifique os testes de `has_tool_call`.

- [ ] **Step 2: Adicionar caso positivo com o novo marker**

Adicione ao final do arquivo:

```python
def test_has_tool_call_matches_tool_marker():
    from scripts.rehearsal.archetypes import has_tool_call
    run_data = {
        "events": [
            {"content": "[tool:encaminhar_humano] Lead encaminhado para Joao Bras: fechamento"},
        ]
    }
    check = has_tool_call("encaminhar_humano")
    passed, reason = check(run_data)
    assert passed is True


def test_has_tool_call_no_match_when_tool_absent():
    from scripts.rehearsal.archetypes import has_tool_call
    run_data = {
        "events": [{"content": "[tool:enviar_fotos] Fotos de atacado enviadas (3/3)"}]
    }
    check = has_tool_call("encaminhar_humano")
    passed, reason = check(run_data)
    assert passed is False
```

- [ ] **Step 3: Rodar**

```bash
cd backend && pytest tests/test_rehearsal_verifier.py -v
```

Esperado: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_rehearsal_verifier.py
git commit -m "test(rehearsal): cobrir has_tool_call com marker [tool:X]"
```

---

### Task 1.5: Strip dos prefixes `[tool:*]` e `[event:*]` no frontend

**Files:**
- Modify: `frontend/src/components/conversas/chat-view.tsx`

**Contexto**: depois das Tasks 1.1 e 1.2, as system messages armazenadas têm prefixos máquina-legíveis. O usuário final não deve ver `[tool:…]`/`[event:…]`.

- [ ] **Step 1: Ler o arquivo para localizar o render de system messages**

Leia `frontend/src/components/conversas/chat-view.tsx` e localize o branch `if (msg.role === "system")` (inserido no fix anterior de bug display).

- [ ] **Step 2: Implementar o strip**

No bloco do `role === "system"`, troque `{msg.content}` por uma expressão que remove o prefixo:

```tsx
{displayMessages.map((msg) => {
  if (msg.role === "system") {
    const cleaned = msg.content.replace(/^\[(tool|event):[^\]]+\]\s*/, "");
    return (
      <div key={msg.id} className="flex justify-center my-1">
        <span className="text-[11px] text-[#7b7b78] italic px-2 text-center">
          {cleaned}
        </span>
      </div>
    );
  }
  // ... resto inalterado
```

- [ ] **Step 3: Validar visualmente**

Suba o frontend dev (`npm run dev` em `frontend/`) e abra `/conversas` em um lead com eventos. Confirme:
- "Lead encaminhado para Joao Bras: fechamento" aparece **sem** `[tool:encaminhar_humano]`
- "stage alterado para: atacado" aparece **sem** `[event:stage]`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/conversas/chat-view.tsx
git commit -m "fix(conversas): remover prefixos [tool:*]/[event:*] da renderizacao de system messages"
```

---

# Parte 2 — Config (Supabase)

### Task 2.1: Resetar `agent_profiles.model` para valor OpenAI válido

**Contexto**: Log do último rehearsal mostrou `Agent profile model 'gemini-2.0-flash' is not a valid OpenAI model, falling back to gpt-4.1-mini`. Em `orchestrator.py` o `_is_valid_openai_model` aceita prefixos `("gpt-", "o1", "o3", "o4", "chatgpt-")`. O seed original de `migration 008` era `gpt-4.1`; foi alterado manualmente para `gemini-2.0-flash`. Enquanto Valéria não migrar pro OpenRouter/google-genai, mantemos OpenAI.

- [ ] **Step 1: Inspecionar o profile atual**

Via MCP `mcp__supabase__execute_sql` no projeto `tshmvxxxyxgctrdkqvam`:

```sql
SELECT id, name, model, env_tag, is_default, is_active
FROM agent_profiles
WHERE env_tag IN ('dev', 'prod')
ORDER BY env_tag, is_default DESC;
```

Registre o resultado (principalmente quais rows têm `gemini-2.0-flash`).

- [ ] **Step 2: Atualizar para `gpt-4.1-mini`**

```sql
UPDATE agent_profiles
SET model = 'gpt-4.1-mini'
WHERE model NOT LIKE 'gpt-%'
  AND model NOT LIKE 'o1%'
  AND model NOT LIKE 'o3%'
  AND model NOT LIKE 'o4%'
  AND model NOT LIKE 'chatgpt-%'
RETURNING id, name, model, env_tag;
```

- [ ] **Step 3: Confirmar que não há mais fallback silencioso**

Reinicie o backend dev (`Run All Dev (CRM & Backend)`) e procure no log inicial (`/tmp/rehearsal-backend.log`) por `"falling back to gpt-4.1-mini"`. Não deve aparecer em novos ciclos.

Esta task não gera commit (é mudança de dados).

---

# Parte 3 — Prompts Valéria (comportamento)

### Task 3.1: Adicionar política de amostras em `base.py`

**Files:**
- Modify: `backend/app/agent/prompts/base.py`

**Contexto**: no A1 a Valéria contradisse-se 3x sobre amostras ("podemos enviar" → "não trabalhamos com amostras gratuitas" → "podemos enviar"). A política real é: **não enviamos amostra gratuita**; o cliente prova comprando o pedido mínimo de atacado (R$ 300) ou através da loja online para volumes pequenos.

- [ ] **Step 1: Localizar a seção "SITUACOES ESPECIAIS"**

Em `backend/app/agent/prompts/base.py`, ache o bloco `# SITUACOES ESPECIAIS` (~linha 214).

- [ ] **Step 2: Adicionar entrada "Cliente pede amostra grátis"**

Após o bloco de "Cliente quer comprar grao cru ou saca de cafe", insira:

```python
## Cliente pede amostra / degustacao / sample
- NAO oferecemos amostra gratuita em nenhuma categoria.
- Caminho pra provar: pedido minimo de atacado (R$ 300) com o sabor que ele quiser testar, OU compra pela loja online (https://www.loja.cafecanastra.com) para volume pequeno.
- NUNCA prometa envio gratuito, NUNCA diga "vamos ver" ou "depende" sobre amostras.
- Se o cliente insistir: reafirme sem hesitar, com naturalidade ("a gente nao trabalha com amostra gratis, mas o minimo do atacado e R$ 300 — da pra testar o sabor e ja garantir o preço de revenda").

```

- [ ] **Step 3: Adicionar regra na lista absoluta**

Em `# REGRAS ABSOLUTAS` (linha ~198), adicione item 12:

```
12. POLITICA DE AMOSTRAS — NUNCA oferecer amostra gratuita. Sempre direcionar para pedido minimo (R$ 300 atacado) ou loja online.
```

- [ ] **Step 4: Rodar testes de prompt**

```bash
cd backend && pytest tests/test_base_prompt.py -v
```

Se houver teste quebrando por assertion sobre regras específicas, ajuste o teste — o comportamento novo é intencional.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/prompts/base.py
git commit -m "feat(valeria): politica explicita de amostras — sem amostra gratis, direcionar a minimo R\$300 ou loja online"
```

---

### Task 3.2: Regra "Responder antes de qualificar" em `base.py`

**Files:**
- Modify: `backend/app/agent/prompts/base.py`

**Contexto**: no A2 a Valéria ignorou a pergunta "qual o prazo de produção?" duas vezes antes de responder. No A4 ela respondeu "enquanto eu separo os contatos, olha a variedade…" — desviando da pergunta direta.

- [ ] **Step 1: Reforçar a regra 4**

Em `# REGRAS ABSOLUTAS`, a regra 4 atual é:

```
4. RESPONDER AO QUE FOI DITO — SEMPRE reaja primeiro ao que o cliente disse. Depois pode avancar.
```

Substitua por:

```
4. RESPONDER AO QUE FOI DITO — SEMPRE responda a PERGUNTA DIRETA do cliente ANTES de fazer nova pergunta, ANTES de desviar, ANTES de oferecer produto. Se a resposta nao estiver disponivel, diga "vou confirmar isso com o time" — NUNCA mude de assunto ignorando a pergunta.
```

- [ ] **Step 2: Adicionar seção "PERGUNTAS DIRETAS NAO IGNORAR"**

Depois de `# REACAO AO CONTEXTO`, insira:

```
---

# PERGUNTAS DIRETAS NAO IGNORAR

Se o cliente fez uma PERGUNTA DIRETA (prazo, preco, MOQ, frete, documentacao, prazo de producao, politica), voce DEVE responder ANTES de qualquer outra coisa.

Exemplos do que NAO FAZER:
- Cliente: "qual o prazo de producao?" → Voce: "me conta, sua cafeteria tem qual publico?" ❌
- Cliente: "podem enviar referencias?" → Voce: "enquanto eu separo, olha a variedade que temos" ❌

Exemplos do que FAZER:
- Cliente: "qual o prazo de producao?" → Voce: "o prazo medio e 10 a 15 dias uteis. ce quer que eu detalhe as etapas?" ✅
- Cliente: "podem enviar referencias?" → Voce: "posso sim, vou ver com o Joao Bras qual case mais parecido com o seu e te mando. qual e o perfil do seu publico hoje?" ✅

Se voce NAO TEM a resposta concreta, assuma e diga com clareza: "isso eu vou confirmar com o time e te retorno" — NUNCA simule resposta, NUNCA desvie.
```

- [ ] **Step 3: Rodar testes de prompt**

```bash
cd backend && pytest tests/test_base_prompt.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/prompts/base.py
git commit -m "feat(valeria): regra explicita de responder pergunta direta antes de qualificar"
```

---

### Task 3.3: Restrições de uso de `encaminhar_humano` em `base.py`

**Files:**
- Modify: `backend/app/agent/prompts/base.py`

**Contexto**: no A3 e A4 a Valéria usou `encaminhar_humano` como escape — lead pediu "não encaminhe, me dê você mesma" e ela encaminhou. No A4 isso **quebrou a confiança** segundo o judge. A regra correta: só encaminhar quando há **handoff de fechamento** (pedido registrado + próximos passos logísticos), para **exportação** (escopo técnico fora do prompt) ou quando o cliente **pede explicitamente**.

- [ ] **Step 1: Adicionar seção "QUANDO (NAO) USAR encaminhar_humano"**

Depois da seção criada na Task 3.2, insira:

```
---

# QUANDO (NAO) USAR encaminhar_humano

encaminhar_humano e uma ferramenta de HANDOFF COMERCIAL — nao de fuga de conversa.

USE apenas em 3 situacoes:
1. FECHAMENTO: o cliente ja informou volume, sabor/tipo e cidade. Voce ja chamou registrar_pedido_simples para gravar o pedido. Entao chama encaminhar_humano para o Joao Bras finalizar pagamento/logistica.
2. EXPORTACAO: qualquer lead que mencionar exportar / pais / cafeteria no exterior — encaminhe direto, pois documentacao foge do seu escopo.
3. PEDIDO EXPLICITO: o cliente pediu com suas palavras "fala com alguem", "me manda pro vendedor", "quero falar com um humano".

NUNCA USE encaminhar_humano para:
- Evitar responder uma pergunta que voce sabe a resposta
- Escapar de objecao de preco (A4: mantenha-se na conversa, argumente valor)
- Interromper multi-intencao (A3: atenda os dois interesses na mesma conversa)
- Desviar de perguntas tecnicas de private label, atacado ou consumo — voce TEM as respostas no seu prompt de stage

Se o cliente disser "nao me encaminhe, me explica voce": OBEDECA. Continue a conversa voce mesma.
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agent/prompts/base.py
git commit -m "feat(valeria): restricoes claras de uso de encaminhar_humano (handoff so no fechamento, exportacao ou pedido explicito)"
```

---

### Task 3.4: Tighten ETAPA 4 em `atacado.py`

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/atacado.py`

**Contexto**: no A1 a Valéria não fechou (20 turnos, terminou por `max_turns`). Precisa deixar clarissimo que a meta de atacado é **chegar ao fechamento** chamando `registrar_pedido_simples` e só depois `encaminhar_humano`.

- [ ] **Step 1: Ler a ETAPA 4 atual**

Leia `backend/app/agent/prompts/valeria_inbound/atacado.py`, localize a seção "ETAPA 4" ou "ETAPA DE HANDOFF PARA FECHAMENTO".

- [ ] **Step 2: Reescrever ETAPA 4 com flow explícito**

Substitua a seção por:

```
---

# ETAPA 4 — FECHAMENTO (meta desta conversa)

Voce so sai do atacado quando:
(A) o cliente confirmou um VOLUME em kg (ex.: 10kg, 50kg)
(B) voce sabe o SABOR/PRODUTO (Classico, Suave, Canela, Microlote, Drip ou Capsulas)
(C) voce sabe a CIDADE de entrega

Tendo (A)+(B)+(C), o fluxo E:

PASSO 1: Faca a conta do frete com a tabela por regiao.
PASSO 2: Confirme o total com o cliente em UMA bolha curta ("entao fica 20kg do Classico pra Belo Horizonte, total R$600 + R$45 de frete, fechando R$645 — confirma?").
PASSO 3: Se ele confirmar, chame registrar_pedido_simples IMEDIATAMENTE (categoria='atacado', produto, volume_kg, observacoes).
PASSO 4: Na mesma resposta, chame encaminhar_humano (vendedor='Joao Bras', motivo='fechar pedido de atacado — {volume}kg {produto}').
PASSO 5: Mande UMA ultima bolha se despedindo: "ja passei seu pedido pro Joao Bras. ele te chama aqui em instantes pra fechar o pagamento e endereco".

Se faltar qualquer um de (A)(B)(C), NAO chame encaminhar_humano. Continue qualificando com UMA pergunta por turno.

Se o cliente pedir amostra gratis: siga a regra global (Parte 3.1) — sem amostra gratis, direcione ao minimo R$300 ou loja online.
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/atacado.py
git commit -m "feat(valeria/atacado): etapa 4 explicita — A+B+C => registrar_pedido_simples => encaminhar_humano"
```

---

### Task 3.5: Tighten handoff em `private_label.py` e `exportacao.py`

**Files:**
- Modify: `backend/app/agent/prompts/valeria_inbound/private_label.py`
- Modify: `backend/app/agent/prompts/valeria_inbound/exportacao.py`

**Contexto**: nos runs A2 e A5 a Valéria demorou ou falhou no handoff. O padrão deve ser: para **exportação** encaminha rapidamente (após entender país + volume aproximado), para **private label** encaminha após passar conceito + tabela + cliente demonstrar interesse concreto (marca, volume alvo, embalagem).

- [ ] **Step 1: Ler `private_label.py` e localizar a seção de handoff (se existir)**

```bash
# Leia backend/app/agent/prompts/valeria_inbound/private_label.py
```

- [ ] **Step 2: Adicionar / ajustar a seção ETAPA FINAL em `private_label.py`**

Garanta que ao final do prompt exista:

```
---

# ETAPA FINAL — HANDOFF (meta desta conversa)

Voce handoff quando o cliente ja:
(A) ouviu o conceito de private label (MOQ, prazo, embalagem com sua logo)
(B) informou nome da marca / publico alvo / volume aproximado
(C) demonstrou interesse em avancar

Entao:
PASSO 1: Confirme em UMA bolha o que o lead quer ("entendi, voce quer rodar 500 unidades de 250g com a marca X pro publico Y — e isso?")
PASSO 2: Se ele confirmar, chame encaminhar_humano (vendedor='Joao Bras', motivo='private label — marca {X}, {volume} unidades, publico {Y}').
PASSO 3: Uma ultima bolha: "passei seu projeto pro Joao Bras, ele e quem conduz os proximos passos de arte, amostra piloto e fechamento. ele fala com voce aqui mesmo em instantes".

Se faltar (A)(B)(C), continue explicando/qualificando. NUNCA use encaminhar_humano como escape.
```

- [ ] **Step 3: Ler `exportacao.py` e aplicar padrão análogo**

```
---

# ETAPA FINAL — HANDOFF (meta desta conversa)

Exportacao e handoff rapido:
(A) confirme pais de destino
(B) confirme tipo de negocio (cafeteria, torrefacao, distribuidor)
(C) confirme volume/frequencia aproximada (pode ser estimativa)

Entao chame encaminhar_humano IMEDIATAMENTE (vendedor='Joao Bras', motivo='exportacao — {pais}, {volume} para {tipo de negocio}').

Uma ultima bolha: "passei pro Joao Bras que cuida do comercial de exportacao. ele te chama aqui com a proposta e a documentacao necessaria".
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/prompts/valeria_inbound/private_label.py backend/app/agent/prompts/valeria_inbound/exportacao.py
git commit -m "feat(valeria): etapa final explicita de handoff em private_label e exportacao"
```

---

# Parte 4 — Validação end-to-end

### Task 4.1: Rodar rehearsal completo e comparar com baseline

**Files:** nenhum código — só execução + análise.

**Baseline (2026-04-20T17-53-34):**
- A1 FAIL (bot_score 2): contradição amostras, max_turns
- A2 FAIL (bot_score 6): ignorou pergunta sobre prazo 3x
- A3 FAIL (bot_score 3): contradições sobre desconto, loop encaminhar
- A4 FAIL (bot_score 3): encaminhou sem permissão
- A5: ReadTimeout (incompleto)

**KRs desta validação:**
- Pelo menos **4/5** arquétipos com **todas** as hard_checks passando.
- bot_score médio (soft_check.bot_score_1_10) ≥ **6/10**.
- Zero contradições sobre amostras no A1 (confirmar lendo transcript).
- A2 responde "prazo de producao" no primeiro turno em que é perguntado.
- A3 cobre as duas intenções (atacado + private_label) em `stages_visited`.
- A4 não chama `encaminhar_humano` a menos que o cliente peça explicitamente.
- A5 completa sem ReadTimeout (se estourar, retry manualmente 1x antes de dar por falha — o fix definitivo é a Task 5.1).

- [ ] **Step 1: Garantir pré-requisitos do ambiente**

- Backend dev rodando com `--reload` e `.env.local` (PID novo, logs limpos)
- `REHEARSAL_MODE=1` e `META_PHONE_NUMBER_ID` setados em `.env.local`
- `GEMINI_API_KEY` válida
- Redis dev acessível via `127.0.0.1:{porta publicada}`
- Supabase `agent_profiles.model` já atualizado pela Task 2.1

- [ ] **Step 2: Rodar os 5 arquétipos**

```bash
cd backend && python -m scripts.rehearsal_runner 2>&1 | tee /tmp/rehearsal-run-$(date +%Y%m%d-%H%M%S).log
```

Tempo esperado: 10–20 minutos (2–4 min por arquétipo).

- [ ] **Step 3: Coletar artefatos**

Resultados em `docs/superpowers/plans/pilot/rehearsal-runs/<timestamp>/`. Para cada A1–A5 conferir:

```bash
# Via Read tool:
# docs/superpowers/plans/pilot/rehearsal-runs/<timestamp>/A<N>-<slug>/verification.json
```

- [ ] **Step 4: Montar tabela comparativa**

Crie `docs/superpowers/plans/pilot/rehearsal-runs/<timestamp>/ANALISE.md` com as colunas:

```markdown
| Arquetipo | Hard (baseline) | Hard (agora) | Bot (baseline) | Bot (agora) | Nota do judge |
|-----------|-----------------|--------------|----------------|-------------|---------------|
| A1        | FAIL            | ...          | 2              | ...         | ...           |
| A2        | FAIL            | ...          | 6              | ...         | ...           |
| A3        | FAIL            | ...          | 3              | ...         | ...           |
| A4        | FAIL            | ...          | 3              | ...         | ...           |
| A5        | ABORT           | ...          | —              | ...         | ...           |
```

- [ ] **Step 5: Decisão**

- Se **4+ passed e bot médio ≥ 6**: merge para master + commit em `docs/superpowers/plans/pilot/summary.md` registrando "v1 de correções validado".
- Se **< 4 passed ou bot < 6**: listar falhas restantes como novas tasks e **não fazer push**. Investigar com `superpowers:systematic-debugging` (Phase 1 — root cause).

- [ ] **Step 6: Commit da análise**

```bash
git add docs/superpowers/plans/pilot/rehearsal-runs/ docs/superpowers/plans/pilot/summary.md
git commit -m "docs(rehearsal): analise pos-correcoes v1 — comparativo com baseline 2026-04-20T17-53-34"
```

---

# Parte 5 — Nice-to-have (deferred após Parte 4)

Estas tasks não bloqueiam o merge. Execute se sobrar tempo ou quando o ReadTimeout do A5 voltar a incomodar.

### Task 5.1: Retry com backoff no rehearsal_runner para ReadTimeout

**Files:**
- Modify: `backend/scripts/rehearsal_runner.py:104` (função `_send_user_message`)

- [ ] **Step 1: Envolver o POST em retry exponencial**

```python
async def _send_user_message(client: httpx.AsyncClient, phone: str, text: str) -> None:
    payload = _build_meta_payload(phone, text)
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            r = await client.post(f"{DEV_BACKEND_URL}/webhook/meta", json=payload, timeout=60)
            if r.status_code >= 400:
                log.warning(f"Webhook POST retornou {r.status_code}: {r.text[:200]}")
            return
        except (httpx.ReadTimeout, httpx.ConnectError) as e:
            last_exc = e
            wait = 2 ** attempt
            log.warning(f"_send_user_message tentativa {attempt+1} falhou ({type(e).__name__}); aguardando {wait}s")
            await asyncio.sleep(wait)
    raise last_exc or RuntimeError("_send_user_message esgotou retries")
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/rehearsal_runner.py
git commit -m "feat(rehearsal): retry exponencial no envio de mensagem (resolve ReadTimeout esporadico)"
```

### Task 5.2: Migração `google-generativeai` → `google-genai`

Deferir para spec separado quando decidirmos rodar a Valéria em Gemini via OpenRouter (já há plano `2026-04-20-valeria-rehearsal-automatico.md` tocando nessa direção). Não fazer aqui.

---

## Self-Review

- **Cobertura do diagnóstico**
  - Stage nunca emitido → Task 1.2 ✅
  - Tool name não é detectável → Task 1.1 ✅
  - Verifier não testa o formato novo → Task 1.4 ✅
  - Frontend leaking prefix → Task 1.5 ✅
  - Modelo inválido no agent_profile → Task 2.1 ✅
  - Amostras (A1) → Task 3.1 ✅
  - Ignorar pergunta direta (A2/A4) → Task 3.2 ✅
  - `encaminhar_humano` como escape (A3/A4) → Task 3.3 ✅
  - Atacado não fecha (A1 max_turns) → Task 3.4 ✅
  - Handoff private_label/exportacao (A2/A5) → Task 3.5 ✅
  - ReadTimeout A5 → Task 5.1 ✅
  - Validação → Task 4.1 ✅

- **Consistência de tipos**: formato `[tool:<nome>]` e `[event:stage]` é o mesmo em `tools.py`, `orchestrator.py`, verifier test e frontend strip. `has_tool_call` usa `if name in content.lower()` — prefix funciona.

- **Ordem de execução**: Parte 1 é pré-requisito para Parte 4 (sem instrumentação os hard-checks continuam falhando mesmo com prompts perfeitos). Parte 2 é rápida (SQL). Parte 3 pode rodar em paralelo com Parte 1 porque não há conflitos de arquivo.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-20-valeria-correcoes-pos-rehearsal-v1.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch um sub-agente fresco por task, revisão entre tasks, iteração rápida.

**2. Inline Execution** — executar aqui mesmo com `superpowers:executing-plans`, batch com checkpoints para revisão.

**Qual abordagem?**
