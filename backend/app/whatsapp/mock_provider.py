import json
import logging
import os
import time
from pathlib import Path

from app.whatsapp.base import WhatsAppProvider

logger = logging.getLogger(__name__)


def _log_entry(entry: dict) -> None:
    path = os.environ.get("REHEARSAL_LOG_PATH")
    if not path:
        return
    entry["timestamp"] = time.time()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class MockProvider(WhatsAppProvider):
    """WhatsApp provider stub used during REHEARSAL_MODE. Never sends real messages."""

    def __init__(self, config: dict):
        self.config = config or {}

    async def send_text(self, to: str, body: str) -> dict:
        logger.warning(f"[MOCK] send_text to={to} body={body[:60]!r}")
        _log_entry({"method": "send_text", "to": to, "body": body})
        return {"status": "mock_ok", "method": "send_text"}

    async def send_image(self, to: str, image_url: str, caption: str | None = None) -> dict:
        logger.warning(f"[MOCK] send_image to={to} url={image_url}")
        _log_entry({"method": "send_image", "to": to, "image_url": image_url, "caption": caption})
        return {"status": "mock_ok", "method": "send_image"}

    async def send_image_base64(self, to: str, base64_data: str, mimetype: str = "image/jpeg", caption: str | None = None) -> dict:
        logger.warning(f"[MOCK] send_image_base64 to={to} size={len(base64_data)}")
        _log_entry({
            "method": "send_image_base64",
            "to": to,
            "mimetype": mimetype,
            "caption": caption,
            "base64_size_bytes": len(base64_data),
        })
        return {"status": "mock_ok", "method": "send_image_base64"}

    async def send_audio(self, to: str, audio_url: str) -> dict:
        logger.warning(f"[MOCK] send_audio to={to} url={audio_url}")
        _log_entry({"method": "send_audio", "to": to, "audio_url": audio_url})
        return {"status": "mock_ok", "method": "send_audio"}

    async def send_template(self, to: str, template_name: str, components: dict | None = None, language_code: str = "pt_BR") -> dict:
        logger.warning(f"[MOCK] send_template to={to} template={template_name}")
        _log_entry({
            "method": "send_template",
            "to": to,
            "template_name": template_name,
            "components": components,
            "language_code": language_code,
        })
        return {"status": "mock_ok", "method": "send_template"}

    async def send_contact(self, to: str, contact_name: str, contact_phone: str) -> dict:
        logger.warning(f"[MOCK] send_contact to={to} contact={contact_name}/{contact_phone}")
        _log_entry({
            "method": "send_contact",
            "to": to,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
        })
        return {"status": "mock_ok", "method": "send_contact"}

    async def mark_read(self, message_id: str, remote_jid: str = "") -> dict:
        _log_entry({"method": "mark_read", "message_id": message_id})
        return {"status": "mock_ok", "method": "mark_read"}

    async def send_typing_indicator(self, to: str) -> dict:
        _log_entry({"method": "send_typing_indicator", "to": to})
        return {"status": "mock_ok", "method": "send_typing_indicator"}
