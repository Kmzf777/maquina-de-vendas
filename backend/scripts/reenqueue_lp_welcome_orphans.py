"""Resgata leads de Landing Page "órfãos": criados com origem mas que nunca receberam
a 1ª mensagem (sem conversa, sem mensagem, sem job lp_welcome) — vazamento do funil
identificado na auditoria de 21/06.

Para cada órfão:
  1. Cria/reaproveita a conversa na inbox da Valéria (canal VALERIA).
  2. Agenda um follow_up_jobs job_type='lp_welcome' (fire_at clampado p/ janela comercial),
     espelhando lp_webhook.service._schedule_lp_welcome, idempotente por conversa.

O worker de follow-up (process_due_followups → _process_lp_welcome) faz o envio do template.

⚠️  SEGURANÇA OPERACIONAL
  - Os jobs PRECISAM entrar no banco de PRODUÇÃO (env_tag='production'), senão o worker
    de produção nunca os vê. .env.local aponta para HOMOLOG — por isso o script ABORTA
    se supabase_url não for o ref de produção.
  - Default é DRY-RUN: apenas imprime o que faria. Use --commit para efetivar.
  - Envia template REAL para clientes reais. Rode só APÓS o fix do handler estar em
    produção (param nomeado {{primeiro_nome}} + anti-loop).

Uso:
    python -m scripts.reenqueue_lp_welcome_orphans            # dry-run
    python -m scripts.reenqueue_lp_welcome_orphans --commit   # efetiva
"""
import argparse
import logging
import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.db.supabase import get_supabase
from app.conversations.service import get_or_create_conversation
from app.follow_up.service import _clamp_to_business_window, is_within_business_window

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("reenqueue_lp_welcome")

# Configuração oficial do disparo de boas-vindas da LP (decisão 21/06):
PROD_PROJECT_REF = "tshmvxxxyxgctrdkqvam"
VALERIA_CHANNEL_ID = "6e51629d-f095-4a4e-9e26-46a8da225a89"
TEMPLATE_NAME = "lp_solicitacao_recebida"
LANGUAGE_CODE = "pt_BR"
SINCE = "2026-06-02"  # data do último lp_welcome que funcionou (incidente em diante)


def _assert_prod() -> None:
    url = get_settings().supabase_url or ""
    if PROD_PROJECT_REF not in url:
        logger.error(
            "ABORTADO: supabase_url (%r) não é o projeto de PRODUÇÃO (%s).\n"
            "Os jobs precisam ir para o banco de produção. Rode com as credenciais de prod\n"
            "(NÃO use .env.local, que aponta para homolog).",
            url, PROD_PROJECT_REF,
        )
        sys.exit(1)


def _find_orphans(sb) -> list[dict]:
    """Leads com origem definida, sem nenhuma conversa associada, desde o incidente."""
    leads = (
        sb.table("leads")
        .select("id, name, phone, metadata, created_at")
        .gte("created_at", SINCE)
        .order("created_at", desc=True)
        .execute()
        .data
    ) or []
    orphans = []
    for lead in leads:
        if not (lead.get("metadata") or {}).get("origem"):
            continue
        convs = sb.table("conversations").select("id").eq("lead_id", lead["id"]).limit(1).execute().data
        if not convs:
            orphans.append(lead)
    return orphans


def _schedule(sb, lead: dict, conversation_id: str, fire_at: str) -> None:
    origem = (lead.get("metadata") or {}).get("origem", "")
    # Idempotência: cancela qualquer lp_welcome pending anterior desta conversa.
    sb.table("follow_up_jobs").update({
        "status": "cancelled", "cancel_reason": "rescheduled",
    }).eq("conversation_id", conversation_id).eq("status", "pending").eq("job_type", "lp_welcome").execute()

    sb.table("follow_up_jobs").insert({
        "conversation_id": conversation_id,
        "lead_id": lead["id"],
        "channel_id": VALERIA_CHANNEL_ID,
        "sequence": 1,
        "fire_at": fire_at,
        "status": "pending",
        "env_tag": "production",
        "job_type": "lp_welcome",
        "metadata": {
            "lead_phone": lead["phone"],
            "lead_name": lead.get("name") or "",
            "template_name": TEMPLATE_NAME,
            "language_code": LANGUAGE_CODE,
            "origem": origem,
        },
    }).execute()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="Efetiva (default: dry-run)")
    args = parser.parse_args()

    _assert_prod()
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    fire_at_dt = now if is_within_business_window(now) else _clamp_to_business_window(now)
    fire_at = fire_at_dt.isoformat()

    orphans = _find_orphans(sb)
    mode = "COMMIT" if args.commit else "DRY-RUN"
    logger.info("=== Resgate LP welcome [%s] — %d órfãos | template=%s | fire_at=%s ===",
                mode, len(orphans), TEMPLATE_NAME, fire_at)

    done = skipped = 0
    for lead in orphans:
        nome = (lead.get("name") or "")[:40]
        if not args.commit:
            logger.info("  [dry] %s | %s | origem=%s", lead["phone"], nome,
                        (lead.get("metadata") or {}).get("origem"))
            continue
        conv = get_or_create_conversation(lead["id"], VALERIA_CHANNEL_ID)
        # Guard: se o lead já respondeu neste canal, não reabordar (o handler também
        # cancelaria via lead_already_replied, mas evitamos criar o job à toa).
        if conv.get("last_customer_message_at"):
            logger.info("  [skip] %s já respondeu — sem job", lead["phone"])
            skipped += 1
            continue
        _schedule(sb, lead, conv["id"], fire_at)
        logger.info("  [ok]  %s | %s | conv=%s", lead["phone"], nome, conv["id"])
        done += 1

    logger.info("=== Fim: %d agendados, %d pulados (de %d) ===", done, skipped, len(orphans))
    if not args.commit:
        logger.info("Dry-run: nada gravado. Rode com --commit para efetivar.")


if __name__ == "__main__":
    main()
