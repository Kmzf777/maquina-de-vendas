import logging
import threading
import time

import httpx
from supabase import create_client, Client

from app.config import settings

logger = logging.getLogger(__name__)

# Cliente Supabase POR THREAD.
#
# O cliente httpx interno (pool de conexões HTTP/2) NÃO é seguro para uso concorrente
# entre threads. Compartilhar um único client (singleton) entre o event loop e o
# ThreadPoolExecutor do meta_audit causava `deque mutated during iteration` no pool h2
# (o pool é iterado por uma thread enquanto outra o muta). Um cliente por thread isola
# os pools e elimina a corrida — cada thread (loop principal + workers do audit) usa o seu.
_thread_local = threading.local()


def get_supabase() -> Client:
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = create_client(settings.supabase_url, settings.supabase_service_key)
        _thread_local.client = client
    return client


# Retry para quedas de conexão HTTP/2 (GOAWAY / ConnectionTerminated) sob rajada de
# disparo. A Meta envia GOAWAY e o httpx levanta RemoteProtocolError (subclasse de
# httpx.TransportError) no meio do request — sem retry, o save/insert se perde.
_DB_RETRY_ATTEMPTS = 3
_DB_RETRY_BASE_DELAY = 0.5  # segundos (backoff linear: 0.5s, 1.0s)


def run_with_retry(fn, *args, label: str = "db", **kwargs):
    """Executa uma chamada Supabase SÍNCRONA com retry em quedas de conexão.

    Repete SOMENTE em `httpx.TransportError` — cobre RemoteProtocolError (GOAWAY/
    ConnectionTerminated), ConnectError, ReadError. NUNCA repete em HTTPStatusError,
    então erros de aplicação (4xx/5xx) não são mascarados. `fn` deve refazer o request
    inteiro a cada tentativa (ex: `lambda: get_supabase().table(...).insert(...).execute()`)
    para que uma conexão derrubada seja reaberta limpa.
    """
    last_exc: Exception | None = None
    for attempt in range(1, _DB_RETRY_ATTEMPTS + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.TransportError as exc:
            last_exc = exc
            logger.warning(
                "[DB RETRY] %s — tentativa %d/%d falhou (conexão): %s",
                label, attempt, _DB_RETRY_ATTEMPTS, exc,
            )
            if attempt < _DB_RETRY_ATTEMPTS:
                time.sleep(_DB_RETRY_BASE_DELAY * attempt)
    raise last_exc
