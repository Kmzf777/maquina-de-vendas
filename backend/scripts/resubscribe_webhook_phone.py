"""
Diagnóstico e correção de webhook de STATUS de entrega para um canal Meta Cloud.

Contexto: a Meta responde ao envio com HTTP 200 + wamid (message_status="accepted"),
o que é apenas ACEITE na fila. A confirmação de entrega chega depois, num webhook de
status (sent/delivered/read/failed). Se o phone_number_id não estiver com a assinatura
de webhook ativa — ou tiver um override de callback apontando para outro lugar — esses
callbacks nunca chegam e toda mensagem fica "aceita mas não confirmada" (falso positivo
de entrega). Foi exatamente o caso do canal "NUMERO ARTHUR" (phone_number_id
1154144237780462): a WABA está assinada (outros números dela recebem status), mas este
número específico ficou silencioso.

A assinatura de webhook é feita no nível da WABA:
    POST /{WABA_ID}/subscribed_apps      → (re)assina o app atual (idempotente)
    GET  /{WABA_ID}/subscribed_apps      → lista apps assinados
Um phone_number pode ainda ter um OVERRIDE de callback próprio, que se sobrepõe ao da
WABA. Isso é inspecionado via GET /{PHONE_NUMBER_ID}?fields=webhook_configuration e
removido via DELETE /{PHONE_NUMBER_ID}/subscribed_apps.

Uso (a partir de backend/):
    python scripts/resubscribe_webhook_phone.py --phone-number-id 1154144237780462
    python scripts/resubscribe_webhook_phone.py --name "NUMERO ARTHUR"
    python scripts/resubscribe_webhook_phone.py --channel-id <uuid>

Por padrão é DRY-RUN (só diagnostica). Para efetivar a re-assinatura:
    ... --apply
Para remover um override de callback preso no phone_number (restaura o default da WABA):
    ... --apply --clear-phone-override

Credenciais: lê a .env (SUPABASE_URL / SUPABASE_SERVICE_KEY) da raiz do repo, se existir,
e busca o canal no banco (access_token + waba_id vêm de channels.provider_config). Também
aceita --access-token / --waba-id explícitos para rodar sem banco.
"""
import argparse
import json
import os
import sys

import httpx

GRAPH_VERSION = "v21.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def _get_channel(args) -> dict | None:
    """Resolve o canal via banco a partir de --channel-id / --phone-number-id / --name."""
    try:
        from supabase import create_client
    except Exception:
        return None
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not (url and key):
        return None
    sb = create_client(url, key)
    q = sb.table("channels").select("id, name, provider, provider_config").eq("provider", "meta_cloud")
    if args.channel_id:
        q = q.eq("id", args.channel_id)
    elif args.name:
        q = q.eq("name", args.name)
    rows = q.execute().data or []
    if args.phone_number_id and not (args.channel_id or args.name):
        rows = [
            r for r in rows
            if (r.get("provider_config") or {}).get("phone_number_id") == args.phone_number_id
        ]
    elif args.phone_number_id:
        rows = [
            r for r in rows
            if (r.get("provider_config") or {}).get("phone_number_id") == args.phone_number_id
        ] or rows
    if not rows:
        # Sem filtro de canal, mas com phone_number_id → varrer todos meta_cloud
        if args.phone_number_id:
            allrows = sb.table("channels").select("id, name, provider_config").eq("provider", "meta_cloud").execute().data or []
            rows = [r for r in allrows if (r.get("provider_config") or {}).get("phone_number_id") == args.phone_number_id]
    return rows[0] if rows else None


def _graph_get(path: str, token: str, params: dict | None = None) -> tuple[int, dict]:
    with httpx.Client(timeout=20.0) as c:
        r = c.get(f"{GRAPH_BASE}/{path}", params=params or {}, headers={"Authorization": f"Bearer {token}"})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text}


def _graph_post(path: str, token: str, data: dict | None = None) -> tuple[int, dict]:
    with httpx.Client(timeout=20.0) as c:
        r = c.post(f"{GRAPH_BASE}/{path}", data=data or {}, headers={"Authorization": f"Bearer {token}"})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text}


