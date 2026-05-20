"""Tests for mode field validation in channels API models."""
import pytest
from app.channels.router import ChannelCreate, ChannelUpdate


def test_channel_create_default_mode_is_ai():
    body = ChannelCreate(
        name="Test",
        phone="5534999999999",
        provider="meta_cloud",
        provider_config={},
    )
    assert body.mode == "ai"


def test_channel_create_accepts_human():
    body = ChannelCreate(
        name="Vendedor",
        phone="5534999999999",
        provider="meta_cloud",
        provider_config={},
        mode="human",
    )
    assert body.mode == "human"


def test_channel_update_mode_none_by_default():
    body = ChannelUpdate()
    assert body.mode is None


def test_channel_update_accepts_mode_human():
    body = ChannelUpdate(mode="human")
    assert body.mode == "human"


def test_channel_update_accepts_mode_ai():
    body = ChannelUpdate(mode="ai")
    assert body.mode == "ai"
