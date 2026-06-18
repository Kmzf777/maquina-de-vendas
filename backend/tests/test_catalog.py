"""Testes do serviço de catálogo (app.agent.catalog) e da injeção no prompt."""

from unittest.mock import MagicMock, patch

import pytest

from app.agent import catalog


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    catalog.clear_cache()
    yield
    catalog.clear_cache()


def _mock_supabase(rows):
    """Monta um cliente Supabase fake cujo .execute().data == rows."""
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value
    chain.execute.return_value = MagicMock(data=rows)
    return sb


def test_normalize_mapeia_variacoes_de_setor():
    assert catalog._normalize("Private Label") == "private_label"
    assert catalog._normalize("private_label") == "private_label"
    assert catalog._normalize("Exportação") == "exportacao"
    assert catalog._normalize("  Atacado  ") == "atacado"


def test_get_products_by_funnel_formata_markdown():
    rows = [
        {
            "sector": "Private Label",
            "name": "Café Canastra 250g",
            "price_formatted": "R$ 26,70",
            "min_lot": "100 un",
            "description": "Inclui silk com logo",
            "image_urls": "https://x/a.jpg ; https://x/b.jpg",
        },
        # Setor diferente — não deve aparecer no funil private_label
        {
            "sector": "Atacado",
            "name": "Fardo Atacado",
            "price_formatted": "R$ 999,00",
            "min_lot": "1 fardo",
            "description": "",
            "image_urls": "",
        },
    ]
    with patch("app.agent.catalog.get_supabase", return_value=_mock_supabase(rows)):
        md = catalog.get_products_by_funnel("private_label")

    assert "Café Canastra 250g" in md
    assert "R$ 26,70" in md
    assert "100 un" in md
    assert "Inclui silk com logo" in md
    assert "https://x/a.jpg" in md and "https://x/b.jpg" in md
    # Produto de outro setor não vaza para o funil errado
    assert "Fardo Atacado" not in md


def test_get_products_by_funnel_setor_casa_normalizado():
    """sector 'Atacado' (CSV de ops) casa com a stage 'atacado'."""
    rows = [{"sector": "Atacado", "name": "Produto X", "price_formatted": "R$ 10"}]
    with patch("app.agent.catalog.get_supabase", return_value=_mock_supabase(rows)):
        md = catalog.get_products_by_funnel("atacado")
    assert "Produto X" in md


def test_atacado_outbound_usa_setor_proprio():
    """Atacado no perfil outbound busca o setor 'Atacado Outbound' (preço agressivo)."""
    rows = [
        {"sector": "Atacado", "name": "Clássico 250g", "price_formatted": "R$ 28,70"},
        {"sector": "Atacado Outbound", "name": "Clássico 250g", "price_formatted": "R$ 27,70"},
    ]
    with patch("app.agent.catalog.get_supabase", return_value=_mock_supabase(rows)):
        inbound = catalog.get_products_by_funnel("atacado")
        outbound = catalog.get_products_by_funnel("atacado", prompt_key="valeria_outbound")

    assert "R$ 28,70" in inbound and "R$ 27,70" not in inbound
    assert "R$ 27,70" in outbound and "R$ 28,70" not in outbound


def test_private_label_outbound_usa_mesmo_setor():
    """Private label não tem tabela outbound separada — usa o setor 'private_label'."""
    rows = [{"sector": "Private Label", "name": "PL 250g", "price_formatted": "R$ 26,70"}]
    with patch("app.agent.catalog.get_supabase", return_value=_mock_supabase(rows)):
        md = catalog.get_products_by_funnel("private_label", prompt_key="valeria_outbound")
    assert "PL 250g" in md


def test_get_products_by_funnel_secretaria_sem_catalogo():
    """Stage de entrada não tem catálogo — retorna "" sem tocar no banco."""
    with patch("app.agent.catalog.get_supabase") as mock_sb:
        assert catalog.get_products_by_funnel("secretaria") == ""
        mock_sb.assert_not_called()


def test_get_products_by_funnel_fail_open():
    """Erro de banco nunca propaga — retorna ""."""
    with patch("app.agent.catalog.get_supabase", side_effect=RuntimeError("db down")):
        assert catalog.get_products_by_funnel("atacado") == ""


def test_get_products_by_funnel_vazio_quando_sem_produtos():
    with patch("app.agent.catalog.get_supabase", return_value=_mock_supabase([])):
        assert catalog.get_products_by_funnel("consumo") == ""


# ---------------------------------------------------------------------------
# Injeção no system prompt
# ---------------------------------------------------------------------------

def test_build_system_prompt_injeta_catalogo_e_anti_alucinacao():
    from app.agent.orchestrator import build_system_prompt

    lead = {"name": "Maria", "company": None}
    prompt = build_system_prompt(
        lead, "private_label", catalog_text="- **Café Canastra 250g**\n  - Preço: R$ 26,70"
    )

    # O bloco injetado é identificado pela TAG DE FECHAMENTO (o prompt de estágio
    # apenas referencia <catalogo_de_produtos> inline, sem fechá-la).
    assert "</catalogo_de_produtos>" in prompt
    assert "Café Canastra 250g" in prompt
    assert "NUNCA invente preços" in prompt
    # FINAL_INSTRUCTION deve permanecer a ÚLTIMA tag (regra XML do Gemini)
    assert prompt.rstrip().endswith("</final_instruction>")
    # bloco do catálogo vem ANTES do final_instruction
    assert prompt.index("</catalogo_de_produtos>") < prompt.index("<final_instruction>")


def test_build_system_prompt_sem_catalogo_nao_injeta_bloco():
    from app.agent.orchestrator import build_system_prompt

    lead = {"name": "Maria", "company": None}
    prompt = build_system_prompt(lead, "private_label", catalog_text="")
    # Sem catálogo, o bloco (tag de fechamento) não é injetado — embora o prompt de
    # estágio ainda referencie <catalogo_de_produtos> inline.
    assert "</catalogo_de_produtos>" not in prompt
    assert prompt.rstrip().endswith("</final_instruction>")
