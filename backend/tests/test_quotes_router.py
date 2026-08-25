"""Contrato HTTP de `/api/quotes` — os quatro estados que não podem escapar.

Este arquivo tranca o que o frontend consome e o que a integridade do ERP
depende:

* **409 ao editar um orçamento convertido** e **409 ao converter duas vezes.**
  Depois da conversão o orçamento é documento histórico: editá-lo mudaria a
  proposta no Bling sem mudar o pedido de venda que nasceu dela.
* **A ordem da conversão: venda ANTES da situação.** Se o PATCH de situação
  viesse primeiro, uma falha na criação do pedido deixaria uma proposta
  "Aprovada" sem venda nenhuma — mentira no ERP, e ninguém olhando.
* **Falha no PATCH não desfaz a venda.** O pedido já existe; derrubar aqui
  faria a UI mostrar erro e o vendedor tentar de novo, duplicando o pedido.
  Devolve 201 com `situacao_sync: false` e a divergência fica visível.

O e-mail obrigatório do `ContactIn` também é testado aqui (e não em
`test_bling_router.py`) porque é o mesmo item de trabalho: o formulário já
exige desde o commit `1d973c30`, mas barreira de navegador não é barreira.
"""
import inspect
from decimal import Decimal

import pytest
from pydantic import ValidationError

import app.quotes.router as qr
from app.bling.contacts import Resolution
from app.bling.errors import BlingServerError, BlingValidationError

LEAD = {"id": "L1", "name": "Empresa X", "cnpj": "24252228000137",
        "email": "compras@empresa.com", "phone": "5534999998888",
        "bling_contact_id": 555}

QUOTE_CONVERTIDO = {
    "id": "Q1", "lead_id": "L1", "deal_id": "D1", "status": "convertido",
    "bling_proposal_id": 987654, "bling_proposal_number": 13,
    "bling_contact_id": 555, "quoted_at": "2026-08-25", "total": "100.00",
    "payment_method_id": 45, "payment_terms": "0", "created_by": "v@e.com",
    "sale_id": "S1",
}

QUOTE_RASCUNHO = {**QUOTE_CONVERTIDO, "status": "rascunho", "sale_id": None}

ITENS_DA_QUOTE = [{
    "bling_product_id": 777, "codigo": "CAF250", "descricao": "Cafe Classico 250g",
    "unidade": "UN", "quantidade": "1", "valor_unitario": "100.00",
    "desconto_percentual": "0", "total": "100.00", "ordem": 0,
}]


def corpo(**over) -> qr.QuoteIn:
    base = dict(
        lead_id="L1", deal_id="D1", conversation_id="CONV-9",
        quoted_at="2026-08-25", created_by="v@e.com",
        items=[qr.QuoteItemIn(bling_product_id=777, codigo="CAF250",
                              descricao="Cafe Classico 250g", unidade="UN",
                              quantidade=1, valor_unitario=100.0,
                              desconto_percentual=0)],
        payment=qr.QuotePaymentIn(method_id=45, terms=[0]),
    )
    base.update(over)
    return qr.QuoteIn(**base)


