"""Context caching explícito (27/07/2026) — guardas do prefixo cacheável.

Contexto (spec 2026-07-27-gemini-context-caching-design.md): a Valéria ficou 5 dias muda
após estourar o teto de gasto MENSAL da Gemini API. O turno carrega ~36K tokens de
entrada para ~47 de saída, e o implicit caching descontava só 10-32% disso de forma não
determinística. O cache explícito troca essa loteria por um desconto contratual de 90%.

Este arquivo trava os invariantes que tornam a mudança segura:
  1. INERTE POR DEFAULT: sem GEMINI_EXPLICIT_CACHE=on, nada muda e a API nem é tocada.
  2. FAIL-OPEN: qualquer falha na criação do cache devolve None — o turno segue normal.
  3. CORTE EXATO: build_system_prompt_parts concatenado é BYTE-IDÊNTICO ao
     build_system_prompt histórico (nenhum caller percebe a separação).
  4. CHAVE ESTÁVEL: mesmo prefixo => mesma chave; um byte diferente => chave diferente.
"""
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

CATALOG = "## Cafe Classico 250g\nPreco: R$28,70"
# Nome propositalmente improvável: "Rafael"/"Arthur" aparecem no BASE_STATIC como
# exemplos de nome próprio, o que tornaria o assert de vazamento inconclusivo.
LEAD = {"id": "l1", "name": "Wenceslau", "company": None, "phone": "5534999998888"}


@pytest.fixture(autouse=True)
def _clean_index():
    """Índice local zerado entre testes — ele é estado de módulo."""
    from app.agent import prompt_cache
    prompt_cache.invalidate_all()
    yield
    prompt_cache.invalidate_all()


# ---------------------------------------------------------------------------
# 1. Inerte por default
# ---------------------------------------------------------------------------
def test_flag_desligada_por_default(monkeypatch):
    from app.agent import prompt_cache
    monkeypatch.delenv("GEMINI_EXPLICIT_CACHE", raising=False)
    assert prompt_cache.cache_enabled() is False


@pytest.mark.anyio
async def test_flag_off_nao_chama_api(monkeypatch, anyio_backend):
    from app.agent import prompt_cache
    monkeypatch.delenv("GEMINI_EXPLICIT_CACHE", raising=False)

    with patch("app.agent.gemini_client.get_genai_client") as client:
        assert await prompt_cache.get_or_create("gemini-2.5-flash", "x" * 50_000) is None
        client.assert_not_called()


@pytest.mark.anyio
async def test_prefixo_curto_nao_chama_api(monkeypatch, anyio_backend):
    """Abaixo do mínimo da API (2.048 tokens) nem tentamos — evita 400 garantido."""
    from app.agent import prompt_cache
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE", "on")

    with patch("app.agent.gemini_client.get_genai_client") as client:
        assert await prompt_cache.get_or_create("gemini-2.5-flash", "curto") is None
        client.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Fail-open
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_falha_na_criacao_devolve_none(monkeypatch, anyio_backend):
    """Cache é otimização: se a criação explode, o turno segue sem cache."""
    from app.agent import prompt_cache
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE", "on")

    client = MagicMock()
    client.aio.caches.create = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("app.agent.gemini_client.get_genai_client", return_value=client):
        assert await prompt_cache.get_or_create("gemini-2.5-flash", "x" * 50_000) is None


@pytest.mark.anyio
async def test_cache_sem_name_devolve_none(monkeypatch, anyio_backend):
    from app.agent import prompt_cache
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE", "on")

    created = MagicMock()
    created.name = None
    client = MagicMock()
    client.aio.caches.create = AsyncMock(return_value=created)
    with patch("app.agent.gemini_client.get_genai_client", return_value=client):
        assert await prompt_cache.get_or_create("gemini-2.5-flash", "x" * 50_000) is None


@pytest.mark.anyio
async def test_reusa_cache_do_indice_sem_recriar(monkeypatch, anyio_backend):
    from app.agent import prompt_cache
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE", "on")

    created = MagicMock()
    created.name = "cachedContents/abc"
    client = MagicMock()
    client.aio.caches.create = AsyncMock(return_value=created)
    prefix = "x" * 50_000

    with patch("app.agent.gemini_client.get_genai_client", return_value=client):
        first = await prompt_cache.get_or_create("gemini-2.5-flash", prefix)
        second = await prompt_cache.get_or_create("gemini-2.5-flash", prefix)

    assert first == second == "cachedContents/abc"
    assert client.aio.caches.create.await_count == 1, "criou duas vezes o mesmo prefixo"


@pytest.mark.anyio
async def test_entrada_expirada_recria(monkeypatch, anyio_backend):
    from app.agent import prompt_cache
    monkeypatch.setenv("GEMINI_EXPLICIT_CACHE", "on")

    created = MagicMock()
    created.name = "cachedContents/abc"
    client = MagicMock()
    client.aio.caches.create = AsyncMock(return_value=created)
    prefix = "x" * 50_000

    with patch("app.agent.gemini_client.get_genai_client", return_value=client):
        await prompt_cache.get_or_create("gemini-2.5-flash", prefix)
        # força a entrada a estar vencida
        key = prompt_cache.cache_key("gemini-2.5-flash", prefix)
        name, _ = prompt_cache._index[key]
        prompt_cache._index[key] = (name, 0.0)
        await prompt_cache.get_or_create("gemini-2.5-flash", prefix)

    assert client.aio.caches.create.await_count == 2


