import os

from app.whatsapp.base import WhatsAppProvider
from app.whatsapp.meta import MetaCloudClient
from app.whatsapp.mock_provider import MockProvider

# Evolution API removido do registry (Card 1, 12/07): adapter morto desde a migração
# para a Meta Graph API (CLAUDE.md §6). Canal legado com provider="evolution" falha
# alto no ValueError abaixo — nunca silenciosamente.
_PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    "meta_cloud": MetaCloudClient,
}


def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve the correct WhatsAppProvider instance from a channel record.

    When REHEARSAL_MODE=true, returns a MockProvider instead — used during
    automated rehearsal so Valéria's outbound messages are not sent via real
    WhatsApp. The mock still logs and triggers save_message paths elsewhere,
    preserving the orchestrator flow.
    """
    if os.environ.get("REHEARSAL_MODE", "").lower() == "true":
        return MockProvider(channel.get("provider_config", {}))

    provider_type = channel["provider"]
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_type!r}. Expected one of: {list(_PROVIDERS)}")
    return provider_class(channel.get("provider_config", {}))