@pytest.fixture
def db(monkeypatch):
    """Neutraliza TODO o I/O do router e devolve o que foi escrito.

    Os helpers de banco são funções de módulo justamente para isto: o teste
    troca a camada de persistência inteira sem simular o PostgREST, e o que
    sobra sendo exercitado é a decisão do endpoint — que é o que pode quebrar.
    """
    estado = {"inserted": None, "items": None, "updates": [], "deal": [],
              "ordem": []}

    monkeypatch.setattr(qr, "_load_lead", lambda _id: dict(LEAD))
    monkeypatch.setattr(qr, "_load_lead_para_pdf", lambda _id: dict(LEAD))
    monkeypatch.setattr(qr, "_products_by_id", lambda _ids: {})
    monkeypatch.setattr(qr, "_seller_id_for", lambda _email: 12)
    monkeypatch.setattr(qr, "_payment_method_name", lambda _id: "Boleto")
    monkeypatch.setattr(qr, "_seller_for",
                        lambda email: {"nome": "Vendedor", "email": email})
    monkeypatch.setattr(qr, "_load_quote_items", lambda _id: list(ITENS_DA_QUOTE))

    def _insert(row):
        estado["inserted"] = row
        return "Q1"

    def _insert_items(quote_id, itens):
        estado["items"] = itens

    def _update(quote_id, values):
        estado["updates"].append((quote_id, values))

    def _replace(quote_id, itens):
        estado["items"] = itens

    def _move(deal_id):
        estado["deal"].append(deal_id)
        return True

    monkeypatch.setattr(qr, "_insert_quote", _insert)
    monkeypatch.setattr(qr, "_insert_quote_items", _insert_items)
    monkeypatch.setattr(qr, "_update_quote", _update)
    monkeypatch.setattr(qr, "_replace_quote_items", _replace)
    monkeypatch.setattr(qr, "_move_deal_to_proposal", _move)

    async def fake_resolve(lead):
        return Resolution("linked", 555)

    monkeypatch.setattr(qr.contacts, "resolve", fake_resolve)

    async def fake_create_proposal(client, **kwargs):
        estado["ordem"].append("create_proposal")
        estado["proposal_kwargs"] = kwargs
        return {"bling_proposal_id": 987654, "bling_proposal_number": 13}

    async def fake_update_proposal(client, **kwargs):
        estado["ordem"].append("update_proposal")
        estado["proposal_kwargs"] = kwargs

    async def fake_set_situacao(client, *, proposal_id, situacao):
        estado["ordem"].append(f"set_situacao:{situacao}")

    async def fake_create_order(client, **kwargs):
        estado["ordem"].append("create_order")
        estado["order_kwargs"] = kwargs
        return {"sale_id": "S9", "bling_order_id": 34215992,
                "bling_order_number": 1234}

    monkeypatch.setattr(qr, "create_proposal", fake_create_proposal)
    monkeypatch.setattr(qr, "update_proposal", fake_update_proposal)
    monkeypatch.setattr(qr, "set_situacao", fake_set_situacao)
    monkeypatch.setattr(qr, "create_order", fake_create_order)
    return estado


# ---------------------------------------------------------------------------
# POST /api/quotes
# ---------------------------------------------------------------------------
async def test_criar_devolve_201_com_id_proposta_numero_e_total(db):
    resp = await qr.create_quote_endpoint(corpo())

    assert resp.status_code == 201
    import json
    dados = json.loads(resp.body)
    assert dados["id"] == "Q1"
    assert dados["bling_proposal_id"] == 987654
    assert dados["bling_proposal_number"] == 13
    assert dados["total"] == 100.0


async def test_criar_grava_a_linha_com_o_trio_do_desconto(db):
    """`discount_value` em reais (o que vai para o Bling e para o total) +
    `discount_unit`/`discount_input` (o que a tela reexibe na edição). Sem o
    par, um desconto digitado como 10% reabriria como "26,70" e o vendedor
    acharia que o sistema mudou o número dele."""
    await qr.create_quote_endpoint(
        corpo(discount=qr.QuoteDiscountIn(valor=10, unidade="PERCENTUAL")))

    linha = db["inserted"]
    assert linha["discount_value"] == 10.0
    assert linha["discount_unit"] == "PERCENTUAL"
    assert linha["discount_input"] == 10.0
    assert linha["subtotal"] == 100.0
    assert linha["total"] == 90.0


async def test_criar_grava_status_rascunho_e_os_vinculos(db):
    await qr.create_quote_endpoint(corpo())

    linha = db["inserted"]
    assert linha["status"] == "rascunho"
    assert linha["bling_situacao"] == "Rascunho"
    assert linha["lead_id"] == "L1"
    assert linha["deal_id"] == "D1"
    assert linha["conversation_id"] == "CONV-9"
    # `created_by` é a base do escopo por vendedor (§8): sem ele o orçamento
    # fica invisível para todo mundo que não for admin.
    assert linha["created_by"] == "v@e.com"
    assert linha["bling_contact_id"] == 555
    assert linha["payment_method_id"] == 45
    assert linha["payment_terms"] == "0"