def _graph_delete(path: str, token: str) -> tuple[int, dict]:
    with httpx.Client(timeout=20.0) as c:
        r = c.delete(f"{GRAPH_BASE}/{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"raw": r.text}


def _pp(label: str, code: int, body: dict):
    print(f"\n── {label} [HTTP {code}] ──")
    print(json.dumps(body, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Diagnostica/corrige webhook de status de um canal Meta.")
    ap.add_argument("--channel-id")
    ap.add_argument("--phone-number-id")
    ap.add_argument("--name")
    ap.add_argument("--access-token", help="Sobrepõe o token do banco")
    ap.add_argument("--waba-id", help="Sobrepõe o waba_id do banco")
    ap.add_argument("--apply", action="store_true", help="Efetiva a re-assinatura (default: dry-run)")
    ap.add_argument("--clear-phone-override", action="store_true",
                    help="Remove override de callback no phone_number (restaura default da WABA)")
    args = ap.parse_args()

    _load_env()

    token = args.access_token
    waba_id = args.waba_id
    phone_number_id = args.phone_number_id
    channel_name = args.name or "(canal)"

    if not (token and waba_id and phone_number_id):
        ch = _get_channel(args)
        if not ch:
            print("ERRO: canal não encontrado no banco e credenciais não fornecidas por flag.")
            print("Passe --access-token, --waba-id e --phone-number-id explicitamente, ou garanta")
            print("SUPABASE_URL/SUPABASE_SERVICE_KEY na .env e um seletor válido de canal.")
            sys.exit(1)
        cfg = ch.get("provider_config") or {}
        channel_name = ch.get("name") or channel_name
        token = token or cfg.get("access_token")
        waba_id = waba_id or cfg.get("waba_id")
        phone_number_id = phone_number_id or cfg.get("phone_number_id")

    if not token:
        print("ERRO: sem access_token (nem no banco nem via --access-token).")
        sys.exit(1)
    if not waba_id:
        print("ERRO: sem waba_id (nem no banco nem via --waba-id).")
        sys.exit(1)

    print(f"Canal:            {channel_name}")
    print(f"WABA ID:          {waba_id}")
    print(f"phone_number_id:  {phone_number_id}")
    print(f"Modo:             {'APPLY' if args.apply else 'DRY-RUN (diagnóstico)'}")

    # 1. Estado do número + override de webhook
    if phone_number_id:
        code, body = _graph_get(
            phone_number_id, token,
            {"fields": "id,display_phone_number,verified_name,code_verification_status,"
                       "quality_rating,platform_type,webhook_configuration"},
        )
        _pp("Estado do phone_number", code, body)
        wc = (body or {}).get("webhook_configuration")
        if wc and wc.get("application"):
            print("\n⚠️  Este número tem um OVERRIDE de webhook próprio (application override):")
            print(f"    {wc}")
            print("    Enquanto existir, os callbacks de status podem NÃO chegar à sua URL da WABA.")

    # 2. Apps assinados na WABA
    code, body = _graph_get(f"{waba_id}/subscribed_apps", token)
    _pp("Apps assinados na WABA (antes)", code, body)

    # 3. (Re)assinar a WABA — idempotente
    if args.apply:
        code, body = _graph_post(f"{waba_id}/subscribed_apps", token)
        _pp("POST /subscribed_apps (re-assinatura da WABA)", code, body)

        if args.clear_phone_override and phone_number_id:
            code, body = _graph_delete(f"{phone_number_id}/subscribed_apps", token)
            _pp("DELETE /{phone}/subscribed_apps (remove override)", code, body)

        code, body = _graph_get(f"{waba_id}/subscribed_apps", token)
        _pp("Apps assinados na WABA (depois)", code, body)
        print("\n✅ Re-assinatura concluída. Envie um template de teste e confirme se o webhook de")
        print("   status (sent/delivered) passa a chegar para este phone_number_id.")
    else:
        print("\n(DRY-RUN) Nada foi alterado. Reexecute com --apply para (re)assinar a WABA.")
        print("Se o passo 1 mostrou um override de webhook no número, adicione --clear-phone-override.")

    # 4. Instrução manual (caso a API não resolva — override no App Dashboard)
    print(_MANUAL_INSTRUCTIONS)


_MANUAL_INSTRUCTIONS = """
────────────────────────────────────────────────────────────────────────────
SE O WEBHOOK CONTINUAR SILENCIOSO (intervenção manual no Meta):

1. Meta App Dashboard (developers.facebook.com) → seu App → WhatsApp → Configuration:
   - Confirme o "Callback URL" = https://api.canastrainteligencia.com/webhook/meta
     (o mesmo endpoint que já recebe os inbounds) e o Verify Token.
   - Em "Webhook fields", garanta que o campo **messages** está ASSINADO (Subscribe).
     Esse campo entrega TANTO mensagens recebidas QUANTO os status de entrega
     (sent/delivered/read/failed).

2. WhatsApp Manager (business.facebook.com) → Configurações da conta →
   verifique se o número afetado está com status **Conectado** e sem um
   "Endpoint de webhook" próprio configurado que difira do da conta (WABA).
   Um override no número tem precedência sobre a assinatura da WABA.

3. Se houver override indesejado no número, remova-o (ou rode este script com
   --apply --clear-phone-override) para que o número volte a herdar o webhook da WABA.

4. Depois de qualquer mudança, dispare um template de teste e observe em
   meta_webhook_logs (direction=inbound, payload contendo "statuses") se os
   callbacks passam a chegar para o phone_number_id em questão.
────────────────────────────────────────────────────────────────────────────
"""


if __name__ == "__main__":
    main()
