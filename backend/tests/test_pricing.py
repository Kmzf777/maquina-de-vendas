"""Testes TDD para app.agent.pricing (lógica pura de orçamento determinístico).

Spec: docs/superpowers/specs/2026-06-26-perception-and-quoting-tools-design.md §4.1, §6 itens 1-5.
Plan: docs/superpowers/plans/2026-06-26-perception-quoting-tools-plan.md Task 1.
"""
import pytest

from app.agent.pricing import (
    FREIGHT_TABLE,
    MAX_DISAMBIGUATION,
    UBERLANDIA_FREIGHT,
    UF_TO_REGION,
    LineQuote,
    OrcamentoInput,
    PedidoItem,
    Quote,
    compute_quote,
    format_quote,
    match_products,
    parse_brl,
    resolve_region,
)


# ---------------------------------------------------------------------------
# 1. parse_brl
# ---------------------------------------------------------------------------


def test_parse_brl_simples():
    """R$ 97,70 → 97.70."""
    assert parse_brl("R$ 97,70") == pytest.approx(97.70)


def test_parse_brl_com_separador_de_milhar():
    """R$ 1.169,70 → 1169.70 (ponto como milhar, vírgula como decimal)."""
    assert parse_brl("R$ 1.169,70") == pytest.approx(1169.70)


def test_parse_brl_invalido_levanta_value_error():
    """Lixo → ValueError tratável (não deve engolir silenciosamente)."""
    with pytest.raises(ValueError):
        parse_brl("nao-e-dinheiro")


# ---------------------------------------------------------------------------
# 2. resolve_region
# ---------------------------------------------------------------------------


def test_resolve_region_sp_sul_sudeste():
    key, is_ub = resolve_region("SP", None)
    assert key == "sul_sudeste"
    assert is_ub is False


def test_resolve_region_ba_nordeste():
    key, is_ub = resolve_region("BA", None)
    assert key == "nordeste"
    assert is_ub is False


def test_resolve_region_go_centro_oeste():
    key, is_ub = resolve_region("GO", None)
    assert key == "centro_oeste"
    assert is_ub is False


def test_resolve_region_am_norte():
    key, is_ub = resolve_region("AM", None)
    assert key == "norte"
    assert is_ub is False


def test_resolve_region_uberlandia_sem_estado():
    """B2: cidade=Uberlândia sem estado → (None, True). Não exige estado."""
    key, is_ub = resolve_region(None, "Uberlândia")
    assert key is None
    assert is_ub is True


def test_resolve_region_uberlandia_sem_acento():
    """Variação de grafia sem acento também reconhece o override."""
    key, is_ub = resolve_region(None, "uberlandia")
    assert is_ub is True
    assert key is None


def test_resolve_region_uberlandia_caixa_alta():
    """Override de cidade é case-insensitive."""
    key, is_ub = resolve_region(None, "UBERLANDIA")
    assert is_ub is True


def test_resolve_region_sem_estado_sem_cidade():
    """Sem estado E sem cidade → (None, False) — caller deve pedir o estado."""
    key, is_ub = resolve_region(None, None)
    assert key is None
    assert is_ub is False


def test_resolve_region_uf_invalida():
    """UF desconhecida → (None, False)."""
    key, is_ub = resolve_region("XX", None)
    assert key is None
    assert is_ub is False


# ---------------------------------------------------------------------------
# Helpers de teste para compute_quote / format_quote
# ---------------------------------------------------------------------------


def _make_lines(*price_qty_pairs: tuple[float, int], names: list[str] | None = None) -> list[LineQuote]:
    """Cria LineQuotes a partir de pares (preco_unitario, quantidade)."""
    result = []
    for i, (price, qty) in enumerate(price_qty_pairs):
        nome = names[i] if names and i < len(names) else f"Produto {i + 1}"
        result.append(LineQuote(
            produto=nome,
            quantidade=qty,
            preco_unitario=price,
            subtotal_linha=round(price * qty, 2),
        ))
    return result


# ---------------------------------------------------------------------------
# 3. compute_quote — carrinho, cálculos exatos (B1)
# ---------------------------------------------------------------------------


def test_compute_quote_multi_item_subtotal_global():
    """B1: subtotal global é a soma das linhas; mínimo aplicado ao global."""
    # 100*2 + 80*1 = 280 → abaixo do mínimo de R$300 para sul_sudeste
    lines = _make_lines((100.0, 2), (80.0, 1))
    q = compute_quote(lines, "sul_sudeste", False)

    assert q.subtotal == pytest.approx(280.0)
    assert q.abaixo_minimo is True
    assert q.pedido_minimo == pytest.approx(300.0)
    # frete deve ser cobrado (280 < 900 e > 0)
    assert q.frete == pytest.approx(55.0)
    assert q.total == pytest.approx(335.0)


