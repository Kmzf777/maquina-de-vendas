import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Any

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"[^\d]+")
_TZ_BR = timezone(timedelta(hours=-3))

# Autor fixo das observações geradas automaticamente ao disparar um template.
# Aparece como rótulo na timeline do card de CRM (lead_notes).
DISPATCH_NOTE_AUTHOR = "sistema-disparo"


def normalize_phone(phone: str | None) -> str:
    """Normalize to E.164 without '+'. Injects the Brazilian 9th digit when missing."""
    if not phone:
        return ""
    if phone.startswith("whatsapp:"):
        phone = phone[len("whatsapp:"):]
    digits = _PHONE_RE.sub("", phone)
    # Detect and fix doubled phone (e.g., "1198115400211981154002" → "11981154002")
    if len(digits) > 15 and len(digits) % 2 == 0:
        half = len(digits) // 2
        if digits[:half] == digits[half:]:
            logger.warning(
                "normalize_phone: doubled phone detected and fixed: %s → %s",
                digits, digits[:half],
            )
            digits = digits[:half]
    # Brazilian mobiles stored without 9th digit: 55 + 2-digit DDD + 8 digits = 12 total
    if len(digits) == 12 and digits.startswith("55"):
        digits = digits[:4] + "9" + digits[4:]
    return digits


# Colunas de atribuição/rastreio persistíveis na criação do lead. Whitelist defensiva:
# só estas chaves de `tracking` são gravadas, evitando injeção de colunas arbitrárias.
TRACKING_COLUMNS: tuple[str, ...] = (
    "ctwa_clid",     # Click-to-WhatsApp (anúncio → WhatsApp)
    "fbclid",        # Facebook click id (anúncio → site/LP)
    "gclid",         # Google click id (anúncio → site/LP)
    "utm_source",
    "utm_medium",
    "utm_campaign",
)


