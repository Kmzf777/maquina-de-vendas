import logging
from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)


def parse_meta_webhook_payload(payload: dict) -> list[IncomingMessage]:
    """Parse Meta Cloud API webhook payload into IncomingMessage list."""
    messages = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            if value.get("messaging_product") != "whatsapp":
                continue

            metadata = value.get("metadata", {})
            display_phone = metadata.get("display_phone_number", "")

            for msg in value.get("messages", []):
                from_number = msg.get("from", "")
                message_id = msg.get("id", "")
                timestamp = msg.get("timestamp", "")
                msg_type = msg.get("type", "")

                contacts = value.get("contacts", [])
                push_name = None
                if contacts:
                    profile = contacts[0].get("profile", {})
                    push_name = profile.get("name")

                text = None
                media_url = None
                media_mime = None
                parsed_type = "text"

                if msg_type == "text":
                    text = msg.get("text", {}).get("body")

                elif msg_type == "image":
                    parsed_type = "image"
                    image = msg.get("image", {})
                    media_url = image.get("id")
                    media_mime = image.get("mime_type")
                    text = image.get("caption")

                elif msg_type == "audio":
                    parsed_type = "audio"
                    audio = msg.get("audio", {})
                    media_url = audio.get("id")
                    media_mime = audio.get("mime_type")

                elif msg_type == "video":
                    parsed_type = "video"
                    video = msg.get("video", {})
                    media_url = video.get("id")
                    media_mime = video.get("mime_type")
                    text = video.get("caption")

                elif msg_type == "document":
                    parsed_type = "document"
                    doc = msg.get("document", {})
                    media_url = doc.get("id")
                    media_mime = doc.get("mime_type")
                    text = doc.get("caption")

                else:
                    logger.info(f"Skipping unsupported Meta message type: {msg_type}")
                    continue

                messages.append(IncomingMessage(
                    from_number=from_number,
                    remote_jid="",
                    message_id=message_id,
                    timestamp=timestamp,
                    type=parsed_type,
                    text=text,
                    media_url=media_url,
                    media_mime=media_mime,
                    push_name=push_name,
                ))

    return messages


def extract_phone_number_id(payload: dict) -> str | None:
    """Extract the phone_number_id from a Meta webhook payload."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")
            if phone_number_id:
                return phone_number_id
    return None