async def test_criar_grava_os_itens_com_total_e_ordem(db):
    await qr.create_quote_endpoint(corpo(items=[
        qr.QuoteItemIn(bling_product_id=777, descricao="A", quantidade=2,
                       valor_unitario=10.0, desconto_percentual=10),
        qr.QuoteItemIn(bling_product_id=778, descricao="B", quantidade=1,
                       valor_unitario=5.55),
    ]))

    itens = db["items"]
    assert [i["ordem"] for i in itens] == [0, 1]
    assert itens[0]["total"] == 18.0
    assert itens[1]["total"] == 5.55


async def test_criar_devolve_409_quando_o_contato_nao_resolve(db, monkeypatch):
    """Mesmo contrato do POST /api/bling/orders: nada é criado — nem contato,
    nem proposta, nem linha em `quotes`. Quem decide é o humano."""
    async def fake_resolve(lead):
        return Resolution("suggested", None, [{"id": 77, "nome": "Empresa X"}],
                          "telefone")

    monkeypatch.setattr(qr.contacts, "resolve", fake_resolve)

    resp = await qr.create_quote_endpoint(corpo())

    assert resp.status_code == 409
    texto = resp.body.decode()
    assert "contact_unresolved" in texto
    assert "Empresa X" in texto
    assert db["inserted"] is None
    assert db["ordem"] == []


async def test_criar_devolve_404_quando_o_lead_nao_existe(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_lead", lambda _id: None)
    resp = await qr.create_quote_endpoint(corpo())
    assert resp.status_code == 404


async def test_criar_devolve_422_quando_o_bling_recusa_e_nada_e_gravado(db, monkeypatch):
    """Payload inválido não vira retentativa nem linha órfã em `quotes`."""
    async def fake_create(client, **kwargs):
        raise BlingValidationError("parcelas invalidas", description="parcelas")

    monkeypatch.setattr(qr, "create_proposal", fake_create)

    resp = await qr.create_quote_endpoint(corpo())

    assert resp.status_code == 422
    assert "parcelas invalidas" in resp.body.decode()
    assert db["inserted"] is None


async def test_criar_devolve_502_quando_o_bling_esta_fora(db, monkeypatch):
    """Diferente da venda, o orçamento NÃO tem fila: a proposta comercial não
    tem `numeroLoja` (nem campo equivalente) para servir de chave de
    idempotência, então uma retentativa automática duplicaria a proposta no ERP
    sem jeito de detectar. O vendedor tenta de novo quando quiser."""
    async def fake_create(client, **kwargs):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(qr, "create_proposal", fake_create)

    resp = await qr.create_quote_endpoint(corpo())

    assert resp.status_code == 502
    assert db["inserted"] is None


async def test_criar_move_o_deal_para_proposta_enviada(db):
    """§6: criar orçamento move o card. Sem isso o Kanban continua mostrando
    como "em contato" um cliente que já recebeu proposta."""
    await qr.create_quote_endpoint(corpo())
    assert db["deal"] == ["D1"]


async def test_falha_ao_mover_o_deal_nao_derruba_o_orcamento(db, monkeypatch):
    """A proposta já existe no ERP e a linha já está gravada. Card no stage
    errado é cosmético e corrigível na mão; um 500 aqui faria o vendedor tentar
    de novo e criar uma SEGUNDA proposta."""
    def explode(_deal_id):
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(qr, "_move_deal_to_proposal", explode)

    resp = await qr.create_quote_endpoint(corpo())

    assert resp.status_code == 201


async def test_falha_ao_gravar_itens_nao_derruba_o_orcamento(db, monkeypatch):
    """Mesma regra do `create_order`: depois do POST aceito, nada levanta."""
    def explode(_quote_id, _itens):
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(qr, "_insert_quote_items", explode)

    resp = await qr.create_quote_endpoint(corpo())

    assert resp.status_code == 201


async def test_descricao_do_item_e_completada_pelo_espelho(db, monkeypatch):
    """O Bling recusa item sem descrição mesmo com `produto.id` — mesma
    completude que o pedido de venda já faz."""
    monkeypatch.setattr(qr, "_products_by_id", lambda _ids: {
        777: {"id": 777, "nome": "Cafe Classico 250g", "codigo": "CAF250",
              "unidade": "UN"}})

    await qr.create_quote_endpoint(corpo(items=[
        qr.QuoteItemIn(bling_product_id=777, descricao="", quantidade=1,
                       valor_unitario=10.0)]))

    item = db["proposal_kwargs"]["itens"][0]
    assert item["descricao"] == "Cafe Classico 250g"
    assert item["codigo"] == "CAF250"
    assert item["unidade"] == "UN"


# ---------------------------------------------------------------------------
# PUT /api/quotes/{id}
# ---------------------------------------------------------------------------
async def test_editar_convertido_devolve_409_e_nao_toca_no_bling(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_CONVERTIDO))

    resp = await qr.update_quote_endpoint("Q1", corpo())

    assert resp.status_code == 409
    assert "quote_converted" in resp.body.decode()
    assert db["ordem"] == [], "convertido é imutável: nem PUT no Bling nem UPDATE"
    assert db["updates"] == []


