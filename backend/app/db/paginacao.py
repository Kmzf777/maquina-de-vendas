"""Paginação de consultas do supabase-py contra o teto silencioso de 1000 linhas do PostgREST."""
from typing import Any, Callable

PAGE = 1000  # teto de linhas por resposta do PostgREST


def paginar(query_factory: Callable[[], Any], page: int = PAGE) -> list[dict[str, Any]]:
    """Pagina com `.range()` até vir página incompleta.

    `query_factory` é chamado a cada página (o builder do supabase-py acumula estado) e a query
    precisa de `.order()` por chave única, senão o Postgres pode repetir/pular linhas entre páginas."""
    rows: list[dict[str, Any]] = []
    i = 0
    while True:
        data = query_factory().range(i, i + page - 1).execute().data or []
        rows.extend(data)
        if len(data) < page:
            return rows
        i += page
