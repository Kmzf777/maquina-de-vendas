from dataclasses import dataclass


@dataclass
class IncomingMessage:
    from_number: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, interactive, button, video, document
    channel_id: str = ""
    text: str | None = None
    media_id: str | None = None
    media_url: str | None = None
    media_mime: str | None = None
    remote_jid: str | None = None
    push_name: str | None = None


def parse_meta_webhook(payload: dict) -> tuple[list[IncomingMessage], str | None]:
    """Parse Meta Cloud API webhook payload.
    Returns (messages, phone_number_id) so caller can resolve channel.
    """
    messages = []
    phone_number_id = None

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id")

            # Build wa_id → display name map from contacts array
            contacts = {
                c["wa_id"]: c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
            }

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

                from_number = msg["from"]
                messages.append(IncomingMessage(
                    from_number=from_number,
                    message_id=msg["id"],
                    timestamp=msg.get("timestamp", ""),
                    type=msg_type,
                    text=text,
                    media_id=media_id,
                    media_mime=media_mime,
                    push_name=contacts.get(from_number),
                ))

    return messages, phone_number_id


def parse_evolution_webhook(payload: dict) -> list[IncomingMessage]:
    """Parse Evolution API v2 MESSAGES_UPSERT webhook payload."""
    messages = []

    event = payload.get("event", "")
    if event != "messages.upsert":
        return messages

    data = payload.get("data", {})
    key = data.get("key", {})

    if key.get("fromMe", False):
        return messages

    remote_jid = key.get("remoteJid", "")
    from_number = remote_jid.split("@")[0] if "@" in remote_jid else remote_jid

    message_id = key.get("id", "")
    timestamp = str(data.get("messageTimestamp", ""))
    push_name = data.get("pushName")
    message_type = data.get("messageType", "")
    message_data = data.get("message", {})

    text = None
    media_url = None
    media_mime = None
    msg_type = "text"

    if message_type == "conversation":
        text = message_data.get("conversation")
    elif message_type == "extendedTextMessage":
        text = message_data.get("extendedTextMessage", {}).get("text")
    elif message_type == "audioMessage":
        msg_type = "audio"
        audio = message_data.get("audioMessage", {})
        media_url = audio.get("url")
        media_mime = audio.get("mimetype")
    elif message_type == "imageMessage":
        msg_type = "image"
        image = message_data.get("imageMessage", {})
        media_url = image.get("url")
        media_mime = image.get("mimetype")
        text = image.get("caption")
    elif message_type == "videoMessage":
        msg_type = "video"
        video = message_data.get("videoMessage", {})
        media_url = video.get("url")
        media_mime = video.get("mimetype")
        text = video.get("caption")
    elif message_type == "documentMessage":
        msg_type = "document"
        doc = message_data.get("documentMessage", {})
        media_url = doc.get("url")
        media_mime = doc.get("mimetype")
        text = doc.get("caption")
    else:
        text = (
            message_data.get("conversation")
            or message_data.get("extendedTextMessage", {}).get("text")
        )
        if not text:
            return messages

    messages.append(IncomingMessage(
        from_number=from_number,
        remote_jid=remote_jid,
        message_id=message_id,
        timestamp=timestamp,
        type=msg_type,
        text=text,
        media_url=media_url,
        media_mime=media_mime,
        push_name=push_name,
    ))

    return messages
