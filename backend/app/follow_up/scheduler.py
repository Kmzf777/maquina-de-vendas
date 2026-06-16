# backend/app/follow_up/scheduler.py
import logging
from datetime import datetime, timezone, timedelta

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.follow_up.service import get_due_followups
from app.leads.service import save_message
from app.whatsapp.registry import get_provider
from app.db.supabase import get_supabase
from app.channels.service import get_channel_by_provider_config
from app.conversations.service import get_or_create_conversation
from app.whatsapp.meta import MetaCloudClient, extract_wamid

logger = logging.getLogger(__name__)

_last_health_check: datetime | None = None
_HEALTH_CHECK_INTERVAL = timedelta(hours=1)

_BILLING_ERROR_CODE = 131042
_META_API_BASE = "https://graph.facebook.com/v21.0"

# agent_profile "ValerIA - Outbound / Recuperacao" (prompt_key=valeria_outbound).
# Todo job ai_reengage é, por definição, uma recuperação outbound — força esta
# persona explicitamente (agent_profile_id=None resolveria para valeria_inbound).
AI_REENGAGE_PROFILE_ID = "b9930820-2c7e-4f1a-998f-f9531ed12c95"

# Número/template do João Bras usados para reabordar o lead pelo número dele.
# Mesma identidade do resgate de handoff (_process_handoff_rescue), centralizada aqui.
JOAO_PHONE_NUMBER_ID = "1049315514934778"
JOAO_TEMPLATE_NAME = "automacao_valeria_to_joao"
# Locale APROVADO na Meta para automacao_valeria_to_joao (verificado em message_templates,
# 2026-06-16): o template existe SÓ em `en` — o corpo é PT, mas o code da Meta é `en`.
# pt_BR não existe e causava 404 #132001 (job cancelado sem entregar). Não confiar em
# memória sobre o locale: conferir sempre em message_templates.
JOAO_TEMPLATE_LANG = "en"
# Nome do vendedor injetado no template (param nomeado nome_do_vendedor).
JOAO_VENDEDOR_NAME = "João"


def _build_joao_handoff_components(lead_name: str, vendedor: str = JOAO_VENDEDOR_NAME) -> list:
    """Componentes BODY do template automacao_valeria_to_joao.

    O template aprovado usa DOIS params NOMEADOS (`nome_do_lead`, `nome_do_vendedor`) —
    enviar 1 param posicional (como o código antigo fazia) causa erro de parâmetros na Meta.
    Usa o primeiro nome do lead; `vendedor` default João.
    """
    first_name = lead_name.split()[0] if lead_name else ""
    return [{
        "type": "body",
        "parameters": [
            {"type": "text", "parameter_name": "nome_do_lead", "text": first_name},
            {"type": "text", "parameter_name": "nome_do_vendedor", "text": vendedor},
        ],
    }]


# Corpo APROVADO do template automacao_valeria_to_joao (Meta), com os placeholders
# nomeados como campos .format(). Usado para PERSISTIR a mensagem do disparo no histórico
# (o envio em si vai pelo template; aqui só registramos o texto renderizado para o frontend).
# Se o texto aprovado mudar na Meta, atualizar aqui (fonte: message_templates.components).
_JOAO_TEMPLATE_BODY = (
    "Olá, {nome_do_lead}! \n\n"
    "Sou o {nome_do_vendedor} e recebi o repasse do seu contato feito com a Valéria mais cedo.\n"
    "Estou enviando esta mensagem para confirmar o seu atendimento.\n\n"
    "Para prosseguirmos com a sua solicitação, basta responder aqui."
)


def _render_joao_handoff_text(lead_name: str, vendedor: str = JOAO_VENDEDOR_NAME) -> str:
    """Renderiza o corpo do template do João com os params, para persistência no histórico."""
    first_name = lead_name.split()[0] if lead_name else ""
    return _JOAO_TEMPLATE_BODY.format(nome_do_lead=first_name, nome_do_vendedor=vendedor)


