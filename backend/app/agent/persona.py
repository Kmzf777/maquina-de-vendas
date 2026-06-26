"""Eixo 1 — Resolução dinâmica de persona (inbound vs outbound).

Substitui o pin estático `conversation.agent_profile_id` por uma decisão recomputada
a cada turno a partir do histórico. Regra:

  persona = valeria_outbound  SE existe um disparo FRIO (cold_reactivation) ainda
                              não respondido pelo lead E nenhum humano interveio;
          = valeria_inbound   caso contrário (lead respondeu, disparo quente de LP,
                              inbound orgânico, ou intervenção humana).

A persona outbound governa exclusivamente o 1º turno reativo ao cold-open; assim que
há resposta real, o controle passa para a inbound (mais conversacional).

Módulo de núcleo puro: opera sobre listas de dicts de mensagens, sem I/O — testável
isoladamente. A busca das mensagens fica no chamador (buffer/processor).
"""
from __future__ import annotations

from app.templates.intent import COLD_REACTIVATION

INBOUND = "valeria_inbound"
OUTBOUND = "valeria_outbound"

_DISPATCH_SENDERS = ("broadcast", "followup")


def persona_signals(messages: list[dict]) -> tuple[bool, bool]:
    """Extrai (has_human_message, cold_open_unanswered) do histórico da conversa.

    - has_human_message: qualquer mensagem com sent_by == 'human' (vendedor interveio).
    - cold_open_unanswered: existe um disparo cold_reactivation E o lead ainda NÃO
      enviou nenhuma mensagem (role == 'user').
    """
    has_human = any((m.get("sent_by") == "human") for m in messages)
    has_user = any(m.get("role") == "user" for m in messages)
    has_cold_dispatch = any(
        m.get("role") == "assistant"
        and m.get("sent_by") in _DISPATCH_SENDERS
        and (((m.get("metadata") or {}).get("dispatch") or {}).get("intent") == COLD_REACTIVATION)
        for m in messages
    )
    return has_human, (has_cold_dispatch and not has_user)


def decide_persona(*, has_human_message: bool, cold_open_unanswered: bool) -> str:
    """Núcleo puro da decisão de persona."""
    if cold_open_unanswered and not has_human_message:
        return OUTBOUND
    return INBOUND


def resolve_persona_prompt_key(messages: list[dict]) -> str:
    """Resolve o prompt_key da persona a partir do histórico da conversa."""
    has_human, cold_open_unanswered = persona_signals(messages)
    return decide_persona(
        has_human_message=has_human, cold_open_unanswered=cold_open_unanswered
    )
