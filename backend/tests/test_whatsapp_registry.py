import pytest

from app.whatsapp.registry import get_provider
from app.whatsapp.meta import MetaCloudClient


def test_get_provider_returns_meta_client():
    channel = {
        "provider": "meta_cloud",
        "provider_config": {
            "phone_number_id": "123456",
            "access_token": "EAAtest",
        },
    }
    provider = get_provider(channel)
    assert isinstance(provider, MetaCloudClient)


def test_get_provider_raises_for_unknown():
    channel = {
        "provider": "unknown_provider",
        "provider_config": {},
    }
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider(channel)


def test_get_provider_raises_for_evolution_descontinuado():
    """Evolution foi removido do registry (Card 1, 12/07): o adapter estava morto
    (CLAUDE.md §6 — Meta Graph API é a fonte única) e a interface do seam era
    moldada por ele. Canal legado com provider=evolution deve falhar ALTO e claro,
    nunca silenciosamente."""
    channel = {
        "provider": "evolution",
        "provider_config": {"api_url": "http://evo.local", "api_key": "k", "instance": "i"},
    }
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider(channel)


def test_meta_client_stores_config():
    channel = {
        "provider": "meta_cloud",
        "provider_config": {
            "phone_number_id": "9999",
            "access_token": "tok",
        },
    }
    client = get_provider(channel)
    assert client.phone_number_id == "9999"
    assert client.access_token == "tok"
