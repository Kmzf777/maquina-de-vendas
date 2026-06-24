"""Smoke test dirigido — Turnaround Framework (contorno de objecao "vou pensar").

Injeta uma conversa scriptada terminando em "Vou analisar com calma e te aviso" e
verifica que a Valeria CONTORNA (ancoragem + quebra de padrao + pergunta) em vez de
descartar o lead com um passivo "perfeito, sem problema / fico a disposicao".

Uso (backend no ar com REHEARSAL_MODE=true):
    REHEARSAL_MODE=true python -m scripts.turnaround_smoke
"""
import asyncio
import os
import time
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env.local")

from scripts.rehearsal import supabase_io  # noqa: E402

DEV = os.environ.get("DEV_BACKEND_URL", "http://127.0.0.1:8001")
PNID = os.environ.get("SMOKE_PHONE_NUMBER_ID", "rehearsal")  # canal outbound (rehearsal)
PHONE = os.environ.get("SMOKE_PHONE", "5521900000099")
SCRIPT = [
    "Sim",
    "tenho uma cafeteria e to querendo comprar cafe especial pro meu negocio",
    "Vou analisar com calma e te aviso",
]
PASSIVE_MARKERS = ["fico a disposicao", "fico à disposição", "sem problema", "quando fizer sentido",
                   "quando quiser", "sem pressa"]


def _payload(text: str) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "smoke", "changes": [{
        "value": {"messaging_product": "whatsapp",
                  "metadata": {"phone_number_id": PNID, "display_phone_number": PHONE},
                  "contacts": [{"profile": {"name": "Smoke Lead"}, "wa_id": PHONE}],
                  "messages": [{"from": PHONE, "id": f"wamid.smoke.{uuid.uuid4().hex}",
                                "timestamp": str(int(time.time())), "type": "text",
                                "text": {"body": text}}]},
        "field": "messages"}]}]}


async def _wait_new_assistant(lead_id: str, since_iso: str, timeout: float = 90.0) -> list[dict]:
    """Espera o turno COMPLETO da Valeria: apos a 1a bolha, segue coletando ate parar
    de chegar bolha nova por ~6s (os baloes vem espacados pelos delays de digitacao)."""
    deadline = time.time() + timeout
    assistant: list[dict] = []
    stable_since = None
    while time.time() < deadline:
        msgs = supabase_io.get_messages_since(lead_id, since_iso)
        cur = [m for m in msgs if m.get("role") == "assistant"]
        if cur and len(cur) == len(assistant):
            if stable_since and (time.time() - stable_since) >= 6.0:
                return cur
        else:
            stable_since = time.time() if cur else None
        assistant = cur
        await asyncio.sleep(2.0)
    return assistant


async def main():
    supabase_io.wipe_lead(PHONE)
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20, read=90, write=10, pool=15)) as c:
        # turno 1 — cria o lead
        await c.post(f"{DEV}/webhook/meta", json=_payload(SCRIPT[0]))
        lead_id = None
        for _ in range(40):
            lead = supabase_io.get_lead_by_phone(PHONE)
            if lead:
                lead_id = lead["id"]; break
            await asyncio.sleep(0.5)
        if not lead_id:
            print("FALHA: lead nao criado"); return

        last_iso = "1970-01-01T00:00:00+00:00"
        for i, text in enumerate(SCRIPT):
            if i > 0:
                await c.post(f"{DEV}/webhook/meta", json=_payload(text))
            print(f"\n[LEAD] {text}")
            new = await _wait_new_assistant(lead_id, last_iso)
            if not new:
                print("  (sem resposta no tempo limite)"); continue
            for m in new:
                print(f"[VALERIA] {m['content']}")
            last_iso = new[-1]["created_at"]

    # Verificacao do turno da objecao (ultimas respostas)
    all_msgs = supabase_io.get_all_messages(lead_id)
    events = supabase_io.get_system_events(lead_id)
    # persona: select de supabase_io nao traz agent_persona — busca dedicada
    from app.db.supabase import get_supabase
    prow = (get_supabase().table("messages").select("agent_persona")
            .eq("lead_id", lead_id).eq("role", "assistant")
            .not_.is_("agent_persona", "null").limit(1).execute())
    persona = (prow.data[0]["agent_persona"] if prow.data else None)
    # resposta(s) ao "vou analisar" = assistants apos a ultima user msg
    last_user_idx = max((i for i, m in enumerate(all_msgs) if m.get("role") == "user"), default=-1)
    objection_reply = " ".join(m["content"].lower() for m in all_msgs[last_user_idx + 1:]
                               if m.get("role") == "assistant")
    descartou = any("sem interesse" in (e.get("content", "").lower()) for e in events)
    passivo = any(mk in objection_reply for mk in PASSIVE_MARKERS)
    # pergunta de contorno: "?" OU frase interrogativa sem o ponto de interrogacao literal
    _interrog = ("?" in objection_reply or any(mk in objection_reply for mk in
                 ["tem algo", "o que", "qual", "quer ", "posso ", "consigo", "te preocupa", "alguma duvida"]))
    turnaround_ok = (not descartou) and (not passivo) and _interrog

    print("\n=== VERDICT ===")
    print(f"persona               : {persona}")
    print(f"descartou (perdido)?  : {descartou}  (esperado False)")
    print(f"resposta passiva?     : {passivo}    (esperado False)")
    print(f"fez pergunta (contorno): {_interrog}  (esperado True)")
    print(f"TURNAROUND_OK         : {turnaround_ok}")


if __name__ == "__main__":
    asyncio.run(main())
