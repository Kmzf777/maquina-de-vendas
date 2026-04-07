import pytest
from app.webhook.router import is_duplicate_message


async def test_primeira_mensagem_nao_e_duplicada(fake_redis):
    result = await is_duplicate_message(fake_redis, "wamid.abc123")
    assert result is False


async def test_segunda_mensagem_com_mesmo_id_e_duplicada(fake_redis):
    await is_duplicate_message(fake_redis, "wamid.abc123")
    result = await is_duplicate_message(fake_redis, "wamid.abc123")
    assert result is True


async def test_ids_diferentes_nao_sao_duplicatas(fake_redis):
    await is_duplicate_message(fake_redis, "wamid.aaa")
    result = await is_duplicate_message(fake_redis, "wamid.bbb")
    assert result is False


async def test_chave_expira_em_24h(fake_redis):
    await is_duplicate_message(fake_redis, "wamid.xyz")
    ttl = await fake_redis.ttl("seen:wamid.xyz")
    # TTL deve ser próximo de 86400 (24h)
    assert 86390 <= ttl <= 86400
