# backend/tests/test_conversions_sender.py
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

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


def test_outside_window_meta_tem_margem_de_1_hora():
    """Request lento/relógio diferente: um evento com 6 d 23 h 59 min chegaria à Meta já fora dos
    7 dias e derrubaria o request. Margem de 1 h."""
    assert not outside_window(_row(event_at=(NOW - timedelta(days=6, hours=22, minutes=59)).isoformat()), NOW)
    assert outside_window(_row(event_at=(NOW - timedelta(days=6, hours=23, minutes=1)).isoformat()), NOW)


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
    assert "status" not in s and "attempts" not in s and "sent_at" not in s
    assert s["claimed_at"] is None and s["last_error"] is None
    assert s["last_response"] == {"modo_teste": True, "resposta": {"a": 1}}
    assert s["next_attempt_at"] == (NOW + TEST_MODE_PAUSE).isoformat()
    assert TEST_MODE_PAUSE == timedelta(hours=6)


def test_next_state_modo_teste_falha_tambem_nao_consome_a_linha():
    """Um erro de teste (ID de ação errado, payload ruim) é o que o teste quer mostrar — mas não
    pode queimar a linha real: nem `erro`, nem tentativa gasta. Fica registrado em last_error."""
    for res in (SendResult(ok=False, permanent=True, error="HTTP 400: bad", response={"e": 1}),
                SendResult(ok=False, error="HTTP 500")):
        s = next_state(_row(attempts=2), res, NOW, test_mode=True)
        assert "status" not in s and "attempts" not in s, res
        assert s["claimed_at"] is None and s["last_error"] == res.error
        assert s["last_response"] == {"modo_teste": True, "resposta": res.response}
        assert s["next_attempt_at"] == (NOW + TEST_MODE_PAUSE).isoformat()


def test_next_state_erro_de_credencial_nao_gasta_tentativa():
    s = next_state(_row(attempts=3), SendResult(ok=False, error="HTTP 401: x", auth_error=True), NOW)
    assert "status" not in s and "attempts" not in s
    assert s["claimed_at"] is None and s["last_error"] == "HTTP 401: x"
    assert s["next_attempt_at"] == (NOW + timedelta(minutes=30)).isoformat()


def test_run_sender_plataformas_desligadas_nao_toca_no_banco(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    assert sender_mod.run_sender(now=NOW)["enviado"] == 0
    called.assert_not_called()


class _Q:
    """Query builder falso do supabase-py. No select, `eq`/`in_` filtram pelas colunas que a linha
    tem e `limit` corta; o resto devolve a si mesmo. O update de claim (com `claimed_at` só)
    devolve a linha; `falhas_gravacao` faz o update final estourar."""

    def __init__(self, data, log, falhas=None, filtra=True):
        self.data = list(data)
        self.log = log
        self.falhas = falhas if falhas is not None else [0]
        self.final = False
        self.filtra = filtra

    def __getattr__(self, n):
        def call(*a, **k):
            self.log.append((n, a))
            if self.filtra and n in ("eq", "in_"):
                col, val = a
                ok = (lambda v: v == val) if n == "eq" else (lambda v: v in set(val))
                self.data = [r for r in self.data if col not in r or ok(r[col])]
            if self.filtra and n == "limit":
                self.data = self.data[:a[0]]
            return self
        return call

    def update(self, u):
        self.log.append(("update", (u,)))
        q = _Q([{"id": "R1"}], self.log, self.falhas, filtra=False)
        q.final = set(u) != {"claimed_at"} or u["claimed_at"] is None
        return q

    def execute(self):
        if self.final and self.falhas[0] > 0:
            self.falhas[0] -= 1
            raise RuntimeError("supabase fora do ar")
        return MagicMock(data=self.data)


def _fake_sb(rows, sales=None, falhas_gravacao=0):
    log = []
    sb = MagicMock()
    falhas = [falhas_gravacao]
    tables = {"ad_conversions": rows, "leads": [{"id": "L1", "wa_id": "5534992009777"}], "sales": sales or []}
    sb.table.side_effect = lambda n: _Q(tables[n], log, falhas)
    return sb, log


def _updates(log):
    return [a[0] for n, a in log if n == "update"]


def _qrow(**kw):
    return {**_row(), "lead_id": "L1", "sale_id": None, "click_id": "C1", "event_id": "e", "value": None, **kw}


def _env(monkeypatch, test_mode="false"):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "true")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    monkeypatch.setenv("CONVERSIONS_TEST_MODE", test_mode)
    monkeypatch.setenv("META_CAPI_DATASET_ID", "DS1")
    monkeypatch.setenv("META_CAPI_ACCESS_TOKEN", "TOK")
    monkeypatch.setenv("META_WABA_ID", "WABA9")
    monkeypatch.setenv("META_CAPI_TEST_EVENT_CODE", "TEST1")


