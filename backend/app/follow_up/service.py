import logging
import os
import random
import uuid
from datetime import datetime, timezone, timedelta, time
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.db.supabase import get_supabase
from app.events.bus import emit_event
from app.channels.service import get_channel_by_provider_config
from app.conversations.service import get_or_create_conversation
from app.follow_up.cadence_joao import (
    ADIAMENTO_ESTOQUE,
    FUNIS,
    JOB_TYPES as JOAO_JOB_TYPES,
    RESPOSTA_ADIAR,
    RESPOSTA_OPTOUT,
    CadenciaResolvida,
    Touch,
    adiar_toques,
    cadencia_do_funil,
    classificar_resposta,
    resolver,
)

logger = logging.getLogger(__name__)

_ENV_TAG = "dev" if get_settings().is_dev_env else "production"

_SP_TZ = ZoneInfo("America/Sao_Paulo")
_BUSINESS_START = time(9, 0)
_BUSINESS_END = time(16, 0)

# 1o follow-up NUNCA "cravado em 1h" (robotico, cara de cobranca de vendas). Sorteia um
# intervalo natural entre ~1.5h e ~3.5h; o clamp de janela comercial ainda se aplica.
_SEQ1_MIN_MINUTES = 90
_SEQ1_MAX_MINUTES = 210


def is_within_business_window(target: datetime) -> bool:
    """True se `target` (UTC) cai na janela comercial 09h-16h, seg-sex, America/Sao_Paulo."""
    local = target.astimezone(_SP_TZ)
    return local.weekday() < 5 and _BUSINESS_START <= local.time() < _BUSINESS_END


def _clamp_to_business_window(target: datetime) -> datetime:
    """Garante que `target` (UTC) caia na janela comercial 09h-16h, seg-sex,
    America/Sao_Paulo. Se estiver fora, empurra para o proximo horario valido
    (mesmo dia 09h se for antes da janela; proximo dia util 09h se for depois
    da janela ou fim de semana).
    """
    local = target.astimezone(_SP_TZ)

    if is_within_business_window(target):
        return target

    if local.weekday() < 5 and local.time() < _BUSINESS_START:
        clamped_local = local.replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        return clamped_local.astimezone(timezone.utc)

    # Fora da janela (>= 16h) ou fim de semana: avanca para o proximo dia util as 09h.
    next_day = local + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    clamped_local = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
    return clamped_local.astimezone(timezone.utc)


# Janela PROPRIA do rescue de handoff — mais ampla que a comercial (09h-16h) usada
# pelo resto do follow-up (schedule_followup/build_touch_jobs/schedule_ai_return,
# via _clamp_to_business_window acima, que continua INTOCADA). Casos reais (Frente B,
# Task 2): Edgar mandou msg as 17:22 e Davi as 15:47 — ambos DEPOIS do fim da janela
# comercial (16h) mas em horario em que um vendedor humano tipicamente ainda esta
# ativo; o aviso ao Joao (`schedule_handoff_rescue`) empurrava os dois pro dia
# seguinte as 09h, um atraso artificial de horas. O rescue e uma notificacao pontual
# ao vendedor (nao uma cadencia automatica de mensagens ao lead) — pode se dar ao
# luxo de uma janela mais ampla sem contaminar a comercial.
_RESCUE_START = time(9, 0)
_RESCUE_END = time(20, 0)


def _clamp_to_rescue_window(target: datetime) -> datetime:
    """Garante que `target` (UTC) caia na janela do rescue de handoff (09h-20h,
    seg-sex, America/Sao_Paulo). Mesma mecanica de `_clamp_to_business_window`
    (empurra pro mesmo dia 09h se for antes da janela; proximo dia util 09h se for
    depois ou fim de semana) — so o fim muda, de 16h para 20h. Usada exclusivamente
    por `schedule_handoff_rescue`; NAO afeta `_clamp_to_business_window` nem quem
    a chama.
    """
    local = target.astimezone(_SP_TZ)

    if local.weekday() < 5 and _RESCUE_START <= local.time() < _RESCUE_END:
        return target

    if local.weekday() < 5 and local.time() < _RESCUE_START:
        clamped_local = local.replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        return clamped_local.astimezone(timezone.utc)

    # Fora da janela (>= 20h) ou fim de semana: avanca para o proximo dia util as 09h.
    next_day = local + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    clamped_local = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
    return clamped_local.astimezone(timezone.utc)


def _already_touched_today(conversation_id: str, now: datetime) -> bool:
    """True se esta conversa já recebeu um toque de cadência ENVIADO hoje (America/Sao_Paulo).

    Trava anti-bombardeio (Erro 2): a cadência é re-armada a cada turno do agente (idempotência
    cancela só os pending e recria), então um lead morno que responde e some várias vezes recebia
    múltiplos T1 same-day no mesmo dia (produção: lead 5519981518080, toques 11:42 e 14:26).
    Fail-open: erro de DB → False (nunca bloqueia o agendamento por falha de leitura).
    """
    try:
        local_now = now.astimezone(_SP_TZ)
        day_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = day_start_local.astimezone(timezone.utc).isoformat()
        day_end = (day_start_local + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        res = (
            get_supabase().table("follow_up_jobs")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("status", "sent")
            .eq("job_type", "standard")
            .gte("sent_at", day_start)
            .lt("sent_at", day_end)
            .limit(1)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.warning(
            "[FOLLOWUP] falha ao checar toque same-day conv=%s: %s — fail-open", conversation_id, exc
        )
        return False


def lead_marked_wrong_number(lead: dict | None) -> bool:
    """True se o lead está marcado como número errado (`metadata.wrong_number_at`).

    A marca nasce em `registrar_numero_errado` e é removida quando o dono real
    responde (broadcast/worker.process_wrong_number_deadends limpa a chave) — então
    a checagem pontual reflete o estado vigente. Caso Maria (10/07): negou ser a
    dona do número e AINDA recebeu o reopen D+1, porque nada entre a marcação e o
    deadend de 72h suprimia cadência/reopen. Fail-safe: lead None/sem metadata →
    False (na dúvida, o fluxo normal segue).
    """
    if not isinstance(lead, dict):
        return False
    meta = lead.get("metadata") or {}
    if not isinstance(meta, dict):
        return False
    return bool(meta.get("wrong_number_at"))


def schedule_followup(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    warm: bool = True,
    outbound: bool = False,
) -> None:
    """Cancela jobs pendentes anteriores desta conversa e insere a cadência via build_touch_jobs.

    `warm=True` (default): cadência completa (T1 same-day). `warm=False` (lead frio sem interesse):
    suprime o T1 — cadência começa no T2 (anti-bombardeio). `outbound=True` (persona
    valeria_outbound): o frio ganha o nudge "retomar_pos_sim" a +18h no lugar do T1 suprimido
    (Onda 2 — "Sim-e-sumiu" dentro da janela de 24h da Meta).
    """
    sb = get_supabase()
    now = datetime.now(timezone.utc)

    # Verifica se a conversa existe
    try:
        conv_check = (
            sb.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao verificar existência da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao verificar conversa {conversation_id} no banco de dados"
        ) from exc

    if not conv_check.data:
        raise ValueError(
            f"conversation_id '{conversation_id}' não existe na tabela conversations"
        )

    # Número errado (caso Maria, 10/07): quem negou ser o dono do número não recebe
    # cadência nem reopen. Cancela os pending (mesma lista de preservação do
    # reschedule) e NÃO insere toques novos — a marca vale até o deadend de 72h
    # (broadcast/worker.process_wrong_number_deadends) resolver o destino do lead.
    # Fail-open: erro na releitura nunca bloqueia o agendamento.
    try:
        lead_row = (
            sb.table("leads").select("id, metadata").eq("id", lead_id).single().execute().data
        )
    except Exception as exc:
        logger.warning(
            "[FOLLOWUP] falha ao checar wrong_number do lead %s: %s — fail-open",
            lead_id, exc,
        )
        lead_row = None
    if lead_marked_wrong_number(lead_row):
        try:
            sb.table("follow_up_jobs").update({
                "status": "cancelled",
                "cancel_reason": "wrong_number",
            }).eq("conversation_id", conversation_id).eq("status", "pending").not_.in_(
                "job_type", ["handoff_rescue", "lp_welcome", "ai_scheduled_return"]
            ).execute()
        except Exception as exc:
            logger.error(
                "[FOLLOWUP] erro ao cancelar pending de lead wrong_number conv=%s: %s",
                conversation_id, exc,
            )
        logger.info(
            "[FOLLOWUP] lead %s marcado wrong_number — cadência suprimida conversation=%s",
            lead_id, conversation_id,
        )
        return

    # Cancela pending da mesma conversa (idempotência).
    # Preserva lp_welcome — é independente do ciclo de follow-up manual.
    # Preserva ai_scheduled_return — agendado explicitamente pela IA via agendar_retorno;
    # um novo turno do cliente NÃO deve cancelar um retorno que a própria IA prometeu.
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": "rescheduled",
        }).eq("conversation_id", conversation_id).eq("status", "pending").not_.in_(
            "job_type", ["handoff_rescue", "lp_welcome", "ai_scheduled_return"]
        ).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar jobs anteriores da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs pendentes para conversa {conversation_id}"
        ) from exc

    # Cadência multi-touch — config-as-code em follow_up/cadence.py.
    # warm=True: 4 toques (T1 same-day). warm=False (lead frio): 3 toques (T1 suprimido, começa no T2).
    # fire_at monotônico (espaçado >= MIN_GAP) e clampado à janela comercial.
    # Trava de cap same-day (Erro 2): se já houve toque enviado hoje, suprime o novo T1 same-day
    # (warm efetivo = warm pedido E ainda não tocou hoje). Mantém a supressão do lead frio também.
    effective_warm = warm and not _already_touched_today(conversation_id, now)
    from app.follow_up.cadence import build_touch_jobs
    jobs = build_touch_jobs(
        now, conversation_id, lead_id, channel_id, _ENV_TAG,
        warm=effective_warm, outbound=outbound,
    )
    try:
        sb.table("follow_up_jobs").insert(jobs).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao inserir jobs para conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao criar follow-up jobs para conversa {conversation_id}"
        ) from exc
    emit_event("followups")  # wake-up do worker (fail-open; fallback tick cobre)

    logger.info(f"[FOLLOWUP] Agendados {len(jobs)} toques de cadência conversation={conversation_id}")


