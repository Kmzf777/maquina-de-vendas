import hashlib
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.audiences import meta
from app.audiences.types import Pessoa
from app.conversions.hashing import meta_email_hash, meta_phone_hash

TOKEN = "SEGREDO-TOKEN-123"


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _p(lead_id="L1", emails=("ana@x.com",), celulares=("5534991234567",), valor=150.5):
    return Pessoa(lead_id=lead_id, pl=True, atacado=False, celulares=list(celulares),
                  emails=list(emails), nome="ana", sobrenome="silva", cidade="uberlandia",
                  uf="mg", cep="38400123", valor=valor)


def _env(monkeypatch):
    monkeypatch.setenv("META_AUDIENCES_ACCESS_TOKEN", TOKEN)
    monkeypatch.delenv("META_AUDIENCES_API_VERSION", raising=False)


def _form(req: httpx.Request) -> dict:
    return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}


def test_schema_e_ordem_das_colunas():
    assert meta.SCHEMA == ["EMAIL", "PHONE", "FN", "LN", "CT", "ST", "ZIP", "COUNTRY", "LOOKALIKE_VALUE"]
    row = meta.build_rows([_p()])[0]
    assert len(row) == len(meta.SCHEMA)
    assert row[2:8] == [_h("ana"), _h("silva"), _h("uberlandia"), _h("mg"), _h("38400123"), _h("br")]


def test_email_e_telefone_em_hash_como_hashing():
    row = meta.build_rows([_p()])[0]
    assert row[0] == meta_email_hash("ana@x.com")
    assert row[1] == meta_phone_hash("5534991234567")


def test_lookalike_value_sem_hash():
    assert meta.build_rows([_p(valor=150.5)])[0][8] == 150.5


def test_dois_emails_um_celular_gera_duas_linhas():
    rows = meta.build_rows([_p(emails=("a@x.com", "b@x.com"))])
    assert len(rows) == 2
    assert rows[0][1] == meta_phone_hash("5534991234567")
    assert rows[1][0] == meta_email_hash("b@x.com")
    assert rows[1][1] == ""


def test_pessoa_sem_contato_e_pulada():
    assert meta.build_rows([_p(emails=(), celulares=())]) == []


def test_lotes_com_max_rows():
    rows = [["r1"], ["r2"], ["r3"]]
    lotes = meta.build_batches(rows, "S1", max_rows=2)
    assert len(lotes) == 2
    assert [b["session"]["batch_seq"] for b in lotes] == [1, 2]
    assert [b["session"]["last_batch_flag"] for b in lotes] == [False, True]
    assert all(b["session"]["estimated_num_total"] == 3 for b in lotes)
    assert all(b["session"]["session_id"] == "S1" for b in lotes)
    assert lotes[0]["payload"] == {"schema": meta.SCHEMA, "data": [["r1"], ["r2"]]}
    assert lotes[1]["payload"]["data"] == [["r3"]]


def test_zero_linhas_vira_um_lote_vazio_final():
    lotes = meta.build_batches([], "S1")
    assert len(lotes) == 1
    assert lotes[0]["payload"]["data"] == []
    assert lotes[0]["session"]["last_batch_flag"] is True


def test_replace_soma_num_received(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(meta, "MAX_ROWS", 1)
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"num_received": 1, "num_invalid_entries": 0, "session_id": 7})

    out = meta.replace("AUD1", [_p(emails=("a@x.com", "b@x.com"))], session_id=7,
                       transport=httpx.MockTransport(handler))
    assert out["num_received"] == 2 and out["num_invalid_entries"] == 0
    assert out["lotes"] == 2 and out["linhas"] == 2 and out["session_id"] == 7
    assert len(out["respostas"]) == 2
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://graph.facebook.com/v25.0/AUD1/usersreplace"
    assert TOKEN not in str(req.url)
    form = _form(req)
    assert json.loads(form["payload"])["schema"] == meta.SCHEMA
    assert json.loads(form["session"])["batch_seq"] == 1
    assert json.loads(_form(seen[1])["session"])["last_batch_flag"] is True


def test_erro_400_vira_runtimeerror_sem_token(monkeypatch):
    _env(monkeypatch)
    t = httpx.MockTransport(lambda req: httpx.Response(
        400, json={"error": {"message": "Invalid parameter", "code": 100}}))
    with pytest.raises(RuntimeError) as exc:
        meta.replace("AUD1", [_p()], transport=t)
    assert "Invalid parameter" in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_sem_token_runtimeerror(monkeypatch):
    monkeypatch.delenv("META_AUDIENCES_ACCESS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="META_AUDIENCES_ACCESS_TOKEN não configurado"):
        meta.replace("AUD1", [_p()], transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def test_check_audience(monkeypatch):
    _env(monkeypatch)
    seen = {}

    def handler(req):
        seen["req"] = req
        return httpx.Response(200, json={"name": "PL", "approximate_count_lower_bound": 1000})

    out = meta.check_audience("AUD1", transport=httpx.MockTransport(handler))
    assert out["name"] == "PL"
    req = seen["req"]
    assert req.method == "GET" and req.url.path == "/v25.0/AUD1"
    assert "operation_status" in req.url.params["fields"]
    assert TOKEN not in str(req.url)
