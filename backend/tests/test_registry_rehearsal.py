import pytest

from app.whatsapp.registry import get_provider
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.meta import MetaCloudClient


def test_returns_mock_when_rehearsal_mode(monkeypatch):
    monkeypatch.setenv("REHEARSAL_MODE", "true")
    channel = {"provider": "meta_cloud", "provider_config": {}}
    provider = get_provider(channel)
    assert isinstance(provider, MockProvider)


def test_returns_real_when_rehearsal_mode_unset(monkeypatch):
    monkeypatch.delenv("REHEARSAL_MODE", raising=False)
    channel = {
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    provider = get_provider(channel)
    assert isinstance(provider, MetaCloudClient)


def test_rehearsal_mode_false_also_returns_real(monkeypatch):
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {
        "provider": "meta_cloud",
        "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    }
    provider = get_provider(channel)
    assert isinstance(provider, MetaCloudClient)
