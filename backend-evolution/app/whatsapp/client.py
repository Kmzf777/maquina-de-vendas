import httpx

from app.config import settings


def _base_url() -> str:
    return settings.evolution_api_url.rstrip("/")


def _headers() -> dict:
    return {
        "apikey": settings.evolution_api_key,
        "Content-Type": "application/json",
    }


def _instance() -> str:
    return settings.evolution_instance


async def _post(path: str, payload: dict) -> dict:
    url = f"{_base_url()}{path}/{_instance()}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def send_text(to: str, body: str) -> dict:
    return await _post("/message/sendText", {
        "number": to,
        "text": body,
    })


async def send_template(to: str, template_name: str, language: str = "pt_BR", components: list | None = None) -> dict:
    """Evolution API doesn't have Meta-style templates.
    Send as regular text message instead.
    """
    return await send_text(to, f"[Template: {template_name}]")


async def send_image(to: str, image_url: str, caption: str | None = None) -> dict:
    return await _post("/message/sendMedia", {
        "number": to,
        "mediatype": "image",
        "mimetype": "image/jpeg",
        "caption": caption or "",
        "media": image_url,
        "fileName": "image.jpg",
    })


async def send_audio(to: str, audio_url: str) -> dict:
    return await _post("/message/sendWhatsAppAudio", {
        "number": to,
        "audio": audio_url,
    })


async def mark_read(message_id: str, remote_jid: str) -> dict:
    """Mark a message as read in Evolution API."""
    return await _post("/chat/markMessageAsRead", {
        "readMessages": [
            {
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }
        ],
    })
