"""TDD — Frente C, Task 3 (C-3): match_products por TOKENS + not-found com opções.

Caso real Edgar (02/07 17:14–17:22): o lead pediu "Suave em grãos 500g" e o
match_products antigo — substring LITERAL da consulta inteira no nome — não casava o
nome real do catálogo (a preposição "em" e a ordem das palavras quebravam a
adjacência). A tool devolveu "não encontrado" SEM listar opções, a Valéria improvisou
"o sistema não achou o Suave em grãos de 500g" (produto ERRADO — o item inexistente
era o Microlote 500g, não o Suave), 2 vezes, substituiu item em silêncio no orçamento
e a guarda disparou handoff quando o cliente disse "adicione mais unidades".

Design adjudicado (coordenador, 03/07):
- Match por TOKENS (AND, ordem livre): consulta e nome canonicalizados (sem acento,
  caixa baixa, "500 g"→"500g", espaços colapsados); stopwords de preposição/artigo
  removidas SÓ da consulta (de, em, com, do, da, o, a); produto casa se TODOS os
  tokens da consulta aparecem (substring) no nome.
- EXACT-MATCH-WINS: consulta canonicalizada IGUAL ao nome canonicalizado de um
  produto → retorna só ele, mesmo que os tokens sejam subconjunto de outro nome
  (catálogos com nomes-superset, ex. "Café Suave 500g" vs "Café Suave Premium 500g").
- Comportamento ADJUDICADO para nomes token-superset: consulta parcial "suave 500"
  passa a ser genuinamente ambígua (2 matches → desambiguação). O single-match antigo
  era um CHUTE codificado por sorte de adjacência — o catálogo do prompt já manda
  "CONFIRME com o cliente qual ele quer ANTES de dizer o preço. Nunca chute a
  variação".
- tools.py: retorno de 0 matches passa a LISTAR os disponíveis do setor (ordem
  estável, cap MAX_DISAMBIGUATION) — a Valéria confirma a variação com o cliente em
  tom de vendedora, nunca inventa em tom de sistema.
"""
from unittest.mock import patch

from app.agent.pricing import MAX_DISAMBIGUATION, match_products


# ---------------------------------------------------------------------------
# Catálogo fake do caso Edgar — nomes realistas/plausíveis (inventados p/ o teste):
# o formato "Café <linha> <peso> (<moagem>)" reproduz a estrutura que derrubou a
# substring literal (peso e moagem em posições diferentes das faladas pelo lead).
# ---------------------------------------------------------------------------

_CATALOGO_EDGAR: list[dict] = [
    {
        "sector": "atacado",
        "name": "Café Suave 500g (grãos)",
        "price_formatted": "R$ 52,70",
        "min_lot": "10",
        "description": "Torra média, notas de melaço",
        "image_urls": "",
    },
    {
        "sector": "atacado",
        "name": "Café Suave 250g (moído)",
        "price_formatted": "R$ 28,70",
        "min_lot": "10",
        "description": "Torra média",
        "image_urls": "",
    },
    {
        "sector": "atacado",
        "name": "Café Microlote 250g (grãos)",
        "price_formatted": "R$ 34,70",
        "min_lot": "5",
        "description": "Notas de mel, caramelo e cacau",
        "image_urls": "",
    },
    {
        "sector": "atacado",
        "name": "Café Clássico 500g (moído)",
        "price_formatted": "R$ 49,70",
        "min_lot": "10",
        "description": "Torra média-escura",
        "image_urls": "",
    },
]


# ---------------------------------------------------------------------------
# 1. Caso Edgar — consulta com preposição e ordem livre casa o nome real
# ---------------------------------------------------------------------------


def test_edgar_suave_em_graos_500g_casa_nome_real_do_catalogo():
    """"Suave em grãos 500g" → tokens {suave, graos, 500g} → casa "Café Suave 500g (grãos)".

    Era o RED principal da task: a substring literal antiga devolvia 0 matches aqui.
    """
    result = match_products("Suave em grãos 500g", _CATALOGO_EDGAR)
    assert len(result) == 1
    assert result[0]["name"] == "Café Suave 500g (grãos)"


