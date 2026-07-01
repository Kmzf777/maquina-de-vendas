import logging
from urllib.parse import urlparse

from app.webhook.parser import IncomingMessage

logger = logging.getLogger(__name__)


def origem_from_referral(referral: dict | None) -> str | None:
    """Deriva a origem do funil a partir do `referral` de um anúncio CTWA (Opção B).

    Casa por substring no PATH do source_url + headline + body. Importante: as LPs vivem
    todas no domínio `atacado.cafecanastra.com`, então o domínio contém 'atacado' mesmo na
    página de terceirização — por isso só o PATH (/cafeatacado, /terceirizacaocafe) entra no
    haystack, nunca o domínio. 'terceiriza' é checado primeiro como desempate quando o
    criativo cita ambos. Mesmo vocabulário de `_resolve_lp_pipeline` (scheduler).
    Origem desconhecida → None. Depende do anúncio ser Click-to-WhatsApp (Meta envia referral).
    """
    if not referral:
        return None
    source_url = str(referral.get("source_url", ""))
    path = urlparse(source_url).path if source_url else ""
    haystack = " ".join([path, str(referral.get("headline", "")), str(referral.get("body", ""))]).lower()
    if "terceiriza" in haystack:
        return "terceirizacao"
    if "atacado" in haystack:
        return "atacado"
    return None


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
                bsuid = msg.get("from_user_id")
                message_id = msg.get("id", "")
                timestamp = msg.get("timestamp", "")
                msg_type = msg.get("type", "")

                contacts = value.get("contacts", [])
                push_name = None
                username = None
                if contacts:
                    profile = contacts[0].get("profile", {})
                    push_name = profile.get("name")
                    username = profile.get("username")
                    # Fallback BSUID from the contacts block if the message lacked from_user_id.
                    if not bsuid:
                        bsuid = contacts[0].get("user_id")

                text = None
                media_url = None
                media_mime = None
                document_name = None
                metadata_dict = None
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
                    document_name = doc.get("filename")

                elif msg_type == "sticker":
                    parsed_type = "sticker"
                    sticker = msg.get("sticker", {})
                    media_url = sticker.get("id")
                    media_mime = sticker.get("mime_type")

                elif msg_type == "location":
                    parsed_type = "location"
                    loc = msg.get("location", {})
                    metadata_dict = {
                        "lat": loc.get("latitude"),
                        "lng": loc.get("longitude"),
                        "name": loc.get("name", ""),
                        "address": loc.get("address", ""),
                    }

                elif msg_type == "contacts":
                    parsed_type = "contact"
                    contacts_list = msg.get("contacts", [])
                    if contacts_list:
                        c = contacts_list[0]
                        name_obj = c.get("name", {})
                        phones = c.get("phones", [])
                        metadata_dict = {
                            "name": name_obj.get("formatted_name", ""),
                            "phone": phones[0].get("phone", "") if phones else "",
                            "vcard": c.get("vcard", ""),
                        }

                elif msg_type == "reaction":
                    parsed_type = "reaction"
                    reaction = msg.get("reaction", {})
                    metadata_dict = {
                        "emoji": reaction.get("emoji", ""),
                        "target_wamid": reaction.get("message_id", ""),
                    }

                elif msg_type == "button":
                    # Quick reply clicked on a template message
                    text = msg.get("button", {}).get("text", "")
                    parsed_type = "text"

                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    interactive_type = interactive.get("type", "")
                    if interactive_type == "button_reply":
                        text = interactive.get("button_reply", {}).get("title", "")
                        parsed_type = "text"
                    elif interactive_type == "list_reply":
                        text = interactive.get("list_reply", {}).get("title", "")
                        parsed_type = "text"
                    else:
                        logger.info(f"Skipping unsupported interactive sub-type: {interactive_type}")
                        continue

                else:
                    logger.info(f"Skipping unsupported Meta message type: {msg_type}")
                    continue

                quoted_wamid: str | None = msg.get("context", {}).get("id")

                # Click-to-WhatsApp (CTWA): mensagens originadas de um anúncio Meta Ads
                # trazem um objeto `referral` aninhado com o `ctwa_clid` (click id) usado
                # depois pela API de Conversões (CAPI) e a origem do funil (source_url do
                # criativo). Extração defensiva: mensagens orgânicas não têm `referral`.
                referral: dict = msg.get("referral") or {}
                ctwa_clid: str | None = referral.get("ctwa_clid")
                ctwa_origem: str | None = origem_from_referral(referral)

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
                    document_name=document_name,
                    metadata=metadata_dict,
                    quoted_wamid=quoted_wamid,
                    ctwa_clid=ctwa_clid,
                    ctwa_origem=ctwa_origem,
                    bsuid=bsuid,
                    username=username,
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
