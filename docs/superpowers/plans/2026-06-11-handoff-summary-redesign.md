# Handoff Summary Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir o formato do resumo de qualificação gerado no handoff pelo template "NOVO LEAD QUALIFICADO PELA VALÉRIA" com 8 campos enriquecidos (aquecimento, dor, orçamento, tom, recomendação).

**Architecture:** Dois arquivos alterados no backend. `summary.py` recebe novo prompt + dois parâmetros opcionais (`motivo`, `handoff_at`). `tools.py` passa esses valores na chamada dentro de `encaminhar_humano`. Sem mudanças de banco, frontend ou entrega.

**Tech Stack:** Python 3.11, pytest, unittest.mock, AsyncOpenAI (Gemini-compat).

**Nota pré-existente:** O teste `test_enviar_fotos_nao_reenvia_se_ja_enviado` já falha antes desta feature (AttributeError em mock). Não é responsabilidade desta tarefa corrigi-lo.

---

### Task 1: Testes para `generate_qualification_summary` (novo formato)

**Files:**
- Create: `backend/tests/test_agent_summary.py`

- [ ] **Step 1: Criar o arquivo de testes**

```python
# backend/tests/test_agent_summary.py
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_empty_history_returns_new_header():
    """Histórico vazio deve retornar mensagem com o novo cabeçalho, sem chamar LLM."""
    from app.agent.summary import generate_qualification_summary

    mock_client = MagicMock()
    result = await generate_qualification_summary(
        history=[],
        lead={"name": "Ana", "stage": "atacado"},
        client=mock_client,
        model="gemini-2.5-flash",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    mock_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_full_history_llm_receives_motivo_and_handoff_at():
    """Com histórico, motivo e handoff_at devem aparecer no contexto enviado ao LLM."""
    from app.agent.summary import generate_qualification_summary

    mock_choice = MagicMock()
    mock_choice.message.content = (
        "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n"
        "**Data/Hora:** 11/06/2026 14:30\n\n"
        "* **Nome do Lead:** João Silva\n"
        "* **Interesse Principal:** Atacado\n"
        "* **Nível de Aquecimento:** Alto — lead com intenção de compra\n"
        "* **Cenário Atual / Dor:** Fornecedor atual sem qualidade\n"
        "* **Expectativa de Volume/Orçamento:** R$300\n"
        "* **Tom da Conversa:** Objetivo e direto\n"
        "* **Recomendação de Abordagem para o João:** Confirmar produto e fechar\n"
    )
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    history = [
        {"role": "user", "content": "quero café para minha cafeteria"},
        {"role": "assistant", "content": "vou apresentar nossos produtos"},
    ]

    result = await generate_qualification_summary(
        history=history,
        lead={"name": "João Silva", "stage": "atacado", "company": "Cafeteria XYZ"},
        client=mock_client,
        model="gemini-2.5-flash",
        motivo="lead com intenção de compra — atacado",
        handoff_at="11/06/2026 14:30",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    user_msg = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    assert "intenção de compra" in user_msg["content"]
    assert "11/06/2026 14:30" in user_msg["content"]


@pytest.mark.asyncio
async def test_llm_empty_choices_returns_fallback_with_new_header():
    """Resposta vazia do LLM deve retornar fallback com o novo cabeçalho."""
    from app.agent.summary import generate_qualification_summary

    mock_response = MagicMock()
    mock_response.choices = []
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    history = [{"role": "user", "content": "preciso de café"}]

    result = await generate_qualification_summary(
        history=history,
        lead={"name": "Maria", "stage": "atacado"},
        client=mock_client,
        model="gemini-2.5-flash",
    )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result


@pytest.mark.asyncio
async def test_llm_exception_returns_fallback_with_new_header(caplog):
    """Exceção no LLM deve retornar fallback com o novo cabeçalho."""
    import logging
    from app.agent.summary import generate_qualification_summary

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("timeout"))

    history = [{"role": "user", "content": "quero café"}]

    with caplog.at_level(logging.ERROR, logger="app.agent.summary"):
        result = await generate_qualification_summary(
            history=history,
            lead={"name": "Carlos", "stage": "private_label"},
            client=mock_client,
            model="gemini-2.5-flash",
        )

    assert "## NOVO LEAD QUALIFICADO PELA VALÉRIA" in result
    assert any("falha na chamada LLM" in r.message for r in caplog.records)
```

