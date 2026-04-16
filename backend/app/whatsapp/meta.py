import json
import logging
import httpx
from app.whatsapp.base import WhatsAppProvider

META_API_BASE = "https://graph.facebook.com/v21.0"

logger = logging.getLogger(__name__)


class MetaCloudClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.phone_number_id = config["phone_number_id"]
        self.access_token = config["access_token"]

    def _url(self) -> str:
        return f"{META_API_BASE}/{self.phone_number_id}/messages"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url(), json=payload, headers=self._headers())
            if not resp.is_success:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text
                logger.error(
                    "[Meta API] %s %s — payload: %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    json.dumps(payload),
                    json.dumps(error_body) if isinstance(error_body, dict) else error_body,
                )
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        })

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload)

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        data_url = f"data:{mimetype};base64,{base64_data}"
        return await self.send_image(to, data_url, caption)

    async def send_audio(self, to: str, audio_url: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        })

    async def send_template(self, to: str, template_name: str, components: list | None = None, language_code: str = "pt_BR") -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            }
        }
        if components:
            payload["template"]["components"] = components
        return await self._post(payload)

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })
