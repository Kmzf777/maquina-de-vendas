"""Script do dataset da Meta: token só no header, e erro sem a URL (que poderia ter segredo)."""
import httpx
import pytest

from scripts.conversoes import criar_dataset_meta as cd


def _env(monkeypatch):
    monkeypatch.setenv("META_WABA_ID", "WABA9")
    monkeypatch.setenv("META_CAPI_ACCESS_TOKEN", "SEGREDO")


def _client(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(cd.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_token_no_header(monkeypatch, capsys):
    _env(monkeypatch)
    vistos = []

    def handler(req):
        vistos.append((req.method, str(req.url), req.headers.get("Authorization")))
        if req.method == "GET":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, json={"id": "DS1"})

    _client(monkeypatch, handler)
    cd.main()
    assert "DS1" in capsys.readouterr().out
    assert [m for m, _u, _a in vistos] == ["GET", "POST"]
    for _m, url, auth in vistos:
        assert "SEGREDO" not in url and "access_token" not in url
        assert auth == "Bearer SEGREDO"


def test_erro_mostra_status_e_mensagem_sem_url(monkeypatch, capsys):
    _env(monkeypatch)
    _client(monkeypatch, lambda req: httpx.Response(400, json={"error": {"message": "Permissão faltando", "code": 200}}))
    with pytest.raises(SystemExit) as exc:
        cd.main()
    saida = capsys.readouterr()
    texto = f"{exc.value.code} {saida.out} {saida.err}"
    assert "400" in texto and "Permissão faltando" in texto
    assert "SEGREDO" not in texto and "graph.facebook.com" not in texto