- [ ] **Step 2: Rodar os testes para confirmar que falham**

```bash
cd "C:/Users/cmap211/Documents/Kelwin Projetos/maquina-de-vendas"
python -m pytest backend/tests/test_agent_summary.py -v
```

Esperado: 4 FAILs (módulo ainda retorna cabeçalho antigo ou não tem os parâmetros novos).

---

### Task 2: Atualizar `summary.py` — novo prompt + assinatura enriquecida

**Files:**
- Modify: `backend/app/agent/summary.py` (arquivo completo)

- [ ] **Step 1: Substituir o conteúdo inteiro de `summary.py`**

```python
import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """Você é um assistente especializado em briefings de vendas do Café Canastra.

Analise as informações do lead e o histórico da conversa abaixo, depois gere exatamente este bloco markdown (mantenha todos os campos — use "Não informado na triagem" quando não houver dados explícitos):

## NOVO LEAD QUALIFICADO PELA VALÉRIA
**Data/Hora:** [usar a data/hora do handoff fornecida no contexto]

* **Nome do Lead:** [nome informado ou "Não informado na triagem"]
* **Interesse Principal:** [categoria (atacado / private_label / exportacao / consumo) + descrição detalhada do que o lead quer]
* **Nível de Aquecimento:** [Alto / Médio / Baixo — seguido de justificativa objetiva baseada no histórico e no motivo do handoff]
* **Cenário Atual / Dor:** [situação atual do lead e problema que deseja resolver; se ausente, "Não informado na triagem"]
* **Expectativa de Volume/Orçamento:** [valores, volumes ou pedido mínimo mencionados; se ausente, "Não informado na triagem"]
* **Tom da Conversa:** [comportamento e atitude do lead durante o atendimento]
* **Recomendação de Abordagem para o João:** [como iniciar o contato com base no histórico e na dor identificada]

Critérios para Nível de Aquecimento:
- Alto: lead declarou intenção de compra ("quero comprar", "quero fechar", "pode mandar") ou motivo contém "intenção de compra".
- Médio: lead qualificado e engajado mas sem intenção declarada, ou motivo contém "lead qualificado".
- Baixo: circuit breaker acionado, objeção de preço sem resolução, ou lead rejeitou o modelo de negócio.

Regras obrigatórias:
- Nunca invente informações ausentes — use "Não informado na triagem".
- Cada campo em 1-3 frases diretas.
- Preserve o formato exato (asteriscos, negrito, marcadores de lista com *)."""


async def generate_qualification_summary(
    history: list[dict[str, Any]],
    lead: dict[str, Any],
    client: AsyncOpenAI,
    model: str,
    motivo: str = "",
    handoff_at: str = "",
) -> str:
    """Gera resumo estruturado da qualificação a partir do histórico da conversa.

    Args:
        history: lista de mensagens com campos role, content (de conversations.service.get_history)
        lead: dict do lead com campos name, stage, company
        client: instância AsyncOpenAI (OpenAI ou Gemini-compat)
        model: nome do modelo a usar
        motivo: motivo do handoff capturado de encaminhar_humano (opcional)
        handoff_at: data/hora do handoff formatada como "DD/MM/YYYY HH:MM" (opcional)

    Returns:
        Resumo em markdown pronto para exibição.
    """
    if not history:
        return "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n\n*Nenhuma mensagem encontrada no histórico.*"

    lines = []
    for m in history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            label = "Lead" if role == "user" else "Valéria"
            lines.append(f"[{label}]: {content}")

    if not lines:
        return "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n\n*Histórico sem mensagens relevantes.*"

    lead_name = lead.get("name") or "não informado"
    lead_stage = lead.get("stage") or "não identificado"
    lead_company = lead.get("company") or "não informada"
    history_text = "\n".join(lines)
    context = (
        f"Data/Hora do handoff: {handoff_at or 'não informada'}\n"
        f"Motivo do handoff: {motivo or 'não informado'}\n"
        f"Informações do lead — Nome: {lead_name} | Empresa: {lead_company} | Segmento identificado: {lead_stage}\n\n"
        f"Histórico da conversa:\n{history_text}"
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            max_tokens=700,
            temperature=0.2,
        )
        if not response.choices:
            return "## NOVO LEAD QUALIFICADO PELA VALÉRIA\n\n*Resumo indisponível (resposta vazia do modelo).*"
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("generate_qualification_summary: falha na chamada LLM: %s", exc, exc_info=True)
        return (
            f"## NOVO LEAD QUALIFICADO PELA VALÉRIA\n\n"
            f"*Erro ao gerar resumo automático.*\n\n"
            f"Segmento: {lead_stage} | Nome: {lead_name}"
        )
```

