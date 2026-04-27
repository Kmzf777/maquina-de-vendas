import pytest
from unittest.mock import patch

from app.agent.tools import get_tools_for_stage, PHOTO_CAPTIONS, PRODUTO_PHOTO_MAP, execute_tool


def test_secretaria_tools():
    tools = get_tools_for_stage("secretaria")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "mudar_stage" in names
    assert "encaminhar_humano" not in names


def test_atacado_tools():
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "encaminhar_humano" in names
    assert "enviar_fotos" in names


def test_consumo_tools():
    tools = get_tools_for_stage("consumo")
    names = [t["function"]["name"] for t in tools]
    assert names == ["salvar_nome"]


def test_photo_captions_exist_for_atacado():
    assert "atacado" in PHOTO_CAPTIONS
    captions = PHOTO_CAPTIONS["atacado"]
    assert len(captions) == 5
    assert "foto_1" in captions
    assert "Classico" in captions["foto_1"]


def test_photo_captions_exist_for_private_label():
    assert "private_label" in PHOTO_CAPTIONS
    captions = PHOTO_CAPTIONS["private_label"]
    assert len(captions) == 4
    assert "foto_1" in captions


def test_produto_photo_map_has_classico():
    assert "atacado" in PRODUTO_PHOTO_MAP
    assert "classico" in PRODUTO_PHOTO_MAP["atacado"]
    entry = PRODUTO_PHOTO_MAP["atacado"]["classico"]
    assert "file" in entry
    assert "caption" in entry


def test_atacado_tools_include_enviar_foto_produto():
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "enviar_foto_produto" in names


def test_private_label_tools_include_enviar_foto_produto():
    tools = get_tools_for_stage("private_label")
    names = [t["function"]["name"] for t in tools]
    assert "enviar_foto_produto" in names


def test_secretaria_tools_exclude_enviar_foto_produto():
    tools = get_tools_for_stage("secretaria")
    names = [t["function"]["name"] for t in tools]
    assert "enviar_foto_produto" not in names


@pytest.mark.asyncio
async def test_encaminhar_humano_logs_when_update_lead_fails(caplog):
    """If update_lead raises, tool must log an ERROR and still return a non-crashing string."""
    import logging
    from app.agent.tools import execute_tool

    with patch("app.agent.tools.update_lead", side_effect=RuntimeError("db dead")), \
         patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.create_deal") as mock_create_deal, \
         patch("app.agent.tools.get_lead", return_value={"id": "lead-x", "stage": "atacado"}):
        caplog.set_level(logging.ERROR, logger="app.agent.tools")
        out = await execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "pronto pra fechar"},
            lead_id="lead-x",
            phone="5511999990000",
            conversation_id="conv-x",
        )
    assert "CRITICAL" in out or "erro" in out.lower()
    assert any("encaminhar_humano" in rec.message and rec.levelname == "ERROR" for rec in caplog.records)
    mock_create_deal.assert_not_called()


@pytest.mark.asyncio
async def test_registrar_pedido_simples_cria_deal(monkeypatch):
    calls = []
    def fake_create_deal(lead_id, title, **kwargs):
        calls.append({"lead_id": lead_id, "title": title, **kwargs})
        return {"id": "deal-fake"}
    monkeypatch.setattr("app.agent.tools.create_deal", fake_create_deal)

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "registrar_pedido_simples",
            {
                "categoria": "atacado",
                "produto": "classico",
                "volume_kg": 10,
                "observacoes": "lead pediu entrega urgente",
            },
            lead_id="lead-test-id",
            phone="+5500000000",
            conversation_id="conv-test-id",
        )
    assert len(calls) == 1
    assert "atacado" in calls[0]["title"].lower() or "pedido" in calls[0]["title"].lower()
    assert "registrado" in result.lower() or "ok" in result.lower()


def test_registrar_pedido_simples_nao_disponivel_em_atacado():
    """registrar_pedido_simples não deve estar disponível no stage atacado."""
    from app.agent.tools import get_tools_for_stage
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "registrar_pedido_simples" not in names, (
        "registrar_pedido_simples foi encontrado nas tools do stage atacado. "
        "A Valéria não deve registrar pedidos — só encaminhar_humano."
    )


def test_registrar_pedido_simples_nao_disponivel_em_private_label():
    """registrar_pedido_simples não deve estar disponível no stage private_label."""
    from app.agent.tools import get_tools_for_stage
    tools = get_tools_for_stage("private_label")
    names = [t["function"]["name"] for t in tools]
    assert "registrar_pedido_simples" not in names, (
        "registrar_pedido_simples foi encontrado nas tools do stage private_label. "
        "A Valéria não deve registrar pedidos — só encaminhar_humano."
    )
