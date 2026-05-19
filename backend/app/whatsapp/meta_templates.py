import logging
import httpx

from app.meta_audit import log_outbound

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
        response_data: dict | None = None
        status_code: int | None = None
        success = False
        error_msg: str | None = None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload, headers=self._headers())
                status_code = resp.status_code
                try:
                    response_data = resp.json()
                except Exception:
                    response_data = {"raw": resp.text}

                if not resp.is_success:
                    error_msg = str(response_data)
                    logger.error(
                        "[Meta Templates] %s %s — payload: %s — response: %s",
                        resp.status_code, resp.reason_phrase, payload, error_msg,
                    )
                    raise httpx.HTTPStatusError(
                        message=error_msg,
                        request=resp.request,
                        response=resp,
                    )

                success = True
                return response_data
        except Exception:
            raise
        finally:
            log_outbound(
                endpoint=url,
                http_method="POST",
                request_type="create_template",
                payload=payload,
                response=response_data,
                status_code=status_code,
                success=success,
                error_message=error_msg,
            )

    async def delete_template(self, template_name: str, meta_template_id: str | None = None) -> None:
        url = f"{META_API_BASE}/{self.waba_id}/message_templates"
        params: dict = {"name": template_name}
        if meta_template_id:
            params["hsm_id"] = meta_template_id

        response_data: dict | None = None
        status_code: int | None = None
        success = False
        error_msg: str | None = None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.delete(url, params=params, headers=self._headers())
                status_code = resp.status_code
                try:
                    response_data = resp.json()
                except Exception:
                    response_data = {"raw": resp.text}

                if not resp.is_success:
                    error_msg = str(response_data)
                    logger.error(
                        "[Meta Templates] DELETE failed %s — template: %s",
                        resp.status_code, template_name,
                    )
                else:
                    success = True

                resp.raise_for_status()
        except Exception:
            raise
        finally:
            log_outbound(
                endpoint=url,
                http_method="DELETE",
                request_type="delete_template",
                payload=params,
                response=response_data,
                status_code=status_code,
                success=success,
                error_message=error_msg,
            )
