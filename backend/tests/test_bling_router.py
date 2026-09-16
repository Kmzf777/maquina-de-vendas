import asyncio

import pytest
from fastapi import HTTPException

import app.bling.router as br
from app.bling import config, contacts
from app.bling.contacts import Resolution
from app.bling.errors import BlingServerError, BlingValidationError


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.captured = {}

    def select(self, *_a, **kwargs):
        # `count="exact"` e como o catalogo paginado pede o total ao PostgREST
        # junto da pagina — sem chamada separada.
        if "count" in kwargs:
            self.captured["select_count"] = kwargs["count"]
        return self

    def eq(self, c, v):
        self.captured.setdefault("eq", {})[c] = v
        return self

    def in_(self, c, v):
        self.captured["in"] = (c, list(v))
        return self

    def or_(self, expr):
        self.captured["or"] = expr
        return self

    def update(self, values):
        self.captured["update"] = values
        return self

    def delete(self):
        # `unlink` deixou de ser UPDATE em leads e virou DELETE em
        # lead_bling_contacts (multi-conta): o vinculo agora e uma LINHA, nao uma
        # coluna, entao desvincular apaga a linha daquela conta em vez de anular
        # um campo. Sem este metodo o duble estoura AttributeError.
        self.captured["delete"] = True
        return self

    def ilike(self, c, v):
        self.captured["ilike"] = (c, v)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def range(self, start, end):
        self.captured["range"] = (start, end)
        return self

    def maybe_single(self):
        self.captured["maybe_single"] = True
        return self

    def execute(self):
        class R:
            pass
        r = R()
        if "range" in self.captured:
            start, end = self.captured["range"]
            r.data = self.rows[start:end + 1]
            r.count = len(self.rows) if self.captured.get("select_count") else None
        elif self.captured.get("maybe_single"):
            # Espelha o supabase-py real: .maybe_single() colapsa para UM dict
            # (ou None), nunca uma lista. `_seller_id_for`/`_load_lead` fazem
            # `row.get(...)` direto em cima de `res.data` -- sem este colapso
            # a duble devolveria a lista crua e `.get()` estouraria
            # AttributeError, um falso-negativo do teste, nao um bug do codigo.
            r.data = self.rows[0] if self.rows else None
            r.count = None
        else:
            r.data = self.rows
            r.count = None
        return r


class FakeSupabase:
    def __init__(self, por_tabela):
        self.por_tabela = por_tabela
        self.queries = []

    def table(self, name):
        q = FakeQuery(self.por_tabela.get(name, []))
        self.queries.append(q)
        return q


# O espelho de produtos e consultado pelo endpoint de pedido para completar a
# descricao dos itens (o Bling exige `descricao` mesmo com `produto.id`). Sem
# este duble, os testes de pedido bateriam no Supabase de verdade.
ESPELHO_PRODUTOS = {"bling_products": [
    {"id": 1, "nome": "Cafe Classico 250g", "codigo": "CAF250", "unidade": "UN"},
]}