def get_or_create_lead(
    phone: str,
    name: str | None = None,
    channel: str | None = None,
    ctwa_clid: str | None = None,
    tracking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sb = get_supabase()
    normalized = normalize_phone(phone)

    # Digits-only form without 9th digit injection — matches legacy DB rows stored before normalization
    digits_only = _PHONE_RE.sub("", phone[len("whatsapp:"):] if phone.startswith("whatsapp:") else phone)

    # Look up by normalized phone first. Fallback to digits-only to catch legacy rows.
    result = sb.table("leads").select("*").eq("phone", normalized).execute()
    if result.data:
        lead = result.data[0]
        # Backfill name from WhatsApp push_name if the lead has none yet.
        if name and not lead.get("name"):
            try:
                sb.table("leads").update({"name": name}).eq("id", lead["id"]).execute()
                lead = {**lead, "name": name}
            except Exception as exc:
                logger.warning("leads.service: failed to backfill name for lead %s: %s", lead["id"], exc)
        return lead

    if digits_only != normalized:
        legacy = sb.table("leads").select("*").eq("phone", digits_only).execute()
        if legacy.data:
            # Backfill: rewrite legacy row to the normalized phone so future lookups match.
            row = dict(legacy.data[0])
            try:
                update_fields: dict[str, Any] = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone normalization for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    # Reverse 9th-digit lookup: incoming phone is 13 digits (with 9), but DB has
    # the old 12-digit format (without the 9th digit).  This happens when leads are
    # imported directly with legacy numbers and then reply after a broadcast — Meta
    # always returns the full 13-digit number in the from_number field.
    if len(normalized) == 13 and normalized.startswith("55") and normalized[4] == "9":
        twelve_digit = normalized[:4] + normalized[5:]
        legacy12 = sb.table("leads").select("*").eq("phone", twelve_digit).execute()
        if legacy12.data:
            row = dict(legacy12.data[0])
            try:
                update_fields = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
                logger.info(
                    "leads.service: backfilled phone (12→13 digit) for lead %s: %s → %s",
                    row.get("id"), twelve_digit, normalized,
                )
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone (12→13 digit) for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    # No-country-code lookup (11 digits): lead was imported as DDD + 9 + 8 digits without "55".
    # Meta always returns the full 13-digit E.164 number, so this bridges the gap.
    if len(normalized) == 13 and normalized.startswith("55"):
        eleven_digit = normalized[2:]  # strip "55" prefix
        legacy11 = sb.table("leads").select("*").eq("phone", eleven_digit).execute()
        if legacy11.data:
            row = dict(legacy11.data[0])
            try:
                update_fields: dict[str, Any] = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
                logger.info(
                    "leads.service: backfilled phone (11→13 digit) for lead %s: %s → %s",
                    row.get("id"), eleven_digit, normalized,
                )
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone (11→13 digit) for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    # No-country-code + no-9th-digit lookup (10 digits): lead stored as DDD + 8 digits only.
    if len(normalized) == 13 and normalized.startswith("55") and normalized[4] == "9":
        ten_digit = normalized[2:4] + normalized[5:]  # DDD + 8 digits, no country code, no 9
        legacy10 = sb.table("leads").select("*").eq("phone", ten_digit).execute()
        if legacy10.data:
            row = dict(legacy10.data[0])
            try:
                update_fields = {"phone": normalized}
                if name and not row.get("name"):
                    update_fields["name"] = name
                sb.table("leads").update(update_fields).eq("id", row["id"]).execute()
                row["phone"] = normalized
                if "name" in update_fields:
                    row["name"] = name
                logger.info(
                    "leads.service: backfilled phone (10→13 digit) for lead %s: %s → %s",
                    row.get("id"), ten_digit, normalized,
                )
            except Exception as exc:
                logger.warning(
                    "leads.service: failed to backfill phone (10→13 digit) for lead %s: %s",
                    row.get("id"), exc,
                )
            return row

    new_lead: dict[str, Any] = {"phone": normalized, "stage": "pending", "status": "imported", "ai_enabled": True}
    if name:
        new_lead["name"] = name
    if channel:
        new_lead["channel"] = channel
    # Atribuição (first-touch): captura os identificadores de campanha na criação do lead.
    # `ctwa_clid` explícito (caminho WhatsApp) + bag `tracking` (caminho LP/site). Só chaves
    # da whitelist TRACKING_COLUMNS são gravadas; valores vazios/None são ignorados.
    merged_tracking: dict[str, Any] = {**(tracking or {})}
    if ctwa_clid:
        merged_tracking["ctwa_clid"] = ctwa_clid
    for col in TRACKING_COLUMNS:
        val = merged_tracking.get(col)
        if val:
            new_lead[col] = val
    result = sb.table("leads").insert(new_lead).execute()
    return result.data[0]


def update_lead(lead_id: str, **fields) -> dict[str, Any]:
    sb = get_supabase()
    result = sb.table("leads").update(fields).eq("id", lead_id).execute()
    return result.data[0]


def persist_lead_tracking(lead: dict[str, Any], tracking: dict[str, Any] | None) -> None:
    """Last-touch: atualiza os campos de rastreio do lead existente com novos valores.

    Só grava chaves da whitelist TRACKING_COLUMNS cujo valor é não-vazio E difere do
    armazenado — assim um novo clique (utm/gclid/fbclid) sobrescreve o anterior, mas um
    payload SEM rastreio (campos vazios) NUNCA apaga uma atribuição já capturada.
    Fail-soft: nunca levanta (rastreio não pode quebrar o cadastro do lead).
    """
    if not lead or not tracking:
        return
    updates: dict[str, Any] = {}
    for col in TRACKING_COLUMNS:
        val = tracking.get(col)
        if isinstance(val, str):
            val = val.strip()
        if val and lead.get(col) != val:
            updates[col] = val
    if not updates:
        return
    try:
        update_lead(lead["id"], **updates)
    except Exception as exc:
        logger.warning("persist_lead_tracking: falha ao gravar rastreio para lead %s: %s", lead.get("id"), exc)


def resolve_send_target(lead: dict[str, Any] | None, fallback: str | None = None) -> str:
    """Endereço WhatsApp ENTREGÁVEL do lead para envio.

    Prefere `wa_id` (o `from` real que a Meta entregou no inbound) sobre `phone`
    (normalizado, que injeta o 9º dígito BR). Alguns números estão no WhatsApp SEM o 9,
    então enviar para o phone normalizado falha com Meta 131026 "Message Undeliverable" —
    o `wa_id` é o endereço que a Meta de fato entrega. NULL/ausente → cai para phone, depois
    para `fallback`. Ver migration 20260616_leads_wa_id.sql.
    """
    if lead:
        target = lead.get("wa_id") or lead.get("phone")
        if target:
            return target
    return fallback or ""


def append_lead_observation(lead_id: str, text: str) -> None:
    """Anexa uma linha de observacao (timestamped pelo chamador) ao campo `notes` do lead.

    Reusa a coluna `notes` existente — nao ha coluna dedicada `observations`. O conteudo de
    `notes` ja e injetado no prompt da Valeria como "Notas do CRM" (ver build_base_prompt),
    entao a observacao realimenta o contexto da IA em conversas futuras.

    Fail-soft: nunca levanta — perder uma observacao nao pode derrubar a tool que a chamou.
    """
    try:
        lead = get_lead(lead_id) or {}
        existing = (lead.get("notes") or "").rstrip()
        new_notes = f"{existing}\n{text}".strip() if existing else text
        update_lead(lead_id, notes=new_notes)
    except Exception as exc:
        logger.error(
            "append_lead_observation: falha ao anexar observacao para lead %s: %s",
            lead_id, exc, exc_info=True,
        )


def format_dispatch_note(template_name: str, when: datetime | None = None) -> str:
    """Formata a observação de disparo no padrão analítico fixo.

    Formato: ``[DD/MM/YYYY HH:MM] - Disparo feito usando o template {template_name}``

    O timestamp é renderizado no fuso de Brasília (BRT). `when` permite
    determinismo nos testes; quando omitido usa o agora.
    """
    ts = (when or datetime.now(_TZ_BR)).astimezone(_TZ_BR)
    return (
        f"[{ts.strftime('%d/%m/%Y %H:%M')}] - "
        f"Disparo feito usando o template {template_name}"
    )


def record_dispatch_note(
    lead_id: str, template_name: str, when: datetime | None = None
) -> None:
    """Registra uma observação de disparo no log de notas do lead (`lead_notes`).

    A nota aparece na timeline do card de CRM e permite quantificar quantos
    disparos foram feitos para cada lead e em quais datas (fim analítico).

    Fail-soft: nunca levanta — perder a observação não pode interromper nem
    derrubar o fluxo de disparo que a chamou. Vira no-op se faltar lead_id ou
    template_name (ex.: lead sem card ativo / disparo sem template nomeado).
    """
    if not lead_id or not template_name:
        return
    try:
        get_supabase().table("lead_notes").insert({
            "lead_id": lead_id,
            "author": DISPATCH_NOTE_AUTHOR,
            "content": format_dispatch_note(template_name, when),
        }).execute()
    except Exception as exc:
        logger.error(
            "record_dispatch_note: falha ao registrar observação de disparo "
            "para lead %s (template %s): %s",
            lead_id, template_name, exc, exc_info=True,
        )


def reset_lead(lead_id: str) -> None:
    """Reset lead: delete message history and reset stage to secretaria on both lead and conversations."""
    sb = get_supabase()
    sb.table("messages").delete().eq("lead_id", lead_id).execute()
    sb.table("leads").update({
        "stage": "secretaria",
        "status": "active",
    }).eq("id", lead_id).execute()
    sb.table("conversations").update({
        "stage": "secretaria",
        "status": "active",
    }).eq("lead_id", lead_id).execute()


_DEV_PURGE_WHITELIST = {"5534996652412", "5534932262600", "5534988861441"}


def purge_dev_lead(phone: str) -> dict:
    """Hard purge: deletes ALL CRM data for a dev phone number in correct FK order.

    Only allowed for phones in _DEV_PURGE_WHITELIST. Raises ValueError for any other number.
    meta_webhook_logs is intentionally preserved for audit history.
    """
    normalized = normalize_phone(phone)
    if normalized not in _DEV_PURGE_WHITELIST:
        raise ValueError(f"purge_dev_lead: phone {normalized!r} not in dev whitelist")

    sb = get_supabase()
    lead_res = sb.table("leads").select("id").eq("phone", normalized).execute()
    if not lead_res.data:
        return {"purged": False, "reason": "lead not found"}

    lead_id = lead_res.data[0]["id"]

    sb.table("follow_up_jobs").delete().eq("lead_id", lead_id).execute()
    sb.table("campaign_enrollments").delete().eq("lead_id", lead_id).execute()
    sb.table("broadcast_leads").delete().eq("lead_id", lead_id).execute()
    sb.table("deals").delete().eq("lead_id", lead_id).execute()
    sb.table("lead_tags").delete().eq("lead_id", lead_id).execute()
    sb.table("token_usage").delete().eq("lead_id", lead_id).execute()
    sb.table("messages").delete().eq("lead_id", lead_id).execute()
    sb.table("conversations").delete().eq("lead_id", lead_id).execute()
    sb.table("leads").delete().eq("id", lead_id).execute()

    return {"purged": True, "lead_id": lead_id, "phone": normalized}


def save_message(lead_id: str, role: str, content: str, stage: str | None = None, sent_by: str = "agent", conversation_id: str | None = None, wamid: str | None = None, agent_persona: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    msg = {
        "lead_id": lead_id,
        "role": role,
        "content": content,
        "stage": stage,
        "sent_by": sent_by,
    }
    if conversation_id:
        msg["conversation_id"] = conversation_id
    # wamid da Meta: necessário para que respostas (reply/citação) a esta mensagem
    # sejam resolvíveis. Sem ele, o frontend mostra "Mensagem original não disponível".
    if wamid is not None:
        msg["wamid"] = wamid
        msg["delivery_status"] = "sent"
    # Rastreabilidade: persona (prompt_key) que gerou a resposta. NULL p/ não-persona.
    if agent_persona is not None:
        msg["agent_persona"] = agent_persona
    result = sb.table("messages").insert(msg).execute()
    return result.data[0]


CATEGORY_PIPELINE_NAMES: dict[str, str] = {
    "atacado": "Atacado",
    "private_label": "Private Label",
    "exportacao": "Exportação",
    "consumo": "Consumo",
}


def get_lead(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    return result.data[0] if result.data else None


def create_deal(lead_id: str, title: str, category: str | None = None) -> dict[str, Any]:
    sb = get_supabase()
    pipeline_id: str | None = None
    stage_id: str | None = None

    pipeline_name = CATEGORY_PIPELINE_NAMES.get(category or "")
    if pipeline_name:
        p = sb.table("pipelines").select("id").eq("name", pipeline_name).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if not pipeline_id:
        p = sb.table("pipelines").select("id").order("order_index", desc=False).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if pipeline_id:
        s = (
            sb.table("pipeline_stages")
            .select("id")
            .eq("pipeline_id", pipeline_id)
            .eq("is_protected", False)
            .order("order_index", desc=False)
            .limit(1)
            .execute()
        )
        if s.data:
            stage_id = s.data[0]["id"]

    deal = {
        "lead_id": lead_id,
        "title": title,
        "stage": "novo",
        "category": category,
        "pipeline_id": pipeline_id,
        "stage_id": stage_id,
    }
    result = sb.table("deals").insert(deal).execute()
    return result.data[0]


BLACKLIST_PIPELINE_ID = "8988e852-2836-4add-b023-4db4d6cd0e6e"
BLACKLIST_STAGE_ID = "fbace13d-d788-423a-879d-ee468dff29ed"


def move_lead_deals_to_blacklist(lead_id: str) -> None:
    """Move ALL of the lead's deals into the Blacklist pipeline/stage.

    If the lead has no deal, create one in Blacklist so the opt-out is tracked.
    Fail-soft: log on error, never raise (opt-out must not break on deal issues).
    """
    try:
        sb = get_supabase()
        result = (
            sb.table("deals")
            .update({
                "pipeline_id": BLACKLIST_PIPELINE_ID,
                "stage_id": BLACKLIST_STAGE_ID,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("lead_id", lead_id)
            .execute()
        )
        if result.data:
            logger.info(
                "move_lead_deals_to_blacklist: %d deal(s) movidos para Blacklist para lead %s",
                len(result.data), lead_id,
            )
        else:
            # No deals existed — insert a tracking deal in Blacklist
            lead = get_lead(lead_id)
            lead_name = (lead.get("name") or lead.get("phone") or "Lead") if lead else "Lead"
            sb.table("deals").insert({
                "lead_id": lead_id,
                "title": f"{lead_name} - Opt-out",
                "stage": "novo",
                "pipeline_id": BLACKLIST_PIPELINE_ID,
                "stage_id": BLACKLIST_STAGE_ID,
            }).execute()
            logger.info(
                "move_lead_deals_to_blacklist: nenhum deal existente — deal de opt-out criado na Blacklist para lead %s",
                lead_id,
            )
    except Exception as exc:
        logger.error(
            "move_lead_deals_to_blacklist: erro ao mover deals para Blacklist para lead %s: %s",
            lead_id, exc, exc_info=True,
        )


def _perdido_stage_id(sb, pipeline_id: str | None) -> str | None:
    """Resolve o stage_id de 'Perdido' dentro de um pipeline (key in perdido/fechado_perdido)."""
    if not pipeline_id:
        return None
    res = (
        sb.table("pipeline_stages")
        .select("id, key")
        .eq("pipeline_id", pipeline_id)
        .in_("key", ["perdido", "fechado_perdido"])
        .order("order_index", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["id"] if res.data else None


def _perdido_target_for_category(sb, category: str | None) -> tuple[str | None, str | None]:
    """(pipeline_id, stage_id) do 'Perdido' para a categoria do lead — mesma resolucao de create_deal."""
    pipeline_id: str | None = None
    pipeline_name = CATEGORY_PIPELINE_NAMES.get(category or "")
    if pipeline_name:
        p = sb.table("pipelines").select("id").eq("name", pipeline_name).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]
    if not pipeline_id:
        p = sb.table("pipelines").select("id").order("order_index", desc=False).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]
    return pipeline_id, _perdido_stage_id(sb, pipeline_id)


def move_lead_deals_to_perdido(lead_id: str, reason: str) -> None:
    """Move os deals do lead para o stage 'Perdido' do PROPRIO pipeline (Soft Rejection).

    Diferente do opt-out (que joga tudo no pipeline Blacklist), uma rejeicao branda mantem o
    deal no pipeline de origem e so o move para o stage Perdido daquele pipeline, registrando
    lost_reason/closed_at. Se o lead ainda nao tem deal, cria um no Perdido do pipeline da sua
    categoria. Fail-soft: nunca levanta (descarte nao pode quebrar por problema de deal).
    """
    try:
        sb = get_supabase()
        now_iso = datetime.now(timezone.utc).isoformat()
        deals = sb.table("deals").select("id, pipeline_id").eq("lead_id", lead_id).execute()
        if deals.data:
            for deal in deals.data:
                stage_id = _perdido_stage_id(sb, deal.get("pipeline_id"))
                update: dict[str, Any] = {
                    "stage": "perdido",
                    "lost_reason": reason,
                    "closed_at": now_iso,
                    "updated_at": now_iso,
                }
                if stage_id:
                    update["stage_id"] = stage_id
                sb.table("deals").update(update).eq("id", deal["id"]).execute()
            logger.info(
                "move_lead_deals_to_perdido: %d deal(s) movidos para Perdido para lead %s",
                len(deals.data), lead_id,
            )
        else:
            lead = get_lead(lead_id) or {}
            category = lead.get("stage")
            lead_name = lead.get("name") or lead.get("phone") or "Lead"
            pipeline_id, stage_id = _perdido_target_for_category(sb, category)
            sb.table("deals").insert({
                "lead_id": lead_id,
                "title": f"{lead_name} - Sem interesse",
                "stage": "perdido",
                "category": category,
                "pipeline_id": pipeline_id,
                "stage_id": stage_id,
                "lost_reason": reason,
                "closed_at": now_iso,
            }).execute()
            logger.info(
                "move_lead_deals_to_perdido: nenhum deal existente — deal Perdido criado para lead %s",
                lead_id,
            )
    except Exception as exc:
        logger.error(
            "move_lead_deals_to_perdido: erro ao mover deals para Perdido para lead %s: %s",
            lead_id, exc, exc_info=True,
        )


def apply_optout_side_effects(lead_id: str, phone: str, reason: str) -> None:
    """Shared opt-out side-effects: move the lead's deals to Blacklist and cancel follow-ups.

    Both the `registrar_optout` tool and the manual POST /api/leads/{id}/optout endpoint
    call this so the sequence lives in ONE place — a future change (e.g. also removing from
    active campaigns) is made once. Callers keep their own ai_enabled disabling and system
    message (which legitimately differ). Fail-soft: never raises.

    `cancel_followups_by_phone` is imported lazily to avoid a circular import
    (app.follow_up.service imports from app.leads.service).
    """
    move_lead_deals_to_blacklist(lead_id)  # already fail-soft internally
    if phone:
        try:
            from app.follow_up.service import cancel_followups_by_phone
            cancel_followups_by_phone(phone, reason=reason)
        except Exception as exc:
            logger.error(
                "apply_optout_side_effects: falha ao cancelar follow-ups para lead %s (phone %s): %s",
                lead_id, phone, exc, exc_info=True,
            )


def get_history(lead_id: str, limit: int = 30) -> list[dict[str, Any]]:
    sb = get_supabase()
    result = (
        sb.table("messages")
        .select("role, content, stage, created_at")
        .eq("lead_id", lead_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data
