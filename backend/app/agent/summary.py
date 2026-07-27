import logging
from typing import Any

from app.agent.gemini_client import generate, user_content

logger = logging.getLogger(__name__)


def _track_summary_usage(result: Any, lead: dict[str, Any], model: str, call_type: str) -> None:
    """Registra o custo da chamada de resumo em token_usage. Fail-soft: nunca levanta —
    contabilidade jamais pode derrubar o handoff. Só grava com lead_id e usage presentes.

    Lê o usage_metadata NATIVO do GenerateResult; completion_tokens = saída FATURADA
    (candidates + thoughts, via billed_output_tokens) — colunas do banco inalteradas."""
    try:
        um = getattr(result, "usage_metadata", None)
        lead_id = lead.get("id")
        if not um or not lead_id:
            return
        from app.agent.token_tracker import track_token_usage
        track_token_usage(
            lead_id=lead_id,
            stage=lead.get("stage") or "",
            model=model,
            call_type=call_type,
            prompt_tokens=um.prompt_token_count or 0,
            completion_tokens=um.billed_output_tokens or 0,
            cached_tokens=um.cached_content_token_count or 0,
            reasoning_tokens=um.thoughts_token_count or 0,
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


# Tetos do briefing determinístico. O dossiê vai por WhatsApp e precisa ser lido no
# celular do vendedor — histórico inteiro colado vira parede de texto ignorada.
_FALLBACK_MAX_MSGS = 6
_FALLBACK_MAX_CHARS = 280


def _fallback_briefing(
    history: list[dict[str, Any]],
    lead: dict[str, Any],
    motivo: str = "",
    handoff_at: str = "",
) -> str:
    """Dossiê DETERMINÍSTICO para quando o resumo por LLM não sai.

    Auditoria 27/07: durante o apagão de `gemini-2.5-flash` (22/07 17:48 em diante),
    63 de 64 dossiês chegaram ao João como "*Erro ao gerar resumo automático.*" + segmento
    e nome. Era um desperdício: o sistema tinha em mãos o histórico completo, o motivo do
    handoff e o timestamp, e jogava tudo fora porque o LLM estava fora.

    Este briefing usa exatamente esses dados. É função PURA (sem rede, sem I/O) para poder
    ser testada e para nunca ter como falhar no ramo em que TUDO já falhou.

    Só mensagens do LEAD entram no trecho verbatim: o que o vendedor precisa é o que o
    cliente pediu. Reproduzir falas da Valéria num dossiê que existe porque a Valéria
    falhou é ruído.
    """
    nome = lead.get("name") or "Não informado"
    empresa = lead.get("company") or "Não informado"
    segmento = lead.get("stage") or "Não informado"

    inbounds = [
        (m.get("content") or "").strip()
        for m in (history or [])
        if m.get("role") == "user" and (m.get("content") or "").strip()
    ]
    recortes = []
    for texto in inbounds[-_FALLBACK_MAX_MSGS:]:
        if len(texto) > _FALLBACK_MAX_CHARS:
            texto = texto[:_FALLBACK_MAX_CHARS] + "..."
        recortes.append(f"- {texto}")

    bloco_msgs = (
        "\n".join(recortes) if recortes else "- (nenhuma mensagem de texto do lead no histórico)"
    )

    return (
        f"## NOVO LEAD QUALIFICADO PELA VALÉRIA\n"
        f"**Data/Hora:** {handoff_at or 'Não informado'}\n\n"
        f"* **Nome do Lead:** {nome}\n"
        f"* **Empresa:** {empresa}\n"
        f"* **Interesse Principal:** {segmento}\n"
        f"* **Motivo do encaminhamento:** {motivo or 'Não informado'}\n\n"
        f"**Triagem automática indisponível** — a IA não conseguiu resumir esta conversa. "
        f"Abaixo, o que o lead escreveu (últimas {len(recortes) or 0} mensagens), na íntegra:\n\n"
        f"{bloco_msgs}"
    )


async def generate_qualification_summary(
    history: list[dict[str, Any]],
    lead: dict[str, Any],
    model: str,
    motivo: str = "",
    handoff_at: str = "",
) -> str:
    """Gera resumo estruturado da qualificação a partir do histórico da conversa.

    Args:
        history: lista de mensagens com campos role, content (de conversations.service.get_history)
        lead: dict do lead com campos name, stage, company
        model: nome do modelo a usar (via app.agent.gemini_client.generate — núcleo nativo)
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
    # desliga o thinking (knob nativo thinking_off → ThinkingConfig(thinking_budget=0)) e dá
    # folga de tokens à saída (mesmo MAX_OUTPUT_TOKENS do orchestrator).
    from app.agent.orchestrator import MAX_OUTPUT_TOKENS

    try:
        result = await generate(
            model,
            contents=[user_content(context)],
            system_instruction=_SUMMARY_SYSTEM_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
            thinking_off=True,
        )
        # Contabiliza o custo desta chamada — antes era off-book (nunca gravava token_usage),
        # mascarando o gasto real e cegando o budget_guard. call_type próprio p/ auditoria.
        _track_summary_usage(result, lead, model, "qualification_summary")
        if not result.text:
            # Antes: "*Resumo indisponível (resposta vazia do modelo).*" — o vendedor
            # recebia um aviso de erro em vez do que o lead escreveu.
            return _fallback_briefing(history, lead, motivo, handoff_at)
        return result.text
    except Exception as exc:
        logger.error("generate_qualification_summary: falha na chamada LLM: %s", exc, exc_info=True)
        # Antes: "*Erro ao gerar resumo automático.*" + segmento/nome — foi o que 63 de 64
        # dossiês da janela do apagão entregaram ao João (auditoria 27/07).
        return _fallback_briefing(history, lead, motivo, handoff_at)
