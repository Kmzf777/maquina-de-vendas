"""T6 (wartime 10/07) — retry de transporte nos hot writes de conversations/leads.

Contexto: GOAWAY (httpx.RemoteProtocolError) sob rajada de disparo perdia um
save_message/update_conversation/update_lead silenciosamente — 1 tentativa só.
Agora esses writes passam por run_with_retry (app/db/supabase.py): 3 tentativas
SOMENTE em httpx.TransportError; erro de aplicação (postgrest APIError) propaga
na primeira tentativa sem retry (contrato do helper — 4xx/5xx nunca mascarados).
"""

import types

import httpx
import pytest
from postgrest.exceptions import APIError

import app.conversations.service as conv_service
import app.db.supabase as db_supabase
import app.leads.service as leads_service


# ── Fake Supabase: roteia cada execute() por (tabela, operação), contando chamadas ──

class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._op = None

    def insert(self, payload):
        self._op = "insert"
        return self

    def update(self, fields):
        self._op = "update"
        return self

    def select(self, *args, **kwargs):
        self._op = "select"
        return self

    def eq(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def execute(self):
        return self._sb._run(self._table, self._op)


class _FakeSB:
    """Cada execute() consulta um script por (tabela, op) — permite falhar N vezes
    e suceder depois, exatamente o cenário GOAWAY-transitório do retry."""

    def __init__(self):
        self.calls: dict[tuple[str, str], int] = {}
        self._scripts: dict[tuple[str, str], object] = {}

    def on(self, table, op, script):
        self._scripts[(table, op)] = script

    def table(self, name):
        return _FakeQuery(self, name)

    def _run(self, table, op):
        key = (table, op)
        self.calls[key] = self.calls.get(key, 0) + 1
        script = self._scripts.get(key)
        if script is None:
            return _Result([])
        return script(self.calls[key])


def _goaway_then_ok(failures: int, data: list):
    """Levanta RemoteProtocolError nas `failures` primeiras chamadas; depois sucede."""
    def script(attempt: int):
        if attempt <= failures:
            raise httpx.RemoteProtocolError("GOAWAY: ConnectionTerminated")
        return _Result(data)
    return script


def _app_error(attempt: int):
    # Erro de APLICAÇÃO (postgrest) — NUNCA pode ser retentado nem mascarado.
    raise APIError({"message": "duplicate key", "code": "23505", "hint": "", "details": ""})


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """run_with_retry usa time.sleep no backoff — zera para não atrasar a suíte."""
    sleeps: list[float] = []
    monkeypatch.setattr(db_supabase, "time", types.SimpleNamespace(sleep=sleeps.append))
    return sleeps


# ── save_message ─────────────────────────────────────────────────────────────────

_MSG_ROW = {"id": "m1", "conversation_id": "conv-1", "content": "olá"}


def test_save_message_sobrevive_goaway_transitorio(monkeypatch, fast_sleep):
    sb = _FakeSB()
    sb.on("messages", "insert", _goaway_then_ok(2, [_MSG_ROW]))
    monkeypatch.setattr(conv_service, "get_supabase", lambda: sb)

    result = conv_service.save_message("conv-1", "lead-1", "assistant", "olá")

    assert result == _MSG_ROW  # retorno inalterado (contrato preservado)
    assert sb.calls[("messages", "insert")] == 3  # 2 falhas de transporte + sucesso
    assert sb.calls[("conversations", "update")] == 1  # carimbo last_msg_at seguiu normal
    assert fast_sleep == [0.5, 1.0]  # backoff linear do helper

def test_save_message_erro_de_aplicacao_propaga_sem_retry(monkeypatch):
    sb = _FakeSB()
    sb.on("messages", "insert", _app_error)
    monkeypatch.setattr(conv_service, "get_supabase", lambda: sb)

    with pytest.raises(APIError):
        conv_service.save_message("conv-1", "lead-1", "assistant", "olá")

    assert sb.calls[("messages", "insert")] == 1  # 1ª tentativa, zero retry
    assert ("conversations", "update") not in sb.calls  # não avançou ao carimbo


def test_save_message_carimbo_da_conversa_falho_nao_derruba_o_save(monkeypatch):
    # Semântica preservada: o touch de last_msg_at sempre foi fail-soft (warning).
    # Transporte fora até esgotar o retry → mensagem salva é retornada mesmo assim.
    sb = _FakeSB()
    sb.on("messages", "insert", _goaway_then_ok(0, [_MSG_ROW]))
    sb.on("conversations", "update", _goaway_then_ok(99, []))
    monkeypatch.setattr(conv_service, "get_supabase", lambda: sb)

    result = conv_service.save_message("conv-1", "lead-1", "user", "oi")

    assert result == _MSG_ROW
    assert sb.calls[("conversations", "update")] == 3  # retry esgotado, engolido no warn


# ── update_conversation ──────────────────────────────────────────────────────────

def test_update_conversation_sobrevive_goaway_transitorio(monkeypatch):
    sb = _FakeSB()
    sb.on("conversations", "update", _goaway_then_ok(2, []))
    monkeypatch.setattr(conv_service, "get_supabase", lambda: sb)

    result = conv_service.update_conversation("conv-1", status="active")

    assert result == {}  # retorno inalterado
    assert sb.calls[("conversations", "update")] == 3


def test_update_conversation_erro_de_aplicacao_propaga_sem_retry(monkeypatch):
    sb = _FakeSB()
    sb.on("conversations", "update", _app_error)
    monkeypatch.setattr(conv_service, "get_supabase", lambda: sb)

    with pytest.raises(APIError):
        conv_service.update_conversation("conv-1", status="active")

    assert sb.calls[("conversations", "update")] == 1


# ── update_lead ──────────────────────────────────────────────────────────────────

_LEAD_ROW = {"id": "lead-1", "name": "Fulano"}


def test_update_lead_sobrevive_goaway_transitorio(monkeypatch):
    sb = _FakeSB()
    sb.on("leads", "update", _goaway_then_ok(2, [_LEAD_ROW]))
    monkeypatch.setattr(leads_service, "get_supabase", lambda: sb)

    result = leads_service.update_lead("lead-1", name="Fulano")

    assert result == _LEAD_ROW  # retorno inalterado (data[0])
    assert sb.calls[("leads", "update")] == 3


def test_update_lead_erro_de_aplicacao_propaga_sem_retry(monkeypatch):
    sb = _FakeSB()
    sb.on("leads", "update", _app_error)
    monkeypatch.setattr(leads_service, "get_supabase", lambda: sb)

    with pytest.raises(APIError):
        leads_service.update_lead("lead-1", name="Fulano")

    assert sb.calls[("leads", "update")] == 1
