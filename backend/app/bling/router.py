"""Endpoints da integracao Bling consumidos pelo Next.

Contrato de POST /api/bling/orders:
  201 -> pedido criado no Bling (o vendedor ve o numero na hora)
  202 -> Bling indisponivel; job enfileirado, a UI mostra "processando"
  409 -> contato nao resolvido; devolve candidatos para o vendedor decidir
  422 -> erro de validacao do Bling, repassado com a mensagem original

A diferenca entre 202 e 422 e a que mais importa: so erro TRANSITORIO vira job.
Um payload invalido na fila viraria retentativa infinita e, pior, rajada de erro
conta para o bloqueio de IP do Bling (300 erros em 10s => 10 min bloqueado).

Contrato de PUT /api/bling/orders/{order_id}:
  200 -> pedido alterado no Bling
  202 -> erro TRANSITORIO; NAO e recusa, e retentativa. Sem job: o PUT nao tem
         idempotency_key porque nao precisa — reenviar o mesmo PUT nao duplica
         nada, entao o proprio vendedor tentando salvar de novo basta.
  409 -> contato nao resolvido (raro aqui: o vinculo e persistido desde a
         criacao do pedido; so volta a acontecer se alguem desfez o vinculo
         manualmente depois)
  422 -> o Bling recusou a alteracao (pedido ja faturado, tipicamente),
         repassado com a mensagem original. Quem decide o que fazer com a
         recusa (inclusive marcar a venda como divergente) e quem chama —
         este endpoint so tenta e devolve a resposta. Por isso, diferente do
         POST, o PUT nao escreve em `sales`.
"""
import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator

from app.bling import auth, config, contacts, jobs
from app.bling.errors import TRANSIENT, BlingError, BlingUnknownAccount, BlingValidationError
from app.bling.orders import create_order, update_order
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bling", tags=["bling"])


def _conta_valida(account: str) -> config.BlingAccount:
    """Resolve a conta ou devolve 400. Slug errado e erro do chamador.

    Unico ponto do modulo onde um slug de conta vindo de fora (query string ou
    corpo do POST) e validado. Todo endpoint que aceita `account` chama isto
    PRIMEIRO e so repassa `.key` (a versao normalizada) para `contacts`,
    `orders` e `auth` — nunca o parametro cru.
    """
    try:
        return config.account(account)
    except BlingUnknownAccount as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    # CNPJ (conta Bling) da venda. Sobe DENTRO do corpo, nao como query param:
    # este e um POST/PUT com body Pydantic e o proxy Next.js
    # (frontend/src/app/api/bling/orders/**) repassa o JSON inteiro sem
    # filtrar chaves — um Query() aqui nunca veria o valor que o vendedor
    # escolheu, porque a URL do proxy para o backend nao carrega query string.
    account: str = config.DEFAULT_ACCOUNT


# Formato de e-mail: ESPELHO EXATO do `EMAIL_RE` de
# `frontend/src/lib/bling-contact-form.ts` — algo antes de um unico `@`, e
# depois dele um dominio com pelo menos um ponto separando rotulos nao vazios.
#
# A escolha por uma checagem sobria (e nao uma regex de RFC 5322) esta explicada
# la, e vale igual aqui: o custo dos dois erros e assimetrico. Deixar passar um
# endereco sintaticamente exotico nao quebra nada — quem valida de verdade e o
# Bling no 422, e depois disso o proprio servidor de e-mail. Ja um falso
# negativo recusa o e-mail real de um cliente e trava a venda na frente do
# vendedor, que nao tem como contornar. Por isso `[^\s@]` e permissivo com
# acento, `+`, `_` e o que mais o cliente tiver no endereco.
#
# As duas regras PRECISAM continuar iguais: divergir faria o formulario aceitar
# o que a API recusa (ou o contrario), e o vendedor veria um erro que a tela nao
# sabe explicar.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$")


