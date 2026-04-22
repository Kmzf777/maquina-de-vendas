import pytest
import respx
import httpx
from app.dev_router.forwarder import forward_to_dev


@pytest.mark.anyio
@respx.mock
async def test_forward_posts_to_dev_url():
    route = respx.post("http://172.17.0.1:8001/webhook/evolution").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    await forward_to_dev(
        dev_url="http://172.17.0.1:8001",
        path="/webhook/evolution",
        headers={"content-type": "application/json"},
        body=b'{"event":"messages.upsert"}',
    )
    assert route.called
    assert route.calls[0].request.content == b'{"event":"messages.upsert"}'


@pytest.mark.anyio
@respx.mock
async def test_forward_passes_signature_header():
    route = respx.post("http://172.17.0.1:8001/webhook/meta").mock(
        return_value=httpx.Response(200)
    )
    await forward_to_dev(
        dev_url="http://172.17.0.1:8001",
        path="/webhook/meta",
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": "sha256=abc123",
            "host": "api.canastrainteligencia.com",
        },
        body=b"{}",
    )
    sent_headers = route.calls[0].request.headers
    assert sent_headers["x-hub-signature-256"] == "sha256=abc123"
    # host header is set by httpx to the target URL, not forwarded from input
    assert sent_headers["host"] == "172.17.0.1:8001"


@pytest.mark.anyio
@respx.mock
async def test_forward_swallows_connection_error():
    respx.post("http://172.17.0.1:8001/webhook/evolution").mock(
        side_effect=httpx.ConnectError("refused")
    )
    # Must not raise
    await forward_to_dev(
        dev_url="http://172.17.0.1:8001",
        path="/webhook/evolution",
        headers={},
        body=b"{}",
    )


@pytest.mark.anyio
@respx.mock
async def test_forward_swallows_timeout():
    respx.post("http://172.17.0.1:8001/webhook/evolution").mock(
        side_effect=httpx.TimeoutException("timeout")
    )
    await forward_to_dev(
        dev_url="http://172.17.0.1:8001",
        path="/webhook/evolution",
        headers={},
        body=b"{}",
    )
