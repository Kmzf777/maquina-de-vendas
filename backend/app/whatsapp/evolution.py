import httpx
from app.whatsapp.base import WhatsAppClient


class EvolutionClient(WhatsAppClient):
    def __init__(self, api_url: str, api_key: str, instance: str):
        self.base_url = api_url.rstrip("/")
        self.api_key = api_key
        self.instance = instance

    def _headers(self) -> dict:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}/{self.instance}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def send_text(self, to: str, body: str) -> dict:
        return await self._post("/message/sendText", {
            "number": to,
            "text": body,
        })

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        return await self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "caption": caption or "",
            "media": image_url,
            "fileName": "image.jpg",
        })

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        return await self._post("/message/sendMedia", {
            "number": to,
            "mediatype": "image",
            "mimetype": mimetype,
            "caption": caption or "",
            "media": base64_data,
            "fileName": "image.jpg" if "jpeg" in mimetype else "image.png",
        })

    async def send_audio(self, to: str, audio_url: str) -> dict:
        return await self._post("/message/sendWhatsAppAudio", {
            "number": to,
            "audio": audio_url,
        })

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post("/chat/markMessageAsRead", {
            "readMessages": [{
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }],
        })
