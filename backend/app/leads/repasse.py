"""Evento `lead_events.repasse`: um por repasse ao closer (D3), sem sobrescrever histórico.

Fail-soft: o repasse em si (mensagem-marcador + carimbo metadata.handoff) já foi gravado e é
o que follow-up, buffer e watchdog leem; perder o evento só empobrece a linha do tempo."""
from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from typing import Any, Iterator

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)


# Reserva do repasse sem vendedor resolvido (b67f1c6b): é a regra de hoje — quem recebe o
# lead sem segmento é o João. Por e-mail, a chave estável do cadastro `vendedores`.
JOAO_EMAIL = "joao@cafecanastra.com"
# Rótulo da exportação quando o cadastro está vazio/indisponível: o cartão enviado é o do
# Arthur (tools.EXPORTACAO_NAME) e o carimbo tem de dizer o mesmo nome.
ROTULO_EXPORTACAO = "Arthur"


# ── Motivo estruturado do repasse (F3, 06/11/2026) ──────────────────────────
# O texto de `motivo` é livre (o LLM escreve; o fluxo de botões manda sempre o mesmo
# "valeria_botoes_v2: lead pediu atendimento do vendedor"). Para separar o repasse
# QUALIFICADO do repasse por tempo, preço ou amostra, o evento `repasse` ganha
# `metadata.motivo_codigo`, com vocabulário fechado:
MOTIVO_FIM_DOS_BOTOES = "fim_dos_botoes"     # tocou até o handoff do ramo
MOTIVO_CIRCUIT_BREAKER = "circuit_breaker"   # IA: 6 turnos sem handoff (ou "por tempo")
MOTIVO_OBJECAO_PRECO = "objecao_preco"
MOTIVO_KIT_AMOSTRA = "kit_amostra"
MOTIVO_AUTOMATICO = "automatico"             # varredura de parados / tabela indisponível
MOTIVO_PEDIU_VENDEDOR = "pediu_vendedor"     # pergunta livre ou "falar com vendedor"
MOTIVO_RUIDO = "ruido"                       # 2 textos que o bot não entendeu
MOTIVO_IA_QUALIFICADO = "ia_qualificado"     # IA com finalidade + volume + sinal de compra
MOTIVO_OUTRO = "outro"
MOTIVOS_CODIGO = (MOTIVO_FIM_DOS_BOTOES, MOTIVO_CIRCUIT_BREAKER, MOTIVO_OBJECAO_PRECO,
                  MOTIVO_KIT_AMOSTRA, MOTIVO_AUTOMATICO, MOTIVO_PEDIU_VENDEDOR, MOTIVO_RUIDO,
                  MOTIVO_IA_QUALIFICADO, MOTIVO_OUTRO)

# Repasses que o cartão 1 do atacado quer tirar de "qualificado": o lead foi ao João
# por tempo, preço, amostra ou silêncio, não porque qualificou.
MOTIVOS_NAO_QUALIFICADOS = frozenset({MOTIVO_CIRCUIT_BREAKER, MOTIVO_OBJECAO_PRECO,
                                      MOTIVO_KIT_AMOSTRA, MOTIVO_AUTOMATICO})

# DESLIGADA. Ligada, o evento `lead_events.qualificado` (critério "repasse") deixa de
# ser gravado para `MOTIVOS_NAO_QUALIFICADOS` — muda o número de "qualificados" do CRM
# (D2/D3). NÃO muda o que vai para Meta/Google: a varredura de conversões
# (`conversions/sweep.py`) lê o carimbo `leads.metadata.handoff`, não `lead_events`.
# Ligar os dois é a decisão 3 do consolidado de 06/11/2026 (Rafael e Tati).
FLAG_SO_REPASSE_QUALIFICADO = "QUALIFICADO_SO_REPASSE_QUALIFICADO"


def so_repasse_qualificado() -> bool:
    return (os.getenv(FLAG_SO_REPASSE_QUALIFICADO) or "").strip().lower() in ("1", "on", "true")


def repasse_conta_como_qualificado(motivo_codigo: str | None) -> bool:
    """Com a flag ligada, repasse por tempo/preço/amostra/automático não qualifica."""
    return not (so_repasse_qualificado() and motivo_codigo in MOTIVOS_NAO_QUALIFICADOS)


# O fluxo de botões chama `registrar_repasse` dentro de `effects.aplicar` (da F2), que
# não sabe o motivo. O runner sabe, e o põe aqui ANTES de chamar os efeitos:
# `asyncio.to_thread` copia o contexto, então a thread dos efeitos enxerga o valor.
_motivo_do_turno: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "motivo_do_repasse", default=None)


@contextlib.contextmanager
def motivo_do_repasse(codigo: str | None) -> Iterator[None]:
    token = _motivo_do_turno.set(codigo if codigo in MOTIVOS_CODIGO else None)
    try:
        yield
    finally:
        _motivo_do_turno.reset(token)


def _normal(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def classificar_motivo(motivo: str | None) -> str:
    """Código do motivo a partir do texto (IA, botões v2, varredura). Puro.

    Os textos da IA vêm dos prompts (`valeria_inbound/*.py`). "lead qualificado —
    atacado" é o texto do CIRCUIT BREAKER do atacado.py até a F3 (o único lugar que o
    usa); a F3 o troca por "circuit breaker — atacado (6 turnos)".
    """
    t = _normal(motivo or "")
    if not t:
        return MOTIVO_OUTRO
    if "circuit breaker" in t or "handoff por tempo" in t or t.startswith("lead qualificado — atacado"):
        return MOTIVO_CIRCUIT_BREAKER
    if "objecao de preco" in t or "negociacao de preco" in t:
        return MOTIVO_OBJECAO_PRECO
    if "amostra" in t or "degustacao" in t or "quero o kit" in t:
        return MOTIVO_KIT_AMOSTRA
    if t.startswith("automatico") or "repasse automatico" in t:
        return MOTIVO_AUTOMATICO
    if "sem resposta a botoes" in t:
        return MOTIVO_RUIDO
    if t.startswith(("pergunta:", "vendedor:")) or "falar com vendedor" in t \
            or "solicitou atendimento humano" in t:
        return MOTIVO_PEDIU_VENDEDOR
    if t.startswith(("clicou ", "escreveu ")):
        return MOTIVO_FIM_DOS_BOTOES
    if ("qualificado" in t or "intencao de compra" in t or "handoff proativo" in t
            or "fechar pedido" in t or "preco de fardo" in t or "alto ticket" in t):
        return MOTIVO_IA_QUALIFICADO
    return MOTIVO_OUTRO


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
    # F3: o código vem do runner de botões (contexto) ou do texto (IA).
    motivo_codigo = _motivo_do_turno.get() or classificar_motivo(motivo)
    evento: dict[str, Any] = {
        "lead_id": lead_id,
        "event_type": "repasse",
        "new_value": vendedor,
        "source": source,
        "dedupe_key": f"repasse:{message_id}",
        "metadata": {"vendedor_id": vendedor_id, "vendedor": vendedor, "segmento": segmento,
                     "motivo": motivo, "motivo_codigo": motivo_codigo,
                     "conversation_id": conversation_id, "message_id": message_id},
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
    if qualificado.motivo_qualifica(motivo) and repasse_conta_como_qualificado(motivo_codigo):
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
