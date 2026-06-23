"""A1 — cliente HTTP compartilhado + retry/backoff respeitando rate limit da Meta."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.whatsapp.meta import MetaCloudClient

CONFIG = {
    "phone_number_id": "123456",
    "access_token": "test_token",
    "api_version": "v21.0",
}


def _resp(status_code: int, json_data: dict | None = None, headers: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.is_success = 200 <= status_code < 300
    resp.json = MagicMock(return_value=json_data if json_data is not None else {})
    resp.headers = headers or {}
    resp.reason_phrase = "OK" if resp.is_success else "Error"
    resp.text = str(json_data)

    def _raise():
        if not resp.is_success:
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=resp)

    resp.raise_for_status = MagicMock(side_effect=_raise)
    return resp


def _mock_client(responses: list):
    """AsyncMock client whose .request yields each item (response or exception)."""
    client = AsyncMock()
    client.request = AsyncMock(side_effect=responses)
    return client


@pytest.mark.anyio
async def test_post_retries_on_429_then_succeeds():
    client = MetaCloudClient(CONFIG)
    http = _mock_client([
        _resp(429, {"error": {"message": "rate limited", "code": 80007}}, {"Retry-After": "0"}),
        _resp(200, {"messages": [{"id": "wamid.1"}]}),
    ])
    with patch("app.whatsapp.meta.get_shared_client", return_value=http), \
         patch("app.whatsapp.meta.asyncio.sleep", new=AsyncMock()) as sleep, \
         patch("app.whatsapp.meta.log_outbound"):
        result = await client._post({"to": "x", "type": "text"}, request_type="send_text")

    assert result == {"messages": [{"id": "wamid.1"}]}
    assert http.request.await_count == 2
    sleep.assert_awaited()


@pytest.mark.anyio
async def test_post_honors_retry_after_header():
    client = MetaCloudClient(CONFIG)
    http = _mock_client([
        _resp(429, {"error": "slow down"}, {"Retry-After": "3"}),
        _resp(200, {"messages": [{"id": "wamid.2"}]}),
    ])
    with patch("app.whatsapp.meta.get_shared_client", return_value=http), \
         patch("app.whatsapp.meta.asyncio.sleep", new=AsyncMock()) as sleep, \
         patch("app.whatsapp.meta.log_outbound"):
        await client._post({"to": "x"}, request_type="send_text")

    # Backoff deve usar exatamente o Retry-After (sem jitter) quando presente.
    sleep.assert_awaited_once_with(3.0)


@pytest.mark.anyio
async def test_post_retries_on_5xx():
    client = MetaCloudClient(CONFIG)
    http = _mock_client([
        _resp(503, {"error": "unavailable"}),
        _resp(200, {"messages": [{"id": "wamid.3"}]}),
    ])
    with patch("app.whatsapp.meta.get_shared_client", return_value=http), \
         patch("app.whatsapp.meta.asyncio.sleep", new=AsyncMock()), \
         patch("app.whatsapp.meta.log_outbound"):
        result = await client._post({"to": "x"}, request_type="send_text")

    assert result["messages"][0]["id"] == "wamid.3"
    assert http.request.await_count == 2


@pytest.mark.anyio
async def test_post_retries_on_transport_error():
    client = MetaCloudClient(CONFIG)
    http = _mock_client([
        httpx.ConnectError("connection refused"),
        _resp(200, {"messages": [{"id": "wamid.4"}]}),
    ])
    with patch("app.whatsapp.meta.get_shared_client", return_value=http), \
         patch("app.whatsapp.meta.asyncio.sleep", new=AsyncMock()), \
         patch("app.whatsapp.meta.log_outbound"):
        result = await client._post({"to": "x"}, request_type="send_text")

    assert result["messages"][0]["id"] == "wamid.4"
    assert http.request.await_count == 2


@pytest.mark.anyio
async def test_post_exhausts_retries_and_raises():
    client = MetaCloudClient(CONFIG)
    http = _mock_client([_resp(429, {"error": "rate"}, {"Retry-After": "0"}) for _ in range(4)])
    with patch("app.whatsapp.meta.get_shared_client", return_value=http), \
         patch("app.whatsapp.meta.asyncio.sleep", new=AsyncMock()), \
         patch("app.whatsapp.meta.log_outbound"), \
         pytest.raises(httpx.HTTPStatusError):
        await client._post({"to": "x"}, request_type="send_text")

    # 1 tentativa inicial + 3 retries = 4 (META_MAX_ATTEMPTS)
    assert http.request.await_count == 4


@pytest.mark.anyio
async def test_post_does_not_retry_on_4xx_client_error():
    client = MetaCloudClient(CONFIG)
    http = _mock_client([_resp(400, {"error": {"message": "invalid param"}})])
    with patch("app.whatsapp.meta.get_shared_client", return_value=http), \
         patch("app.whatsapp.meta.asyncio.sleep", new=AsyncMock()) as sleep, \
         patch("app.whatsapp.meta.log_outbound"), \
         pytest.raises(httpx.HTTPStatusError):
        await client._post({"to": "x"}, request_type="send_text")

    assert http.request.await_count == 1
    sleep.assert_not_awaited()


def test_get_shared_client_is_singleton_with_timeout():
    import app.whatsapp.meta as meta

    meta._shared_client = None
    c1 = meta.get_shared_client()
    c2 = meta.get_shared_client()
    try:
        assert c1 is c2
        assert c1.timeout.read == 15.0
        assert c1.timeout.connect == 15.0
    finally:
        meta._shared_client = None
