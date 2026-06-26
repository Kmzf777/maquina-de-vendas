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


# Caractere que denuncia "handle"/username em vez de nome real (dígito ou underscore).
# Ex.: "Brunor_barista", "cassianofonseca15" — usar como nome próprio soa robótico
# ("Falo com Brunor_barista neste número?"). Nesses casos preferimos "sem nome".
_HANDLE_CHAR_RE = re.compile(r"[0-9_]")
# Lixo de importação/CRM que não pode ir pro WhatsApp do cliente como nome
# (ex.: "João - Import - Leads Frios"). Marcadores: separador " - " e palavras de import.
_IMPORT_GARBAGE_RE = re.compile(
    r"(\s-\s|\bimport\b|leads?\s+frios?|lead\s+frio|sem\s+nome|desconhecid)",
    re.IGNORECASE,
)


def sanitize_display_name(name: str | None) -> str | None:
    """Retorna o nome se parecer um nome real; None se parecer handle/username ou lixo de import.

    None faz o fluxo cair naturalmente em "sem nome" (a Valéria pergunta o nome em vez de
    chamar o lead por um handle; o template do disparo usa "você"). Conservador: só descarta
    com sinal claro — handle (dígito/underscore) ou marcador de lixo de importação/CRM —
    pra não derrubar nomes legítimos como "João Silva".
    """
    if not name:
        return None
    n = name.strip()
    if not n:
        return None
    if _HANDLE_CHAR_RE.search(n):
        return None
    if _IMPORT_GARBAGE_RE.search(n):
        return None
    return n


# Estágios de deal que indicam relacionamento ativo (em tratativa humana). 'novo' é o
# estado default da massa e fica DE FORA de propósito.
_ACTIVE_DEAL_STAGES: tuple[str, ...] = ("ja_chamado",)
# Estágios de deal que indicam negócio fechado positivamente (closed-won) no CRM.
_WON_DEAL_STAGES: tuple[str, ...] = ("fechado_ganho",)
# Estágios de perda — usados para EXCLUIR da heurística de closed-won por closed_at.
_LOST_DEAL_STAGES: tuple[str, ...] = ("perdido", "fechado_perdido")


def lead_has_active_relationship(lead_id: str) -> bool:
    """True se o lead já é cliente / está em tratativa humana.

    Sinal de "já é cliente / já em atendimento", usado para (a) excluir de disparo frio
    de prospecção e (b) avisar a Valéria (lead_is_customer). Fail-open=False: em erro,
    retorna False (não bloqueia o fluxo nem o disparo por causa da checagem).

    Ponte runtime do Gap E (sem alterar schema): além do estágio de tratativa, consulta a
    tabela `sales` (qualquer venda registrada = cliente definitivo) e os deals em
    closed-won (`fechado_ganho`), pegando clientes reais que o disparo tratava como frios
    (auditoria 2026-06-22: Jéssica e Kadi Guth, clientes ativas com deal ainda em 'novo').
    """
    if not lead_id:
        return False
    try:
        sb = get_supabase()
        # (1) Venda registrada na tabela `sales` = cliente definitivo (sinal mais forte).
        sale = sb.table("sales").select("id").eq("lead_id", lead_id).limit(1).execute()
        if sale.data:
            return True
        # (2) Deal em tratativa humana (ja_chamado) ou fechado-ganho (closed-won).
        deal = (
            sb.table("deals").select("id")
            .eq("lead_id", lead_id)
            .in_("stage", list(_ACTIVE_DEAL_STAGES + _WON_DEAL_STAGES))
            .limit(1).execute()
        )
        if deal.data:
            return True
        # (3) Heurística legada: deal fechado (closed_at setado) que NÃO é de perda.
        closed_won = (
            sb.table("deals").select("id")
            .eq("lead_id", lead_id)
            .filter("stage", "not.in", f"({','.join(_LOST_DEAL_STAGES)})")
            .filter("closed_at", "not.is", "null")
            .limit(1).execute()
        )
        return bool(closed_won.data)
    except Exception as exc:
        logger.warning("leads.service: lead_has_active_relationship falhou p/ %s: %s", lead_id, exc)
        return False