# ---------------------------------------------------------------------------
# 3. Chave estável
# ---------------------------------------------------------------------------
def test_chave_estavel_e_sensivel_a_um_byte():
    from app.agent.prompt_cache import cache_key
    a = cache_key("gemini-2.5-flash", "prefixo estatico")
    b = cache_key("gemini-2.5-flash", "prefixo estatico")
    c = cache_key("gemini-2.5-flash", "prefixo estatica")
    d = cache_key("gemini-2.5-flash-lite", "prefixo estatico")
    assert a == b
    assert a != c, "um byte diferente tem que gerar outra chave"
    assert a != d, "modelo diferente tem que gerar outra chave"


def test_chave_nao_colide_por_concatenacao():
    """('ab','c') e ('a','bc') não podem colidir — daí o separador \\x00."""
    from app.agent.prompt_cache import cache_key
    assert cache_key("ab", "c") != cache_key("a", "bc")


def test_invalidate_remove_do_indice():
    from app.agent import prompt_cache
    key = prompt_cache.cache_key("m", "p")
    prompt_cache._index[key] = ("cachedContents/x", 9e12)
    prompt_cache.invalidate("m", "p")
    assert key not in prompt_cache._index


# ---------------------------------------------------------------------------
# 4. Corte exato do prompt (o invariante mais crítico)
# ---------------------------------------------------------------------------
def _parts(lead_context=None):
    from app.agent.orchestrator import build_system_prompt_parts
    return build_system_prompt_parts(
        LEAD, "atacado", prompt_key="valeria_inbound",
        lead_context=lead_context, catalog_text=CATALOG,
    )


def test_partes_concatenadas_sao_o_prompt_completo():
    """Contrato de não-regressão: nenhum caller pode perceber a separação."""
    from app.agent.orchestrator import build_system_prompt
    static_part, volatile_part = _parts()
    completo = build_system_prompt(
        LEAD, "atacado", prompt_key="valeria_inbound", catalog_text=CATALOG,
    )
    assert "\n\n".join([static_part, volatile_part]) == completo


def test_estatico_nao_contem_bloco_volatil():
    """Nada que varie por lead/dia pode estar no prefixo — senão o cache nunca bate.

    NÃO se testa pela tag `<context>` isolada: os prompts de stage também usam essa tag
    para o próprio contexto ESTÁTICO do funil. O que identifica o bloco volátil é o seu
    conteúdo (data, saudação, dados do lead), gerado por build_context_block.
    """
    static_part, volatile_part = _parts()
    for marcador in ("# CONTEXTO TEMPORAL", "Hoje e:", "Saudacao sugerida:", "# SOBRE O LEAD"):
        assert marcador not in static_part, f"volátil vazou pro prefixo: {marcador}"
        assert marcador in volatile_part
    assert LEAD["name"] not in static_part, "nome do lead vazou pro prefixo cacheável"
    assert "<final_instruction>" not in static_part


def test_estatico_e_identico_entre_leads_diferentes():
    """O prefixo tem que ser byte-idêntico cross-lead, senão o cache é inútil."""
    from app.agent.orchestrator import build_system_prompt_parts
    a, _ = build_system_prompt_parts(
        {"id": "1", "name": "Ana", "company": "X"}, "atacado",
        prompt_key="valeria_inbound", catalog_text=CATALOG,
    )
    b, _ = build_system_prompt_parts(
        {"id": "2", "name": "Bruno", "company": "Y"}, "atacado",
        prompt_key="valeria_inbound", catalog_text=CATALOG,
    )
    assert a == b


def test_estatico_muda_com_stage_e_catalogo():
    """Stage/catálogo diferentes têm que gerar prefixos (e portanto caches) distintos."""
    from app.agent.orchestrator import build_system_prompt_parts
    base, _ = build_system_prompt_parts(
        LEAD, "atacado", prompt_key="valeria_inbound", catalog_text=CATALOG,
    )
    outro_stage, _ = build_system_prompt_parts(
        LEAD, "private_label", prompt_key="valeria_inbound", catalog_text=CATALOG,
    )
    outro_catalogo, _ = build_system_prompt_parts(
        LEAD, "atacado", prompt_key="valeria_inbound", catalog_text="## Outro\nPreco: R$1,00",
    )
    assert base != outro_stage
    assert base != outro_catalogo


def test_estatico_grande_o_suficiente_para_valer_cache():
    """Se o prefixo caísse abaixo do piso da API, o cache viraria no-op silencioso."""
    from app.agent.prompt_cache import _MIN_CHARS_DEFAULT
    static_part, _ = _parts()
    assert len(static_part) > _MIN_CHARS_DEFAULT


# ---------------------------------------------------------------------------
# 5. Integração com generate()
# ---------------------------------------------------------------------------
def test_is_cache_error_so_dispara_com_a_palavra_cache():
    from app.agent.gemini_client import _is_cache_error
    assert _is_cache_error(Exception("CachedContent not found")) is True
    assert _is_cache_error(Exception("404 cache expired")) is True
    # 404 comum (falso-sunset) NÃO pode ser confundido com erro de cache
    assert _is_cache_error(Exception("404 model no longer available")) is False
    assert _is_cache_error(Exception("429 RESOURCE_EXHAUSTED")) is False