def _persist_joao_handoff_message(
    lead_id: str, joao_channel_id: str, lead_name: str, send_result: dict | None
) -> None:
    """Persiste a mensagem do template de resgate na conversa do CANAL DO JOÃO.

    Sem isto, o disparo sai pela Meta mas não vai para a tabela `messages` — e quando o
    lead responde (criando/reabrindo a conversa do João), o frontend mostra só a resposta,
    como se o cliente tivesse iniciado do nada. Cria/reaproveita a conversa do canal humano
    do João e grava a mensagem outbound com o wamid.

    Nunca levanta: falha de persistência não pode derrubar o disparo (já entregue à Meta).
    """
    try:
        conv = get_or_create_conversation(lead_id, joao_channel_id)
        save_message(
            lead_id=lead_id,
            role="assistant",
            content=_render_joao_handoff_text(lead_name),
            sent_by="followup",
            conversation_id=conv["id"],
            wamid=extract_wamid(send_result),
        )
        logger.info(
            "[JOAO_HANDOFF] mensagem do template persistida lead=%s conv=%s", lead_id, conv["id"]
        )
    except Exception as exc:
        logger.error(
            "[JOAO_HANDOFF] falha ao persistir mensagem do template (lead %s): %s",
            lead_id, exc, exc_info=True,
        )


async def send_joao_handoff_template(lead_phone: str, lead_name: str = "", lead_id: str | None = None) -> bool:
    """Dispara AGORA o template de reabordagem pelo número do João para o lead.

    Usado pelo fluxo `retomar_contato_vendedor` quando estamos dentro do horário
    comercial — o envio é síncrono para que a Valéria possa confirmar ao lead que
    "o João acabou de chamar". Retorna True em sucesso, False em qualquer falha.
    Nunca levanta: o chamador decide o fallback (reagendamento).

    Quando `lead_id` é informado, persiste a mensagem do template na conversa do canal
    do João (mesmo motivo do _process_handoff_rescue: o histórico não pode mostrar só a
    resposta do lead).
    """
    if not lead_phone:
        logger.error("[JOAO_REENGAGE] lead_phone vazio — disparo abortado")
        return False

    joao_channel = get_channel_by_provider_config("phone_number_id", JOAO_PHONE_NUMBER_ID, "meta_cloud")
    if not joao_channel:
        logger.error(
            "[JOAO_REENGAGE] Canal do João (phone_number_id=%s) não encontrado — disparo abortado",
            JOAO_PHONE_NUMBER_ID,
        )
        return False

    components = _build_joao_handoff_components(lead_name)

    try:
        provider = MetaCloudClient(joao_channel["provider_config"])
        send_result = await provider.send_template(
            lead_phone, JOAO_TEMPLATE_NAME, components=components, language_code=JOAO_TEMPLATE_LANG
        )
        logger.info(
            "[JOAO_REENGAGE] Template '%s' (%s) disparado AGORA para %s",
            JOAO_TEMPLATE_NAME, JOAO_TEMPLATE_LANG, lead_phone,
        )
        if lead_id:
            _persist_joao_handoff_message(lead_id, joao_channel["id"], lead_name, send_result)
        return True
    except Exception as exc:
        logger.error(
            "[JOAO_REENGAGE] Falha ao disparar template para %s: %s", lead_phone, exc, exc_info=True
        )
        return False


async def check_meta_channel_health() -> None:
    """Roda a cada hora: verifica canais Meta via API e escaneia logs por erros de billing."""
    global _last_health_check
    now = datetime.now(timezone.utc)
    if _last_health_check and (now - _last_health_check) < _HEALTH_CHECK_INTERVAL:
        return
    _last_health_check = now
    logger.info("[HEALTH] Iniciando health check dos canais Meta")

    await _health_check_via_api()
    await _health_check_via_logs(now)


