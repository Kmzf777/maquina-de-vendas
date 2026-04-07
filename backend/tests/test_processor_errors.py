import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_channel(with_profile=True):
    return {
        "id": "chan-uuid",
        "name": "Test",
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "12345", "access_token": "tok"},
        "agent_profile_id": "profile-uuid" if with_profile else None,
    }


async def test_falha_no_lead_retorna_sem_crashar():
    """Se get_or_create_lead falhar, a função deve retornar silenciosamente."""
    from app.buffer.processor import process_buffered_messages

    with patch("app.buffer.processor.get_provider"), \
         patch("app.buffer.processor._resolve_media", return_value="oi"), \
         patch("app.buffer.processor.get_or_create_lead", side_effect=Exception("DB timeout")):
        # Não deve levantar exceção
        await process_buffered_messages("5511999999999", "oi", _make_channel())


async def test_mensagem_do_usuario_sempre_salva_mesmo_quando_agente_falha():
    """Falha no run_agent não deve impedir que save_message seja chamado."""
    from app.buffer.processor import process_buffered_messages

    saved_messages = []

    def mock_save(conv_id, lead_id, role, content, stage=None):
        saved_messages.append({"role": role, "content": content})
        return {}

    with patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
         patch("app.buffer.processor._resolve_media", return_value="oi"), \
         patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "phone": "5511999999999"}), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor.get_agent_profile", return_value={
             "id": "profile-uuid", "model": "gpt-4.1",
             "base_prompt": "You are ValerIA", "stages": {}
         }), \
         patch("app.buffer.processor.save_message", side_effect=mock_save), \
         patch("app.buffer.processor.run_agent", side_effect=Exception("OpenAI timeout")), \
         patch("app.buffer.processor.update_conversation", return_value={}):
        await process_buffered_messages("5511999999999", "oi", _make_channel())

    # Mensagem do usuário deve ter sido salva
    user_msgs = [m for m in saved_messages if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert user_msgs[0]["content"] == "oi"


async def test_falha_no_send_nao_cancela_save_da_resposta():
    """Falha no provider.send_text não deve impedir save da resposta do agente."""
    from app.buffer.processor import process_buffered_messages

    saved_messages = []

    def mock_save(conv_id, lead_id, role, content, stage=None):
        saved_messages.append({"role": role, "content": content})
        return {}

    mock_provider = AsyncMock()
    mock_provider.send_text = AsyncMock(side_effect=Exception("Network error"))

    with patch("app.buffer.processor.get_provider", return_value=mock_provider), \
         patch("app.buffer.processor._resolve_media", return_value="oi"), \
         patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "phone": "5511999999999"}), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor.get_agent_profile", return_value={
             "id": "profile-uuid", "model": "gpt-4.1",
             "base_prompt": "You are ValerIA", "stages": {}
         }), \
         patch("app.buffer.processor.save_message", side_effect=mock_save), \
         patch("app.buffer.processor.run_agent", return_value="Olá! Como posso ajudar?"), \
         patch("app.buffer.processor.split_into_bubbles", return_value=["Olá! Como posso ajudar?"]), \
         patch("app.buffer.processor.calculate_typing_delay", return_value=0), \
         patch("app.buffer.processor.update_conversation", return_value={}):
        await process_buffered_messages("5511999999999", "oi", _make_channel())

    assistant_msgs = [m for m in saved_messages if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1


async def test_canal_sem_agent_profile_salva_mensagem_usuario():
    """Canal sem agent_profile_id ainda deve salvar a mensagem do usuário."""
    from app.buffer.processor import process_buffered_messages

    saved_messages = []

    def mock_save(conv_id, lead_id, role, content, stage=None):
        saved_messages.append({"role": role, "content": content})
        return {}

    with patch("app.buffer.processor.get_provider", return_value=AsyncMock()), \
         patch("app.buffer.processor._resolve_media", return_value="oi"), \
         patch("app.buffer.processor.get_or_create_lead", return_value={"id": "lead-1", "phone": "5511999999999"}), \
         patch("app.buffer.processor.get_or_create_conversation", return_value={
             "id": "conv-1", "status": "active", "stage": "secretaria"
         }), \
         patch("app.buffer.processor.save_message", side_effect=mock_save), \
         patch("app.buffer.processor.update_conversation", return_value={}):
        await process_buffered_messages("5511999999999", "oi", _make_channel(with_profile=False))

    user_msgs = [m for m in saved_messages if m["role"] == "user"]
    assert len(user_msgs) == 1
