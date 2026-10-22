"""Evento `lead_events.repasse`: um por repasse ao closer (D3), sem sobrescrever histórico.

Fail-soft: o repasse em si (mensagem-marcador + carimbo metadata.handoff) já foi gravado e é
o que follow-up, buffer e watchdog leem; perder o evento só empobrece a linha do tempo."""
from __future__ import annotations

import logging
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


# Reserva do repasse sem vendedor resolvido (b67f1c6b): é a regra de hoje — quem recebe o
# lead sem segmento é o João. Por e-mail, a chave estável do cadastro `vendedores`.
JOAO_EMAIL = "joao@cafecanastra.com"
# Rótulo da exportação quando o cadastro está vazio/indisponível: o cartão enviado é o do
# Arthur (tools.EXPORTACAO_NAME) e o carimbo tem de dizer o mesmo nome.
ROTULO_EXPORTACAO = "Arthur"


def vendedor_do_repasse(*, segmento: str | None, vendedor: str | None,
                        vendedor_id: str | None = None,
                        reserva_joao: bool = True) -> tuple[str | None, str]:
    """(vendedor_id, rótulo) de quem recebe o repasse. Nunca levanta.

    - `vendedor_id` já resolvido pelo segmento (atacado/private_label/exportacao) manda;
    - senão, o nome indicado (`vendedor`, texto do LLM ou do fluxo de botões) passa pelo
      resolvedor; não resolvendo, o João (`JOAO_EMAIL`) quando `reserva_joao`.
      Exportação nunca cai no João: o cartão enviado é o do Arthur.
    - Rótulo = `vendedores.nome`. Cadastro vazio/indisponível: mantém o nome de hoje
      (o do LLM; "Arthur" na exportação) e o id pode ser None — o repasse não cai.
    """
    from app.leads.segmento import normalizar_segmento
    seg = normalizar_segmento(segmento)
    rotulo = (vendedor or "").strip() or "Vendedor"
    if seg == "exportacao":
        rotulo = ROTULO_EXPORTACAO
    vid = vendedor_id
    try:
        from app.vendedores import service as vendedores
        if not vid and seg != "exportacao":
            vid = vendedores.resolver_vendedor(vendedor)
            if not vid and reserva_joao:
                vid = vendedores.resolver_vendedor(JOAO_EMAIL)
        nome = (vendedores.por_id(vid) or {}).get("nome")
    except Exception as exc:
        logger.error("vendedor_do_repasse: cadastro de vendedores indisponível: %s", exc)
        nome = None
    return vid, (nome or rotulo)


def registrar_repasse(*, lead_id: str, conversation_id: str | None, message_id: str | None,
                      occurred_at: str | None, source: str, vendedor_id: str | None = None,
                      vendedor: str | None = None, segmento: str | None = None,
                      motivo: str | None = None) -> bool:
    if not lead_id or not message_id:
        logger.warning("registrar_repasse: lead %s sem message_id; evento não gravado", lead_id)
        return False
    evento: dict[str, Any] = {
        "lead_id": lead_id,
        "event_type": "repasse",
        "new_value": vendedor,
        "source": source,
        "dedupe_key": f"repasse:{message_id}",
        "metadata": {"vendedor_id": vendedor_id, "vendedor": vendedor, "segmento": segmento,
                     "motivo": motivo, "conversation_id": conversation_id, "message_id": message_id},
    }
    if occurred_at:
        evento["occurred_at"] = occurred_at
    try:
        get_supabase().table("lead_events").insert(evento).execute()
    except Exception as exc:  # inclui violação do dedupe_key (repetição) — idempotente
        logger.error("registrar_repasse: evento do lead %s não gravado: %s", lead_id, exc)
        return False
    # Evento `qualificado` (b67f1c6b): só quando o repasse gravou; o dedupe por lead já
    # garante um só. Import tardio evita ciclo; registrar_qualificado nunca levanta.
    from app.leads import qualificado
    if qualificado.motivo_qualifica(motivo):
        qualificado.registrar_qualificado(lead_id=lead_id, criterio="repasse", source=source,
                                          occurred_at=occurred_at, segmento=segmento, motivo=motivo,
                                          vendedor_id=vendedor_id, b2b=None)
    return True


def marcador_id_e_data(marcador: Any) -> tuple[str | None, str | None]:
    """(id, created_at) da linha devolvida por `save_message` do marcador.

    Só aceita dict: qualquer outra coisa (None quando o insert falhou, dublê de teste)
    vira (None, None), e `registrar_repasse` não grava nada sem message_id."""
    if not isinstance(marcador, dict):
        return None, None
    return marcador.get("id"), marcador.get("created_at")
