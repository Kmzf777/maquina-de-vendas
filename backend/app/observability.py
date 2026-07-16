"""Sentry fail-open: captura de exceções com stack trace quando SENTRY_DSN existe.

Sem DSN (ou sem o pacote instalado), o app funciona identicamente — nenhuma
exceção, nenhum efeito. O watchdog continua cobrindo estados de negócio; o
Sentry cobre a classe `try/except Exception` que hoje vira warning silencioso.
"""
import logging
import os

logger = logging.getLogger(__name__)


def init_sentry() -> bool:
    """Inicializa o Sentry se SENTRY_DSN estiver definido. Retorna True se ativo."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("[OBS] SENTRY_DSN ausente — Sentry desativado (fail-open)")
        return False
    try:
        import sentry_sdk

        from app.config import get_settings
        environment = "dev" if get_settings().is_dev_env else "production"
        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=0.0,  # só erros; sem tracing (free tier)
        )
        logger.info("[OBS] Sentry ativo (environment=%s)", environment)
        return True
    except Exception as exc:
        logger.warning("[OBS] falha ao inicializar Sentry (seguindo sem): %s", exc)
        return False
