import pytest
from unittest.mock import patch

from app.agent.tools import get_tools_for_stage, PHOTO_CAPTIONS, PRODUTO_PHOTO_MAP, execute_tool


def test_secretaria_tools():
    tools = get_tools_for_stage("secretaria")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "mudar_stage" in names
    assert "encaminhar_humano" in names


def test_atacado_tools():
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "encaminhar_humano" in names
    assert "enviar_fotos" in names


def test_consumo_tools():
    tools = get_tools_for_stage("consumo")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "mudar_stage" in names
    assert "registrar_optout" in names
    assert "encaminhar_humano" not in names


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
async def test_enviar_fotos_nao_reenvia_se_ja_enviado():
    """enviar_fotos não deve enviar se já foi enviado nesta conversa."""
    lead_id = "lead-joana-test"

    # Histórico simulado com a marca de fotos já enviadas — formato exato salvo em produção
    history_com_fotos = [
        {"role": "system", "content": "[enviar_fotos] Fotos de private_label enviadas (4/4)"},
    ]

    with patch("app.agent.tools.get_history", return_value=history_com_fotos), \
         patch("app.agent.tools.get_active_channel") as mock_channel:

        result = await execute_tool(
            "enviar_fotos",
            {"categoria": "private_label"},
            lead_id=lead_id,
            phone="5511999999999",
        )

    assert "ja enviadas" in result.lower() or "nao reenviar" in result.lower(), (
        f"Deveria retornar mensagem de dedup, mas retornou: '{result}'"
    )
    mock_channel.assert_not_called()  # não deve chegar a buscar canal


def test_registrar_pedido_simples_removida_do_schema():
    """registrar_pedido_simples não deve existir no TOOLS_SCHEMA — é dead code."""
    from app.agent.tools import TOOLS_SCHEMA
    names = [t["function"]["name"] for t in TOOLS_SCHEMA]
    assert "registrar_pedido_simples" not in names


def test_mudar_stage_description_contem_gatilhos():
    """description de mudar_stage deve conter os gatilhos por stage."""
    from app.agent.tools import TOOLS_SCHEMA
    schema = next(t for t in TOOLS_SCHEMA if t["function"]["name"] == "mudar_stage")
    desc = schema["function"]["description"]
    assert "atacado" in desc
    assert "private_label" in desc
    assert "exportacao" in desc
    assert "consumo" in desc
    assert "sem avisar" in desc or "silenciosa" in desc


def test_encaminhar_humano_description_contem_casos():
    """description de encaminhar_humano deve cobrir qualificado, rejeição e circuit breaker."""
    from app.agent.tools import TOOLS_SCHEMA
    schema = next(t for t in TOOLS_SCHEMA if t["function"]["name"] == "encaminhar_humano")
    desc = schema["function"]["description"]
    assert "qualificado" in desc
    assert "REJEITOU" in desc
    assert "turnos" in desc
    assert "NAO envie" in desc or "nao envie" in desc.lower()


def test_registrar_optout_presente_em_todos_os_stages():
    """registrar_optout deve estar disponível em todos os stages."""
    for stage in ["secretaria", "atacado", "private_label", "exportacao", "consumo"]:
        tools = get_tools_for_stage(stage)
        names = [t["function"]["name"] for t in tools]
        assert "registrar_optout" in names, f"registrar_optout ausente no stage '{stage}'"


def test_registrar_optout_schema():
    """registrar_optout deve ter schema correto com campo motivo obrigatório."""
    from app.agent.tools import TOOLS_SCHEMA
    schema = next(t for t in TOOLS_SCHEMA if t["function"]["name"] == "registrar_optout")
    fn = schema["function"]
    assert fn["name"] == "registrar_optout"
    assert "motivo" in fn["parameters"]["properties"]
    assert "motivo" in fn["parameters"]["required"]
    desc = fn["description"]
    assert "opt-out" in desc.lower() or "parar" in desc.lower()
    assert "NAO envie" in desc or "nao envie" in desc.lower()


@pytest.mark.asyncio
async def test_registrar_optout_chama_update_lead_ai_enabled_false():
    """registrar_optout deve chamar update_lead com ai_enabled=False e salvar system message."""
    with patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools.save_message") as mock_save, \
         patch("app.agent.tools.apply_optout_side_effects"):
        result = await execute_tool(
            "registrar_optout",
            {"motivo": "clicou parar mensagens"},
            lead_id="lead-optout-1",
            phone="5511999990001",
            conversation_id="conv-optout-1",
        )
    assert result == "Opt-out registrado."
    mock_update.assert_called_once_with("lead-optout-1", ai_enabled=False)
    mock_save.assert_called_once()
    call_args = mock_save.call_args
    assert "registrar_optout" in call_args[0][2]
    assert "clicou parar mensagens" in call_args[0][2]


@pytest.mark.asyncio
async def test_registrar_optout_retorna_erro_se_update_lead_falha(caplog):
    """registrar_optout deve retornar mensagem de erro se update_lead lançar exceção."""
    import logging
    with patch("app.agent.tools.update_lead", side_effect=RuntimeError("db timeout")), \
         patch("app.agent.tools.save_message") as mock_save, \
         patch("app.agent.tools.apply_optout_side_effects"):
        caplog.set_level(logging.ERROR, logger="app.agent.tools")
        result = await execute_tool(
            "registrar_optout",
            {"motivo": "nao quer mais contato"},
            lead_id="lead-optout-2",
            phone="5511999990002",
            conversation_id="conv-optout-2",
        )
    assert "ERRO" in result or "erro" in result.lower()
    assert "db timeout" in result
    mock_save.assert_not_called()
    assert any("registrar_optout" in rec.message and rec.levelname == "ERROR" for rec in caplog.records)


@pytest.mark.asyncio
async def test_registrar_optout_nao_chama_create_deal_nem_human_control():
    """registrar_optout NÃO deve chamar create_deal, não deve setar human_control."""
    with patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools.save_message"), \
         patch("app.agent.tools.create_deal") as mock_create_deal, \
         patch("app.agent.tools.apply_optout_side_effects"):
        await execute_tool(
            "registrar_optout",
            {"motivo": "opt-out"},
            lead_id="lead-optout-3",
            phone="5511999990003",
        )
    mock_create_deal.assert_not_called()
    # update_lead must only receive ai_enabled=False — not human_control or status
    call_kwargs = mock_update.call_args[1]
    assert "human_control" not in call_kwargs
    assert "status" not in call_kwargs
    assert call_kwargs.get("ai_enabled") is False
