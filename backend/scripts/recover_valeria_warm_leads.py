"""Recuperação ESTRITA dos leads mornos de landing page no canal da Valéria (queda 03/07).

Escopo cirúrgico: SOMENTE os disparos do template `lp_solicitacao_recebida` (a mensagem
de contato inicial dos leads que se cadastraram pela landing page) que falharam / não
foram entregues desde sexta 03/07 e cujo lead ainda não respondeu. Esses leads pediram
contato pelo formulário mas nunca receberam a primeira mensagem por causa do bug de
infra/faturamento — reengajá-los via HSM é legítimo.

EXCLUSÃO EXPLÍCITA (instrução): a campanha fria pausada "DSP - FRIOS - 04/07"
(template utilidade_22_04_2026_16_40) e os disparos de teste (hello_world, etc.) NÃO
são tocados. A segmentação é feita pelo marcador autoritativo do próprio disparo,
`metadata.dispatch.template == 'lp_solicitacao_recebida'`, o que já isola o template
correto; um denylist redundante reforça a barreira.

Template (verificado em message_templates): `lp_solicitacao_recebida`, pt_BR, approved,
BODY com 1 param NOMEADO `primeiro_nome` (sem botões). Param nomeado é obrigatório —
formato posicional é rejeitado e vira loop (histórico do funil LP). Por isso enviamos
`parameter_name="primeiro_nome"`.

Padrão = DRY-RUN. Só `--execute --yes` dispara, com teto anti-spam e idempotência.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone

from supabase import create_client

VALERIA_CHANNEL_ID = "6e51629d-f095-4a4e-9e26-46a8da225a89"
FAILURE_START = "2026-07-03T00:00:00Z"
LP_TEMPLATE = "lp_solicitacao_recebida"
LP_LANG = "pt_BR"
FAILED_STATUSES = ("failed", "undelivered")
BATCH_TAG = "valeria_lp_recovery_20260708"
MAX_SEND = 50
# Denylist redundante — nunca disparar estes (campanha fria pausada + testes).
DENY_TEMPLATES = {
    "utilidade_22_04_2026_16_40", "hello_world",
    "atualizacao_cadastro_informacoes", "continuar_conversa",
}
EXAMPLE_PHONE_FRAGMENT = "68984034025"  # lead de exemplo do contexto (Agnus)


def _sb():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _conv_map(sb) -> dict[str, str]:
    convs = sb.table("conversations").select("id, lead_id").eq("channel_id", VALERIA_CHANNEL_ID).execute().data
    return {c["id"]: c["lead_id"] for c in convs}


def _inbound_leads_since(sb, conv_ids: list[str]) -> set[str]:
    by_conv = {}  # reuse map from caller instead — kept simple here
    leads: set[str] = set()
    CHUNK = 100
    convs = sb.table("conversations").select("id, lead_id").eq("channel_id", VALERIA_CHANNEL_ID).execute().data
    cmap = {c["id"]: c["lead_id"] for c in convs}
    for i in range(0, len(conv_ids), CHUNK):
        rows = (
            sb.table("messages").select("conversation_id")
            .in_("conversation_id", conv_ids[i : i + CHUNK])
            .eq("role", "user").gte("created_at", FAILURE_START).execute().data
        )
        for r in rows:
            lid = cmap.get(r["conversation_id"])
            if lid:
                leads.add(lid)
    return leads


def _already_recovered(sb, lead_id: str) -> bool:
    rows = (
        sb.table("messages").select("metadata")
        .eq("lead_id", lead_id).order("created_at", desc=True).limit(50).execute().data
    )
    for r in rows:
        md = r.get("metadata") or {}
        if isinstance(md, dict) and md.get("recovery_batch") == BATCH_TAG:
            return True
    return False


def build_cohort(sb) -> list[dict]:
    cmap = _conv_map(sb)
    conv_ids = list(cmap.keys())
    inbound_since = _inbound_leads_since(sb, conv_ids)

    lp_fail_leads: set[str] = set()
    CHUNK = 100
    for i in range(0, len(conv_ids), CHUNK):
        rows = (
            sb.table("messages").select("conversation_id, lead_id, metadata")
            .in_("conversation_id", conv_ids[i : i + CHUNK])
            .eq("role", "assistant").gte("created_at", FAILURE_START)
            .in_("delivery_status", list(FAILED_STATUSES)).execute().data
        )
        for r in rows:
            md = r.get("metadata") or {}
            tmpl = (md.get("dispatch") or {}).get("template") if isinstance(md, dict) else None
            # filtro rígido: só o template LP; denylist redundante barra frios/testes
            if tmpl == LP_TEMPLATE and tmpl not in DENY_TEMPLATES:
                lid = r.get("lead_id") or cmap.get(r["conversation_id"])
                if lid and lid not in inbound_since:  # ainda não respondeu
                    lp_fail_leads.add(lid)

    if not lp_fail_leads:
        return []
    return sb.table("leads").select("id, name, phone, wa_id, traffic_type").in_("id", list(lp_fail_leads)).execute().data


def print_dry_run(cohort: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    print("=" * 72)
    print("DRY-RUN — recuperação leads MORNOS de LP no canal da Valéria (SOMENTE LEITURA)")
    print(f"  agora(UTC)={now}  corte(sexta)={FAILURE_START}")
    print(f"  canal Valéria={VALERIA_CHANNEL_ID}  template ÚNICO={LP_TEMPLATE} [{LP_LANG}]")
    print(f"  EXCLUÍDOS (denylist): {sorted(DENY_TEMPLATES)}")
    print("=" * 72)
    agnus = False
    for L in cohort:
        if EXAMPLE_PHONE_FRAGMENT in (L.get("phone") or ""):
            agnus = True
        print(f"    lead={L['id']}  nome={L.get('name')!r}  phone={L.get('phone')}  wa_id={L.get('wa_id')}  traffic={L.get('traffic_type')}")
    print("-" * 72)
    print(f"  LEADS ELEGÍVEIS (LP falho, sem resposta) = {len(cohort)}")
    print(f"  lead de exemplo 5568984034025 (Agnus) incluído? {'SIM' if agnus else 'NÃO'}")
    print("=" * 72)


async def do_execute(sb, cohort: list[dict]) -> None:
    if not cohort:
        print("Nada a disparar (0 leads). Encerrando sem tocar na Meta.")
        return
    if len(cohort) > MAX_SEND:
        raise SystemExit(f"ABORTADO: {len(cohort)} > teto {MAX_SEND}. Revisar manualmente.")

    from app.follow_up.scheduler import resolve_send_target, strip_greeting_prefix, _NAME_FALLBACK
    from app.whatsapp.meta import MetaCloudClient, extract_wamid
    from app.conversations.service import get_or_create_conversation
    from app.conversations.service import save_message as save_message_conv

    channel = sb.table("channels").select("provider_config").eq("id", VALERIA_CHANNEL_ID).single().execute().data
    provider = MetaCloudClient(channel["provider_config"])

    sent_ok = 0
    for lead in cohort:
        if _already_recovered(sb, lead["id"]):
            print(f"  pulado (idempotência) lead={lead['id']}"); continue
        # 9º dígito: usa o resolvedor canônico do app (prefere wa_id; aqui é phone pois nunca houve inbound)
        send_to = resolve_send_target(lead, lead.get("phone", ""))
        stripped = strip_greeting_prefix(lead.get("name"))
        first_name = stripped.split()[0] if stripped else _NAME_FALLBACK
        components = [{"type": "body", "parameters": [
            {"type": "text", "parameter_name": "primeiro_nome", "text": first_name}]}]
        try:
            resp = await provider.send_template(send_to, LP_TEMPLATE, components=components, language_code=LP_LANG)
        except Exception as exc:
            print(f"  FALHOU lead={lead['id']} to={send_to}: {exc}"); continue
        conv = get_or_create_conversation(lead["id"], VALERIA_CHANNEL_ID)
        save_message_conv(
            conversation_id=conv["id"], lead_id=lead["id"], role="assistant",
            content=f"[reengajamento LP] template {LP_TEMPLATE} reenviado", sent_by="recovery",
            wamid=extract_wamid(resp), metadata={"recovery_batch": BATCH_TAG, "template": LP_TEMPLATE},
        )
        sent_ok += 1
        print(f"  enviado lead={lead['id']} to={send_to} nome={first_name}")

    print("-" * 72)
    print(f"CONCLUÍDO: {sent_ok}/{len(cohort)} template(s) LP disparado(s).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    sb = _sb()
    cohort = build_cohort(sb)
    print_dry_run(cohort)

    if not args.execute:
        print("\nMODO DRY-RUN. Nada disparado. Para executar: --execute --yes")
        return
    if not args.yes:
        raise SystemExit("--execute exige --yes.")
    asyncio.run(do_execute(sb, cohort))


if __name__ == "__main__":
    main()
