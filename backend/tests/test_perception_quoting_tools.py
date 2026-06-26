"""TDD — Task 3: tools.execute_tool consultar_relacionamento + calcular_orcamento

Cases (spec §6 items 7-9):
  7. execute_tool("calcular_orcamento", ...):
     (a) multi-item cart → correct summed breakdown
     (b) ambiguous item → disambiguation (≤5 names)
     (c) cidade="Uberlândia" sem estado → calcula com frete 15, NÃO pede estado (B2)
     (d) sem estado e sem cidade → subtotal + pede estado
     (e) OrcamentoInput inválido (itens vazio) → string de erro, nunca levanta
     (f) produto não encontrado → string de erro clara
     (g) fail-soft: _fetch_active_products levanta → string segura
  8. consultar_relacionamento → delega para get_relationship_summary(lead_id)
  9. get_tools_for_stage:
     - calcular_orcamento SOMENTE em atacado
     - consultar_relacionamento em TODOS os stages comerciais
 10. TOOLS_SCHEMA bem-formado (tipo, required, itens é array de objetos)

Mocks: _fetch_active_products patchado em app.agent.tools; get_relationship_summary
       patchado em app.agent.tools.
"""
from unittest.mock import patch
import pytest


# ---------------------------------------------------------------------------
# Produtos fake para os testes (setor atacado + um de private_label que deve ser ignorado)
# ---------------------------------------------------------------------------

_FAKE_PRODUCTS = [
    {
        "sector": "atacado",
        "name": "Café Clássico 500g",
        "price_formatted": "R$ 100,00",
        "min_lot": "10",
        "description": "Torra média-escura",
        "image_urls": "",
    },
    {
        "sector": "atacado",
        "name": "Café Suave 500g",
        "price_formatted": "R$ 80,00",
        "min_lot": "10",
        "description": "Torra média",
        "image_urls": "",
    },
    {
        "sector": "atacado",
        "name": "Café Suave Premium 500g",
        "price_formatted": "R$ 120,00",
        "min_lot": "5",
        "description": "Microlote suave",
        "image_urls": "",
    },
    {
        # este deve ser FILTRADO — não é atacado
        "sector": "private_label",
        "name": "Produto PL Exclusivo",
        "price_formatted": "R$ 200,00",
        "min_lot": "1",
        "description": "",
        "image_urls": "",
    },
]


# ---------------------------------------------------------------------------
# Helper: chama execute_tool com os defaults de teste
# ---------------------------------------------------------------------------

async def _exec(tool_name, args, lead_id="lead-test", phone="5511999999999", conv="conv-test"):
    from app.agent.tools import execute_tool
    return await execute_tool(tool_name, args, lead_id=lead_id, phone=phone, conversation_id=conv)


# ===========================================================================
# 8. consultar_relacionamento
# ===========================================================================

async def test_consultar_relacionamento_delegates_to_service():
    """consultar_relacionamento deve chamar get_relationship_summary(lead_id) e retornar o resultado."""
    with patch(
        "app.agent.tools.get_relationship_summary",
        return_value="CLIENTE ATIVO. Última compra: Café 1kg (R$ 150,00) em 15/01/2026. Trate como reabastecimento/upsell — NÃO requalifique.",
    ) as mock_fn:
        result = await _exec("consultar_relacionamento", {}, lead_id="lead-abc")

    mock_fn.assert_called_once_with("lead-abc")
    assert "CLIENTE ATIVO" in result
    assert "reabastecimento" in result


async def test_consultar_relacionamento_lead_novo():
    """Quando o lead não tem histórico, devolve mensagem de lead novo."""
    with patch(
        "app.agent.tools.get_relationship_summary",
        return_value="SEM histórico de compra — tratar como lead novo.",
    ):
        result = await _exec("consultar_relacionamento", {}, lead_id="lead-frio")

    assert "lead novo" in result or "SEM histórico" in result


# ===========================================================================
# 7a. calcular_orcamento — carrinho multi-item, breakdown somado correto
# ===========================================================================