def test_edgar_peso_com_espaco_normaliza_500_g_para_500g():
    """"suave 500 g" → normalização de peso ("500 g"→"500g") antes da tokenização."""
    result = match_products("suave 500 g", _CATALOGO_EDGAR)
    assert len(result) == 1
    assert result[0]["name"] == "Café Suave 500g (grãos)"


def test_edgar_microlote_500g_nao_existe_zero_matches():
    """"Microlote em grãos 500g" → 0 matches (Microlote só existe em 250g no catálogo)."""
    result = match_products("Microlote em grãos 500g", _CATALOGO_EDGAR)
    assert result == []


def test_mais_de_um_match_continua_desambiguando():
    """"suave" casa as duas variações do Suave → 2 matches (desambiguação preservada)."""
    result = match_products("suave", _CATALOGO_EDGAR)
    assert len(result) == 2
    names = {r["name"] for r in result}
    assert names == {"Café Suave 500g (grãos)", "Café Suave 250g (moído)"}


def test_consulta_vazia_retorna_lista_vazia():
    assert match_products("", _CATALOGO_EDGAR) == []
    assert match_products("   ", _CATALOGO_EDGAR) == []


def test_consulta_so_de_stopwords_retorna_lista_vazia():
    """Consulta que só tem preposições/artigos (tokens todos removidos) → [] como vazia."""
    assert match_products("de em com", _CATALOGO_EDGAR) == []


# ---------------------------------------------------------------------------
# 2. Regras da tokenização — stopwords SÓ na consulta; pesos nos DOIS lados
# ---------------------------------------------------------------------------


def test_stopword_no_nome_do_produto_nao_e_removida_e_nao_atrapalha():
    """Stopwords saem SÓ da consulta; o nome NUNCA é tokenizado/podado (substring pura).

    "Café da Roça 500g" contém a stopword "da" — segue matchável por tokens que
    ignoram o "da" da consulta, e o exact-match compara o nome inteiro (com "da").
    """
    catalogo = [
        {"sector": "atacado", "name": "Café da Roça 500g"},
        {"sector": "atacado", "name": "Café Clássico 500g"},
    ]
    # tokens {cafe, roca, 500g} — "da" removido da CONSULTA, presente no nome
    result = match_products("café da roça 500g", catalogo)
    assert len(result) == 1
    assert result[0]["name"] == "Café da Roça 500g"


def test_peso_com_espaco_no_nome_do_produto_tambem_normaliza():
    """Normalização de peso vale pros DOIS lados: nome com "1 kg" casa consulta "1kg"."""
    catalogo = [
        {"sector": "atacado", "name": "Café Exportação 1 kg"},
        {"sector": "atacado", "name": "Café Exportação 500g"},
    ]
    result = match_products("exportação 1kg", catalogo)
    assert len(result) == 1
    assert result[0]["name"] == "Café Exportação 1 kg"


def test_cap_max_disambiguation_preservado():
    """>5 matches → corta em MAX_DISAMBIGUATION (P2 — nunca 50+ itens pro LLM)."""
    catalogo = [{"sector": "atacado", "name": f"Café Produto {i}"} for i in range(9)]
    result = match_products("café", catalogo)
    assert len(result) == MAX_DISAMBIGUATION


# ---------------------------------------------------------------------------
# 3. Nomes token-superset (comportamento ADJUDICADO) + exact-match-wins
# ---------------------------------------------------------------------------

_CATALOGO_SUPERSET: list[dict] = [
    {"sector": "atacado", "name": "Café Suave 500g", "price_formatted": "R$ 80,00"},
    {"sector": "atacado", "name": "Café Suave Premium 500g", "price_formatted": "R$ 120,00"},
]


def test_superset_consulta_parcial_e_ambigua_2_matches():
    """PINO do comportamento adjudicado: "suave 500" NÃO escolhe sozinha entre
    "Café Suave 500g" e "Café Suave Premium 500g" (tokens de um ⊂ tokens do outro)
    → 2 matches → desambiguação. O single-match antigo era chute por adjacência.
    """
    result = match_products("suave 500", _CATALOGO_SUPERSET)
    assert len(result) == 2
    names = {r["name"] for r in result}
    assert names == {"Café Suave 500g", "Café Suave Premium 500g"}


