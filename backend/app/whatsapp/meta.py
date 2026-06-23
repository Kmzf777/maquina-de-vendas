import asyncio
import base64
import json
import logging
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from app.whatsapp.base import WhatsAppProvider
from app.meta_audit import log_outbound

META_API_BASE = "https://graph.facebook.com"

# A1 — robustez de envio à Meta:
# timeout explícito + cliente compartilhado (pool/keep-alive) + retry com backoff.
META_REQUEST_TIMEOUT = 15.0
META_MAX_ATTEMPTS = 4  # 1 tentativa inicial + 3 retries
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

logger = logging.getLogger(__name__)

# Instância única compartilhada: reusa conexões TLS (keep-alive) em vez de abrir
# um AsyncClient novo por chamada. Criado preguiçosamente para permitir patch em testes.
_shared_client: httpx.AsyncClient | None = None


def get_shared_client() -> httpx.AsyncClient:
    """Retorna o AsyncClient compartilhado (pool/keep-alive, timeout explícito)."""
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=httpx.Timeout(META_REQUEST_TIMEOUT),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _shared_client


async def close_shared_client() -> None:
    """Fecha o cliente compartilhado (chamar no shutdown da app)."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


def _parse_retry_after(value: str | None) -> float | None:
    """Interpreta o header Retry-After (segundos OU HTTP-date). None se ausente/inválido."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        dt = parsedate_to_datetime(value)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def _backoff_delay(attempt: int, retry_after: float | None) -> float:
    """Honra Retry-After quando presente; senão backoff exponencial com jitter (cap 60s)."""
    if retry_after is not None:
        return min(retry_after, 60.0)
    return min(0.5 * (2 ** attempt) + random.uniform(0, 0.3), 60.0)


async def _request_with_retry(
    method: str, url: str, *, max_attempts: int = META_MAX_ATTEMPTS, **kwargs
) -> httpx.Response:
    """POST/GET via cliente compartilhado, com retry em 429/5xx e erros de transporte.

    Retorna a Response final (mesmo que de erro após esgotar retries) — o chamador
    decide o tratamento (raise_for_status). Erros de transporte são re-levantados
    após a última tentativa.
    """
    client = get_shared_client()
    for attempt in range(max_attempts):
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt >= max_attempts - 1:
                raise
            delay = _backoff_delay(attempt, None)
            logger.warning(
                "[Meta API] erro de transporte (tentativa %d/%d): %s — retry em %.2fs",
                attempt + 1, max_attempts, exc, delay,
            )
            await asyncio.sleep(delay)
            continue

        if resp.status_code in _RETRYABLE_STATUS and attempt < max_attempts - 1:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            delay = _backoff_delay(attempt, retry_after)
            logger.warning(
                "[Meta API] status %s (tentativa %d/%d) — retry em %.2fs",
                resp.status_code, attempt + 1, max_attempts, delay,
            )
            await asyncio.sleep(delay)
            continue

        return resp

    raise RuntimeError("unreachable: retry loop esgotado sem resposta")


def extract_wamid(send_result: dict | None) -> str | None:
    """Extrai o wamid da resposta de send_text/send_template da Meta.

    A Meta retorna {"messages": [{"id": "wamid...."}], ...}. Devolve None para
    qualquer outro formato (providers Mock/Evolution, envelopes de erro) para que
    o chamador possa persistir wamid=None sem quebrar. Sem isso, citações (reply)
    a mensagens da Valéria ficam irresolvíveis no frontend.
    """
    if not isinstance(send_result, dict):
        return None
    messages = send_result.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    first = messages[0]
    if not isinstance(first, dict):
        return None
    return first.get("id")


