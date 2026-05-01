import base64
import json
import logging
import httpx
from app.whatsapp.base import WhatsAppProvider

META_API_BASE = "https://graph.facebook.com"

logger = logging.getLogger(__name__)


class MetaCloudClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.phone_number_id = config["phone_number_id"]
        self.access_token = config["access_token"]
        self.api_version = config.get("api_version", "v21.0")
        self._messages_url = f"{META_API_BASE}/{self.api_version}/{self.phone_number_id}/messages"
        self._media_url = f"{META_API_BASE}/{self.api_version}/{self.phone_number_id}/media"

    def _url(self) -> str:
        return self._messages_url

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

    async def upload_media(self, image_bytes: bytes, mimetype: str) -> str:
        """Upload image bytes to Meta Media API and return the media_id."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._media_url,
                headers={"Authorization": f"Bearer {self.access_token}"},
                files={"file": ("image", image_bytes, mimetype)},
                data={"messaging_product": "whatsapp", "type": mimetype},
            )
            if not resp.is_success:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text
                logger.error(
                    "[Meta API] Media upload failed %s %s — mimetype: %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    mimetype,
                    json.dumps(error_body) if isinstance(error_body, dict) else error_body,
                )
            resp.raise_for_status()
            return resp.json()["id"]

    async def send_image_bytes(self, to: str, image_bytes: bytes, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        """Upload image to Meta and send via media_id (required — Meta rejects data: URIs)."""
        media_id = await self.upload_media(image_bytes, mimetype)
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"id": media_id},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload)

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        image_bytes = base64.b64decode(base64_data)
        return await self.send_image_bytes(to, image_bytes, mimetype, caption=caption)

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

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media from Meta using media_id. Returns (bytes, content_type)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: resolve media_id → temporary download URL
            info_resp = await client.get(
                f"{META_API_BASE}/{self.api_version}/{media_id}",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            info_resp.raise_for_status()
            info = info_resp.json()
            download_url = info["url"]
            mime_type = info.get("mime_type", "audio/ogg")

            # Step 2: download bytes with Bearer token
            audio_resp = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            audio_resp.raise_for_status()
            return audio_resp.content, mime_type

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })
