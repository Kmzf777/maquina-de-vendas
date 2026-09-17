import asyncio

import app.bling.webhook_processor as wp


class FakeQuery:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.store.setdefault("eq_" + self.name, {})[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def update(self, payload):
        self.store.setdefault(self.name + "_updates", []).append(payload)
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = self.store.get("row_" + self.name, [])
        return r


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


class FakeClient:
    def __init__(self, pedido):
        self.pedido = pedido
        self.gets = []

    async def get(self, path, params=None):
        self.gets.append(path)
        return {"data": self.pedido}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


PEDIDO = {"id": 34215992, "numero": 1234, "data": "2026-08-18", "total": 267.0,
          "contato": {"id": 5845664414}, "situacao": {"id": 6},
          "itens": [{"produto": {"id": 123}, "codigo": "CAN-250",
                     "descricao": "Cafe 250g", "quantidade": 10,
                     "valor": 26.70, "desconto": 0}]}


def _evento(event="order.created", date="2026-08-18T12:00:00Z", data=None):
    return {"event_id": "E1", "event": event, "event_date": date, "attempts": 0,
            "payload": {"event": event, "date": date,
                        "data": data or {"id": 34215992, "contato": {"id": 5845664414}}}}


# Helpers do enunciado da Task 10: usados na regressao "conta vem da linha do
# evento", onde o foco do teste e _new_client/_contact_row, nao estas funcoes.
async def _none_async(*_a, **_k):
    return None


async def _ok_async(*_a, **_k):
    return None


def test_created_busca_o_pedido_completo_e_projeta(monkeypatch):
    """O payload do webhook nao traz itens — o GET e obrigatorio."""
    # Contato precisa existir no espelho para `_resolve_lead` ser chamado — sem
    # isso `_contact_row` (nao mockado aqui) devolve [] e o codigo toma o
    # ramo "ausente do espelho", nunca chegando a "LEAD-1".
    store = {"row_bling_webhook_events": [_evento()],
             "row_bling_contacts": {"id": 5845664414, "nome": "Cliente Teste"}}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    client = FakeClient(PEDIDO)
    monkeypatch.setattr(wp, "_new_client", lambda account: client)

    projetados = []

    async def fake_upsert(pedido, lead_id, event_date, account):
        projetados.append((pedido["id"], lead_id, event_date, account))
        return "SALE-1"

    async def fake_resolve_lead(account, contato):
        return "LEAD-1"

    async def fake_last_event(account, order_id):
        return None

    monkeypatch.setattr(wp, "upsert_from_bling", fake_upsert)
    monkeypatch.setattr(wp, "_resolve_lead", fake_resolve_lead)
    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)

    asyncio.run(wp.process_pending())

    assert client.gets == ["/pedidos/vendas/34215992"]
    assert projetados == [(34215992, "LEAD-1", "2026-08-18T12:00:00Z", wp.config.DEFAULT_ACCOUNT)]
    assert store["bling_webhook_events_updates"][0]["status"] == "done"


async def test_processador_usa_a_conta_da_linha_do_evento(monkeypatch):
    """A conta nao vem de loop nem de env: vem da propria linha do evento — a
    unica fonte que diz de forma inequivoca qual conta entregou o webhook."""
    usadas = []

    class FakeAccountClient:
        def __init__(self, account):   # duble exige a conta
            usadas.append(account)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _path):
            return {"data": {"id": 7, "contato": {"id": 1}}}

    monkeypatch.setattr(wp, "_new_client", lambda account: FakeAccountClient(account))
    monkeypatch.setattr(wp, "_last_event_date", _none_async)
    monkeypatch.setattr(wp, "_contact_row", lambda a, c: None)
    monkeypatch.setattr(wp, "upsert_from_bling", _ok_async)

    evento = {"event_id": "e1", "event": "order.created", "account": "secundaria"}
    await wp._handle_order(evento, {"data": {"id": 7}, "date": "2026-09-13T10:00:00Z"})
    assert usadas == ["secundaria"]


def test_contact_row_filtra_por_conta():
    assert wp._contact_filter("secundaria", 42) == {
        "account": "secundaria", "id": 42}


def test_evento_fora_de_ordem_e_descartado(monkeypatch):
    """A entrega do Bling nao e ordenada: um `updated` antigo pode chegar depois
    de um mais novo e reverteria a situacao do pedido."""
    store = {"row_bling_webhook_events": [_evento(date="2026-08-18T10:00:00Z")]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(wp, "_new_client", lambda account: FakeClient(PEDIDO))

    async def fake_last_event(account, order_id):
        return "2026-08-18T12:00:00Z"   # ja aplicamos um evento mais novo

    chamou = []

    async def fake_upsert(*a, **k):
        chamou.append(True)

    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)
    monkeypatch.setattr(wp, "upsert_from_bling", fake_upsert)

    asyncio.run(wp.process_pending())

    assert chamou == []
    assert store["bling_webhook_events_updates"][0]["status"] == "skipped"


