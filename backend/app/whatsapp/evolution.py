import json
import httpx
from app.whatsapp.base import WhatsAppProvider
from app.meta_audit import log_outbound


class EvolutionClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.base_url = config["api_url"].rstrip("/")
        self.api_key = config["api_key"]
        self.instance = config["instance"]

    def _headers(self) -> dict:
        return {"apikey": self.api_key, "Content-Type": "application/json"}

    async def _post(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}/{self.instance}"
        response_data: dict | None = None
        status_code: int | None = None
        success = False
        error_msg: str | None = None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                status_code = resp.status_code
                try:
                    response_data = resp.json()
                except Exception:
                    response_data = {"raw": resp.text}
                if not resp.is_success:
                    error_msg = json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)
                else:
                    success = True
                resp.raise_for_status()
                return response_data
        except Exception:
            raise
        finally:
            log_outbound(
                endpoint=url,
                http_method="POST",
                request_type=path.split("/")[-1] if "/" in path else path,
                payload=payload,
                response=response_data,
                status_code=status_code,
                success=success,
                to_number=payload.get("number"),
                phone_number_id=None,
                error_message=error_msg,
            )

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

    async def send_image_base64(
        self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None
    ) -> dict:
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

    async def send_template(self, to: str, template_name: str, components: dict | None = None, language_code: str = "pt_BR") -> dict:
        payload = {
            "number": to,
            "template": {
                "name": template_name,
            }
        }
        if components:
            payload["template"]["components"] = components
        return await self._post("/message/sendTemplate", payload)

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post("/chat/markMessageAsRead", {
            "readMessages": [{
                "id": message_id,
                "fromMe": False,
                "remoteJid": remote_jid,
            }],
        })
