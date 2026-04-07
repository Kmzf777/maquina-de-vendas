"""
MVP - Integração Meta WhatsApp Cloud API
Fluxo: recebe webhook → salva no Supabase → responde automaticamente
Sem Redis, sem OpenAI.
"""
import logging
import os

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request, Response
from supabase import create_client

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_PHONE_NUMBER_ID = os.environ["META_PHONE_NUMBER_ID"]
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "canastra_webhook_verify")
META_API_VERSION = "v25.0"

AUTO_REPLY = (
    "Olá! Recebemos sua mensagem e em breve nossa equipe entrará em contato. 😊"
)

# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Canastra MVP")


# ---------------------------------------------------------------------------
# Helpers — Supabase
# ---------------------------------------------------------------------------
def get_or_create_lead(phone: str, name: str | None = None) -> dict:
    result = sb.table("leads").select("*").eq("phone", phone).execute()
    if result.data:
        lead = result.data[0]
        if name and not lead.get("name"):
            result = sb.table("leads").update({"name": name}).eq("id", lead["id"]).execute()
            return result.data[0]
        return lead
    new_lead = {"phone": phone}
    if name:
        new_lead["name"] = name
    return sb.table("leads").insert(new_lead).execute().data[0]


def save_message(lead_id: str, role: str, content: str) -> None:
    sb.table("messages").insert(
        {"lead_id": lead_id, "role": role, "content": content}
    ).execute()


# ---------------------------------------------------------------------------
# Helper — Meta API
# ---------------------------------------------------------------------------
async def send_meta_text(to: str, body: str) -> None:
    url = (
        f"https://graph.facebook.com/{META_API_VERSION}"
        f"/{META_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    headers = {
        "Authorization": f"Bearer {META_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/webhook/meta")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
        logger.info("Webhook verificado com sucesso")
        return Response(content=hub_challenge, media_type="text/plain")
    logger.warning(f"Verificacao falhou: mode={hub_mode} token={hub_verify_token}")
    return Response(status_code=403)


@app.post("/webhook/meta")
async def receive_webhook(request: Request):
    payload = await request.json()
    logger.debug(f"Payload recebido: {payload}")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})

            # wa_id → nome do contato
            contacts = {
                c["wa_id"]: c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
            }

            for msg in value.get("messages", []):
                from_number = msg["from"]
                msg_type = msg.get("type", "")

                if msg_type == "text":
                    content = msg["text"]["body"]
                elif msg_type == "button":
                    content = msg["button"]["text"]
                else:
                    content = f"[{msg_type}]"

                push_name = contacts.get(from_number)
                logger.info(
                    f"[RECV] {push_name or from_number} ({from_number}): {content!r}"
                )

                # 1. Salva lead
                lead = get_or_create_lead(from_number, name=push_name)

                # 2. Salva mensagem recebida
                save_message(lead["id"], "user", content)
                logger.info(f"[DB] Mensagem salva (lead_id={lead['id']})")

                # 3. Envia auto-reply e salva
                try:
                    await send_meta_text(from_number, AUTO_REPLY)
                    save_message(lead["id"], "assistant", AUTO_REPLY)
                    logger.info(f"[SEND] Auto-reply enviado para {from_number}")
                except httpx.HTTPStatusError as e:
                    logger.error(
                        f"[SEND] Erro HTTP {e.response.status_code} ao enviar para "
                        f"{from_number}: {e.response.text}"
                    )
                except Exception as e:
                    logger.error(f"[SEND] Erro ao enviar para {from_number}: {e}")

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "mvp"}