def _google_env(monkeypatch, stages=("lead", "qualified", "opportunity", "purchase")):
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "true")
    for v in ("GOOGLE_ADS_CUSTOMER_ID", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"):
        monkeypatch.setenv(v, "x")
    for st in ("lead", "qualified", "opportunity", "purchase"):
        if st in stages:
            monkeypatch.setenv(f"GOOGLE_ADS_CONVERSION_ACTION_{st.upper()}", "123")
        else:
            monkeypatch.delenv(f"GOOGLE_ADS_CONVERSION_ACTION_{st.upper()}", raising=False)


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    monkeypatch.setattr(sender_mod, "_sleep", lambda s: None)
    monkeypatch.setattr(sender_mod, "_utcnow", lambda: NOW)


def test_run_sender_plataforma_sem_config_nao_reivindica_linhas(monkeypatch, caplog):
    """Variável faltando: a plataforma é pulada inteira (nada sai da fila, nenhuma tentativa
    gasta) e o tick avisa no log uma vez — em vez de cada linha virar `erro`."""
    _env(monkeypatch)
    monkeypatch.delenv("META_CAPI_DATASET_ID")
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    with caplog.at_level("WARNING"):
        counts = sender_mod.run_sender(now=NOW)
    assert sum(counts.values()) == 0
    called.assert_not_called()
    avisos = [r for r in caplog.records if "META_CAPI_DATASET_ID" in r.getMessage()]
    assert len(avisos) == 1


def test_run_sender_meta_em_modo_teste_sem_codigo_e_pulada(monkeypatch):
    _env(monkeypatch, test_mode="true")
    monkeypatch.delenv("META_CAPI_TEST_EVENT_CODE")
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    assert sum(sender_mod.run_sender(now=NOW).values()) == 0
    called.assert_not_called()


def test_run_sender_so_reivindica_a_plataforma_configurada(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("META_CAPI_ACCESS_TOKEN")
    _google_env(monkeypatch)
    sb, log = _fake_sb([])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    sender_mod.run_sender(now=NOW)
    assert ("eq", ("platform", "google")) in log
    assert ("eq", ("platform", "meta")) not in log


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
    assert "status" not in _updates(log)[-1]


def test_run_sender_modo_teste_erro_nao_vira_erro(monkeypatch):
    _env(monkeypatch, test_mode="true")
    sb, log = _fake_sb([_qrow()])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=False, permanent=True, error="HTTP 400: x"))
    counts = sender_mod.run_sender(now=NOW)
    assert counts["erro"] == 0 and counts["pendente"] == 1
    last = _updates(log)[-1]
    assert "status" not in last and "attempts" not in last and last["last_error"] == "HTTP 400: x"


def test_run_sender_venda_removida_vira_ignorado(monkeypatch):
    """Venda apagada depois de enfileirada: a FK zera `sale_id` (on delete set null)."""
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(stage="purchase", sale_id=None)])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    assert counts["ignorado"] == 1
    send.assert_not_called()
    assert _updates(log)[-1] == {"status": "ignorado", "claimed_at": None,
                                 "last_error": "venda removida antes do envio"}


