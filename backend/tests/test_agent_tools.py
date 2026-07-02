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
async def test_enviar_fotos_nao_reenfileira_quando_ja_enviado():
    """enviar_fotos ABORTA reenvio quando marca [enviar_fotos] já existe no histórico.

    Contrato atualizado: o dedup-block foi reintroduzido em enviar_fotos
    (issue: "photo batches sent twice"). Adota o padrão de early-return do
    enviar_foto_produto para eliminar duplicatas.
    """
    from app.agent.tools import _deferred_media

    lead_id = "lead-joana-test"
    conversation_id = "conv-joana-test"
    _deferred_media.pop(conversation_id, None)

    # Histórico simulado com a marca de fotos já enviadas — formato exato salvo em produção
    history_com_fotos = [
        {"role": "system", "content": "[enviar_fotos] Fotos de private_label enviadas (4/4)"},
    ]

    with patch("app.agent.tools.get_history", return_value=history_com_fotos):

        result = await execute_tool(
            "enviar_fotos",
            {"categoria": "private_label"},
            lead_id=lead_id,
            phone="5511999999999",
            conversation_id=conversation_id,
        )

    # Aborta: não enfileira, não grava nova marca, retorna string de no-op.
    assert "ja" in result.lower() or "nao reenviar" in result.lower(), (
        f"Deveria abortar, mas retornou: '{result}'"
    )
    queued = _deferred_media.get(conversation_id, [])
    assert queued in (None, []), f"Esperava fila vazia, mas havia {len(queued) if queued else 0} fotos"
    _deferred_media.pop(conversation_id, None)


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
    """registrar_optout deve chamar update_lead com ai_enabled=False e opt_out=True, e salvar system message."""
    with patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools.save_message") as mock_save, \
         patch("app.agent.tools.append_lead_observation") as mock_obs, \
         patch("app.agent.tools.apply_optout_side_effects"):
        result = await execute_tool(
            "registrar_optout",
            {"motivo": "clicou parar mensagens"},
            lead_id="lead-optout-1",
            phone="5511999990001",
            conversation_id="conv-optout-1",
        )
    assert result == "Opt-out registrado."
    mock_update.assert_called_once_with("lead-optout-1", ai_enabled=False, opt_out=True)
    mock_save.assert_called_once()
    call_args = mock_save.call_args
    assert "registrar_optout" in call_args[0][2]
    assert "clicou parar mensagens" in call_args[0][2]
    # Hard opt-out tambem anexa observacao com o prefixo definitivo.
    mock_obs.assert_called_once()
    obs_text = mock_obs.call_args[0][1]
    assert "OPT-OUT DEFINITIVO" in obs_text
    assert "clicou parar mensagens" in obs_text


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
         patch("app.agent.tools.append_lead_observation"), \
         patch("app.agent.tools.create_deal") as mock_create_deal, \
         patch("app.agent.tools.apply_optout_side_effects"):
        await execute_tool(
            "registrar_optout",
            {"motivo": "opt-out"},
            lead_id="lead-optout-3",
            phone="5511999990003",
        )
    mock_create_deal.assert_not_called()
    # update_lead must NOT set human_control/status; only ai_enabled=False + opt_out=True
    call_kwargs = mock_update.call_args[1]
    assert "human_control" not in call_kwargs
    assert "status" not in call_kwargs
    assert call_kwargs.get("ai_enabled") is False
    assert call_kwargs.get("opt_out") is True


def test_registrar_sem_interesse_presente_nos_stages():
    """registrar_sem_interesse_atual disponível nos stages de prospecção. EXCETO consumo:
    varejo B2C não é 'lead perdido', então consumo nunca auto-descarta (auditoria 5551991295543)."""
    for stage in ["secretaria", "atacado", "private_label", "exportacao"]:
        tools = get_tools_for_stage(stage)
        names = [t["function"]["name"] for t in tools]
        assert "registrar_sem_interesse_atual" in names, f"ausente no stage '{stage}'"
    # consumo NÃO tem a ferramenta de descarte
    consumo_names = [t["function"]["name"] for t in get_tools_for_stage("consumo")]
    assert "registrar_sem_interesse_atual" not in consumo_names


def test_registrar_sem_interesse_schema():
    """Schema do soft rejection: motivo obrigatório e descrição que o distingue do opt-out."""
    from app.agent.tools import TOOLS_SCHEMA
    schema = next(t for t in TOOLS_SCHEMA if t["function"]["name"] == "registrar_sem_interesse_atual")
    fn = schema["function"]
    assert "motivo" in fn["parameters"]["properties"]
    assert "motivo" in fn["parameters"]["required"]
    desc = fn["description"]
    assert "SOFT REJECTION" in desc
    assert "registrar_optout" in desc  # aponta o caminho do hard opt-out
    assert "opt_out continua FALSE" in desc or "opt_out continua false" in desc.lower()


@pytest.mark.asyncio
async def test_registrar_sem_interesse_atual_marca_perdido_sem_optout():
    """Soft rejection: stage=perdido, ai_enabled=False, human_control=True, opt_out=False; move deal e anexa observação."""
    with patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools.move_lead_deals_to_perdido") as mock_perdido, \
         patch("app.agent.tools.cancel_followups_by_phone") as mock_cancel, \
         patch("app.agent.tools.append_lead_observation") as mock_obs, \
         patch("app.agent.tools.save_message") as mock_save:
        result = await execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": "ja fechou com outro fornecedor a R$18/kg; ~30kg/mes"},
            lead_id="lead-soft-1",
            phone="5511999990010",
            conversation_id="conv-soft-1",
        )
    assert result == "Lead marcado como sem interesse atual."
    call_kwargs = mock_update.call_args[1]
    assert call_kwargs.get("stage") == "perdido"
    assert call_kwargs.get("ai_enabled") is False
    assert call_kwargs.get("human_control") is True
    assert call_kwargs.get("opt_out") is False  # invariante: soft NUNCA dá opt-out
    mock_perdido.assert_called_once()
    mock_cancel.assert_called_once()
    obs_text = mock_obs.call_args[0][1]
    assert "SEM INTERESSE ATUAL" in obs_text
    assert "fechou com outro fornecedor" in obs_text
    assert "registrar_sem_interesse_atual" in mock_save.call_args[0][2]


@pytest.mark.asyncio
async def test_registrar_sem_interesse_atual_erro_no_update_retorna_erro():
    """Se update_lead falhar, retorna erro e NÃO mexe em deals/follow-ups."""
    with patch("app.agent.tools.update_lead", side_effect=RuntimeError("db down")), \
         patch("app.agent.tools.move_lead_deals_to_perdido") as mock_perdido, \
         patch("app.agent.tools.cancel_followups_by_phone") as mock_cancel, \
         patch("app.agent.tools.append_lead_observation") as mock_obs, \
         patch("app.agent.tools.save_message") as mock_save:
        result = await execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": "sem grana agora"},
            lead_id="lead-soft-2",
            phone="5511999990011",
        )
    assert "ERRO" in result and "db down" in result
    mock_perdido.assert_not_called()
    mock_cancel.assert_not_called()
    mock_obs.assert_not_called()
    mock_save.assert_not_called()