class ContactIn(BaseModel):
    lead_id: str
    nome: str
    numeroDocumento: str
    tipo: str | None = None
    # OBRIGATORIO desde a entrega do orcamento (decisao 6 do design da proposta
    # comercial). O formulario ja exige desde o commit `1d973c30`, mas isso e
    # barreira de NAVEGADOR: um POST direto em /api/bling/contacts passaria reto
    # e criaria no ERP exatamente o contato incompleto que a decisao quer
    # impedir. O orcamento e um documento que se entrega ao cliente, e contato
    # sem e-mail no Bling e proposta que nao tem para onde ir.
    #
    # `validate_default=True` existe para que o campo AUSENTE tambem caia no
    # validador: sem isso o default None passaria sem ser validado e a exigencia
    # so valeria para quem mandasse a chave.
    email: str | None = Field(default=None, validate_default=True)
    telefone: str | None = None
    celular: str | None = None
    endereco: dict | None = None
    # Mesmo raciocinio do account em OrderIn: sobe no corpo porque o proxy
    # Next.js (frontend/src/app/api/bling/contacts/route.ts) repassa o JSON
    # inteiro sem filtrar chaves.
    account: str = config.DEFAULT_ACCOUNT

    @field_validator("email")
    @classmethod
    def _email_obrigatorio(cls, valor: str | None) -> str:
        email = (valor or "").strip()
        if not email:
            raise ValueError("o e-mail do cliente e obrigatorio")
        if not _EMAIL_RE.match(email):
            raise ValueError("e-mail invalido")
        return email


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


def _query_products(q: str | None, limit: int, account: str):
    query = (get_supabase().table("bling_products")
             .select("id, codigo, nome, preco, unidade, saldo_virtual, imagem_url")
             .eq("situacao", "A").eq("account", account))
    if q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},codigo.ilike.{alvo}")
    return getattr(query.order("nome").limit(limit).execute(), "data", None) or []


@router.get("/products")
async def list_products(q: str | None = Query(None), limit: int = Query(50, le=200),
                         account: str = Query(config.DEFAULT_ACCOUNT)):
    """Busca no ESPELHO, nunca no Bling — o combobox dispara a cada tecla."""
    conta = _conta_valida(account)
    data = await asyncio.to_thread(_query_products, q, limit, conta.key)
    return {"data": data}


def _query_catalog(q: str | None, situacao: str | None, page: int, limit: int, account: str):
    """Catalogo completo, paginado. Diferente de `_query_products`, que fixa
    situacao='A' e teto de 200 porque nasceu para um combobox.

    A paginacao e explicita de proposito: o PostgREST corta em 1000 linhas por
    padrao, e um catalogo maior que isso viraria truncamento silencioso."""
    inicio = (page - 1) * limit
    query = (get_supabase().table("bling_products")
             .select("id, codigo, nome, preco, unidade, situacao, saldo_virtual, "
                     "imagem_url", count="exact")
             .eq("account", account))
    if situacao:
        query = query.eq("situacao", situacao)
    if q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},codigo.ilike.{alvo}")
    res = query.order("nome").range(inicio, inicio + limit - 1).execute()
    return getattr(res, "data", None) or [], getattr(res, "count", None) or 0


@router.get("/catalog")
async def list_catalog(q: str | None = Query(None), situacao: str | None = Query(None),
                        page: int = Query(1, ge=1), limit: int = Query(50, le=200),
                        account: str = Query(config.DEFAULT_ACCOUNT)):
    """Catalogo do espelho para a tela de produtos — nunca a API do Bling.

    Diferente de GET /products (combobox de pedido: so ativos, teto de 200),
    aqui a paginacao e explicita e o total vem do PostgREST via `count=exact`.
    """
    conta = _conta_valida(account)
    data, total = await asyncio.to_thread(_query_catalog, q, situacao, page, limit, conta.key)
    return {"data": data, "page": page, "limit": limit, "total": total}


def _query_contacts(q: str | None, limit: int, account: str, contact_id: int | None = None):
    query = (get_supabase().table("bling_contacts")
             .select("id, nome, fantasia, doc_digits, telefone_e164, celular_e164, "
                     "email, situacao, endereco")
             .eq("account", account))
    if contact_id is not None:
        # id e exato (chave do espelho, agora composta (account, id)): combinar
        # com o `or_` de texto nao faz sentido, entao o id vence e o texto e
        # ignorado.
        query = query.eq("id", contact_id)
    elif q:
        alvo = f"%{_termo_seguro(q)}%"
        query = query.or_(f"nome.ilike.{alvo},fantasia.ilike.{alvo},doc_digits.ilike.{alvo}")
    return getattr(query.order("nome").limit(limit).execute(), "data", None) or []