async def _health_check_via_api() -> None:
    """GET leve em cada canal Meta para verificar token e quality_rating."""
    try:
        from app.channels.service import list_channels
        channels = [c for c in list_channels() if c.get("provider") == "meta_cloud"]
    except Exception as exc:
        logger.error("[HEALTH] Falha ao listar canais: %s", exc)
        return

    for channel in channels:
        config = channel.get("provider_config") or {}
        phone_number_id = config.get("phone_number_id", "")
        access_token = config.get("access_token", "")
        if not phone_number_id or not access_token:
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_META_API_BASE}/{phone_number_id}",
                    params={"fields": "id,quality_rating,display_phone_number"},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            data = resp.json()
            if not resp.is_success:
                error = data.get("error", {})
                code = error.get("code")
                logger.critical(
                    "[HEALTH] Canal '%s' retornou erro Meta code=%s: %s",
                    channel.get("name"), code, error.get("message"),
                )
                if code == 190:
                    from app.alerts.service import create_system_alert
                    create_system_alert(
                        "token_expired",
                        f"Token Meta expirado — canal {channel.get('name')}",
                        f"O access_token do canal '{channel.get('name')}' está inválido ou expirado. "
                        "Renove o token no Business Manager da Meta.",
                        severity="critical",
                        metadata={"channel_id": channel.get("id"), "meta_error": error},
                    )
            else:
                quality = (data.get("quality_rating") or "GREEN").upper()
                if quality == "RED":
                    logger.warning(
                        "[HEALTH] Canal '%s' com quality_rating=RED — risco de bloqueio pela Meta",
                        channel.get("name"),
                    )
                else:
                    logger.info("[HEALTH] Canal '%s' OK (quality=%s)", channel.get("name"), quality)
        except Exception as exc:
            logger.error("[HEALTH] Erro ao verificar canal '%s': %s", channel.get("name"), exc)


async def _health_check_via_logs(now: datetime) -> None:
    """Escaneia meta_webhook_logs da última hora por erros de billing (131042)."""
    try:
        sb = get_supabase()
        since = (now - _HEALTH_CHECK_INTERVAL).isoformat()
        result = (
            sb.table("meta_webhook_logs")
            .select("id, payload")
            .eq("direction", "inbound")
            .gte("received_at", since)
            .order("received_at", desc=True)
            .limit(200)
            .execute()
        )
        has_billing = any(
            str(_BILLING_ERROR_CODE) in str(row.get("payload", ""))
            for row in (result.data or [])
        )
        if has_billing:
            logger.critical("[HEALTH] Erros de billing (%d) detectados nos logs da última hora", _BILLING_ERROR_CODE)
            from app.alerts.service import fire_billing_alert
            await fire_billing_alert([{"code": _BILLING_ERROR_CODE, "title": "Business eligibility payment issue"}])
        else:
            logger.info("[HEALTH] Nenhum erro de billing nos logs da última hora")
            # Auto-resolve alertas de billing pendentes — billing foi normalizado
            try:
                sb = get_supabase()
                open_alerts = (
                    sb.table("system_alerts")
                    .select("id")
                    .eq("type", "billing_payment_issue")
                    .eq("resolved", False)
                    .execute()
                )
                if open_alerts.data:
                    ids = [a["id"] for a in open_alerts.data]
                    sb.table("system_alerts").update({
                        "resolved": True,
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                    }).in_("id", ids).execute()
                    logger.info(
                        "[HEALTH] %d alerta(s) de billing auto-resolvido(s) — sem erros na última hora",
                        len(ids),
                    )
            except Exception as exc:
                logger.error("[HEALTH] Falha ao auto-resolver alertas de billing: %s", exc)
    except Exception as exc:
        logger.error("[HEALTH] Falha ao escanear logs por billing errors: %s", exc)


_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_FOLLOWUP_MODEL = "gemini-2.5-flash"
# gemini-2.5-flash conta tokens de thinking + texto no mesmo budget via API de compatibilidade.
# Com max_tokens baixo, o modelo consome o budget pensando e trunca a saída (ex: "E aí, Rafael! Tudo").
_FOLLOWUP_MAX_TOKENS = 1024