async def test_multi_item_cart_correct_breakdown():
    """Carrinho com dois produtos → subtotal = soma, frete correto, total certo (estado SP)."""
    # "classico" → único match "Café Clássico 500g" (R$100)
    # "suave 500" → único match "Café Suave 500g" (R$80)  [não bate em "Suave Premium"]
    # SP = sul_sudeste, pedido_minimo=300, frete=55, gratis_acima=900
    # subtotal = 2*100 + 3*80 = 200 + 240 = 440 → frete=55, total=495
    args = {
        "itens": [
            {"produto": "classico", "quantidade": 2},
            {"produto": "suave 500", "quantidade": 3},
        ],
        "estado": "SP",
    }
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    # breakdown item a item
    assert "Clássico" in result or "classico" in result.lower()
    assert "Suave" in result
    # subtotal 440 deve aparecer
    assert "440" in result
    # frete sul_sudeste = 55
    assert "55" in result
    # total 495
    assert "495" in result


async def test_single_item_cart_with_region():
    """Carrinho de 1 item com estado → breakdown correto."""
    args = {
        "itens": [{"produto": "classico", "quantidade": 5}],
        "estado": "BA",  # nordeste → frete 75, pedido_minimo 300
    }
    # 5 * 100 = 500, 500 >= 300 mínimo, 500 < 1200 grátis → frete = 75, total = 575
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    assert "500" in result
    assert "75" in result   # frete nordeste
    assert "575" in result  # total


# ===========================================================================
# 7b. calcular_orcamento — item ambíguo → desambiguação ≤5 nomes
# ===========================================================================

async def test_ambiguous_item_returns_disambiguation():
    """'suave' bate em Café Suave 500g E Café Suave Premium 500g → pede especificação."""
    args = {"itens": [{"produto": "suave", "quantidade": 1}]}
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    # Deve pedir especificação
    assert "especifique" in result.lower() or "qual" in result.lower()
    # Ambos os nomes devem aparecer na sugestão
    assert "Suave 500g" in result
    assert "Suave Premium" in result


async def test_disambiguation_at_most_5_names():
    """Desambiguação retorna no máximo 5 nomes (P2 — MAX_DISAMBIGUATION)."""
    # Criar 7 produtos com o mesmo prefixo "cafe"
    many_products = [
        {
            "sector": "atacado",
            "name": f"Café Produto {i}",
            "price_formatted": "R$ 50,00",
            "min_lot": "5",
            "description": "",
            "image_urls": "",
        }
        for i in range(7)
    ]
    args = {"itens": [{"produto": "cafe", "quantidade": 1}]}
    with patch("app.agent.tools._fetch_active_products", return_value=many_products):
        result = await _exec("calcular_orcamento", args)

    # Deve ser desambiguação (>1 match)
    assert "especifique" in result.lower() or "qual" in result.lower()
    # Nunca deve devolver todos os 7 — máximo 5 (P2)
    count = sum(1 for i in range(7) if f"Café Produto {i}" in result)
    assert count <= 5, f"Esperava ≤5 nomes, encontrou {count}"


# ===========================================================================
# 7c. calcular_orcamento — Uberlândia sem estado → calcula (frete 15), NÃO pede estado (B2)
# ===========================================================================

async def test_uberlandia_without_estado_computes_flat_freight():
    """cidade='Uberlândia' sem estado → calcula com frete flat R$15, NÃO pede estado."""
    args = {
        "itens": [{"produto": "classico", "quantidade": 2}],
        "cidade": "Uberlândia",
        # sem 'estado'
    }
    # subtotal = 2 * 100 = 200, frete_uberlandia = 15, total = 215
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    # Deve conter frete de 15
    assert "15" in result
    # Deve conter o total (200 + 15 = 215)
    assert "215" in result
    # NÃO deve pedir estado
    assert "estado" not in result.lower()


async def test_uberlandia_spelling_variant_no_accent():
    """'uberlandia' sem acento também ativa o override de Uberlândia (B2)."""
    args = {
        "itens": [{"produto": "classico", "quantidade": 1}],
        "cidade": "uberlandia",
    }
    # subtotal = 100, frete = 15, total = 115
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    assert "15" in result
    assert "115" in result
    assert "estado" not in result.lower()


# ===========================================================================
# 7d. calcular_orcamento — sem estado e sem cidade → subtotal + pede estado
# ===========================================================================

async def test_no_estado_no_cidade_returns_subtotal_and_asks_estado():
    """Sem estado e sem cidade → retorna subtotal dos produtos + pede o estado."""
    args = {
        "itens": [{"produto": "classico", "quantidade": 2}],
        # sem 'estado', sem 'cidade'
    }
    # subtotal = 2 * 100 = 200
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    # Deve conter o subtotal
    assert "200" in result
    # Deve pedir o estado
    assert "estado" in result.lower()
    # NÃO deve ter frete inventado (não deve aparecer "Frete: R$ 55" ou similar)
    # Nota: pode mencionar frete em frases de explicação, mas não deve ter um valor calculado
    assert "Subtotal" in result or "subtotal" in result