class MetaCloudClient(WhatsAppProvider):
    def __init__(self, config: dict):
        self.phone_number_id = config.get("phone_number_id") or ""
        self.access_token = config.get("access_token") or ""
        if not self.phone_number_id:
            raise ValueError("Canal Meta Cloud sem phone_number_id configurado")
        if not self.access_token:
            raise ValueError("Canal Meta Cloud sem access_token configurado")
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

    async def _post(self, payload: dict, request_type: str = "api_call") -> dict:
        response_data: dict | None = None
        status_code: int | None = None
        success = False
        error_msg: str | None = None

        try:
            resp = await _request_with_retry(
                "POST", self._url(), json=payload, headers=self._headers()
            )
            status_code = resp.status_code
            try:
                response_data = resp.json()
            except Exception:
                response_data = {"raw": resp.text}

            if not resp.is_success:
                error_msg = json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)
                logger.error(
                    "[Meta API] %s %s — payload: %s — response: %s",
                    resp.status_code,
                    resp.reason_phrase,
                    json.dumps(payload),
                    error_msg,
                )
            else:
                success = True

            resp.raise_for_status()
            return response_data
        except Exception as exc:
            if error_msg is None:
                error_msg = str(exc)
            raise
        finally:
            log_outbound(
                endpoint=self._url(),
                http_method="POST",
                request_type=request_type,
                payload=payload,
                response=response_data,
                status_code=status_code,
                success=success,
                to_number=payload.get("to"),
                phone_number_id=self.phone_number_id,
                error_message=error_msg,
            )

    async def send_text(self, to: str, body: str) -> dict:
        result = await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }, request_type="send_text")
        # Meta Graph API can return HTTP 200 with an embedded error object.
        # A real acceptance always contains "messages" with at least one wamid.
        if not isinstance(result, dict) or "messages" not in result:
            raise RuntimeError(
                f"Meta send_text rejected (missing messages in response): {result!r}"
            )
        return result

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        payload: dict = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        return await self._post(payload, request_type="send_image")

    async def upload_media(self, image_bytes: bytes, mimetype: str) -> str:
        """Upload image bytes to Meta Media API and return the media_id."""
        response_data: dict | None = None
        status_code: int | None = None
        success = False
        error_msg: str | None = None

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._media_url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    files={"file": ("image", image_bytes, mimetype)},
                    data={"messaging_product": "whatsapp", "type": mimetype},
                )
                status_code = resp.status_code
                try:
                    response_data = resp.json()
                except Exception:
                    response_data = {"raw": resp.text}

                if not resp.is_success:
                    error_msg = json.dumps(response_data) if isinstance(response_data, dict) else str(response_data)
                    logger.error(
                        "[Meta API] Media upload failed %s %s — mimetype: %s — response: %s",
                        resp.status_code, resp.reason_phrase, mimetype, error_msg,
                    )
                else:
                    success = True

                resp.raise_for_status()
                return response_data["id"]
        except Exception as exc:
            if error_msg is None:
                error_msg = str(exc)
            raise
        finally:
            log_outbound(
                endpoint=self._media_url,
                http_method="POST",
                request_type="upload_media",
                payload={"messaging_product": "whatsapp", "type": mimetype},
                response=response_data,
                status_code=status_code,
                success=success,
                phone_number_id=self.phone_number_id,
                error_message=error_msg,
            )

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
        return await self._post(payload, request_type="send_image_bytes")

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        image_bytes = base64.b64decode(base64_data)
        return await self.send_image_bytes(to, image_bytes, mimetype, caption=caption)

    async def send_audio(self, to: str, audio_url: str) -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        }, request_type="send_audio")

    async def send_contact(self, to: str, contact_name: str, contact_phone: str) -> dict:
        """Envia um cartão de contato (vCard) via mensagem tipo `contacts` da Meta."""
        digits = "".join(ch for ch in contact_phone if ch.isdigit())
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "contacts",
            "contacts": [
                {
                    "name": {"formatted_name": contact_name, "first_name": contact_name},
                    "phones": [
                        {"phone": f"+{digits}", "wa_id": digits, "type": "WORK"}
                    ],
                }
            ],
        }
        result = await self._post(payload, request_type="send_contact")
        # Meta pode retornar HTTP 200 com erro embutido — aceite real tem "messages".
        if not isinstance(result, dict) or "messages" not in result:
            raise RuntimeError(
                f"Meta send_contact rejected (missing messages in response): {result!r}"
            )
        return result

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
        result = await self._post(payload, request_type="send_template")
        # Meta can return HTTP 200 with an embedded error object — same caveat as send_text.
        # A real acceptance always contains "messages" with at least one wamid.
        if not isinstance(result, dict) or "messages" not in result:
            raise RuntimeError(
                f"Meta send_template rejected (missing messages in response): {result!r}"
            )
        return result

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media from Meta using media_id. Returns (bytes, content_type)."""
        info_endpoint = f"{META_API_BASE}/{self.api_version}/{media_id}"
        info_status: int | None = None
        info_success = False
        info_response: dict | None = None
        info_error: str | None = None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: resolve media_id → temporary download URL
                info_resp = await client.get(
                    info_endpoint,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
                info_status = info_resp.status_code
                try:
                    info_response = info_resp.json()
                except Exception:
                    info_response = {"raw": info_resp.text}
                info_resp.raise_for_status()
                info_success = True

                download_url = info_response["url"]
                mime_type = info_response.get("mime_type", "audio/ogg")

                # Step 2: download bytes with Bearer token
                audio_resp = await client.get(
                    download_url,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
                audio_resp.raise_for_status()
                return audio_resp.content, mime_type
        except Exception as exc:
            if not info_success:
                info_error = str(exc)
            raise
        finally:
            log_outbound(
                endpoint=info_endpoint,
                http_method="GET",
                request_type="download_media",
                payload={"media_id": media_id},
                response=info_response,
                status_code=info_status,
                success=info_success,
                phone_number_id=self.phone_number_id,
                error_message=info_error,
            )

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        return await self._post({
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }, request_type="mark_read")

    async def send_typing_indicator(self, to: str) -> dict:
        """Mostra o indicador "digitando…" ao lead (payload STANDALONE, Cloud API v18+).

        DESACOPLADO do read receipt. O combo status=read + message_id + typing_indicator
        sofre idempotência: re-enviar na MESMA mensagem (já marcada como lida) é descartado
        pela Meta, então a renovação do "digitando…" entre balões some da tela. O payload
        avulso por `to` (type=typing_indicator) pode ser re-pulsado quantas vezes for preciso
        sem ser deduplicado — cada pulso renova os ~25s do indicador. O mark_read continua
        separado (disparado uma vez no início do turno via mark_read()).
        """
        return await self._post({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "typing_indicator",
            "typing_indicator": {"type": "text"},
        }, request_type="typing_on")
