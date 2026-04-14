from app.providers.base import WhatsAppProvider
from app.providers.meta_cloud import MetaCloudProvider
from app.providers.evolution import EvolutionProvider

_PROVIDERS = {
    "meta_cloud": MetaCloudProvider,
    "evolution": EvolutionProvider,
}


def get_provider(channel: dict) -> WhatsAppProvider:
    """Resolve a WhatsAppProvider instance from a channel record."""
    provider_type = channel["provider"]
    provider_class = _PROVIDERS.get(provider_type)
    if not provider_class:
        raise ValueError(f"Unknown provider: {provider_type}")
    return provider_class(channel["provider_config"])