def is_lead_blacklisted(lead_id: str) -> bool:
    """True se o lead está na BLACKLIST e NÃO pode receber disparo outbound ativo.

    Critério (hard opt-out — proibição definitiva de contato):
      - leads.opt_out IS TRUE  (canônico — setado por registrar_optout), OU
      - o lead tem QUALQUER deal no pipeline Blacklist (BLACKLIST_PIPELINE_ID) — cobre o
        caso de lead movido para a Blacklist sem o flag opt_out (defesa em profundidade).

    NÃO inclui stage='perdido' (SOFT rejection — registrar_sem_interesse_atual mantém
    opt_out=False e o lead é reativável; excluí-lo aqui quebraria campanhas de reativação).

    Fail-open=False: erro de checagem retorna False (não bloqueia o disparo por causa da
    checagem), espelhando lead_has_active_relationship. A proteção real vem das DUAS camadas
    (filtro na criação + guardrail no envio), não de fail-closed.
    """
    if not lead_id:
        return False
    try:
        sb = get_supabase()
        lead = sb.table("leads").select("opt_out").eq("id", lead_id).limit(1).execute()
        if lead.data and lead.data[0].get("opt_out"):
            return True
        deal = (
            sb.table("deals").select("id")
            .eq("lead_id", lead_id)
            .eq("pipeline_id", BLACKLIST_PIPELINE_ID)
            .limit(1).execute()
        )
        return bool(deal.data)
    except Exception as exc:
        logger.warning("leads.service: is_lead_blacklisted falhou p/ %s: %s", lead_id, exc)
        return False


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
    # Não persistir handle/username (ex.: push_name "Brunor_barista") como nome do lead.
    name = sanitize_display_name(name)
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


# Categoria (stage do lead) → NOME REAL do pipeline (verificado em prod, `pipelines`).
# Antes apontava para nomes curtos ('Atacado', 'Private Label', ...) que NÃO existem —
# create_deal caía sempre no fallback (1º pipeline por order_index). Corrigido para os
# nomes reais dos funis de produto da Valéria/Arthur.
CATEGORY_PIPELINE_NAMES: dict[str, str] = {
    "atacado": "Valeria - Atacado",
    "private_label": "Valeria - Private Label",
    "exportacao": "Arthur - Exportação",
    "consumo": "Valeria - Consumo",
}

# Roteamento de HANDOFF EXCLUSIVO para cards de LP: quando o lead qualificado já tem um
# card aberto num funil de ENTRADA da Valéria (criado no disparo de boas-vindas da LP), o
# encaminhar_humano MOVE o card para o funil de FECHAMENTO do vendedor (João), na 1ª coluna
# não-protegida. Leads sem card em funil de LP não são afetados (seguem o fluxo padrão).
LP_HANDOFF_PIPELINE_ROUTES: dict[str, str] = {
    "Valeria - Atacado": "João - Atacado",
    "Valeria - Private Label": "João - Private Label",
}


# Destino de HANDOFF por SEGMENTO (independe do pipeline de origem do card).
# Generaliza LP_HANDOFF_PIPELINE_ROUTES: garante que atacado/private_label/exportacao
# cheguem ao board do vendedor venham de LP, broadcast ou inbound (auditoria 2026-06-22:
# broadcast-qualificados ficavam presos em 'Valeria - Importação Leads Frios').
# 'consumo' fica DE FORA de proposito (self-service; sem pipeline de vendedor dedicado).
SEGMENT_HANDOFF_PIPELINE: dict[str, str] = {
    "atacado":       "João - Atacado",
    "private_label": "João - Private Label",
    "exportacao":    "Arthur - Exportação",
}


