"""Gatilho deal_stage_stagnation: card parado na coluna do Kanban."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.automation.triggers import check_polling_triggers

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)

TRIGGER_NODE = {
    "campaign_id": "camp-e2",
    "next_node_id": "node-1",
    "channel_id": "ch-joao",
    "audience": "humano",
    "config": {
        "trigger_type": "deal_stage_stagnation",
        "stage_id": "stage-ja-chamado",
        "pipeline_id": "pipe-joao",
        "silence_days": 15,
        "stage_days": 0,
        "last_speaker": "qualquer",
    },
}

LINHA = {
    "lead_id": "lead1",
    "deal_id": "deal1",
    "stage_id": "stage-ja-chamado",
    "last_speaker": "nos",
    "last_message_at": "2026-08-01T12:00:00+00:00",
}


def _patches(rpc_rows, enrolled=False, disabled=False, blacklisted=False):
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rpc_rows
    return (
        patch("app.automation.triggers.get_supabase", return_value=sb),
        patch("app.automation.triggers.get_campaigns_with_trigger_type",
              side_effect=lambda t: [TRIGGER_NODE] if t == "deal_stage_stagnation" else []),
        patch("app.automation.triggers.is_already_enrolled", return_value=enrolled),
        patch("app.automation.triggers._engine._conversation_followup_disabled", return_value=disabled),
        patch("app.automation.triggers.is_lead_blacklisted", return_value=blacklisted),
    ), sb


@pytest.mark.asyncio
async def test_enrolla_com_deal_id_e_guarda():
    ps, sb = _patches([LINHA])
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_called_once()
    kwargs = mock_enroll.call_args.kwargs
    assert kwargs["deal_id"] == "deal1"
    assert kwargs["metadata"]["guard"] == {
        "deal_id": "deal1", "stage_id": "stage-ja-chamado", "stage_key": None,
    }


@pytest.mark.asyncio
async def test_passa_os_parametros_certos_para_a_rpc():
    ps, sb = _patches([])
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment"):
        await check_polling_triggers(NOW)
    nome, args = sb.rpc.call_args[0]
    assert nome == "get_deals_stage_stagnant"
    assert args["p_stage_id"] == "stage-ja-chamado"
    assert args["p_pipeline_id"] == "pipe-joao"
    assert args["p_channel_id"] == "ch-joao"
    assert args["p_silence_days"] == 15
    assert args["p_stage_days"] == 0
    assert args["p_last_speaker"] == "qualquer"
    assert args["p_audience"] == "humano"


@pytest.mark.asyncio
async def test_string_vazia_do_builder_vira_null():
    """O <select> do builder usa value="" para "— qualquer —". String vazia num
    parametro uuid da RPC e erro de sintaxe no Postgres, nao "sem filtro"."""
    node = dict(TRIGGER_NODE, config=dict(
        TRIGGER_NODE["config"], stage_id="", pipeline_id="", stage_key=""))
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = [LINHA]
    with (
        patch("app.automation.triggers.get_supabase", return_value=sb),
        patch("app.automation.triggers.get_campaigns_with_trigger_type",
              side_effect=lambda t: [node] if t == "deal_stage_stagnation" else []),
        patch("app.automation.triggers.is_already_enrolled", return_value=False),
        patch("app.automation.triggers._engine._conversation_followup_disabled", return_value=False),
        patch("app.automation.triggers.is_lead_blacklisted", return_value=False),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await check_polling_triggers(NOW)
    args = sb.rpc.call_args[0][1]
    assert args["p_stage_id"] is None
    assert args["p_stage_key"] is None
    assert args["p_pipeline_id"] is None
    assert mock_enroll.call_args.kwargs["metadata"]["guard"]["stage_key"] is None


@pytest.mark.asyncio
async def test_pula_ja_enrolado():
    ps, sb = _patches([LINHA], enrolled=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_pula_conversa_finalizada():
    ps, sb = _patches([LINHA], disabled=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_pula_blacklist():
    """A esteira de reposicao varre a base inteira — e onde mora quem pediu para
    nao ser incomodado. Os gatilhos de polling atuais nao tem essa guarda."""
    ps, sb = _patches([LINHA], blacklisted=True)
    with ps[0], ps[1], ps[2], ps[3], ps[4], \
         patch("app.automation.triggers.create_enrollment") as mock_enroll:
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_sem_next_node_nao_enrolla():
    node = dict(TRIGGER_NODE, next_node_id=None)
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = [LINHA]
    with (
        patch("app.automation.triggers.get_supabase", return_value=sb),
        patch("app.automation.triggers.get_campaigns_with_trigger_type",
              side_effect=lambda t: [node] if t == "deal_stage_stagnation" else []),
        patch("app.automation.triggers.is_already_enrolled", return_value=False),
        patch("app.automation.triggers._engine._conversation_followup_disabled", return_value=False),
        patch("app.automation.triggers.is_lead_blacklisted", return_value=False),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()


@pytest.mark.asyncio
async def test_rpc_falha_nao_derruba_o_tick():
    """RPC ausente/erro no Postgres nao pode abortar check_polling_triggers — os
    outros gatilhos do mesmo tick continuam valendo."""
    sb = MagicMock()
    sb.rpc.return_value.execute.side_effect = Exception("function does not exist")
    with (
        patch("app.automation.triggers.get_supabase", return_value=sb),
        patch("app.automation.triggers.get_campaigns_with_trigger_type",
              side_effect=lambda t: [TRIGGER_NODE] if t == "deal_stage_stagnation" else []),
        patch("app.automation.triggers.is_already_enrolled", return_value=False),
        patch("app.automation.triggers._engine._conversation_followup_disabled", return_value=False),
        patch("app.automation.triggers.is_lead_blacklisted", return_value=False),
        patch("app.automation.triggers.create_enrollment") as mock_enroll,
    ):
        await check_polling_triggers(NOW)
    mock_enroll.assert_not_called()