# ===========================================================================
# 7e. calcular_orcamento — OrcamentoInput inválido → string de erro, nunca levanta
# ===========================================================================

async def test_empty_itens_returns_error_string():
    """itens=[] viola min_length=1 → Pydantic ValidationError → string de erro (não exception)."""
    args = {"itens": []}
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    assert isinstance(result, str)
    assert len(result) > 0
    # Deve indicar problema com a entrada
    assert any(
        kw in result.lower()
        for kw in ("item", "pedido", "erro", "inválido", "não consegui", "verifique")
    )


async def test_zero_quantidade_returns_error_string():
    """quantidade=0 viola Field(gt=0) → Pydantic ValidationError → string de erro."""
    args = {"itens": [{"produto": "classico", "quantidade": 0}]}
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    assert isinstance(result, str)
    assert len(result) > 0


# ===========================================================================
# 7f. calcular_orcamento — produto não encontrado → string de erro clara
# ===========================================================================

async def test_product_not_found_returns_clear_error():
    """Produto inexistente no catálogo → string informando que não foi encontrado."""
    args = {
        "itens": [{"produto": "produto inexistente xyz", "quantidade": 1}],
        "estado": "SP",
    }
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        result = await _exec("calcular_orcamento", args)

    assert "não encontrado" in result.lower() or "confirme o nome" in result.lower()
    assert "produto inexistente xyz" in result.lower() or "produto" in result.lower()


# ===========================================================================
# 7g. calcular_orcamento — fail-soft: _fetch_active_products levanta → string segura
# ===========================================================================

async def test_fail_soft_on_fetch_products_error():
    """Se a busca de produtos falhar, retorna string segura sem levantar exceção."""
    args = {
        "itens": [{"produto": "classico", "quantidade": 1}],
        "estado": "SP",
    }
    with patch("app.agent.tools._fetch_active_products", side_effect=RuntimeError("db is down")):
        result = await _exec("calcular_orcamento", args)

    assert isinstance(result, str)
    assert len(result) > 0
    # Deve instruir a encaminhar para o João
    assert "joao" in result.lower() or "encaminhe" in result.lower() or "problema" in result.lower()


# ===========================================================================
# Fix #1 — null/empty price_formatted → safe precise message, no exception
# ===========================================================================

async def test_null_price_formatted_returns_precise_safe_string():
    """Matched product with price_formatted=None → safe string (no exception, precise message).

    Without the guard, parse_brl(None) raises AttributeError which escapes the inner
    (ValueError, KeyError, TypeError) handler and falls to the outer generic handler
    ('Ocorreu um problema'). With the guard we return a precise 'não consegui ler o preço'
    message that names the product and routes to João.
    """
    null_price_products = [
        {
            "sector": "atacado",
            "name": "Café Sem Preço",
            "price_formatted": None,
            "min_lot": "10",
            "description": "",
            "image_urls": "",
        }
    ]
    args = {"itens": [{"produto": "cafe sem preco", "quantidade": 1}], "estado": "SP"}
    with patch("app.agent.tools._fetch_active_products", return_value=null_price_products):
        result = await _exec("calcular_orcamento", args)

    assert isinstance(result, str)
    assert len(result) > 0
    # Precise handler fires (not the outer "Ocorreu um problema" fallback)
    assert "não consegui" in result.lower(), f"Expected precise message, got: {result!r}"
    assert "ocorreu um problema" not in result.lower()


# ===========================================================================
# Fix #7 — consultar_relacionamento fail-soft: get_relationship_summary raises
# ===========================================================================

async def test_consultar_relacionamento_fail_soft_on_service_exception():
    """If get_relationship_summary raises, execute_tool returns safe fallback, no exception."""
    with patch(
        "app.agent.tools.get_relationship_summary",
        side_effect=RuntimeError("db is down"),
    ):
        result = await _exec("consultar_relacionamento", {}, lead_id="lead-err")

    assert isinstance(result, str)
    assert len(result) > 0
    # Should contain the safe fallback (not propagate the exception)
    assert "possível" in result.lower() or "relacionamento" in result.lower()


