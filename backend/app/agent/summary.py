import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """Você é um assistente que gera resumos objetivos de conversas de qualificação de leads.

Analise o histórico e gere um resumo em markdown com EXATAMENTE este formato (sem alterar os cabeçalhos):

## Resumo da Qualificação

**Interesse:** [categoria: atacado / private_label / exportacao / consumo / não identificado]
**Nome:** [nome informado ou "não informado"]
**Empresa:** [empresa ou "não informada"]
**CNPJ:** [CNPJ ou "não informado"]

**Necessidades identificadas:**
- [ponto 1 — máximo 3 pontos]

**Observações para o vendedor:**
- [ponto 1 — máximo 3 pontos]

**Status:** [qualificado e encaminhado / encaminhado por circuit breaker / opt-out registrado]

Seja direto. Inclua apenas informações explicitamente mencionadas na conversa."""


async def generate_qualification_summary(
    history: list[dict[str, Any]],
    lead: dict[str, Any],
    client: AsyncOpenAI,
    model: str,
) -> str:
    """Gera resumo estruturado da qualificação a partir do histórico da conversa.

    Args:
        history: lista de mensagens com campos role, content (de conversations.service.get_history)
        lead: dict do lead com campos name, stage, company
        client: instância AsyncOpenAI (OpenAI ou Gemini-compat)
        model: nome do modelo a usar

    Returns:
        Resumo em markdown pronto para exibição.
    """
    if not history:
        return "## Resumo da Qualificação\n\n*Nenhuma mensagem encontrada no histórico.*"

    lines = []
    for m in history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            label = "Lead" if role == "user" else "Valéria"
            lines.append(f"[{label}]: {content}")

    if not lines:
        return "## Resumo da Qualificação\n\n*Histórico sem mensagens relevantes.*"

    lead_name = lead.get("name") or "não informado"
    lead_stage = lead.get("stage") or "não identificado"
    lead_company = lead.get("company") or "não informada"
    history_text = "\n".join(lines)
    context = (
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
            max_tokens=600,
            temperature=0.2,
        )
        if not response.choices:
            return "## Resumo da Qualificação\n\n*Resumo indisponível (resposta vazia do modelo).*"
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("generate_qualification_summary: falha na chamada LLM: %s", exc, exc_info=True)
        return f"## Resumo da Qualificação\n\n*Erro ao gerar resumo automático.*\n\nSegmento: {lead_stage} | Nome: {lead_name}"