def cancel_followups(conversation_id: str, reason: str) -> None:
    """Cancela todos os jobs pending de uma conversa.

    Preserva 'handoff_rescue' (gerenciado pelo fluxo de handoff) e
    'ai_scheduled_return' (agendado explicitamente pela IA via agendar_retorno —
    quando a IA prometeu retornar ao lead, esse compromisso não deve ser
    cancelado por um simples evento de conversa).
    """
    sb = get_supabase()
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": reason,
        }).eq("conversation_id", conversation_id).eq("status", "pending").not_.in_(
            "job_type", ["handoff_rescue", "ai_scheduled_return"]
        ).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar follow-ups da conversa {conversation_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs para conversa {conversation_id}"
        ) from exc
    logger.info(f"[FOLLOWUP] Cancelado reason={reason} conversation={conversation_id}")


def _toggle_ninth_digit(number: str | None) -> str | None:
    """Alterna a presença do 9º dígito de um móvel BR em E.164 (sem '+').

    13 díg. com 9 → remove o 9 (12 díg.); 12 díg. sem 9 → injeta o 9 (13 díg.).
    None se não for um móvel BR reconhecível. Espelha broadcast/worker._toggle_br_ninth_digit
    (reimplementado aqui para não acoplar follow_up ao módulo de broadcast).
    """
    if not number:
        return None
    d = "".join(ch for ch in number if ch.isdigit())
    if len(d) == 13 and d.startswith("55") and d[4] == "9":
        return d[:4] + d[5:]
    if len(d) == 12 and d.startswith("55"):
        return d[:4] + "9" + d[4:]
    return None


def _phone_identity_values(phone: str) -> tuple[str, list[str]]:
    """Resolve a coluna e TODAS as formas que representam a mesma identidade de contato.

    Fragmentação do 9º dígito (caso 5511910402026, 15/07): o mesmo humano pode existir
    como duas linhas em `leads` — uma com o 9º dígito (13) e outra sem (12). Cancelar
    por `.eq(phone).limit(1)` limpava só uma delas e a gêmea seguia disparando. Aqui
    devolvemos as duas formas do móvel BR (via `normalize_phone` + `_toggle_ninth_digit`)
    para casar ambas. BSUID (adotante de username) não é telefone — devolvido intacto.
    """
    from app.leads.service import is_bsuid, normalize_phone
    if is_bsuid(phone):
        return "bsuid", [phone.strip()]
    normalized = normalize_phone(phone)
    values = {phone, normalized}
    toggled = _toggle_ninth_digit(normalized)
    if toggled:
        values.add(toggled)
    return "phone", [v for v in values if v]


def _preserved_job_types(preserve_scheduled_return: bool) -> list[str]:
    """Tipos de job que o cancelamento por telefone NÃO deve tocar.

    `handoff_rescue` é SEMPRE preservado: o `encaminhar_humano` cancela a cadência e
    conta que o aviso ao vendedor (rescue) sobreviva. `ai_scheduled_return` (retorno que
    a própria IA prometeu via `agendar_retorno`) é preservado apenas em cancelamentos
    NÃO-terminais (ex.: o cliente respondeu e a cadência é re-armada). Em paradas
    terminais (opt-out, handoff, sem-interesse) ele TAMBÉM é cancelado — um lead que
    pediu para sair não pode receber um retorno proativo mesmo que `ai_enabled` volte.
    """
    if preserve_scheduled_return:
        return ["handoff_rescue", "ai_scheduled_return"]
    return ["handoff_rescue"]


def cancel_followups_by_phone(
    phone: str, reason: str, *, preserve_scheduled_return: bool = True
) -> None:
    """Cancela follow-ups pending de TODAS as conversas de TODOS os leads deste número.

    `phone` pode ser um BSUID (adotante de username, cujo lead tem phone="" e é keyed
    pela coluna bsuid). Resolve as duas formas do 9º dígito BR (ver `_phone_identity_values`)
    para não deixar um lead gêmeo com cadência viva.

    `preserve_scheduled_return=False` (paradas terminais): também cancela os
    `ai_scheduled_return` — ver `_preserved_job_types`.
    """
    sb = get_supabase()
    id_col, id_values = _phone_identity_values(phone)

    try:
        lead_result = (
            sb.table("leads")
            .select("id")
            .in_(id_col, id_values)
            .execute()
        )
    except Exception as exc:
        logger.error(f"[FOLLOWUP] Erro ao buscar lead pelo phone {phone}: {exc}")
        raise RuntimeError(
            f"Falha ao buscar lead pelo phone {phone}"
        ) from exc

    if not lead_result.data:
        return

    lead_ids = [row["id"] for row in lead_result.data]

    try:
        conversations = (
            sb.table("conversations")
            .select("id")
            .in_("lead_id", lead_ids)
            .execute()
        )
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao buscar conversas dos leads {lead_ids}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao buscar conversas dos leads {lead_ids}"
        ) from exc

    if not conversations.data:
        return

    conv_ids = [c["id"] for c in conversations.data]
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled",
            "cancel_reason": reason,
        }).in_("conversation_id", conv_ids).eq("status", "pending").not_.in_(
            "job_type", _preserved_job_types(preserve_scheduled_return)
        ).execute()
    except Exception as exc:
        logger.error(
            f"[FOLLOWUP] Erro ao cancelar follow-ups pelo phone {phone}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao cancelar follow-up jobs para o phone {phone}"
        ) from exc

    logger.info(
        "[FOLLOWUP] Cancelado reason=%s phone=%s leads=%d preserve_scheduled_return=%s",
        reason, phone, len(lead_ids), preserve_scheduled_return,
    )


