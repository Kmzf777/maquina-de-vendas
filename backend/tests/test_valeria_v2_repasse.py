"""Varredura de repasse automático da ValerIA v2 (Task 9)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.button_flow import valeria_registry_v2 as r2
from app.button_flow import valeria_repasse as rep
from app.button_flow import valeria_runner_v2 as runner


class FakeQuery:
    def __init__(self, paginas):
        self.paginas, self.calls, self._range = paginas, [], None

    def __getattr__(self, nome):
        def _m(*a, **k):
            self.calls.append((nome, a))
            if nome == "range":
                self._range = a
            return self
        return _m

    def execute(self):
        ini = self._range[0]
        return MagicMock(data=self.paginas.get(ini // rep.TAMANHO_PAGINA, []))


def _conv(i, lead=None):
    return {"id": f"c{i}", "channel_id": "ch", "last_customer_message_at": "2026-10-08T10:00:00+00:00",
            "flow_state": {}, "leads": lead if lead is not None else {"id": f"l{i}"}}


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("VALERIA_REPASSE_AUTO_ENABLED", "1")
    q = FakeQuery({})
    sb = MagicMock()
    sb.table.return_value = q
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    monkeypatch.setattr("app.channels.service.get_channel_by_id", lambda cid: {"id": cid})
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: "prov")
    chamadas = []

    async def fake(**kw):
        chamadas.append(kw)
        return True
    monkeypatch.setattr(runner, "repassar_parado", fake)
    return q, sb, chamadas


def test_desligado_nao_toca_no_banco(monkeypatch):
    monkeypatch.delenv("VALERIA_REPASSE_AUTO_ENABLED", raising=False)
    sb = MagicMock()
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert asyncio.run(rep.varrer()) == 0
    sb.table.assert_not_called()


def test_filtros_de_no_e_janela(ambiente):
    q, sb, _ = ambiente
    asyncio.run(rep.varrer())
    nomes = {c[0]: c[1] for c in q.calls}
    assert ("flow_state->>flow", "valeria_botoes_v2") == nomes["eq"]
    assert nomes["in_"] == ("flow_state->>node", sorted(r2.NOS_COM_INTENCAO))
    assert nomes["is_"] == ("flow_state->>repasse_auto", "null")
    assert nomes["gte"][0] == "last_customer_message_at" and nomes["lte"][0] == "last_customer_message_at"
    assert nomes["gte"][1] < nomes["lte"][1]
    sb.table.assert_called_with("conversations")


def test_pula_human_control_e_opt_out(ambiente):
    q, _, chamadas = ambiente
    q.paginas = {0: [_conv(1, {"id": "a", "human_control": True}),
                     _conv(2, {"id": "b", "opt_out": True}), _conv(3)]}
    assert asyncio.run(rep.varrer()) == 1
    assert [c["conversation"]["id"] for c in chamadas] == ["c3"]
    assert chamadas[0]["provider"] == "prov" and chamadas[0]["horas"] >= 0


def test_teto_de_50(ambiente):
    q, _, chamadas = ambiente
    q.paginas = {p: [_conv(p * 200 + i) for i in range(200)] for p in range(3)}
    assert asyncio.run(rep.varrer()) == 50
    assert len(chamadas) == 50


def test_false_nao_conta(ambiente, monkeypatch):
    q, _, _ = ambiente
    q.paginas = {0: [_conv(1), _conv(2)]}

    async def perde(**kw):
        return kw["conversation"]["id"] == "c2"
    monkeypatch.setattr(runner, "repassar_parado", perde)
    assert asyncio.run(rep.varrer()) == 1


def test_excecao_numa_conversa_nao_para_as_outras(ambiente, monkeypatch):
    q, _, _ = ambiente
    q.paginas = {0: [_conv(1), _conv(2)]}

    async def quebra(**kw):
        if kw["conversation"]["id"] == "c1":
            raise RuntimeError("boom")
        return True
    monkeypatch.setattr(runner, "repassar_parado", quebra)
    assert asyncio.run(rep.varrer()) == 1


def test_worker_registra_job_de_600s():
    from app.worker import main
    spec = {s[0]: s for s in main.TASK_SPECS}["valeria_repasse_parados"]
    assert spec[1] == "periodic" and spec[3] == 600
