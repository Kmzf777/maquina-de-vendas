"""Configuracao da integracao Bling, lida de os.getenv.

Segue o padrao de `app/campaigns/google_ads.py`: env cru via os.getenv em vez de
campo no Settings do pydantic. Motivo pratico — o Settings tem `extra: allow`, que
aceita a variavel no .env mas NAO cria o atributo, entao `settings.bling_client_id`
levantaria AttributeError.
"""
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# A v3 e a unica com OAuth/JWT. A v2 esta descontinuada.
API_BASE = "https://api.bling.com.br/Api/v3"
AUTHORIZE_URL = "https://bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://api.bling.com.br/Api/v3/oauth/token"

DEFAULT_ACCOUNT = "default"

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
        logger.warning("Valor invalido para %s: %r (esperava inteiro)", name, raw)
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


def is_configured() -> bool:
    """Tem credenciais para falar com o Bling? Fonte unica desta regra."""
    return bool(client_id() and client_secret())


def require_credentials() -> tuple[str, str]:
    """Devolve (client_id, client_secret) ou levanta BlingNotConfigured."""
    from app.bling.errors import BlingNotConfigured

    if not is_configured():
        raise BlingNotConfigured(
            "BLING_CLIENT_ID e BLING_CLIENT_SECRET precisam estar configurados"
        )
    return client_id(), client_secret()


@dataclass(frozen=True)
class BlingAccount:
    """Uma conta Bling configurada. `key` e o slug usado como chave em tudo."""
    key: str
    label: str
    client_id: str
    client_secret: str
    store_id: int | None
    situacao_id: int | None

    @property
    def configured(self) -> bool:
        """Tem credenciais para falar com o Bling nesta conta.

        Mesma regra de is_configured() (fonte unica para a conta default),
        agora por conta — evita que cada modulo que precisa checar uma conta
        especifica reimplemente esta comparacao na mao.
        """
        return bool(self.client_id and self.client_secret)


def _suffixed(name: str, key: str) -> str:
    """BLING_<CONTA>_<NAME>. A conta default NUNCA recebe sufixo — e o que
    mantem todas as variaveis de ambiente de hoje valendo sem alteracao."""
    if key == DEFAULT_ACCOUNT:
        return f"BLING_{name}"
    return f"BLING_{key.upper()}_{name}"


def _env_source(name: str, key: str) -> tuple[str, str]:
    """Valor da conta com fallback para a variavel global, junto do NOME da
    variavel que efetivamente forneceu o valor (sufixada ou global).

    O fallback e o que permite um unico aplicativo Bling autorizado nas duas
    contas: client_id/secret sao compartilhados e so o label e o store_id
    entram por conta. O nome-fonte existe para _env_int_for apontar, no
    warning de valor invalido, a variavel certa — que pode ser a global
    quando a sufixada nem esta definida.
    """
    suffixed_name = _suffixed(name, key)
    valor = _env(suffixed_name)
    if valor:
        return valor, suffixed_name
    global_name = f"BLING_{name}"
    return _env(global_name), global_name


def _env_for(name: str, key: str) -> str:
    """Valor da conta, caindo para a variavel global quando a especifica falta."""
    return _env_source(name, key)[0]


def _env_int_for(name: str, key: str) -> int | None:
    bruto, fonte = _env_source(name, key)
    if not bruto:
        return None
    try:
        return int(bruto)
    except ValueError:
        logger.warning("Valor invalido para %s: %r (esperava inteiro)", fonte, bruto)
        return None


def account_keys() -> list[str]:
    """Slugs configurados. 'default' esta SEMPRE presente — e prependida
    quando BLING_ACCOUNTS nao a cita — porque e a conta que ja existia antes
    deste roster e account() sem argumento (todo call site de hoje) depende
    dela nunca sumir por causa de um typo no env. Duplicatas sao removidas
    preservando a ordem.
    """
    bruto = _env("BLING_ACCOUNTS")
    chaves = [p.strip().lower() for p in bruto.split(",") if p.strip()]
    if DEFAULT_ACCOUNT not in chaves:
        chaves.insert(0, DEFAULT_ACCOUNT)
    return list(dict.fromkeys(chaves))


def account(key: str = DEFAULT_ACCOUNT) -> BlingAccount:
    """Resolve o slug (trim + lowercase; vazio ou None cai para 'default')
    na BlingAccount configurada. Levanta BlingUnknownAccount se o slug
    normalizado nao estiver em account_keys().
    """
    from app.bling.errors import BlingUnknownAccount

    key = (key or DEFAULT_ACCOUNT).strip().lower()
    if key not in account_keys():
        raise BlingUnknownAccount(f"conta Bling desconhecida: {key!r}")
    return BlingAccount(
        key=key,
        # LABEL nao usa _env_for de proposito: nao faz sentido a conta 2 herdar
        # o rotulo da conta 1 — o rotulo existe justamente para distingui-las.
        label=_env(_suffixed("LABEL", key)) or key,
        client_id=_env_for("CLIENT_ID", key),
        client_secret=_env_for("CLIENT_SECRET", key),
        store_id=_env_int_for("STORE_ID", key),
        situacao_id=_env_int_for("ORDER_SITUACAO_ID", key),
    )


def accounts() -> list[BlingAccount]:
    """Todas as contas configuradas, na mesma ordem de account_keys()
    ('default' primeiro quando o env nao a menciona explicitamente)."""
    return [account(k) for k in account_keys()]