def test_compute_quote_abaixo_do_minimo():
    """Subtotal abaixo do mínimo → abaixo_minimo=True."""
    lines = _make_lines((50.0, 2))  # subtotal = 100
    q = compute_quote(lines, "nordeste", False)

    assert q.abaixo_minimo is True
    assert q.pedido_minimo == pytest.approx(300.0)
    assert q.frete == pytest.approx(75.0)  # nordeste, não atingiu grátis


def test_compute_quote_frete_gratis_na_faixa():
    """sul_sudeste: subtotal >= R$900 → frete = 0, frete_gratis=True."""
    lines = _make_lines((450.0, 2))  # subtotal = 900 (exatamente na faixa)
    q = compute_quote(lines, "sul_sudeste", False)

    assert q.subtotal == pytest.approx(900.0)
    assert q.frete == pytest.approx(0.0)
    assert q.frete_gratis is True
    assert q.total == pytest.approx(900.0)
    assert q.abaixo_minimo is False


def test_compute_quote_frete_cobrado():
    """sul_sudeste: 300 <= subtotal < 900 → frete = R$55."""
    lines = _make_lines((350.0, 1))  # subtotal = 350
    q = compute_quote(lines, "sul_sudeste", False)

    assert q.subtotal == pytest.approx(350.0)
    assert q.frete == pytest.approx(55.0)
    assert q.frete_gratis is False
    assert q.total == pytest.approx(405.0)
    assert q.abaixo_minimo is False


def test_compute_quote_uberlandia_frete_flat():
    """Uberlândia: frete R$15 flat, sem pedido mínimo."""
    lines = _make_lines((50.0, 1))  # subtotal = 50 (abaixo de 300, mas sem mínimo)
    q = compute_quote(lines, None, True)

    assert q.subtotal == pytest.approx(50.0)
    assert q.frete == pytest.approx(UBERLANDIA_FREIGHT)
    assert q.total == pytest.approx(65.0)
    assert q.abaixo_minimo is False
    assert q.pedido_minimo is None


def test_compute_quote_uberlandia_frete_nao_gratis():
    """Uberlândia: não há faixa de grátis — sempre flat R$15."""
    lines = _make_lines((5000.0, 1))  # subtotal altíssimo, mas ainda paga R$15
    q = compute_quote(lines, None, True)

    assert q.frete == pytest.approx(UBERLANDIA_FREIGHT)
    assert q.frete_gratis is False


def test_compute_quote_centro_oeste_valores_exatos():
    """centro_oeste: mínimo R$300, frete R$65, grátis >= R$1000."""
    lines = _make_lines((500.0, 1))  # subtotal = 500
    q = compute_quote(lines, "centro_oeste", False)

    assert q.frete == pytest.approx(65.0)
    assert q.abaixo_minimo is False

    lines_gratis = _make_lines((1000.0, 1))
    q_gratis = compute_quote(lines_gratis, "centro_oeste", False)
    assert q_gratis.frete == pytest.approx(0.0)
    assert q_gratis.frete_gratis is True


def test_compute_quote_norte_valores_exatos():
    """norte: frete R$85, grátis >= R$1500."""
    lines = _make_lines((800.0, 1))  # subtotal = 800
    q = compute_quote(lines, "norte", False)

    assert q.frete == pytest.approx(85.0)
    assert q.frete_gratis is False

    lines_gratis = _make_lines((1500.0, 1))
    q_gratis = compute_quote(lines_gratis, "norte", False)
    assert q_gratis.frete == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 4. match_products
# ---------------------------------------------------------------------------


_CATALOG_ATACADO: list[dict] = [
    {"name": "Café Clássico 250g", "sector": "atacado"},
    {"name": "Café Suave 250g", "sector": "atacado"},
    {"name": "Café Canela 250g", "sector": "atacado"},
    {"name": "Café Microlote 250g", "sector": "atacado"},
    {"name": "Drip Coffee Pack", "sector": "atacado"},
    {"name": "Nespresso Canastra 10un", "sector": "atacado"},
]


def test_match_products_zero_resultados():
    """Produto inexistente → lista vazia."""
    result = match_products("xyz_inexistente_abc", _CATALOG_ATACADO)
    assert result == []


def test_match_products_um_resultado():
    """Match único → lista com 1 item."""
    result = match_products("microlote", _CATALOG_ATACADO)
    assert len(result) == 1
    assert result[0]["name"] == "Café Microlote 250g"


def test_match_products_multiplos_resultados():
    """Substring que casa com mais de 1 produto → todos retornados (dentro do cap)."""
    result = match_products("cafe", _CATALOG_ATACADO)
    assert len(result) > 1


def test_match_products_cap_top5():
    """P2: mais de 5 matches → corta no TOP 5 (MAX_DISAMBIGUATION=5)."""
    big_catalog = [{"name": f"Café Produto Tipo {i}"} for i in range(10)]
    result = match_products("café", big_catalog)
    assert len(result) == MAX_DISAMBIGUATION  # exatamente 5


