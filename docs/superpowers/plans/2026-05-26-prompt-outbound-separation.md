# Separação system/user no Prompt Outbound da Valéria — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar as regras de negócio estáticas (system) do contexto dinâmico de campanha (user) no fluxo `valeria_outbound`, eliminando o monólito que mistura estado transitório com instruções imutáveis.

**Architecture:** O `SECRETARIA_PROMPT` outbound perde o bloco "CONTEXTO DESTA ABORDAGEM" (linhas 2–22). Um novo `context.py` expõe `build_outbound_first_turn_context` que monta o bloco dinâmico. O `orchestrator.run_agent` injeta esse bloco como mensagem `user` extra apenas quando `prompt_key == "valeria_outbound"`, `history` está vazio e `lead_context["campaign_message"]` existe.

**Tech Stack:** Python 3.11, pytest, pytest-asyncio, unittest.mock, OpenAI Chat Completions API (`chat.completions.create`)

---

## Mapa de Arquivos

| Arquivo | Ação | Responsabilidade |
|---------|------|-----------------|
| `backend/app/agent/prompts/valeria_outbound/context.py` | Criar | Montar o bloco de contexto dinâmico de campanha |
| `backend/app/agent/prompts/valeria_outbound/secretaria.py` | Modificar | Remover linhas 2–22 (bloco transitório) |
| `backend/app/agent/orchestrator.py` | Modificar | Injetar contexto como primeiro `user` message no turno 1 do fluxo outbound |
| `backend/tests/test_outbound_prompt_separation.py` | Criar | Testes unitários para as 3 mudanças acima |

---

## Task 1: Criar `context.py` com `build_outbound_first_turn_context`

**Files:**
- Create: `backend/app/agent/prompts/valeria_outbound/context.py`
- Test: `backend/tests/test_outbound_prompt_separation.py`

- [ ] **Step 1: Criar o arquivo de teste com os dois casos do context builder**

Crie `backend/tests/test_outbound_prompt_separation.py` com o seguinte conteúdo:

```python
import pytest


# ---------------------------------------------------------------------------
# Task 1 — build_outbound_first_turn_context
# ---------------------------------------------------------------------------

def test_context_builder_com_nome_e_campanha():
    """Deve incluir campaign_message, nome do lead e aviso de que está respondendo."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Ola, aqui e a Valeria da Cafe Canastra.",
        lead_name="Joao",
    )

    assert "Ola, aqui e a Valeria da Cafe Canastra." in result
    assert "O lead se chama Joao" in result
    assert "O lead está respondendo" in result


def test_context_builder_sem_nome():
    """Sem lead_name, não deve incluir linha de nome mas deve manter o restante."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Template da campanha.",
        lead_name=None,
    )

    assert "O lead se chama" not in result
    assert "Template da campanha." in result
    assert "O lead está respondendo" in result
```

- [ ] **Step 2: Executar o teste e confirmar que falha (módulo não existe)**

```
cd backend && python -m pytest tests/test_outbound_prompt_separation.py::test_context_builder_com_nome_e_campanha tests/test_outbound_prompt_separation.py::test_context_builder_sem_nome -v
```

Saída esperada: `FAILED` / `ModuleNotFoundError` para `valeria_outbound.context`.

- [ ] **Step 3: Criar `context.py`**

Crie `backend/app/agent/prompts/valeria_outbound/context.py`:

```python
def build_outbound_first_turn_context(campaign_message: str, lead_name: str | None) -> str:
    name_line = f"O lead se chama {lead_name}." if lead_name else ""
    return (
        f"Contexto desta abordagem outbound:\n\n"
        f"Mensagem enviada na campanha:\n---\n{campaign_message}\n---\n\n"
        f"{name_line}\n"
        f"O lead está respondendo a essa mensagem agora."
    ).strip()
```

- [ ] **Step 4: Executar os testes e confirmar PASS**

```
cd backend && python -m pytest tests/test_outbound_prompt_separation.py::test_context_builder_com_nome_e_campanha tests/test_outbound_prompt_separation.py::test_context_builder_sem_nome -v
```

