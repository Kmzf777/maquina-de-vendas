from dataclasses import dataclass


@dataclass
class IncomingMessage:
    from_number: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, interactive, button
    text: str | None = None
    media_id: str | None = None
    media_mime: str | None = None


def parse_webhook_payload(payload: dict) -> list[IncomingMessage]:
    messages = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            for msg in value.get("messages", []):
                msg_type = msg.get("type", "")
                text = None
                media_id = None
                media_mime = None

                if msg_type == "text":
                    text = msg.get("text", {}).get("body")

                elif msg_type in ("image", "audio", "video", "document"):
                    media_obj = msg.get(msg_type, {})
                    media_id = media_obj.get("id")
                    media_mime = media_obj.get("mime_type")
                    text = media_obj.get("caption")

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        text = interactive.get("button_reply", {}).get("title")
                    elif interactive.get("type") == "list_reply":
                        text = interactive.get("list_reply", {}).get("title")

                elif msg_type == "button":
                    text = msg.get("button", {}).get("text")

                messages.append(IncomingMessage(
                    from_number=msg["from"],
                    message_id=msg["id"],
                    timestamp=msg.get("timestamp", ""),
                    type=msg_type,
                    text=text,
                    media_id=media_id,
                    media_mime=media_mime,
                ))

    return messages
