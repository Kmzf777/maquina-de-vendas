"""Endpoints de orçamento (`/api/quotes`) consumidos pelo Next.

CONTRATO — é o que o frontend consome; mudar qualquer linha abaixo quebra a tela.

  POST   /api/quotes               201 {id, bling_proposal_id, bling_proposal_number, total}
                                   404 {error:"lead_not_found"}
                                   409 {error:"contact_unresolved", status, reason, candidates}
                                   422 {error:"validation", message, detail, type}
                                   502 {error:"bling"|"quote_not_saved", ...}
  PUT    /api/quotes/{id}          200 {id, total}
                                   409 {error:"quote_converted"}
  PATCH  /api/quotes/{id}/status   200 {status, situacao_sync}      corpo {"status": "..."}
                                   409 {error:"quote_converted"}
                                   422 {error:"validation", message}
  POST   /api/quotes/{id}/convert  201 {sale_id, bling_order_id, situacao_sync}
                                   409 {error:"already_converted"}
                                   422 {error:"validation", message, detail, type}
  GET    /api/quotes/{id}/pdf      application/pdf
                                   Content-Disposition: attachment; filename="orcamento-{numero}.pdf"

O 409 de contato repete literalmente o formato do `POST /api/bling/orders` —
o `BlingContactResolver` do frontend é o mesmo componente nos dois fluxos, e
um formato diferente aqui o faria não reconhecer o erro.

## Três regras de integridade que este arquivo existe para garantir

1. **Depois do 201 do Bling, nada levanta.** A proposta comercial não tem
   `numeroLoja` (nem campo equivalente) para servir de chave de idempotência —
   ao contrário do pedido de venda. Um erro propagado depois do POST faria o
   vendedor tentar de novo e criar uma SEGUNDA proposta no ERP, sem jeito
   automático de detectar. Por isso itens, movimento do deal e número da
   proposta são todos best-effort, e a única falha pós-POST que vira resposta
   de erro é a gravação da própria linha em `quotes` — que devolve 502 CITANDO
   o id da proposta, para o vendedor saber que ela existe lá.
2. **Orçamento convertido é imutável.** Editá-lo mudaria a proposta no Bling
   sem mudar o pedido de venda que nasceu dela.
3. **Na conversão a venda nasce ANTES do PATCH de situação.** Se a ordem fosse
   inversa, uma falha na criação do pedido deixaria uma proposta marcada como
   aprovada sem venda nenhuma — mentira no ERP que nada denunciaria depois.

## Escopo por vendedor

Não é aplicado aqui. `quotes.created_by` é gravado no POST e a leitura (lista,
métricas) acontece nas rotas do Next contra o Supabase, como `sales` já faz
hoje (§8 da spec). Este router só ESCREVE — e o PDF, que lê, é acessado a
partir de uma lista já escopada.
"""
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.bling import contacts
from app.bling.client import BlingClient
from app.bling.errors import TRANSIENT, BlingError, BlingValidationError
from app.bling.orders import (_dec, _money, build_installments, create_order,
                              item_total, parse_terms)
# `_load_lead`, `_products_by_id` e `_seller_id_for` são reaproveitados do router
# do Bling em vez de reescritos: são exatamente as mesmas consultas (o mesmo
# conjunto de colunas que `contacts.resolve` exige, o mesmo filtro por id que
# evita o teto de 1000 linhas do PostgREST, o mesmo mapa e-mail -> vendedor).
# Duas cópias divergiriam no primeiro ajuste de coluna, e a divergência
# apareceria como contato "não resolvido" em um fluxo e resolvido no outro.
from app.bling.router import _load_lead, _products_by_id, _seller_id_for
from app.bling import config
from app.db.supabase import get_supabase
from app.quotes.pdf import build_quote_pdf
from app.quotes.proposals import (STATUS_SITUACAO, create_proposal,
                                  normalize_discount_input, normalize_freight,
                                  quote_subtotal, quote_total, resolve_discount,
                                  set_situacao, update_proposal)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

# Key da etapa criada por `20260825_quotes.sql`. Ela se REPETE a cada funil
# (é única por pipeline, não global), o que torna o filtro por pipeline_id
# obrigatório — mesma armadilha do `fechado_ganho` em `orders.py`.
_PROPOSAL_STAGE_KEY = "proposta_enviada"

# `convertido` não entra: quem o grava é o endpoint de conversão, que também
# grava `sale_id`. Deixar o PATCH marcá-lo produziria um orçamento "vendido"
# sem venda, e o 409 do convert passaria a barrar a conversão de verdade.
_STATUS_MANUAIS = ("rascunho", "enviado", "aprovado", "nao_aprovado", "cancelado")