Saída esperada: `2 passed`.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/prompts/valeria_outbound/context.py backend/tests/test_outbound_prompt_separation.py
git commit -m "feat(prompt): context builder para primeiro turno outbound"
```

---

## Task 2: Limpar `secretaria.py` outbound — remover bloco transitório

**Files:**
- Modify: `backend/app/agent/prompts/valeria_outbound/secretaria.py`
- Test: `backend/tests/test_outbound_prompt_separation.py` (adicionar teste)

- [ ] **Step 1: Adicionar teste de regressão ao arquivo de teste existente**

Acrescente ao final de `backend/tests/test_outbound_prompt_separation.py`:

```python
# ---------------------------------------------------------------------------
# Task 2 — secretaria.py outbound não contém mais conteúdo transitório
# ---------------------------------------------------------------------------

def test_secretaria_outbound_sem_bloco_transitorio():
    """SECRETARIA_PROMPT outbound não deve mais conter o bloco 'CONTEXTO DESTA ABORDAGEM'."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "CONTEXTO DESTA ABORDAGEM" not in SECRETARIA_PROMPT
    assert "Voce iniciou este contato via campanha de WhatsApp. A mensagem que voce enviou foi" not in SECRETARIA_PROMPT
    assert "O lead esta RESPONDENDO a essa mensagem agora" not in SECRETARIA_PROMPT


def test_secretaria_outbound_mantem_regras_de_negocio():
    """As regras de negócio e o funil devem permanecer no prompt."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "CONTEXTO OUTBOUND" in SECRETARIA_PROMPT
    assert "POSTURA OUTBOUND" in SECRETARIA_PROMPT
    assert "REGRAS CRITICAS DE SEGURANCA" in SECRETARIA_PROMPT
    assert "ETAPA 1" in SECRETARIA_PROMPT
    assert "ETAPA 4" in SECRETARIA_PROMPT
```

- [ ] **Step 2: Executar o teste e confirmar que falha**

```
cd backend && python -m pytest tests/test_outbound_prompt_separation.py::test_secretaria_outbound_sem_bloco_transitorio -v
```

Saída esperada: `FAILED` — o prompt ainda contém o bloco transitório.

- [ ] **Step 3: Remover as linhas 2–22 de `secretaria.py`**

Abra `backend/app/agent/prompts/valeria_outbound/secretaria.py`.

O conteúdo atual começa assim:
```
SECRETARIA_PROMPT = """
## CONTEXTO DESTA ABORDAGEM — LEIA ANTES DE QUALQUER COISA
...
(onde [NOME DO LEAD] foi substituido pelo nome real no envio)
---

O lead esta RESPONDENDO a essa mensagem agora. Isso significa:
- Voce JA se apresentou como Valeria da Cafe Canastra
- NAO se apresente de novo do zero — isso parece automacao sem memoria
- Contextualize a partir dessa abertura de forma natural
- O lead SABE quem e voce — sua resposta deve ser uma continuacao, nao um reinicio

---

## CONTEXTO OUTBOUND — ABORDAGEM ATIVA
```

Após a edição, o arquivo deve começar exatamente assim (sem linha em branco antes de `## CONTEXTO OUTBOUND`):

```python
SECRETARIA_PROMPT = """
## CONTEXTO OUTBOUND — ABORDAGEM ATIVA
```

Todo o restante do arquivo (linhas 24–199 do original) permanece inalterado.

- [ ] **Step 4: Executar ambos os testes da Task 2 e confirmar PASS**

```
cd backend && python -m pytest tests/test_outbound_prompt_separation.py::test_secretaria_outbound_sem_bloco_transitorio tests/test_outbound_prompt_separation.py::test_secretaria_outbound_mantem_regras_de_negocio -v
```

Saída esperada: `2 passed`.

- [ ] **Step 5: Confirmar que a suite completa existente não quebrou**

```
cd backend && python -m pytest tests/ -x -q
```

Saída esperada: todos os testes existentes passam.

- [ ] **Step 6: Commit**

```
git add backend/app/agent/prompts/valeria_outbound/secretaria.py backend/tests/test_outbound_prompt_separation.py
git commit -m "refactor(prompt): remover bloco transitorio do secretaria outbound"
```

---

## Task 3: Injetar contexto dinâmico no `orchestrator.run_agent`

**Files:**
- Modify: `backend/app/agent/orchestrator.py` (região das linhas 135–139)
- Test: `backend/tests/test_outbound_prompt_separation.py` (adicionar testes)

- [ ] **Step 1: Adicionar os 4 testes de injeção ao arquivo de teste existente**

Acrescente ao final de `backend/tests/test_outbound_prompt_separation.py`:

```python
# ---------------------------------------------------------------------------
# Task 3 — orchestrator injeta contexto outbound como primeiro user message
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, patch, MagicMock


