"""Reengajamento HSM dos leads do canal do João após a queda de 03/07/2026.

A janela de 24h está fechada para os não-respondentes, então o reengajamento é feito
via TEMPLATES APROVADOS (HSM), que podem ser disparados fora da janela. Mapeia 3 coortes
mutuamente exclusivas (corte temporal = sexta 03/07) e dispara UM template por lead:

  Coorte 1 (Falha no Handoff): teve disparo `automacao_valeria_to_joao` FALHO/não-entregue
      desde sexta E não respondeu (sem inbound) desde sexta  ->  reenvia automacao_valeria_to_joao.
  Coorte 2 (Falha no Retorno): teve disparo `continuar_conversa` FALHO/não-entregue desde
      sexta E não respondeu desde sexta  ->  reenvia continuar_conversa.
  Coorte 3 (Vácuo): enviou inbound desde sexta MAS não recebeu nenhum outbound no canal do
      João desde sexta  ->  envia continuar_conversa.

Dedup / exclusividade (obrigatório — nenhum lead recebe 2 templates):
  * C3 é disjunta de C1/C2 por construção (C3 exige inbound-desde-sexta; C1/C2 exigem SEM
    inbound-desde-sexta).
  * C1 tem prioridade sobre C2 (um lead com ambos os disparos falhos recebe só o handoff).
  * Dentro de cada coorte, 1 template por lead.

Nomes/locales APROVADOS na Meta (verificados em public.message_templates):
  automacao_valeria_to_joao -> language `en`, 2 params nomeados (nome_do_lead, nome_do_vendedor)
  continuar_conversa        -> language `pt_BR`, 1 param nomeado (primeiro_nome)
Erros de locale/param dão 404/rejeição -> por isso reusamos os builders/senders do app.

Padrão = DRY-RUN. Só `--execute --yes` dispara de verdade, com teto anti-spam e marcador
de idempotência (metadata.recovery_batch) que impede reenvio duplicado se rodar 2x.

Uso (no container/venv do backend, com env de produção):
    python -m scripts.recover_joao_templates                 # dry-run (conta as 3 coortes)
    python -m scripts.recover_joao_templates --execute --yes # dispara os templates
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone

from supabase import create_client

JOAO_CHANNEL_ID = "a3a607b1-6bff-4370-8609-b275eef270dd"
FAILURE_START = "2026-07-03T00:00:00Z"
FAILED_STATUSES = ("failed", "undelivered")
VALERIA_SIGNATURE = "recebi o repasse"  # corpo persistido do automacao_valeria_to_joao
REOPEN_TEMPLATE = "continuar_conversa"
REOPEN_LANG = "pt_BR"
BATCH_TAG = "joao_templates_recovery_20260708"
MAX_SEND = 50  # teto duro anti-spam


def _sb():
    url = os.environ["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


def _lead_ids_with(sb, role: str) -> set[str]:
    convs = sb.table("conversations").select("id, lead_id").eq("channel_id", JOAO_CHANNEL_ID).execute().data
    conv_ids = [c["id"] for c in convs]
    by_conv = {c["id"]: c["lead_id"] for c in convs}
    leads: set[str] = set()
    CHUNK = 100
    for i in range(0, len(conv_ids), CHUNK):
        rows = (
            sb.table("messages").select("conversation_id")
            .in_("conversation_id", conv_ids[i : i + CHUNK])
            .eq("role", role).gte("created_at", FAILURE_START).execute().data
        )
        for r in rows:
            lid = by_conv.get(r["conversation_id"])
            if lid:
                leads.add(lid)
    return leads


def _failed_disparo_leads(sb, valeria: bool) -> set[str]:
    """Leads com disparo FALHO/não-entregue desde sexta; valeria=True -> automacao_valeria_to_joao,
    valeria=False -> qualquer outro (proxy do continuar_conversa)."""
    convs = sb.table("conversations").select("id, lead_id").eq("channel_id", JOAO_CHANNEL_ID).execute().data
    conv_ids = [c["id"] for c in convs]
    by_conv = {c["id"]: c["lead_id"] for c in convs}
    leads: set[str] = set()
    CHUNK = 100
    for i in range(0, len(conv_ids), CHUNK):
        rows = (
            sb.table("messages").select("conversation_id, content")
            .in_("conversation_id", conv_ids[i : i + CHUNK])
            .eq("role", "assistant").gte("created_at", FAILURE_START)
            .in_("delivery_status", list(FAILED_STATUSES)).execute().data
        )
        for r in rows:
            is_valeria = VALERIA_SIGNATURE in (r.get("content") or "")
            if is_valeria == valeria:
                lid = by_conv.get(r["conversation_id"])
                if lid:
                    leads.add(lid)
    return leads


def _already_recovered(sb, lead_id: str) -> bool:
    """Idempotência: já existe uma mensagem deste batch de recuperação para o lead?"""
    rows = (
        sb.table("messages").select("id, metadata")
        .eq("lead_id", lead_id)
        .order("created_at", desc=True).limit(50).execute().data
    )
    for r in rows:
        md = r.get("metadata") or {}
        if isinstance(md, dict) and md.get("recovery_batch") == BATCH_TAG:
            return True
    return False


def build_cohorts(sb) -> dict[str, list[dict]]:
    inbound_since = _lead_ids_with(sb, "user")
    outbound_since = _lead_ids_with(sb, "assistant")
    c1_leads = _failed_disparo_leads(sb, valeria=True) - inbound_since
    c2_leads = (_failed_disparo_leads(sb, valeria=False) - inbound_since) - c1_leads
    c3_leads = inbound_since - outbound_since

    def hydrate(ids: set[str]) -> list[dict]:
        if not ids:
            return []
        rows = sb.table("leads").select("id, name, phone, wa_id").in_("id", list(ids)).execute().data
        return rows

    return {"cohort1": hydrate(c1_leads), "cohort2": hydrate(c2_leads), "cohort3": hydrate(c3_leads)}


def print_dry_run(cohorts: dict[str, list[dict]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    print("=" * 72)
    print("DRY-RUN — reengajamento HSM do canal do João (SOMENTE LEITURA)")
    print(f"  agora(UTC)={now}  corte(sexta)={FAILURE_START}  canal={JOAO_CHANNEL_ID}")
    print("=" * 72)
    labels = {
        "cohort1": "Coorte 1 (Falha Handoff) -> automacao_valeria_to_joao [en]",
        "cohort2": "Coorte 2 (Falha Retorno) -> continuar_conversa [pt_BR]",
        "cohort3": "Coorte 3 (Vácuo)         -> continuar_conversa [pt_BR]",
    }
    for key in ("cohort1", "cohort2", "cohort3"):
        leads = cohorts[key]
        print(f"\n{labels[key]}  = {len(leads)} lead(s)")
        for L in leads:
            print(f"    lead={L['id']}  nome={L.get('name')!r}  phone={L.get('phone')}  wa_id={L.get('wa_id')}")
    total = sum(len(v) for v in cohorts.values())
    # sanidade de dedup: nenhum lead em 2 coortes
    ids = [L["id"] for v in cohorts.values() for L in v]
    dup = len(ids) - len(set(ids))
    print("\n" + "-" * 72)
    print(f"  TOTAL leads elegíveis = {total}   |   duplicados entre coortes = {dup} (deve ser 0)")
    print("=" * 72)


async def do_execute(sb, cohorts: dict[str, list[dict]]) -> None:
    total = sum(len(v) for v in cohorts.values())
    if total == 0:
        print("Nada a disparar (0 leads). Encerrando sem tocar na Meta.")
        return
    if total > MAX_SEND:
        raise SystemExit(f"ABORTADO: {total} > teto {MAX_SEND}. Revisar manualmente.")

    # imports tardios (só no caminho real) — reusa senders/builders endurecidos do app
    from app.follow_up.scheduler import (
        send_joao_handoff_template,
        resolve_send_target,
        strip_greeting_prefix,
        _NAME_FALLBACK,
    )
    from app.whatsapp.meta import MetaCloudClient, extract_wamid
    from app.conversations.service import get_or_create_conversation
    from app.conversations.service import save_message as save_message_conv

    channel = sb.table("channels").select("provider_config").eq("id", JOAO_CHANNEL_ID).single().execute().data
    provider = MetaCloudClient(channel["provider_config"])

    sent_ok = 0

    async def send_continuar(lead: dict) -> None:
        nonlocal sent_ok
        send_to = resolve_send_target(lead, lead.get("phone", ""))
        # continuar_conversa (pt_BR) tem BODY estático (0 variáveis) + botão QUICK_REPLY.
        # Enviar QUALQUER param no body dá Meta (#132000). Portanto: sem components.
        resp = await provider.send_template(send_to, REOPEN_TEMPLATE, components=None, language_code=REOPEN_LANG)
        conv = get_or_create_conversation(lead["id"], JOAO_CHANNEL_ID)
        save_message_conv(
            conversation_id=conv["id"], lead_id=lead["id"], role="assistant",
            content=f"[reengajamento] template {REOPEN_TEMPLATE} enviado", sent_by="recovery",
            wamid=extract_wamid(resp), metadata={"recovery_batch": BATCH_TAG, "template": REOPEN_TEMPLATE},
        )
        sent_ok += 1
        print(f"  [C-continuar] enviado lead={lead['id']} to={send_to}")

    # Coorte 1 -> automacao_valeria_to_joao (via sender do app, que já persiste)
    for lead in cohorts["cohort1"]:
        if _already_recovered(sb, lead["id"]):
            print(f"  [C1] pulado (idempotência) lead={lead['id']}"); continue
        target = lead.get("wa_id") or lead.get("phone")
        ok = await send_joao_handoff_template(target, lead.get("name") or "", lead["id"])
        if ok:
            # marca o batch para idempotência (o sender persiste sem o marcador)
            conv = get_or_create_conversation(lead["id"], JOAO_CHANNEL_ID)
            save_message_conv(
                conversation_id=conv["id"], lead_id=lead["id"], role="system",
                content=f"[reengajamento] batch {BATCH_TAG} — automacao_valeria_to_joao",
                sent_by="recovery", metadata={"recovery_batch": BATCH_TAG, "template": "automacao_valeria_to_joao"},
            )
            sent_ok += 1
            print(f"  [C1] enviado lead={lead['id']} to={target}")
        else:
            print(f"  [C1] FALHOU lead={lead['id']} to={target}")

    # Coorte 2 e 3 -> continuar_conversa
    for lead in cohorts["cohort2"] + cohorts["cohort3"]:
        if _already_recovered(sb, lead["id"]):
            print(f"  [C2/3] pulado (idempotência) lead={lead['id']}"); continue
        try:
            await send_continuar(lead)
        except Exception as exc:
            print(f"  [C2/3] FALHOU lead={lead['id']}: {exc}")

    print("-" * 72)
    print(f"CONCLUÍDO: {sent_ok}/{total} template(s) disparado(s).")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    sb = _sb()
    cohorts = build_cohorts(sb)
    print_dry_run(cohorts)

    if not args.execute:
        print("\nMODO DRY-RUN. Nada disparado. Para executar: --execute --yes")
        return
    if not args.yes:
        raise SystemExit("--execute exige --yes.")
    asyncio.run(do_execute(sb, cohorts))


if __name__ == "__main__":
    main()
