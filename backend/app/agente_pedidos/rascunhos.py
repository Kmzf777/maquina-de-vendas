"""Rascunhos do agente de pedidos: validar, montar o payload Bling e o resumo.

Um rascunho NAO cria nada no Bling. Ele guarda no Redis (TTL 30 min) o payload
pronto, a conta, o tipo e o autor; so o clique de quem pediu, via
`confirmar.confirmar`, leva o payload ao Bling. O resumo devolvido ao bot e o
que a pessoa confere antes do clique, por isso sai dos MESMOS numeros do
payload (`orders.item_total`, `order_net_total`, as parcelas do proprio payload).
"""
import asyncio
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Awaitable, Callable, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.agente_pedidos import contas, leitura
from app.agente_pedidos.erros import erro
from app.bling import contacts, orders
from app.bling.errors import BlingError, BlingValidationError

TTL = 30 * 60
CHAVE = "agente_pedidos:rascunho:{}"
_ID_RE = re.compile(r"^[0-9a-f]{12}$")
_TZ = ZoneInfo("America/Sao_Paulo")


def get_redis():
    """Mesmo cliente Redis da trava de contato (`decode_responses=True`)."""
    return contacts._get_redis()


def hoje() -> str:
    return datetime.now(_TZ).date().isoformat()


def id_valido(id_: str) -> bool:
    return bool(_ID_RE.match(id_ or ""))


# --------------------------------------------------------------------------
# Corpos de entrada
# --------------------------------------------------------------------------
def _data_iso(valor: str | None) -> str | None:
    if valor is None or valor == "":
        return None
    try:
        return date.fromisoformat(str(valor)).isoformat()
    except ValueError as exc:
        raise ValueError("data no formato AAAA-MM-DD") from exc


class AutorIn(BaseModel):
    discord_id: str = Field(min_length=1)
    nome: str = Field(min_length=1)


class DescontoIn(BaseModel):
    valor: float = Field(gt=0)
    unidade: Literal["REAL", "PERCENTUAL"]


class ItemVendaIn(BaseModel):
    produto_id: int
    quantidade: float = Field(gt=0)
    desconto_percentual: float | None = Field(default=None, ge=0, le=100)
    valor_unitario: float | None = Field(default=None, gt=0)


class RascunhoVendaIn(BaseModel):
    conta: str
    cliente_id: int
    itens: list[ItemVendaIn] = Field(min_length=1)
    desconto: DescontoIn | None = None
    frete: float | None = Field(default=None, ge=0)
    forma_pagamento_id: int
    prazos: list[int] = Field(default_factory=lambda: [0])
    vendedor_id: int | None = None
    data: str | None = None
    observacoes: str | None = None
    observacoes_internas: str | None = None
    autor: AutorIn

    @field_validator("data")
    @classmethod
    def _data(cls, v):
        return _data_iso(v)

    @field_validator("prazos")
    @classmethod
    def _prazos(cls, v):
        if any(d < 0 for d in v):
            raise ValueError("prazos em dias, nunca negativos")
        return v


class ItemCompraIn(BaseModel):
    produto_id: int
    quantidade: float = Field(gt=0)
    valor_unitario: float | None = Field(default=None, gt=0)


class RascunhoCompraIn(BaseModel):
    conta: str
    itens: list[ItemCompraIn] = Field(min_length=1)
    data_prevista: str | None = None
    observacoes: str | None = None
    autor: AutorIn

    @field_validator("data_prevista")
    @classmethod
    def _data(cls, v):
        return _data_iso(v)


class EnderecoIn(BaseModel):
    endereco: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    cep: str | None = None
    municipio: str | None = None
    uf: str | None = None


class RascunhoContatoIn(BaseModel):
    conta: str
    nome: str = Field(min_length=1)
    documento: str
    tipo: Literal["F", "J"] | None = None
    email: str | None = None
    telefone: str | None = None
    celular: str | None = None
    endereco: EnderecoIn | None = None
    autor: AutorIn


# --------------------------------------------------------------------------
# Ajudantes
# --------------------------------------------------------------------------
def _brl(valor) -> str:
    texto = f"{Decimal(str(valor)):,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _nota_interna(autor: AutorIn, extra: str | None = None) -> str:
    nota = f"Criado pelo agente de pedidos (Discord: {autor.nome})"
    return nota + (f"\n{extra.strip()}" if extra and extra.strip() else "")


