import logging
from typing import Any

from app.agent.gemini_native import GeminiNativeClient

logger = logging.getLogger(__name__)


def _track_summary_usage(response: Any, lead: dict[str, Any], model: str, call_type: str) -> None:
    """Registra o custo da chamada de resumo em token_usage. Fail-soft: nunca levanta —
    contabilidade jamais pode derrubar o handoff. Só grava com lead_id e usage presentes."""
    try:
        usage = getattr(response, "usage", None)
        lead_id = lead.get("id")
        if not usage or not lead_id:
            return
        from app.agent.token_tracker import track_token_usage
        track_token_usage(
            lead_id=lead_id,
            stage=lead.get("stage") or "",
            model=model,
            call_type=call_type,
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            cached_tokens=getattr(usage, "cached_tokens", 0) or 0,
            reasoning_tokens=getattr(usage, "reasoning_tokens", 0) or 0,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        logger.warning("summary: falha ao registrar token_usage (ignorado): %s", exc)

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
    client: GeminiNativeClient,
    model: str,
    motivo: str = "",
    handoff_at: str = "",
) -> str:
    """Gera resumo estruturado da qualificação a partir do histórico da conversa.

    Args:
        history: lista de mensagens com campos role, content (de conversations.service.get_history)
        lead: dict do lead com campos name, stage, company
        client: instância GeminiNativeClient (SDK nativo google-genai)
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

    # gemini-2.5-flash conta os tokens de "thinking" no MESMO budget de saída. Com teto baixo
    # (era 700) o modelo gasta quase tudo pensando e devolve só o cabeçalho + início da data,
    # cortando o resumo (ex.: lead 5545999367983 → "**Data/Hora:** 26/06/"). Espelha o orchestrator:
    # desliga o thinking nos modelos 2.5 (reasoning_effort="none") e dá folga de tokens à saída.
    from app.agent.orchestrator import MAX_OUTPUT_TOKENS, _gemini_thinking_off

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
            **_gemini_thinking_off(model),
        )
        # Contabiliza o custo desta chamada — antes era off-book (nunca gravava token_usage),
        # mascarando o gasto real e cegando o budget_guard. call_type próprio p/ auditoria.
        _track_summary_usage(response, lead, model, "qualification_summary")
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
