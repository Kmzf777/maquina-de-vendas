# backend/tests/test_conversions_sender.py
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.conversions import sender as sender_mod
from app.conversions.sender import BACKOFF, TEST_MODE_PAUSE, next_state, outside_window
from app.conversions.types import SendResult

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def _row(**kw):
    r = {"id": "R1", "platform": "meta", "stage": "qualified", "attempts": 0,
         "event_at": (NOW - timedelta(days=1)).isoformat(), "click_at": (NOW - timedelta(days=2)).isoformat()}
    r.update(kw)
    return r


def test_outside_window_meta_pelo_evento():
    assert not outside_window(_row(), NOW)
    assert outside_window(_row(event_at=(NOW - timedelta(days=7, minutes=1)).isoformat()), NOW)


def test_outside_window_google_pelo_clique():
    r = _row(platform="google", event_at=(NOW - timedelta(days=30)).isoformat(),
             click_at=(NOW - timedelta(days=89)).isoformat())
    assert not outside_window(r, NOW)
    assert outside_window({**r, "click_at": (NOW - timedelta(days=91)).isoformat()}, NOW)


def test_next_state_ok():
    s = next_state(_row(), SendResult(ok=True, response={"a": 1}), NOW)
    assert s["status"] == "enviado" and s["sent_at"] == NOW.isoformat()
    assert s["attempts"] == 1 and s["claimed_at"] is None and s["last_response"] == {"a": 1}


def test_next_state_transitorio_agenda_backoff():
    s = next_state(_row(attempts=0), SendResult(ok=False, error="HTTP 500"), NOW)
    assert s["status"] == "pendente"
    assert s["next_attempt_at"] == (NOW + timedelta(seconds=BACKOFF[0])).isoformat()
    s = next_state(_row(attempts=2), SendResult(ok=False, error="x"), NOW)
    assert s["next_attempt_at"] == (NOW + timedelta(seconds=BACKOFF[2])).isoformat()


def test_next_state_esgota_tentativas():
    s = next_state(_row(attempts=len(BACKOFF)), SendResult(ok=False, error="x"), NOW)
    assert s["status"] == "erro" and s["last_error"] == "x"


def test_next_state_permanente_vira_erro_direto():
    s = next_state(_row(), SendResult(ok=False, permanent=True, error="HTTP 400: bad"), NOW)
    assert s["status"] == "erro" and s["attempts"] == 1


def test_next_state_modo_teste_ok_nao_consome_a_linha():
    s = next_state(_row(attempts=1), SendResult(ok=True, response={"a": 1}), NOW, test_mode=True)
    assert s["status"] == "pendente"
    assert "attempts" not in s and "sent_at" not in s
    assert s["claimed_at"] is None and s["last_error"] is None
    assert s["last_response"] == {"modo_teste": True, "resposta": {"a": 1}}
    assert s["next_attempt_at"] == (NOW + TEST_MODE_PAUSE).isoformat()
    assert TEST_MODE_PAUSE == timedelta(hours=6)


def test_next_state_modo_teste_falha_segue_regras_normais():
    s = next_state(_row(), SendResult(ok=False, permanent=True, error="HTTP 400: bad"), NOW, test_mode=True)
    assert s["status"] == "erro" and s["attempts"] == 1 and s["last_error"] == "HTTP 400: bad"
    s = next_state(_row(), SendResult(ok=False, error="HTTP 500"), NOW, test_mode=True)
    assert s["status"] == "pendente" and s["attempts"] == 1
    assert s["next_attempt_at"] == (NOW + timedelta(seconds=BACKOFF[0])).isoformat()


def test_run_sender_plataformas_desligadas_nao_toca_no_banco(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    assert sender_mod.run_sender(now=NOW)["enviado"] == 0
    called.assert_not_called()


class _Q:
    """Query builder falso do supabase-py: qualquer filtro devolve a si mesmo."""

    def __init__(self, data, log):
        self.data = data
        self.log = log

    def __getattr__(self, n):
        def call(*a, **k):
            self.log.append((n, a))
            return self
        return call

    def update(self, u):
        self.log.append(("update", (u,)))
        return _Q([{"id": "R1"}], self.log)

    def execute(self):
        return MagicMock(data=self.data)


def _fake_sb(rows, sales=None):
    log = []
    sb = MagicMock()
    tables = {"ad_conversions": rows, "leads": [{"id": "L1", "wa_id": "5534992009777"}], "sales": sales or []}
    sb.table.side_effect = lambda n: _Q(tables[n], log)
    return sb, log


def _updates(log):
    return [a[0] for n, a in log if n == "update"]


def _qrow(**kw):
    return {**_row(), "lead_id": "L1", "sale_id": None, "click_id": "C1", "event_id": "e", "value": None, **kw}


def _env(monkeypatch, test_mode="false"):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "true")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", test_mode)


def test_run_sender_envia_e_grava(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow()])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True, response={"events_received": 1}))
    counts = sender_mod.run_sender(now=NOW)
    assert counts["enviado"] == 1
    # 1º update = claim; último = estado final
    assert "claimed_at" in _updates(log)[0]
    assert _updates(log)[-1]["status"] == "enviado"


def test_run_sender_fora_da_janela_nao_envia(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(event_at=(NOW - timedelta(days=8)).isoformat())])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    assert counts["fora_da_janela"] == 1
    send.assert_not_called()
    assert _updates(log)[-1] == {"status": "fora_da_janela", "claimed_at": None}


def test_run_sender_venda_cancelada_vira_ignorado(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(stage="purchase", sale_id="S1")], sales=[{"id": "S1", "status": "cancelada"}])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    assert counts["ignorado"] == 1
    send.assert_not_called()


def test_run_sender_claim_perdido_nao_envia(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow()])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod, "_claim", lambda *a: False)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    assert sum(counts.values()) == 0
    send.assert_not_called()


def test_run_sender_excecao_no_cliente_vira_retentativa(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow()])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)

    def boom(r, l):
        raise KeyError("stage")
    monkeypatch.setattr(sender_mod.meta, "send", boom)
    counts = sender_mod.run_sender(now=NOW)
    assert counts["pendente"] == 1
    last = _updates(log)[-1]
    assert last["status"] == "pendente" and last["attempts"] == 1 and last["claimed_at"] is None


def test_run_sender_modo_teste_limita_lote_e_mantem_pendente(monkeypatch):
    _env(monkeypatch, test_mode="true")
    sb, log = _fake_sb([_qrow()])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True, response={"events_received": 1}))
    counts = sender_mod.run_sender(now=NOW, limit=100)
    assert counts["enviado"] == 0 and counts["pendente"] == 1
    assert ("limit", (sender_mod.TEST_MODE_LIMIT,)) in log and sender_mod.TEST_MODE_LIMIT == 10
    assert _updates(log)[-1]["last_response"]["modo_teste"] is True
