"""Endpoints da integracao Bling consumidos pelo Next.

Contrato de POST /api/bling/orders:
  201 -> pedido criado no Bling (o vendedor ve o numero na hora)
  202 -> Bling indisponivel; job enfileirado, a UI mostra "processando"
  409 -> contato nao resolvido; devolve candidatos para o vendedor decidir
  422 -> erro de validacao do Bling, repassado com a mensagem original

A diferenca entre 202 e 422 e a que mais importa: so erro TRANSITORIO vira job.
Um payload invalido na fila viraria retentativa infinita e, pior, rajada de erro
conta para o bloqueio de IP do Bling (300 erros em 10s => 10 min bloqueado).
"""
import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.bling import auth, config, contacts, jobs
from app.bling.errors import TRANSIENT, BlingError, BlingValidationError
from app.bling.orders import create_order
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bling", tags=["bling"])


class OrderItemIn(BaseModel):
    bling_product_id: int
    quantidade: float
    valor_unitario: float
    desconto_percentual: float = 0
    codigo: str | None = None
    descricao: str | None = None
    unidade: str | None = None


class PaymentIn(BaseModel):
    method_id: int
    terms: list[int] = Field(default_factory=lambda: [0])


class OrderIn(BaseModel):
    lead_id: str
    deal_id: str | None = None
    # Quem registra a venda a partir do chat manda a conversa de origem; e o que
    # liga a venda ao atendimento que a gerou, como ja faz o POST /api/sales.
    conversation_id: str | None = None
    sold_at: str
    sold_by: str | None = None
    items: list[OrderItemIn]
    payment: PaymentIn
    notes: str = ""


class ContactIn(BaseModel):
    lead_id: str
    nome: str
    numeroDocumento: str
    tipo: str | None = None
    email: str | None = None
    telefone: str | None = None
    celular: str | None = None
    endereco: dict | None = None


# --------------------------------------------------------------------------
# Leitura dos espelhos
# --------------------------------------------------------------------------
def _termo_seguro(q: str) -> str:
    """Neutraliza os caracteres que COMPOEM a sintaxe do filtro `or` do PostgREST.

    O termo chega cru do combobox. Uma virgula ou parentese digitados fechariam a
    expressao e o resto do texto viraria filtro — no melhor caso um 400 na cara do
    vendedor, no pior um filtro que ninguem pediu. Ninguem busca produto por virgula.
    """
    return q.translate(str.maketrans({",": " ", "(": " ", ")": " ", '"': " "})).strip()


def _query_products(q: str | None, limit: int):
    query = (get_supabase().table("bling_products")
             .select("id, codigo, nome, preco, unidade, saldo_virtual, imagem_url")
             .eq("situacao", "A"))
    if q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},codigo.ilike.{alvo}")
    return getattr(query.order("nome").limit(limit).execute(), "data", None) or []


@router.get("/products")
async def list_products(q: str | None = Query(None), limit: int = Query(50, le=200)):
    """Busca no ESPELHO, nunca no Bling — o combobox dispara a cada tecla."""
    data = await asyncio.to_thread(_query_products, q, limit)
    return {"data": data}


def _query_contacts(q: str | None, limit: int):
    query = (get_supabase().table("bling_contacts")
             .select("id, nome, fantasia, doc_digits, telefone_e164, celular_e164, "
                     "email, situacao, endereco"))
    if q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},fantasia.ilike.{alvo},doc_digits.ilike.{alvo}")
    return getattr(query.order("nome").limit(limit).execute(), "data", None) or []


@router.get("/contacts/search")
async def search_contacts(q: str | None = Query(None), limit: int = Query(20, le=100)):
    """Busca no ESPELHO, nunca no Bling — o campo dispara a cada tecla."""
    return {"data": await asyncio.to_thread(_query_contacts, q, limit)}


def _query_payment_methods():
    rows = getattr(get_supabase().table("bling_payment_methods")
                   .select("*").order("descricao").execute(), "data", None) or []
    # finalidade: 1 pagamentos, 2 recebimentos, 3 ambos. Venda usa 2 ou 3.
    return [m for m in rows
            if m.get("situacao") == 1 and m.get("finalidade") in (2, 3)]


@router.get("/payment-methods")
async def list_payment_methods():
    return {"data": await asyncio.to_thread(_query_payment_methods)}


def _query_sellers():
    return getattr(get_supabase().table("bling_sellers").select("*")
                   .order("nome").execute(), "data", None) or []


@router.get("/sellers")
async def list_sellers():
    return {"data": await asyncio.to_thread(_query_sellers)}


