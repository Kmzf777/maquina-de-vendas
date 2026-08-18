"""Configuracao da integracao Bling, lida de os.getenv.

Segue o padrao de `app/campaigns/google_ads.py`: env cru via os.getenv em vez de
campo no Settings do pydantic. Motivo pratico — o Settings tem `extra: allow`, que
aceita a variavel no .env mas NAO cria o atributo, entao `settings.bling_client_id`
levantaria AttributeError.
"""
import os

# A v3 e a unica com OAuth/JWT. A v2 esta descontinuada.
API_BASE = "https://api.bling.com.br/Api/v3"
AUTHORIZE_URL = "https://bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://api.bling.com.br/Api/v3/oauth/token"

# Limites publicados pelo Bling (developer.bling.com.br/limites), por CONTA.
REQUESTS_PER_SECOND = 3
DAILY_LIMIT = 120_000
# Margem de 8% sobre o teto diario: preferimos recusar localmente (e enfileirar)
# a levar 429 do Bling, porque erro em rajada tambem conta para bloqueio de IP
# (300 erros em 10s => 10 min de bloqueio).
DAILY_SOFT_CAP = 110_000


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _env_int(name: str) -> int | None:
    raw = _env(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def enabled() -> bool:
    return _env("BLING_ENABLED").lower() in ("1", "true", "yes", "on")


def client_id() -> str:
    return _env("BLING_CLIENT_ID")


def client_secret() -> str:
    return _env("BLING_CLIENT_SECRET")


def redirect_uri() -> str:
    return _env("BLING_REDIRECT_URI")


def store_id() -> int | None:
    return _env_int("BLING_STORE_ID")


def order_situacao_id() -> int | None:
    return _env_int("BLING_ORDER_SITUACAO_ID")


def lead_default_stage() -> str:
    return _env("BLING_LEAD_DEFAULT_STAGE") or "novo"


def require_credentials() -> tuple[str, str]:
    """Devolve (client_id, client_secret) ou levanta BlingNotConfigured."""
    from app.bling.errors import BlingNotConfigured

    cid, csec = client_id(), client_secret()
    if not cid or not csec:
        raise BlingNotConfigured(
            "BLING_CLIENT_ID e BLING_CLIENT_SECRET precisam estar configurados"
        )
    return cid, csec
