from app.whatsapp.base import WhatsAppClient
from app.whatsapp.evolution import EvolutionClient
from app.whatsapp.meta import MetaCloudClient


def get_whatsapp_client(channel: dict) -> WhatsAppClient:
    """Instantiate the correct WhatsApp client based on channel provider."""
    provider = channel["provider"]
    config = channel.get("provider_config", {})

    if provider == "evolution":
        return EvolutionClient(
            api_url=config["api_url"],
            api_key=config["api_key"],
            instance=config["instance"],
        )
    elif provider == "meta_cloud":
        return MetaCloudClient(
            phone_number_id=config["phone_number_id"],
            access_token=config["access_token"],
        )
    else:
        raise ValueError(f"Unknown provider: {provider}")
