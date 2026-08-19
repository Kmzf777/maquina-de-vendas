"""Cliente HTTP unico da API v3 do Bling.

Toda chamada ao Bling no sistema passa por aqui — e o que garante que o
token-bucket de 3 req/s (limite por CONTA) seja respeitado de verdade.

Politica de retry, derivada da pagina de erros do Bling:
  401 -> invalida o cache do token, renova UMA vez e repete. Segunda falha e
         BlingAuthError (precisa refazer o OAuth).
  429 -> backoff exponencial 1s/2s/4s, 3 tentativas (configuravel por instancia).
  5xx / timeout -> mesmo backoff.
  4xx de validacao -> levanta na hora, SEM retry. Repetir o mesmo payload
         invalido so queima orcamento e conta para o bloqueio de IP
         (300 erros em 10s = 10 min bloqueado).
"""
import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from app.bling import auth, config, ratelimit
from app.bling.errors import (
    BlingAuthError, BlingRateLimitError, BlingServerError, BlingValidationError,
)

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 1.0
_PAGE_LIMIT = 100
# Teto de seguranca do paginate(): 1000 paginas x 100 itens/pagina = 100 mil
# registros, folga generosa acima de qualquer catalogo ou base de contatos
# real. Sem isso, um bug do lado do Bling que sempre devolve pagina cheia (ou
# um `limite` ignorado) so para quando o teto DIARIO local de requisicoes
# estoura — a 3 req/s isso consome a quota inteira em ~6 minutos e trava
# modal de venda, sync e webhook pelo resto do dia. Estourar o teto e falha
# alta (BlingServerError), nao truncamento silencioso: um sync incompleto sem
# ninguem perceber vira dado errado no CRM.
_MAX_PAGES = 1000


class BlingClient:
    """Wrapper de httpx com auth, rate limit e retry.

    `http` existe para os testes injetarem um duble; em producao o cliente cria
    o proprio httpx.AsyncClient.
    """

    def __init__(self, http: Any | None = None, timeout: float = 30.0,
                 max_attempts: int = _MAX_ATTEMPTS):
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout
        # Configuravel por instancia: o modal de venda (sincrono, vendedor
        # olhando a tela) precisa de um teto bem menor que o do sync em lote
        # ou o do processamento de webhook, que podem esperar mais. O default
        # preserva o comportamento anterior (3 tentativas).
        self._max_attempts = max_attempts

    async def _client(self):
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        await self.aclose()
        return False

    async def _headers(self) -> dict:
        token = await auth.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            # Obrigatorio: sem isso o Bling devolve o token opaco descontinuado.
            "enable-jwt": "1",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def request(self, method: str, path: str, *, params: dict | None = None,
                      json: dict | None = None) -> dict:
        url = f"{config.API_BASE}{path}"
        renovou = False

        for attempt in range(1, self._max_attempts + 1):
            # Consome uma vaga do orcamento a CADA tentativa — a tentativa
            # repetida tambem e uma requisicao real para o Bling.
            await ratelimit.acquire()
            http = await self._client()
            try:
                resp = await http.request(
                    method, url, headers=await self._headers(),
                    params=params, json=json,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == self._max_attempts:
                    logger.warning(
                        "[BLING] %s %s: tentativas esgotadas (tentativa %s/%s) "
                        "apos erro de transporte: %s",
                        method, path, attempt, self._max_attempts, exc,
                    )
                    raise BlingServerError(f"{method} {path}: {exc}") from exc
                logger.warning(
                    "[BLING] %s %s: erro de transporte na tentativa %s/%s, "
                    "tentando de novo — %s",
                    method, path, attempt, self._max_attempts, exc,
                )
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            status = resp.status_code

            if 200 <= status < 300:
                try:
                    return resp.json()
                except ValueError:
                    # 204 (sem corpo) cai aqui normalmente — silencioso, de
                    # proposito. Corpo NAO vazio que falha o parse e outra
                    # historia: proxy quebrado ou HTML de erro disfarcado de
                    # 200. No fluxo de criacao de pedido isso pode significar
                    # que o pedido nasceu no Bling e o id de retorno se
                    # perdeu no parse — silencio aqui vira pedido duplicado
                    # quando o vendedor tenta de novo. Loga sem o corpo (pode
                    # ser grande ou sensivel), so o suficiente pra investigar.
                    if getattr(resp, "content", b""):
                        logger.error(
                            "[BLING] %s %s: HTTP %s com corpo nao vazio que "
                            "falhou o parse JSON",
                            method, path, status,
                        )
                    return {}

            if status == 401:
                if renovou:
                    raise BlingAuthError(
                        f"{method} {path}: 401 apos renovar o token — refaca o OAuth"
                    )
                renovou = True
                await auth.invalidate_cache()
                continue

            if status == 429:
                if attempt == self._max_attempts:
                    logger.warning(
                        "[BLING] %s %s: 429 esgotou as tentativas (tentativa %s/%s)",
                        method, path, attempt, self._max_attempts,
                    )
                    raise BlingRateLimitError(f"{method} {path}: 429 do Bling")
                logger.warning(
                    "[BLING] %s %s: 429 na tentativa %s/%s, tentando de novo",
                    method, path, attempt, self._max_attempts,
                )
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            if status >= 500:
                if attempt == self._max_attempts:
                    logger.warning(
                        "[BLING] %s %s: HTTP %s esgotou as tentativas "
                        "(tentativa %s/%s)",
                        method, path, status, attempt, self._max_attempts,
                    )
                    raise BlingServerError(f"{method} {path}: HTTP {status}")
                logger.warning(
                    "[BLING] %s %s: HTTP %s na tentativa %s/%s, tentando de novo",
                    method, path, status, attempt, self._max_attempts,
                )
                await asyncio.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            # 4xx de validacao: nunca retenta.
            body = {}
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                pass
            err = (body or {}).get("error") or {}
            raise BlingValidationError(
                err.get("message") or f"{method} {path}: HTTP {status}",
                type_=err.get("type") or "",
                description=err.get("description") or "",
                status=status,
                payload=body,
            )

        raise BlingServerError(f"{method} {path}: tentativas esgotadas")

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: dict | None = None) -> dict:
        return await self.request("POST", path, json=json)

    async def put(self, path: str, json: dict | None = None) -> dict:
        return await self.request("PUT", path, json=json)

    async def paginate(self, path: str, params: dict | None = None,
                       limite: int = _PAGE_LIMIT) -> AsyncIterator[dict]:
        """Itera todas as paginas ate a pagina vir incompleta ou vazia.

        Teto de seguranca em _MAX_PAGES (ver comentario na constante do
        modulo): estourar o teto e falha alta, nao fim silencioso de
        paginacao.
        """
        pagina = 1
        while True:
            if pagina > _MAX_PAGES:
                logger.error(
                    "[BLING] paginate excedeu o teto de %s paginas em %s — "
                    "abortando",
                    _MAX_PAGES, path,
                )
                raise BlingServerError(
                    f"paginate {path}: excedeu o teto de {_MAX_PAGES} paginas"
                )
            page_params = dict(params or {})
            page_params.update({"pagina": pagina, "limite": limite})
            body = await self.get(path, page_params)
            itens = body.get("data") or []
            for item in itens:
                yield item
            if len(itens) < limite:
                return
            pagina += 1