# ── C1: nunca reenviar quando o desfecho é desconhecido ─────────────────────

def test_gravacao_final_tenta_de_novo(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow()], falhas_gravacao=2)
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True, response={}))
    counts = sender_mod.run_sender(now=NOW)
    assert counts["enviado"] == 1
    assert [u.get("status") for u in _updates(log)][1:] == ["enviado"] * 3


def test_gravacao_final_que_falha_3_vezes_loga_erro(monkeypatch, caplog):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow()], falhas_gravacao=3)
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True, response={}))
    with caplog.at_level("ERROR"):
        sender_mod.run_sender(now=NOW)
    assert len(_updates(log)) == 4  # claim + 3 tentativas
    erros = [r for r in caplog.records if r.levelname == "ERROR" and "R1" in r.getMessage()]
    assert erros


def test_meta_retomada_de_claim_abandonado_nao_reenvia(monkeypatch):
    """Claim velho = um worker morreu no meio do envio. A Meta não deduplica: o evento pode já
    estar lá. Vira `erro` para conferência no Gerenciador de Eventos, sem chamar a Meta."""
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(claimed_at=(NOW - timedelta(minutes=11)).isoformat())])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    send.assert_not_called()
    assert counts["erro"] == 1
    assert _updates(log)[-1] == {"status": "erro", "claimed_at": None,
                                 "last_error": "envio interrompido — conferir no Gerenciador de Eventos antes de reenviar"}


def test_google_retomada_de_claim_abandonado_reenvia(monkeypatch):
    """O Google deduplica pelo transactionId: reenviar é seguro."""
    _env(monkeypatch)
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    _google_env(monkeypatch)
    sb, log = _fake_sb([_qrow(platform="google", claimed_at=(NOW - timedelta(minutes=11)).isoformat())])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.google, "send", lambda r, l: SendResult(ok=True, response={}))
    assert sender_mod.run_sender(now=NOW)["enviado"] == 1


def test_meta_sem_claim_anterior_envia_normal(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(claimed_at=None)])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True, response={}))
    assert sender_mod.run_sender(now=NOW)["enviado"] == 1


# ── I2: etapa do Google sem ação configurada; disjuntor de credencial ──────

def test_google_so_reivindica_etapas_com_acao_configurada(monkeypatch, caplog):
    _env(monkeypatch)
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    _google_env(monkeypatch, stages=("qualified", "purchase"))
    rows = [_qrow(id="R1", platform="google", stage="lead"), _qrow(id="R2", platform="google", stage="qualified")]
    sb, log = _fake_sb(rows)
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    enviados = []
    monkeypatch.setattr(sender_mod.google, "send", lambda r, l: enviados.append(r["id"]) or SendResult(ok=True))
    with caplog.at_level("WARNING"):
        counts = sender_mod.run_sender(now=NOW)
    # filtro na própria consulta (a linha sem ação não ocupa o lote) + trava linha a linha
    assert ("in_", ("stage", ["qualified", "purchase"])) in log
    assert enviados == ["R2"] and counts["enviado"] == 1
    claims = [a for n, a in log if n == "eq" and a[0] == "id"]
    assert ("id", "R1") not in claims
    avisos = [r for r in caplog.records if "GOOGLE_ADS_CONVERSION_ACTION_LEAD" in r.getMessage()]
    assert len(avisos) == 1