@router.get("/contacts/search")
async def search_contacts(q: str | None = Query(None), id: int | None = Query(None),
                           limit: int = Query(20, le=100),
                           account: str = Query(config.DEFAULT_ACCOUNT)):
    """Busca no ESPELHO, nunca no Bling — o campo dispara a cada tecla.

    `id` busca exata pela chave (account, id) do espelho — usada pela tela de
    detalhe do lead para carregar o contato ja vinculado ao lead NESTA conta
    (`contacts._contato_do_lead`, tabela `lead_bling_contacts` — a coluna
    `leads.bling_contact_id` foi aposentada pela Task 7) mesmo quando o lead
    nao tem CNPJ para servir de termo de busca (vinculo por telefone/e-mail ou
    escolhido a mao).
    """
    conta = _conta_valida(account)
    return {"data": await asyncio.to_thread(_query_contacts, q, limit, conta.key, id)}


def _query_payment_methods(account: str):
    rows = getattr(get_supabase().table("bling_payment_methods")
                   .select("*").eq("account", account).order("descricao").execute(),
                   "data", None) or []
    # finalidade: 1 pagamentos, 2 recebimentos, 3 ambos. Venda usa 2 ou 3.
    return [m for m in rows
            if m.get("situacao") == 1 and m.get("finalidade") in (2, 3)]


@router.get("/payment-methods")
async def list_payment_methods(account: str = Query(config.DEFAULT_ACCOUNT)):
    conta = _conta_valida(account)
    return {"data": await asyncio.to_thread(_query_payment_methods, conta.key)}


def _query_sellers(account: str):
    return getattr(get_supabase().table("bling_sellers").select("*")
                   .eq("account", account).order("nome").execute(), "data", None) or []


@router.get("/sellers")
async def list_sellers(account: str = Query(config.DEFAULT_ACCOUNT)):
    conta = _conta_valida(account)
    return {"data": await asyncio.to_thread(_query_sellers, conta.key)}


# --------------------------------------------------------------------------
# Pedido
# --------------------------------------------------------------------------
def _load_lead(lead_id: str) -> dict | None:
    # `bling_contact_id` NAO entra mais na projecao: Task 7 moveu o vinculo
    # lead-contato para `lead_bling_contacts` (uma linha por lead+conta) --
    # quem precisa do contato vinculado usa `contacts._contato_do_lead`
    # (chamado indiretamente por `contacts.resolve`), nunca esta coluna.
    res = (get_supabase().table("leads")
           .select("id, name, phone, telefone_comercial, email, cnpj")
           .eq("id", lead_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _seller_id_for(email: str | None, account: str) -> int | None:
    if not email:
        return None
    res = (get_supabase().table("bling_seller_map").select("bling_seller_id")
           .eq("user_email", email).eq("account", account).limit(1).maybe_single().execute())
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
    conta = _conta_valida(body.account)
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    resolucao = await contacts.resolve(lead, conta.key)
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
        "seller_id": await asyncio.to_thread(_seller_id_for, body.sold_by, conta.key),
        "notes": body.notes,
        "account": conta.key,
    }

    from app.bling.client import BlingClient
    try:
        async with BlingClient(account=conta.key) as client:
            out = await create_order(client, **kwargs)
    except BlingValidationError as exc:
        # Repetir payload invalido nunca conserta — nao vai para a fila.
        return JSONResponse({
            "error": "validation", "message": str(exc),
            "detail": exc.description, "type": exc.type,
        }, status_code=422)
    except TRANSIENT as exc:
        # `account=` PRECISA ir aqui. A conta oficial do job e a da LINHA, nao a
        # do payload — `_handle_create_order` descarta a do payload de proposito,
        # para nao colidir com o parametro nomeado. Sem passar a conta no enqueue,
        # a linha nasce com a conta padrao e a retentativa roda INTEIRA como
        # conta 1: autentica no Bling do CNPJ errado e cria o pedido la, sem erro
        # nenhum na tela. E o mesmo defeito que esta entrega existe para impedir,
        # so que no caminho da fila.
        await jobs.enqueue("create_order", kwargs, account=conta.key)
        logger.warning("[BLING] pedido enfileirado (conta %s, Bling indisponivel): %s",
                       conta.key, exc)
        return JSONResponse({"status": "queued", "reason": str(exc)}, status_code=202)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    return JSONResponse({**out, "status": "created"}, status_code=201)


@router.put("/orders/{order_id}")
async def update_order_endpoint(order_id: int, body: OrderIn):
    """422 quando o Bling recusa (pedido faturado, tipicamente) — a UI pergunta
    se salva so no CRM e marca divergencia. 202 quando o erro e transitorio:
    ai NAO e divergencia, e retentativa (sem job — ver docstring do modulo)."""
    conta = _conta_valida(body.account)
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    # Mesma resolucao do POST. Na pratica cai direto no atalho `linked`: o
    # vinculo lead-contato foi persistido quando o pedido foi criado e
    # `contacts.resolve` o devolve sem I/O extra (ve o comentario no modulo
    # `contacts`). So volta a exigir decisao humana se o vinculo tiver sido
    # desfeito manualmente depois — o mesmo caso que o POST ja trata, entao
    # reusar em vez de inventar um caminho novo para o PUT.
    resolucao = await contacts.resolve(lead, conta.key)
    if resolucao.status != "linked":
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
        "order_id": order_id,
        "contact_id": resolucao.contact_id,
        "sold_at": body.sold_at,
        "itens": itens,
        "payment": {"method_id": body.payment.method_id, "terms": body.payment.terms},
        "seller_id": await asyncio.to_thread(_seller_id_for, body.sold_by, conta.key),
        "notes": body.notes,
        "account": conta.key,
    }

    from app.bling.client import BlingClient
    try:
        async with BlingClient(account=conta.key) as client:
            await update_order(client, **kwargs)
    except BlingValidationError as exc:
        # Repetir a mesma alteracao recusada nunca conserta — nao vira retentativa.
        # Quem chama decide se salva local e marca divergencia.
        return JSONResponse({
            "error": "validation", "message": str(exc),
            "detail": exc.description, "type": exc.type,
        }, status_code=422)
    except TRANSIENT as exc:
        # Sem job: o PUT e seguro de reenviar (nao ha duplicacao possivel como
        # no POST), entao o proprio vendedor tentando salvar de novo basta.
        logger.warning("[BLING] PUT do pedido %s falhou (transitorio): %s", order_id, exc)
        return JSONResponse({"status": "bling_unavailable", "reason": str(exc)},
                            status_code=202)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    return JSONResponse({"status": "updated", "bling_order_id": order_id}, status_code=200)


