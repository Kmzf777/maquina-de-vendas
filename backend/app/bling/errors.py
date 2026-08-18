"""Hierarquia de erros da integracao Bling.

A distincao que importa no fluxo de venda: erro TRANSITORIO (rate limit, 5xx,
timeout) vai para a fila e e retentado; erro de VALIDACAO nao vai — repetir o
mesmo payload invalido nunca conserta.
"""


class BlingError(Exception):
    """Base de todos os erros da integracao."""


class BlingNotConfigured(BlingError):
    """Faltam BLING_CLIENT_ID / BLING_CLIENT_SECRET, ou nunca houve autorizacao."""


class BlingAuthError(BlingError):
    """401 apos tentativa de renovacao — precisa refazer o fluxo OAuth."""


class BlingRateLimitError(BlingError):
    """429 do Bling, ou o token-bucket local recusou. TRANSITORIO."""


class BlingDailyCapError(BlingRateLimitError):
    """Teto diario local atingido. TRANSITORIO (destrava na virada do dia)."""


class BlingServerError(BlingError):
    """5xx ou timeout. TRANSITORIO."""


class BlingValidationError(BlingError):
    """4xx de validacao. NAO retentar.

    Carrega os campos que o Bling devolve em `error` para repassar ao vendedor.
    """

    def __init__(self, message: str, *, type_: str = "", description: str = "",
                 status: int = 400, payload: dict | None = None):
        super().__init__(message)
        self.type = type_
        self.description = description
        self.status = status
        self.payload = payload or {}


TRANSIENT = (BlingRateLimitError, BlingServerError)
