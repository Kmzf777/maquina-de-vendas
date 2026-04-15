import httpx

from app.providers.base import WhatsAppProvider

# Explicit timeouts: 5s connect, 30s read (media downloads can be large)
HTTPX_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class EvolutionProvider(WhatsAppProvider):
    """Evolution API provider."""

    def _base_url(self) -> str:
        return self.config["api_url"].rstrip("/")

    def _headers(self) -> dict:
        return {
            "apikey": self.config["api_key"],
            "Content-Type": "application/json",
        }

    def _instance(self) -> str:
        return self.config["instance"]

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._base_url()}{path}/{self._instance()}"
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post("/message/sendText", {
            "number": to,
            "text": body,
        })

    async def send_template(self, to: str, template_name: str,
                            language: str = "pt_BR",
                            components: list | None = None) -> dict:
        raise NotImplementedError(
            "Evolution API does not support Meta-style templates. "
            "Campaigns require a Meta Cloud API channel."
        )

    async def send_image(self, to: str, image_url: str,
                         caption: str | None = None) -> dict:
        return await self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "caption": caption or "",
            "media": image_url,
            "fileName": "image.jpg",
        })

    async def mark_read(self, message_id: str, **kwargs) -> dict:
        remote_jid = kwargs.get("remote_jid", "")
        return await self._post("/chat/markMessageAsRead", {
            "readMessages": [{
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }],
        })

    async def download_media(self, media_ref: str) -> tuple[bytes, str]:
        """Download media from URL. media_ref is the direct URL for Evolution."""
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.get(media_ref)
            resp.raise_for_status()
            return resp.content, resp.headers.get(
                "content-type", "application/octet-stream"
            )
