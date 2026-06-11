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