async def _generate_followup_message(history: list[dict], sequence: int) -> str:
    """Gera mensagem contextualizada via LLM para o follow-up."""
    client = AsyncOpenAI(
        api_key=settings.gemini_api_key,
        base_url=_GEMINI_BASE_URL,
    )

    sequence_context = (
        "Esta é a primeira tentativa de retomar contato (1 hora após o último envio do vendedor). "
        "Seja leve, curioso e natural. Não pressione. Apenas demonstre interesse genuíno."
        if sequence == 1
        else
        "Esta é a última tentativa antes da janela de atendimento expirar (23 horas após o último envio). "
        "Seja mais direto, crie senso de oportunidade, mas sem ser agressivo."
    )

    messages_text = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Vendedor'}: {m['content']}"
        for m in history
    )

    resp = await client.chat.completions.create(
        model=_FOLLOWUP_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um assistente de vendas do Café Canastra. "
                    "Com base no histórico da conversa, escreva uma mensagem de follow-up para WhatsApp. "
                    f"{sequence_context} "
                    "Use linguagem informal brasileira, sem emojis excessivos. "
                    "Máximo 3 linhas. Não use saudações formais como 'Olá' ou 'Bom dia'. "
                    "Seja contextual — faça referência ao que foi discutido."
                ),
            },
            {
                "role": "user",
                "content": f"Histórico da conversa:\n{messages_text}\n\nEscreva o follow-up:",
            },
        ],
        max_tokens=_FOLLOWUP_MAX_TOKENS,
        temperature=0.8,
    )
    return (resp.choices[0].message.content or "").strip()