def _resumo_vazio(conta: str) -> dict:
    return {
        "rotulo_conta": contas.rotulo(conta), "parte": None, "linhas": [],
        "subtotal": None, "desconto": None, "desconto_valor": None, "frete": None,
        "total": None, "parcelas": [], "vendedor": None, "forma_pagamento": None,
        "data_prevista": None, "observacoes": None, "contato": None, "avisos": [],
    }


def _produto_ativo(conta: str, produto_id: int) -> dict:
    p = leitura.produto(conta, produto_id)
    if not p or p.get("situacao") != "A":
        raise erro(404, "produto", f"produto {produto_id} não existe ou está inativo nesta conta")
    return p


def _linha(item: dict, preco_alterado: bool) -> dict:
    return {
        "descricao": item["descricao"], "codigo": item.get("codigo") or None,
        "quantidade": float(item["quantidade"]), "unidade": item.get("unidade") or "UN",
        "valor_unitario": float(item["valor_unitario"]),
        "desconto_percentual": float(item.get("desconto_percentual") or 0),
        "total": float(orders.item_total(item)), "preco_alterado": preco_alterado,
    }


# --------------------------------------------------------------------------
# Venda
# --------------------------------------------------------------------------
def preparar_venda(corpo: RascunhoVendaIn) -> dict:
    conta = contas.validar(corpo.conta)
    cliente = leitura.cliente(conta, corpo.cliente_id)
    if not cliente:
        raise erro(404, "cliente", f"cliente {corpo.cliente_id} não existe nesta conta")

    avisos: list[str] = []
    itens: list[dict] = []
    alterados: list[bool] = []
    for it in corpo.itens:
        p = _produto_ativo(conta, it.produto_id)
        preco_bling = p.get("preco")
        if it.valor_unitario is not None:
            valor = it.valor_unitario
        elif preco_bling is not None and Decimal(str(preco_bling)) > 0:
            valor = preco_bling
        else:
            raise erro(422, "preco", f"{p.get('nome')} está sem preço no Bling: informe o valor")
        alterado = (it.valor_unitario is not None and
                    (preco_bling is None or Decimal(str(valor)) != Decimal(str(preco_bling))))
        if alterado:
            avisos.append(f"Preço de {p.get('nome')} alterado: {_brl(valor)} "
                          f"(Bling: {_brl(preco_bling or 0)})")
        itens.append({
            "bling_product_id": int(p["id"]), "codigo": p.get("codigo") or "",
            "unidade": p.get("unidade") or "UN", "descricao": p.get("nome") or "",
            "quantidade": it.quantidade, "valor_unitario": valor,
            "desconto_percentual": it.desconto_percentual or 0,
        })
        alterados.append(alterado)

    forma = leitura.forma(conta, corpo.forma_pagamento_id)
    if not forma or forma.get("finalidade") not in (2, 3):
        raise erro(404, "forma_pagamento",
                   f"forma de pagamento {corpo.forma_pagamento_id} não existe nesta conta")
    vendedor = None
    if corpo.vendedor_id is not None:
        vendedor = leitura.vendedor(conta, corpo.vendedor_id)
        if not vendedor:
            raise erro(404, "vendedor", f"vendedor {corpo.vendedor_id} não existe nesta conta")

    data = corpo.data or hoje()
    desconto = corpo.desconto.model_dump() if corpo.desconto else None
    frete = corpo.frete or 0
    try:
        payload = orders.build_order_payload(
            contact_id=int(cliente["id"]), sold_at=data, itens=itens,
            payment={"method_id": int(forma["id"]), "terms": corpo.prazos or [0]},
            seller_id=int(vendedor["id"]) if vendedor else None,
            store_id=None, situacao_id=None, discount=desconto,
            notes=corpo.observacoes or "",
            internal_notes=_nota_interna(corpo.autor, corpo.observacoes_internas),
            freight=frete,
        )
    except BlingValidationError as exc:
        raise erro(422, "validacao", str(exc)) from exc

    subtotal = orders.order_total(itens)
    resumo = _resumo_vazio(conta)
    resumo.update({
        "parte": {"nome": cliente.get("nome") or "",
                  "documento": leitura.formatar_documento(cliente.get("doc_digits"))},
        "linhas": [_linha(i, a) for i, a in zip(itens, alterados)],
        "subtotal": float(subtotal),
        "desconto": payload.get("desconto"),
        "desconto_valor": float(subtotal - orders.apply_discount(subtotal, desconto)),
        "frete": float(orders._money(Decimal(str(frete)))),
        "total": float(orders.order_net_total(itens, desconto, frete)),
        "parcelas": [{"data": p["dataVencimento"], "valor": p["valor"]}
                     for p in payload["parcelas"]],
        "vendedor": vendedor.get("nome") if vendedor else None,
        "forma_pagamento": forma.get("descricao") or None,
        "observacoes": corpo.observacoes or None,
        "avisos": avisos,
    })
    return {"tipo": "venda", "conta": conta, "payload": payload, "resumo": resumo,
            "autor": corpo.autor.model_dump()}