def test_google_sem_nenhuma_acao_e_pulado(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    _google_env(monkeypatch, stages=())
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    assert sum(sender_mod.run_sender(now=NOW).values()) == 0
    called.assert_not_called()


def test_disjuntor_de_credencial_para_a_plataforma_no_tick(monkeypatch):
    _env(monkeypatch)
    rows = [_qrow(id="R1"), _qrow(id="R2"), _qrow(id="R3")]
    sb, log = _fake_sb(rows)
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    chamadas = []

    def send(r, l):
        chamadas.append(r["id"])
        return SendResult(ok=False, error="HTTP 401: token", auth_error=True)
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    assert chamadas == ["R1"]
    claims = [a for n, a in log if n == "eq" and a[0] == "id"]
    assert ("id", "R2") not in claims and ("id", "R3") not in claims
    last = [u for u in _updates(log) if "last_error" in u][-1]
    assert "attempts" not in last and "status" not in last and last["claimed_at"] is None
    assert last["next_attempt_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert counts["pendente"] == 1 and counts["erro"] == 0
    # as outras linhas vencidas da plataforma são empurradas de uma vez (não ficam girando)
    adiar = {"next_attempt_at": (NOW + timedelta(minutes=30)).isoformat()}
    assert adiar in _updates(log)
    i = log.index(("update", (adiar,)))
    filtros = log[i + 1:i + 6]
    assert ("eq", ("platform", "meta")) in filtros and ("eq", ("status", "pendente")) in filtros
    assert ("lte", ("next_attempt_at", NOW.isoformat())) in filtros
    assert ("is_", ("claimed_at", "null")) in filtros


def test_disjuntor_nao_para_a_outra_plataforma(monkeypatch):
    _env(monkeypatch)
    _google_env(monkeypatch)
    rows = [_qrow(id="R1"), _qrow(id="R2", platform="google"), _qrow(id="R3")]
    sb, log = _fake_sb(rows)
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=False, error="x", auth_error=True))
    monkeypatch.setattr(sender_mod.google, "send", lambda r, l: SendResult(ok=True))
    counts = sender_mod.run_sender(now=NOW)
    assert counts["enviado"] == 1 and counts["pendente"] == 1


# ── I3: claim ───────────────────────────────────────────────────────────────

def test_claim_filtra_next_attempt_at_com_a_hora_do_claim(monkeypatch):
    """Outro worker pode ter reagendado a linha entre o select e o claim: o UPDATE confere de
    novo `next_attempt_at <= agora` (agora = hora do claim, não do início do tick)."""
    _env(monkeypatch)
    claim_at = NOW + timedelta(minutes=3)
    monkeypatch.setattr(sender_mod, "_utcnow", lambda: claim_at)
    sb, log = _fake_sb([_qrow()])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: SendResult(ok=True))
    sender_mod.run_sender(now=NOW)
    assert _updates(log)[0] == {"claimed_at": claim_at.isoformat()}
    i = log.index(("update", ({"claimed_at": claim_at.isoformat()},)))
    depois = log[i:i + 6]
    assert ("lte", ("next_attempt_at", claim_at.isoformat())) in depois
    assert ("eq", ("status", "pendente")) in depois


def test_venda_cancelada_com_caixa_e_espaco_vira_ignorado(monkeypatch):
    _env(monkeypatch)
    sb, log = _fake_sb([_qrow(stage="purchase", sale_id="S1")], sales=[{"id": "S1", "status": " Cancelada "}])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    assert sender_mod.run_sender(now=NOW)["ignorado"] == 1
    send.assert_not_called()


def test_plataforma_travada_nao_toma_as_vagas_da_outra(monkeypatch):
    """Token do Google revogado com mais linhas vencidas do que o lote: a Meta precisa sair do
    mesmo jeito (senão as linhas dela passam dos 7 dias e se perdem). Uma consulta por plataforma,
    cada uma com o seu limite."""
    _env(monkeypatch)
    _google_env(monkeypatch)
    rows = [_qrow(id=f"G{i}", platform="google", next_attempt_at=f"2026-10-0{i + 1}") for i in range(5)]
    rows.append(_qrow(id="M1", platform="meta"))
    sb, log = _fake_sb(rows)
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    google_calls, meta_calls = [], []
    monkeypatch.setattr(sender_mod.google, "send",
                        lambda r, l: google_calls.append(r["id"]) or SendResult(ok=False, error="HTTP 401", auth_error=True))
    monkeypatch.setattr(sender_mod.meta, "send", lambda r, l: meta_calls.append(r["id"]) or SendResult(ok=True))
    counts = sender_mod.run_sender(now=NOW, limit=3)
    assert meta_calls == ["M1"] and counts["enviado"] == 1
    assert len(google_calls) == 1
    assert ("limit", (3,)) in log and log.count(("limit", (3,))) == 2