@router.post("/contacts")
async def create_contact_endpoint(body: ContactIn):
    """Cria o contato no Bling e vincula ao lead (fluxo do 409)."""
    conta = _conta_valida(body.account)
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    from app.bling.client import BlingClient
    # `account` sai de `dados`: e roteamento (qual conta do Bling), nao um
    # campo do contato -- `contacts.create_contact` so espera nome,
    # numeroDocumento, tipo, email, telefone, celular, endereco.
    dados = body.model_dump(exclude={"lead_id", "account"}, exclude_none=True)
    try:
        async with BlingClient(account=conta.key) as client:
            contact_id = await contacts.create_contact(client, lead, dados, account=conta.key)
    except BlingValidationError as exc:
        return JSONResponse({"error": "validation", "message": str(exc),
                             "detail": exc.description}, status_code=exc.status)
    except BlingError as exc:
        # Antes so BlingValidationError era pega. Com multi-conta,
        # BlingNotConfigured/BlingAuthError/BlingServerError deixam de ser
        # teoricos aqui: uma conta valida mas ainda sem token (nunca passou
        # pelo OAuth) cai exatamente neste caminho. Sem isto, 500 opaco.
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)
    return {"bling_contact_id": contact_id, "account": conta.key}


@router.post("/contacts/link")
async def link_contact_endpoint(lead_id: str, contact_id: int,
                                 account: str = Query(config.DEFAULT_ACCOUNT)):
    """Confirma manualmente um candidato sugerido."""
    conta = _conta_valida(account)
    await contacts.link(lead_id, contact_id, conta.key)
    return {"linked": True}


@router.post("/contacts/unlink")
async def unlink_contact_endpoint(lead_id: str, account: str = Query(config.DEFAULT_ACCOUNT)):
    """Desfaz o vinculo lead-contato (a proxima venda volta a resolucao por documento)."""
    conta = _conta_valida(account)
    await contacts.unlink(lead_id, conta.key)
    return {"unlinked": True}