- [ ] **Step 2: Rodar os testes para confirmar que passam**

```bash
cd "C:/Users/cmap211/Documents/Kelwin Projetos/maquina-de-vendas"
python -m pytest backend/tests/test_agent_summary.py -v
```

Esperado: 4 PASSes.

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/cmap211/Documents/Kelwin Projetos/maquina-de-vendas"
git add backend/app/agent/summary.py backend/tests/test_agent_summary.py
git commit -m "feat(summary): novo formato NOVO LEAD QUALIFICADO PELA VALÉRIA com 8 campos"
```

---

### Task 3: Atualizar `tools.py` — passar `motivo` e `handoff_at` na chamada

**Files:**
- Modify: `backend/app/agent/tools.py` (somente o bloco try da geração de resumo, linhas ~266-291)

- [ ] **Step 1: Adicionar import de datetime no topo de `tools.py`**

Encontre a linha `import asyncio` (linha 1) e adicione `datetime` imports logo após. O topo do arquivo deve ficar:

```python
import asyncio
import base64
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
```

- [ ] **Step 2: Adicionar constante de fuso horário após os imports**

Após os imports existentes e antes de `logger = logging.getLogger(__name__)`, adicione:

```python
_TZ_BR = timezone(timedelta(hours=-3))
```

- [ ] **Step 3: Atualizar a chamada a `generate_qualification_summary` dentro de `encaminhar_humano`**

Localize o bloco `try` que chama `generate_qualification_summary` (começa em `# Gera e armazena resumo estruturado da qualificação`). Substitua apenas a chamada à função. O bloco completo deve ficar assim:

```python
        # Gera e armazena resumo estruturado da qualificação
        try:
            from app.agent.summary import generate_qualification_summary
            from app.agent.orchestrator import get_ai_client, DEFAULT_MODEL
            from app.db.supabase import get_supabase
            conv_history = get_conversation_history(conversation_id, limit=100)
            fresh_lead = get_lead(lead_id) or {}
            _model = DEFAULT_MODEL
            _handoff_at = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
            summary_text = await generate_qualification_summary(
                conv_history, fresh_lead, get_ai_client(_model), _model,
                motivo=motivo,
                handoff_at=_handoff_at,
            )
            _sb = get_supabase()
            _sb.table("lead_notes").insert({
                "lead_id": lead_id,
                "author": "qualificação-ia",
                "content": summary_text,
            }).execute()
            existing_meta = dict(fresh_lead.get("metadata") or {})
            existing_meta["handoff_summary"] = summary_text
            update_lead(lead_id, metadata=existing_meta)
            logger.info("encaminhar_humano: resumo de qualificação salvo para lead %s", lead_id)
        except Exception as _exc:
            logger.error(
                "encaminhar_humano: falha ao gerar/salvar resumo para lead %s: %s",
                lead_id, _exc, exc_info=True,
            )
```

- [ ] **Step 4: Rodar toda a suite de testes para confirmar nenhuma regressão**

```bash
cd "C:/Users/cmap211/Documents/Kelwin Projetos/maquina-de-vendas"
python -m pytest backend/tests/ -v --ignore=backend/tests/test_agent_tools.py -q
python -m pytest backend/tests/test_agent_tools.py -v -q
```

Esperado:
- `test_agent_summary.py`: 4 PASSes.
- `test_agent_tools.py`: 18 PASSes, 1 FAIL pré-existente (`test_enviar_fotos_nao_reenvia_se_ja_enviado` — AttributeError de mock pré-existente, não relacionado a esta feature).
- Demais testes: todos passando.

- [ ] **Step 5: Commit final**

```bash
cd "C:/Users/cmap211/Documents/Kelwin Projetos/maquina-de-vendas"
git add backend/app/agent/tools.py
git commit -m "feat(tools): passar motivo e handoff_at ao generate_qualification_summary"
```
