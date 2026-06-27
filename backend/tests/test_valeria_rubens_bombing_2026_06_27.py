"""Anti message-bombing (caso Rubens 5531999844461): peek do buffer Redis no re-coalescing.

A irmã fica ~15s no buffer Redis antes de ir pro DB; o guard só-DB ficava cego a ela durante o
envio do 1º turno → 2º turno empilhado. Agora o guard também consulta o buffer.
"""
import pytest
from unittest.mock import AsyncMock, patch
from app.buffer import processor


@pytest.fixture(autouse=True)
def _reset_buffer_cooldown():
    """Zera o cooldown de Redis indisponível antes de cada teste (estado global do módulo)."""
    processor._buffer_unavailable_until = 0.0
    yield
    processor._buffer_unavailable_until = 0.0


@pytest.mark.asyncio
async def test_pending_buffered_inbound_true_quando_buffer_tem_item():
    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(return_value=1)
    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis):
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is True
    fake_redis.llen.assert_awaited()  # consultou buffer:{phone}:{channel}


@pytest.mark.asyncio
async def test_pending_buffered_inbound_false_quando_vazio():
    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(return_value=0)
    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis):
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is False


@pytest.mark.asyncio
async def test_pending_buffered_inbound_failopen_false_em_erro():
    fake_redis = AsyncMock()
    fake_redis.llen = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch("app.buffer.processor._get_buffer_redis", return_value=fake_redis):
        # fail-open: erro de Redis nunca aborta o atendimento
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is False


@pytest.mark.asyncio
async def test_cooldown_evita_repagar_timeout_apos_falha():
    """Após uma falha, o cooldown faz a próxima chamada falhar-aberto SEM tocar o Redis."""
    boom = AsyncMock()
    boom.llen = AsyncMock(side_effect=RuntimeError("redis down"))
    with patch("app.buffer.processor._get_buffer_redis", return_value=boom):
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is False
    # 2ª chamada: cooldown ativo → retorna False sem nem chamar _get_buffer_redis
    with patch("app.buffer.processor._get_buffer_redis", side_effect=AssertionError("não deve conectar em cooldown")):
        assert await processor._has_pending_buffered_inbound("5531999844461", "ch-1") is False