# --------------------------------------------------------------------------
# Corpo das requisições
# --------------------------------------------------------------------------
class QuoteItemIn(BaseModel):
    bling_product_id: int
    codigo: str | None = None
    # Aceita nulo e completa do espelho depois (`_montar_itens`): o Bling exige
    # descrição no item mesmo com `produto.id`, e recusar aqui obrigaria o
    # frontend a conhecer o catálogo só para preencher um campo que o backend já
    # tem à mão.
    descricao: str | None = None
    unidade: str | None = None
    quantidade: float
    valor_unitario: float
    desconto_percentual: float = 0


class QuoteDiscountIn(BaseModel):
    """O desconto como o vendedor digitou: número + unidade.

    O par viaja inteiro (e não só o valor já convertido) porque `quotes` guarda
    `discount_unit` + `discount_input` para a edição reexibir "10%" no campo
    onde ele digitou 10 — mandar só os reais faria reabrir o orçamento mostrando
    "26,70" e ele acharia que o sistema mudou o desconto.
    """
    valor: float = 0
    unidade: str = "REAL"


class QuotePaymentIn(BaseModel):
    method_id: int
    terms: list[int] = Field(default_factory=lambda: [0])


class QuoteIn(BaseModel):
    lead_id: str
    deal_id: str | None = None
    conversation_id: str | None = None
    quoted_at: str
    # E-mail do vendedor. É a base do escopo por vendedor (§8): sem ele o
    # orçamento fica invisível para quem não for admin.
    created_by: str | None = None
    items: list[QuoteItemIn]
    discount: QuoteDiscountIn | None = None
    freight: float = 0
    # 0 CIF · 1 FOB · 2 Terceiros · 3 Próprio remetente · 4 Próprio destinatário
    # · 9 Sem transporte.
    freight_mode: int | None = None
    payment: QuotePaymentIn
    notes: str = ""
    internal_notes: str = ""


class QuoteStatusIn(BaseModel):
    status: str


