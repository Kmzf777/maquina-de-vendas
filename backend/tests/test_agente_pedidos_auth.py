import pytest
from fastapi import HTTPException

from app.agente_pedidos import auth, contas


def test_sem_token_configurado_503(monkeypatch):
    monkeypatch.setattr(auth.settings, "agente_pedidos_token", None, raising=False)
    with pytest.raises(HTTPException) as e:
        auth.exigir_token("qualquer")
    assert e.value.status_code == 503


def test_token_errado_401(monkeypatch):
    monkeypatch.setattr(auth.settings, "agente_pedidos_token", "certo", raising=False)
    with pytest.raises(HTTPException) as e:
        auth.exigir_token("errado")
    assert e.value.status_code == 401


def test_sem_header_401(monkeypatch):
    monkeypatch.setattr(auth.settings, "agente_pedidos_token", "certo", raising=False)
    with pytest.raises(HTTPException) as e:
        auth.exigir_token(None)
    assert e.value.status_code == 401


def test_token_certo_passa(monkeypatch):
    monkeypatch.setattr(auth.settings, "agente_pedidos_token", "certo", raising=False)
    assert auth.exigir_token("certo") is None


def test_settings_tem_o_campo():
    from app.config import Settings
    assert "agente_pedidos_token" in Settings.model_fields


def test_contas_com_apelido(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    assert [c["apelido"] for c in contas.listar()] == ["boaventura", "caferural"]
    assert contas.rotulo("default") == "Bling Boaventura"
    assert contas.rotulo("secundaria") == "Bling Caferural"


def test_conta_desconhecida_400(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    with pytest.raises(HTTPException) as e:
        contas.validar("outra")
    assert e.value.status_code == 400
    assert e.value.detail["erro"] == "conta"


def test_fabrica_por_conta(monkeypatch):
    monkeypatch.setenv("BLING_ACCOUNTS", "default,secundaria")
    monkeypatch.setenv("BLING_FABRICA_CONTATO_ID", "111")
    monkeypatch.setenv("BLING_SECUNDARIA_FABRICA_CONTATO_ID", "222")
    assert contas.fabrica("default") == 111
    assert contas.fabrica("secundaria") == 222


def test_fabrica_secundaria_nao_herda_a_default(monkeypatch):
    monkeypatch.setenv("BLING_FABRICA_CONTATO_ID", "111")
    monkeypatch.delenv("BLING_SECUNDARIA_FABRICA_CONTATO_ID", raising=False)
    with pytest.raises(HTTPException) as e:
        contas.fabrica("secundaria")
    assert e.value.status_code == 422


def test_fabrica_ausente_422(monkeypatch):
    monkeypatch.delenv("BLING_SECUNDARIA_FABRICA_CONTATO_ID", raising=False)
    monkeypatch.delenv("BLING_FABRICA_CONTATO_ID", raising=False)
    with pytest.raises(HTTPException) as e:
        contas.fabrica("secundaria")
    assert e.value.status_code == 422
    assert "BLING_SECUNDARIA_FABRICA_CONTATO_ID" in e.value.detail["mensagem"]
