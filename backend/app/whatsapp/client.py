import httpx

from app.config import settings


def _base_url() -> str:
    return f"https://graph.facebook.com/{settings.meta_api_version}/{settings.meta_phone_number_id}/messages"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.meta_access_token}",
        "Content-Type": "application/json",
    }


async def _post(payload: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(_base_url(), json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def send_text(to: str, body: str) -> dict:
    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    })


async def send_template(to: str, template_name: str, language: str = "pt_BR", components: list | None = None) -> dict:
    template = {
        "name": template_name,
        "language": {"code": language},
    }
    if components:
        template["components"] = components

    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": template,
    })


async def send_image(to: str, image_url: str, caption: str | None = None) -> dict:
    image = {"link": image_url}
    if caption:
        image["caption"] = caption

    return await _post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image,
    })


async def mark_read(message_id: str) -> dict:
    return await _post({
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    })