def _mock_openai_response(text: str = "resposta da ia"):
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = text
    resp = MagicMock()
    resp.choices = [MagicMock(message=msg)]
    resp.usage = None
    return resp


def _capture_messages(create_mock):
    """Retorna a lista de messages passada na primeira chamada ao create."""
    call_args = create_mock.call_args
    return call_args.kwargs.get("messages") or call_args.args[0]


@pytest.mark.asyncio
async def test_outbound_primeiro_turno_injeta_contexto_campanha():
    """No turno 1 outbound, messages[1] deve ser o contexto da campanha (role user)."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-1",
        "stage": "secretaria",
        "leads": {"id": "lead-out-1", "name": "Maria", "phone": "5511900000001"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria."}

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-out-1", "name": "Maria", "phone": "5511900000001", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "sim", lead_context=lead_context, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    # messages[0] = system, messages[1] = contexto campanha, messages[2] = user_text
    assert len(messages) == 3
    assert messages[1]["role"] == "user"
    assert "Ola, aqui e a Valeria." in messages[1]["content"]
    assert "O lead está respondendo" in messages[1]["content"]
    assert messages[2] == {"role": "user", "content": "sim"}


@pytest.mark.asyncio
async def test_outbound_segundo_turno_nao_injeta_contexto():
    """Com histórico existente (turno 2+), não deve injetar o contexto de campanha."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-2",
        "stage": "secretaria",
        "leads": {"id": "lead-out-2", "phone": "5511900000002"},
    }
    lead_context = {"campaign_message": "Ola, aqui e a Valeria."}
    existing_history = [
        {"role": "user", "content": "sim"},
        {"role": "assistant", "content": "Que bom confirmar."},
    ]

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-out-2", "phone": "5511900000002", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=existing_history), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "quero saber mais", lead_context=lead_context, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    # system + 2 history + user_text = 4 mensagens; nenhum role extra de contexto
    assert len(messages) == 4
    roles = [m["role"] for m in messages]
    assert roles == ["system", "user", "assistant", "user"]


