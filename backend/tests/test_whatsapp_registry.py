import pytest
from unittest.mock import patch

from app.whatsapp.registry import get_provider
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient


def test_get_provider_returns_evolution_client():
    channel = {
        "provider": "evolution",
        "provider_config": {
            "api_url": "http://evolution.local",
            "api_key": "test-key",
            "instance": "test-instance",
        },
    }
    provider = get_provider(channel)
    assert isinstance(provider, EvolutionClient)


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


def test_evolution_client_stores_config():
    channel = {
        "provider": "evolution",
        "provider_config": {
            "api_url": "http://evo.local",
            "api_key": "my-key",
            "instance": "my-instance",
        },
    }
    client = get_provider(channel)
    assert client.base_url == "http://evo.local"
    assert client.api_key == "my-key"
    assert client.instance == "my-instance"


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