# --------------------------------------------------------------------------
# Compra (à fábrica)
# --------------------------------------------------------------------------
CustoAoVivo = Callable[[str, int], Awaitable[Decimal | None]]


def novo_cliente_bling(conta: str):
    """Fábrica de `BlingClient` (os testes trocam por um duble)."""
    from app.bling.client import BlingClient
    return BlingClient(account=conta, max_attempts=2)


def _decimal_positivo(valor) -> Decimal | None:
    try:
        d = Decimal(str(valor))
    except Exception:  # noqa: BLE001 — valor estranho do Bling = sem custo
        return None
    return d if d > 0 else None


async def custo_ao_vivo(conta: str, produto_id: int) -> Decimal | None:
    """Preço de custo do produto lido AO VIVO no Bling (`GET /produtos/{id}`):
    `fornecedor.precoCusto` e, se zero/ausente, `precoCusto`."""
    async with novo_cliente_bling(conta) as client:
        resp = await client.get(f"/produtos/{int(produto_id)}")
    dados = resp.get("data") or {}
    return (_decimal_positivo((dados.get("fornecedor") or {}).get("precoCusto"))
            or _decimal_positivo(dados.get("precoCusto")))


async def preparar_compra(corpo: RascunhoCompraIn, custo: CustoAoVivo | None = None) -> dict:
    custo = custo or custo_ao_vivo
    conta = contas.validar(corpo.conta)
    fornecedor_id = contas.fabrica(conta)
    fabrica = await asyncio.to_thread(leitura.cliente, conta, fornecedor_id)

    data = hoje()
    avisos: list[str] = []
    itens: list[dict] = []
    linhas: list[dict] = []
    for it in corpo.itens:
        p = await asyncio.to_thread(_produto_ativo, conta, it.produto_id)
        nome = p.get("nome") or ""
        if it.valor_unitario is not None:
            valor = Decimal(str(it.valor_unitario))
            avisos.append(f"Valor de {nome} informado na mensagem: {_brl(valor)}")
        else:
            try:
                valor = await custo(conta, int(p["id"]))
            except BlingError as exc:
                raise erro(422, "custo", f"não consegui ler o custo de {nome} no Bling "
                                         f"({exc}): informe o valor") from exc
            if not valor:
                raise erro(422, "custo", f"sem preço de custo para {nome}: informe o valor")
        item = {"codigo": p.get("codigo") or "", "unidade": p.get("unidade") or "UN",
                "descricao": nome, "quantidade": it.quantidade, "valor_unitario": valor}
        itens.append({"produto": {"id": int(p["id"]), "codigo": p.get("codigo") or ""},
                      "descricao": nome, "unidade": item["unidade"],
                      "quantidade": float(it.quantidade), "valor": float(valor)})
        linhas.append(_linha(item, it.valor_unitario is not None))

    payload = {
        "fornecedor": {"id": fornecedor_id},
        "data": data,
        "dataPrevista": corpo.data_prevista or data,
        "itens": itens,
        "observacoes": corpo.observacoes or "",
        "observacoesInternas": _nota_interna(corpo.autor),
    }
    total = float(orders._money(sum((Decimal(str(l["total"])) for l in linhas), Decimal("0"))))
    resumo = _resumo_vazio(conta)
    resumo.update({
        "parte": {"nome": (fabrica or {}).get("nome") or "Fábrica",
                  "documento": leitura.formatar_documento((fabrica or {}).get("doc_digits"))},
        "linhas": linhas,
        "subtotal": total,
        "total": total,
        "data_prevista": payload["dataPrevista"],
        "observacoes": corpo.observacoes or None,
        "avisos": avisos,
    })
    return {"tipo": "compra", "conta": conta, "payload": payload, "resumo": resumo,
            "autor": corpo.autor.model_dump()}


