"""Fase 1 da sincronia Bling: webhook robusto e campos que o import nao gravava.

- contato desconhecido e buscado na hora (G2), pelo `BlingClient` da conta (o
  mesmo rate limit de 3 req/s);
- backoff por evento e `failed` reabrivel;
- situacao Cancelado/devolucao -> `status='cancelada'`, com reversao (B10/G4);
- frete, desconto e forma de pagamento do pedido (G7);
- vendedor pela cascata D8 com `vendedor_fonte`, sem tocar venda do CRM/manual
  nem `sold_by` ja preenchido (B1).

As duas contas sao exercitadas em cada regra que depende de espelho por conta.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import app.bling.orders as orders
import app.bling.pedido_import as pi
import app.bling.webhook_processor as wp
from app.bling.errors import BlingRateLimitError, BlingValidationError


@pytest.fixture(autouse=True)
def _contas(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    orders._cache_email_usuario.clear()


# --------------------------------------------------------------------------
# Banco falso que FILTRA de verdade (por .eq), por tabela
# --------------------------------------------------------------------------
class Q:
    def __init__(self, db, nome):
        self.db, self.nome = db, nome
        self.filtros = {}
        self.op = "select"
        self.payload = None
        self.on_conflict = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filtros[col] = val
        return self

    def in_(self, col, vals):
        self.filtros[col] = ("in", list(vals))
        return self

    def or_(self, expr):
        self.db.ors.append((self.nome, expr))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def lt(self, *_a):
        return self

    def gte(self, *_a):
        return self

    def lte(self, *_a):
        return self

    def upsert(self, payload, on_conflict=None):
        self.op, self.payload, self.on_conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def delete(self):
        self.op = "delete"
        return self

    def _casa(self, linha):
        for col, val in self.filtros.items():
            if isinstance(val, tuple) and val[0] == "in":
                if linha.get(col) not in val[1]:
                    return False
            elif linha.get(col) != val:
                return False
        return True

    def execute(self):
        class R:
            pass
        r = R()
        self.db.ops.append((self.nome, self.op, self.payload, dict(self.filtros)))
        if self.op == "select":
            linhas = [l for l in self.db.tabelas.get(self.nome, []) if self._casa(l)]
            r.data = (linhas[0] if linhas else None) if getattr(self, "single", False) else linhas
        elif self.op == "upsert" and self.nome == "sales":
            r.data = [{"id": "SALE-1"}]
        elif self.op == "update":
            r.data = [l for l in self.db.tabelas.get(self.nome, []) if self._casa(l)]
        else:
            r.data = []
        return r


class DB:
    def __init__(self, **tabelas):
        self.tabelas = tabelas
        self.ops = []
        self.ors = []

    def table(self, nome):
        return Q(self, nome)

    def upserts(self, nome):
        return [p for (n, op, p, _f) in self.ops if n == nome and op == "upsert"]

    def updates(self, nome):
        return [(p, f) for (n, op, p, f) in self.ops if n == nome and op == "update"]


def _usa(monkeypatch, db, *modulos):
    for m in modulos:
        monkeypatch.setattr(m, "get_supabase", lambda: db)


PEDIDO = {"id": 900, "numero": 77, "data": "2026-10-10", "total": 160.0,
          "contato": {"id": 555}, "situacao": {"id": 9},
          "transporte": {"frete": 10.0},
          "itens": [{"produto": {"id": 1}, "codigo": "A", "descricao": "Item A",
                     "quantidade": 3, "valor": 50.0, "desconto": 0}]}


def _pedido(**extra):
    p = dict(PEDIDO)
    p.update(extra)
    return p


def _upsert(db, pedido, conta="default", lead="L1"):
    asyncio.run(orders.upsert_from_bling(pedido, lead_id=lead,
                                         event_date="2026-10-10T10:00:00Z", account=conta))
    return db.upserts("sales")[-1]


# --------------------------------------------------------------------------
# Situacao -> status
# --------------------------------------------------------------------------
@pytest.mark.parametrize("conta", ["default", "secundaria"])
def test_situacao_cancelado_vira_venda_cancelada(monkeypatch, conta):
    db = DB(sales=[], bling_situacoes=[{"account": conta, "id": 12, "nome": "Cancelado"}])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(situacao={"id": 12}), conta)
    assert linha["status"] == "cancelada"
    assert linha["bling_situacao_nome"] == "Cancelado"


@pytest.mark.parametrize("nome", ["Devolvido", "Em devolução", "DEVOLUCAO PARCIAL", "Cancelada"])
def test_situacoes_de_devolucao_e_cancelamento_por_nome(monkeypatch, nome):
    db = DB(sales=[], bling_situacoes=[{"account": "secundaria", "id": 31, "nome": nome}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 31}), "secundaria")["status"] == "cancelada"


def test_situacao_e_lida_do_espelho_da_propria_conta(monkeypatch):
    """Situacao personalizada 31 e 'Devolvido' na conta 2 e 'Separacao' na 1."""
    db = DB(sales=[], bling_situacoes=[
        {"account": "secundaria", "id": 31, "nome": "Devolvido"},
        {"account": "default", "id": 31, "nome": "Separação"}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 31}), "default")["status"] == "registrada"
    assert _upsert(db, _pedido(situacao={"id": 31}), "secundaria")["status"] == "cancelada"


def test_cancelado_padrao_12_sem_espelho_ainda_cancela(monkeypatch):
    db = DB(sales=[], bling_situacoes=[])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 12}))["status"] == "cancelada"


def test_pedido_que_sai_do_cancelado_volta_a_registrada(monkeypatch):
    """Cancelado -> cancelada -> reaberto no Bling -> registrada."""
    db = DB(sales=[{"bling_account": "default", "bling_order_id": 900, "id": "SALE-1",
                    "origin": "bling", "status": "cancelada", "bling_situacao_id": 12,
                    "bling_situacao_nome": "Cancelado"}],
            bling_situacoes=[{"account": "default", "id": 6, "nome": "Em aberto"}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 6}))["status"] == "registrada"


def test_ciclo_completo_cancelado_reaberto(monkeypatch):
    sit = [{"account": "secundaria", "id": 12, "nome": "Cancelado"},
           {"account": "secundaria", "id": 9, "nome": "Atendido"}]
    vendas = []
    db = DB(sales=vendas, bling_situacoes=sit)
    _usa(monkeypatch, db, orders)

    l1 = _upsert(db, _pedido(situacao={"id": 9}), "secundaria")
    assert l1["status"] == "registrada"
    vendas.append({**l1, "id": "SALE-1"})
    l2 = _upsert(db, _pedido(situacao={"id": 12}), "secundaria")
    assert l2["status"] == "cancelada"
    vendas[0] = {**l2, "id": "SALE-1"}
    l3 = _upsert(db, _pedido(situacao={"id": 9}), "secundaria")
    assert l3["status"] == "registrada"


def test_cancelada_por_outro_motivo_nao_e_reaberta(monkeypatch):
    """`order.deleted` (ou cancelamento no CRM) com a situacao antiga 'Atendido':
    um evento posterior em situacao normal NAO desfaz esse cancelamento."""
    db = DB(sales=[{"bling_account": "default", "bling_order_id": 900, "id": "SALE-1",
                    "origin": "crm", "status": "cancelada", "bling_situacao_id": 9,
                    "bling_situacao_nome": "Atendido"}],
            bling_situacoes=[{"account": "default", "id": 9, "nome": "Atendido"}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(situacao={"id": 9}))["status"] == "cancelada"


# --------------------------------------------------------------------------
# Frete, desconto, pagamento
# --------------------------------------------------------------------------
@pytest.mark.parametrize("conta", ["default", "secundaria"])
def test_frete_do_pedido_e_gravado(monkeypatch, conta):
    db = DB(sales=[])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(transporte={"frete": 23.456}), conta)
    assert linha["freight"] == 23.46
    assert linha["value"] == 160.0, "value continua o total do pedido (com frete)"


def test_payload_sem_transporte_nao_zera_frete_existente(monkeypatch):
    db = DB(sales=[])
    _usa(monkeypatch, db, orders)
    p = _pedido()
    del p["transporte"]
    assert "freight" not in _upsert(db, p)


def test_desconto_real_e_percentual(monkeypatch):
    db = DB(sales=[])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(desconto={"valor": 15, "unidade": "REAL"}))["discount"] == 15.0
    # 10% sobre os itens (3 x 50 = 150)
    assert _upsert(db, _pedido(desconto={"valor": 10, "unidade": "PERCENTUAL"}))["discount"] == 15.0


def test_forma_e_prazos_de_pagamento_das_parcelas(monkeypatch):
    db = DB(sales=[])
    _usa(monkeypatch, db, orders)
    p = _pedido(parcelas=[
        {"dataVencimento": "2026-11-09", "valor": 80, "formaPagamento": {"id": 4321}},
        {"dataVencimento": "2026-12-09", "valor": 80, "formaPagamento": {"id": 4321}}])
    linha = _upsert(db, p)
    assert linha["payment_method_id"] == 4321
    assert linha["payment_terms"] == "30/60"


def test_pagamento_de_venda_do_crm_ja_preenchido_nao_e_reescrito(monkeypatch):
    db = DB(sales=[{"bling_account": "default", "bling_order_id": 900, "id": "SALE-1",
                    "origin": "crm", "status": "registrada", "payment_method_id": 1,
                    "payment_terms": "0", "sold_by": "joao@x.com"}])
    _usa(monkeypatch, db, orders)
    p = _pedido(parcelas=[{"dataVencimento": "2026-11-09", "formaPagamento": {"id": 4321}}])
    linha = _upsert(db, p)
    assert "payment_method_id" not in linha and "payment_terms" not in linha


# --------------------------------------------------------------------------
# Vendedor (cascata D8)
# --------------------------------------------------------------------------
def _db_vendedor(**extra):
    base = dict(
        sales=[],
        bling_seller_map=[
            {"account": "default", "bling_seller_id": 11, "user_email": "Joao@Cafe.com"},
            {"account": "secundaria", "bling_seller_id": 11, "user_email": "rural@cafe.com"},
            {"account": "default", "bling_seller_id": 22, "user_email": "contato@cafe.com"}],
        bling_contacts=[{"account": "default", "id": 555, "vendedor_id": 22}],
        leads=[{"id": "L1", "assigned_to": "uuid-ana"}],
    )
    base.update(extra)
    return DB(**base)


def test_vendedor_do_pedido_tem_prioridade(monkeypatch):
    db = _db_vendedor()
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(vendedor={"id": 11}))
    assert linha["sold_by"] == "joao@cafe.com"
    assert linha["vendedor_fonte"] == "bling_pedido"


def test_vendedor_do_pedido_usa_o_mapa_da_conta(monkeypatch):
    """O id 11 e um vendedor diferente em cada conta."""
    db = _db_vendedor()
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(vendedor={"id": 11}), "secundaria")
    assert linha["sold_by"] == "rural@cafe.com"


def test_sem_vendedor_no_pedido_cai_para_o_do_contato(monkeypatch):
    db = _db_vendedor()
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(vendedor={"id": 0}))
    assert linha["sold_by"] == "contato@cafe.com"
    assert linha["vendedor_fonte"] == "bling_contato"


def test_vendedor_do_pedido_sem_mapa_cai_para_o_contato(monkeypatch):
    db = _db_vendedor()
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(vendedor={"id": 99}))
    assert linha["vendedor_fonte"] == "bling_contato"


def test_sem_pedido_nem_contato_cai_para_o_responsavel_do_lead(monkeypatch):
    db = _db_vendedor(bling_contacts=[])
    _usa(monkeypatch, db, orders)
    monkeypatch.setattr(orders, "_email_do_usuario",
                        lambda uid: "ana@cafe.com" if uid == "uuid-ana" else None)
    linha = _upsert(db, _pedido())
    assert linha["sold_by"] == "ana@cafe.com"
    assert linha["vendedor_fonte"] == "lead_assigned"


def test_sem_nenhuma_fonte_nao_grava_vendedor(monkeypatch):
    db = _db_vendedor(bling_contacts=[], leads=[{"id": "L1", "assigned_to": None}])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido())
    assert "sold_by" not in linha and "vendedor_fonte" not in linha


@pytest.mark.parametrize("origem", ["crm", "manual"])
def test_venda_do_crm_ou_manual_nunca_tem_vendedor_reescrito(monkeypatch, origem):
    db = _db_vendedor(sales=[{"bling_account": "default", "bling_order_id": 900,
                              "id": "SALE-1", "origin": origem, "status": "registrada",
                              "sold_by": None}])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(vendedor={"id": 11}))
    assert "sold_by" not in linha and "vendedor_fonte" not in linha


def test_sold_by_ja_preenchido_nao_e_sobrescrito(monkeypatch):
    db = _db_vendedor(sales=[{"bling_account": "default", "bling_order_id": 900,
                              "id": "SALE-1", "origin": "bling", "status": "registrada",
                              "sold_by": "outro@cafe.com"}])
    _usa(monkeypatch, db, orders)
    linha = _upsert(db, _pedido(vendedor={"id": 11}))
    assert "sold_by" not in linha


def test_email_do_usuario_falha_sem_derrubar(monkeypatch):
    class SemAuth:
        def table(self, nome):
            return Q(DB(), nome)
    monkeypatch.setattr(orders, "get_supabase", lambda: SemAuth())
    assert orders._email_do_usuario("uuid-x") is None


# --------------------------------------------------------------------------
# Venda nova sem lead: erro claro, nao 23502 do Postgres
# --------------------------------------------------------------------------
def test_venda_nova_sem_lead_levanta_erro_claro(monkeypatch):
    db = DB(sales=[])
    _usa(monkeypatch, db, orders)
    with pytest.raises(orders.PedidoSemLead):
        asyncio.run(orders.upsert_from_bling(_pedido(), lead_id=None,
                                             event_date=None, account="secundaria"))
    assert db.upserts("sales") == []


def test_venda_existente_sem_lead_novo_mantem_o_lead_gravado(monkeypatch):
    db = DB(sales=[{"bling_account": "default", "bling_order_id": 900, "id": "SALE-1",
                    "origin": "bling", "status": "registrada", "lead_id": "L-OLD"}])
    _usa(monkeypatch, db, orders)
    assert _upsert(db, _pedido(), lead=None)["lead_id"] == "L-OLD"


# --------------------------------------------------------------------------
# Contato sob demanda (pedido_import)
# --------------------------------------------------------------------------
class Cliente:
    def __init__(self, respostas=None, erro=None):
        self.respostas = respostas or {}
        self.erro = erro
        self.gets = []

    async def get(self, path, params=None):
        self.gets.append(path)
        if self.erro:
            raise self.erro
        return {"data": self.respostas.get(path, {})}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


CONTATO_BLING = {"id": 777, "nome": "Cliente Novo", "numeroDocumento": "12.345.678/0001-90",
                 "celular": "(34) 99999-0000", "vendedor": {"id": 11}}


@pytest.mark.parametrize("conta", ["default", "secundaria"])
def test_contato_fora_do_espelho_e_buscado_e_gravado_na_conta(monkeypatch, conta):
    db = DB(bling_contacts=[])
    _usa(monkeypatch, db, pi)
    leads = []

    async def fake_ensure(contato, account):
        leads.append((contato["id"], contato["vendedor_id"], account))
        return "LEAD-NOVO"

    monkeypatch.setattr(pi, "ensure_lead", fake_ensure)
    cli = Cliente({"/contatos/777": CONTATO_BLING})

    lead = asyncio.run(pi.lead_do_pedido(cli, conta, {"contato": {"id": 777}}))

    assert lead == "LEAD-NOVO"
    assert cli.gets == ["/contatos/777"]
    gravado = db.upserts("bling_contacts")[0]
    assert gravado["account"] == conta and gravado["id"] == 777
    assert gravado["vendedor_id"] == 11, "o detalhe traz o vendedor do contato (D8)"
    assert leads == [(777, 11, conta)]


def test_contato_no_espelho_nao_chama_o_bling(monkeypatch):
    db = DB(bling_contacts=[{"account": "default", "id": 777, "nome": "X"}])
    _usa(monkeypatch, db, pi)

    async def fake_ensure(contato, account):
        return "LEAD-1"

    monkeypatch.setattr(pi, "ensure_lead", fake_ensure)
    cli = Cliente()
    assert asyncio.run(pi.lead_do_pedido(cli, "default", {"contato": {"id": 777}})) == "LEAD-1"
    assert cli.gets == []


def test_contato_inexistente_no_bling_devolve_none(monkeypatch):
    db = DB(bling_contacts=[])
    _usa(monkeypatch, db, pi)
    cli = Cliente(erro=BlingValidationError("nao encontrado", status=404))
    assert asyncio.run(pi.lead_do_pedido(cli, "default", {"contato": {"id": 1}})) is None


def test_erro_transitorio_ao_buscar_contato_sobe(monkeypatch):
    """429/5xx/teto: sobe, para o evento ir para o backoff (nao vira lead None)."""
    db = DB(bling_contacts=[])
    _usa(monkeypatch, db, pi)
    cli = Cliente(erro=BlingRateLimitError("429"))
    with pytest.raises(BlingRateLimitError):
        asyncio.run(pi.lead_do_pedido(cli, "default", {"contato": {"id": 1}}))


def test_importar_pedido_busca_detalhe_lead_e_projeta(monkeypatch):
    gravados = []

    async def fake_lead(cli, conta, pedido):
        return "LEAD-9"

    async def fake_upsert(pedido, lead_id, event_date, account):
        gravados.append((pedido["id"], lead_id, event_date, account))
        return "S"

    monkeypatch.setattr(pi, "lead_do_pedido", fake_lead)
    monkeypatch.setattr(pi, "upsert_from_bling", fake_upsert)
    cli = Cliente({"/pedidos/vendas/5": {"id": 5, "data": "2026-10-01"}})
    asyncio.run(pi.importar_pedido(cli, "secundaria", 5))
    assert gravados == [(5, "LEAD-9", "2026-10-01T00:00:00+00:00", "secundaria")]


def test_backfill_usa_a_busca_de_contato_sob_demanda(monkeypatch):
    import app.bling.backfill as bf
    chamadas = []

    async def fake_importar(cli, conta, order_id):
        chamadas.append((conta, order_id))

    monkeypatch.setattr(pi, "importar_pedido", fake_importar)
    asyncio.run(bf._importar(object(), "secundaria", 3))
    assert chamadas == [("secundaria", 3)]


# --------------------------------------------------------------------------
# Webhook: contato desconhecido, backoff, failed reabrivel, conta no update
# --------------------------------------------------------------------------
def _evento(conta="default", attempts=0, event="order.created"):
    return {"event_id": "E1", "account": conta, "event": event, "attempts": attempts,
            "status": "pending",
            "event_date": "2026-10-10T12:00:00Z",
            "payload": {"event": event, "date": "2026-10-10T12:00:00Z",
                        "data": {"id": 900, "contato": {"id": 777}}}}


@pytest.mark.parametrize("conta", ["default", "secundaria"])
def test_webhook_de_cliente_novo_busca_o_contato_em_vez_de_falhar(monkeypatch, conta):
    """O caso G2: contato criado hoje, espelho so atualiza a noite."""
    db = DB(bling_webhook_events=[_evento(conta)], bling_contacts=[], sales=[])
    _usa(monkeypatch, db, wp, pi)
    cli = Cliente({"/pedidos/vendas/900": {**PEDIDO, "contato": {"id": 777}},
                   "/contatos/777": CONTATO_BLING})
    monkeypatch.setattr(wp, "_new_client", lambda account: cli)

    resolvidos = []

    async def fake_resolve(account, contato):
        resolvidos.append((account, contato["id"]))
        return f"LEAD-{account}"

    projetados = []

    async def fake_upsert(pedido, lead_id, event_date, account):
        projetados.append((lead_id, account))

    monkeypatch.setattr(wp, "_resolve_lead", fake_resolve)
    monkeypatch.setattr(wp, "upsert_from_bling", fake_upsert)
    monkeypatch.setattr(wp, "venda_recente", lambda *_a: False)

    asyncio.run(wp.process_pending())

    assert cli.gets == ["/pedidos/vendas/900", "/contatos/777"]
    assert projetados == [(f"LEAD-{conta}", conta)]
    assert resolvidos == [(conta, 777)]
    assert db.upserts("bling_contacts")[0]["account"] == conta
    payload, filtros = db.updates("bling_webhook_events")[-1]
    assert payload["status"] == "done"
    assert filtros == {"event_id": "E1", "account": conta}, "PK e (account, event_id)"


def test_claim_respeita_next_attempt_at(monkeypatch):
    db = DB(bling_webhook_events=[])
    _usa(monkeypatch, db, wp)
    wp._claim()
    assert db.ors and db.ors[0][0] == "bling_webhook_events"
    assert db.ors[0][1].startswith("next_attempt_at.is.null,next_attempt_at.lte.")


def test_falha_agenda_a_proxima_tentativa_com_backoff(monkeypatch):
    db = DB(bling_webhook_events=[_evento("secundaria", attempts=2)])
    _usa(monkeypatch, db, wp)

    def explode(account):
        raise RuntimeError("erro qualquer")

    monkeypatch.setattr(wp, "_new_client", explode)
    antes = datetime.now(timezone.utc)
    asyncio.run(wp.process_pending())

    payload, filtros = db.updates("bling_webhook_events")[-1]
    assert payload["status"] == "pending" and payload["attempts"] == 3
    proxima = datetime.fromisoformat(payload["next_attempt_at"])
    esperado = timedelta(minutes=wp.BACKOFF_MINUTOS[2])
    assert antes + esperado - timedelta(seconds=5) <= proxima <= \
        datetime.now(timezone.utc) + esperado
    assert filtros["account"] == "secundaria"


def test_backoff_e_mais_longo_que_o_espelho_de_contatos_antigo():
    """Antes: 6 tentativas em ~6 minutos. Agora a fila espera horas antes de desistir."""
    assert sum(wp.BACKOFF_MINUTOS[: wp.MAX_ATTEMPTS - 1]) >= 6 * 60


def test_desistencia_grava_processed_at_para_a_reabertura(monkeypatch):
    db = DB(bling_webhook_events=[_evento(attempts=wp.MAX_ATTEMPTS - 1)])
    _usa(monkeypatch, db, wp)

    def explode(account):
        raise RuntimeError("erro qualquer")

    monkeypatch.setattr(wp, "_new_client", explode)
    asyncio.run(wp.process_pending())
    payload, _ = db.updates("bling_webhook_events")[-1]
    assert payload["status"] == "failed"
    assert payload["processed_at"]
    assert payload["next_attempt_at"] is None


def test_rate_limit_nao_gasta_tentativa(monkeypatch):
    db = DB(bling_webhook_events=[_evento(attempts=3)])
    _usa(monkeypatch, db, wp)

    def limite(account):
        raise BlingRateLimitError("3 req/s saturado")

    monkeypatch.setattr(wp, "_new_client", limite)
    asyncio.run(wp.process_pending())
    payload, _ = db.updates("bling_webhook_events")[-1]
    assert payload["status"] == "pending"
    assert payload["attempts"] == 3
    assert payload["next_attempt_at"]


def test_reabrir_falhas_limpa_o_agendamento(monkeypatch):
    db = DB(bling_webhook_events=[{"event_id": "E1", "account": "default", "status": "failed"}])
    _usa(monkeypatch, db, wp)
    assert wp.reabrir_falhas("default") == 1
    payload, _ = db.updates("bling_webhook_events")[-1]
    assert payload["next_attempt_at"] is None


# --------------------------------------------------------------------------
# Migration da fase (nao aplicada; so o conteudo)
# --------------------------------------------------------------------------
def test_migration_da_fase_1_e_aditiva_e_reexecutavel():
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[2] / "supabase" / "migrations"
           / "20261014_bling_sync_webhook_vendedor.sql").read_text(encoding="utf-8").lower()
    assert "add column if not exists vendedor_fonte text" in sql
    assert "add column if not exists discount numeric(12,2)" in sql
    assert "add column if not exists next_attempt_at timestamptz" in sql
    assert "set local lock_timeout" in sql
    # so aditiva: nenhum UPDATE/DELETE de dados fora do bloco de rollback comentado
    ativo = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "update " not in ativo and "delete " not in ativo