# --------------------------------------------------------------------------
# Pedido
# --------------------------------------------------------------------------
def _load_lead(lead_id: str) -> dict | None:
    res = (get_supabase().table("leads")
           .select("id, name, phone, telefone_comercial, email, cnpj, bling_contact_id")
           .eq("id", lead_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _seller_id_for(email: str | None) -> int | None:
    if not email:
        return None
    res = (get_supabase().table("bling_seller_map").select("bling_seller_id")
           .eq("user_email", email).limit(1).maybe_single().execute())
    row = getattr(res, "data", None) or {}
    return row.get("bling_seller_id")


def _products_by_id(ids: list[int]) -> dict[int, dict]:
    """Le do espelho SO os produtos citados no pedido.

    Filtrar por id (em vez de varrer a tabela) nao e so economia: o PostgREST
    devolve no maximo 1000 linhas por padrao, entao um catalogo maior que isso
    faria o produto do pedido simplesmente nao aparecer e a descricao cair no
    generico "Item" — dado errado dentro do ERP, em silencio.
    """
    if not ids:
        return {}
    rows = getattr(get_supabase().table("bling_products")
                   .select("id, nome, codigo, unidade")
                   .in_("id", ids).execute(), "data", None) or []
    return {int(p["id"]): p for p in rows}


@router.post("/orders")
async def create_order_endpoint(body: OrderIn):
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    resolucao = await contacts.resolve(lead)
    if resolucao.status != "linked":
        # Nunca chuta o contato: sem match unico por documento, decide o humano.
        # Nada e criado aqui — nem contato, nem venda, nem job.
        return JSONResponse({
            "error": "contact_unresolved",
            "status": resolucao.status,
            "reason": resolucao.reason,
            "candidates": resolucao.candidates,
        }, status_code=409)

    itens = [{
        "bling_product_id": i.bling_product_id,
        "codigo": i.codigo,
        "descricao": i.descricao or "",
        "unidade": i.unidade,
        "quantidade": i.quantidade,
        "valor_unitario": i.valor_unitario,
        "desconto_percentual": i.desconto_percentual,
    } for i in body.items]

    # Descricao e obrigatoria no item mesmo com produto.id — completa do espelho.
    faltando = [i for i in itens if not i["descricao"]]
    if faltando:
        por_id = await asyncio.to_thread(
            _products_by_id, [i["bling_product_id"] for i in faltando]
        )
        for item in faltando:
            p = por_id.get(item["bling_product_id"]) or {}
            item["descricao"] = p.get("nome") or "Item"
            item["codigo"] = item["codigo"] or p.get("codigo")
            item["unidade"] = item["unidade"] or p.get("unidade")

    kwargs = {
        "lead_id": body.lead_id,
        "deal_id": body.deal_id,
        "conversation_id": body.conversation_id,
        "contact_id": resolucao.contact_id,
        "sold_at": body.sold_at,
        "sold_by": body.sold_by,
        "itens": itens,
        "payment": {"method_id": body.payment.method_id, "terms": body.payment.terms},
        "seller_id": await asyncio.to_thread(_seller_id_for, body.sold_by),
        "notes": body.notes,
    }

    from app.bling.client import BlingClient
    try:
        async with BlingClient() as client:
            out = await create_order(client, **kwargs)
    except BlingValidationError as exc:
        # Repetir payload invalido nunca conserta — nao vai para a fila.
        return JSONResponse({
            "error": "validation", "message": str(exc),
            "detail": exc.description, "type": exc.type,
        }, status_code=422)
    except TRANSIENT as exc:
        await jobs.enqueue("create_order", kwargs)
        logger.warning("[BLING] pedido enfileirado (Bling indisponivel): %s", exc)
        return JSONResponse({"status": "queued", "reason": str(exc)}, status_code=202)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    return JSONResponse({**out, "status": "created"}, status_code=201)


@router.post("/contacts")
async def create_contact_endpoint(body: ContactIn):
    """Cria o contato no Bling e vincula ao lead (fluxo do 409)."""
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    from app.bling.client import BlingClient
    dados = body.model_dump(exclude={"lead_id"}, exclude_none=True)
    try:
        async with BlingClient() as client:
            contact_id = await contacts.create_contact(client, lead, dados)
    except BlingValidationError as exc:
        return JSONResponse({"error": "validation", "message": str(exc),
                             "detail": exc.description}, status_code=exc.status)
    return {"bling_contact_id": contact_id}


@router.post("/contacts/link")
async def link_contact_endpoint(lead_id: str, contact_id: int):
    """Confirma manualmente um candidato sugerido."""
    await contacts.link(lead_id, contact_id)
    return {"linked": True}


@router.post("/contacts/unlink")
async def unlink_contact_endpoint(lead_id: str):
    """Desfaz o vinculo lead-contato (a proxima venda volta a resolucao por documento)."""
    await contacts.unlink(lead_id)
    return {"unlinked": True}


# --------------------------------------------------------------------------
# OAuth e operacao
# --------------------------------------------------------------------------
@router.get("/oauth/authorize")
async def oauth_authorize():
    # Sem credenciais, authorize_url levanta BlingNotConfigured e o admin veria um
    # 500 opaco em vez de "falta configurar". is_configured() e a fonte unica da regra.
    if not config.is_configured():
        return JSONResponse({"error": "not_configured"}, status_code=400)
    state = await auth.new_state()
    return {"url": auth.authorize_url(state)}


@router.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = ""):
    # O state e a protecao anti-CSRF do fluxo: validado (e queimado) ANTES de o
    # code ser trocado, senao um callback forjado plantaria o token de outra conta.
    if not await auth.consume_state(state):
        return JSONResponse({"error": "invalid_state"}, status_code=400)
    # O authorization_code expira em 1 MINUTO — troca imediata.
    await auth.exchange_code(code)
    destino = (settings.frontend_url or "").rstrip("/") + "/config?bling=ok"
    return RedirectResponse(destino, status_code=302)


@router.get("/status")
async def bling_status():
    # `configured` ja vem de auth.status(), que consulta config.is_configured().
    # `enabled` e outra coisa: o toggle BLING_ENABLED que liga os workers.
    estado = await auth.status()
    return {**estado, "enabled": config.enabled()}


@router.post("/sync")
async def sync_endpoint(full: bool = False):
    from app.bling.sync import sync_all
    return await sync_all(full=full)


@router.post("/backfill")
async def backfill_endpoint(months: int = 12):
    """Importacao historica sob demanda (nao roda automatico)."""
    from app.bling.backfill import run
    return await run(months=months)
