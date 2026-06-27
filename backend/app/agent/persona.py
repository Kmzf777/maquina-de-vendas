"""Eixo 1 — Resolução dinâmica de persona (inbound vs outbound).

Substitui o pin estático `conversation.agent_profile_id` por uma decisão recomputada
a cada turno a partir do histórico. Regra (sticky outbound, 2026-06-27):

  persona = valeria_outbound  SE existe um disparo FRIO (cold_reactivation) nesta
                              conversa E nenhum humano interveio — durante TODA a
                              conversa, não apenas no 1º turno;
          = valeria_inbound   caso contrário (disparo quente de LP, inbound orgânico,
                              ou intervenção humana).

Antes (até 2026-06-27) a outbound governava só o 1º turno reativo e o controle passava
para inbound assim que o lead respondia. Isso quebrava campanhas frias: um disparo feito
explicitamente sob a persona outbound era atendido pela inbound a partir da 1ª resposta.
Agora a persona outbound é "sticky": uma conversa semeada por um cold-open permanece
outbound até o fim (a persona outbound tem cobertura completa de stages no PROMPT_REGISTRY).
A intervenção humana continua sendo o escape hatch para inbound.

Módulo de núcleo puro: opera sobre listas de dicts de mensagens, sem I/O — testável
isoladamente. A busca das mensagens fica no chamador (buffer/processor).
"""
from __future__ import annotations

from app.templates.intent import COLD_REACTIVATION

INBOUND = "valeria_inbound"
OUTBOUND = "valeria_outbound"

_DISPATCH_SENDERS = ("broadcast", "followup")


def persona_signals(messages: list[dict]) -> tuple[bool, bool]:
    """Extrai (has_human_message, has_cold_dispatch) do histórico da conversa.

    - has_human_message: qualquer mensagem com sent_by == 'human' (vendedor interveio).
    - has_cold_dispatch: existe um disparo cold_reactivation nesta conversa,
      INDEPENDENTE de o lead já ter respondido (persona outbound é sticky).
    """
    has_human = any((m.get("sent_by") == "human") for m in messages)
    has_cold_dispatch = any(
        m.get("role") == "assistant"
        and m.get("sent_by") in _DISPATCH_SENDERS
        and (((m.get("metadata") or {}).get("dispatch") or {}).get("intent") == COLD_REACTIVATION)
        for m in messages
    )
    return has_human, has_cold_dispatch


def decide_persona(*, has_human_message: bool, has_cold_dispatch: bool) -> str:
    """Núcleo puro da decisão de persona (sticky outbound).

    Intervenção humana tem prioridade (escape hatch → inbound). Sem humano, um cold-open
    em qualquer ponto do histórico mantém a conversa em outbound até o fim.
    """
    if has_human_message:
        return INBOUND
    if has_cold_dispatch:
        return OUTBOUND
    return INBOUND


def resolve_persona_prompt_key(messages: list[dict]) -> str:
    """Resolve o prompt_key da persona a partir do histórico da conversa."""
    has_human, has_cold_dispatch = persona_signals(messages)
    return decide_persona(
        has_human_message=has_human, has_cold_dispatch=has_cold_dispatch
    )
