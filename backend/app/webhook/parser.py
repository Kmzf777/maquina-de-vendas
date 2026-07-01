from dataclasses import dataclass


@dataclass
class IncomingMessage:
    from_number: str
    remote_jid: str
    message_id: str
    timestamp: str
    type: str  # text, image, audio, video, document
    text: str | None = None
    media_url: str | None = None
    media_mime: str | None = None
    push_name: str | None = None
    channel_id: str | None = None
    document_name: str | None = None
    metadata: dict | None = None
    quoted_wamid: str | None = None  # wamid of the message being replied to
    ctwa_clid: str | None = None  # Click-to-WhatsApp click id (Meta Ads referral) — base p/ CAPI
    ctwa_origem: str | None = None  # Origem do funil derivada do referral CTWA (atacado/terceirizacao)
    bsuid: str | None = None       # Business-Scoped User ID (from_user_id) — fallback identity
    username: str | None = None    # WhatsApp username (contacts.profile.username), if adopted


def parse_webhook_payload(payload: dict) -> list[IncomingMessage]:
    """Parse Evolution API v2 MESSAGES_UPSERT webhook payload."""
    messages = []

    event = payload.get("event", "")
    if event != "messages.upsert":
        return messages

    data = payload.get("data", {})
    key = data.get("key", {})

    # Skip messages from ourselves
    if key.get("fromMe", False):
        return messages

    remote_jid = key.get("remoteJid", "")
    # Extract phone number from JID (5534999999999@s.whatsapp.net -> 5534999999999)
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

    # Text messages
    if message_type == "conversation":
        text = message_data.get("conversation")
    elif message_type == "extendedTextMessage":
        text = message_data.get("extendedTextMessage", {}).get("text")

    # Audio messages
    elif message_type == "audioMessage":
        msg_type = "audio"
        audio = message_data.get("audioMessage", {})
        media_url = audio.get("url")
        media_mime = audio.get("mimetype")

    # Image messages
    elif message_type == "imageMessage":
        msg_type = "image"
        image = message_data.get("imageMessage", {})
        media_url = image.get("url")
        media_mime = image.get("mimetype")
        text = image.get("caption")

    # Video messages
    elif message_type == "videoMessage":
        msg_type = "video"
        video = message_data.get("videoMessage", {})
        media_url = video.get("url")
        media_mime = video.get("mimetype")
        text = video.get("caption")

    # Document messages
    elif message_type == "documentMessage":
        msg_type = "document"
        doc = message_data.get("documentMessage", {})
        media_url = doc.get("url")
        media_mime = doc.get("mimetype")
        text = doc.get("caption")

    else:
        # Unknown type - try to extract any text
        text = message_data.get("conversation") or message_data.get("extendedTextMessage", {}).get("text")
        if not text:
            return messages  # Skip unknown non-text messages

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


def webhook_identity(msg: "IncomingMessage") -> str:
    """Canonical routing key for a message: phone if present, else the BSUID.

    Meta omits the phone number once a user adopts a username, sending only the
    BSUID. This helper gives every consumer a single non-empty identity to key on.
    """
    return msg.from_number or (msg.bsuid or "")
