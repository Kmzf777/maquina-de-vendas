import pytest
from app.dev_router.service import (
    is_dev_number,
    add_dev_number,
    remove_dev_number,
    list_dev_numbers,
)


@pytest.mark.anyio
async def test_unknown_number_returns_false(fake_redis):
    assert await is_dev_number(fake_redis, "5511000000000") is False


@pytest.mark.anyio
async def test_add_and_check_number(fake_redis):
    await add_dev_number(fake_redis, "5511999999999")
    assert await is_dev_number(fake_redis, "5511999999999") is True


@pytest.mark.anyio
async def test_normalize_strips_plus(fake_redis):
    await add_dev_number(fake_redis, "+5511999999999")
    assert await is_dev_number(fake_redis, "5511999999999") is True


@pytest.mark.anyio
async def test_normalize_strips_spaces_and_hyphens(fake_redis):
    await add_dev_number(fake_redis, "55 11 99999-9999")
    # stored as "5511999999999"; lookup also normalizes, so both forms resolve
    assert await is_dev_number(fake_redis, "5511999999999") is True
    assert await is_dev_number(fake_redis, "55 11 99999-9999") is True


@pytest.mark.anyio
async def test_remove_number(fake_redis):
    await add_dev_number(fake_redis, "5511999999999")
    await remove_dev_number(fake_redis, "5511999999999")
    assert await is_dev_number(fake_redis, "5511999999999") is False


@pytest.mark.anyio
async def test_list_numbers(fake_redis):
    await add_dev_number(fake_redis, "5511111111111")
    await add_dev_number(fake_redis, "5511222222222")
    numbers = await list_dev_numbers(fake_redis)
    assert "5511111111111" in numbers
    assert "5511222222222" in numbers


@pytest.mark.anyio
async def test_list_empty(fake_redis):
    numbers = await list_dev_numbers(fake_redis)
    assert numbers == []
