from app.whatsapp.base import WhatsAppProvider
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient

_PROVIDERS: dict[str, type[WhatsAppProvider]] = {
    "evolution": EvolutionClient,
    "meta_cloud": MetaCloudClient,
}


def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve the correct WhatsAppProvider instance from a channel record.

    Args:
        channel: dict with keys 'provider' (str) and 'provider_config' (dict)

    Returns:
        Concrete WhatsAppProvider instance ready for use.
    """
    provider_type = channel["provider"]
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_type!r}. Expected one of: {list(_PROVIDERS)}")
    return provider_class(channel.get("provider_config", {}))
