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
    ADIAMENTO_RESPOSTA,
    FUNIS,
    # TODOS: as 5 da tela + as complementares (o `kit`). Ver `cadence_joao.JOB_TYPES_TODOS`.
    JOB_TYPES_TODOS as JOAO_JOB_TYPES,
    RESPOSTA_ADIAR,
    RESPOSTA_INTERESSE,
    RESPOSTA_OPTOUT,
    CadenciaResolvida,
    Touch,
    adiar_toques,
    cadencia_do_funil,
    cadencias_do_funil,
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


# O motivo com que `webhook/meta_router.py` chama `cancel_followups_by_phone` quando o
# LEAD RESPONDEU. É o ÚNICO motivo NÃO-TERMINAL que chega lá — todos os outros
# (`handoff`, `sem_interesse_atual`, `cliente_ativo_sem_demanda`, `lead_already_served`,
# `optout`/`optout_botao`/`block_manual`) são paradas de verdade. Ver o recorte em
# `_preserved_job_types`, que é a única coisa no código que olha para este valor.
MOTIVO_RESPOSTA_DO_LEAD = "client_replied"


def _preserved_job_types(preserve_scheduled_return: bool, reason: str = "") -> list[str]:
    """Tipos de job que o cancelamento por telefone NÃO deve tocar.

    `handoff_rescue` é SEMPRE preservado: o `encaminhar_humano` cancela a cadência e
    conta que o aviso ao vendedor (rescue) sobreviva. `ai_scheduled_return` (retorno que
    a própria IA prometeu via `agendar_retorno`) é preservado apenas em cancelamentos
    NÃO-terminais (ex.: o cliente respondeu e a cadência é re-armada). Em paradas
    terminais (opt-out, handoff, sem-interesse) ele TAMBÉM é cancelado — um lead que
    pediu para sair não pode receber um retorno proativo mesmo que `ai_enabled` volte.

    ── O RECORTE DO `client_replied` (spec 2026-09-25 §3.2) ────────────────────────
    As cadências do João (`JOAO_JOB_TYPES`) são preservadas **só quando o motivo é
    `client_replied`**, e o critério é o MOTIVO — nunca o tipo do job sozinho.

    Por que preservar nesse motivo: responder deixou de MATAR a esteira do João e passou
    a ADIÁ-LA (`processar_resposta_joao`). As duas coisas rodavam ao mesmo tempo e uma
    corria contra a outra: este cancelamento é *background task* registrada na INGESTÃO
    do webhook (`meta_router.py`), milissegundos depois da resposta HTTP, enquanto
    `processar_resposta_joao` só é alcançado via `fire_trigger("message_received")`,
    depois do debounce do buffer e como `create_task` não aguardado. Quando o handler
    chegava, os jobs já estavam `cancelled` e ele não fazia nada — por isso o botão
    "ainda tenho estoque" NUNCA adiou os 60 dias em produção. Tirar este competidor do
    caminho acaba com a corrida: não porque alguém ganhou, mas porque deixa de haver
    dois. `processar_resposta_joao` vira a única autoridade sobre o que uma resposta faz
    com a cadência do João.

    Por que NÃO virar "preserva sempre": esta mesma função é chamada com motivos
    TERMINAIS — `handoff`, `sem_interesse_atual`, `cliente_ativo_sem_demanda`,
    `lead_already_served` e o caminho de blacklist/opt-out de
    `leads/service.py::apply_optout_side_effects`. Em todos esses os jobs do João DEVEM
    continuar sendo cancelados, e este é o backstop que cobre o caso de 15/07 (o cliente
    pediu ao HUMANO para a IA parar e os toques seguiram saindo). Preservar sempre
    reabriria aquele incidente pela porta dos fundos.

    O caminho `standard` da ValerIA não muda em nenhum motivo: lá responder continua
    cancelando, porque aquela cadência existe justamente porque o lead sumiu.

    `reason` tem default porque o único chamador de produção sempre o passa, e o default
    cai no lado SEGURO: sem motivo declarado não há recorte, e os jobs do João são
    cancelados como sempre foram. Um default que preservasse seria a mutação proibida
    escrita na assinatura.
    """
    preservados = ["handoff_rescue"]
    if preserve_scheduled_return:
        preservados.append("ai_scheduled_return")
    if reason == MOTIVO_RESPOSTA_DO_LEAD:
        preservados.extend(sorted(JOAO_JOB_TYPES))
    return preservados


