"""Catálogo: fallback para o último cache válido em erro de fetch (FinOps 08/07/2026).

O catálogo dinâmico do banco é a fonte ÚNICA de preços do agente (os roteiros apontam
para a tag <catalogo_de_produtos> — nada hardcoded). O fail-open antigo devolvia "" em
qualquer erro de DB: a Valéria ficava SEM NENHUM preço durante a janela de falha e caía
em "confirmo com o João" para tudo. Agora um fetch com erro serve o último markdown
válido (stale) — sem renovar o TTL, para a próxima chamada tentar o banco de novo.
"""
import time

import pytest

from app.agent import catalog


@pytest.fixture(autouse=True)
def _clean_cache():
    catalog.clear_cache()
    yield
    catalog.clear_cache()


def _products():
    return [{"sector": "atacado", "name": "Suave", "price_formatted": "R$28,70",
             "min_lot": "100", "description": "torra media", "image_urls": ""}]


def test_erro_de_fetch_serve_ultimo_catalogo_valido(monkeypatch):
    monkeypatch.setattr(catalog, "_fetch_active_products", _products)
    ok = catalog.get_products_by_funnel("atacado")
    assert "Suave" in ok

    # expira o TTL na mão e faz o banco falhar → serve o stale, não ""
    ts, markdown = catalog._cache["atacado"]
    catalog._cache["atacado"] = (ts - catalog._CACHE_TTL_SECONDS - 1, markdown)

    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog, "_fetch_active_products", _boom)
    stale = catalog.get_products_by_funnel("atacado")
    assert stale == markdown, "erro de fetch deveria servir o último catálogo válido"


def test_stale_nao_renova_ttl(monkeypatch):
    """Servir stale não pode 'curar' o cache — a próxima chamada tenta o banco de novo."""
    monkeypatch.setattr(catalog, "_fetch_active_products", _products)
    catalog.get_products_by_funnel("atacado")
    ts_old = catalog._cache["atacado"][0] - catalog._CACHE_TTL_SECONDS - 1
    catalog._cache["atacado"] = (ts_old, catalog._cache["atacado"][1])

    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog, "_fetch_active_products", _boom)
    catalog.get_products_by_funnel("atacado")
    catalog.get_products_by_funnel("atacado")
    assert calls["n"] == 2, "stale renovou o TTL — banco não foi re-tentado"


def test_erro_sem_cache_previo_continua_fail_open_vazio(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog, "_fetch_active_products", _boom)
    assert catalog.get_products_by_funnel("atacado") == ""