def test_products_filtra_por_ativos_e_busca(monkeypatch):
    sb = FakeSupabase({"bling_products": [{"id": 1, "nome": "Cafe Classico 250g"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_products(q="classico", account=config.DEFAULT_ACCOUNT))

    assert out["data"][0]["nome"] == "Cafe Classico 250g"
    assert sb.queries[0].captured["eq"]["situacao"] == "A"


def test_products_sem_busca_nao_aplica_filtro_de_texto(monkeypatch):
    sb = FakeSupabase({"bling_products": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)
    asyncio.run(br.list_products(q=None, account=config.DEFAULT_ACCOUNT))
    assert "or" not in sb.queries[0].captured


def test_products_filtra_pela_conta_informada(monkeypatch):
    """Isolamento de dados: o combobox de uma venda na conta 2 nao pode sugerir
    produto da conta 1 -- catalogos sao independentes por CNPJ."""
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    sb = FakeSupabase({"bling_products": [{"id": 1, "nome": "Cafe"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    asyncio.run(br.list_products(q=None, account="secundaria"))

    assert sb.queries[0].captured["eq"]["account"] == "secundaria"


def test_products_conta_desconhecida_devolve_400(monkeypatch):
    sb = FakeSupabase({"bling_products": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.list_products(q=None, account="conta-que-nao-existe"))

    assert exc.value.status_code == 400


def test_busca_de_contato_sanitiza_o_termo():
    # Virgula e parentese COMPOEM a sintaxe do filtro `or` do PostgREST: sem
    # neutralizar, o resto do texto vira filtro.
    assert br._termo_seguro("Ltda, (ME)") == "Ltda   ME"


def test_contacts_search_filtra_no_espelho(monkeypatch):
    sb = FakeSupabase({"bling_contacts": [{"id": 1, "nome": "Empresa X"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.search_contacts(q="empresa", id=None, limit=20,
                                          account=config.DEFAULT_ACCOUNT))

    assert out["data"][0]["nome"] == "Empresa X"
    assert "empresa" in sb.queries[0].captured["or"].lower()


def test_contacts_search_sem_termo_nao_aplica_filtro_de_texto(monkeypatch):
    sb = FakeSupabase({"bling_contacts": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)
    asyncio.run(br.search_contacts(q=None, id=None, limit=20,
                                    account=config.DEFAULT_ACCOUNT))
    assert "or" not in sb.queries[0].captured


def test_contacts_search_por_id_filtra_por_igualdade(monkeypatch):
    # A tela de detalhe do lead precisa achar o contato vinculado mesmo sem
    # CNPJ no lead (vinculo por telefone/e-mail/escolha manual) — id e exato.
    sb = FakeSupabase({"bling_contacts": [{"id": 42, "nome": "Empresa Y"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.search_contacts(id=42, limit=20, account=config.DEFAULT_ACCOUNT))

    assert out["data"][0]["nome"] == "Empresa Y"
    assert sb.queries[0].captured["eq"]["id"] == 42


def test_contacts_search_por_id_ignora_filtro_de_texto(monkeypatch):
    # id e exato: combinar com o `or_` de texto nao faz sentido — id vence.
    sb = FakeSupabase({"bling_contacts": [{"id": 42, "nome": "Empresa Y"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    asyncio.run(br.search_contacts(q="qualquer coisa", id=42, limit=20,
                                    account=config.DEFAULT_ACCOUNT))

    assert "or" not in sb.queries[0].captured
    assert sb.queries[0].captured["eq"]["id"] == 42


def test_contacts_search_filtra_por_conta_junto_com_id(monkeypatch):
    """bling_contacts tem PK composta (account, id): o mesmo numero de id existe
    nas duas contas apontando para empresas diferentes -- filtrar so por id
    devolveria o contato errado quando as duas contas colidem no numero."""
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    sb = FakeSupabase({"bling_contacts": [{"id": 42, "nome": "Empresa da conta 2"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    asyncio.run(br.search_contacts(id=42, limit=20, account="secundaria"))

    assert sb.queries[0].captured["eq"]["id"] == 42
    assert sb.queries[0].captured["eq"]["account"] == "secundaria"


def test_payment_methods_so_recebimentos_e_ativas(monkeypatch):
    sb = FakeSupabase({"bling_payment_methods": [
        {"id": 45, "descricao": "Boleto", "situacao": 1, "finalidade": 2},
        {"id": 46, "descricao": "Fornecedor", "situacao": 1, "finalidade": 1},
        {"id": 47, "descricao": "Antiga", "situacao": 0, "finalidade": 2},
    ]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_payment_methods(account=config.DEFAULT_ACCOUNT))

    ids = [m["id"] for m in out["data"]]
    assert ids == [45], "so formas ativas com finalidade de recebimento"
    assert sb.queries[0].captured["eq"]["account"] == config.DEFAULT_ACCOUNT


def test_payment_methods_filtra_pela_conta_informada(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    sb = FakeSupabase({"bling_payment_methods": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    asyncio.run(br.list_payment_methods(account="secundaria"))

    assert sb.queries[0].captured["eq"]["account"] == "secundaria"


def test_sellers_lista_e_filtra_pela_conta_informada(monkeypatch):
    sb = FakeSupabase({"bling_sellers": [{"id": 1, "nome": "Vendedor A"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    out = asyncio.run(br.list_sellers(account=config.DEFAULT_ACCOUNT))

    assert out["data"][0]["nome"] == "Vendedor A"
    assert sb.queries[0].captured["eq"]["account"] == config.DEFAULT_ACCOUNT


# --------------------------------------------------------------------------
# _conta_valida: unico ponto onde o slug de conta (dado externo, vindo de
# query string ou corpo) vira BlingAccount ou 400. Ver router.py.
# --------------------------------------------------------------------------
def test_conta_valida_devolve_a_conta_configurada():
    conta = br._conta_valida(config.DEFAULT_ACCOUNT)
    assert conta.key == config.DEFAULT_ACCOUNT


def test_conta_valida_normaliza_espaco_e_maiuscula(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    conta = br._conta_valida("  SECUNDARIA  ")
    assert conta.key == "secundaria"


def test_conta_valida_slug_desconhecido_vira_400():
    """Slug errado e erro do CHAMADOR (400), nunca 500 — e a unica porta de
    entrada de dado externo neste modulo (ver docstring de _conta_valida)."""
    with pytest.raises(HTTPException) as exc:
        br._conta_valida("conta-que-nao-existe")
    assert exc.value.status_code == 400


# --------------------------------------------------------------------------
# _seller_id_for: mapeamento sold_by -> vendedor do ERP, agora por conta.
# --------------------------------------------------------------------------
def test_seller_id_for_filtra_por_email_e_conta(monkeypatch):
    sb = FakeSupabase({"bling_seller_map": [{"bling_seller_id": 7}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    resultado = br._seller_id_for("v@e.com", "secundaria")

    assert resultado == 7
    assert sb.queries[0].captured["eq"] == {"user_email": "v@e.com", "account": "secundaria"}


def test_seller_id_for_sem_email_devolve_none():
    # Regra preservada: vendedor sem mapeamento NESTA conta sai sem vendedor no
    # pedido, sem bloquear a venda — nao muda com a segunda conta.
    assert br._seller_id_for(None, config.DEFAULT_ACCOUNT) is None


# --------------------------------------------------------------------------
# _load_lead: Task 7 aposentou leads.bling_contact_id (vinculo agora mora em
# lead_bling_contacts, por conta) — o select nao pode mais projetar a coluna.
# --------------------------------------------------------------------------
def test_load_lead_nao_projeta_mais_bling_contact_id(monkeypatch):
    """FakeQuery.select() descarta a lista de colunas (so guarda kwargs), entao
    a checagem e no texto fonte — mesma tecnica de test_router_registrado_no_app,
    que ja evita depender de estado de runtime. Assercao POSITIVA (a chamada
    .select(...) exata esperada), nao uma checagem negativa de substring: a
    funcao tem um comentario que CITA o nome da coluna retirada para explicar
    o porque dela ter sumido, e uma checagem negativa pegaria o comentario."""
    import inspect

    fonte = inspect.getsource(br._load_lead)
    assert '.select("id, name, phone, telefone_comercial, email, cnpj")' in fonte


def test_criar_pedido_devolve_409_quando_contato_nao_resolve(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "cnpj": None})

    async def fake_resolve(lead, account):
        return Resolution("suggested", None, [{"id": 77, "nome": "Empresa X"}], "telefone")

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 409
    corpo = resp.body.decode()
    assert "contact_unresolved" in corpo
    assert "Empresa X" in corpo


def test_criar_pedido_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.create_order_endpoint(br.OrderIn(
            lead_id="L1", sold_at="2026-08-18",
            items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
            payment=br.PaymentIn(method_id=45, terms=[0]),
            account="conta-que-nao-existe",
        )))
    assert exc.value.status_code == 400


def test_criar_pedido_enfileira_quando_bling_esta_fora(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    async def fake_resolve(lead, account):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        raise BlingServerError("bling fora do ar")

    enfileirados = []

    async def fake_enqueue(kind, payload, sale_id=None, account=None):
        # `account` exigido de proposito (sem cair em silencio num default): e a
        # conta da LINHA do job que manda na retentativa, e sem ela o pedido da
        # conta 2 seria recriado no Bling da conta 1.
        enfileirados.append((kind, account))

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br.jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email, _account: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 202
    assert enfileirados == [("create_order", config.DEFAULT_ACCOUNT)]


def test_erro_de_validacao_nao_enfileira_e_devolve_422(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    async def fake_resolve(lead, account):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        raise BlingValidationError("quantidade invalida", description="itens[0]")

    enfileirados = []

    async def fake_enqueue(kind, payload, sale_id=None, account=None):
        # `account` exigido de proposito (sem cair em silencio num default): e a
        # conta da LINHA do job que manda na retentativa, e sem ela o pedido da
        # conta 2 seria recriado no Bling da conta 1.
        enfileirados.append((kind, account))

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br.jobs, "enqueue", fake_enqueue)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email, _account: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 422
    assert enfileirados == [], "erro de validacao nao pode virar retentativa"


def test_sucesso_devolve_201_com_numero_do_pedido(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    capturado = {}

    async def fake_resolve(lead, account):
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        capturado.update(k)
        return {"sale_id": "S1", "bling_order_id": 34215992, "bling_order_number": 1234}

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email, _account: None)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", deal_id="D1", conversation_id="CONV-9",
        sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 201
    assert "1234" in resp.body.decode()
    # A conversa de origem tem de atravessar o router ate a `sales`: e o vinculo
    # entre a venda e o atendimento que a gerou, que o POST /api/sales ja grava.
    assert capturado["conversation_id"] == "CONV-9"
    # O Bling recusa item sem `descricao` mesmo quando o `produto.id` vai junto:
    # a descricao tem de ser completada a partir do espelho antes do POST.
    assert capturado["itens"][0]["descricao"] == "Cafe Classico 250g"
    assert capturado["itens"][0]["codigo"] == "CAF250"
    # Conta default quando o corpo nao escolhe nenhuma — preserva o
    # comportamento de hoje sem exigir que o front ja mande o campo.
    assert capturado["account"] == config.DEFAULT_ACCOUNT


def test_criar_pedido_repassa_a_conta_para_resolve_seller_e_create_order(monkeypatch):
    """A conta escolhida pelo vendedor tem que atravessar TRES pontos -- a
    resolucao de contato, o mapeamento de vendedor e o create_order -- e os
    tres tem que concordar, senao o pedido sai atrelado ao CNPJ errado ou ao
    cadastro de vendedor errado."""
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1"})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    capturado = {}

    async def fake_resolve(lead, account):
        capturado["resolve_account"] = account
        return Resolution("linked", 555)

    async def fake_create(*a, **k):
        capturado.update(k)
        return {"sale_id": "S1", "bling_order_id": 1, "bling_order_number": 1}

    seller_chamadas = []

    def fake_seller_id_for(email, account):
        seller_chamadas.append((email, account))
        return None

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "create_order", fake_create)
    monkeypatch.setattr(br, "_seller_id_for", fake_seller_id_for)

    resp = asyncio.run(br.create_order_endpoint(br.OrderIn(
        lead_id="L1", sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
        account="secundaria",
    )))

    assert resp.status_code == 201
    assert capturado["resolve_account"] == "secundaria"
    assert capturado["account"] == "secundaria"
    assert seller_chamadas == [("v@e.com", "secundaria")]


def test_atualizar_pedido_devolve_409_quando_contato_nao_resolve(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "cnpj": None})

    async def fake_resolve(lead, account):
        return Resolution("suggested", None, [{"id": 77, "nome": "Empresa X"}], "telefone")

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)

    resp = asyncio.run(br.update_order_endpoint(34215992, br.OrderIn(
        lead_id="L1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 409
    corpo = resp.body.decode()
    assert "contact_unresolved" in corpo
    assert "Empresa X" in corpo


def test_atualizar_pedido_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.update_order_endpoint(34215992, br.OrderIn(
            lead_id="L1", sold_at="2026-08-18",
            items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
            payment=br.PaymentIn(method_id=45, terms=[0]),
            account="conta-que-nao-existe",
        )))
    assert exc.value.status_code == 400


def test_atualizar_pedido_devolve_202_quando_erro_e_transitorio(monkeypatch):
    """Erro transitorio no PUT NAO e recusa — e retentativa. Sem job: o frontend
    e que decide tentar de novo, nao ha marca de divergencia aqui."""
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    async def fake_resolve(lead, account):
        return Resolution("linked", 555)

    async def fake_update(*a, **k):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "update_order", fake_update)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email, _account: None)

    resp = asyncio.run(br.update_order_endpoint(34215992, br.OrderIn(
        lead_id="L1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 202
    corpo = resp.body.decode()
    assert "queued" not in corpo, "nada foi enfileirado: o PUT nao precisa de job"


def test_atualizar_pedido_erro_de_validacao_devolve_422_com_mensagem_original(monkeypatch):
    """E o caso central da task: o Bling recusa (pedido ja faturado) e a
    mensagem original tem que atravessar intacta para o frontend decidir."""
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    async def fake_resolve(lead, account):
        return Resolution("linked", 555)

    async def fake_update(*a, **k):
        raise BlingValidationError("pedido faturado nao aceita alteracao",
                                   description="situacao", type_="VALIDATION_ERROR")

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "update_order", fake_update)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email, _account: None)

    resp = asyncio.run(br.update_order_endpoint(34215992, br.OrderIn(
        lead_id="L1", sold_at="2026-08-18",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 422
    corpo = resp.body.decode()
    assert "pedido faturado nao aceita alteracao" in corpo
    assert "situacao" in corpo


def test_atualizar_pedido_sucesso_devolve_200(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "bling_contact_id": 555})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    capturado = {}

    async def fake_resolve(lead, account):
        return Resolution("linked", 555)

    async def fake_update(*a, **k):
        capturado.update(k)
        return {"data": {"id": 34215992}}

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "update_order", fake_update)
    monkeypatch.setattr(br, "_seller_id_for", lambda _email, _account: None)

    resp = asyncio.run(br.update_order_endpoint(34215992, br.OrderIn(
        lead_id="L1", sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
    )))

    assert resp.status_code == 200
    corpo = resp.body.decode()
    assert "34215992" in corpo
    assert capturado["order_id"] == 34215992
    # mesma completude de itens que o POST ja faz: descricao/codigo do espelho
    assert capturado["itens"][0]["descricao"] == "Cafe Classico 250g"
    assert capturado["itens"][0]["codigo"] == "CAF250"
    assert capturado["account"] == config.DEFAULT_ACCOUNT


def test_atualizar_pedido_repassa_a_conta_para_resolve_seller_e_update_order(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1"})
    sb = FakeSupabase(ESPELHO_PRODUTOS)
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    capturado = {}

    async def fake_resolve(lead, account):
        capturado["resolve_account"] = account
        return Resolution("linked", 555)

    async def fake_update(*a, **k):
        capturado.update(k)
        return {"data": {"id": 34215992}}

    seller_chamadas = []

    def fake_seller_id_for(email, account):
        seller_chamadas.append((email, account))
        return None

    monkeypatch.setattr(br.contacts, "resolve", fake_resolve)
    monkeypatch.setattr(br, "update_order", fake_update)
    monkeypatch.setattr(br, "_seller_id_for", fake_seller_id_for)

    resp = asyncio.run(br.update_order_endpoint(34215992, br.OrderIn(
        lead_id="L1", sold_at="2026-08-18", sold_by="v@e.com",
        items=[br.OrderItemIn(bling_product_id=1, quantidade=1, valor_unitario=10.0)],
        payment=br.PaymentIn(method_id=45, terms=[0]),
        account="secundaria",
    )))

    assert resp.status_code == 200
    assert capturado["resolve_account"] == "secundaria"
    assert capturado["account"] == "secundaria"
    assert seller_chamadas == [("v@e.com", "secundaria")]


# --------------------------------------------------------------------------
# POST /contacts: cria (ou reaproveita) o contato no Bling e vincula ao lead.
# --------------------------------------------------------------------------
def test_criar_contato_endpoint_sucesso_devolve_bling_contact_id_e_conta(monkeypatch):
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "name": "Cliente"})

    async def fake_create_contact(client, lead, dados, account):
        return 4321

    monkeypatch.setattr(br.contacts, "create_contact", fake_create_contact)

    resp = asyncio.run(br.create_contact_endpoint(br.ContactIn(
        lead_id="L1", nome="Cliente Ltda", numeroDocumento="11222333000181",
        email="cliente@empresa.com",
    )))

    # bling_contact_id continua sendo a chave (contrato com o frontend); account
    # e ADITIVO -- Task 11 nao pode quebrar quem ja le so a primeira chave.
    assert resp == {"bling_contact_id": 4321, "account": config.DEFAULT_ACCOUNT}


def test_criar_contato_endpoint_repassa_a_conta_do_corpo(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "name": "Cliente"})

    capturado = {}

    async def fake_create_contact(client, lead, dados, account):
        capturado["account"] = account
        assert "account" not in dados, "account e roteamento, nao campo do Bling"
        return 4321

    monkeypatch.setattr(br.contacts, "create_contact", fake_create_contact)

    resp = asyncio.run(br.create_contact_endpoint(br.ContactIn(
        lead_id="L1", nome="Cliente Ltda", numeroDocumento="11222333000181",
        email="cliente@empresa.com", account="secundaria",
    )))

    assert capturado["account"] == "secundaria"
    assert resp["account"] == "secundaria"


def test_criar_contato_endpoint_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.create_contact_endpoint(br.ContactIn(
            lead_id="L1", nome="Cliente Ltda", numeroDocumento="11222333000181",
            email="cliente@empresa.com", account="conta-que-nao-existe",
        )))
    assert exc.value.status_code == 400


def test_criar_contato_endpoint_erro_bling_generico_devolve_502_em_vez_de_500(monkeypatch):
    """Antes so BlingValidationError era pega; qualquer outro BlingError (ex.:
    BlingServerError, ou BlingNotConfigured de uma conta que ainda nao passou
    pelo OAuth) estourava 500 opaco. Com multi-conta isso deixa de ser teorico:
    a conta 2 pode existir configurada e ainda nao ter token nenhum."""
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "name": "Cliente"})

    async def fake_create_contact(client, lead, dados, account):
        raise BlingServerError("bling fora do ar")

    monkeypatch.setattr(br.contacts, "create_contact", fake_create_contact)

    resp = asyncio.run(br.create_contact_endpoint(br.ContactIn(
        lead_id="L1", nome="Cliente Ltda", numeroDocumento="11222333000181",
        email="cliente@empresa.com",
    )))

    assert resp.status_code == 502


def test_criar_contato_endpoint_validacao_preserva_status_e_mensagem(monkeypatch):
    # Regressao: a introducao do `except BlingError` generico nao pode capturar
    # BlingValidationError primeiro (BlingValidationError E-UM BlingError) --
    # a ordem dos except importa.
    monkeypatch.setattr(br, "_load_lead", lambda _id: {"id": "L1", "name": "Cliente"})

    async def fake_create_contact(client, lead, dados, account):
        raise BlingValidationError("documento invalido", status=422)

    monkeypatch.setattr(br.contacts, "create_contact", fake_create_contact)

    resp = asyncio.run(br.create_contact_endpoint(br.ContactIn(
        lead_id="L1", nome="Cliente Ltda", numeroDocumento="11222333000181",
        email="cliente@empresa.com",
    )))

    assert resp.status_code == 422
    assert "documento invalido" in resp.body.decode()


def test_link_endpoint_confirma_o_vinculo_na_conta_informada(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    chamadas = []

    async def fake_link(lead_id, contact_id, account):
        chamadas.append((lead_id, contact_id, account))

    monkeypatch.setattr(br.contacts, "link", fake_link)

    resp = asyncio.run(br.link_contact_endpoint(lead_id="lead-1", contact_id=999,
                                                 account="secundaria"))

    assert resp == {"linked": True}
    assert chamadas == [("lead-1", 999, "secundaria")]


def test_link_endpoint_usa_a_conta_default_quando_informada(monkeypatch):
    chamadas = []

    async def fake_link(lead_id, contact_id, account):
        chamadas.append(account)

    monkeypatch.setattr(br.contacts, "link", fake_link)

    asyncio.run(br.link_contact_endpoint(lead_id="lead-1", contact_id=999,
                                          account=config.DEFAULT_ACCOUNT))

    assert chamadas == [config.DEFAULT_ACCOUNT]


def test_link_endpoint_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.link_contact_endpoint(lead_id="lead-1", contact_id=999,
                                              account="conta-que-nao-existe"))
    assert exc.value.status_code == 400


def test_oauth_authorize_delega_para_begin_authorization(monkeypatch):
    """new_state + authorize_url colapsaram em begin_authorization (um unico
    caminho, mesma conta para os dois) -- o router so repassa a URL."""
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")

    async def fake_begin(account):
        assert account == config.DEFAULT_ACCOUNT
        return "https://bling.com.br/Api/v3/oauth/authorize?state=xyz"

    monkeypatch.setattr(br.auth, "begin_authorization", fake_begin)

    resp = asyncio.run(br.oauth_authorize(account=config.DEFAULT_ACCOUNT))

    assert resp == {"url": "https://bling.com.br/Api/v3/oauth/authorize?state=xyz"}


def test_oauth_authorize_repassa_a_conta_escolhida(monkeypatch):
    """begin_authorization recebe a MESMA conta do query param -- nunca a
    default por engano quando o admin esta conectando a conta 2. Chamar
    new_state/authorize_url em separado reabriria exatamente este risco -- por
    isso o router so pode chamar begin_authorization."""
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")

    chamadas = []

    async def fake_begin(account):
        chamadas.append(account)
        return "https://bling.com.br/Api/v3/oauth/authorize?state=xyz"

    monkeypatch.setattr(br.auth, "begin_authorization", fake_begin)

    asyncio.run(br.oauth_authorize(account="secundaria"))

    assert chamadas == ["secundaria"]


def test_oauth_authorize_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.oauth_authorize(account="conta-que-nao-existe"))
    assert exc.value.status_code == 400


def test_oauth_authorize_sem_credenciais_devolve_not_configured(monkeypatch):
    """bling-settings.tsx le body.error === "not_configured" para manter o
    banner de credenciais ausentes e desabilitar o botao Conectar/Reconectar --
    contrato existente que a introducao de contas nao pode quebrar. A regra
    agora e por CONTA (`conta.configured`, Task 1), nao mais
    `config.is_configured()` global."""
    monkeypatch.delenv("BLING_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)

    resp = asyncio.run(br.oauth_authorize(account=config.DEFAULT_ACCOUNT))

    assert resp.status_code == 400
    assert "not_configured" in resp.body.decode()


def test_oauth_callback_rejeita_state_invalido(monkeypatch):
    async def fake_consume(state):
        return None

    monkeypatch.setattr(br.auth, "consume_state", fake_consume)
    resp = asyncio.run(br.oauth_callback(code="c", state="ruim"))
    assert resp.status_code == 400
    assert "state_invalido" in resp.body.decode()


def test_oauth_callback_aceita_conta_vazia_como_valida_default(monkeypatch):
    """consume_state pode devolver "" (conta vazia, que config.account()
    normaliza para default) como resultado LEGITIMO de um state consumido --
    diferente de None (state invalido, inexistente ou ja usado). A checagem
    tem que ser `is None`, nunca truthiness: `not ""` e True, o que rejeitaria
    em silencio um state legitimo cuja conta e a string vazia."""
    async def fake_consume(state):
        return ""

    chamadas = []

    async def fake_exchange(code, account):
        chamadas.append((code, account))

    monkeypatch.setattr(br.auth, "consume_state", fake_consume)
    monkeypatch.setattr(br.auth, "exchange_code", fake_exchange)

    resp = asyncio.run(br.oauth_callback(code="c", state="st"))

    assert resp.status_code == 302
    assert chamadas == [("c", "")]


def test_oauth_callback_troca_o_code_na_conta_certa(monkeypatch):
    """O code trocado tem que ir para a MESMA conta que o state carregava --
    nunca a default por omissao, senao o token da conta 2 seria gravado como
    se fosse da conta 1 (o mesmo risco que o state, Task 4, fechou; nao pode
    reabrir aqui por causa de um argumento esquecido)."""
    async def fake_consume(state):
        return "secundaria"

    chamadas = []

    async def fake_exchange(code, account):
        chamadas.append((code, account))

    monkeypatch.setattr(br.auth, "consume_state", fake_consume)
    monkeypatch.setattr(br.auth, "exchange_code", fake_exchange)

    resp = asyncio.run(br.oauth_callback(code="c", state="st"))

    assert resp.status_code == 302
    assert chamadas == [("c", "secundaria")]


# --------------------------------------------------------------------------
# /status: formato ADITIVO (Task 4 fechou o gap que a propria Task 4 abriu --
# auth.status() virou lista por conta e este endpoint fazia {**estado, ...},
# o que quebraria com TypeError assim que fosse exercitado de verdade. So
# existia checagem de rota (test_router_expoe_as_rotas_esperadas), nunca uma
# chamada de verdade ao handler -- por isso o defeito nao apareceu antes.
# --------------------------------------------------------------------------
def test_status_expoe_enabled_e_connected_no_topo_do_json(monkeypatch):
    """Regressao do modo legado silencioso: use-bling-status.ts le body.enabled
    e body.connected direto do topo do JSON e colapsa os dois num booleano. Se
    estas duas chaves sumissem do topo (por exemplo devolvendo so a lista de
    contas, ou fazendo {**contas, ...}), as duas virariam undefined no
    frontend, o hook devolveria enabled:false, e blingGate cairia em
    mode:"legacy", canSubmit:true -- as vendas parariam de ir para o Bling SEM
    NENHUM ERRO na tela. NAO troque o formato deste endpoint para so a lista:
    a redundancia com `accounts` e proposital e existe para evitar exatamente
    essa regressao."""
    async def fake_status():
        return [{"account": "default", "connected": True}]

    monkeypatch.setattr(br.auth, "status", fake_status)
    monkeypatch.setattr(br.config, "enabled", lambda: True)

    saida = asyncio.run(br.bling_status())

    assert saida["enabled"] is True
    assert saida["connected"] is True


def test_status_expoe_configured_e_expiracoes_e_scope_no_topo_do_json(monkeypatch):
    """CRITICAL: frontend/src/components/config/bling-settings.tsx busca
    /api/bling/status DIRETO (nao via use-bling-status.ts) e le
    status.configured, status.access_expires_at, status.refresh_expires_at e
    status.scope no topo do JSON. Sem estas quatro chaves no topo:
    - `configured` vira undefined -> o banner "Credenciais do app Bling
      ausentes no servidor" fica preso ligado PARA SEMPRE, mesmo configurado,
      e o botao "Conectar ao Bling"/"Reconectar" fica DESABILITADO PARA
      SEMPRE (disabled={...!status.configured}) -- nenhum admin consegue
      autorizar conta nenhuma pela tela.
    - `access_expires_at`/`refresh_expires_at`/`scope` viram undefined -> os
      detalhes do token mostram "—" para sempre, e o aviso de expiracao do
      refresh_token (5 dias de antecedencia) NUNCA mais dispara.
    O envelope aditivo tem que carregar estas quatro chaves ALEM de
    enabled/connected/accounts -- nao e so um formato, e um contrato com
    um consumidor especifico."""
    async def fake_status():
        return [{
            "account": "default",
            "connected": True,
            "configured": True,
            "access_expires_at": "2026-09-20T00:00:00+00:00",
            "refresh_expires_at": "2026-10-10T00:00:00+00:00",
            "scope": "1 2 3",
        }]

    monkeypatch.setattr(br.auth, "status", fake_status)
    monkeypatch.setattr(br.config, "enabled", lambda: True)

    saida = asyncio.run(br.bling_status())

    assert saida["configured"] is True
    assert saida["access_expires_at"] == "2026-09-20T00:00:00+00:00"
    assert saida["refresh_expires_at"] == "2026-10-10T00:00:00+00:00"
    assert saida["scope"] == "1 2 3"


def test_status_accounts_carrega_uma_entrada_por_conta(monkeypatch):
    contas_fake = [
        {"account": "default", "connected": True},
        {"account": "secundaria", "connected": False},
    ]

    async def fake_status():
        return contas_fake

    monkeypatch.setattr(br.auth, "status", fake_status)
    monkeypatch.setattr(br.config, "enabled", lambda: True)

    saida = asyncio.run(br.bling_status())

    assert saida["accounts"] == contas_fake


def test_status_connected_no_topo_e_da_conta_default_nao_de_qualquer_uma(monkeypatch):
    """connected no topo precisa ser da conta DEFAULT especificamente, nao
    "existe alguma conta conectada". Com a default desconectada e uma segunda
    conta conectada, o topo tem que acusar False -- um refactor que trocasse
    isso por any(c["connected"] for c in contas) passaria despercebido sem
    este teste."""
    async def fake_status():
        return [
            {"account": "default", "connected": False},
            {"account": "secundaria", "connected": True},
        ]

    monkeypatch.setattr(br.auth, "status", fake_status)
    monkeypatch.setattr(br.config, "enabled", lambda: True)

    saida = asyncio.run(br.bling_status())

    assert saida["connected"] is False


def test_unlink_apaga_a_linha_da_conta(monkeypatch):
    """O vinculo virou LINHA em lead_bling_contacts, nao coluna em leads.

    Desvincular apaga a linha DAQUELA conta — nao pode encostar no vinculo que o
    mesmo lead tenha na outra conta, que e o caso do cliente com cadastro nos
    dois CNPJs.
    """
    sb = FakeSupabase({})
    monkeypatch.setattr(contacts, "get_supabase", lambda: sb)

    asyncio.run(contacts.unlink("lead-1", "secundaria"))

    q = sb.queries[0]
    assert q.captured["delete"] is True
    assert q.captured["eq"] == {"lead_id": "lead-1", "account": "secundaria"}


def test_unlink_endpoint_devolve_unlinked(monkeypatch):
    chamadas = []

    async def fake_unlink(lead_id, account):
        chamadas.append((lead_id, account))

    monkeypatch.setattr(br.contacts, "unlink", fake_unlink)

    resp = asyncio.run(br.unlink_contact_endpoint(lead_id="lead-1",
                                                   account=config.DEFAULT_ACCOUNT))

    assert resp == {"unlinked": True}
    assert chamadas == [("lead-1", config.DEFAULT_ACCOUNT)]


def test_unlink_endpoint_repassa_a_conta_informada(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    chamadas = []

    async def fake_unlink(lead_id, account):
        chamadas.append((lead_id, account))

    monkeypatch.setattr(br.contacts, "unlink", fake_unlink)

    resp = asyncio.run(br.unlink_contact_endpoint(lead_id="lead-1", account="secundaria"))

    assert resp == {"unlinked": True}
    assert chamadas == [("lead-1", "secundaria")]


def test_unlink_endpoint_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(br.unlink_contact_endpoint(lead_id="lead-1", account="conta-que-nao-existe"))
    assert exc.value.status_code == 400


async def test_catalogo_pagina_de_verdade_e_devolve_total(monkeypatch):
    # Diferente de /products (combobox, teto de 200, so ativos), /catalog e
    # para uma tela de listagem: precisa paginar de verdade e dizer o total.
    produtos = [{"id": i, "nome": f"Produto {i:02d}"} for i in range(1, 51)]
    sb = FakeSupabase({"bling_products": produtos})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    pagina2 = await br.list_catalog(q=None, situacao=None, page=2, limit=20,
                                     account=config.DEFAULT_ACCOUNT)

    assert len(pagina2["data"]) == 20
    assert pagina2["page"] == 2
    assert pagina2["total"] == 50
    assert pagina2["data"][0]["nome"] == "Produto 21"


async def test_catalogo_filtra_por_situacao_e_busca_quando_informados(monkeypatch):
    sb = FakeSupabase({"bling_products": [{"id": 1, "nome": "Cafe Classico 250g"}]})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    await br.list_catalog(q="classico", situacao="A", page=1, limit=50,
                           account=config.DEFAULT_ACCOUNT)

    assert sb.queries[0].captured["eq"]["situacao"] == "A"
    assert "classico" in sb.queries[0].captured["or"].lower()


async def test_catalogo_sem_filtros_nao_aplica_situacao_nem_busca(monkeypatch):
    # Diferente de /products, /catalog nao fixa situacao='A' — sem filtro
    # explicito, devolve o catalogo inteiro (ativos e inativos) DENTRO da
    # conta. O filtro de conta e o UNICO que se aplica sempre — isolamento de
    # dados entre CNPJs nao e opcional.
    sb = FakeSupabase({"bling_products": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    await br.list_catalog(q=None, situacao=None, page=1, limit=50,
                           account=config.DEFAULT_ACCOUNT)

    assert "situacao" not in sb.queries[0].captured["eq"]
    assert "or" not in sb.queries[0].captured


async def test_catalogo_filtra_pela_conta_informada(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    sb = FakeSupabase({"bling_products": []})
    monkeypatch.setattr(br, "get_supabase", lambda: sb)

    await br.list_catalog(q=None, situacao=None, page=1, limit=50, account="secundaria")

    assert sb.queries[0].captured["eq"]["account"] == "secundaria"


async def test_catalogo_conta_desconhecida_devolve_400():
    with pytest.raises(HTTPException) as exc:
        await br.list_catalog(q=None, situacao=None, page=1, limit=50,
                               account="conta-que-nao-existe")
    assert exc.value.status_code == 400


def test_router_registrado_no_app():
    """O router precisa estar montado no app.

    Guarda em NIVEL DE FONTE (mesma convencao de test_cadence_definition_api_2026_07_10):
    inspecionar `app.main.app.routes` em runtime e fragil a poluicao de modulos entre
    testes — o app pode chegar aqui parcialmente montado por outro teste, e ai a asserticao
    falha SO no runner do CI (foi exatamente o que derrubou o deploy em 21/08/2026).

    As rotas em si continuam cobertas pelos testes de comportamento deste arquivo."""
    import inspect
    import app.main as main_module

    src = inspect.getsource(main_module)
    assert "from app.bling.router import router as bling_router" in src
    assert "app.include_router(bling_router)" in src


def test_router_expoe_as_rotas_esperadas():
    """Prefixo e paths do proprio router (objeto isolado, imune a poluicao de modulos)."""
    from app.bling.router import router as bling_router

    rotas = {r.path for r in bling_router.routes}
    assert "/api/bling/products" in rotas
    assert "/api/bling/catalog" in rotas
    assert "/api/bling/orders" in rotas
    assert "/api/bling/status" in rotas