# --------------------------------------------------------------------------
# Contato
# --------------------------------------------------------------------------
def _texto(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


def _endereco_texto(e: dict) -> str | None:
    rua = ", ".join(x for x in (e.get("endereco"), e.get("numero"), e.get("complemento")) if x)
    cidade = "/".join(x for x in (e.get("municipio"), e.get("uf")) if x)
    partes = [x for x in (rua, e.get("bairro"), cidade) if x]
    if e.get("cep"):
        partes.append(f"CEP {e['cep']}")
    return " - ".join(partes) or None


def preparar_contato(corpo: RascunhoContatoIn) -> dict:
    conta = contas.validar(corpo.conta)
    if not contacts.is_valid_document(corpo.documento):
        raise erro(422, "documento", f"CPF/CNPJ inválido: {corpo.documento}")
    digitos = contacts.doc_digits(corpo.documento)
    existente = leitura.contato_por_documento(conta, digitos)
    if existente:
        raise erro(409, "contato_existe",
                   f"já existe contato com este documento nesta conta: {existente.get('nome')} "
                   f"(id {existente.get('id')})",
                   contato={"id": int(existente["id"]), "nome": existente.get("nome") or ""})

    tipo = corpo.tipo or ("J" if len(digitos) == 14 else "F")
    nome = corpo.nome.strip()
    payload: dict = {"nome": nome, "numeroDocumento": digitos, "tipo": tipo}
    for campo in ("email", "telefone", "celular"):
        valor = _texto(getattr(corpo, campo))
        if valor:
            payload[campo] = valor
    endereco = {k: v.strip() for k, v in (corpo.endereco.model_dump() if corpo.endereco else {}).items()
                if isinstance(v, str) and v.strip()}
    if endereco.get("uf"):
        endereco["uf"] = endereco["uf"].upper()
    if endereco:
        payload["endereco"] = {"geral": endereco}

    documento = leitura.formatar_documento(digitos)
    resumo = _resumo_vazio(conta)
    resumo.update({
        "parte": {"nome": nome, "documento": documento},
        "contato": {"nome": nome, "documento": documento, "tipo": tipo,
                    "email": payload.get("email"), "telefone": payload.get("telefone"),
                    "celular": payload.get("celular"),
                    "endereco_texto": _endereco_texto(endereco) if endereco else None},
    })
    return {"tipo": "contato", "conta": conta, "payload": payload, "resumo": resumo,
            "autor": corpo.autor.model_dump()}


# --------------------------------------------------------------------------
# Guardar / carregar
# --------------------------------------------------------------------------
async def guardar(r: dict) -> dict:
    r = dict(r)
    r["id"] = secrets.token_hex(6)
    r["expira_em"] = (datetime.now(timezone.utc) + timedelta(seconds=TTL)).isoformat()
    await get_redis().set(CHAVE.format(r["id"]), json.dumps(r, ensure_ascii=False), ex=TTL)
    return r


async def carregar(id_: str) -> dict | None:
    if not id_valido(id_):
        return None
    bruto = await get_redis().get(CHAVE.format(id_))
    return json.loads(bruto) if bruto else None


async def apagar(id_: str) -> None:
    if id_valido(id_):
        await get_redis().delete(CHAVE.format(id_))


def resposta(r: dict) -> dict:
    """Corpo do 201 de POST /rascunhos/*: o que o bot mostra; o payload fica aqui."""
    return {"id": r["id"], "tipo": r["tipo"], "conta": r["conta"],
            "expira_em": r["expira_em"], "resumo": r["resumo"]}