def cancel_followups_by_phone(
    phone: str, reason: str, *, preserve_scheduled_return: bool = True
) -> None:
    """Cancela follow-ups pending de TODAS as conversas de TODOS os leads deste número.

    `phone` pode ser um BSUID (adotante de username, cujo lead tem phone="" e é keyed
    pela coluna bsuid). Resolve as duas formas do 9º dígito BR (ver `_phone_identity_values`)
    para não deixar um lead gêmeo com cadência viva.

    `preserve_scheduled_return=False` (paradas terminais): também cancela os
    `ai_scheduled_return` — ver `_preserved_job_types`.

    `reason` NÃO é só rótulo de log: com `client_replied` as cadências do João ficam de
    fora do cancelamento, porque quem decide o que uma resposta faz com elas é
    `processar_resposta_joao` (adia, não mata). Ver `_preserved_job_types`.
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
            "job_type", _preserved_job_types(preserve_scheduled_return, reason)
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
                # `agent_profile_id` + o perfil EMBUTIDO (`agent_profiles(kind, flow_id)`)
                # porque o backstop de parada precisa saber se esta conversa é atendida por
                # um FLUXO DE BOTÕES — `scheduler._lead_stop_reason` decidia só por
                # `ai_enabled`/canal humano e não sabia que fluxos de botões existem. Sem
                # estas colunas o motivo `fluxo_de_botoes` nunca dispara, e o `ai_reengage`
                # volta a falar por LLM por cima de uma conversa de botões.
                # O embed segue o molde que já roda em `channels/service.py`
                # (`*, agent_profiles(*)`); `flow_id` existe desde 20260929 (conferido em
                # produção 01/10/2026 — a coluna responde 200 no PostgREST).
                # A conversa tem precedência sobre o canal (ver `runner.fluxo_da_conversa`),
                # e por isso os DOIS `agent_profile_id` vêm: hoje em produção os jobs do
                # número da ValerIA têm `conversations.agent_profile_id = NULL` e quem aponta
                # para o perfil de botões é o CANAL.
                "channels!inner(id, name, provider, provider_config, mode, "
                "agent_profile_id, agent_profiles(kind, flow_id)), "
                "conversations!inner(id, stage, followup_enabled, "
                "last_customer_message_at, agent_profile_id)"
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

# JANELA DE CANDIDATOS — quantos cards a RPC OLHA, e não quantos entram.
#
# ── A AVARIA QUE ISTO CORRIGE (medida em 30/09/2026, com as esteiras já ligadas) ──
# O código mandava `p_limit=teto`, colando as duas ideias: a janela de candidatos ERA
# o teto de matrícula. E a RPC ordena por silêncio mais antigo, então ela devolve
# sempre os MESMOS 20 primeiros.
#
# Assim que esses 20 são matriculados, `motivo_para_pular_joao` passa a pular todos
# eles (`cadencia_em_andamento`) — e como a matrícula não move o card nem muda o
# `last_message_at`, eles continuam sendo os 20 mais antigos na varredura seguinte. A
# esteira devolve 20, pula 20 e matricula ZERO, para sempre, sem erro e sem alerta.
#
# Medido em produção: 88 cards entraram no primeiro tick (20+20+21+20+5+2) e a
# varredura não avançou mais um único card nos ticks seguintes. Confirmado chamando a
# RPC à mão: dos 20 devolvidos, 20 já estavam matriculados.
#
# É EXATAMENTE o modo de falha que a própria RPC documenta em `20260904`:
#
#     "Lead que o Python pula nunca recebe mensagem, entao o `last_message_at` dele
#      nunca muda e ele fica no TOPO da ordenacao para sempre, ocupando um slot.
#      Bastam `p_limit` leads assim para a esteira devolver 20 linhas, pular as 20 e
#      parar de funcionar em silencio — sem erro, sem alerta."
#
# ── POR QUE UMA JANELA LARGA RESOLVE ────────────────────────────────────────────
# Quem limita o VOLUME são o teto por passagem (20) e o orçamento do dia, os dois do
# lado Python. A janela só precisa ser larga o bastante para que os pulos permanentes
# não escondam quem ainda não entrou. 2.000 está muito acima de qualquer etapa dos
# funis do João (a maior, "Em conversa" do Private Label, tem 560 cards), e a consulta
# é indexada por `entered_stage_at`.
#
# ── O LIMITE DESTA CORREÇÃO, DITO EM VOZ ALTA ───────────────────────────────────
# Se um dia uma etapa acumular MAIS de 2.000 cards permanentemente pulados, a fome
# volta. O conserto definitivo é mover a condição "já tem job aberto" para o WHERE da
# RPC, junto das outras paradas permanentes (blacklist, número errado, conversa
# finalizada) — que é o que a própria RPC diz que deve ser feito. Isso é migration com
# DROP+CREATE de função compartilhada com as campanhas, e foi deixado para uma entrega
# própria em vez de ser enfiado no meio de uma correção urgente.
JOAO_JANELA_CANDIDATOS = 2000

# COOLDOWN de reentrada, em dias. O defeito que a RPC documenta em 20260904: quando a
# cadência acaba o card NÃO sai da etapa, então na varredura seguinte ele é elegível de
# novo — um template a cada poucos dias, para sempre. Exclusão TEMPORÁRIA e não
# permanente pela mesma razão que a RPC dá: card que sai da etapa e volta meses depois é
# oportunidade legítima.
JOAO_COOLDOWN_DIAS = 90

# O `cancel_reason` do ramo do BOTÃO POSITIVO (spec 2026-09-26 §2.3). Ele NÃO é
# `RESPOSTA_OPTOUT`, e a diferença é lida em dois lugares: nos relatórios (encerrar
# porque o objetivo foi alcançado não é a mesma coisa que um lead pedindo para sair)
# e em `_matricula_interrompida`, onde este motivo específico faz a matrícula CONTAR
# para o cooldown em vez de liberar a rematrícula.
MOTIVO_INTERESSE = "lead_demonstrou_interesse"

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


# ── Os AJUSTES GLOBAIS do motor (spec 2026-09-26 §3.5) ────────────────────
#
# Dois números que o dono do funil edita na tela e que NÃO são por cadência — são do
# motor inteiro. Por isso não cabem em `followup_joao_cadencia` (cuja PK é
# `(funil, cadencia)`): gravá-los ali obrigaria a escolher uma cadência arbitrária
# para hospedar um valor global, e a próxima leitura teria de saber qual foi.
#
# Estes são os DEFAULTS DE CÓDIGO. A tabela `followup_joao_ajustes` (migration
# 20260926) sobrepõe; ausência de linha, valor ilegível e tabela inexistente valem
# todos a mesma coisa — vale o código. As chaves são as MESMAS do CHECK da migration,
# e as duas listas são fixadas pela suíte, cada uma do seu lado: uma chave que exista
# só de um lado é configuração que a tela grava e o motor nunca lê.
AJUSTES_PADRAO: dict[str, int] = {
    # Máximo de TEMPLATES por dia, somando as 5 esteiras do João. A unidade é DISPARO
    # e não matrícula (spec §4): uma matrícula agenda 4 toques ao longo de 45 dias, e
    # limitar matrícula não limitaria envio.
    "teto_diario_disparos": 100,
    # A espera do botão "Ainda tenho estoque". Era 60 no código até 26/09; o default
    # virou 30 e o número passou a ser editável. `cadence_joao.ADIAMENTO_ESTOQUE` é o
    # mesmo valor do outro lado, e a suíte cruza os dois.
    "adiamento_estoque_dias": 30,
}

# Sentinela de LEITURA FALHA de `disparos_de_hoje`. Ver a docstring da função: o valor
# é maior que qualquer teto que o CHECK da tabela aceite, para que tanto
# `disparos >= teto` quanto `teto - disparos` leiam "sem saldo" sem um segundo ramo.
DISPAROS_ILEGIVEIS = 10 ** 6

_joao_ajustes_aviso_dado = False


def carregar_ajustes_joao() -> dict[str, int]:
    """`followup_joao_ajustes` sobreposto em `AJUSTES_PADRAO`. FAIL-CLOSED para o código.

    Mesma disciplina de `carregar_overrides_joao`, pelo mesmo motivo: a migration
    `20260926_followup_joao_ajustes.sql` NÃO é aplicada pelo deploy — um humano a roda
    à mão no SQL editor. Até lá a leitura falha, e falhar para os defaults é a falha
    segura: o teto de 100/dia continua valendo, e o adiamento do botão continua em 30
    dias. O outro lado (tratar "não li" como "sem teto") seria exatamente o incidente
    de 16/09 — 888 templates em 6 minutos — por uma tabela que ninguém criou.

    O aviso sai UMA VEZ POR PROCESSO. O tick do agendador roda a cada 30s; repetir este
    erro em todo tick afogaria o log de verdade, e ele é ESPERADO enquanto a migration
    não for aplicada.

    Sempre devolve as DUAS chaves: quem chama indexa direto (`[...]`), sem `.get` com
    default espalhado por três arquivos. Linha com chave desconhecida, valor não
    inteiro ou valor < 1 é descartada — o CHECK do banco já barra os três, e esta
    segunda cópia existe para o caso de a tabela ser editada por fora do CRM.
    """
    global _joao_ajustes_aviso_dado
    ajustes = dict(AJUSTES_PADRAO)
    try:
        linhas = get_supabase().table("followup_joao_ajustes").select(
            "chave, valor"
        ).execute().data or []
    except Exception as exc:
        if not _joao_ajustes_aviso_dado:
            logger.warning(
                "[JOAO_CADENCIA] ajustes globais não lidos (%s) — valem os defaults "
                "de código %s. A migration 20260926 é aplicada à mão.",
                exc, ajustes,
            )
            _joao_ajustes_aviso_dado = True
        return ajustes

    for row in linhas:
        chave = row.get("chave")
        if chave not in AJUSTES_PADRAO:
            continue
        try:
            valor = int(row.get("valor"))
        except (TypeError, ValueError):
            continue
        if valor < 1:
            # Zero tem significado perigoso e DIFERENTE em cada chave (teto 0 pararia
            # o motor em silêncio; adiamento 0 reenviaria no mesmo dia), e em nenhuma
            # das duas é um valor útil. Mesmo CHECK da migration.
            continue
        ajustes[chave] = valor
    return ajustes


def _dia_em_sao_paulo(now: datetime) -> tuple[str, str]:
    """`[início, fim)` do dia corrente em America/Sao_Paulo, em ISO UTC.

    O dia do TETO é o dia do calendário de quem opera o funil, não o de UTC. São Paulo
    está em UTC-3 o ano inteiro (o horário de verão acabou em 2019), então das 21h à
    meia-noite BRT o relógio UTC JÁ ESTÁ no dia seguinte: contar por UTC viraria a
    conta às 21h e daria um segundo orçamento de 100 disparos em cima do primeiro,
    todo santo dia — e justamente na faixa em que um atraso de fila empurra os toques.
    """
    local = now.astimezone(_SP_TZ)
    inicio_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    fim_local = inicio_local + timedelta(days=1)
    return (
        inicio_local.astimezone(timezone.utc).isoformat(),
        fim_local.astimezone(timezone.utc).isoformat(),
    )


def disparos_de_hoje(sb, *, now: datetime | None = None) -> int:
    """Quantos TEMPLATES do João já saíram hoje (dia de America/Sao_Paulo).

    UMA consulta, e ela é do TICK — nunca uma por job (spec §4). Quem chama guarda o
    número e desconta dele; recontar por job seria N idas ao banco a cada 30 segundos.

    O ESCOPO é `JOAO_JOB_TYPES`, as 5 esteiras do vendedor. O caminho `standard` da
    ValerIA fica de FORA de propósito: lá é texto livre do LLM dentro de uma janela de
    24h que o lead abriu, dirigido por resposta, e é o único follow-up que roda de
    verdade em produção (8.140 jobs). Um teto ali quebraria o que funciona sem reduzir
    o risco que motiva esta regra.

    O JOB DE MOVER NÃO CONTA. Ele é um job do João, é marcado `sent` e ganha `sent_at`
    como qualquer outro — mas não manda mensagem nenhuma (`metadata.acao ==
    "mover_etapa"`, sem template, sem canal). Contá-lo gastaria orçamento de disparo
    com uma escrita em `deals`, e a unidade declarada é TEMPLATE. A marca é a mesma que
    `scheduler._process_joao_touch` lê para decidir o que o job é.

    FAIL-CLOSED: erro de leitura devolve `DISPAROS_ILEGIVEIS`, que é "sem saldo". Não
    saber quantos templates já saíram hoje não é razão para mandar mais — é a mesma
    escolha de `carregar_overrides_joao` e de `_jobs_joao_dos_leads`, e o custo do
    outro lado é a avalanche que este teto existe para impedir. O sintoma da falha é
    visível (zero disparos), e a consulta é um select indexado na mesma tabela que o
    scheduler lê a cada tick: se ela falha de forma permanente, o motor já está morto.
    """
    now = now or datetime.now(timezone.utc)
    inicio, fim = _dia_em_sao_paulo(now)
    try:
        linhas = sb.table("follow_up_jobs").select(
            "id, metadata"
        ).eq("status", "sent").in_(
            "job_type", sorted(JOAO_JOB_TYPES)
        ).gte("sent_at", inicio).lt("sent_at", fim).execute().data or []
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] não consegui contar os disparos de hoje (%s) — "
            "tratando como orçamento ESGOTADO", exc)
        return DISPAROS_ILEGIVEIS
    return sum(
        1 for linha in linhas
        if _job_metadata(linha).get("acao") != "mover_etapa"
    )


def templates_do_joao_hoje(
    sb, lead_id: str, *, now: datetime | None = None,
) -> set[str]:
    """Os templates do João que ESTE lead já recebeu hoje (dia de America/Sao_Paulo).

    A última linha antes do envio, e ela existe por causa de 05/10/2026: o teto de
    envio segurou o volume (50), mas gastou 48 deles em PARES — 24 leads levaram o
    mesmo template duas vezes no mesmo segundo, porque cada um tinha duas matrículas
    abertas e nada no envio olhava o que já tinha saído para aquele lead. Na mesma
    auditoria, 105 leads tinham o toque 2 e o toque 3 da mesma matrícula vencendo no
    mesmo dia (o teto adia um job por vez, e o toque seguinte alcança o anterior).

    Quem chama decide com o conjunto: o MESMO template de novo é duplicata; um
    template DIFERENTE no mesmo dia é um toque que chegou cedo demais. "Hoje" e não
    "nunca": a cadência que se repete ("Em atenção") manda o mesmo template a cada N
    dias por desenho.

    Só `.eq` na consulta e o resto em Python: os jobs `sent` de um lead são poucos
    (cada um é uma mensagem que ele recebeu de verdade). O job de mover não conta — não
    manda mensagem. Erro PROPAGA: quem chama não envia sem responder esta pergunta.
    """
    now = now or datetime.now(timezone.utc)
    inicio, fim = (_parse_ts(t) for t in _dia_em_sao_paulo(now))
    linhas = sb.table("follow_up_jobs").select(
        "id, job_type, sent_at, metadata"
    ).eq("lead_id", lead_id).eq("status", "sent").execute().data or []
    hoje: set[str] = set()
    for linha in linhas:
        if linha.get("job_type") not in JOAO_JOB_TYPES:
            continue
        md = _job_metadata(linha)
        if md.get("acao") == "mover_etapa":
            continue
        enviado = _parse_ts(linha.get("sent_at"))
        if enviado and inicio <= enviado < fim:
            hoje.add(str(md.get("template_name") or ""))
    return hoje


# Status que ainda vão consumir a cota de hoje. `cancelled` e `failed` ficam de fora:
# aquele job não vai sair, e contá-lo seria cobrar do orçamento uma mensagem que
# ninguém recebe.
_STATUS_COMPROMETIDOS = ("pending", "processing", "sent")


def disparos_comprometidos(sb, *, now: datetime | None = None) -> int:
    """Quantos templates do João já estão COMPROMETIDOS para o dia em que uma matrícula
    feita AGORA dispararia o toque 1. UMA consulta.

    ── O DIA É O DO DISPARO, NÃO O DO RELÓGIO (incidente de 03–04/10/2026) ──────
    Até 05/10 esta função se chamava `disparos_comprometidos_hoje` e contava os jobs
    com `fire_at` no dia corrente. Só que o toque 1 tem offset 0 e é clampado para a
    janela comercial: matrícula feita no sábado marca o toque 1 para segunda 09:00, e
    matrícula feita numa quarta às 17h marca para quinta 09:00. Nos dois casos "o que
    está comprometido para HOJE" é zero — e o saldo voltava CHEIO a cada tick de 30
    segundos. No fim de semana de 03–04/10 isso matriculou ~50 cards por tick durante
    48 horas, todos com o toque 1 na segunda às 09:00.

    O recorte agora é o dia de `_clamp_to_business_window(now)` — exatamente o dia que
    `_montar_jobs_da_matricula` grava no toque 1. As duas metades usam a MESMA função
    de clamp, e é isso que impede que voltem a divergir.

    ── POR QUE ISTO NÃO É `disparos_de_hoje` ───────────────────────────────────
    As duas contam coisas diferentes porque os dois tetos perguntam coisas diferentes:

      ENVIO      "quantos já saíram?"       -> `disparos_de_hoje`, por `sent_at`
      MATRÍCULA  "quantos já estão na fila?" -> esta, por `fire_at`

    Avaria medida em 29/09/2026, simulando ligar as esteiras de prospecção: o
    agendador usava a contagem de ENVIO para decidir quantos cards matricular. Como a
    janela comercial é 09h-16h, ligar a esteira às 03h significa que nada foi enviado
    hoje — então, a cada tick de 30s, o saldo voltava CHEIO e um lote novo era
    matriculado. Com ~1.100 cards elegíveis, em ~11 minutos todos estariam
    matriculados com o toque 1 às 09:00, contra um teto declarado de 50/dia.

    O teto de ENVIO seguraria o estrago visível (50 sairiam), mas os outros 1.050
    ficariam numa fila adiada um dia por vez, com os toques 2 e 3 vencendo enquanto o
    1 ainda não saiu. É literalmente a "fila que nunca drena" que o comentário de
    `_varrer_cadencia_joao` diz existir para impedir — a trava estava inerte
    exatamente na hora em que ela é necessária.

    ── O RECORTE É `fire_at`, E É ELE QUE CONSERTA ─────────────────────────────
    "Comprometido para hoje" é ter `fire_at` dentro do dia de hoje e ainda não ter
    sido descartado. Job adiado para amanhã sai da conta sozinho (o `fire_at` dele
    mudou de dia), que é o comportamento certo: ele passou a ser problema de amanhã.

    LIMITE CONHECIDO: um job que venceu ONTEM e só saiu hoje (worker parado no meio)
    tem `fire_at` de ontem e não é contado. É subcontagem, e ela afrouxa o teto no
    dia seguinte a uma parada — raro, pequeno, e o teto de ENVIO continua segurando o
    volume real. A alternativa (duas consultas, ou um `or` de dois intervalos) custa
    mais do que o erro que evita.

    O JOB DE MOVER NÃO CONTA, pela mesma razão do outro lado: a unidade declarada do
    teto é TEMPLATE, e o move escreve em `deals` sem mandar mensagem nenhuma.

    FAIL-CLOSED: erro de leitura devolve `DISPAROS_ILEGIVEIS` ("sem saldo"), igual a
    `disparos_de_hoje`. Não saber o que já está na fila não é razão para enfileirar
    mais.
    """
    now = now or datetime.now(timezone.utc)
    inicio, fim = _dia_em_sao_paulo(_clamp_to_business_window(now))
    try:
        linhas = sb.table("follow_up_jobs").select(
            "id, metadata"
        ).in_("status", list(_STATUS_COMPROMETIDOS)).in_(
            "job_type", sorted(JOAO_JOB_TYPES)
        ).gte("fire_at", inicio).lt("fire_at", fim).execute().data or []
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] não consegui contar o que já está comprometido para hoje "
            "(%s) — tratando como orçamento ESGOTADO", exc)
        return DISPAROS_ILEGIVEIS
    return sum(
        1 for linha in linhas
        if _job_metadata(linha).get("acao") != "mover_etapa"
    )


def _inicio_da_janela_de_amanha(now: datetime) -> datetime:
    """As 09h do PRÓXIMO DIA ÚTIL em America/Sao_Paulo, em UTC.

    Reusa `_clamp_to_business_window` em vez de repetir a regra de fim de semana: a
    meia-noite local de amanhã está sempre ANTES da janela, então o clamp devolve as
    09h do mesmo dia quando amanhã é dia útil, e pula para segunda quando cai no fim
    de semana. Duas cópias da regra divergiriam, e o sintoma seria um template saindo
    num sábado.
    """
    local = now.astimezone(_SP_TZ)
    amanha = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return _clamp_to_business_window(amanha.astimezone(timezone.utc))


def adiar_job_para_amanha(job_id: str, sb, *, now: datetime | None = None) -> None:
    """Empurra `fire_at` para o início da janela comercial de amanhã. NUNCA cancela.

    É o que o teto diário faz com um toque que estourou o orçamento do dia (spec §4), e
    a escolha entre ADIAR e CANCELAR não é estilo:

      · cancelar jogaria o toque no lixo — o lead pularia do toque 2 para o 4 sem que
        ninguém registrasse que houve um buraco;
      · e, pior, `motivo_para_pular_joao` lê job `cancelled` como "o lead respondeu no
        meio" e por isso NÃO deixa aquela matrícula segurar o cooldown. O card voltaria
        a ser elegível na varredura seguinte, seria rematriculado do toque 1, estouraria
        o teto de novo, seria cancelado de novo: laço. É o mesmo raciocínio que faz
        `_mover_card_joao` marcar `sent` em vez de `cancelled` quando não consegue mover.

    Falha de escrita é logada e engolida: quem chama está no meio de um tick de envio, e
    a alternativa (propagar) derrubaria os jobs seguintes da mesma passagem. O job segue
    `pending` com o `fire_at` antigo e volta a ser avaliado no próximo tick — onde o
    mesmo teto o barra de novo.
    """
    alvo = _inicio_da_janela_de_amanha(now or datetime.now(timezone.utc))
    try:
        sb.table("follow_up_jobs").update(
            {"fire_at": alvo.isoformat()}).eq("id", job_id).execute()
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] falha ao adiar o job %s para %s: %s",
            job_id, alvo.isoformat(), exc)
        return
    logger.info(
        "[JOAO_CADENCIA] teto diário atingido — job %s adiado para %s",
        job_id, alvo.isoformat())


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
#
# O PostgREST desta VPS corta TODA resposta em 1.000 linhas (`PGRST_DB_MAX_ROWS=1000`
# no `supabase_rest`) e não avisa: a consulta volta "com sucesso", só que truncada.
#
# Foi isso que fez a explosão de 03–04/10/2026 (1.019.281 jobs para 467 leads). A
# janela de candidatos tem até 2.000 cards, e a leitura dos jobs deles numa consulta só
# parava na linha 1.000. O card cujo job aberto ficava depois do corte parecia livre,
# `motivo_para_pular_joao` não via `cadencia_em_andamento`, e ele era matriculado de
# novo — e cada rematrícula empurrava mais cards para além do corte. Às 00:05 de sábado
# veio a primeira; dali até domingo 23:59, só rematrículas, a cada tick de 30 segundos.
#
# Toda leitura da qual a idempotência depende PAGINA até a página vir incompleta.
_PAGINA_POSTGREST = 1000
# 2.000 UUIDs num `in.(...)` são ~75 KB de URL. Lotes de 200 ficam longe de qualquer
# limite de proxy (mesmo número de `campaigns/traffic_report.py::_chunks`).
_LOTE_DE_LEADS = 200


def _ler_todas_as_paginas(montar_consulta) -> list[dict]:
    """Executa a consulta paginando com `.range()` até a página vir incompleta.

    `montar_consulta` é chamado a cada página porque o builder do postgrest-py acumula
    estado. A consulta TEM de vir ordenada por uma chave única (`order("id")`): sem
    ordem, o Postgres pode devolver a mesma linha em duas páginas e pular outra.
    Erro em qualquer página PROPAGA — quem chama decide o fail-closed.
    """
    linhas: list[dict] = []
    inicio = 0
    while True:
        pagina = montar_consulta().range(
            inicio, inicio + _PAGINA_POSTGREST - 1).execute().data or []
        linhas.extend(pagina)
        if len(pagina) < _PAGINA_POSTGREST:
            return linhas
        inicio += _PAGINA_POSTGREST


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
    jobs: list[dict] = []
    try:
        for i in range(0, len(lead_ids), _LOTE_DE_LEADS):
            lote = lead_ids[i:i + _LOTE_DE_LEADS]
            jobs.extend(_ler_todas_as_paginas(lambda lote=lote: sb.table(
                "follow_up_jobs").select(
                "id, lead_id, job_type, status, sequence, fire_at, sent_at, created_at, "
                # `cancel_reason` entrou em 26/09: `motivo_para_pular_joao` precisa
                # distinguir "o lead respondeu no meio" de "o lead disse que quer repor".
                "cancel_reason, metadata"
            ).in_("lead_id", lote).in_(
                "job_type", sorted(JOAO_JOB_TYPES)
            ).order("id")))
    except Exception as exc:
        # Metade dos jobs é tão perigoso quanto nenhum: o card cujo job ficou na
        # página que não veio parece livre. Fail-closed vale para a leitura inteira.
        logger.error("[JOAO_CADENCIA] falha ao ler os jobs existentes: %s", exc)
        return None
    return jobs


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


def _matricula_interrompida(jobs_da_matricula: list[dict]) -> bool:
    """Esta matrícula MORREU no meio (e por isso não segura o cooldown)?

    A regra base é de 23/09: matrícula com algum job `cancelled` foi interrompida — o
    lead respondeu, a esteira não terminou o trabalho dela, e 90 dias de silêncio seriam
    o oposto de "se responder, reinicia".

    A EXCEÇÃO é de 26/09 e ela é estreita: `MOTIVO_INTERESSE`. O botão positivo também
    cancela os `pending`, mas pelo motivo contrário — a esteira alcançou o objetivo e
    saiu da frente para o vendedor assumir. Sem esta exceção, o cancelamento faria o
    card voltar a ser elegível no tick seguinte (30s) e a esteira o rematricularia do
    toque 1, em cima de uma negociação em andamento: laço, e cada volta custa um
    template de marketing. É o mesmo laço que `adiar_job_para_amanha` existe para
    evitar do outro lado.

    Na Reposição o laço já estaria fechado pelo move do toque 1 (o card sai de "Cliente
    Ativo", que é a única etapa de ENTRADA da esteira). Esta trava cobre o resto: as
    três cadências de prospecção não movem card no meio, e "quero a tabela" é uma frase
    perfeitamente natural para um lead de Atacado DIGITAR.
    """
    cancelados = [j for j in jobs_da_matricula if j.get("status") == "cancelled"]
    if not cancelados:
        return False
    return not all(j.get("cancel_reason") == MOTIVO_INTERESSE for j in cancelados)


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
    # A ÚNICA exceção a "cancelada = interrompida" é o botão positivo — ver
    # `_matricula_interrompida`.
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
        if _matricula_interrompida(jobs_da_matricula):
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
    é por ele que o adiamento do botão "ainda tenho estoque" (30 dias no código desde
    26/09, e editável em `followup_joao_ajustes`) desliza o bloco INTEIRO, o move
    incluído, em vez de mover o card no meio de uma cadência adiada.

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
    now: datetime, teto: int, *, orcamento: int | None = None,
) -> tuple[int, int]:
    """Uma passagem de UMA (cadência, funil). Devolve `(jobs criados, cards matriculados)`.

    DOIS tetos, e eles são COISAS DIFERENTES (spec 2026-09-26 §4):

      · `teto`     — POR PASSAGEM. "Quantos cards por vez", para que uma varredura não
                      matricule a base inteira numa consulta. É o `JOAO_TETO_PADRAO`
                      (20), o mesmo de `automation/triggers.py`, e ele se renova a cada
                      tick de 30s — por isso sozinho ele não limita VOLUME: 20 a cada
                      30s são até 2.400 matrículas por hora.
      · `orcamento` — o saldo do DIA, já descontado do que saiu, calculado UMA vez por
                      passagem do agendador e repartido entre as cadências na ordem em
                      que elas aparecem. `None` = sem orçamento (o comportamento
                      histórico; nenhum chamador de produção passa None).

    Matrícula gasta orçamento porque o toque 1 sai praticamente na hora (offset 0,
    clampado para a janela comercial): matricular N cards é disparar N templates. É o
    que faz o teto se autoequilibrar sem uma segunda regra.

    Devolver os DOIS números é o que permite descontar o orçamento certo: `len(rows)`
    conta jobs (4 toques + o move), e descontar isso do orçamento cobraria 5 disparos
    por uma matrícula que manda 1 template hoje.
    """
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
        # A JANELA, não o teto — ver `JOAO_JANELA_CANDIDATOS`. Mandar `teto` aqui
        # fazia a varredura devolver sempre os mesmos 20 já matriculados e parar de
        # avançar em silêncio. Quem limita o volume é o corte em Python, abaixo.
        "p_limit": JOAO_JANELA_CANDIDATOS,
    }
    try:
        linhas = sb.rpc("get_deals_stage_stagnant", args).execute().data or []
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] RPC falhou p/ %s/%s: %s",
            cadencia.codigo, cadencia.funil, exc)
        return 0, 0
    if not linhas:
        return 0, 0

    jobs = _jobs_joao_dos_leads(sb, [l["lead_id"] for l in linhas if l.get("lead_id")])
    if jobs is None:
        return 0, 0

    from app.leads.service import is_lead_blacklisted

    rows: list[dict] = []
    matriculados = 0
    for linha_rpc in linhas:
        # TETO POR PASSAGEM. O `p_limit` já foi para a RPC, mas o corte é refeito AQUI:
        # a defesa não pode depender de o banco honrar o LIMIT — e não dependeu, no
        # incidente de 16/09, de a tela honrar a validação.
        if matriculados >= teto:
            break
        # ORÇAMENTO DO DIA, que é outra coisa (ver a docstring). Ele para a matrícula
        # ANTES do insert, e não depois: um card que não entrou hoje continua parado na
        # etapa e será varrido amanhã, com a régua inteira começando do zero. Matricular
        # e só depois segurar o envio construiria fila que nunca drena — o toque do dia
        # 15 chegaria no dia 40, corrompendo a cadência em silêncio (spec §4).
        if orcamento is not None and matriculados >= orcamento:
            logger.info(
                "[JOAO_CADENCIA] %s/%s: orçamento do dia esgotado em %d matrícula(s)",
                cadencia.codigo, cadencia.funil, matriculados)
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
        return 0, 0
    try:
        sb.table("follow_up_jobs").insert(rows).execute()
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] falha ao inserir %d jobs de %s/%s: %s",
            len(rows), cadencia.codigo, cadencia.funil, exc)
        # Insert que falhou não gastou orçamento: nenhum template vai sair por ele.
        return 0, 0
    logger.info(
        "[JOAO_CADENCIA] %s/%s: %d card(s) matriculado(s), %d job(s) agendado(s)",
        # "job(s)" e não "toque(s)": desde 23/09 a matrícula de uma cadência que move
        # termina num job que não é toque (`acao=mover_etapa`).
        cadencia.codigo, cadencia.funil, matriculados, len(rows))
    return len(rows), matriculados


def agendar_cadencias_joao(now: datetime | None = None, teto: int | None = None) -> int:
    """Uma passagem do agendador sobre as cadências ATIVAS. Devolve os jobs criados.

    Chamada pelo tick de automação (`automation/triggers.py::check_polling_triggers`).
    Cadência desligada não varre NADA — nem chega a perguntar ao banco, e isso vale
    também para o orçamento do dia: ele só é calculado quando a PRIMEIRA cadência
    elegível aparece, junto da resolução do canal.

    O ORÇAMENTO DIÁRIO (spec 2026-09-26 §4) é UM número por passagem, repartido entre
    as cadências na ordem dos funis — UMA contagem por tick, nunca uma por card. Ele
    NÃO substitui o teto por passagem (`teto`, 20): esse protege contra varrer a base
    inteira numa consulta, e continua existindo.
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
    # O saldo de DISPAROS do dia. `None` = ainda não calculado (preguiçoso de
    # propósito: passagem sem cadência ativa não paga as duas consultas).
    saldo: int | None = None
    teto_diario = 0
    esgotou_o_dia = False

    # Cada FUNIL pergunta só as SUAS PRÓPRIAS cadências — `funil.cadencias` é `()` para
    # "recuperacao", então o laço interno não roda nenhuma vez para ela: zero iteração,
    # zero job, sem `if` especial (spec 2026-09-21 §7).
    for f in FUNIS:
        if esgotou_o_dia:
            break
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
            if saldo is None:
                teto_diario = carregar_ajustes_joao()["teto_diario_disparos"]
                # COMPROMETIDOS, não ENVIADOS — ver a docstring de
                # `disparos_comprometidos`. A janela é 09h-16h; medir por
                # `sent_at` faria o saldo voltar cheio a cada tick de 30s enquanto a
                # janela estivesse fechada, e a base inteira seria matriculada de
                # madrugada com o toque 1 marcado para as 09h.
                saldo = max(0, teto_diario - disparos_comprometidos(sb, now=now))
            if saldo <= 0:
                # O log sai UMA vez por passagem, e não uma por cadência: o tick roda a
                # cada 30s e o orçamento fica em zero pelo resto do dia — uma linha por
                # cadência por tick seriam ~10 mil linhas até a meia-noite.
                logger.info(
                    "[JOAO_CADENCIA] teto diário de %d disparo(s) já consumido — "
                    "nenhuma matrícula nova nesta passagem", teto_diario)
                esgotou_o_dia = True
                break
            novos, matriculados = _varrer_cadencia_joao(
                sb, cadencia, canal, now, teto, orcamento=saldo)
            criados += novos
            saldo -= matriculados

    if criados:
        emit_event("followups")  # wake-up do worker (fail-open; o tick cobre)
    return criados


# ── A resposta do lead (ata 41:40) ────────────────────────────────────────────
def processar_resposta_joao(
    lead_id: str, texto: str | None, *,
    conversation_id: str | None = None, now: datetime | None = None,
) -> str | None:
    """O que a resposta do lead faz com as matrículas ABERTAS do João. QUATRO ramos:

        botão de saída              -> opt-out REAL (blacklist), reusando a autoridade
        botão positivo              -> ENCERRA a matrícula (o João assume), sem blacklist
        botão "ainda tenho estoque" -> adia `adiamento_estoque_dias`, sem recomeçar
        qualquer outra resposta     -> adia `ADIAMENTO_RESPOSTA` (3 dias), sem recomeçar

    Nessa ORDEM, que é a precedência: saída → interesse → adiamento → comum. Devolve a
    ação aplicada (`RESPOSTA_OPTOUT`, `RESPOSTA_INTERESSE` ou `RESPOSTA_ADIAR`), ou None
    quando não havia o que fazer — os dois adiamentos devolvem `RESPOSTA_ADIAR` porque a
    AÇÃO é a mesma; só a distância muda, e ela está no log e no `fire_at` gravado.

    O RAMO DO BOTÃO POSITIVO é de 26/09 (spec §2.3). "Preciso repor" é o sinal mais
    quente que a esteira de Reposição produz e até ontem caía no ramo genérico: adiava
    3 dias e mandava outro "ainda tem estoque?" depois, possivelmente enquanto o João já
    negociava. Ele ENCERRA e não notifica ninguém — o lead respondeu no número do
    vendedor, e o /conversas já mostra.

    O TERCEIRO RAMO é novo (spec 2026-09-25 §3.3) e o `return None` antecipado que existia
    quando `classificar_resposta` não classificava SAIU: "não é opt-out nem adiamento
    longo" deixou de ser "nada a fazer" e passou a ter ação própria. Antes, responder
    MATAVA a esteira (via `cancel_followups_by_phone`) e o cooldown por matrícula a
    deixava reentrar ~2 dias depois, DO TOQUE 1 — sem teto, porque cada volta reiniciava
    a contagem. Agora responder ADIA: o lead continua de onde parou, consome os toques e
    chega a "Em Atenção" como deveria.

    CUSTO NOVO no caminho quente do inbound: este handler passou a consultar
    `follow_up_jobs` em TODA resposta, e não só nas duas que casavam um rótulo. É uma
    leitura indexada por `lead_id`, feita fora do caminho da resposta HTTP
    (`fire_trigger` → `create_task`), e não dá para evitá-la: saber se há matrícula
    aberta é exatamente a pergunta que decide se há algo a adiar.

    ESCOPO — e ele é deliberado: só age quando o lead tem matrícula ABERTA do João.
    `buffer/processor.py` já tem um caminho determinístico de opt-out, e ele é
    propositalmente restrito ao público que o LLM não arbitra
    (`_optout_deterministico_cabe`), porque o parser da Meta achata clique de botão em
    texto comum e blacklistar o público da IA transformaria negativa reflexa digitada em
    banimento. Agir fora da cadência do João aqui reabriria esse buraco por outra porta.
    """
    classificacao = classificar_resposta(texto)

    now = now or datetime.now(timezone.utc)
    sb = get_supabase()
    try:
        # Paginado: um opt-out que cancelasse só os primeiros 1.000 pendentes deixaria
        # o resto sair para quem pediu para parar (ver `_ler_todas_as_paginas`).
        jobs = _ler_todas_as_paginas(lambda: sb.table("follow_up_jobs").select(
            "id, lead_id, job_type, status, sequence, fire_at, sent_at, metadata"
        ).eq("lead_id", lead_id).in_(
            "job_type", sorted(JOAO_JOB_TYPES)
        ).in_("status", ["pending", "sent"]).order("id"))
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

    if classificacao == RESPOSTA_INTERESSE:
        _encerrar_por_interesse(lead_id, pendentes, sb)
        return RESPOSTA_INTERESSE

    if classificacao == RESPOSTA_ADIAR:
        # O NÚMERO vem do banco, não da constante: `ADIAMENTO_ESTOQUE` virou o DEFAULT
        # DE CÓDIGO em 26/09 e o dono do funil edita o valor efetivo na tela
        # (spec §3.4/§3.5). A leitura é fail-closed para os 30 dias do código, e só
        # acontece NESTE ramo — uma resposta comum não paga uma consulta a mais.
        adiamento = timedelta(
            days=carregar_ajustes_joao()["adiamento_estoque_dias"])
    else:
        adiamento = ADIAMENTO_RESPOSTA
    _adiar_matriculas_joao(jobs, pendentes, sb, adiamento=adiamento)
    return RESPOSTA_ADIAR


def _encerrar_por_interesse(lead_id: str, pendentes: list[dict], sb) -> None:
    """O botão positivo encerra a matrícula. NÃO é blacklist (spec 2026-09-26 §2.3).

    Cancela TODOS os jobs `pending` do João deste lead — os toques que faltavam E o job
    de `mover_etapa`, que é só mais um `pending` e por isso cai junto sem regra nenhuma
    (o mesmo motivo pelo qual ele é um JOB e não uma varredura à parte). Mover o card
    para "Em atenção" depois de o lead dizer que quer repor seria marcar como abandonado
    exatamente quem levantou a mão.

    O ESCOPO é o mesmo dos outros dois ramos desta função — todas as matrículas abertas
    do lead, e não só a do card que mandou o último toque. Um lead pode ter card em
    Atacado e card em Reposição caminhando em paralelo; quem diz "quero repor agora"
    não deve seguir recebendo template automático pelo outro. O opt-out e o adiamento já
    tratam o lead inteiro pela mesma razão.

    Sem notificação: decisão do dono (spec §2.3). O lead respondeu no número do João e
    a conversa aparece em /conversas como qualquer outra.
    """
    ids = [j["id"] for j in pendentes if j.get("id")]
    if not ids:
        return
    try:
        sb.table("follow_up_jobs").update({
            "status": "cancelled", "cancel_reason": MOTIVO_INTERESSE,
        }).in_("id", ids).execute()
    except Exception as exc:
        logger.error(
            "[JOAO_CADENCIA] falha ao encerrar %d job(s) do lead %s por interesse: %s",
            len(ids), lead_id, exc)
        return
    logger.info(
        "[JOAO_CADENCIA] lead %s demonstrou interesse — %d job(s) encerrado(s); "
        "o vendedor assume", lead_id, len(ids))


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


def _adiar_matriculas_joao(
    jobs: list[dict], pendentes: list[dict], sb, *,
    adiamento: timedelta = ADIAMENTO_ESTOQUE,
) -> None:
    """Empurra os toques que ainda não saíram em `adiamento`, sem recomeçar a contagem.

    Os DOIS ramos de adiamento de `processar_resposta_joao` passam por aqui e só diferem
    na distância: quem apertou "ainda tenho estoque" leva
    `carregar_ajustes_joao()["adiamento_estoque_dias"]` (ata 41:40 — 30 dias no código
    desde 26/09, e o dono edita o efetivo na tela), e qualquer outra resposta leva
    `ADIAMENTO_RESPOSTA`, 3 dias de código (spec 2026-09-25 §3.3). O default do
    parâmetro continua sendo `ADIAMENTO_ESTOQUE`, que é o ramo que esta função serviu
    sozinha até aqui — mas o caminho de produção SEMPRE passa a distância explícita.

    Duas coisas ao mesmo tempo, e a segunda é a que costuma se perder: adiar, e NÃO
    recomeçar a contagem. Recomeçar devolveria a cadência ao toque 1, e o lead releria o
    texto que já leu. É também o que dá TETO a quem responde muito: cada resposta
    consome espera, nunca devolve toques.

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
        for adiado in adiar_toques(
            touches, ultimo_enviado=ultimo_enviado, adiamento=adiamento,
        ):
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
            chave, adiamento.days, len(abertos))
