import logging
import httpx

META_API_BASE = "https://graph.facebook.com/v21.0"
logger = logging.getLogger(__name__)


class MetaTemplateClient:
    def __init__(self, waba_id: str, access_token: str):
        self.waba_id = waba_id
        self.access_token = access_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    async def create_template(self, payload: dict) -> dict:
        url = f"{META_API_BASE}/{self.waba_id}/message_templates"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers())
            if not resp.is_success:
                try:
                    error_body = resp.json()
                except Exception:
                    error_body = resp.text
                logger.error(
                    "[Meta Templates] %s %s — payload: %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    payload,
                    error_body,
                )
            resp.raise_for_status()
            return resp.json()

    async def delete_template(self, template_name: str, meta_template_id: str | None = None) -> None:
        url = f"{META_API_BASE}/{self.waba_id}/message_templates"
        params: dict = {"name": template_name}
        if meta_template_id:
            params["hsm_id"] = meta_template_id
        async with httpx.AsyncClient() as client:
            resp = await client.delete(url, params=params, headers=self._headers())
            if not resp.is_success:
                logger.error(
                    "[Meta Templates] DELETE failed %s — template: %s",
                    resp.status_code,
                    template_name,
                )
            resp.raise_for_status()