# --------------------------------------------------------------------------
# Banco — funções de módulo para que os testes troquem a persistência inteira
# --------------------------------------------------------------------------
def _load_quote(quote_id: str) -> dict | None:
    res = (get_supabase().table("quotes").select("*")
           .eq("id", quote_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _load_quote_items(quote_id: str) -> list[dict]:
    """Itens na ordem em que o vendedor os montou.

    O `order("ordem")` é obrigatório: o PostgREST não garante ordenação sem
    ORDER BY, e a sequência dos itens é o que o cliente confere no PDF.
    """
    res = (get_supabase().table("quote_items").select("*")
           .eq("quote_id", quote_id).order("ordem").execute())
    return getattr(res, "data", None) or []


def _insert_quote(row: dict) -> str | None:
    res = get_supabase().table("quotes").insert(row).execute()
    return (getattr(res, "data", None) or [{}])[0].get("id")


def _insert_quote_items(quote_id: str, itens: list[dict]) -> None:
    if not itens:
        return
    (get_supabase().table("quote_items")
     .insert([{**i, "quote_id": quote_id} for i in itens]).execute())


def _replace_quote_items(quote_id: str, itens: list[dict]) -> None:
    """Troca a lista inteira, como o PUT do Bling faz com a proposta.

    Atualizar item a item deixaria em `quote_items` uma linha que o vendedor
    removeu da tela — e o PDF mostraria um item que não está mais na proposta.
    """
    get_supabase().table("quote_items").delete().eq("quote_id", quote_id).execute()
    _insert_quote_items(quote_id, itens)


def _update_quote(quote_id: str, values: dict) -> None:
    get_supabase().table("quotes").update(values).eq("id", quote_id).execute()


def _load_lead_para_pdf(lead_id: str) -> dict | None:
    """Colunas que o documento imprime — mais largas que as de `_load_lead`.

    `razao_social` entra porque o orçamento é peça comercial: o cliente confere
    o nome que está na nota, não o apelido pelo qual o vendedor o salvou.
    """
    res = (get_supabase().table("leads")
           .select("id, name, razao_social, cnpj, email, phone, telefone_comercial")
           .eq("id", lead_id).limit(1).maybe_single().execute())
    return getattr(res, "data", None)


def _payment_method_name(method_id) -> str | None:
    """Descrição da forma de pagamento, do espelho — nunca da API do Bling.

    Ausência devolve None e o bloco some do PDF: forma de pagamento apagada do
    ERP depois do orçamento não pode impedir o vendedor de baixar o arquivo.
    """
    if not method_id:
        return None
    try:
        res = (get_supabase().table("bling_payment_methods")
               .select("descricao").eq("id", int(method_id)).limit(1).execute())
    except Exception:
        logger.warning("[QUOTES] lookup da forma de pagamento %s falhou",
                       method_id, exc_info=True)
        return None
    linhas = getattr(res, "data", None) or []
    return linhas[0].get("descricao") if linhas else None


def _seller_for(email: str | None) -> dict | None:
    """`{"nome", "email"}` para a assinatura do rodapé do PDF.

    O nome vem de `bling_sellers` via `bling_seller_map`; vendedor sem mapa sai
    só com o e-mail (o `pdf.py` junta com "·" o que existir), porque um rodapé
    com o contato do vendedor é melhor do que rodapé nenhum.
    """
    if not email:
        return None
    nome = None
    try:
        seller_id = _seller_id_for(email)
        if seller_id:
            res = (get_supabase().table("bling_sellers").select("nome")
                   .eq("id", int(seller_id)).limit(1).execute())
            linhas = getattr(res, "data", None) or []
            nome = linhas[0].get("nome") if linhas else None
    except Exception:
        logger.warning("[QUOTES] nome do vendedor %s indisponivel", email,
                       exc_info=True)
    return {"nome": nome or "", "email": email}


def _move_deal_to_proposal(deal_id: str) -> bool:
    """Move o card para "Proposta Enviada" — §6 da spec.

    NUNCA anda para trás: se o deal já está em `fechado_ganho`, `fechado_perdido`
    ou em qualquer etapa de `order_index` maior, não mexe. Um orçamento de
    recompra feito para um cliente já fechado puxaria o card de volta para o
    meio do funil, e o Kanban passaria a mentir sobre o que ainda está em aberto.

    A etapa é procurada DENTRO do pipeline do próprio deal: `key` é única por
    pipeline, não global (índice `idx_pipeline_stages_key_unique`), e sem o
    filtro o card iria para o funil de outra pessoa.
    """
    sb = get_supabase()
    deal = getattr(sb.table("deals").select("pipeline_id, stage_id")
                   .eq("id", deal_id).maybe_single().execute(), "data", None) or {}
    pipeline_id = deal.get("pipeline_id")
    if not pipeline_id:
        return False

    # Uma consulta só para as etapas do funil: precisamos do alvo E da posição
    # atual, e duas idas ao banco para a mesma tabela não pagam por si.
    etapas = getattr(sb.table("pipeline_stages").select("id, key, order_index")
                     .eq("pipeline_id", pipeline_id).execute(), "data", None) or []
    alvo = next((e for e in etapas if e.get("key") == _PROPOSAL_STAGE_KEY), None)
    if not alvo:
        # Funil sem a etapa (migration não aplicada, ou funil sem
        # `fechado_ganho`): o orçamento continua válido, só o card não anda.
        logger.info("[QUOTES] funil %s nao tem a etapa %s — deal %s fica onde esta",
                    pipeline_id, _PROPOSAL_STAGE_KEY, deal_id)
        return False

    atual = next((e for e in etapas if e.get("id") == deal.get("stage_id")), None)
    if atual and (atual.get("order_index") or 0) >= (alvo.get("order_index") or 0):
        return False

    agora = datetime.now(timezone.utc).isoformat()
    (sb.table("deals").update({"stage_id": alvo["id"], "updated_at": agora})
     .eq("id", deal_id).execute())
    return True


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------
async def _montar_itens(items: list[QuoteItemIn]) -> list[dict]:
    """Itens do corpo completados pelo espelho de produtos.

    O Bling recusa item sem `descricao` mesmo quando o `produto.id` vai junto —
    a mesma completude que o pedido de venda já faz, pelo mesmo motivo.
    """
    itens = [{
        "bling_product_id": i.bling_product_id,
        "codigo": i.codigo,
        "descricao": i.descricao or "",
        "unidade": i.unidade,
        "quantidade": i.quantidade,
        "valor_unitario": i.valor_unitario,
        "desconto_percentual": i.desconto_percentual,
    } for i in items]

    faltando = [i for i in itens if not i["descricao"]]
    if faltando:
        por_id = await asyncio.to_thread(
            _products_by_id, [i["bling_product_id"] for i in faltando])
        for item in faltando:
            p = por_id.get(item["bling_product_id"]) or {}
            item["descricao"] = p.get("nome") or "Item"
            item["codigo"] = item["codigo"] or p.get("codigo")
            item["unidade"] = item["unidade"] or p.get("unidade")
    return itens


def _linhas_de_itens(itens: list[dict]) -> list[dict]:
    """Itens do payload traduzidos para linhas de `quote_items`.

    `total` é gravado por item (e não recalculado na leitura) porque é o número
    que foi enviado ao ERP e impresso no PDF: recalcular depois abriria a chance
    de o documento divergir da proposta por uma diferença de arredondamento.
    """
    return [{
        "bling_product_id": i["bling_product_id"],
        "codigo": i.get("codigo"),
        "descricao": i["descricao"],
        "unidade": i.get("unidade"),
        "quantidade": float(_dec(i["quantidade"])),
        "valor_unitario": float(_dec(i["valor_unitario"])),
        "desconto_percentual": float(_dec(i.get("desconto_percentual"))),
        "total": float(item_total(i)),
        "ordem": ordem,
    } for ordem, i in enumerate(itens)]


def _contato_nao_resolvido(resolucao) -> JSONResponse:
    """409 no MESMO formato do `POST /api/bling/orders`.

    Nunca chuta o contato: sem match único por documento, decide o humano. Nada
    é criado aqui — nem contato, nem proposta, nem linha em `quotes`.
    """
    return JSONResponse({
        "error": "contact_unresolved",
        "status": resolucao.status,
        "reason": resolucao.reason,
        "candidates": resolucao.candidates,
    }, status_code=409)


def _erro_de_validacao(exc: BlingValidationError) -> JSONResponse:
    return JSONResponse({
        "error": "validation", "message": str(exc),
        "detail": exc.description, "type": exc.type,
    }, status_code=422)


def _numeros_do_corpo(body: QuoteIn, itens: list[dict]) -> dict:
    """Subtotal, desconto (em reais e como digitado), frete e total.

    Um lugar só para a aritmética do orçamento: POST e PUT recalculam do zero a
    partir do MESMO corpo que a tela usou para mostrar o resumo, e os dois
    precisam chegar ao mesmo número que `quote-state.ts` mostrou.
    """
    unidade = (body.discount.unidade if body.discount else "REAL") or "REAL"
    digitado = body.discount.valor if body.discount else 0

    subtotal = quote_subtotal(itens)
    desconto = resolve_discount(subtotal, unidade=unidade, valor=digitado)
    frete = normalize_freight(body.freight)
    return {
        "subtotal": subtotal,
        "discount_value": desconto,
        "discount_unit": unidade.upper(),
        "discount_input": normalize_discount_input(digitado),
        "freight": frete,
        "total": quote_total(itens, discount_value=desconto, freight=frete),
    }


def _kwargs_da_proposta(body: QuoteIn, *, contact_id: int, itens: list[dict],
                        numeros: dict, seller_id: int | None) -> dict:
    return {
        "contact_id": contact_id,
        "quoted_at": body.quoted_at,
        "itens": itens,
        "discount_value": numeros["discount_value"],
        "freight": numeros["freight"],
        "freight_mode": body.freight_mode,
        "method_id": body.payment.method_id,
        "terms": body.payment.terms,
        "seller_id": seller_id,
        "store_id": config.store_id(),
        "notes": body.notes,
        "internal_notes": body.internal_notes,
        # Vazio de propósito: não existe campo de "A/C" no formulário nem coluna
        # em `quotes` para guardá-lo (§3). O PDF deriva o dele do nome do lead
        # na hora de imprimir; mandar esse mesmo palpite para o ERP gravaria no
        # cadastro da proposta um dado que ninguém digitou.
        "aos_cuidados_de": "",
    }


# --------------------------------------------------------------------------
# POST /api/quotes
# --------------------------------------------------------------------------
@router.post("")
async def create_quote_endpoint(body: QuoteIn):
    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    resolucao = await contacts.resolve(lead)
    if resolucao.status != "linked":
        return _contato_nao_resolvido(resolucao)

    itens = await _montar_itens(body.items)
    numeros = _numeros_do_corpo(body, itens)
    seller_id = await asyncio.to_thread(_seller_id_for, body.created_by)

    try:
        async with BlingClient() as client:
            criada = await create_proposal(client, **_kwargs_da_proposta(
                body, contact_id=resolucao.contact_id, itens=itens,
                numeros=numeros, seller_id=seller_id))
    except BlingValidationError as exc:
        # Repetir payload invalido nunca conserta — e, sem proposta criada, nada
        # ficou pendurado no ERP.
        return _erro_de_validacao(exc)
    except TRANSIENT as exc:
        # Sem fila, ao contrário da venda: a proposta comercial não tem chave de
        # idempotência, então uma retentativa automática duplicaria a proposta
        # sem jeito de detectar. Quem decide tentar de novo é o vendedor.
        logger.warning("[QUOTES] proposta nao criada (Bling indisponivel): %s", exc)
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    # ---- daqui para baixo a proposta JA EXISTE no ERP ----
    linha = {
        "lead_id": body.lead_id,
        "deal_id": body.deal_id,
        "conversation_id": body.conversation_id,
        "created_by": body.created_by,
        "quoted_at": body.quoted_at,
        "status": "rascunho",
        "bling_situacao": "Rascunho",
        "bling_proposal_id": criada["bling_proposal_id"],
        "bling_proposal_number": criada["bling_proposal_number"],
        "bling_contact_id": resolucao.contact_id,
        "subtotal": float(numeros["subtotal"]),
        "discount_value": float(numeros["discount_value"]),
        "discount_unit": numeros["discount_unit"],
        "discount_input": float(numeros["discount_input"]),
        "freight": float(numeros["freight"]),
        "freight_mode": body.freight_mode,
        "total": float(numeros["total"]),
        "payment_method_id": body.payment.method_id,
        "payment_terms": "/".join(str(d) for d in (body.payment.terms or [0])),
        "notes": body.notes or None,
        "internal_notes": body.internal_notes or None,
    }

    try:
        quote_id = await asyncio.to_thread(_insert_quote, linha)
    except Exception:
        # Única falha pós-POST que vira erro de resposta — e ela CITA o id da
        # proposta: sem a linha em `quotes` o orçamento não existe para o CRM,
        # mas existe para o ERP, e o vendedor precisa saber disso antes de
        # clicar de novo (o clique cria a segunda).
        logger.exception("[QUOTES] proposta %s criada no Bling, mas a linha em "
                         "`quotes` NAO foi gravada", criada["bling_proposal_id"])
        return JSONResponse({
            "error": "quote_not_saved",
            "message": ("a proposta foi criada no Bling mas nao foi gravada no "
                        "CRM; nao tente de novo sem conferir o ERP"),
            "bling_proposal_id": criada["bling_proposal_id"],
        }, status_code=502)

    # Best-effort a partir daqui: falha não pode virar retentativa, porque a
    # retentativa duplica a proposta.
    try:
        await asyncio.to_thread(_insert_quote_items, quote_id,
                                _linhas_de_itens(itens))
    except Exception:
        logger.exception("[QUOTES] orcamento %s gravado, mas falhou ao gravar "
                         "os itens", quote_id)

    if body.deal_id:
        try:
            await asyncio.to_thread(_move_deal_to_proposal, body.deal_id)
        except Exception:
            logger.exception("[QUOTES] orcamento %s criado, mas falhou ao mover "
                             "o deal %s para Proposta Enviada", quote_id,
                             body.deal_id)

    return JSONResponse({
        "id": quote_id,
        "bling_proposal_id": criada["bling_proposal_id"],
        "bling_proposal_number": criada["bling_proposal_number"],
        "total": float(numeros["total"]),
    }, status_code=201)


# --------------------------------------------------------------------------
# PUT /api/quotes/{id}
# --------------------------------------------------------------------------
@router.put("/{quote_id}")
async def update_quote_endpoint(quote_id: str, body: QuoteIn):
    quote = await asyncio.to_thread(_load_quote, quote_id)
    if not quote:
        return JSONResponse({"error": "quote_not_found"}, status_code=404)
    if quote.get("status") == "convertido":
        # Regra 1 do usuário: depois de convertido o orçamento não pode mais ser
        # editado. Ele virou documento histórico — mudá-lo alteraria a proposta
        # no Bling sem alterar o pedido de venda que nasceu dela.
        return JSONResponse({"error": "quote_converted"}, status_code=409)

    proposal_id = quote.get("bling_proposal_id")
    if not proposal_id:
        # Estado que a criação não produz (a linha só é gravada depois do 201),
        # mas que uma correção manual no banco produziria. Sem id não há o que
        # alterar no ERP, e gravar só no CRM seria divergência silenciosa.
        return JSONResponse({
            "error": "validation",
            "message": "orcamento sem proposta no Bling — nao ha o que alterar",
        }, status_code=422)

    lead = await asyncio.to_thread(_load_lead, body.lead_id)
    if not lead:
        return JSONResponse({"error": "lead_not_found"}, status_code=404)

    resolucao = await contacts.resolve(lead)
    if resolucao.status != "linked":
        return _contato_nao_resolvido(resolucao)

    itens = await _montar_itens(body.items)
    numeros = _numeros_do_corpo(body, itens)
    seller_id = await asyncio.to_thread(_seller_id_for, body.created_by)

    # A situação enviada no PUT é a que o orçamento já tem — o PUT altera o
    # conteúdo, não o estado. Mandar `Rascunho` fixo rebaixaria uma proposta já
    # enviada ao cliente.
    situacao = STATUS_SITUACAO.get(quote.get("status") or "rascunho", "Rascunho")

    try:
        async with BlingClient() as client:
            await update_proposal(client, proposal_id=int(proposal_id),
                                  situacao=situacao, **_kwargs_da_proposta(
                                      body, contact_id=resolucao.contact_id,
                                      itens=itens, numeros=numeros,
                                      seller_id=seller_id))
    except BlingValidationError as exc:
        return _erro_de_validacao(exc)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    try:
        await asyncio.to_thread(_update_quote, quote_id, {
            "lead_id": body.lead_id,
            "deal_id": body.deal_id,
            "quoted_at": body.quoted_at,
            "bling_contact_id": resolucao.contact_id,
            "subtotal": float(numeros["subtotal"]),
            "discount_value": float(numeros["discount_value"]),
            "discount_unit": numeros["discount_unit"],
            "discount_input": float(numeros["discount_input"]),
            "freight": float(numeros["freight"]),
            "freight_mode": body.freight_mode,
            "total": float(numeros["total"]),
            "payment_method_id": body.payment.method_id,
            "payment_terms": "/".join(str(d) for d in (body.payment.terms or [0])),
            "notes": body.notes or None,
            "internal_notes": body.internal_notes or None,
        })
    except Exception:
        # Aqui a exceção SOBE (500), diferente do POST: o PUT é seguro de
        # repetir — reenviá-lo não duplica nada no ERP — então a retentativa do
        # vendedor é justamente o que conserta a divergência.
        logger.exception("[QUOTES] proposta %s alterada no Bling, mas a linha "
                         "%s nao foi atualizada", proposal_id, quote_id)
        raise

    try:
        await asyncio.to_thread(_replace_quote_items, quote_id,
                                _linhas_de_itens(itens))
    except Exception:
        logger.exception("[QUOTES] orcamento %s atualizado, mas falhou ao "
                         "regravar os itens", quote_id)

    return JSONResponse({"id": quote_id, "total": float(numeros["total"])},
                        status_code=200)


# --------------------------------------------------------------------------
# PATCH /api/quotes/{id}/status
# --------------------------------------------------------------------------
@router.patch("/{quote_id}/status")
async def update_status_endpoint(quote_id: str, body: QuoteStatusIn):
    """Marca o estado do orçamento e espelha a situação no Bling.

    `situacao_sync: false` NÃO é erro: a situação do ERP é espelho, não fonte.
    Recusar a marcação local porque o Bling não respondeu deixaria o vendedor
    sem conseguir registrar que o cliente recusou a proposta.
    """
    status = (body.status or "").strip().lower()
    if status not in _STATUS_MANUAIS:
        return JSONResponse({
            "error": "validation",
            "message": (f"status invalido: {body.status!r} "
                        f"(use um de {', '.join(_STATUS_MANUAIS)})"),
        }, status_code=422)

    quote = await asyncio.to_thread(_load_quote, quote_id)
    if not quote:
        return JSONResponse({"error": "quote_not_found"}, status_code=404)
    if quote.get("status") == "convertido":
        return JSONResponse({"error": "quote_converted"}, status_code=409)

    situacao = STATUS_SITUACAO[status]
    proposal_id = quote.get("bling_proposal_id")
    sincronizado = False
    if proposal_id:
        try:
            async with BlingClient() as client:
                await set_situacao(client, proposal_id=int(proposal_id),
                                   situacao=situacao)
            sincronizado = True
        except Exception:
            logger.warning("[QUOTES] situacao %r nao espelhada na proposta %s",
                           situacao, proposal_id, exc_info=True)

    valores = {"status": status}
    if sincronizado:
        # `bling_situacao` é o espelho da última situação que CONSEGUIMOS
        # enviar. Gravá-la sem confirmação faria o CRM afirmar sobre o ERP algo
        # que o ERP não sabe.
        valores["bling_situacao"] = situacao
    await asyncio.to_thread(_update_quote, quote_id, valores)

    return JSONResponse({"status": status, "situacao_sync": sincronizado},
                        status_code=200)


# --------------------------------------------------------------------------
# POST /api/quotes/{id}/convert
# --------------------------------------------------------------------------
@router.post("/{quote_id}/convert")
async def convert_quote_endpoint(quote_id: str):
    """Orçamento aceito vira pedido de venda com um clique.

    A ORDEM é obrigatória e é o motivo de esta rota existir separada:

      1. 409 se já convertido.
      2. `create_order` — cria o pedido no Bling, grava `sales` + `sale_items`
         e move o deal para Fechado Ganho.
      3. `set_situacao(..., "Aprovado")`. Falha aqui NÃO desfaz a venda: loga e
         devolve 201 com `situacao_sync: false`.
      4. `UPDATE quotes` marcando a conversão.

    Se o passo 3 viesse antes do 2, uma falha na criação do pedido deixaria uma
    proposta marcada como aprovada sem venda nenhuma — mentira no ERP.
    """
    quote = await asyncio.to_thread(_load_quote, quote_id)
    if not quote:
        return JSONResponse({"error": "quote_not_found"}, status_code=404)
    if quote.get("status") == "convertido":
        return JSONResponse({"error": "already_converted",
                             "sale_id": quote.get("sale_id")}, status_code=409)

    itens = await asyncio.to_thread(_load_quote_items, quote_id)
    if not itens:
        return JSONResponse({
            "error": "validation",
            "message": "orcamento sem itens — nao ha o que vender",
        }, status_code=422)

    contact_id = quote.get("bling_contact_id")
    if not contact_id:
        # O vínculo foi gravado na criação; só falta se alguém o desfez depois.
        lead = await asyncio.to_thread(_load_lead, quote.get("lead_id"))
        if not lead:
            return JSONResponse({"error": "lead_not_found"}, status_code=404)
        resolucao = await contacts.resolve(lead)
        if resolucao.status != "linked":
            return _contato_nao_resolvido(resolucao)
        contact_id = resolucao.contact_id

    desconto = _money(_dec(quote.get("discount_value")))
    frete = normalize_freight(quote.get("freight"))

    # O frete ATRAVESSA a conversao: `build_order_payload` aprendeu `freight`
    # nesta entrega. Sem isso o pedido nasceria com `subtotal - desconto`
    # enquanto o orcamento fechou em `subtotal - desconto + frete`, e a
    # diferenca viraria nota emitida a menor e `sales.value` a menor — erro de
    # dinheiro que so apareceria na conferencia do financeiro.
    observacoes = (quote.get("notes") or "").strip()

    kwargs = {
        "lead_id": quote.get("lead_id"),
        "deal_id": quote.get("deal_id"),
        "conversation_id": quote.get("conversation_id"),
        "contact_id": int(contact_id),
        # A venda acontece HOJE, não na data em que o orçamento foi escrito: é
        # de hoje que os prazos de pagamento contam, e é hoje que a receita
        # entra no funil.
        "sold_at": datetime.now(timezone.utc).date().isoformat(),
        "sold_by": quote.get("created_by"),
        "itens": itens,
        "payment": {
            "method_id": (int(quote["payment_method_id"])
                          if quote.get("payment_method_id") else None),
            "terms": parse_terms(quote.get("payment_terms")),
        },
        "seller_id": await asyncio.to_thread(_seller_id_for, quote.get("created_by")),
        # Já em reais: `quotes.discount_value` guarda o desconto convertido, e
        # `apply_discount` com unidade REAL subtrai exatamente esse valor.
        "discount": ({"valor": float(desconto), "unidade": "REAL"}
                     if desconto > 0 else None),
        "notes": observacoes,
        # O mesmo par que a proposta comercial usou. Atencao ao nome: o pedido
        # de venda chama o enum de `fretePorConta` e a proposta de
        # `freteModalidade` — `build_order_payload` faz essa traducao.
        "freight": float(frete),
        "freight_mode": quote.get("freight_mode"),
        # Chave DETERMINÍSTICA a partir do orçamento: um duplo clique (ou uma
        # retentativa do vendedor depois de um timeout) reencontra o pedido já
        # criado em vez de criar o segundo. Mesmo formato de `jobs.enqueue`.
        "idempotency_key": f"orc-{str(quote_id).replace('-', '')[:16]}",
    }

    try:
        async with BlingClient() as client:
            venda = await create_order(client, **kwargs)
    except BlingValidationError as exc:
        return _erro_de_validacao(exc)
    except BlingError as exc:
        return JSONResponse({"error": "bling", "message": str(exc)}, status_code=502)

    # ---- daqui para baixo a VENDA JA EXISTE ----
    sincronizado = False
    proposal_id = quote.get("bling_proposal_id")
    if proposal_id:
        try:
            async with BlingClient() as client:
                await set_situacao(client, proposal_id=int(proposal_id),
                                   situacao=STATUS_SITUACAO["convertido"])
            sincronizado = True
        except Exception:
            logger.warning("[QUOTES] pedido %s criado, mas a proposta %s nao "
                           "foi marcada como Aprovada", venda.get("bling_order_id"),
                           proposal_id, exc_info=True)

    valores = {
        "status": "convertido",
        "sale_id": venda.get("sale_id"),
        "converted_at": datetime.now(timezone.utc).isoformat(),
    }
    if sincronizado:
        valores["bling_situacao"] = STATUS_SITUACAO["convertido"]
    try:
        await asyncio.to_thread(_update_quote, quote_id, valores)
    except Exception:
        # A venda existe. Propagar faria a UI mostrar erro, o vendedor clicar de
        # novo e — não fosse a chave de idempotência — nascer um segundo pedido.
        logger.exception("[QUOTES] venda %s criada, mas o orcamento %s nao foi "
                         "marcado como convertido", venda.get("sale_id"), quote_id)

    return JSONResponse({
        "sale_id": venda.get("sale_id"),
        "bling_order_id": venda.get("bling_order_id"),
        "situacao_sync": sincronizado,
    }, status_code=201)


# --------------------------------------------------------------------------
# GET /api/quotes/{id}/pdf
# --------------------------------------------------------------------------
def _numero_visivel(quote: dict) -> str:
    """Número do documento, com as mesmas quedas em cascata do `pdf.py`.

    O `numero` do Bling vem de um GET best-effort e pode não existir; nesse caso
    o id da proposta é o identificador que o vendedor consegue procurar no ERP.
    Sem nenhum dos dois, o nome do arquivo diz "sem-numero" (o PDF imprime "-",
    que não serve como nome de arquivo).
    """
    return str(quote.get("bling_proposal_number")
               or quote.get("bling_proposal_id") or "sem-numero")


def _parcelas_para_o_pdf(quote: dict) -> list[dict]:
    """As parcelas impressas, recalculadas do total gravado.

    `build_installments` é a mesma da venda e da proposta, então a lista sai
    idêntica à que foi enviada ao Bling. Recusa (total sem centavo para dividir)
    devolve lista vazia: o bloco de pagamento some do PDF em vez de a rota
    devolver 500 num arquivo que o vendedor só quer imprimir.
    """
    try:
        return build_installments(
            _money(_dec(quote.get("total"))),
            parse_terms(quote.get("payment_terms")),
            quote.get("payment_method_id"),
            str(quote.get("quoted_at") or "")[:10],
        )
    except Exception:
        logger.warning("[QUOTES] parcelas do orcamento %s nao puderam ser "
                       "recalculadas para o PDF", quote.get("id"), exc_info=True)
        return []


@router.get("/{quote_id}/pdf")
async def quote_pdf_endpoint(quote_id: str):
    quote = await asyncio.to_thread(_load_quote, quote_id)
    if not quote:
        return JSONResponse({"error": "quote_not_found"}, status_code=404)

    items = await asyncio.to_thread(_load_quote_items, quote_id)
    lead = await asyncio.to_thread(_load_lead_para_pdf, quote.get("lead_id")) or {}
    seller = await asyncio.to_thread(_seller_for, quote.get("created_by"))

    razao = lead.get("razao_social") or lead.get("name")
    # "A/C" só quando o nome da pessoa difere do nome que encabeça o documento —
    # repetir a razão social no A/C seria ruído.
    aos_cuidados = lead.get("name") if lead.get("name") != razao else ""

    # Lista EXPLÍCITA, e não `{**quote}`: espalhar a linha inteira carregaria
    # `internal_notes` — a anotação de margem e negociação do vendedor — para
    # dentro do documento que vai à mão do cliente.
    dados = {
        "id": quote.get("id"),
        "bling_proposal_id": quote.get("bling_proposal_id"),
        "bling_proposal_number": quote.get("bling_proposal_number"),
        "quoted_at": quote.get("quoted_at"),
        "subtotal": quote.get("subtotal"),
        "discount_value": quote.get("discount_value"),
        "freight": quote.get("freight"),
        "total": quote.get("total"),
        "notes": quote.get("notes"),
        "payment_terms": quote.get("payment_terms"),
        "payment_method_name": await asyncio.to_thread(
            _payment_method_name, quote.get("payment_method_id")),
        "installments": _parcelas_para_o_pdf(quote),
        "lead_nome": razao,
        "lead_documento": lead.get("cnpj"),
        "lead_email": lead.get("email"),
        "lead_telefone": lead.get("phone") or lead.get("telefone_comercial"),
        "aos_cuidados_de": aos_cuidados,
    }

    # `build_quote_pdf` é CPU pura (reportlab) e a rota é síncrona do ponto de
    # vista do vendedor — sai da thread do event loop para não travar os outros
    # requests enquanto desenha.
    pdf = await asyncio.to_thread(build_quote_pdf, dados, items, seller=seller)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="orcamento-{_numero_visivel(quote)}.pdf"'},
    )
