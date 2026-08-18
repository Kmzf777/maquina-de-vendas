import app.bling.config as cfg
from app.bling.errors import (
    BlingError, BlingAuthError, BlingRateLimitError,
    BlingServerError, BlingValidationError, BlingNotConfigured,
)


def test_desabilitado_por_default(monkeypatch):
    monkeypatch.delenv("BLING_ENABLED", raising=False)
    assert cfg.enabled() is False


def test_habilita_por_env(monkeypatch):
    monkeypatch.setenv("BLING_ENABLED", "true")
    assert cfg.enabled() is True


def test_credenciais_lidas_do_env(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    assert cfg.client_id() == "cid"
    assert cfg.client_secret() == "csec"


def test_require_credentials_levanta_quando_falta(monkeypatch):
    monkeypatch.delenv("BLING_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)
    try:
        cfg.require_credentials()
    except BlingNotConfigured:
        return
    raise AssertionError("deveria levantar BlingNotConfigured")


def test_ids_opcionais_viram_none_quando_vazios(monkeypatch):
    monkeypatch.setenv("BLING_STORE_ID", "")
    monkeypatch.setenv("BLING_ORDER_SITUACAO_ID", "  ")
    assert cfg.store_id() is None
    assert cfg.order_situacao_id() is None


def test_ids_opcionais_viram_int(monkeypatch):
    monkeypatch.setenv("BLING_STORE_ID", "203455519")
    assert cfg.store_id() == 203455519


def test_base_url_e_a_v3():
    assert cfg.API_BASE == "https://api.bling.com.br/Api/v3"


def test_hierarquia_de_erros():
    for klass in (BlingAuthError, BlingRateLimitError, BlingServerError,
                  BlingValidationError, BlingNotConfigured):
        assert issubclass(klass, BlingError)