def schedule_handoff_rescue(
    lead_id: str,
    lead_phone: str,
    conversation_id: str,
    channel_id: str,
    delay_minutes: int = 15,
    lead_name: str = "",
    use_rescue_window: bool = True,
) -> datetime | None:
    """Agenda um job de resgate de handoff (job_type='handoff_rescue') para fire em delay_minutes.

    Retorna o `fire_at` (UTC) efetivamente agendado — clampado para a janela PROPRIA
    do rescue (09h-20h, seg-sex, ver `_clamp_to_rescue_window`) — ou None quando o
    agendamento é ignorado (REHEARSAL_MODE). O retorno permite ao chamador informar
    ao lead quando o vendedor entrará em contato.

    Janela mais ampla que a comercial (09h-16h) usada pelo resto do follow-up: casos
    Edgar (17:22) e Davi (15:47) mandavam o aviso ao João para o dia seguinte às 09h
    só por estarem depois das 16h, mesmo com o vendedor tipicamente ainda ativo até
    as 20h (ver `_clamp_to_rescue_window`). `_clamp_to_business_window` continua
    intocada para schedule_followup/build_touch_jobs/schedule_ai_return.

    `use_rescue_window=False` (fix review B2): clampa com a janela COMERCIAL
    (09h-16h) em vez da ampliada. Existe para o fallback fora-de-horário de
    `retomar_contato_vendedor` (tools._safe_schedule_reengage), que herdou a janela
    de 20h TRANSITIVAMENTE quando ela foi criada — mas ali a Valéria PROMETE
    verbalmente ao lead quando o João vai chamar, e a Global Constraint do plano da
    Frente B manda esse fluxo continuar na janela comercial 09h-16h. Os handoffs
    genuínos (encaminhar_humano) continuam no default True (janela até 20h).
    """
    if os.environ.get("REHEARSAL_MODE") == "true":
        logger.info("[HANDOFF_RESCUE] REHEARSAL_MODE ativo — rescue ignorado")
        return None
    sb = get_supabase()
    now = datetime.now(timezone.utc)
    clamp = _clamp_to_rescue_window if use_rescue_window else _clamp_to_business_window
    fire_at = clamp(now + timedelta(minutes=delay_minutes))
    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": fire_at.isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "handoff_rescue",
        "metadata": {
            "lead_phone": lead_phone,
            "lead_name": lead_name,
            "joao_phone_number_id": "1049315514934778",
            "template_name": "automacao_valeria_to_joao",
            # Locale APROVADO na Meta (message_templates): automacao_valeria_to_joao só
            # existe em `en`. pt_BR não existe → 404 #132001. Ver scheduler.JOAO_TEMPLATE_LANG.
            "language_code": "en",
        },
    }
    try:
        sb.table("follow_up_jobs").insert(job).execute()
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Erro ao inserir rescue job para lead {lead_id}: {exc}"
        )
        raise RuntimeError(
            f"Falha ao agendar job de resgate para lead {lead_id}"
        ) from exc
    emit_event("followups")  # wake-up do worker (fail-open; fallback tick cobre)
    logger.info(
        f"[HANDOFF_RESCUE] Agendado em {delay_minutes}min lead={lead_id} conversation={conversation_id} fire_at={fire_at.isoformat()}"
    )
    return fire_at


def schedule_ai_return(
    conversation_id: str,
    lead_id: str,
    channel_id: str,
    fire_at: datetime,
    metadata: dict[str, Any] | None = None,
) -> datetime:
    """Agenda um RETORNO AUTÔNOMO da IA (job_type='ai_scheduled_return') no `fire_at` pedido.

    Usado pela tool `agendar_retorno`: quando o lead marca um horário ("falo sexta"), a própria
    Valéria agenda o job, independente do motor genérico de follow-up. O `fire_at` é clampado
    para a janela comercial (09h-16h, seg-sex). Retorna o `fire_at` efetivo (clampado), para a
    tool informar ao lead o horário correto. Levanta RuntimeError em falha de insert.
    """
    clamped = _clamp_to_business_window(fire_at)
    if os.environ.get("REHEARSAL_MODE") == "true":
        logger.info("[AI_SCHEDULED_RETURN] REHEARSAL_MODE ativo — agendamento ignorado")
        return clamped
    sb = get_supabase()
    job = {
        "conversation_id": conversation_id,
        "lead_id": lead_id,
        "channel_id": channel_id,
        "sequence": 1,
        "fire_at": clamped.isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": "ai_scheduled_return",
        "metadata": metadata or {},
    }
    try:
        sb.table("follow_up_jobs").insert(job).execute()
    except Exception as exc:
        logger.error(
            "[AI_SCHEDULED_RETURN] Erro ao inserir job p/ lead %s: %s", lead_id, exc
        )
        raise RuntimeError(f"Falha ao agendar retorno para lead {lead_id}") from exc
    emit_event("followups")  # wake-up do worker (fail-open; fallback tick cobre)
    logger.info(
        "[AI_SCHEDULED_RETURN] Agendado lead=%s conv=%s fire_at=%s",
        lead_id, conversation_id, clamped.isoformat(),
    )
    return clamped


# Eixo 3B: TTL do contexto de retomada. Após o disparo de reabertura (continuar_conversa),
# o lead tem 7 dias para responder e a IA retomar o assunto. Passado isso, o contexto é
# considerado obsoleto (anti-contexto-zumbi) e descartado.
REOPEN_TTL_DAYS = 7


def _update_job_status(job_id: str, status: str, sent_at: datetime | None = None) -> None:
    payload: dict[str, Any] = {"status": status}
    if sent_at is not None:
        payload["sent_at"] = sent_at.isoformat()
    try:
        get_supabase().table("follow_up_jobs").update(payload).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("[REOPEN] falha ao atualizar job %s p/ %s: %s", job_id, status, exc)