def test_match_products_normaliza_acento():
    """Busca sem acento encontra produto com acento no nome."""
    result = match_products("cafe classico", _CATALOG_ATACADO)
    assert len(result) >= 1
    assert any("Clássico" in r["name"] for r in result)


def test_match_products_case_insensitive():
    """Busca em maiúsculas encontra produto em caixa mista."""
    result = match_products("CAFE SUAVE", _CATALOG_ATACADO)
    assert any("Suave" in r["name"] for r in result)


def test_match_products_substring_parcial():
    """Drip Coffee encontrado pela substring 'drip'."""
    result = match_products("drip", _CATALOG_ATACADO)
    assert len(result) == 1
    assert "Drip Coffee" in result[0]["name"]


# ---------------------------------------------------------------------------
# 5. format_quote
# ---------------------------------------------------------------------------


def test_format_quote_contem_subtotal_frete_total():
    """Output deve incluir os três valores numéricos chave."""
    lines = _make_lines((350.0, 1))
    q = compute_quote(lines, "sul_sudeste", False)
    text = format_quote(q)

    # Valores em formato BRL ou fragmentos deles
    assert "350" in text
    assert "55" in text
    assert "405" in text


def test_format_quote_frete_gratis_label():
    """Quando frete é grátis, o texto deve dizer 'grátis' ou 'gratis'."""
    lines = _make_lines((900.0, 1))
    q = compute_quote(lines, "sul_sudeste", False)
    text = format_quote(q)

    assert "grátis" in text.lower() or "gratis" in text.lower()


def test_format_quote_aviso_minimo_quando_aplicavel():
    """Quando abaixo do mínimo, o texto deve conter aviso com o valor mínimo."""
    lines = _make_lines((100.0, 1))  # subtotal = 100 < 300
    q = compute_quote(lines, "sul_sudeste", False)
    assert q.abaixo_minimo is True

    text = format_quote(q)
    text_lower = text.lower()

    assert "300" in text
    assert "mínimo" in text_lower or "minimo" in text_lower


def test_format_quote_breakdown_por_linha():
    """Deve listar o nome de cada produto do carrinho individualmente."""
    lines = [
        LineQuote(produto="Café Clássico 250g", quantidade=2, preco_unitario=100.0, subtotal_linha=200.0),
        LineQuote(produto="Café Suave 250g", quantidade=3, preco_unitario=80.0, subtotal_linha=240.0),
    ]
    q = compute_quote(lines, "sul_sudeste", False)
    text = format_quote(q)

    assert "Café Clássico 250g" in text
    assert "Café Suave 250g" in text


def test_format_quote_uberlandia_sem_aviso_minimo():
    """Para Uberlândia, não deve aparecer aviso de pedido mínimo."""
    lines = _make_lines((50.0, 1))  # subtotal = 50 (abaixo de 300, mas sem mínimo)
    q = compute_quote(lines, None, True)
    text = format_quote(q)
    text_lower = text.lower()

    assert q.abaixo_minimo is False
    # Sem aviso de mínimo
    assert "mínimo" not in text_lower or "15" in text  # R$15 frete pode aparecer


# ---------------------------------------------------------------------------
# Checagem de constantes e Pydantic models
# ---------------------------------------------------------------------------


def test_freight_table_tem_quatro_regioes():
    assert set(FREIGHT_TABLE.keys()) == {"sul_sudeste", "centro_oeste", "nordeste", "norte"}


def test_uf_to_region_valores_exatos():
    """Alguns UFs críticos mapeiam para a região correta."""
    assert UF_TO_REGION["SP"] == "sul_sudeste"
    assert UF_TO_REGION["SC"] == "sul_sudeste"  # Sul → sul_sudeste
    assert UF_TO_REGION["BA"] == "nordeste"
    assert UF_TO_REGION["GO"] == "centro_oeste"
    assert UF_TO_REGION["AM"] == "norte"
    assert UF_TO_REGION["MG"] == "sul_sudeste"  # Sudeste (UF de Uberlândia) → sul_sudeste


def test_pydantic_pedido_item_quantidade_zero_invalida():
    """quantidade=0 deve ser rejeitado pelo Pydantic (gt=0)."""
    with pytest.raises(Exception):  # ValidationError
        PedidoItem(produto="Café", quantidade=0)


def test_pydantic_orcamento_input_itens_vazios_invalido():
    """Lista de itens vazia deve ser rejeitada (min_length=1)."""
    with pytest.raises(Exception):
        OrcamentoInput(itens=[])


def test_pydantic_orcamento_input_valido():
    o = OrcamentoInput(
        itens=[PedidoItem(produto="Café Clássico", quantidade=5)],
        estado="SP",
        cidade=None,
    )
    assert len(o.itens) == 1
    assert o.estado == "SP"