async def process_due_followups(now: datetime | None = None) -> None:
    """Processa jobs de follow-up vencidos. Chamado pelo worker a cada tick."""
    now = now or datetime.now(timezone.utc)
    jobs = get_due_followups(now)

    for job in jobs:
        # Rota jobs de resgate de handoff para handler dedicado (antes de qualquer guard padrão)
        if job.get("job_type") == "handoff_rescue":
            await _process_handoff_rescue(job, now)
            continue

        if job.get("job_type") == "lp_welcome":
            await _process_lp_welcome(job, now)
            continue

        if job.get("job_type") == "ai_reengage":
            await _process_ai_reengage(job, now)
            continue

        conversation_id = job["conversation_id"]
        lead = job["leads"]
        channel = job["channels"]
        conversation = job["conversations"]
        sequence = job["sequence"]

        # Guard: toggle desativado
        if not conversation.get("followup_enabled", True):
            _cancel_job(job["id"], "followup_disabled")
            logger.info(
                f"[FOLLOWUP] followup_enabled=false — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Guard: canal humano nunca executa follow-up
        if channel.get("mode", "ai") == "human":
            _cancel_job(job["id"], "human_channel")
            logger.info(
                f"[FOLLOWUP] mode=human — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Guard: janela de 24h
        last_msg_str = lead.get("last_customer_message_at")
        if not last_msg_str:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Sem last_customer_message_at — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
        if last_msg + timedelta(hours=24) <= now:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Janela expirada — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Busca histórico e gera mensagem via LLM
        try:
            sb = get_supabase()
            history_result = (
                sb.table("messages")
                .select("role, content")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            history = list(reversed(history_result.data or []))
            history = [m for m in history if m.get("role") and m.get("content")]
            message = await _generate_followup_message(history, sequence)
        except Exception as e:
            logger.error(f"[FOLLOWUP] Erro ao gerar mensagem seq={sequence} conversation={conversation_id}: {e}", exc_info=True)
            continue

        if not message:
            _cancel_job(job["id"], "empty_response")
            logger.warning(
                f"[FOLLOWUP] LLM retornou vazio — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # Envia via WhatsApp
        try:
            provider = get_provider(channel)
            send_result = await provider.send_text(lead["phone"], message)
        except Exception as e:
            logger.error(
                f"[FOLLOWUP] Falha ao enviar seq={sequence} lead={lead['phone']}: {e}",
                exc_info=True,
            )
            # Intencional per spec: em caso de falha no envio, não atualiza status — job será retentado no próximo tick
            continue

        # Persiste mensagem
        try:
            save_message(
                lead_id=job["lead_id"],
                role="assistant",
                content=message,
                stage=conversation.get("stage"),
                sent_by="followup",
                conversation_id=conversation_id,
                wamid=extract_wamid(send_result),
            )
        except Exception as e:
            logger.error(f"[FOLLOWUP] Falha ao salvar mensagem seq={sequence}: {e}")

        _mark_sent(job["id"])
        logger.info(f"[FOLLOWUP] Enviado seq={sequence} lead={lead['phone']}")


async def _process_handoff_rescue(job: dict, now: datetime) -> None:
    """Verifica se lead contatou João nos últimos 15 min. Se não, dispara template de resgate."""
    metadata = job.get("metadata") or {}
    lead_phone = metadata.get("lead_phone")
    joao_phone_number_id = metadata.get("joao_phone_number_id", "1049315514934778")
    template_name = metadata.get("template_name", JOAO_TEMPLATE_NAME)
    # Template 'automacao_valeria_to_joao' está aprovado na Meta SÓ em `en` (corpo é PT,
    # mas o locale Meta é `en`) e usa 2 params NOMEADOS. O default pt_BR causava 404
    # (#132001 "does not exist in pt_BR") e o job era cancelado sem entregar.
    # Fonte de verdade: message_templates (verificado 2026-06-16). Ver JOAO_TEMPLATE_LANG.
    language_code = metadata.get("language_code", JOAO_TEMPLATE_LANG)

    if not lead_phone:
        _cancel_job(job["id"], "missing_lead_phone")
        logger.error(f"[HANDOFF_RESCUE] Job {job['id']} sem lead_phone no metadata")
        return

    joao_channel = get_channel_by_provider_config("phone_number_id", joao_phone_number_id, "meta_cloud")
    if not joao_channel:
        _cancel_job(job["id"], "joao_channel_not_found")
        logger.error(
            f"[HANDOFF_RESCUE] Canal do João (phone_number_id={joao_phone_number_id}) não encontrado"
        )
        return

    sb = get_supabase()
    cutoff = (now - timedelta(minutes=15)).isoformat()

    try:
        conv_result = (
            sb.table("conversations")
            .select("id")
            .eq("lead_id", job["lead_id"])
            .eq("channel_id", joao_channel["id"])
            .execute()
        )
        if conv_result.data:
            conv_ids = [c["id"] for c in conv_result.data]
            msg_result = (
                sb.table("messages")
                .select("id")
                .in_("conversation_id", conv_ids)
                .eq("role", "user")
                .gte("created_at", cutoff)
                .limit(1)
                .execute()
            )
            if msg_result.data:
                logger.info(
                    f"[HANDOFF_RESCUE] Lead {job['lead_id']} já contatou João — resgate desnecessário"
                )
                _mark_sent(job["id"])
                return
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Erro ao verificar contato do lead {job['lead_id']}: {exc}",
            exc_info=True,
        )
        # Segurança: se falhou a verificação, envia o template (falso negativo > falso positivo)

    lead_name = (job.get("leads") or {}).get("name") or metadata.get("lead_name") or ""
    components = _build_joao_handoff_components(lead_name)

    try:
        provider = MetaCloudClient(joao_channel["provider_config"])
        send_result = await provider.send_template(lead_phone, template_name, components=components, language_code=language_code)
        logger.info(f"[HANDOFF_RESCUE] Template '{template_name}' ({language_code}) enviado para {lead_phone}")
    except httpx.HTTPStatusError as http_exc:
        status = http_exc.response.status_code
        if 400 <= status < 500:
            _cancel_job(job["id"], f"meta_permanent_error_{status}")
            logger.error(
                f"[HANDOFF_RESCUE] Erro permanente Meta HTTP {status} para {lead_phone} — job cancelado"
            )
        else:
            logger.error(
                f"[HANDOFF_RESCUE] Erro transitório Meta HTTP {status} para {lead_phone} — será retentado",
                exc_info=True,
            )
        return
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Falha ao enviar template para {lead_phone}: {exc}",
            exc_info=True,
        )
        return  # erro transitório → retry no próximo tick

    # Persiste a mensagem do template na conversa do canal do João (senão o histórico
    # mostra só a resposta do lead — "como se ele tivesse iniciado do nada").
    _persist_joao_handoff_message(job["lead_id"], joao_channel["id"], lead_name, send_result)

    _mark_sent(job["id"])


async def _process_lp_welcome(job: dict, now: datetime) -> None:
    """Dispara template de boas-vindas para lead capturado por landing page.

    Só envia se o lead ainda não enviou mensagem — guarda do requisito
    'apenas em caso do lead não enviar nenhuma mensagem'.
    """
    metadata = job.get("metadata") or {}
    lead_phone = metadata.get("lead_phone")
    template_name = metadata.get("template_name")
    language_code = metadata.get("language_code", "pt_BR")
    channel = job["channels"]
    lead = job["leads"]

    if not lead_phone or not template_name:
        _cancel_job(job["id"], "missing_metadata")
        logger.error(
            "[LP_WELCOME] Job %s sem lead_phone ou template_name no metadata", job["id"]
        )
        return

    # Guard: só dispara se o lead ainda não entrou em contato via WhatsApp
    if lead.get("last_customer_message_at"):
        _cancel_job(job["id"], "lead_already_replied")
        logger.info(
            "[LP_WELCOME] Lead já enviou mensagem (last_customer_message_at=%s) — cancelando job %s",
            lead["last_customer_message_at"],
            job["id"],
        )
        return

    lead_name = metadata.get("lead_name") or (job.get("leads") or {}).get("name") or ""
    first_name = lead_name.split()[0] if lead_name else ""
    components = [{"type": "body", "parameters": [{"type": "text", "text": first_name}]}] if first_name else None

    try:
        provider = MetaCloudClient(channel["provider_config"])
        await provider.send_template(lead_phone, template_name, components=components, language_code=language_code)
        logger.info("[LP_WELCOME] Template '%s' enviado para %s", template_name, lead_phone)
    except httpx.HTTPStatusError as http_exc:
        status = http_exc.response.status_code
        if 400 <= status < 500:
            _cancel_job(job["id"], f"meta_permanent_error_{status}")
            logger.error(
                "[LP_WELCOME] Erro permanente Meta HTTP %s para %s — job cancelado", status, lead_phone
            )
        else:
            logger.error(
                "[LP_WELCOME] Erro transitório Meta HTTP %s para %s — será retentado", status, lead_phone,
                exc_info=True,
            )
        return
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Falha ao enviar template para %s: %s", lead_phone, exc, exc_info=True
        )
        return  # erro transitório → retry no próximo tick

    _mark_sent(job["id"])


async def _process_ai_reengage(job: dict, now: datetime) -> None:
    """Reativação pós-handoff: roda o AGENTE REAL (Valéria) sobre a última mensagem
    inbound órfã do lead e envia a resposta livre.

    Diferente do follow-up `standard` (que gera uma mensagem genérica via Gemini),
    este handler reinvoca `run_agent` sobre o texto da última mensagem do cliente —
    a Valéria "continua o atendimento" de onde parou. Agendado pelo script avulso
    `scripts/sql/reativar_ia_valeria_janela24h.sql`.

    Guards estritos (qualquer um falha → não envia):
    - lead.ai_enabled deve estar True (se alguém redesativou, aborta sem enviar).
    - janela de 24h da Meta deve estar aberta (senão free-text é rejeitado #131047).
    - canal humano nunca roda IA.

    O lead é RE-LIDO do banco aqui porque o select de `get_due_followups` não traz
    `ai_enabled`/`metadata` — não confiar no payload joinado para os guards.
    """
    from app.agent.orchestrator import run_agent
    from app.humanizer.splitter import split_into_bubbles

    channel = job["channels"]
    conversation = job["conversations"]
    conversation_id = job["conversation_id"]

    # Guard: canal humano nunca roda IA
    if channel.get("mode", "ai") == "human":
        _cancel_job(job["id"], "human_channel")
        logger.info("[AI_REENGAGE] mode=human — cancelando conv=%s", conversation_id)
        return

    sb = get_supabase()

    # Re-lê o lead para obter ai_enabled/metadata/last_customer_message_at atuais.
    try:
        lead_row = (
            sb.table("leads")
            .select("id, phone, name, ai_enabled, last_customer_message_at, metadata")
            .eq("id", job["lead_id"])
            .single()
            .execute()
        )
        lead = lead_row.data
    except Exception as exc:
        logger.error("[AI_REENGAGE] falha ao reler lead %s: %s", job["lead_id"], exc, exc_info=True)
        return  # transitório → retry no próximo tick

    if not lead or not lead.get("ai_enabled", False):
        _cancel_job(job["id"], "ai_disabled")
        logger.info("[AI_REENGAGE] ai_enabled=false — cancelando conv=%s", conversation_id)
        return

    phone = lead["phone"]

    # Guard: janela de 24h (mesma regra do follow-up standard)
    last_msg_str = lead.get("last_customer_message_at")
    if not last_msg_str:
        _cancel_job(job["id"], "window_expired")
        logger.info("[AI_REENGAGE] sem last_customer_message_at — cancelando conv=%s", conversation_id)
        return
    last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
    if last_msg + timedelta(hours=24) <= now:
        _cancel_job(job["id"], "window_expired")
        logger.warning("[AI_REENGAGE] janela 24h expirada — cancelando conv=%s", conversation_id)
        return

    # Recupera a última mensagem inbound (a órfã) para o agente continuar o atendimento.
    try:
        last_inbound = (
            sb.table("messages")
            .select("content")
            .eq("conversation_id", conversation_id)
            .eq("role", "user")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("[AI_REENGAGE] falha ao buscar última inbound conv=%s: %s", conversation_id, exc, exc_info=True)
        return  # transitório → retry

    if not last_inbound.data or not (last_inbound.data[0].get("content") or "").strip():
        _cancel_job(job["id"], "no_inbound_message")
        logger.warning("[AI_REENGAGE] sem mensagem inbound — cancelando conv=%s", conversation_id)
        return
    orphan_text = last_inbound.data[0]["content"]

    # Força a persona valeria_outbound: ai_reengage é sempre recuperação outbound.
    # agent_profile_id=None resolveria para valeria_inbound (persona errada).
    conversation["leads"] = lead
    lead_context = lead.get("metadata") or {}
    try:
        response = await run_agent(
            conversation, orphan_text,
            lead_context=lead_context,
            agent_profile_id=AI_REENGAGE_PROFILE_ID,
        )
    except Exception as exc:
        logger.error("[AI_REENGAGE] run_agent falhou conv=%s: %s", conversation_id, exc, exc_info=True)
        return  # transitório → retry no próximo tick (não marca sent)

    if response is None:
        # encaminhar_humano foi chamado pela tool — mensagem de handoff já enviada.
        logger.info("[AI_REENGAGE] handoff via tool conv=%s — nada a enviar", conversation_id)
        _mark_sent(job["id"])
        return

    if not response.strip():
        _cancel_job(job["id"], "empty_response")
        logger.warning("[AI_REENGAGE] resposta vazia — cancelando conv=%s", conversation_id)
        return

    provider = get_provider(channel)
    bubbles = split_into_bubbles(response)
    sent_wamids: list[str | None] = []
    for bubble in bubbles:
        try:
            send_result = await provider.send_text(phone, bubble)
            sent_wamids.append(extract_wamid(send_result))
        except Exception as exc:
            logger.error("[AI_REENGAGE] falha ao enviar bubble conv=%s: %s", conversation_id, exc, exc_info=True)
            return  # não marca sent → retry no próximo tick

    for bubble, bubble_wamid in zip(bubbles, sent_wamids):
        try:
            save_message(
                lead_id=job["lead_id"],
                role="assistant",
                content=bubble,
                stage=conversation.get("stage"),
                sent_by="agent",
                conversation_id=conversation_id,
                wamid=bubble_wamid,
                # ai_reengage força AI_REENGAGE_PROFILE_ID → persona sempre outbound.
                agent_persona="valeria_outbound",
            )
        except Exception as exc:
            logger.error("[AI_REENGAGE] falha ao salvar bubble conv=%s: %s", conversation_id, exc)

    _mark_sent(job["id"])
    logger.info("[AI_REENGAGE] Valéria respondeu lead=%s conv=%s", phone, conversation_id)


def _cancel_job(job_id: str, reason: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).eq("id", job_id).execute()


def _mark_sent(job_id: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()