def move_deal_to_vendor_pipeline(
    lead_id: str, segment: str | None, title: str | None = None
) -> dict[str, Any] | None:
    """Move o deal ABERTO do lead (qualquer origem) para o pipeline do vendedor do segmento.

    Resolve o destino por SEGMENTO (lead.stage) via SEGMENT_HANDOFF_PIPELINE, move o card
    aberto para a 1ª coluna não-protegida do destino (e atualiza o título), ou cria um card
    lá se o lead ainda não tiver deal aberto. Retorna None quando o segmento não tem pipeline
    de vendedor mapeado (ex.: consumo/secretaria) — o chamador então usa o fallback.
    Fail-soft: erro é logado e retorna None (nunca derruba o handoff).
    """
    dest_name = SEGMENT_HANDOFF_PIPELINE.get((segment or "").strip())
    if not dest_name:
        return None
    try:
        sb = get_supabase()
        dp = sb.table("pipelines").select("id").eq("name", dest_name).limit(1).execute()
        if not dp.data:
            logger.warning(
                "move_deal_to_vendor_pipeline: pipeline destino '%s' inexistente — lead %s",
                dest_name, lead_id,
            )
            return None
        dest_pipeline_id = dp.data[0]["id"]
        dest_stage_id = _first_unprotected_stage_id(sb, dest_pipeline_id)

        deal = get_open_deal(lead_id)
        if deal:
            update: dict[str, Any] = {
                "pipeline_id": dest_pipeline_id,
                "stage_id": dest_stage_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if title:
                update["title"] = title
            res = sb.table("deals").update(update).eq("id", deal["id"]).execute()
            logger.info(
                "move_deal_to_vendor_pipeline: card %s movido p/ '%s' por segmento '%s' (lead %s)",
                deal["id"], dest_name, segment, lead_id,
            )
            return res.data[0] if res.data else {**deal, **update}
        # Sem deal aberto: cria no pipeline do vendedor.
        return create_deal(lead_id, title=title or "Handoff", pipeline_name=dest_name)
    except Exception as exc:
        logger.error(
            "move_deal_to_vendor_pipeline: falha ao mover card do lead %s (segmento %s): %s",
            lead_id, segment, exc, exc_info=True,
        )
        return None


# ── Tags (etiquetas de CRM aplicadas pela IA) ───────────────────────────────
def add_tags_to_lead(lead_id: str, names: list[str]) -> list[str]:
    """Aplica tags (por NOME) a um lead, gravando em lead_tags com dedupe.

    Segurança: resolve o tag_id por nome EXATO na tabela `tags` (já semeada) e NUNCA cria
    tags novas — nomes inexistentes são ignorados. Pares (lead_id, tag_id) já existentes
    não são reinseridos. Fail-soft: em erro, retorna o que conseguiu (ou []).
    Retorna os nomes efetivamente aplicados nesta chamada.
    """
    if not lead_id or not names:
        return []
    try:
        sb = get_supabase()
        rows = sb.table("tags").select("id, name").in_("name", list({*names})).execute()
        by_name = {r["name"]: r["id"] for r in (rows.data or [])}
        if not by_name:
            return []
        existing = sb.table("lead_tags").select("tag_id").eq("lead_id", lead_id).execute()
        already = {r["tag_id"] for r in (existing.data or [])}
        applied: list[str] = []
        to_insert: list[dict[str, str]] = []
        for nm in names:
            tag_id = by_name.get(nm)
            if tag_id and tag_id not in already:
                to_insert.append({"lead_id": lead_id, "tag_id": tag_id})
                already.add(tag_id)
                applied.append(nm)
        if to_insert:
            sb.table("lead_tags").insert(to_insert).execute()
        return applied
    except Exception as exc:
        logger.error("add_tags_to_lead: falha ao aplicar tags %s p/ lead %s: %s", names, lead_id, exc)
        return []


def get_lead(lead_id: str) -> dict[str, Any] | None:
    sb = get_supabase()
    result = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    return result.data[0] if result.data else None


def get_open_deal(lead_id: str) -> dict[str, Any] | None:
    """Retorna o deal ABERTO (closed_at IS NULL) mais recente do lead, ou None.

    'Aberto' = ainda não fechado (nem ganho nem perdido). Serve como guard de
    idempotência para não duplicar cards: quando um card já nasceu antes (ex.: disparo
    de boas-vindas da LP cria o card em 'Valeria - X / Entrada') e depois a IA chama
    encaminhar_humano, queremos reaproveitar esse card em vez de criar um segundo.

    Fail-soft: em caso de erro de consulta retorna None (o chamador decide criar) —
    nunca levanta para não derrubar o fluxo que a chamou.
    """
    sb = get_supabase()
    try:
        res = (
            sb.table("deals")
            .select("id, title, pipeline_id, stage_id, category")
            .eq("lead_id", lead_id)
            .is_("closed_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(
            "get_open_deal: falha ao buscar deal aberto do lead %s: %s", lead_id, exc, exc_info=True
        )
        return None
    return res.data[0] if res.data else None


def create_deal(
    lead_id: str,
    title: str,
    category: str | None = None,
    *,
    pipeline_name: str | None = None,
    stage_label: str | None = None,
    dedupe_open: bool = False,
) -> dict[str, Any]:
    """Cria um deal (card de CRM) para o lead.

    Resolução do PIPELINE (precedência):
      1. `pipeline_name` explícito (ex.: 'Valeria - Atacado') — usado pelo roteamento de LP.
      2. `category` → CATEGORY_PIPELINE_NAMES.
      3. fallback: primeiro pipeline por order_index.
    Se um nome explícito/por categoria não existir naquele ambiente (ex.: pipelines da
    Valeria não existem no homolog), cai no fallback — o código roda em dev e prod sem
    modificação, só muda o dado.

    Resolução do STAGE: se `stage_label` for informado e existir no pipeline resolvido
    (ex.: 'Entrada'), usa-o; senão a primeira coluna não-protegida por order_index.

    `dedupe_open=True`: se o lead já tiver um deal aberto, reaproveita-o e NÃO insere outro
    (retorna o existente). Evita cards duplicados no fluxo LP→inbound→encaminhar_humano.
    """
    sb = get_supabase()

    if dedupe_open:
        existing = get_open_deal(lead_id)
        if existing:
            logger.info(
                "create_deal: lead %s já possui deal aberto %s — reaproveitando (sem duplicar)",
                lead_id, existing.get("id"),
            )
            return existing

    pipeline_id: str | None = None
    stage_id: str | None = None

    # (1) pipeline explícito por nome
    if pipeline_name:
        p = sb.table("pipelines").select("id").eq("name", pipeline_name).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    # (2) pipeline derivado da categoria
    if not pipeline_id:
        cat_pipeline_name = CATEGORY_PIPELINE_NAMES.get(category or "")
        if cat_pipeline_name:
            p = sb.table("pipelines").select("id").eq("name", cat_pipeline_name).limit(1).execute()
            if p.data:
                pipeline_id = p.data[0]["id"]

    # (3) fallback: primeiro pipeline
    if not pipeline_id:
        p = sb.table("pipelines").select("id").order("order_index", desc=False).limit(1).execute()
        if p.data:
            pipeline_id = p.data[0]["id"]

    if pipeline_id:
        # Stage por label explícito (ex.: 'Entrada'); senão 1ª coluna não-protegida.
        if stage_label:
            s = (
                sb.table("pipeline_stages")
                .select("id")
                .eq("pipeline_id", pipeline_id)
                .eq("label", stage_label)
                .limit(1)
                .execute()
            )
            if s.data:
                stage_id = s.data[0]["id"]
        if not stage_id:
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


# ── Resolução de stage por key (autoritativa) com fallback por label ─────────
# Keys estáveis do funil 'Valeria - Importação Leads Frios' (migration
# 20260625_valeria_coldfunnel_stage_keys). O reflexo de reply e as tools de pipeline
# resolvem por `key` (robusto a renome no CRM) e caem no label só como rede de segurança.
COLD_DISPARO_KEY = "disparo_feito"
COLD_RESPONDEU_KEY = "respondeu"
COLD_QUALIFICADO_KEY = "qualificado"
COLD_ENCERRADO_KEY = "encerrado"


def stage_id_by_key(
    sb, pipeline_id: str | None, key: str, label_fallback: str | None = None
) -> str | None:
    """Resolve o stage_id por `key` dentro de um pipeline; fallback por `label` exato.

    Fail-soft: erro de consulta → None (o chamador decide o no-op).
    """
    if not pipeline_id:
        return None
    try:
        r = (
            sb.table("pipeline_stages")
            .select("id")
            .eq("pipeline_id", pipeline_id)
            .eq("key", key)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]["id"]
        if label_fallback:
            r = (
                sb.table("pipeline_stages")
                .select("id")
                .eq("pipeline_id", pipeline_id)
                .eq("label", label_fallback)
                .limit(1)
                .execute()
            )
            if r.data:
                return r.data[0]["id"]
    except Exception as exc:
        logger.error(
            "stage_id_by_key: falha ao resolver stage key=%s pipeline=%s: %s",
            key, pipeline_id, exc,
        )
    return None


def advance_cold_deal_on_reply(lead_id: str) -> bool:
    """REFLEXO DE SISTEMA (sem LLM): card aberto em 'Disparo feito' → 'Respondeu'.

    Disparado quando o lead responde a um disparo. Idempotente e auto-escopado ao funil
    frio: só age quando o stage ATUAL do card é exatamente o 'disparo_feito' do pipeline
    dele — nunca regride 'Respondeu'/'Qualificado'/'Encerrado'. Outros funis (vendedor,
    produto) não têm o par disparo_feito/respondeu → no-op natural.

    Fail-soft: nunca levanta (não pode derrubar o processamento do inbound).
    Retorna True só quando moveu o card.
    """
    try:
        sb = get_supabase()
        deal = get_open_deal(lead_id)
        if not deal or not deal.get("pipeline_id") or not deal.get("stage_id"):
            return False
        pipeline_id = deal["pipeline_id"]
        disparo_id = stage_id_by_key(sb, pipeline_id, COLD_DISPARO_KEY, "Disparo feito")
        if not disparo_id or deal["stage_id"] != disparo_id:
            return False  # não está em 'Disparo feito' → nada a fazer (não regride)
        respondeu_id = stage_id_by_key(sb, pipeline_id, COLD_RESPONDEU_KEY, "Respondeu")
        if not respondeu_id:
            return False
        sb.table("deals").update({
            "stage_id": respondeu_id,
            "stage": "respondeu",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", deal["id"]).execute()
        logger.info(
            "advance_cold_deal_on_reply: card %s movido 'Disparo feito' → 'Respondeu' (lead %s)",
            deal["id"], lead_id,
        )
        return True
    except Exception as exc:
        logger.error(
            "advance_cold_deal_on_reply: falha p/ lead %s: %s", lead_id, exc, exc_info=True
        )
        return False


def move_deal_to_stage_key(
    lead_id: str, key: str, label_fallback: str | None = None
) -> bool:
    """Move o deal ABERTO do lead para o stage `key` DENTRO do pipeline atual do card.

    Não troca de pipeline — só reposiciona a coluna. No-op (False) se não há deal aberto ou
    se o pipeline atual não tem aquele stage (ex.: lead já no funil do vendedor). Idempotente.
    Fail-soft: erro nunca levanta. Usado pelas tools da IA (ex.: marcar_interesse → Qualificado).
    """
    try:
        sb = get_supabase()
        deal = get_open_deal(lead_id)
        if not deal or not deal.get("pipeline_id"):
            return False
        stage_id = stage_id_by_key(sb, deal["pipeline_id"], key, label_fallback)
        if not stage_id:
            return False
        if deal.get("stage_id") == stage_id:
            return True  # já está no stage alvo
        sb.table("deals").update({
            "stage_id": stage_id,
            "stage": key,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", deal["id"]).execute()
        logger.info(
            "move_deal_to_stage_key: card %s → stage '%s' (lead %s)", deal["id"], key, lead_id
        )
        return True
    except Exception as exc:
        logger.error(
            "move_deal_to_stage_key: falha p/ lead %s (key %s): %s",
            lead_id, key, exc, exc_info=True,
        )
        return False


def _first_unprotected_stage_id(sb, pipeline_id: str) -> str | None:
    """Retorna o stage_id da 1ª coluna não-protegida do pipeline (ex.: 'Novo')."""
    s = (
        sb.table("pipeline_stages")
        .select("id")
        .eq("pipeline_id", pipeline_id)
        .eq("is_protected", False)
        .order("order_index", desc=False)
        .limit(1)
        .execute()
    )
    return s.data[0]["id"] if s.data else None


def move_open_deal_for_handoff(lead_id: str, title: str | None = None) -> dict[str, Any] | None:
    """MOVE o card de LP do lead para o funil de fechamento do vendedor (handoff).

    Escopo EXCLUSIVO de LP: só atua quando o lead tem um deal ABERTO cujo pipeline atual é
    um funil de ENTRADA da Valéria mapeado em LP_HANDOFF_PIPELINE_ROUTES
    ('Valeria - Atacado' / 'Valeria - Private Label'). Nesse caso faz UPDATE do card —
    pipeline_id + stage_id (1ª coluna não-protegida do destino, ex.: 'Novo') e, se informado,
    o título — e retorna o deal atualizado.

    Retorna None quando NÃO há card de LP a mover (sem deal aberto, ou o deal está em outro
    funil): o chamador então segue o fluxo padrão (create_deal). Assim, leads que não vieram
    de LP não são afetados.

    Fail-soft: qualquer erro é logado e retorna None (o chamador decide o fallback) — nunca
    levanta, para não derrubar o handoff.
    """
    try:
        sb = get_supabase()
        deal = get_open_deal(lead_id)
        if not deal or not deal.get("pipeline_id"):
            return None

        p = sb.table("pipelines").select("name").eq("id", deal["pipeline_id"]).limit(1).execute()
        src_name = p.data[0]["name"] if p.data else None
        dest_name = LP_HANDOFF_PIPELINE_ROUTES.get(src_name or "")
        if not dest_name:
            return None  # card não está num funil de entrada de LP → não mexe

        dp = sb.table("pipelines").select("id").eq("name", dest_name).limit(1).execute()
        if not dp.data:
            logger.warning(
                "move_open_deal_for_handoff: pipeline destino '%s' inexistente — card %s mantido",
                dest_name, deal["id"],
            )
            return None
        dest_pipeline_id = dp.data[0]["id"]
        dest_stage_id = _first_unprotected_stage_id(sb, dest_pipeline_id)

        update: dict[str, Any] = {
            "pipeline_id": dest_pipeline_id,
            "stage_id": dest_stage_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if title:
            update["title"] = title
        res = sb.table("deals").update(update).eq("id", deal["id"]).execute()
        logger.info(
            "move_open_deal_for_handoff: card %s movido '%s' → '%s' (lead %s)",
            deal["id"], src_name, dest_name, lead_id,
        )
        return res.data[0] if res.data else {**deal, **update}
    except Exception as exc:
        logger.error(
            "move_open_deal_for_handoff: falha ao mover card do lead %s: %s",
            lead_id, exc, exc_info=True,
        )
        return None


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
    """Resolve o stage_id de fechamento por perda dentro de um pipeline.

    Aceita as keys 'perdido'/'fechado_perdido' (funis de produto/vendedor) E 'encerrado'
    (funil 'Importação Leads Frios', que não tem coluna 'Perdido'). Sem essa última, a
    soft-rejection marcava o card como closed mas o deixava preso em 'Disparo feito'
    (auditoria 2026-06-25). Pega o maior order_index entre os candidatos.
    """
    if not pipeline_id:
        return None
    res = (
        sb.table("pipeline_stages")
        .select("id, key")
        .eq("pipeline_id", pipeline_id)
        .in_("key", ["perdido", "fechado_perdido", "encerrado"])
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