# ===========================================================================
# 9. get_tools_for_stage — calcular_orcamento somente em atacado
# ===========================================================================

def test_calcular_orcamento_in_atacado_and_private_label():
    """calcular_orcamento nos stages com cálculo de pedido (atacado e private_label).

    Eixo 4 (harmonização): private_label passou a rotear cálculo pela tool em vez de
    multiplicar na mão, alinhando com a regra de preço do base.py."""
    from app.agent.tools import get_tools_for_stage

    for stage in ("atacado", "private_label"):
        names = [t["function"]["name"] for t in get_tools_for_stage(stage)]
        assert "calcular_orcamento" in names, f"calcular_orcamento ausente no stage '{stage}'"

    for stage in ("secretaria", "exportacao", "consumo"):
        names = [t["function"]["name"] for t in get_tools_for_stage(stage)]
        assert "calcular_orcamento" not in names, (
            f"calcular_orcamento não deve estar em stage '{stage}'"
        )


# ===========================================================================
# 9. get_tools_for_stage — consultar_relacionamento em todos os stages comerciais
# ===========================================================================

def test_consultar_relacionamento_in_all_commercial_stages():
    """consultar_relacionamento deve estar disponível em TODOS os stages comerciais."""
    from app.agent.tools import get_tools_for_stage

    commercial_stages = ("secretaria", "atacado", "private_label", "exportacao", "consumo")
    for stage in commercial_stages:
        names = [t["function"]["name"] for t in get_tools_for_stage(stage)]
        assert "consultar_relacionamento" in names, (
            f"consultar_relacionamento deveria estar em stage '{stage}' mas não está"
        )


# ===========================================================================
# 10. TOOLS_SCHEMA — entradas bem-formadas
# ===========================================================================

def test_consultar_relacionamento_schema_well_formed():
    """consultar_relacionamento deve estar no TOOLS_SCHEMA sem parâmetros obrigatórios."""
    from app.agent.tools import TOOLS_SCHEMA

    schema = next(
        (t for t in TOOLS_SCHEMA if t["function"]["name"] == "consultar_relacionamento"),
        None,
    )
    assert schema is not None, "consultar_relacionamento não encontrado no TOOLS_SCHEMA"
    assert schema["type"] == "function"
    params = schema["function"]["parameters"]
    assert params["type"] == "object"
    # Sem parâmetros obrigatórios — o lead_id é injetado pelo runtime
    assert params.get("required", []) == []
    # Descrição forte (menciona relacionamento / cliente / percepção)
    desc = schema["function"]["description"]
    assert len(desc) > 20


def test_calcular_orcamento_schema_well_formed():
    """calcular_orcamento deve estar no TOOLS_SCHEMA com itens como array de objetos."""
    from app.agent.tools import TOOLS_SCHEMA

    schema = next(
        (t for t in TOOLS_SCHEMA if t["function"]["name"] == "calcular_orcamento"),
        None,
    )
    assert schema is not None, "calcular_orcamento não encontrado no TOOLS_SCHEMA"
    assert schema["type"] == "function"
    params = schema["function"]["parameters"]
    assert params["type"] == "object"

    # itens é required
    assert "itens" in params.get("required", [])

    # itens é um array de objetos com produto e quantidade
    itens_prop = params["properties"]["itens"]
    assert itens_prop["type"] == "array"
    items_schema = itens_prop["items"]
    assert items_schema["type"] == "object"
    assert "produto" in items_schema["properties"]
    assert items_schema["properties"]["produto"]["type"] == "string"
    assert "quantidade" in items_schema["properties"]
    assert items_schema["properties"]["quantidade"]["type"] == "integer"

    # estado e cidade são opcionais (não em required)
    required = params.get("required", [])
    assert "estado" not in required
    assert "cidade" not in required

    # Descrição forte (menciona obrigatório / proibido / cabeça / preço)
    desc = schema["function"]["description"].lower()
    assert len(desc) > 50
    # Deve mencionar que é obrigatório para preços
    assert "obrigatório" in desc or "obrigatorio" in desc or "proibido" in desc


def test_tools_schema_has_both_new_entries():
    """Ambas as novas tools devem existir no TOOLS_SCHEMA."""
    from app.agent.tools import TOOLS_SCHEMA
    names = [t["function"]["name"] for t in TOOLS_SCHEMA]
    assert "consultar_relacionamento" in names
    assert "calcular_orcamento" in names
