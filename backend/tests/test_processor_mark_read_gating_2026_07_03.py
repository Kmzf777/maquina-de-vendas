"""Gate do recibo de leitura (mark_read) no buffer — CA#1 movido para pós-gates.

Regra "nunca lido sem resposta": o tique azul automático do buffer (provider.mark_read)
só pode disparar quando a Valéria REALMENTE vai responder — depois de TODOS os gates de
handoff/canal-humano/kill-switch/allowlist/escalação. Em atendimento humano o recibo passa
a ser disparado quando o vendedor responde pela plataforma (endpoint /read-receipt), e NÃO
mais aqui — assim o cliente nunca vê o tique azul sem ninguém ter respondido.

Os mocks espelham test_processor_human_control.py, test_processor_channel_mode.py e
test_human_pacing.py::test_processor_marks_read_at_turn_start_and_types_before_bubbles.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_mark_read_nao_dispara_em_handoff():
    """ai_enabled=False (handoff): mark_read NÃO dispara e run_agent não roda.

    Mesmo com wamid presente, o tique azul fica ATRÁS do gate de ai_enabled — o recibo só
    sai quando a IA vai responder. Modela test_human_control_skips_agent: o lead satisfaz
    a ponte pós-handoff (B1) e _get_buffer_redis estoura, forçando o caminho fail-closed
    determinístico (teste hermético, sem depender de Redis local).
    """
    lead = {
        "id": "lead-123",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "human_control": True,
        "ai_enabled": False,
        "name": "João",
    }
    channel = {
        "id": "channel-1",
        "is_active": True,
        # sem 'mode' → default "ai": o bloqueio vem do ai_enabled=false, não do canal
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    conversation = {
        "id": "conv-1",
        "lead_id": "lead-123",
        "channel_id": "channel-1",
        "stage": "atacado",
        "status": "active",
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conversation), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed", return_value=False), \
         patch("app.buffer.processor._get_buffer_redis", side_effect=RuntimeError("sem redis no teste")), \
         patch("app.buffer.processor.update_conversation"):

        mock_provider = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages(
            "+5511999999999", "oi quero comprar", "channel-1", wamid="wamid.inbound"
        )

        # tique azul NÃO sai em handoff — o recibo passa a ser do endpoint /read-receipt
        mock_provider.mark_read.assert_not_awaited()
        mock_agent.assert_not_called()
        # a mensagem do cliente ainda é persistida, mesmo sob handoff
        mock_save.assert_called_once()
        assert mock_save.call_args.args[2] == "user"


@pytest.mark.asyncio
async def test_mark_read_nao_dispara_em_canal_humano():
    """Canal mode='human' (ai_enabled=True): mark_read NÃO dispara e run_agent não roda.

    O gate de canal humano precede o bloco de mark_read; o recibo passa a sair pelo
    endpoint /read-receipt quando o vendedor responde. Modela
    test_processor_channel_mode.test_human_channel_skips_agent.
    """
    lead = {
        "id": "lead-1",
        "phone": "+5511999999999",
        "stage": "atacado",
        "status": "active",
        "ai_enabled": True,
        "name": "Teste",
    }
    channel = {
        "id": "ch-1",
        "is_active": True,
        "mode": "human",
        "agent_profiles": {"id": "p1", "stages": {}},
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    conversation = {
        "id": "conv-1",
        "lead_id": "lead-1",
        "channel_id": "ch-1",
        "stage": "atacado",
        "status": "active",
        "followup_enabled": True,
    }

    with patch("app.buffer.processor.get_or_create_lead", return_value=lead), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel), \
         patch("app.buffer.processor.get_provider") as mock_provider_fn, \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conversation), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message") as mock_save, \
         patch("app.buffer.processor.run_agent") as mock_agent, \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed", return_value=False), \
         patch("app.buffer.processor.update_conversation"), \
         patch("app.buffer.processor._schedule_followup") as mock_followup, \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor._update_last_msg") as mock_update_last:

        mock_sb.return_value = MagicMock(
            table=MagicMock(return_value=MagicMock(
                update=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(execute=MagicMock(return_value=MagicMock()))),
                )),
                select=MagicMock(return_value=MagicMock(
                    eq=MagicMock(return_value=MagicMock(
                        single=MagicMock(return_value=MagicMock(
                            execute=MagicMock(return_value=MagicMock(data={"unread_count": 0}))
                        ))
                    ))
                )),
            ))
        )
        mock_provider = AsyncMock()
        mock_provider_fn.return_value = mock_provider

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages(
            "+5511999999999", "oi", "ch-1", wamid="wamid.inbound"
        )

        mock_provider.mark_read.assert_not_awaited()
        mock_agent.assert_not_called()
        mock_followup.assert_not_called()
        mock_update_last.assert_called_once_with("conv-1")


@pytest.mark.asyncio
async def test_mark_read_dispara_no_caminho_ia():
    """Caminho feliz (ai_enabled=True, canal 'ai'): mark_read dispara 1x com o wamid.

    Passados todos os gates, a Valéria vai responder → o tique azul sai ANTES da geração,
    preservando a ordem read→typing→text do caminho IA. Modela
    test_human_pacing.test_processor_marks_read_at_turn_start_and_types_before_bubbles,
    reusando os mesmos patches (run_agent/_resolve_media/split_into_bubbles/asyncio.sleep/
    _start_typing_pulse/settings).
    """
    lead_data = {"id": "lead-x", "phone": "+5511999990000", "ai_enabled": True, "human_control": False}
    conv_data = {"id": "conv-x", "lead_id": "lead-x", "stage": "consumo", "status": "active",
                 "ai_enabled": True, "agent_profile_id": None}
    channel_data = {"id": "chan-1", "mode": "ai", "agent_profiles": None,
                    "provider_config": {"phone_number_id": "ph"}}

    events: list[tuple] = []
    provider = MagicMock()
    provider.mark_read = AsyncMock(side_effect=lambda mid: events.append(("read", mid)))
    provider.send_typing_indicator = AsyncMock(side_effect=lambda mid: events.append(("typing", mid)))
    provider.send_text = AsyncMock(side_effect=lambda ph, txt: events.append(("text", txt)))

    # _start_typing_pulse stubado (o pulso de fundo é um while-True que inunda `events`
    # sob asyncio.sleep mockado); este teste valida o gating do read, não o pulso de fundo.
    with patch("app.buffer.processor.get_or_create_lead", return_value=lead_data), \
         patch("app.buffer.processor.get_channel_by_id", return_value=channel_data), \
         patch("app.buffer.processor.get_or_create_conversation", return_value=conv_data), \
         patch("app.buffer.processor._is_recent_duplicate", return_value=False), \
         patch("app.buffer.processor._wamid_already_processed", return_value=False), \
         patch("app.buffer.processor.get_active_enrollment", return_value=None), \
         patch("app.buffer.processor.save_message", return_value={}), \
         patch("app.buffer.processor.get_supabase") as mock_sb, \
         patch("app.buffer.processor.get_provider", return_value=provider), \
         patch("app.buffer.processor.run_agent", new=AsyncMock(return_value="Oi tudo bem")), \
         patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: (t, None, None, None, None))), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["Oi tudo bem", "Como posso ajudar"]), \
         patch("app.buffer.processor.asyncio.sleep", new=AsyncMock()), \
         patch("app.buffer.processor._start_typing_pulse", return_value=None), \
         patch("app.buffer.processor.settings") as mock_settings:
        mock_settings.ai_phone_number_ids = []
        mock_settings.valeria_enabled = True
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        from app.buffer.processor import process_buffered_messages
        await process_buffered_messages(
            "+5511999990000", "oi", channel_id="chan-1", wamid="wamid.inbound"
        )

    # o tique azul dispara exatamente uma vez, referenciando o wamid do inbound
    provider.mark_read.assert_awaited_once_with("wamid.inbound")
    # read é o PRIMEIRO evento — antes de qualquer typing/text (ordem do caminho IA)
    assert events and events[0] == ("read", "wamid.inbound"), f"sequência inesperada: {events}"
    # prova de que a IA de fato rodou e a resposta chegou ao lead (não bloqueado por gate)
    assert ("text", "Oi tudo bem") in events, f"resposta da IA não enviada: {events}"