def test_meta_claim_abandonado_vira_erro_tambem_em_modo_teste(monkeypatch):
    """Em modo teste o claim velho pode ser de um envio REAL anterior: reenviar como teste apagaria
    a evidência e a linha sairia de verdade de novo depois."""
    _env(monkeypatch, test_mode="true")
    sb, log = _fake_sb([_qrow(claimed_at=(NOW - timedelta(minutes=11)).isoformat())])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    send.assert_not_called()
    assert counts["erro"] == 1
    assert _updates(log)[-1]["last_error"].startswith("envio interrompido")


# --- Janela retroativa (CONVERSIONS_BACKFILL_DAYS) e simulação (dry-run) — 14/10 ---


def test_outside_window_respeita_a_janela_retroativa(monkeypatch):
    monkeypatch.delenv("CONVERSIONS_BACKFILL_DAYS", raising=False)
    r = _row(platform="google", event_at=(NOW - timedelta(days=40)).isoformat(),
             click_at=(NOW - timedelta(days=41)).isoformat())
    assert outside_window(r, NOW) is False                         # padrão 90
    assert outside_window(r, NOW, backfill=timedelta(days=30)) is True


def test_run_sender_evento_fora_da_janela_retroativa_nao_envia(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setenv("CONVERSIONS_BACKFILL_DAYS", "3")
    row = _qrow(platform="meta", event_at=(NOW - timedelta(days=5)).isoformat(),
                click_at=(NOW - timedelta(days=5, hours=1)).isoformat())
    sb, log = _fake_sb([row])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    counts = sender_mod.run_sender(now=NOW)
    send.assert_not_called()
    assert counts["fora_da_janela"] == 1


def test_run_sender_dry_run_nao_envia_nem_grava(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("CONVERSIONS_BACKFILL_DAYS", raising=False)
    sb, log = _fake_sb([_qrow(platform="meta")])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    send = MagicMock()
    monkeypatch.setattr(sender_mod.meta, "send", send)
    claim = MagicMock(return_value=True)
    monkeypatch.setattr(sender_mod, "_claim", claim)
    res = sender_mod.run_sender(now=NOW, dry_run=True)
    send.assert_not_called()
    claim.assert_not_called()
    assert _updates(log) == []
    assert res["simulacao"] == {("meta", _qrow()["stage"], "0-7d"): 1}


def test_run_sender_dry_run_sem_plataforma_pronta_simulacao_vazia(monkeypatch):
    monkeypatch.setenv("CONVERSIONS_META_ENABLED", "false")
    monkeypatch.setenv("CONVERSIONS_GOOGLE_ENABLED", "false")
    called = MagicMock()
    monkeypatch.setattr(sender_mod, "get_supabase", called)
    assert sender_mod.run_sender(now=NOW, dry_run=True)["simulacao"] == {}
    called.assert_not_called()


def test_simulate_sender_conta_plataformas_pedidas_sem_estarem_ligadas(monkeypatch):
    monkeypatch.delenv("CONVERSIONS_META_ENABLED", raising=False)
    monkeypatch.delenv("CONVERSIONS_GOOGLE_ENABLED", raising=False)
    monkeypatch.delenv("CONVERSIONS_BACKFILL_DAYS", raising=False)
    velho = _qrow(platform="meta", event_at=(NOW - timedelta(days=8)).isoformat())
    sb, log = _fake_sb([_qrow(platform="meta"), velho])
    monkeypatch.setattr(sender_mod, "get_supabase", lambda: sb)
    res = sender_mod.simulate_sender(now=NOW, platforms=("meta",))
    assert sum(res["enviaria"].values()) == 1 and res["fora_da_janela"] == 1
    assert res["backfill_days"] == 90
    assert _updates(log) == []
