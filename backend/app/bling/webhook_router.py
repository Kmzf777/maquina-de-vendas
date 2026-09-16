"""Receiver dos webhooks do Bling.

REGRA DE OURO: responder 2xx em ate 5 SEGUNDOS. Passou disso, o Bling retenta
por ate 3 dias e depois DESABILITA a configuracao do webhook — a integracao
para em silencio ate alguem reabilitar na mao no painel.

Por isso o receiver so faz tres coisas: valida a assinatura, grava o evento e
devolve 200. Buscar o pedido completo (`GET /pedidos/vendas/{id}`, necessario
porque o payload do webhook nao traz itens) acontece no worker.
"""
import asyncio
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Request, Response

from app.bling import config
from app.bling.errors import BlingUnknownAccount
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bling"])

_SIG_HEADER = "x-bling-signature-256"
_PREFIX = "sha256="


def verify_signature(corpo: bytes, header: str | None, secret: str) -> bool:
    """HMAC-SHA256 hex do corpo CRU com o client_secret do aplicativo."""
    if not header or not header.startswith(_PREFIX) or not secret:
        return False
    esperado = hmac.new(secret.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, header[len(_PREFIX):])


def _insert_event(row: dict) -> bool:
    """Insere o evento. False se o event_id ja existia (repeticao do Bling)."""
    try:
        res = get_supabase().table("bling_webhook_events").insert(row).execute()
        return bool(getattr(res, "data", None))
    except Exception as exc:  # noqa: BLE001 — violacao de PK e o caminho esperado
        if "duplicate key" in str(exc).lower() or "23505" in str(exc):
            return False
        raise


async def _notify_worker() -> None:
    """Acorda o tick de processamento (o worker tambem varre por fallback).

    `emit_event` e SINCRONA e faz I/O no Redis — precisa de to_thread para nao
    bloquear o event loop dentro do request do webhook, que tem 5s de orcamento.
    O dominio e o nome da task no worker ("bling-webhook"), porque
    run_event_driven usa o nome como stream.
    """
    try:
        from app.events.bus import emit_event
        await asyncio.to_thread(emit_event, "bling-webhook")
    except Exception:  # noqa: BLE001 — o fallback periodico cobre
        pass


async def _receber(request: Request, account: str) -> Response:
    """Valida a assinatura com o secret DA CONTA e grava o evento com o slug
    dela. Compartilhada pelas duas rotas abaixo para as duas nao divergirem
    com o tempo."""
    try:
        conta = config.account(account)
    except BlingUnknownAccount:
        # 404 de proposito, NAO 200: slug errado e erro de configuracao no painel
        # do Bling e precisa ser barulhento. Absorver com 200 esconderia para
        # sempre um webhook que nunca vai ser processado.
        logger.error("[BLING WEBHOOK] conta desconhecida na rota: %s", account)
        return Response(status_code=404)

    corpo = await request.body()

    if not verify_signature(corpo, request.headers.get(_SIG_HEADER),
                            conta.client_secret):
        logger.warning("[BLING WEBHOOK] assinatura invalida (conta %s) — descartado",
                       account)
        return Response(status_code=401)

    try:
        evento = json.loads(corpo)
    except Exception:  # noqa: BLE001
        # Corpo ilegivel com assinatura valida nao deve virar retentativa eterna.
        logger.error("[BLING WEBHOOK] corpo nao e JSON valido (conta %s)", account)
        return Response(status_code=200)

    event_id = evento.get("eventId")
    if not event_id:
        logger.error("[BLING WEBHOOK] evento sem eventId: %s", evento.get("event"))
        return Response(status_code=200)

    novo = await asyncio.to_thread(_insert_event, {
        "event_id": event_id,
        # `conta.key`, nao o `account` cru da URL: config.account() normaliza
        # (strip + lower), e a PK da tabela e (account, event_id). Um slug com
        # caixa diferente no painel do Bling ("/webhook/bling/Secundaria")
        # gravaria "Secundaria" aqui — o dedupe por PK deixaria de casar com as
        # linhas de "secundaria", e toda query que filtra pelo slug normalizado
        # simplesmente nao acharia esses eventos.
        "account": conta.key,
        "event": evento.get("event") or "",
        "payload": evento,
        "event_date": evento.get("date"),
        "status": "pending",
    })

    if novo:
        await _notify_worker()
    else:
        logger.info("[BLING WEBHOOK] evento %s (conta %s) repetido — absorvido",
                    event_id, account)

    # Sempre 200: repeticao tambem precisa de 2xx (contrato de idempotencia).
    return Response(status_code=200)


@router.post("/webhook/bling")
async def bling_webhook_legado(request: Request) -> Response:
    """Rota SEM slug de conta. NAO REMOVER.

    O painel da conta 1 (a que ja existia) aponta para ca. Se esta rota
    sumir, os webhooks dela passam a 404, o Bling retenta por ate 3 dias e
    depois DESABILITA a configuracao — a integracao para em silencio ate
    alguem reabilitar na mao no painel do Bling.
    """
    return await _receber(request, config.DEFAULT_ACCOUNT)


@router.post("/webhook/bling/{account}")
async def bling_webhook(request: Request, account: str) -> Response:
    """Rota COM slug de conta, para toda conta Bling cadastrada depois da
    primeira (ex.: /webhook/bling/secundaria)."""
    return await _receber(request, account)