# --------------------------------------------------------------------------
# OAuth e operacao
# --------------------------------------------------------------------------
@router.get("/oauth/authorize")
async def oauth_authorize(account: str = Query(config.DEFAULT_ACCOUNT)):
    # Slug invalido vira 400 aqui (_conta_valida), antes de qualquer outra
    # checagem. Sem credenciais NESTA conta, begin_authorization levantaria
    # BlingNotConfigured e o admin veria um 500 opaco em vez de "falta
    # configurar" -- `conta.configured` (Task 1) e a fonte unica da regra,
    # agora por conta (era `config.is_configured()` global).
    #
    # new_state e authorize_url NUNCA sao chamados em separado aqui -- so
    # `begin_authorization`, que garante a MESMA conta nos dois. Como as duas
    # contas podem compartilhar client_id/client_secret, um par trocado nao
    # erraria do lado do Bling: gravaria o token exchangeado no CNPJ errado,
    # em silencio.
    conta = _conta_valida(account)
    if not conta.configured:
        return JSONResponse({"error": "not_configured"}, status_code=400)
    return {"url": await auth.begin_authorization(conta.key)}


@router.get("/oauth/callback")
async def oauth_callback(code: str = "", state: str = ""):
    # O state e a protecao anti-CSRF do fluxo: validado (e queimado) ANTES de o
    # code ser trocado, senao um callback forjado plantaria o token de outra conta.
    # Checagem EXPLICITA contra None, nao truthiness: consume_state devolve a
    # CONTA como string, e uma conta vazia normaliza para default dentro de
    # config.account() -- "" e um resultado VALIDO do consumo, so None e
    # invalido (state ausente, inexistente ou ja usado).
    conta = await auth.consume_state(state)
    if conta is None:
        return JSONResponse({"error": "state_invalido"}, status_code=400)
    # O authorization_code expira em 1 MINUTO — troca imediata. `conta` (nao a
    # default) vai para exchange_code: e a MESMA conta que o state carregava
    # desde que o fluxo comecou em oauth_authorize, senao o token cairia no
    # CNPJ errado.
    await auth.exchange_code(code, conta)
    destino = (settings.frontend_url or "").rstrip("/") + "/config?bling=ok"
    return RedirectResponse(destino, status_code=302)


@router.get("/status")
async def bling_status():
    # auth.status() devolve LISTA (Task 4: uma entrada por conta). O JSON aqui
    # continua ADITIVO de proposito -- nunca troque por `return {**contas, ...}`
    # nem por `return contas`. use-bling-status.ts le body.enabled e
    # body.connected direto do topo; se sumissem, os dois virariam undefined no
    # frontend, o hook devolveria enabled:false e blingGate cairia em
    # mode:"legacy", canSubmit:true -- as vendas parariam de ir para o Bling SEM
    # NENHUM ERRO na tela. `accounts` e o dado novo, ao lado, nao no lugar.
    #
    # configured/access_expires_at/refresh_expires_at/scope no topo NAO sao
    # redundancia gratuita: bling-settings.tsx busca este endpoint DIRETO (nao
    # via use-bling-status.ts) e le estas quatro chaves no topo. Sem elas,
    # `configured` vira undefined -> o banner de credenciais ausentes fica
    # preso ligado e o botao Conectar/Reconectar fica desabilitado PARA
    # SEMPRE; e o aviso de expiracao do refresh_token (5 dias de antecedencia)
    # nunca mais dispara. Todas as quatro sao da conta DEFAULT, igual `connected`.
    contas = await auth.status()
    padrao = next((c for c in contas if c["account"] == config.DEFAULT_ACCOUNT), {})
    return {
        "enabled": config.enabled(),
        "connected": bool(padrao.get("connected")),
        "configured": bool(padrao.get("configured")),
        "access_expires_at": padrao.get("access_expires_at"),
        "refresh_expires_at": padrao.get("refresh_expires_at"),
        "scope": padrao.get("scope"),
        "accounts": contas,
    }


@router.post("/sync")
async def sync_endpoint(full: bool = False):
    from app.bling.sync import sync_all
    return await sync_all(full=full)


@router.post("/backfill")
async def backfill_endpoint(months: int = 12):
    """Importacao historica sob demanda (nao roda automatico)."""
    from app.bling.backfill import run
    return await run(months=months)
