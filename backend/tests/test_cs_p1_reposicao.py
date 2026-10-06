"""P1.4 — venda registrada pelo CRM via Bling (e venda nova do webhook) cria a Reposicao.

Diagnostico 7 da call de 01/10: `create_order` nao dispara `sale_created`, entao o card de
Reposicao nunca nascia e a cadencia de reposicao/kit (P6) ficava sem card.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import app.bling.orders as orders
import app.bling.webhook_processor as wp
import app.leads.reposicao as reposicao


class _Q:
    def __init__(self, sb, tabela):
        self.sb, self.tabela = sb, tabela

    def __getattr__(self, _nome):
        return lambda *_a, **_k: self

    def execute(self):
        return type("R", (), {"data": self.sb.linhas.get(self.tabela, [{"id": "SALE-1"}])})()


class _SB:
    def __init__(self, linhas=None):
        self.linhas = linhas or {}

    def table(self, nome):
        return _Q(self, nome)


class _Cliente:
    async def post(self, path, json=None):
        return {"data": {"id": 999}}

    async def get(self, path, params=None):
        return {"data": {"id": 999, "numero": 1, "situacao": {"id": 6}}}


def _conta(_account):
    return orders.config.BlingAccount(key="default", label="default", client_id="",
                                      client_secret="", store_id=None, situacao_id=None)


def _criar(monkeypatch, deal_id, movido=True, origem=None, ensure=None):
    chamadas = []
    monkeypatch.setattr(orders, "get_supabase", lambda: _SB())
    monkeypatch.setattr(orders.config, "account", _conta)
    monkeypatch.setattr(orders, "_move_deal_to_won", lambda _d: movido)
    monkeypatch.setattr(orders, "_deal_de_origem_do_lead", lambda _l: origem)
    monkeypatch.setattr(
        reposicao, "ensure_reposicao_deal",
        ensure or (lambda lead_id, deal_id=None: chamadas.append((lead_id, deal_id))))
    out = asyncio.run(orders.create_order(
        _Cliente(), lead_id="L1", deal_id=deal_id, contact_id=5, sold_at="2026-10-06",
        sold_by=None, itens=[{"bling_product_id": 1, "descricao": "Kit", "quantidade": 1,
                              "valor_unitario": 60, "desconto_percentual": 0}],
        payment={"method_id": 1, "terms": [0]}, seller_id=None))
    return out, chamadas


def test_create_order_cria_reposicao_depois_de_mover_o_deal(monkeypatch):
    out, chamadas = _criar(monkeypatch, "D1")
    assert out["bling_order_id"] == 999
    assert chamadas == [("L1", "D1")]


def test_create_order_sem_deal_usa_o_deal_de_origem_do_lead(monkeypatch):
    _out, chamadas = _criar(monkeypatch, None, origem="D-ATACADO")
    assert chamadas == [("L1", "D-ATACADO")]


def test_create_order_sem_deal_e_sem_origem_nao_cria(monkeypatch):
    _out, chamadas = _criar(monkeypatch, None, origem=None)
    assert chamadas == []


def test_create_order_deal_nao_movido_nao_cria(monkeypatch):
    _out, chamadas = _criar(monkeypatch, "D1", movido=False)
    assert chamadas == []


def test_create_order_excecao_na_reposicao_nao_desfaz_a_venda(monkeypatch):
    def explode(lead_id, deal_id=None):
        raise RuntimeError("funil fora")
    out, _ = _criar(monkeypatch, "D1", ensure=explode)
    assert out["sale_id"] == "SALE-1"


def test_deal_de_origem_e_o_mais_recente_de_funil_mapeado(monkeypatch):
    atacado = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
    sb = _SB({"deals": [
        {"id": "D-VALERIA", "pipeline_id": "outro", "created_at": "2026-10-01T00:00:00+00:00"},
        {"id": "D-VELHO", "pipeline_id": atacado, "created_at": "2026-08-01T00:00:00+00:00"},
        {"id": "D-NOVO", "pipeline_id": atacado, "created_at": "2026-09-01T00:00:00+00:00"},
    ]})
    monkeypatch.setattr(orders, "get_supabase", lambda: sb)
    assert orders._deal_de_origem_do_lead("L1") == "D-NOVO"


def test_deal_de_origem_sem_funil_mapeado_e_none(monkeypatch):
    sb = _SB({"deals": [{"id": "D-VALERIA", "pipeline_id": "outro", "created_at": "x"}]})
    monkeypatch.setattr(orders, "get_supabase", lambda: sb)
    assert orders._deal_de_origem_do_lead("L1") is None


def test_venda_recente_janela_de_7_dias():
    agora = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    assert orders.venda_recente("2026-09-29T12:00:00+00:00", agora)
    assert not orders.venda_recente("2026-09-29T11:59:59+00:00", agora)
    assert not orders.venda_recente(None, agora)
    assert not orders.venda_recente("lixo", agora)


# ---------- webhook ----------

def _pedido(dias_atras):
    data = (datetime.now(timezone.utc) - timedelta(days=dias_atras)).date().isoformat()
    return {"id": 555, "data": data, "total": 60, "contato": {"id": 9}}


def _handle(monkeypatch, pedido, ja_existia=False, garantir=None, lead="L1"):
    chamadas = []

    class Cli:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _p):
            return {"data": pedido}

    async def nada(*_a, **_k):
        return None

    async def lead_fn(*_a):
        return lead

    monkeypatch.setattr(wp, "_new_client", lambda a: Cli())
    monkeypatch.setattr(wp, "_last_event_date", nada)
    monkeypatch.setattr(wp, "_contact_row", lambda a, c: {"id": 9})
    monkeypatch.setattr(wp, "_resolve_lead", lead_fn)
    monkeypatch.setattr(wp, "upsert_from_bling", nada)
    monkeypatch.setattr(wp, "_venda_ja_existia", lambda a, o: ja_existia)
    monkeypatch.setattr(wp, "garantir_reposicao_apos_venda",
                        garantir or (lambda lead_id, deal_id=None: chamadas.append(lead_id)))
    evento = {"event_id": "E1", "event": "order.created", "account": "default"}
    status = asyncio.run(wp._handle_order(evento, {"data": {"id": 555}}))
    return status, chamadas


def test_webhook_venda_nova_e_recente_cria_reposicao(monkeypatch):
    status, chamadas = _handle(monkeypatch, _pedido(1))
    assert status == "done"
    assert chamadas == ["L1"]


def test_webhook_venda_antiga_nao_cria(monkeypatch):
    _s, chamadas = _handle(monkeypatch, _pedido(10))
    assert chamadas == []


def test_webhook_venda_ja_existente_nao_cria(monkeypatch):
    _s, chamadas = _handle(monkeypatch, _pedido(1), ja_existia=True)
    assert chamadas == []


def test_webhook_sem_lead_nao_cria(monkeypatch):
    _s, chamadas = _handle(monkeypatch, _pedido(1), lead=None)
    assert chamadas == []


def test_webhook_excecao_na_reposicao_nao_falha_o_evento(monkeypatch):
    def explode(*_a, **_k):
        raise RuntimeError("x")
    status, _ = _handle(monkeypatch, _pedido(1), garantir=explode)
    assert status == "done"


def test_venda_ja_existia_erro_de_leitura_conta_como_existente(monkeypatch):
    def quebra():
        raise RuntimeError("supabase fora")
    monkeypatch.setattr(wp, "get_supabase", quebra)
    assert wp._venda_ja_existia("default", 555) is True
