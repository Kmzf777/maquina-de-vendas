import os
import pytest
from unittest.mock import patch
from app.dev_router.service import (
    is_dev_number,
    add_dev_number,
    remove_dev_number,
    list_dev_numbers,
    get_dev_route,
    set_dev_route,
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


# --- 9th-digit normalization tests ---

@pytest.mark.anyio
async def test_register_12digit_lookup_13digit(fake_redis):
    """Registering legacy 12-digit number is found via canonical 13-digit lookup."""
    await add_dev_number(fake_redis, "553496652412")
    assert await is_dev_number(fake_redis, "5534996652412") is True


@pytest.mark.anyio
async def test_register_13digit_lookup_12digit(fake_redis):
    """Registering canonical 13-digit is also found via 12-digit input."""
    await add_dev_number(fake_redis, "5534996652412")
    assert await is_dev_number(fake_redis, "553496652412") is True


@pytest.mark.anyio
async def test_get_dev_route_12digit_input_returns_url(fake_redis):
    """get_dev_route returns the URL regardless of whether input is 12 or 13 digits."""
    with patch.dict(os.environ, {"IS_DEV_ENV": "false"}):
        await set_dev_route(fake_redis, "5534996652412", "http://localhost:8001")
        url_13 = await get_dev_route(fake_redis, "5534996652412")
        url_12 = await get_dev_route(fake_redis, "553496652412")
        assert url_13 == "http://localhost:8001"
        assert url_12 == "http://localhost:8001"


@pytest.mark.anyio
async def test_all_formats_resolve_to_same_entry(fake_redis):
    """All common formats for the dev number resolve to the same whitelist entry."""
    await add_dev_number(fake_redis, "5534996652412")
    formats = [
        "5534996652412",
        "553496652412",
        "+5534996652412",
        "55 34 99665-2412",
        "+55 (34) 99665-2412",
        "55-34-99665-2412",
    ]
    for fmt in formats:
        assert await is_dev_number(fake_redis, fmt) is True, f"Format not recognized: {fmt!r}"


@pytest.mark.anyio
async def test_get_dev_route_returns_none_when_is_dev_env(fake_redis):
    """get_dev_route returns None on the dev server (IS_DEV_ENV=true) to prevent loops."""
    with patch.dict(os.environ, {"IS_DEV_ENV": "true"}):
        await set_dev_route(fake_redis, "5534996652412", "http://localhost:8001")
        assert await get_dev_route(fake_redis, "5534996652412") is None
