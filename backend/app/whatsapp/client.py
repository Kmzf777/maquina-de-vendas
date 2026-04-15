"""Backward-compatible module — delegates to EvolutionClient.

Used by campaign worker and other modules that still import from here.
"""
from app.config import settings
from app.whatsapp.evolution import EvolutionClient


def _get_legacy_client() -> EvolutionClient:
    return EvolutionClient(
        api_url=settings.evolution_api_url,
        api_key=settings.evolution_api_key,
        instance=settings.evolution_instance,
    )


async def send_text(to: str, body: str) -> dict:
    return await _get_legacy_client().send_text(to, body)


async def send_template(to: str, template_name: str, language: str = "pt_BR", components: list | None = None) -> dict:
    return await send_text(to, f"[Template: {template_name}]")


async def send_image(to: str, image_url: str, caption: str | None = None) -> dict:
    return await _get_legacy_client().send_image(to, image_url, caption)


async def send_image_base64(to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
    return await _get_legacy_client().send_image_base64(to, base64_data, mimetype, caption)


async def send_audio(to: str, audio_url: str) -> dict:
    return await _get_legacy_client().send_audio(to, audio_url)


async def mark_read(message_id: str, remote_jid: str) -> dict:
    return await _get_legacy_client().mark_read(message_id, remote_jid)
