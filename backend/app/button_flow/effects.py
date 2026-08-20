"""Efeitos do bot de botões no CRM.

Toda regra de negócio aqui já existe em outro lugar — este módulo só a chama na
ordem certa. Nada é reimplementado: opt-out é o mesmo `apply_optout_side_effects`
usado pela tool do LLM e pelo endpoint manual, tag é o mesmo `add_tags_to_lead`.

Fail-soft por padrão: um erro de CRM loga e segue, porque o lead já recebeu a
resposta e não pode ficar preso. A ÚNICA exceção é o opt-out — ver `aplicar`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.agent.tools import SUPERVISOR_NAME
from app.button_flow.engine import Efeitos
from app.leads.service import (
    add_tags_to_lead,
    append_lead_observation,
    apply_optout_side_effects,
    save_message,
    update_lead,
)

logger = logging.getLogger(__name__)

# Aproximação deliberada: "3 meses" aqui é 90 dias. O lead escolheu uma faixa, não
# uma data — precisão de calendário não agrega e traria dependência de dateutil.
_DIAS_POR_MES = 30


def aplicar(efeitos: Efeitos, *, lead: dict, conversation_id: str) -> bool:
    """Aplica os efeitos da decisão. Retorna False se o fluxo NÃO deve avançar.

    Só o opt-out bloqueia: se não conseguimos gravar `opt_out=true`, avançar o nó
    encerraria o fluxo com o lead ainda elegível a disparos — exatamente o que ele
    acabou de pedir para não acontecer. O nó fica onde está e o próximo clique retenta.
    """
    lead_id = lead["id"]

    if efeitos.tags:
        try:
            add_tags_to_lead(lead_id, list(efeitos.tags))
        except Exception as exc:
            logger.warning("[BUTTON FLOW] tags %s falharam p/ lead %s: %s",
                           efeitos.tags, lead_id, exc)

    if efeitos.optout and not _aplicar_optout(lead, conversation_id):
        return False

    if efeitos.silenciar_ia:
        _silenciar_ia(lead, conversation_id)

    if efeitos.handoff:
        _aplicar_handoff(lead, conversation_id)

    if efeitos.recontato_meses:
        _agendar_recontato(lead, efeitos.recontato_meses, conversation_id)

    return True


def _aplicar_optout(lead: dict, conversation_id: str) -> bool:
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False, opt_out=True)
    except Exception as exc:
        logger.error(
            "[BUTTON FLOW] FALHA ao gravar opt-out do lead %s — fluxo NÃO avança: %s",
            lead_id, exc, exc_info=True,
        )
        return False

    apply_optout_side_effects(lead_id, lead.get("phone") or "", reason="optout")
    _anotar(lead_id, conversation_id,
            "🚫 [OPT-OUT] Lead clicou em 'Não quero mais receber' no bot de reativação.")
    return True


def _silenciar_ia(lead: dict, conversation_id: str) -> None:
    """Entrega a conversa ao vendedor sem carimbar handoff.

    Encerrar o nó só tira o BOT do caminho — no número da ValerIA o LLM assumiria em
    seguida. Aqui NÃO usamos o carimbo de handoff de propósito: ele marcaria como lead
    qualificado alguém que só escreveu texto livre duas vezes, sujando a cascata de
    Qualificados/Aceites.
    """
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao silenciar IA do lead %s: %s", lead_id, exc)
        return
    _anotar(lead_id, conversation_id,
            "🙋 [ATENDIMENTO HUMANO] Lead insistiu em texto livre no bot de reativação; "
            "IA desligada, conversa entregue ao vendedor.")


def _aplicar_handoff(lead: dict, conversation_id: str) -> None:
    """Handoff enxuto: sem resumo por LLM (não houve conversa) e sem rescue job.

    O carimbo `metadata.handoff` é o mesmo de `encaminhar_humano` — é ele que a
    cascata de Qualificados/Aceites conta, e um handoff do bot precisa aparecer lá.
    """
    lead_id = lead["id"]
    try:
        update_lead(lead_id, ai_enabled=False)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao desligar IA no handoff do lead %s: %s",
                       lead_id, exc)
    try:
        # Cópia: o metadata do lead carrega marcadores de outros fluxos (catalog_shown,
        # rastreio) que precisam sobreviver ao update, e o dict do chamador não é nosso.
        meta = dict(lead.get("metadata") or {})
        meta["handoff"] = {
            "vendedor": SUPERVISOR_NAME,
            "motivo": "bot de reativação: lead clicou em 'Quero comprar agora'",
            "at": datetime.now(timezone.utc).isoformat(),
            "origem": "button_flow",
        }
        update_lead(lead_id, metadata=meta)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao carimbar metadata.handoff do lead %s: %s",
                       lead_id, exc)
    _anotar(lead_id, conversation_id,
            f"➡️ [TRANSBORDO p/ {SUPERVISOR_NAME}] Bot de reativação: lead clicou em "
            f"'Quero comprar agora'. Nenhuma qualificação por conversa — abordar direto.")


def _agendar_recontato(lead: dict, meses: int, conversation_id: str) -> None:
    lead_id = lead["id"]
    quando = datetime.now(timezone.utc) + timedelta(days=meses * _DIAS_POR_MES)
    try:
        meta = dict(lead.get("metadata") or {})
        meta["recontatar_em"] = quando.isoformat()
        update_lead(lead_id, metadata=meta)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] falha ao gravar recontatar_em do lead %s: %s",
                       lead_id, exc)
        return
    _anotar(lead_id, conversation_id,
            f"⏰ [RECONTATO] Lead pediu contato em ~{meses} mês(es) "
            f"({quando.date().isoformat()}), via bot de reativação.")


def _anotar(lead_id: str, conversation_id: str, texto: str) -> None:
    """Observação no lead + mensagem de sistema na conversa. Fail-soft nos dois."""
    try:
        append_lead_observation(lead_id, texto)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] observação não gravada p/ lead %s: %s", lead_id, exc)
    try:
        save_message(lead_id, "system", f"[button_flow] {texto}",
                     conversation_id=conversation_id)
    except Exception as exc:
        logger.warning("[BUTTON FLOW] mensagem de sistema não gravada p/ conv %s: %s",
                       conversation_id, exc)