async def test_editar_devolve_200_com_id_e_total(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.update_quote_endpoint("Q1", corpo())

    assert resp.status_code == 200
    import json
    assert json.loads(resp.body) == {"id": "Q1", "total": 100.0}
    assert db["ordem"] == ["update_proposal"]


async def test_editar_substitui_os_itens(db, monkeypatch):
    """O PUT no Bling troca a lista inteira; o CRM tem que fazer o mesmo, senão
    um item removido na tela continuaria em `quote_items` e o PDF mostraria um
    item que não está mais na proposta."""
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    await qr.update_quote_endpoint("Q1", corpo(items=[
        qr.QuoteItemIn(bling_product_id=778, descricao="B", quantidade=3,
                       valor_unitario=7.0)]))

    assert [i["bling_product_id"] for i in db["items"]] == [778]


async def test_editar_quote_inexistente_devolve_404(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: None)
    resp = await qr.update_quote_endpoint("Q1", corpo())
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/quotes/{id}/status
# ---------------------------------------------------------------------------
async def test_patch_de_status_espelha_a_situacao_no_bling(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.update_status_endpoint("Q1", qr.QuoteStatusIn(status="enviado"))

    assert resp.status_code == 200
    import json
    assert json.loads(resp.body) == {"status": "enviado", "situacao_sync": True}
    assert db["ordem"] == ["set_situacao:Pendente"]
    assert db["updates"][0][1]["status"] == "enviado"
    assert db["updates"][0][1]["bling_situacao"] == "Pendente"


async def test_patch_com_status_desconhecido_devolve_422(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.update_status_endpoint("Q1", qr.QuoteStatusIn(status="quase"))

    assert resp.status_code == 422
    assert db["ordem"] == []
    assert db["updates"] == []


async def test_patch_nao_pode_marcar_convertido_na_mao(db, monkeypatch):
    """`convertido` significa que existe uma venda com pedido no Bling. Deixar
    o PATCH gravá-lo produziria um orçamento marcado como vendido sem `sale_id`
    — e o 409 do convert passaria a barrar a conversão de verdade."""
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.update_status_endpoint("Q1",
                                           qr.QuoteStatusIn(status="convertido"))

    assert resp.status_code == 422
    assert db["updates"] == []


async def test_patch_em_orcamento_convertido_devolve_409(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_CONVERTIDO))

    resp = await qr.update_status_endpoint("Q1",
                                           qr.QuoteStatusIn(status="nao_aprovado"))

    assert resp.status_code == 409
    assert "quote_converted" in resp.body.decode()


async def test_patch_grava_o_status_mesmo_com_o_bling_fora(db, monkeypatch):
    """A situação no ERP é espelho, não fonte. Recusar a marcação local porque
    o Bling não respondeu deixaria o vendedor sem conseguir registrar que o
    cliente recusou a proposta."""
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    async def explode(client, **kwargs):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(qr, "set_situacao", explode)

    resp = await qr.update_status_endpoint("Q1",
                                           qr.QuoteStatusIn(status="nao_aprovado"))

    assert resp.status_code == 200
    import json
    assert json.loads(resp.body) == {"status": "nao_aprovado",
                                     "situacao_sync": False}
    valores = db["updates"][0][1]
    assert valores["status"] == "nao_aprovado"
    # `bling_situacao` é o espelho da última situação que CONSEGUIMOS enviar —
    # gravá-la sem confirmação faria o CRM afirmar algo que o ERP não sabe.
    assert "bling_situacao" not in valores


# ---------------------------------------------------------------------------
# POST /api/quotes/{id}/convert
# ---------------------------------------------------------------------------
async def test_converter_cria_a_venda_ANTES_de_mudar_a_situacao(db, monkeypatch):
    """A ordem é o coração desta rota (§4 da spec).

    Se o PATCH viesse primeiro, uma falha na criação do pedido deixaria uma
    proposta marcada como aprovada sem venda nenhuma — e nada no ERP denunciaria
    isso depois.
    """
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.convert_quote_endpoint("Q1")

    assert resp.status_code == 201
    assert db["ordem"] == ["create_order", "set_situacao:Aprovado"]


async def test_converter_devolve_sale_id_pedido_e_sincronismo(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.convert_quote_endpoint("Q1")

    import json
    assert json.loads(resp.body) == {"sale_id": "S9",
                                     "bling_order_id": 34215992,
                                     "situacao_sync": True}


async def test_converter_marca_a_quote_com_a_venda(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    await qr.convert_quote_endpoint("Q1")

    valores = db["updates"][-1][1]
    assert valores["status"] == "convertido"
    assert valores["sale_id"] == "S9"
    assert valores["converted_at"]


async def test_converter_duas_vezes_devolve_409(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_CONVERTIDO))

    resp = await qr.convert_quote_endpoint("Q1")

    assert resp.status_code == 409
    assert "already_converted" in resp.body.decode()
    assert db["ordem"] == [], "nem pedido no Bling, nem PATCH de situação"


async def test_falha_na_situacao_nao_desfaz_a_venda(db, monkeypatch):
    """O pedido já existe no Bling e a `sales` já foi gravada. Devolver erro
    faria o vendedor clicar de novo e criar um SEGUNDO pedido; `situacao_sync:
    false` deixa a divergência visível sem destruir nada."""
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    async def explode(client, **kwargs):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(qr, "set_situacao", explode)

    resp = await qr.convert_quote_endpoint("Q1")

    assert resp.status_code == 201
    import json
    dados = json.loads(resp.body)
    assert dados["situacao_sync"] is False
    assert dados["sale_id"] == "S9"
    # E a conversão continua registrada: a venda existe, então o orçamento está
    # convertido — independentemente do que o Bling achou da situação.
    assert db["updates"][-1][1]["status"] == "convertido"


async def test_falha_ao_criar_o_pedido_nao_converte_nem_toca_na_situacao(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    async def explode(client, **kwargs):
        raise BlingValidationError("estoque insuficiente")

    monkeypatch.setattr(qr, "create_order", explode)

    resp = await qr.convert_quote_endpoint("Q1")

    assert resp.status_code == 422
    assert db["ordem"] == []
    assert db["updates"] == [], "sem venda não há conversão"


async def test_converter_repassa_itens_e_parcelas_do_orcamento(db, monkeypatch):
    """O pedido nasce com o que foi PROPOSTO — itens, forma, prazos e o
    desconto de cabeçalho já em reais."""
    monkeypatch.setattr(qr, "_load_quote", lambda _id: {
        **QUOTE_RASCUNHO, "payment_terms": "30/60",
        "discount_value": "10.00", "discount_unit": "PERCENTUAL"})

    await qr.convert_quote_endpoint("Q1")

    kwargs = db["order_kwargs"]
    assert kwargs["payment"] == {"method_id": 45, "terms": [30, 60]}
    assert kwargs["itens"][0]["bling_product_id"] == 777
    assert kwargs["discount"] == {"valor": 10.0, "unidade": "REAL"}
    assert kwargs["lead_id"] == "L1"
    assert kwargs["deal_id"] == "D1"
    assert kwargs["contact_id"] == 555
    assert kwargs["sold_by"] == "v@e.com"


async def test_converter_quote_inexistente_devolve_404(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: None)
    resp = await qr.convert_quote_endpoint("Q1")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/quotes/{id}/pdf
# ---------------------------------------------------------------------------
async def test_pdf_sai_como_anexo_com_o_numero_no_nome(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.media_type == "application/pdf"
    assert resp.headers["content-disposition"] == (
        'attachment; filename="orcamento-13.pdf"')
    assert resp.body[:4] == b"%PDF"


async def test_pdf_cai_no_id_da_proposta_quando_nao_ha_numero(db, monkeypatch):
    """O `numero` vem de um GET best-effort — um orçamento cujo GET falhou tem
    que gerar PDF do mesmo jeito."""
    monkeypatch.setattr(qr, "_load_quote",
                        lambda _id: {**QUOTE_RASCUNHO, "bling_proposal_number": None})

    resp = await qr.quote_pdf_endpoint("Q1")

    assert resp.headers["content-disposition"] == (
        'attachment; filename="orcamento-987654.pdf"')


async def test_pdf_de_quote_inexistente_devolve_404(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: None)
    resp = await qr.quote_pdf_endpoint("Q1")
    assert resp.status_code == 404


async def test_pdf_recebe_o_que_precisa_e_nada_da_observacao_interna(db, monkeypatch):
    """`internal_notes` é anotação do vendedor e o PDF vai para a mão do
    cliente. O `build_quote_pdf` nem lê a chave — mas quem monta o dicionário é
    o router, e é aqui que um `notes = internal_notes` distraído vazaria.

    A asserção é sobre o DICIONÁRIO entregue, não sobre os bytes do PDF: o
    stream sai comprimido em produção, então procurar o texto no arquivo daria
    verde mesmo que o vazamento existisse.
    """
    capturado = {}

    def fake_pdf(quote, items, *, seller=None):
        capturado["quote"] = quote
        capturado["items"] = items
        capturado["seller"] = seller
        return b"%PDF-fake"

    monkeypatch.setattr(qr, "build_quote_pdf", fake_pdf)
    monkeypatch.setattr(qr, "_load_quote", lambda _id: {
        **QUOTE_RASCUNHO, "notes": "Entrega em duas remessas",
        "internal_notes": "MARGEM-INTERNA-XYZZY-42"})

    await qr.quote_pdf_endpoint("Q1")

    assert "MARGEM-INTERNA-XYZZY-42" not in str(capturado["quote"])
    assert capturado["quote"]["notes"] == "Entrega em duas remessas"
    # O que a tabela `quotes` não guarda e o documento precisa: dados do
    # cliente, nome da forma de pagamento e as parcelas já calculadas.
    assert capturado["quote"]["lead_nome"] == "Empresa X"
    assert capturado["quote"]["payment_method_name"] == "Boleto"
    assert capturado["quote"]["installments"], "as parcelas saem no PDF"
    assert capturado["items"] == ITENS_DA_QUOTE
    assert capturado["seller"] == {"nome": "Vendedor", "email": "v@e.com"}


# ---------------------------------------------------------------------------
# E-mail obrigatório no contato (item 7 da tarefa)
# ---------------------------------------------------------------------------
def test_contato_sem_email_e_recusado_pelo_pydantic():
    """O frontend já exige desde `1d973c30`, mas isso é barreira de navegador:
    um POST direto em `/api/bling/contacts` passaria reto e criaria no ERP o
    contato incompleto que a decisão 6 quer impedir."""
    import app.bling.router as br

    with pytest.raises(ValidationError) as exc:
        br.ContactIn(lead_id="L1", nome="Empresa X",
                     numeroDocumento="24252228000137")

    assert "e-mail" in str(exc.value).lower()


def test_contato_com_email_vazio_e_recusado():
    import app.bling.router as br

    with pytest.raises(ValidationError):
        br.ContactIn(lead_id="L1", nome="Empresa X",
                     numeroDocumento="24252228000137", email="   ")


@pytest.mark.parametrize("email", [
    "sem-arroba.com", "duplo@@dominio.com", "sem@dominio", "com espaco@d.com",
    "arroba@dominio.", "@dominio.com",
])
def test_email_com_formato_invalido_e_recusado(email):
    import app.bling.router as br

    with pytest.raises(ValidationError):
        br.ContactIn(lead_id="L1", nome="Empresa X",
                     numeroDocumento="24252228000137", email=email)


@pytest.mark.parametrize("email", [
    "compras@empresa.com", "jose.silva+nf@empresa.com.br",
    "joão@empresa.com", "a_b-c@sub.dominio.co",
])
def test_email_valido_passa(email):
    """Mesma regra sóbria do frontend (`bling-contact-form.ts`): acento, `+` e
    `_` passam. Recusar o e-mail real de um cliente trava a venda; deixar
    passar um endereço exótico não quebra nada — quem valida de verdade é o
    Bling e depois o servidor de e-mail."""
    import app.bling.router as br

    contato = br.ContactIn(lead_id="L1", nome="Empresa X",
                           numeroDocumento="24252228000137", email=email)
    assert contato.email == email


def test_email_e_normalizado_com_trim():
    import app.bling.router as br

    contato = br.ContactIn(lead_id="L1", nome="Empresa X",
                           numeroDocumento="24252228000137",
                           email="  compras@empresa.com  ")
    assert contato.email == "compras@empresa.com"


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------
def test_router_registrado_no_app():
    """Guarda em NÍVEL DE FONTE, mesma convenção de `test_bling_router.py`:
    inspecionar `app.main.app.routes` em runtime é frágil a poluição de módulos
    entre testes — o app pode chegar aqui parcialmente montado por outro teste,
    e aí a asserção falha SÓ no runner do CI."""
    import app.main as main_module

    src = inspect.getsource(main_module)
    assert "from app.quotes.router import router as quotes_router" in src
    assert "app.include_router(quotes_router)" in src


def test_router_expoe_as_rotas_do_contrato():
    from app.quotes.router import router as quotes_router

    rotas = {(r.path, tuple(sorted(r.methods))) for r in quotes_router.routes}
    assert ("/api/quotes", ("POST",)) in rotas
    assert ("/api/quotes/{quote_id}", ("PUT",)) in rotas
    assert ("/api/quotes/{quote_id}/status", ("PATCH",)) in rotas
    assert ("/api/quotes/{quote_id}/convert", ("POST",)) in rotas
    assert ("/api/quotes/{quote_id}/pdf", ("GET",)) in rotas


# ---------------------------------------------------------------------------
# Frete na conversao
# ---------------------------------------------------------------------------
async def test_converter_leva_o_frete_para_o_pedido_de_venda(db, monkeypatch):
    """O cliente aceitou o total COM frete; o pedido tem que nascer com ele.

    A primeira versao desta rota so mencionava o frete nas observacoes, porque
    `build_order_payload` nao tinha o campo. O efeito era silencioso e caro:
    nota emitida a menor e `sales.value` menor que o combinado, diferenca que so
    apareceria na conferencia do financeiro.
    """
    quote = {**QUOTE_RASCUNHO, "freight": "45.00", "freight_mode": 1}
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(quote))

    resp = await qr.convert_quote_endpoint("Q1")

    assert resp.status_code == 201
    assert db["order_kwargs"]["freight"] == 45.0
    assert db["order_kwargs"]["freight_mode"] == 1
    # O valor NAO fica so nas observacoes: a mencao em texto era a mitigacao
    # antiga e some agora que o campo existe de verdade.
    assert "Frete do orcamento" not in (db["order_kwargs"].get("notes") or "")


async def test_converter_sem_frete_nao_inventa_valor(db, monkeypatch):
    monkeypatch.setattr(qr, "_load_quote", lambda _id: dict(QUOTE_RASCUNHO))

    await qr.convert_quote_endpoint("Q1")

    assert db["order_kwargs"]["freight"] == 0.0
    assert db["order_kwargs"]["freight_mode"] is None
