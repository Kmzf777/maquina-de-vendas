import httpx

from app.providers.base import WhatsAppProvider


class MetaCloudProvider(WhatsAppProvider):
    """Meta WhatsApp Cloud API provider."""

    def _base_url(self) -> str:
        version = self.config.get("api_version", "v21.0")
        phone_number_id = self.config["phone_number_id"]
        return f"https://graph.facebook.com/{version}/{phone_number_id}/messages"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.config['access_token']}",
            "Content-Type": "application/json",
        }

    def _media_base_url(self) -> str:
        version = self.config.get("api_version", "v21.0")
        return f"https://graph.facebook.com/{version}"

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._base_url(), json=payload, headers=self._headers()
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

    async def send_template(self, to: str, template_name: str,
                            language: str = "pt_BR",
                            components: list | None = None) -> dict:
        template = {
            "name": template_name,
            "language": {"code": language},
        }
        if components:
            template["components"] = components

        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        })

    async def send_image(self, to: str, image_url: str,
                         caption: str | None = None) -> dict:
        image = {"link": image_url}
        if caption:
            image["caption"] = caption

        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": image,
        })

    async def mark_read(self, message_id: str, **kwargs) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        })

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """Download media from Meta. media_ref is the media_id."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._media_base_url()}/{media_ref}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            media_url = resp.json()["url"]

            resp = await client.get(media_url, headers=self._headers())
            resp.raise_for_status()
            return resp.content, resp.headers.get(
                "content-type", "application/octet-stream"
            )