@pytest.mark.asyncio
async def test_inbound_nao_injeta_contexto_de_campanha():
    """Fluxo inbound (valeria_inbound) nunca deve injetar o contexto de campanha."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-in-1",
        "stage": "secretaria",
        "leads": {"id": "lead-in-1", "phone": "5511900000003"},
    }
    # Mesmo passando campaign_message, inbound não deve injetar
    lead_context = {"campaign_message": "Mensagem que nao deveria aparecer."}

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-in-1", "phone": "5511900000003", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_inbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        await run_agent(conversation, "oi", lead_context=lead_context, agent_profile_id="profile-in")

    messages = _capture_messages(create_mock)
    assert len(messages) == 2  # system + user_text
    assert all("Mensagem que nao deveria aparecer" not in str(m) for m in messages)


@pytest.mark.asyncio
async def test_outbound_sem_campaign_message_nao_injeta():
    """Se campaign_message estiver ausente em lead_context, não deve injetar nada extra."""
    from app.agent.orchestrator import run_agent

    conversation = {
        "id": "conv-out-3",
        "stage": "secretaria",
        "leads": {"id": "lead-out-3", "phone": "5511900000004"},
    }

    create_mock = AsyncMock(return_value=_mock_openai_response())

    with patch("app.agent.orchestrator.get_lead", return_value={
            "id": "lead-out-3", "phone": "5511900000004", "ai_enabled": True,
         }), \
         patch("app.agent.orchestrator.get_history", return_value=[]), \
         patch("app.agent.orchestrator.get_agent_profile", return_value={"prompt_key": "valeria_outbound", "model": "gpt-4.1-mini"}), \
         patch("app.agent.orchestrator._get_client") as mock_client:

        mock_client.return_value.chat.completions.create = create_mock
        # lead_context sem campaign_message
        await run_agent(conversation, "oi", lead_context={"name": "Carlos"}, agent_profile_id="profile-out")

    messages = _capture_messages(create_mock)
    assert len(messages) == 2  # system + user_text apenas
```

- [ ] **Step 2: Executar os 4 testes e confirmar que FALHAM**

```
cd backend && python -m pytest tests/test_outbound_prompt_separation.py::test_outbound_primeiro_turno_injeta_contexto_campanha tests/test_outbound_prompt_separation.py::test_outbound_segundo_turno_nao_injeta_contexto tests/test_outbound_prompt_separation.py::test_inbound_nao_injeta_contexto_de_campanha tests/test_outbound_prompt_separation.py::test_outbound_sem_campaign_message_nao_injeta -v
```

Saída esperada: os testes de injeção falham (`AssertionError: assert 2 == 3`). Os testes de "não injetar" podem passar — isso é aceitável.

- [ ] **Step 3: Implementar a injeção condicional em `orchestrator.py`**

Localize o bloco de montagem de `messages` em `backend/app/agent/orchestrator.py` (linhas 135–139 no original):

```python
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})
```

Substitua por:

```python
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    is_outbound = prompt_key == "valeria_outbound"
    is_first_turn = len(history) == 0
    campaign_message = (lead_context or {}).get("campaign_message")

    if is_outbound and is_first_turn and campaign_message:
        from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
        ctx = build_outbound_first_turn_context(campaign_message, lead.get("name"))
        messages.append({"role": "user", "content": ctx})

    messages.append({"role": "user", "content": user_text})
```

- [ ] **Step 4: Executar os 4 testes e confirmar PASS**

```
cd backend && python -m pytest tests/test_outbound_prompt_separation.py::test_outbound_primeiro_turno_injeta_contexto_campanha tests/test_outbound_prompt_separation.py::test_outbound_segundo_turno_nao_injeta_contexto tests/test_outbound_prompt_separation.py::test_inbound_nao_injeta_contexto_de_campanha tests/test_outbound_prompt_separation.py::test_outbound_sem_campaign_message_nao_injeta -v
```

Saída esperada: `4 passed`.

- [ ] **Step 5: Rodar a suite completa e garantir zero regressões**

```
cd backend && python -m pytest tests/ -x -q
```

Saída esperada: todos os testes passam.

- [ ] **Step 6: Commit final**

```
git add backend/app/agent/orchestrator.py backend/tests/test_outbound_prompt_separation.py
git commit -m "feat(orchestrator): injetar contexto de campanha outbound no primeiro turno"
```

---

## Checklist de Verificação Final

Após os 3 tasks concluídos, confirme:

- [ ] `python -m pytest tests/test_outbound_prompt_separation.py -v` → todos os 8 testes passam
- [ ] `python -m pytest tests/ -q` → zero regressões na suite completa
- [ ] `SECRETARIA_PROMPT` outbound não contém "CONTEXTO DESTA ABORDAGEM"
- [ ] `context.py` existe em `valeria_outbound/`
- [ ] Fluxo inbound não é afetado (testado em `test_inbound_nao_injeta_contexto_de_campanha`)
- [ ] `campaign_message` ausente não quebra o fluxo (testado em `test_outbound_sem_campaign_message_nao_injeta`)