def test_deleted_cancela_sem_buscar_o_pedido(monkeypatch):
    store = {"row_bling_webhook_events": [
        _evento(event="order.deleted", data={"id": 34215992})]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    client = FakeClient(PEDIDO)
    monkeypatch.setattr(wp, "_new_client", lambda account: client)

    cancelados = []

    async def fake_cancel(order_id, event_date, account):
        cancelados.append(order_id)

    async def fake_last_event(account, order_id):
        return None

    monkeypatch.setattr(wp, "cancel_from_bling", fake_cancel)
    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)

    asyncio.run(wp.process_pending())

    assert cancelados == [34215992]
    assert client.gets == [], "deleted nao precisa buscar o pedido"


def test_deleted_cancela_com_a_conta_do_evento(monkeypatch):
    """`cancel_from_bling` tem que receber a MESMA conta que entregou o
    `.deleted` — sem isso a venda seria cancelada (ou procurada) no CNPJ
    errado, ja que `_update_sale` filtra por `bling_account`."""
    evento = _evento(event="order.deleted", data={"id": 555})
    evento["account"] = "secundaria"
    store = {"row_bling_webhook_events": [evento]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    monkeypatch.setattr(wp, "_new_client", lambda account: FakeClient(PEDIDO))

    cancelados = []

    async def fake_cancel(order_id, event_date, account):
        cancelados.append((order_id, account))

    async def fake_last_event(account, order_id):
        return None

    monkeypatch.setattr(wp, "cancel_from_bling", fake_cancel)
    monkeypatch.setattr(wp, "_last_event_date", fake_last_event)

    asyncio.run(wp.process_pending())

    assert cancelados == [(555, "secundaria")]


def test_product_event_atualiza_o_espelho(monkeypatch):
    store = {"row_bling_webhook_events": [
        {"event_id": "E2", "event": "product.updated", "attempts": 0,
         "event_date": "2026-08-18T12:00:00Z",
         "payload": {"event": "product.updated", "date": "2026-08-18T12:00:00Z",
                     "data": {"id": 123, "nome": "Cafe", "situacao": "A"}}}]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    aplicados = []

    async def fake_apply(event, payload, account):
        aplicados.append((event, payload["id"], account))

    monkeypatch.setattr(wp, "apply_product_event", fake_apply)

    asyncio.run(wp.process_pending())

    assert aplicados == [("product.updated", 123, wp.config.DEFAULT_ACCOUNT)]


def test_product_event_encaminha_a_conta_do_evento(monkeypatch):
    """Regressao do bug conhecido: `apply_product_event` exige 3 argumentos
    posicionais (event, payload, account) desde a Task 6. Um handler que passe
    so 2 quebra em TypeError. Usa uma conta NAO-default de proposito, para o
    teste nao passar por coincidencia quando os dois lados esquecem a conta."""
    store = {"row_bling_webhook_events": [
        {"event_id": "E3", "event": "product.updated", "attempts": 0,
         "event_date": "2026-08-18T12:00:00Z", "account": "secundaria",
         "payload": {"event": "product.updated", "date": "2026-08-18T12:00:00Z",
                     "data": {"id": 321, "nome": "Cafe", "situacao": "A"}}}]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))
    aplicados = []

    async def fake_apply(event, payload, account):
        aplicados.append((event, payload["id"], account))

    monkeypatch.setattr(wp, "apply_product_event", fake_apply)

    asyncio.run(wp.process_pending())

    assert aplicados == [("product.updated", 321, "secundaria")]


def test_falha_incrementa_attempts_e_mantem_pending(monkeypatch):
    store = {"row_bling_webhook_events": [_evento()]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))

    def explode(account):
        raise RuntimeError("bling fora")

    monkeypatch.setattr(wp, "_new_client", explode)

    asyncio.run(wp.process_pending())

    upd = store["bling_webhook_events_updates"][0]
    assert upd["status"] == "pending"
    assert upd["attempts"] == 1


def test_desiste_apos_o_maximo_de_tentativas(monkeypatch):
    evt = _evento()
    evt["attempts"] = wp.MAX_ATTEMPTS - 1
    store = {"row_bling_webhook_events": [evt]}
    monkeypatch.setattr(wp, "get_supabase", lambda: FakeSupabase(store))

    def explode(account):
        raise RuntimeError("bling fora")

    monkeypatch.setattr(wp, "_new_client", explode)

    asyncio.run(wp.process_pending())

    assert store["bling_webhook_events_updates"][0]["status"] == "failed"


def test_worker_registra_o_tick_de_webhook():
    from app.worker.main import TASK_SPECS
    spec = next(s for s in TASK_SPECS if s[0] == "bling-webhook")
    assert spec[1] == "event"
    assert spec[3] == 60
