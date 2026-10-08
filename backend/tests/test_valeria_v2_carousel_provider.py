"""send_interactive_carousel: payload da Meta e validações antes do envio."""
from unittest.mock import AsyncMock

import pytest

from app.whatsapp.meta import MetaCloudClient


@pytest.fixture
def meta_client_com_post_mockado():
    class _Cliente(MetaCloudClient):
        def __init__(self):
            self._post = AsyncMock(return_value={"messages": [{"id": "wamid.TESTE"}]})

    cliente = _Cliente()
    return cliente, cliente._post


def _cards(n, botoes=1):
    return [{"image_url": f"https://x/{i}.jpg", "body": f"card {i}",
             "buttons": [(f"card:c{i}:{j}", "Quero esse") for j in range(botoes)]} for i in range(n)]


@pytest.mark.asyncio
async def test_payload_carrossel_segue_doc_da_meta(meta_client_com_post_mockado):
    client, post = meta_client_com_post_mockado
    post.return_value = {"messages": [{"id": "wamid.X"}]}
    await client.send_interactive_carousel("5534999990000", "corpo", _cards(3))
    payload = post.call_args.args[0]
    assert payload["type"] == "interactive"
    inter = payload["interactive"]
    assert inter["type"] == "carousel"
    assert inter["body"] == {"text": "corpo"}
    cards = inter["action"]["cards"]
    assert [c["card_index"] for c in cards] == [0, 1, 2]
    assert cards[0]["header"] == {"type": "image", "image": {"link": "https://x/0.jpg"}}
    assert cards[0]["body"] == {"text": "card 0"}
    assert cards[0]["action"]["buttons"] == [
        {"type": "quick_reply", "quick_reply": {"id": "card:c0:0", "title": "Quero esse"}}]


@pytest.mark.parametrize("n", [1, 11])
@pytest.mark.asyncio
async def test_recusa_fora_de_2_a_10_cards(meta_client_com_post_mockado, n):
    client, _ = meta_client_com_post_mockado
    with pytest.raises(ValueError):
        await client.send_interactive_carousel("5534999990000", "corpo", _cards(n))


@pytest.mark.asyncio
async def test_recusa_cards_com_numero_de_botoes_diferente(meta_client_com_post_mockado):
    client, _ = meta_client_com_post_mockado
    cards = _cards(2)
    cards[1]["buttons"] = cards[1]["buttons"] * 2
    with pytest.raises(ValueError):
        await client.send_interactive_carousel("5534999990000", "corpo", cards)


@pytest.mark.asyncio
async def test_recusa_corpo_do_card_acima_de_160(meta_client_com_post_mockado):
    client, _ = meta_client_com_post_mockado
    cards = _cards(2)
    cards[0]["body"] = "x" * 161
    with pytest.raises(ValueError):
        await client.send_interactive_carousel("5534999990000", "corpo", cards)


@pytest.mark.asyncio
async def test_resposta_sem_messages_vira_runtimeerror(meta_client_com_post_mockado):
    client, post = meta_client_com_post_mockado
    post.return_value = {"error": {"code": 131009}}
    with pytest.raises(RuntimeError):
        await client.send_interactive_carousel("5534999990000", "corpo", _cards(2))


@pytest.mark.asyncio
async def test_mock_registra_carrossel():
    from app.whatsapp.mock_provider import MockProvider
    r = await MockProvider({}).send_interactive_carousel("5534999990000", "corpo", _cards(2))
    assert r["method"] == "send_interactive_carousel"