def test_superset_consulta_exata_vence_1_match():
    """EXACT-MATCH-WINS: consulta igual ao nome canonicalizado → só ele, mesmo sendo
    subconjunto de tokens do nome-superset ("...Premium...")."""
    result = match_products("café suave 500g", _CATALOGO_SUPERSET)
    assert len(result) == 1
    assert result[0]["name"] == "Café Suave 500g"


def test_superset_consulta_exata_tolera_acento_caixa_e_peso_com_espaco():
    """Exact-wins compara a forma CANÔNICA: acento/caixa/peso-com-espaço não quebram."""
    result = match_products("CAFE SUAVE 500 G", _CATALOGO_SUPERSET)
    assert len(result) == 1
    assert result[0]["name"] == "Café Suave 500g"


# ---------------------------------------------------------------------------
# 4. Tool calcular_orcamento — 0 matches lista os DISPONÍVEIS (caso Edgar, parte 2)
# ---------------------------------------------------------------------------


async def _exec_orcamento(args: dict, products: list[dict]) -> str:
    from app.agent.tools import execute_tool
    with patch("app.agent.tools._fetch_active_products", return_value=products):
        return await execute_tool(
            "calcular_orcamento", args,
            lead_id="lead-edgar-c3", phone="5534999990000",
            conversation_id="conv-edgar-c3",
        )


async def test_tool_not_found_lista_disponiveis_do_setor():
    """Microlote 500g não existe → mensagem lista os nomes REAIS disponíveis, pra
    Valéria confirmar a variação com o cliente (em vez de improvisar "o sistema não
    achou..." com produto errado, como no caso real)."""
    args = {"itens": [{"produto": "Microlote em grãos 500g", "quantidade": 4}], "estado": "MG"}
    result = await _exec_orcamento(args, _CATALOGO_EDGAR)

    # Mensagem INTERNA (auditoria 14/07, caso Thiago): reescrita p/ não vazar "não
    # encontrado no catálogo" ao cliente — marca [INTERNO] + instrução de tom.
    assert "[INTERNO" in result and "NÃO REPASSAR" in result
    assert "não existe" in result
    assert "disponíveis" in result.lower()
    for name in (p["name"] for p in _CATALOGO_EDGAR):
        assert name in result, f"nome disponível ausente da mensagem: {name!r}"
    assert "Confirme com o cliente" in result


async def test_tool_not_found_disponiveis_ordem_estavel_e_cap_5():
    """Nomes na ORDEM do catálogo (estável) e no máximo MAX_DISAMBIGUATION (5)."""
    catalogo = [
        {"sector": "atacado", "name": f"Café Linha {i} 250g", "price_formatted": "R$ 30,00"}
        for i in range(7)
    ]
    args = {"itens": [{"produto": "produto inexistente xyz", "quantidade": 1}], "estado": "SP"}
    result = await _exec_orcamento(args, catalogo)

    assert "disponíveis" in result.lower()
    for i in range(5):
        assert f"Café Linha {i} 250g" in result
    for i in (5, 6):
        assert f"Café Linha {i} 250g" not in result, "cap de 5 nomes estourado"
    # ordem estável = ordem do catálogo
    positions = [result.index(f"Café Linha {i} 250g") for i in range(5)]
    assert positions == sorted(positions)


async def test_tool_edgar_pedido_original_agora_resolve_orcamento():
    """Regressão do caso feliz: o pedido REAL do Edgar ("Suave em grãos 500g") agora
    casa e devolve orçamento com valores — não mais "não encontrado"."""
    args = {"itens": [{"produto": "Suave em grãos 500g", "quantidade": 4}], "estado": "MG"}
    result = await _exec_orcamento(args, _CATALOGO_EDGAR)

    assert "não encontrado" not in result
    assert "Café Suave 500g (grãos)" in result
    assert "R$" in result


async def test_tool_ambiguo_continua_pedindo_especificacao():
    """>1 match segue no fluxo de desambiguação existente (nomes listados)."""
    args = {"itens": [{"produto": "suave", "quantidade": 2}], "estado": "MG"}
    result = await _exec_orcamento(args, _CATALOGO_EDGAR)

    assert "especifique" in result.lower() or "qual" in result.lower()
    assert "Café Suave 500g (grãos)" in result
    assert "Café Suave 250g (moído)" in result
