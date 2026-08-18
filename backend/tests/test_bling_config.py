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


def test_is_configured_false_sem_nenhuma_credencial(monkeypatch):
    monkeypatch.delenv("BLING_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)
    assert cfg.is_configured() is False


def test_is_configured_false_com_apenas_uma_credencial(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.delenv("BLING_CLIENT_SECRET", raising=False)
    assert cfg.is_configured() is False


def test_is_configured_true_com_as_duas_credenciais(monkeypatch):
    monkeypatch.setenv("BLING_CLIENT_ID", "cid")
    monkeypatch.setenv("BLING_CLIENT_SECRET", "csec")
    assert cfg.is_configured() is True


def test_env_int_invalido_gera_warning_com_nome_da_variavel(monkeypatch, caplog):
    monkeypatch.setenv("BLING_STORE_ID", "abc")
    with caplog.at_level("WARNING"):
        assert cfg.store_id() is None
    assert "BLING_STORE_ID" in caplog.text


def test_redirect_uri_le_do_env(monkeypatch):
    monkeypatch.setenv("BLING_REDIRECT_URI", "https://exemplo.com/callback")
    assert cfg.redirect_uri() == "https://exemplo.com/callback"


def test_lead_default_stage_default_e_novo(monkeypatch):
    monkeypatch.delenv("BLING_LEAD_DEFAULT_STAGE", raising=False)
    assert cfg.lead_default_stage() == "novo"


def test_lead_default_stage_le_do_env(monkeypatch):
    monkeypatch.setenv("BLING_LEAD_DEFAULT_STAGE", "negociando")
    assert cfg.lead_default_stage() == "negociando"


def test_authorize_e_token_url_usam_hosts_diferentes_de_proposito():
    # bling.com.br (autorizacao, fluxo do navegador) e api.bling.com.br (troca de
    # token, servidor a servidor) sao hosts distintos no Bling — nao unificar.
    assert cfg.AUTHORIZE_URL.startswith("https://bling.com.br/")
    assert cfg.TOKEN_URL.startswith("https://api.bling.com.br/")


def test_transient_contem_apenas_erros_retentaveis():
    from app.bling.errors import TRANSIENT

    assert TRANSIENT == (BlingRateLimitError, BlingServerError)
    assert BlingValidationError not in TRANSIENT
    assert BlingAuthError not in TRANSIENT


def test_bling_validation_error_guarda_os_kwargs():
    erro = BlingValidationError(
        "campo invalido", type_="VALIDATION", description="preco negativo",
        status=422, payload={"campo": "preco"},
    )
    assert erro.type == "VALIDATION"
    assert erro.description == "preco negativo"
    assert erro.status == 422
    assert erro.payload == {"campo": "preco"}


def test_bling_validation_error_funciona_so_com_mensagem():
    erro = BlingValidationError("campo invalido")
    assert str(erro) == "campo invalido"
    assert erro.type == ""
    assert erro.description == ""
    assert erro.status == 400
    assert erro.payload == {}
