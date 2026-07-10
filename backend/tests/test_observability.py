"""Sentry fail-open: sem DSN é no-op absoluto; com DSN inicializa com environment."""
from unittest.mock import MagicMock, patch

from app.observability import init_sentry


def test_sem_dsn_e_noop_que_nao_levanta(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False  # não inicializou, não levantou


def test_dsn_vazio_e_noop(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "")
    assert init_sentry() is False


def test_com_dsn_chama_sentry_init(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    fake_sdk = MagicMock()
    with patch.dict("sys.modules", {"sentry_sdk": fake_sdk}):
        assert init_sentry() is True
    kwargs = fake_sdk.init.call_args.kwargs
    assert kwargs["dsn"] == "https://key@o0.ingest.sentry.io/0"
    assert kwargs["environment"] in ("dev", "production")
    assert kwargs["traces_sample_rate"] == 0.0


def test_sdk_ausente_e_failopen(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    import builtins
    real_import = builtins.__import__

    def no_sentry(name, *a, **k):
        if name == "sentry_sdk":
            raise ImportError("sem sdk")
        return real_import(name, *a, **k)

    with patch.object(builtins, "__import__", side_effect=no_sentry):
        assert init_sentry() is False  # falta do pacote não derruba o app
