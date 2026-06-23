"""UX de envio "100% humano": tique azul deslocado, debounce com reset de 15s,
indicador de digitação (typing_on) proporcional.

CA#1 — mark_read só no início do turno da IA (não na ingestão).
CA#2 — buffer reseta para 15s a cada mensagem nova; teto absoluto de 60s.
CA#4 — typing_indicator antes de cada balão com sleep proporcional.
"""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.webhook.parser import IncomingMessage
from app.whatsapp.meta import MetaCloudClient

META_CONFIG = {"phone_number_id": "123456", "access_token": "tok", "api_version": "v21.0"}


def _msg(from_number="5511999990000", message_id="wamid.in1", text="oi"):
    return IncomingMessage(
        from_number=from_number,
        remote_jid=f"{from_number}@s.whatsapp.net",
        message_id=message_id,
        timestamp="0",
        type="text",
        text=text,
        channel_id="chan-1",
    )


def _redis_for(deadline_offset: float | None, has_lock: bool, current_ttl: int = 8):
    """AsyncMock Redis com get() despachando por chave."""
    now = time.time()

    async def _get(key):
        if key == "config:buffer_enabled":
            return "1"
        if key.endswith(":deadline"):
            return str(now + deadline_offset) if deadline_offset is not None else None
        return None

    r = AsyncMock()
    r.get = AsyncMock(side_effect=_get)
    r.exists = AsyncMock(return_value=1 if has_lock else 0)
    r.ttl = AsyncMock(return_value=current_ttl)
    return r


# ---------------------------------------------------------------------------
# CA#4 — meta.py typing indicator payload
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_send_typing_indicator_builds_read_plus_typing_payload():
    client = MetaCloudClient(META_CONFIG)
    client._post = AsyncMock(return_value={"success": True})

    await client.send_typing_indicator("wamid.abc")

    payload = client._post.call_args.args[0]
    assert payload["messaging_product"] == "whatsapp"
    assert payload["status"] == "read"           # typing exige status read na Meta
    assert payload["message_id"] == "wamid.abc"
    assert payload["typing_indicator"] == {"type": "text"}
    assert client._post.call_args.kwargs.get("request_type") == "typing_on"


# ---------------------------------------------------------------------------
# CA#2 — debounce com reset real de 15s + teto de 60s
# ---------------------------------------------------------------------------
def test_buffer_max_timeout_is_60s():
    assert settings.buffer_max_timeout == 60


@pytest.mark.asyncio
async def test_buffer_first_message_sets_base_ttl_and_60s_deadline():
    from app.buffer.manager import push_to_buffer

    r = _redis_for(deadline_offset=None, has_lock=False)
    with patch("app.buffer.manager._wait_and_flush", new=MagicMock()), \
         patch("app.buffer.manager.asyncio.create_task", new=MagicMock()):
        await push_to_buffer(r, _msg())

    set_calls = {c.args[0]: c for c in r.set.call_args_list}
    lock_key = "buffer:5511999990000:chan-1:lock"
    deadline_key = "buffer:5511999990000:chan-1:deadline"

    # lock criado com TTL = base (15s)
    assert set_calls[lock_key].args[1] == "1"
    assert set_calls[lock_key].kwargs["ex"] == 15
    # deadline absoluto = base_max (60s), com folga de +5 no TTL da chave
    assert set_calls[deadline_key].kwargs["ex"] == 65
    flush_at = float(set_calls[deadline_key].args[1])
    assert 58 <= (flush_at - time.time()) <= 60
    # primeira mensagem não estende lock existente
    r.expire.assert_not_called()


@pytest.mark.asyncio
async def test_buffer_new_message_resets_to_base_not_extend():
    """A 2ª mensagem deve RESETAR o lock para 15s (não 'extend +5' sobre o TTL atual)."""
    from app.buffer.manager import push_to_buffer

    # Há lock ativo, TTL atual 8s, deadline bem distante (~50s) → reset deve dar 15, não 13.
    r = _redis_for(deadline_offset=50.0, has_lock=True, current_ttl=8)
    await push_to_buffer(r, _msg(message_id="wamid.in2"))

    r.expire.assert_awaited_once()
    key, new_ttl = r.expire.await_args.args
    assert key == "buffer:5511999990000:chan-1:lock"
    assert new_ttl == 15  # reset para o base, não 8+5=13


@pytest.mark.asyncio
async def test_buffer_reset_capped_by_absolute_deadline():
    """Perto do teto absoluto, o reset não pode ultrapassar o tempo restante até o deadline."""
    from app.buffer.manager import push_to_buffer

    r = _redis_for(deadline_offset=6.0, has_lock=True, current_ttl=4)
    await push_to_buffer(r, _msg(message_id="wamid.in3"))

    _key, new_ttl = r.expire.await_args.args
    assert 0 < new_ttl <= 6  # capeado pelo restante até o deadline, < 15


# ---------------------------------------------------------------------------
# CA#1 + CA#4 — processor: read no início do turno, typing antes dos balões
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_processor_marks_read_at_turn_start_and_types_before_bubbles():
    from app.buffer.processor import process_buffered_messages

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
         patch("app.buffer.processor.settings") as mock_settings:
        mock_settings.ai_phone_number_ids = []
        mock_settings.valeria_enabled = True
        mock_sb.return_value.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        await process_buffered_messages(
            "+5511999990000", "oi", channel_id="chan-1", wamid="wamid.inbound"
        )

    kinds = [e[0] for e in events]
    # read PRIMEIRO (início do turno). Agora o 1º balão também tem delay de digitação
    # (LLM mock é instantânea → llm_latency ~0 → delay>0), então typing precede CADA balão.
    assert kinds == ["read", "typing", "text", "typing", "text"], f"sequência inesperada: {events}"
    assert events[0] == ("read", "wamid.inbound")
    # read e typing referenciam o wamid da última msg do lead; text carrega o conteúdo do balão
    assert all(e[1] == "wamid.inbound" for e in events if e[0] in ("read", "typing"))