def consume_reopen_context(conversation_id: str, now: datetime) -> str | None:
    """Retoma um retorno agendado cuja janela havia fechado (Eixo 3B).

    Se há um job `awaiting_reopen` para a conversa e o lead respondeu DENTRO do TTL de 7 dias,
    marca o job `sent` e devolve um bloco <retorno_agendado> com motivo/contexto p/ a IA retomar.
    Fora do TTL: marca `expired` e devolve None (trata como inbound orgânico). Fail-open: None.
    """
    if not conversation_id:
        return None
    try:
        res = (
            get_supabase()
            .table("follow_up_jobs")
            .select("id, sent_at, fire_at, metadata")
            .eq("conversation_id", conversation_id)
            .eq("status", "awaiting_reopen")
            .order("fire_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.warning("[REOPEN] falha ao buscar awaiting_reopen p/ conv %s: %s", conversation_id, exc)
        return None

    job = res.data[0] if res.data else None
    if not job:
        return None

    ref_str = job.get("sent_at") or job.get("fire_at")
    try:
        ref = datetime.fromisoformat(str(ref_str).replace("Z", "+00:00"))
    except Exception:
        ref = now
    if now - ref > timedelta(days=REOPEN_TTL_DAYS):
        _update_job_status(job["id"], "expired")
        logger.info("[REOPEN] contexto expirado (TTL %dd) p/ conv %s — tratando como inbound", REOPEN_TTL_DAYS, conversation_id)
        return None

    _update_job_status(job["id"], "sent", sent_at=now)
    md = job.get("metadata") or {}
    motivo = (md.get("motivo") or "").strip()
    contexto = (md.get("contexto") or "").strip()
    return (
        "<retorno_agendado>\n"
        "Você tinha combinado de retomar este contato e a janela reabriu agora que o lead respondeu. "
        + (f"Motivo combinado: {motivo}. " if motivo else "")
        + (f"Contexto: {contexto}. " if contexto else "")
        + "Retome esse ponto de forma natural e pessoal — NÃO diga que foi um lembrete automático "
        "nem mencione agendamento.\n"
        "</retorno_agendado>"
    )


def find_pending_ai_return(conversation_id: str) -> dict[str, Any] | None:
    """Retorna o job ai_scheduled_return `pending` desta conversa, se houver (Eixo 3A).

    Base da idempotência da tool `agendar_retorno`: se já existe um retorno agendado, a
    IA não deve criar outro. Fail-open: em erro de DB retorna None (a tool agenda normal).
    """
    if not conversation_id:
        return None
    try:
        res = (
            get_supabase()
            .table("follow_up_jobs")
            .select("id, fire_at, metadata")
            .eq("conversation_id", conversation_id)
            .eq("status", "pending")
            .eq("job_type", "ai_scheduled_return")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("[AI_SCHEDULED_RETURN] falha ao buscar pending p/ conv %s: %s", conversation_id, exc)
        return None


# Rede de segurança (backstop) pós-catálogo: segmentos em que "já viu o catálogo e sumiu"
# significa lead qualificado o bastante para não ficar preso na cadência genérica.
_PROACTIVE_HANDOFF_STAGES = {"atacado", "private_label"}


def should_proactive_handoff(lead: dict[str, Any] | None) -> bool:
    """True quando um lead inativo deve ser entregue PROATIVAMENTE ao vendedor humano,
    em vez de receber o próximo toque genérico da cadência de follow-up.

    Elegível quando, simultaneamente:
    - `lead.stage` está em {atacado, private_label} (segmentos com catálogo/preço reais,
      onde "sumir depois do catálogo" é o sinal mais forte de intenção que o funil produz);
    - `lead.metadata.catalog_shown` é verdadeiro (a IA já apresentou o catálogo via a tool
      `enviar_fotos` — carimbo de outro workstream, ver `metadata.catalog_shown_at`);
    - `lead.metadata.handoff` está AUSENTE (ainda não houve um handoff real — se já houve,
      o lead já foi entregue e cabe ao vendedor, não a este backstop).

    Função PURA e sem efeitos colaterais: só decide. Quem chama decide o que fazer com o
    resultado (ex.: disparar `encaminhar_humano` via `execute_tool` e pular o follow-up
    padrão deste lead). `lead=None` (falha ao reler o registro, lead inexistente) → False,
    fail-safe: na dúvida, o lead segue na cadência normal em vez de ganhar um handoff.
    """
    if not lead:
        return False
    if lead.get("stage") not in _PROACTIVE_HANDOFF_STAGES:
        return False
    metadata = lead.get("metadata") or {}
    if not metadata.get("catalog_shown"):
        return False
    if metadata.get("handoff"):
        return False
    return True


def get_due_followups(now: datetime, limit: int = 10) -> list[dict[str, Any]]:
    """Retorna jobs pending cujo fire_at já passou."""
    sb = get_supabase()
    try:
        result = (
            sb.table("follow_up_jobs")
            .select(
                "*, "
                "leads!inner(id, phone, name, last_customer_message_at, wa_id), "
                "channels!inner(id, name, provider, provider_config, mode), "
                "conversations!inner(id, stage, followup_enabled, last_customer_message_at)"
            )
            .eq("status", "pending")
            .eq("env_tag", _ENV_TAG)
            .lte("fire_at", now.isoformat())
            .order("fire_at", desc=False)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        logger.error(f"[FOLLOWUP] Erro ao buscar follow-ups devidos: {exc}")
        raise RuntimeError("Falha ao buscar follow-up jobs devidos") from exc

    if not result.data:
        return []

    return result.data


# ═══════════════════════════════════════════════════════════════════════════════
# AGENDADOR DAS CADÊNCIAS DO JOÃO — quem CRIA os jobs (Task J3, spec 2026-09-18)
# ═══════════════════════════════════════════════════════════════════════════════
#
# A J1 declarou as cadências (`follow_up/cadence_joao.py`), a J2 escreveu o handler que
# as executa (`scheduler._process_joao_touch`). Entre as duas falta quem varre o funil e
# decide QUEM recebe. É isto.
#
# NÃO É UM SEGUNDO MOTOR: os jobs nascem no mesmo `follow_up_jobs`, com `job_type`
# próprio, e o scheduler que já existe os despacha. E a varredura NÃO tem consulta nova —
# reusa a RPC `get_deals_stage_stagnant` (20260904_esteiras_vendedor.sql), que já carrega
# no WHERE as guardas que custaram caro para existir: card aberto, opt-out, funil
# Blacklist, número errado, conversa finalizada pelo vendedor.
#
# ──────────────────────────────────────────────────────────────────────────────
# A EXCLUSÃO MÚTUA ENTRE `reposicao` E `em_atencao` — a decisão desta task
# ──────────────────────────────────────────────────────────────────────────────
# As duas vigiam a MESMA etapa (`stage_key='novo'`) do MESMO funil de Reposição — aos 45
# e aos 90 dias (ver a decisão 2 no cabeçalho de `cadence_joao.py`). O desenho anterior
# (esteira-campanha, apagada na Task J0) não colidia porque a esteira MOVIA o card para
# "Em atenção" ao terminar; este handler não move card nenhum. Sem regra explícita, no
# dia em que alguém preencher o template de "Em atenção" pela tela (Task J5) o mesmo card
# passaria a casar os dois gatilhos — e receberia as duas cadências ao mesmo tempo, do
# mesmo vendedor, no mesmo número.
#
# A REGRA É UMA PARTIÇÃO sobre um único booleano — "a Reposição já se esgotou aqui?":
#
#     reposicao   só pega card com reposicao_concluida == False
#     em_atencao  só pega card com reposicao_concluida == True
#
# Por ser partição (e não uma diferença de PRAZO), não existe estado do card em que as
# duas sejam elegíveis — nem no dia 90, nem em nenhum outro, nem depois de qualquer
# cooldown expirar. Ela também traduz a ata melhor: "90 dias que ele não compra" (38:08)
# descreve quem já esgotou a régua de Reposição, não quem nunca entrou nela.
#
# O ALTERNATIVO REJEITADO era "em_atencao pega 90+ dias E que não está elegível para
# reposicao": depende do relógio, e os prazos são exatamente o que a ata manda deixar o
# João editar (33:28). Bastaria ele subir o gatilho de Reposição para 120 dias para as
# duas voltarem a colidir, em silêncio.
#
# "Reposição esgotada" é lida de um FATO gravado no job (`metadata.ultimo_toque` num job
# `sent`), não de uma contagem de toques: a tela pode mudar os dias e o código pode mudar
# a forma da cadência, e uma contagem passaria a mentir nos dois casos.

# Número do vendedor. Mesmo valor de `scheduler.JOAO_PHONE_NUMBER_ID` e de
# `schedule_handoff_rescue` acima — declarado aqui, e não importado, porque
# `scheduler.py` importa ESTE módulo e o import inverso fecharia o ciclo. A suíte cruza
# os dois valores.
JOAO_PHONE_NUMBER_ID = "1049315514934778"

# Público da varredura. `humano` = `leads.ai_enabled = FALSE`, que é o público do funil
# do João por definição (o handoff desliga a IA, e os 1.208 leads do Bling nasceram
# assim). A escolha é DELIBERADAMENTE conservadora: com `ambos`, um lead que a ValerIA
# ainda estivesse atendendo receberia o template do vendedor no meio da conversa. O custo
# do lado escolhido é uma cadência que "não pega ninguém" se o funil tiver card de lead
# com IA ligada — visível e corrigível; o custo do outro lado é mensagem duplicada.
JOAO_CADENCIA_AUDIENCIA = "humano"

# TETO POR PASSAGEM ("quantos cards por vez"). Medido em 16/09/2026: 888 cards ficam
# elegíveis no INSTANTE em que uma cadência liga. Sem teto, a primeira varredura
# matricularia a base inteira. 20 é o mesmo teto que `automation/triggers.py` usa em
# todos os gatilhos de polling (e o `p_limit` default da própria RPC).
JOAO_TETO_PADRAO = 20
JOAO_TETO_ENV = "JOAO_CADENCIA_TETO"

# COOLDOWN de reentrada, em dias. O defeito que a RPC documenta em 20260904: quando a
# cadência acaba o card NÃO sai da etapa, então na varredura seguinte ele é elegível de
# novo — um template a cada poucos dias, para sempre. Exclusão TEMPORÁRIA e não
# permanente pela mesma razão que a RPC dá: card que sai da etapa e volta meses depois é
# oportunidade legítima.
JOAO_COOLDOWN_DIAS = 90

_joao_overrides_aviso_dado = False


def _joao_teto(teto: int | None = None) -> int:
    """O teto efetivo desta passagem. Parâmetro > env > default."""
    if teto is not None:
        return max(1, int(teto))
    bruto = os.environ.get(JOAO_TETO_ENV)
    try:
        return max(1, int(bruto)) if bruto else JOAO_TETO_PADRAO
    except (TypeError, ValueError):
        return JOAO_TETO_PADRAO


def _parse_ts(valor: Any) -> datetime | None:
    """ISO do Postgres para datetime aware, ou None. Nunca levanta."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _job_metadata(job: Mapping[str, Any]) -> dict:
    md = job.get("metadata") or {}
    return md if isinstance(md, dict) else {}


def _job_toque(job: Mapping[str, Any]) -> int:
    try:
        return int(_job_metadata(job).get("toque") or job.get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


# ── A sobreposição do banco ───────────────────────────────────────────────────
def carregar_overrides_joao() -> dict[str, dict]:
    """As duas tabelas de sobreposição viram `{funil: {codigo: {gatilho_dias, ativa, toques}}}`.

    A PK das duas tabelas mudou no Lote 1 (spec 2026-09-21 §4/§7): `followup_joao_cadencia`
    agora é `(funil, cadencia)`, `followup_joao_toque` é `(funil, cadencia, toque)` — sem
    coluna `linha`. `gatilho_dias`/`ativa` descem para o nível `(funil, cadencia)`, porque
    cada funil liga/desliga e define prazo independente do seu irmão (Atacado e Private
    Label deixaram de estar acoplados).

    FAIL-CLOSED, e essa é a decisão de projeto mais importante desta função: a migration
    `20260918_followup_joao_config.sql` NÃO é aplicada pelo deploy (é a decisão da Task
    J1/F1 — um humano a roda à mão). Até lá a leitura falha, e falhar para o lado de
    "desligado" é a única falha segura: o outro lado seriam 888 templates saindo por uma
    tabela que ninguém criou.

    Vazio significa a mesma coisa que ausência de linha e que coluna NULL: vale o código.
    E o código traz `ativa=False` nas quatro cadências (spec §7).
    """
    global _joao_overrides_aviso_dado
    sb = get_supabase()
    try:
        linhas_cadencia = sb.table("followup_joao_cadencia").select(
            "funil, cadencia, gatilho_dias, ativa"
        ).execute().data or []
    except Exception as exc:
        if not _joao_overrides_aviso_dado:
            # Uma vez por processo: este erro é ESPERADO enquanto a migration não for
            # aplicada, e repeti-lo a cada tick de 30s afogaria o log de verdade.
            logger.warning(
                "[JOAO_CADENCIA] sobreposição não lida (%s) — todas as cadências "
                "seguem DESLIGADAS. A migration 20260918 é aplicada à mão.", exc,
            )
            _joao_overrides_aviso_dado = True
        return {}

    overrides: dict[str, dict] = {}
    for row in linhas_cadencia:
        funil_codigo, codigo = row.get("funil"), row.get("cadencia")
        if cadencia_do_funil(funil_codigo, codigo) is None:
            continue
        overrides.setdefault(funil_codigo, {})[codigo] = {
            "gatilho_dias": row.get("gatilho_dias"),
            "ativa": row.get("ativa"),
            "toques": {},
        }

    try:
        linhas_toque = sb.table("followup_joao_toque").select(
            "funil, cadencia, toque, dias, template_name"
        ).execute().data or []
    except Exception as exc:
        logger.warning("[JOAO_CADENCIA] toques não lidos (%s) — vale o código", exc)
        linhas_toque = []

    for row in linhas_toque:
        funil_codigo, codigo = row.get("funil"), row.get("cadencia")
        if cadencia_do_funil(funil_codigo, codigo) is None:
            continue
        try:
            toque = int(row.get("toque"))
        except (TypeError, ValueError):
            continue
        # Toque gravado sem a linha de cadência correspondente é legítimo: editar os
        # dias não exige tocar no liga/desliga. Sem este setdefault a edição seria
        # descartada em silêncio — o pior modo de falha de uma tela de configuração.
        do_funil = overrides.setdefault(funil_codigo, {})
        da_cadencia = do_funil.setdefault(
            codigo, {"gatilho_dias": None, "ativa": None, "toques": {}})
        da_cadencia["toques"][toque] = {
            "dias": row.get("dias"), "template_name": row.get("template_name"),
        }
    return overrides


def resolver_para_agendar(
    funil: str, codigo: str, overrides_do_par: Mapping[str, Any] | None = None,
) -> CadenciaResolvida:
    """`cadence_joao.resolver` — funil primeiro, overrides já achatado. PURA.

    `carregar_overrides_joao` já devolve o par `(funil, codigo)` resolvido — sem o
    aninhamento `linhas.X.toques` de antes, que só existia porque uma cadência vivia em
    duas linhas ao mesmo tempo. Com funil como eixo essa ambiguidade não existe mais:
    quem chama já sabe de qual funil está falando.
    """
    ov = dict(overrides_do_par or {})
    return resolver(funil, codigo, {
        "gatilho_dias": ov.get("gatilho_dias"),
        "ativa": ov.get("ativa"),
        "toques": ov.get("toques") or {},
    })


# ── O estado do card, lido dos jobs que ele já teve ───────────────────────────
def _jobs_joao_dos_leads(sb, lead_ids: list[str]) -> list[dict] | None:
    """Todos os jobs de cadência do João destes leads, numa consulta só.

    UMA consulta por passagem (e não uma por card): com o teto em 20, o N+1 seria 20
    idas ao banco a cada 30 segundos por cadência ligada.

    FAIL-CLOSED no erro (devolve None, e o chamador pula a passagem): sem saber o que o
    card já recebeu não existe idempotência. Devolver lista vazia faria a varredura achar
    que ninguém tem cadência e matricular a base inteira de novo.
    """
    if not lead_ids:
        return []
    try:
        return sb.table("follow_up_jobs").select(
            "id, lead_id, job_type, status, sequence, fire_at, sent_at, created_at, metadata"
        ).in_("lead_id", lead_ids).in_(
            "job_type", sorted(JOAO_JOB_TYPES)
        ).execute().data or []
    except Exception as exc:
        logger.error("[JOAO_CADENCIA] falha ao ler os jobs existentes: %s", exc)
        return None


def _jobs_do_card(jobs: list[dict], lead_id: str, deal_id: str | None) -> list[dict]:
    """Os jobs daquele CARD, não daquele lead.

    A cadência é do card: o mesmo lead tem card em Atacado e card em Reposição, e eles
    caminham em paralelo. Job sem `deal_id` no metadata (nenhum criado por este
    agendador, mas um criado à mão teria) casa pelo lead, que é o comportamento
    conservador — ele BARRA em vez de deixar passar.
    """
    do_card = []
    for job in jobs:
        if job.get("lead_id") != lead_id:
            continue
        do_job = _job_metadata(job).get("deal_id")
        if do_job and deal_id and str(do_job) != str(deal_id):
            continue
        do_card.append(job)
    return do_card


# `job_type` só depende do código da cadência, não do funil (cadence_joao.Cadencia.job_type)
# — "reposicao_atacado" é só o funil que serve de ponto de entrada para pegar o objeto;
# "reposicao_private_label" devolveria o mesmo `job_type`.
_REPOSICAO_JOB_TYPE = cadencia_do_funil("reposicao_atacado", "reposicao").job_type


def _reposicao_concluida(jobs_do_card: list[dict]) -> bool:
    """True quando a régua de Reposição se ESGOTOU neste card.

    O fato é o último toque ENVIADO (`metadata.ultimo_toque` num job `sent`), gravado
    pelo próprio agendador na criação. Não é uma contagem de toques: a tela pode mudar os
    dias e o código pode mudar a forma da cadência, e a contagem mentiria nos dois casos.
    """
    return any(
        job.get("job_type") == _REPOSICAO_JOB_TYPE
        and job.get("status") == "sent"
        and _job_metadata(job).get("ultimo_toque")
        for job in jobs_do_card
    )


def _ultimo_envio(jobs_do_card: list[dict], job_type: str) -> datetime | None:
    enviados = [
        _parse_ts(job.get("sent_at")) or _parse_ts(job.get("fire_at"))
        for job in jobs_do_card
        if job.get("job_type") == job_type and job.get("status") == "sent"
    ]
    validos = [dt for dt in enviados if dt]
    return max(validos) if validos else None


def motivo_para_pular_joao(
    cadencia: CadenciaResolvida, jobs_do_card: list[dict], now: datetime,
) -> str | None:
    """Por que este card NÃO entra nesta cadência agora — ou None se ele entra. PURA.

    Devolver o motivo (em vez de um booleano) é o que torna a decisão auditável no log e
    testável isoladamente: é aqui que mora a exclusão mútua descrita no cabeçalho desta
    seção, e ela precisa de um teste que a prove sem passar pelo banco.

    A ORDEM das regras é parte do contrato:
      1. cadência em andamento — um card, uma cadência por vez;
      2. a PARTIÇÃO reposicao x em_atencao;
      3. repetição (cadência sem fim) ou cooldown (cadência com fim).
    """
    # 1. UM CARD, UMA CADÊNCIA POR VEZ — inclusive entre cadências diferentes. Duas
    #    abertas no mesmo card mandariam dois templates distintos, do mesmo vendedor,
    #    no mesmo dia. É também a idempotência pedida: card com job aberto não ganha
    #    outro, nem na varredura seguinte, nem em nenhuma.
    if any(job.get("status") == "pending" for job in jobs_do_card):
        return "cadencia_em_andamento"

    # 2. A PARTIÇÃO. Ver o cabeçalho desta seção para o porquê de não ser por prazo.
    concluiu_reposicao = _reposicao_concluida(jobs_do_card)
    if cadencia.codigo == "em_atencao" and not concluiu_reposicao:
        return "reposicao_nao_concluida"
    if cadencia.codigo == "reposicao" and concluiu_reposicao:
        return "reposicao_ja_concluida"

    # 3a. Cadência que SE REPETE ("Em atenção": uma mensagem a cada 3 dias até o lead
    #     dizer que não quer — ata 38:08). Não tem cooldown: ela é feita para voltar. O
    #     que a segura é o intervalo desde o último envio.
    if cadencia.repete_ultimo:
        intervalo = cadencia.intervalo_repeticao
        if intervalo is None:
            # `intervalo_repeticao` devolve None em intervalo <= 0 — um zero gravado na
            # tela faria o motor reenviar em laço. Parar é a falha segura.
            return "sem_intervalo_de_repeticao"
        ultimo = _ultimo_envio(jobs_do_card, cadencia.job_type)
        if ultimo is not None and now < ultimo + intervalo:
            return "intervalo_da_repeticao"
        return None

    # 3b. Cadência com fim: cooldown de reentrada, POR MATRÍCULA (spec 2026-09-23 §4).
    #
    # A unidade do cooldown é a MATRÍCULA, não o job. A regra antiga já ignorava job
    # `cancelled` — a intenção sempre foi "cadência que morreu não segura reentrada" —
    # mas olhava um job por vez, e quando o lead responde no meio só os PENDENTES são
    # cancelados: os toques que JÁ SAÍRAM ficam `sent`, e eram eles que disparavam o
    # cooldown. O lead que respondia no T2 e voltava a sumir ficava 90 dias sem esteira
    # nenhuma — exatamente o oposto de "se responder, reinicia".
    #
    #   matrícula com ALGUM job `cancelled`  -> INTERROMPIDA, não conta
    #   matrícula sem nenhum cancelado       -> rodou até o fim, conta
    #
    # É a distinção entre "a esteira terminou o trabalho dela" e "o lead respondeu no
    # meio". `JOAO_COOLDOWN_DIAS` continua 90: muda O QUE conta, não por quanto tempo.
    corte = now - timedelta(days=JOAO_COOLDOWN_DIAS)
    por_matricula: dict[str, list[dict]] = {}
    avulsos = 0
    for job in jobs_do_card:
        if job.get("job_type") != cadencia.job_type:
            continue
        matricula_id = _job_metadata(job).get("matricula_id")
        if matricula_id:
            chave = f"matricula:{matricula_id}"
        else:
            # Job sem `matricula_id` (nenhum criado por este agendador; um criado à mão
            # teria) é tratado como matrícula PRÓPRIA — conservador: ele conta sozinho,
            # em vez de ser absorvido por um bloco cancelado que não é dele.
            avulsos += 1
            chave = f"avulso:{job.get('id') or avulsos}"
        por_matricula.setdefault(chave, []).append(job)

    for jobs_da_matricula in por_matricula.values():
        if any(job.get("status") == "cancelled" for job in jobs_da_matricula):
            continue
        nascimentos = [
            dt for dt in (
                _parse_ts(job.get("created_at")) or _parse_ts(job.get("fire_at"))
                for job in jobs_da_matricula
            ) if dt
        ]
        # O job MAIS ANTIGO da matrícula é a data de nascimento dela. Na prática todos
        # nascem no mesmo INSERT; o `min` é o que mantém isso verdadeiro se um dia não
        # nascerem.
        if nascimentos and min(nascimentos) > corte:
            return "cooldown"
    return None


# ── A criação dos jobs ────────────────────────────────────────────────────────
def _montar_jobs_da_matricula(
    cadencia: CadenciaResolvida, linha_rpc: Mapping[str, Any], *,
    canal: Mapping[str, Any], conversation_id: str, now: datetime,
    jobs_do_card: list[dict],
) -> list[dict]:
    """Os jobs de UMA matrícula, no formato que `scheduler._process_joao_touch` lê.

    DECISÃO, e ela está no plano como escolha do implementador: a cadência inteira é
    agendada de uma vez, na matrícula. O alternativo (criar só o próximo toque, e o
    seguinte quando este sair) obrigaria o HANDLER a reagendar — acoplando o caminho de
    envio ao de agendamento, que é justamente o que separa este motor do builder
    abandonado. Uma matrícula é um bloco de jobs com o mesmo `matricula_id`, e é esse id
    que deixa a resposta do lead adiar o bloco certo.

    A exceção é a cadência que SE REPETE: "uma mensagem a cada três dias até ele falar
    que não quer" não tem fim declarado, então "todos os toques de uma vez" é
    literalmente impossível nela. Ela cria UM job por passagem, e a passagem seguinte
    cria o próximo depois do intervalo.

    E MAIS UM JOB, que não é toque: quando a cadência declara `etapa_final_key`, o
    último job da matrícula é o de MOVER o card (spec 2026-09-23 §3) — ver
    `_job_de_mover` logo abaixo.
    """
    matricula_id = str(uuid.uuid4())
    matricula_em = now.isoformat()
    lead_id = linha_rpc.get("lead_id")
    ultimo_sequence = cadencia.touches[-1].sequence if cadencia.touches else 0

    toques = cadencia.touches[-1:] if cadencia.repete_ultimo else cadencia.touches
    rows: list[dict] = []
    for toque in toques:
        if cadencia.repete_ultimo:
            ultimo = _ultimo_envio(jobs_do_card, cadencia.job_type)
            intervalo = cadencia.intervalo_repeticao or toque.offset
            # A repetição conta do ÚLTIMO ENVIO, não do instante da varredura: contar da
            # varredura somaria o intervalo duas vezes (o tick só vê o card depois de o
            # intervalo já ter passado) e a cada volta a cadência ficaria mais lenta.
            base = (ultimo + intervalo) if ultimo else (now + toque.offset)
            base = max(base, now)
        else:
            base = now + toque.offset

        rows.append({
            "conversation_id": conversation_id,
            "lead_id": lead_id,
            "channel_id": canal["id"],
            "sequence": toque.sequence,
            "fire_at": _clamp_to_business_window(base).isoformat(),
            "status": "pending",
            "env_tag": _ENV_TAG,
            "job_type": cadencia.job_type,
            "metadata": {
                "cadencia": cadencia.codigo,
                "funil": cadencia.funil,
                "toque": toque.sequence,
                "template_name": toque.template_name,
                "aceita_adiamento": toque.aceita_adiamento,
                # O FATO sobre o qual a exclusão mútua decide, gravado na criação.
                "ultimo_toque": (
                    not cadencia.repete_ultimo and toque.sequence == ultimo_sequence
                ),
                "matricula_id": matricula_id,
                "matricula_em": matricula_em,
                "deal_id": linha_rpc.get("deal_id"),
                "stage_id": linha_rpc.get("stage_id"),
                "pipeline_id": cadencia.pipeline_id,
                # O toque TEM de sair do número do VENDEDOR — ver
                # `scheduler._resolve_joao_channel`.
                "phone_number_id": JOAO_PHONE_NUMBER_ID,
            },
        })

    mover = _job_de_mover(
        cadencia, linha_rpc, canal=canal, conversation_id=conversation_id, now=now,
        matricula_id=matricula_id, matricula_em=matricula_em)
    if mover is not None:
        rows.append(mover)
    return rows


def _job_de_mover(
    cadencia: CadenciaResolvida, linha_rpc: Mapping[str, Any], *,
    canal: Mapping[str, Any], conversation_id: str, now: datetime,
    matricula_id: str, matricula_em: str,
) -> dict | None:
    """O job que MOVE o card para a etapa final — ou None se esta cadência não move.

    A única exceção ao "o motor nunca move card" do spec de 18/09, e ela é estreita
    (spec 2026-09-23 §3): passado o último toque, se o lead nunca respondeu, o card vai
    para "Em atenção". Quem executa é `scheduler._process_joao_touch`, pela MARCA
    `metadata.acao == "mover_etapa"` — a única condição de leitura combinada entre os
    dois lados. Sem template, sem canal, sem envio.

    POR QUE UM JOB, e não uma varredura à parte: a resposta do lead já cancela todos os
    jobs `pending` da matrícula (`cancel_followups_by_phone`, motivo `client_replied`,
    disparado no `webhook/meta_router.py`). Sendo um job, o "mover" é cancelado JUNTO —
    lead que responde não recebe mais nada E não tem o card movido, sem uma única regra
    nova. Uma varredura separada precisaria reimplementar essa condição, e divergiria
    dela no primeiro ajuste. Pelo mesmo motivo ele carrega o `matricula_id` dos toques:
    é por ele que o adiamento de 60 dias ("ainda tenho estoque") desliza o bloco INTEIRO,
    o move incluído, em vez de mover o card no meio de uma cadência adiada.

    Duas guardas, nesta ordem:

      · `etapa_final_key` ausente -> esta cadência não move nada (as duas de Reposição);
      · `repete_ultimo` -> cadência SEM FIM declarado ("Em atenção", uma mensagem a cada
        três dias até o lead dizer que não quer). Não existe "depois do último toque"
        para agendar, e o job nasceria a cada passagem.

    `sequence` é a do último toque + 1: `follow_up_jobs` tem `sequence` NOT NULL e
    reusar a do último toque criaria dois jobs com a mesma sequence na mesma matrícula —
    e é `sequence` que `_adiar_matriculas_joao` usa como chave do bloco.
    """
    if not cadencia.etapa_final_key or cadencia.repete_ultimo or not cadencia.touches:
        return None

    ultimo = cadencia.touches[-1]
    base = now + ultimo.offset + timedelta(days=cadencia.dias_ate_mover)
    return {
        "conversation_id": conversation_id,
        "lead_id": linha_rpc.get("lead_id"),
        "channel_id": canal["id"],
        "sequence": ultimo.sequence + 1,
        # Mesmo clamp dos toques. Um move empurrado das 2h para as 8h é invisível para
        # o lead, e a alternativa seria um ramo a mais no laço (spec 2026-09-23 §3).
        "fire_at": _clamp_to_business_window(base).isoformat(),
        "status": "pending",
        "env_tag": _ENV_TAG,
        "job_type": cadencia.job_type,
        "metadata": {
            # A MARCA. Ausente = job de toque normal. Nada de inferir pelo template
            # nulo: job de TOQUE sem template também existe (e é o estado atual das
            # três cadências de prospecção).
            "acao": "mover_etapa",
            "etapa_final_key": cadencia.etapa_final_key,
            "cadencia": cadencia.codigo,
            "funil": cadencia.funil,
            "matricula_id": matricula_id,
            "matricula_em": matricula_em,
            "deal_id": linha_rpc.get("deal_id"),
            "stage_id": linha_rpc.get("stage_id"),
            "pipeline_id": cadencia.pipeline_id,
            # Explicitamente nulo: este job nunca manda mensagem.
            "template_name": None,
            "phone_number_id": JOAO_PHONE_NUMBER_ID,
        },
    }


def _varrer_cadencia_joao(
    sb, cadencia: CadenciaResolvida, canal: Mapping[str, Any],
    now: datetime, teto: int,
) -> int:
    """Uma passagem de UMA (cadência, funil). Devolve quantos jobs foram criados."""
    args = {
        # Por KEY e não por id: a etapa é a mesma em todo funil do João, e um id
        # hardcoded morreria na primeira reestruturação de funil (Arthur reestruturou os
        # funis à mão na reunião de 10/09).
        "p_stage_id": None,
        "p_stage_key": cadencia.gatilho_stage_key,
        "p_pipeline_id": cadencia.pipeline_id,
        "p_channel_id": canal["id"],
        "p_stage_days": int(cadencia.gatilho_dias or 0),
        # O SEGUNDO relógio, e ele é um AND com o de etapa dentro da RPC: dias sem
        # NENHUMA conversa. Era fixo em 0 ("o relógio da ata é o da ETAPA") até
        # 22/09/2026; o dono escreveu "2 dias SEM CONVERSAR" para Novo e Em conversa
        # (spec 2026-09-23 §5), e agora o número vem da cadência. 0 continua
        # DESLIGANDO o filtro — é o que Proposta Enviada e as duas de Reposição pedem,
        # e é o default de `Cadencia.gatilho_silencio_dias`.
        "p_silence_days": int(cadencia.gatilho_silencio_dias or 0),
        # Continua "qualquer" em todas: um lead calado há 2 dias merece follow-up
        # tanto se a última palavra foi dele quanto se foi nossa.
        "p_last_speaker": "qualquer",
        "p_audience": JOAO_CADENCIA_AUDIENCIA,
        "p_limit": teto,
    }
    try:
        linhas = sb.rpc("get_deals_stage_stagnant", args).execute().data or []
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] RPC falhou p/ %s/%s: %s",
            cadencia.codigo, cadencia.funil, exc)
        return 0
    if not linhas:
        return 0

    jobs = _jobs_joao_dos_leads(sb, [l["lead_id"] for l in linhas if l.get("lead_id")])
    if jobs is None:
        return 0

    from app.leads.service import is_lead_blacklisted

    rows: list[dict] = []
    matriculados = 0
    for linha_rpc in linhas:
        # TETO POR PASSAGEM. O `p_limit` já foi para a RPC, mas o corte é refeito AQUI:
        # a defesa não pode depender de o banco honrar o LIMIT — e não dependeu, no
        # incidente de 16/09, de a tela honrar a validação.
        if matriculados >= teto:
            break
        lead_id, deal_id = linha_rpc.get("lead_id"), linha_rpc.get("deal_id")
        if not lead_id:
            continue
        do_card = _jobs_do_card(jobs, lead_id, deal_id)
        motivo = motivo_para_pular_joao(cadencia, do_card, now)
        if motivo:
            logger.debug(
                "[JOAO_CADENCIA] %s/%s pula card %s: %s",
                cadencia.codigo, cadencia.funil, deal_id, motivo)
            continue
        # Defesa em profundidade: a mesma condição já está no WHERE da RPC. Barata (no
        # máximo `teto` leituras) e é a última linha antes de um template sair para quem
        # pediu para não receber mais.
        if is_lead_blacklisted(lead_id):
            logger.info("[JOAO_CADENCIA] lead %s na blacklist — skip", lead_id)
            continue
        try:
            conversa = get_or_create_conversation(lead_id, canal["id"])
        except Exception as exc:
            logger.error(
                "[JOAO_CADENCIA] sem conversa no canal do vendedor p/ lead %s: %s",
                lead_id, exc)
            continue
        rows.extend(_montar_jobs_da_matricula(
            cadencia, linha_rpc, canal=canal, conversation_id=conversa["id"],
            now=now, jobs_do_card=do_card))
        matriculados += 1

    if not rows:
        return 0
    try:
        sb.table("follow_up_jobs").insert(rows).execute()
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] falha ao inserir %d jobs de %s/%s: %s",
            len(rows), cadencia.codigo, cadencia.funil, exc)
        return 0
    logger.info(
        "[JOAO_CADENCIA] %s/%s: %d card(s) matriculado(s), %d job(s) agendado(s)",
        # "job(s)" e não "toque(s)": desde 23/09 a matrícula de uma cadência que move
        # termina num job que não é toque (`acao=mover_etapa`).
        cadencia.codigo, cadencia.funil, matriculados, len(rows))
    return len(rows)


def agendar_cadencias_joao(now: datetime | None = None, teto: int | None = None) -> int:
    """Uma passagem do agendador sobre as cadências ATIVAS. Devolve os jobs criados.

    Chamada pelo tick de automação (`automation/triggers.py::check_polling_triggers`).
    Cadência desligada não varre NADA — nem chega a perguntar ao banco.
    """
    if os.environ.get("REHEARSAL_MODE") == "true":
        logger.info("[JOAO_CADENCIA] REHEARSAL_MODE ativo — varredura ignorada")
        return 0

    now = now or datetime.now(timezone.utc)
    teto = _joao_teto(teto)
    overrides = carregar_overrides_joao()

    criados = 0
    canal: dict | None = None
    canal_resolvido = False
    sb = None

    # Cada FUNIL pergunta só as SUAS PRÓPRIAS cadências — `funil.cadencias` é `()` para
    # "recuperacao", então o laço interno não roda nenhuma vez para ela: zero iteração,
    # zero job, sem `if` especial (spec 2026-09-21 §7).
    for f in FUNIS:
        overrides_do_funil = overrides.get(f.codigo) or {}
        for cadencia_do_codigo in f.cadencias:
            ov = overrides_do_funil.get(cadencia_do_codigo.codigo) or {}
            cadencia = resolver_para_agendar(f.codigo, cadencia_do_codigo.codigo, ov)
            if not cadencia.ativa:
                continue
            # Defesa em profundidade da trava da Task J4 ("ligar exige template aprovado
            # em todo toque"). O banco pode ser editado à mão, e um job sem template
            # morre no handler com `missing_template_name`: cadência que matricula, não
            # envia, e caminha até o fim — o defeito exato que este spec corrige.
            faltando = [t.sequence for t in cadencia.touches if not t.template_name]
            if faltando:
                logger.warning(
                    "[JOAO_CADENCIA] %s/%s ativa SEM template nos toques %s — "
                    "nenhum job criado", cadencia.codigo, f.codigo, faltando)
                continue
            if not canal_resolvido:
                canal_resolvido = True
                canal = get_channel_by_provider_config(
                    "phone_number_id", JOAO_PHONE_NUMBER_ID, "meta_cloud")
            if not canal:
                logger.error(
                    "[JOAO_CADENCIA] canal do vendedor (phone_number_id=%s) não "
                    "encontrado — nenhuma cadência agendada", JOAO_PHONE_NUMBER_ID)
                return criados
            if sb is None:
                sb = get_supabase()
            criados += _varrer_cadencia_joao(sb, cadencia, canal, now, teto)

    if criados:
        emit_event("followups")  # wake-up do worker (fail-open; o tick cobre)
    return criados


# ── A resposta do lead (ata 41:40) ────────────────────────────────────────────
def processar_resposta_joao(
    lead_id: str, texto: str | None, *,
    conversation_id: str | None = None, now: datetime | None = None,
) -> str | None:
    """Aplica as duas regras de resposta da ata às matrículas ABERTAS do João.

        botão "ainda tenho estoque" -> adia 60 dias, SEM recomeçar a contagem (41:40)
        botão de saída              -> opt-out REAL (blacklist), reusando a autoridade

    Devolve a classificação aplicada, ou None quando não havia o que fazer.

    ESCOPO — e ele é deliberado: só age quando o lead tem matrícula ABERTA do João.
    `buffer/processor.py` já tem um caminho determinístico de opt-out, e ele é
    propositalmente restrito ao público que o LLM não arbitra
    (`_optout_deterministico_cabe`), porque o parser da Meta achata clique de botão em
    texto comum e blacklistar o público da IA transformaria negativa reflexa digitada em
    banimento. Agir fora da cadência do João aqui reabriria esse buraco por outra porta.
    """
    classificacao = classificar_resposta(texto)
    if not classificacao:
        return None

    now = now or datetime.now(timezone.utc)
    sb = get_supabase()
    try:
        jobs = sb.table("follow_up_jobs").select(
            "id, lead_id, job_type, status, sequence, fire_at, sent_at, metadata"
        ).eq("lead_id", lead_id).in_(
            "job_type", sorted(JOAO_JOB_TYPES)
        ).in_("status", ["pending", "sent"]).execute().data or []
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] falha ao ler as matrículas do lead %s: %s", lead_id, exc)
        return None

    pendentes = [j for j in jobs if j.get("status") == "pending"]
    if not pendentes:
        return None

    if classificacao == RESPOSTA_OPTOUT:
        _optout_da_cadencia_joao(lead_id, texto, conversation_id, pendentes, sb)
        return RESPOSTA_OPTOUT

    _adiar_matriculas_joao(jobs, pendentes, sb)
    return RESPOSTA_ADIAR


def _optout_da_cadencia_joao(
    lead_id: str, texto: str | None, conversation_id: str | None,
    pendentes: list[dict], sb,
) -> None:
    """Opt-out REAL, DELEGADO a `campaigns/worker.py::handle_optout_reply`.

    Não é um quarto caminho de blacklist: `handle_optout_reply` -> `_gravar_optout` grava
    `leads.opt_out` + `apply_optout_side_effects` (funil Blacklist, cancelamento de
    campanhas e de follow-ups), que é o par que `is_lead_blacklisted` lê. Uma segunda
    cópia da regra divergiria no primeiro dia, e o custo do desvio é um "parar mensagens"
    que o sistema não honra.

    O cancelamento dos jobs do João é EXPLÍCITO mesmo assim, e não por desconfiança:
    `handle_optout_reply` é idempotente e devolve False sem fazer nada quando o lead já
    está na blacklist — o que acontece sempre que o caminho determinístico do
    `buffer/processor.py` arbitrou o mesmo turno primeiro. Nesse caso os efeitos
    colaterais não rodam de novo, e é este cancelamento que garante que a cadência pare.
    """
    lead = None
    try:
        from app.leads.service import get_lead
        lead = get_lead(lead_id)
    except Exception as exc:
        logger.warning("[JOAO_CADENCIA] não consegui reler o lead %s: %s", lead_id, exc)
    try:
        from app.campaigns.worker import handle_optout_reply
        handle_optout_reply(lead, texto, conversation_id)
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] opt-out do lead %s falhou: %s", lead_id, exc, exc_info=True)

    ids = [j["id"] for j in pendentes if j.get("id")]
    if not ids:
        return
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled", "cancel_reason": RESPOSTA_OPTOUT,
        }).in_("id", ids).execute()
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] falha ao cancelar %d toque(s) do lead %s: %s",
            len(ids), lead_id, exc)
        return
    logger.info(
        "[JOAO_CADENCIA] opt-out do lead %s — %d toque(s) cancelado(s)",
        lead_id, len(ids))


def _chave_matricula(job: Mapping[str, Any]) -> str:
    """O bloco a que este job pertence. `matricula_id` quando há; senão o job_type.

    O fallback importa para job criado antes deste agendador (ou à mão): sem ele, jobs
    sem `matricula_id` cairiam todos na mesma chave vazia e o `ultimo_enviado` de uma
    cadência contaminaria o de outra.
    """
    md = _job_metadata(job)
    return str(md.get("matricula_id") or job.get("job_type") or "")


def _adiar_matriculas_joao(jobs: list[dict], pendentes: list[dict], sb) -> None:
    """"Ainda tenho estoque" -> +60 dias nos toques que ainda não saíram (ata 41:40).

    Duas coisas ao mesmo tempo, e a segunda é a que costuma se perder: adiar 60 dias, e
    NÃO recomeçar a contagem. Recomeçar devolveria a cadência ao toque 1, e o lead
    releria o texto que já leu.

    Quem faz o cálculo é `cadence_joao.adiar_toques` — a mesma função pura que a Task J1
    escreveu, com o filtro `sequence > ultimo_enviado` fazendo o trabalho de "os que já
    saíram não voltam". Aqui só traduzimos jobs<->toques: o `offset` de cada job é a
    distância dele até a MATRÍCULA (`metadata.matricula_em`), que é exatamente a régua
    que `adiar_toques` empurra. O espaçamento entre os toques restantes é preservado — o
    bloco inteiro desliza, ele não é reescrito.
    """
    por_matricula: dict[str, list[dict]] = {}
    for job in pendentes:
        por_matricula.setdefault(_chave_matricula(job), []).append(job)

    enviados = [j for j in jobs if j.get("status") == "sent"]
    for chave, abertos in por_matricula.items():
        ultimo_enviado = max(
            (_job_toque(j) for j in enviados if _chave_matricula(j) == chave),
            default=0)
        base = _parse_ts(_job_metadata(abertos[0]).get("matricula_em"))
        if base is None:
            base = min(
                (dt for dt in (_parse_ts(j.get("fire_at")) for j in abertos) if dt),
                default=None)
        if base is None:
            logger.warning(
                "[JOAO_CADENCIA] matrícula %s sem régua de tempo — não adiada", chave)
            continue

        por_sequence = {_job_toque(j): j for j in abertos}
        touches = tuple(
            Touch(sequence=seq, offset=(_parse_ts(job.get("fire_at")) or base) - base,
                  template_name=_job_metadata(job).get("template_name"))
            for seq, job in sorted(por_sequence.items())
        )
        for adiado in adiar_toques(touches, ultimo_enviado=ultimo_enviado):
            job = por_sequence.get(adiado.sequence)
            if not job:
                continue
            novo = _clamp_to_business_window(base + adiado.offset)
            try:
                sb.table("follow_up_jobs").update(
                    {"fire_at": novo.isoformat()}).eq("id", job["id"]).execute()
            except Exception as exc:
                logger.error(
                    "[JOAO_CADENCIA] falha ao adiar o toque %s: %s", job.get("id"), exc)
        logger.info(
            "[JOAO_CADENCIA] matrícula %s adiada em %d dias (%d toque(s) em aberto)",
            chave, ADIAMENTO_ESTOQUE.days, len(abertos))
