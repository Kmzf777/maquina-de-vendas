import asyncio
import base64
import json
import os
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.leads.service import (
    get_or_create_lead, resolve_send_target, get_lead, advance_cold_deal_on_reply,
)
from app.conversations.service import (
    get_or_create_conversation, activate_conversation,
    update_conversation, save_message,
)
from app.agent.orchestrator import run_agent, resolve_prompt_key
from app.humanizer.splitter import split_into_bubbles
from app.whatsapp.registry import get_provider
from app.whatsapp.meta import extract_wamid
from app.channels.service import get_channel_by_id
from app.follow_up.service import schedule_followup as _schedule_followup
from app.campaigns.service import get_active_enrollment_for_lead as get_active_enrollment
from app.agent.tools import pop_deferred_media, pop_interest_marked
from app.utils.geo import ddd_to_region
from app.buffer.lead_lock import lead_run_lock

# Kill switch global — mude para True para reativar a Valéria
VALERIA_ENABLED = True
from app.db.supabase import get_supabase, run_with_retry

logger = logging.getLogger(__name__)


# Conexões HTTP/2 com Supabase/Meta às vezes recebem GOAWAY sob concorrência
# (rajada de disparo), derrubando o save e PERDENDO a mensagem do agente (regressão
# observada: Micheli, João). Retry simples preserva o estado no banco sem refatorar
# o cliente HTTP. httpx.TransportError cobre RemoteProtocolError/ConnectError/ReadError
# mas NÃO HTTPStatusError — então erros de aplicação (4xx/5xx) não são mascarados.
_DB_RETRY_ATTEMPTS = 3
_DB_RETRY_DELAY = 2  # segundos


async def _save_with_retry(label: str, fn, *args, **kwargs):
    """Executa uma operação de persistência síncrona com retry em drops de conexão."""
    last_exc: Exception | None = None
    for attempt in range(1, _DB_RETRY_ATTEMPTS + 1):
        try:
            return fn(*args, **kwargs)
        except httpx.TransportError as exc:
            last_exc = exc
            logger.warning(
                "[DB RETRY] %s — tentativa %d/%d falhou (conexão): %s",
                label, attempt, _DB_RETRY_ATTEMPTS, exc,
            )
            if attempt < _DB_RETRY_ATTEMPTS:
                await asyncio.sleep(_DB_RETRY_DELAY)
    raise last_exc


# Delays ASSIMÉTRICOS — limite real da Meta API: o "digitando…" NÃO re-renderiza no
# celular após o 1º balão ser entregue (o app ignora os 200 OK seguintes). Então:
#
# 1º balão (PENSATIVO): o indicador funciona, então vale demorar. A 4 chars/sec
#    (≈10 WPM) clampado em [5s, 15s], menos a latência já gasta pela LLM.
_TYPING_CHARS_PER_SEC: float = 4.0
_MIN_BUBBLE_DELAY: float = 5.0    # seconds — piso do 1º balão
_MAX_BUBBLE_DELAY: float = 15.0   # seconds — teto do 1º balão
# Balões SEGUINTES (SUCESSÃO RÁPIDA): sem indicador visual entre eles, um delay longo
# vira silêncio (parece que travou). Caem rápido em sequência, clampados num range curto
# e engessado — imita alguém que quebrou um texto grande no Enter. Sem pausa de transição.
_SUBSEQUENT_MIN_DELAY: float = 1.5   # seconds
_SUBSEQUENT_MAX_DELAY: float = 2.5   # seconds
# O indicador "digitando…" da Meta expira sozinho (~25s) e pode esfriar antes em rajada.
# Re-pulsamos o payload a cada N segundos durante o sleep para manter o status na tela
# (efetivo sobretudo no 1º balão, onde o indicador realmente aparece).
_TYPING_RENEWAL_INTERVAL: float = 10.0  # seconds


def _typing_secs(text: str) -> float:
    """Tempo 'pensativo' de digitação do 1º balão: clamp(len/CPS, MIN, MAX)."""
    return max(_MIN_BUBBLE_DELAY, min(_MAX_BUBBLE_DELAY, len(text) / _TYPING_CHARS_PER_SEC))


def _subsequent_secs(text: str) -> float:
    """Delay de sucessão rápida p/ balões pós-primeiro: clamp curto e engessado."""
    return max(_SUBSEQUENT_MIN_DELAY, min(_SUBSEQUENT_MAX_DELAY, len(text) / _TYPING_CHARS_PER_SEC))


def _bubble_delays(
    bubbles: list[str], is_rehearsal: bool, llm_latency: float = 0.0
) -> list[float]:
    """Pré-delay ASSIMÉTRICO por balão (ver constantes acima p/ o porquê).

    - Primeiro balão (pensativo): clamp(len/CPS, 5, 15) menos a latência da LLM (piso 0).
      É onde o "digitando…" aparece de fato, então a demora é natural.
    - Balões seguintes (sucessão rápida): clamp(len(prev)/CPS, 1.5, 2.5), SEM pausa de
      transição. Como a Meta não re-renderiza o typing aqui, delays longos virariam
      silêncio visual — então caem rápido em sequência.
    - Rehearsal zera tudo (testes/automação não esperam).
    """
    count = len(bubbles)
    if is_rehearsal or count == 0:
        return [0.0] * count

    first_delay = max(0.0, _typing_secs(bubbles[0]) - llm_latency)
    delays = [first_delay]
    for prev_bubble in bubbles[:-1]:
        delays.append(_subsequent_secs(prev_bubble))
    return delays


async def _sleep_with_typing_renewal(delay: float, provider, wamid: str | None) -> None:
    """Aguarda `delay` segundos re-pulsando o "digitando…" a cada _TYPING_RENEWAL_INTERVAL.

    O indicador da Meta expira (~25s) e pode esfriar antes sob carga; sem renovação, em
    delays longos o status some na tela do lead antes do balão chegar. Pulsamos no INÍCIO
    de cada fatia (t=0, t=interval, t=2·interval…) usando sempre o mesmo wamid da última
    mensagem do lead. Best-effort: falha no pulso nunca interrompe a espera. Sem wamid,
    apenas dorme (não há como pulsar pela Cloud API).
    """
    remaining = delay
    while remaining > 0:
        if wamid:
            try:
                await provider.send_typing_indicator(wamid)
            except Exception as e:
                logger.debug(f"[TYPING] renovação falhou: {e}")
        chunk = min(_TYPING_RENEWAL_INTERVAL, remaining)
        await asyncio.sleep(chunk)
        remaining -= chunk


async def _pulse_typing_loop(provider, wamid: str) -> None:
    """Pulsa "digitando…" imediatamente e a cada _TYPING_RENEWAL_INTERVAL até ser cancelado.

    Roda como task de fundo DURANTE o processamento do LLM/tools (antes da 1ª bolha existir).
    O 1º pulso é em t=0 (imediato). Best-effort: falha de pulso nunca derruba o turno.
    """
    try:
        while True:
            try:
                await provider.send_typing_indicator(wamid)
            except Exception as e:
                logger.debug("[TYPING] pulso de processamento falhou: %s", e)
            await asyncio.sleep(_TYPING_RENEWAL_INTERVAL)
    except asyncio.CancelledError:
        pass


def _start_typing_pulse(provider, wamid: str | None, is_rehearsal: bool):
    """Dispara o "digitando…" AGORA e o mantém pulsando enquanto o agente pensa.

    Cobre o vácuo de 30-47s de latência do LLM ANTES da 1ª bolha — sem isso o lead olha
    pra tela vazia e manda outra mensagem (o gatilho da race condition, auditoria
    5544991611703). Sem wamid (nada a referenciar na Cloud API) ou em rehearsal → no-op.
    """
    if not wamid or is_rehearsal:
        return None
    return asyncio.create_task(_pulse_typing_loop(provider, wamid))


def _stop_typing_pulse(task) -> None:
    """Cancela o pulso de digitação (idempotente). A partir daqui o pacing das bolhas
    assume a renovação do indicador via _sleep_with_typing_renewal."""
    if task is not None and not task.done():
        task.cancel()

# Marcador único de falha de áudio — usado tanto no replace do texto quanto na
# detecção de insistência (escalonamento). Mantido como constante para evitar drift.
_AUDIO_FAIL_MARKER = "[audio: nao foi possivel transcrever]"

# B3 (graceful degradation de mídia): mídia visual sem texto vira um marcador legível para
# o agente (a persona reconhece "[imagem]"/"[documento]" via base.py e não diz "chegou cortada").
# Os rótulos devem casar com os marcadores citados na seção "TRATAMENTO DE MÍDIA" do base.py.
_MEDIA_MARKERS = {
    "image": "[imagem]",
    "document": "[documento]",
    "video": "[vídeo]",
    "sticker": "[figurinha]",
}


def _apply_media_signal(resolved_text: str | None, message_type: str | None) -> str:
    """Injeta um marcador legível quando a mensagem é mídia visual SEM texto.

    Imagem/documento/vídeo/figurinha são resolvidos para texto vazio (o id é extraído e o
    conteúdo não é baixado). Sem um sinal textual, o agente recebe "" e divaga. Áudio NÃO entra
    aqui (tem fluxo próprio de transcrição/_AUDIO_FAIL_MARKER). Texto já presente é preservado
    (caption de imagem, por exemplo). Fail-safe: tipo desconhecido → retorna o texto original.
    """
    text = resolved_text or ""
    if text.strip():
        return text
    return _MEDIA_MARKERS.get(message_type or "", text)

# Transcrição de áudio: o endpoint OpenAI-compat do Gemini NÃO expõe
# /audio/transcriptions (Whisper) — a chamada antiga falhava 100% (auditoria
# 2026-06-22: 9 falhas/dia). O caminho suportado é generateContent com inline_data,
# que aceita OGG/opus (formato do áudio do WhatsApp).
_GEMINI_GENERATE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _audio_mime_type(content_type: str | None) -> str:
    """Normaliza o content-type p/ um mime aceito pelo Gemini.

    O WhatsApp manda 'audio/ogg; codecs=opus' — o parâmetro codecs quebra o Gemini,
    então mantemos só o tipo base. Default audio/ogg (voz do WhatsApp).
    """
    base = (content_type or "").split(";")[0].strip().lower()
    return base or "audio/ogg"


async def _transcribe_audio(audio_bytes: bytes, content_type: str | None) -> str:
    """Transcreve áudio via Gemini generateContent (inline_data). Levanta em falha."""
    mime = _audio_mime_type(content_type)
    b64 = base64.b64encode(audio_bytes).decode()
    url = _GEMINI_GENERATE_URL.format(model=settings.transcription_model)
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": "Transcreva o áudio a seguir em português do Brasil. "
                        "Responda APENAS com a transcrição literal, sem comentários, "
                        "aspas ou rótulos.",
                    },
                    {"inline_data": {"mime_type": mime, "data": b64}},
                ]
            }
        ]
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, params={"key": settings.gemini_api_key}, json=payload)
        resp.raise_for_status()
        data = resp.json()

    candidate = (data.get("candidates") or [{}])[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    transcript = "".join(p.get("text", "") for p in parts).strip()
    if not transcript:
        raise RuntimeError(
            f"transcrição vazia (finishReason={candidate.get('finishReason')!r})"
        )
    return transcript


async def _download_media_with_retry(provider, media_ref: str, attempts: int = 3, delay: int = 2):
    """download_media com retry em erros transientes (rede/GOAWAY)."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await provider.download_media(media_ref)
        except Exception as exc:  # noqa: BLE001 — instrumentação: queremos o tipo real
            last_exc = exc
            logger.warning(
                "[AUDIO] download tentativa %d/%d falhou para %s: %s: %s",
                attempt, attempts, media_ref, type(exc).__name__, exc,
            )
            if attempt < attempts:
                await asyncio.sleep(delay)
    raise last_exc


def _resolve_agent_profile_id(conversation: dict, channel: dict) -> str | None:
    """Resolve which agent_profile_id to use for this conversation.

    Priority:
    1. conversation.agent_profile_id (set by broadcast worker)
    2. channel.agent_profiles.id (default channel agent)
    3. None (human-only mode)
    """
    conv_agent = conversation.get("agent_profile_id")
    if conv_agent:
        return conv_agent
    channel_profile = channel.get("agent_profiles")
    if channel_profile:
        return channel_profile.get("id")
    return None


def _wamid_already_processed(wamid: str) -> bool:
    """Return True if a message with this wamid is already persisted in the messages table.

    This is a durable, defense-in-depth backstop: catches duplicates that survive
    a Redis flush/restart (which would allow the SETNX check at ingestion to pass again).
    Fail-open: on any exception, log a warning and return False — never drop a real message
    because of a DB hiccup.
    """
    try:
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("id")
            .eq("wamid", wamid)
            .limit(1)
            .execute()
        )
        return len(result.data) > 0
    except Exception as exc:
        logger.warning(
            "[DEDUP-DB] falha ao verificar wamid=%s no banco — fail-open (mensagem será processada): %s",
            wamid, exc,
        )
        return False


def _is_recent_duplicate(
    conversation_id: str, content: str, role: str, window_seconds: int = 30
) -> bool:
    """Return True only if an identical user message was recently saved AND received an assistant reply.

    A user message without a following assistant reply means the agent crashed — allow retry.
    """
    if role != "user":
        # For non-user roles, use simple time-based dedup
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("role", role)
            .eq("content", content)
            .gte("created_at", cutoff)
            .limit(1)
            .execute()
        )
        return len(result.data) > 0

    # For user messages: only deduplicate if an assistant reply followed the last identical message
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    sb = get_supabase()

    # Find the most recent identical user message within window
    dup = (
        sb.table("messages")
        .select("id, created_at")
        .eq("conversation_id", conversation_id)
        .eq("role", "user")
        .eq("content", content)
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not dup.data:
        return False  # No duplicate found

    dup_created_at = dup.data[0]["created_at"]

    # Check if an assistant reply was sent AFTER that duplicate user message
    reply = (
        sb.table("messages")
        .select("id")
        .eq("conversation_id", conversation_id)
        .eq("role", "assistant")
        .gt("created_at", dup_created_at)
        .limit(1)
        .execute()
    )
    # Only skip if a real reply was already sent — otherwise allow retry
    return len(reply.data) > 0


_FRUSTRATION_PATTERNS = [
    r"\bdesisto\b",
    r"\bdesisti\b",
    r"quero falar com (um |uma )?(humano|pessoa|atendente|vendedor)\b",
    r"\bfalar com atendente\b",
    r"\bfalar com (uma )?pessoa\b",
    r"\bfalar com humano\b",
    r"\bme passa (pro|para o) (humano|atendente|vendedor)\b",
    r"atendimento (pessimo|ruim|horrivel|terrivel|uma merda)\b",
    r"nao (quero|vou) (mais )?(falar|conversar) com (robo|ia|bot)\b",
]


async def _check_frustration_guardrail(
    text: str,
    lead_id: str,
    phone: str,
    conversation_id: str,
) -> bool:
    """Return True if a high-confidence frustration signal was found and encaminhar_humano was triggered.

    Bypasses the LLM entirely for unambiguous desistência or explicit human-agent requests.
    Only fires for very clear signals to avoid false positives.
    """
    import re
    import unicodedata

    def _normalize(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s.lower())
            if unicodedata.category(c) != "Mn"
        )

    normalized = _normalize(text)
    matched = next((p for p in _FRUSTRATION_PATTERNS if re.search(p, normalized)), None)
    if matched is None:
        return False

    logger.warning(
        "[FRUSTRATION_GUARDRAIL] sinal de frustração detectado para lead %s (conv=%s) "
        "— disparando encaminhar_humano direto sem chamar LLM. padrao=%r texto=%r",
        lead_id, conversation_id, matched, text[:120],
    )
    try:
        from app.agent.tools import execute_tool
        await execute_tool(
            "encaminhar_humano",
            {
                "vendedor": "Joao Bras",
                "motivo": "lead demonstrou frustracao ou desistencia — guardrail ativado",
            },
            lead_id=lead_id,
            phone=phone,
            conversation_id=conversation_id,
        )
    except Exception as exc:
        logger.error(
            "[FRUSTRATION_GUARDRAIL] execute_tool(encaminhar_humano) falhou para lead %s: %s",
            lead_id, exc, exc_info=True,
        )
    return True


def _count_recent_failed_audio(conversation_id: str, window_minutes: int = 30) -> int:
    """Conta mensagens recentes do lead cuja transcrição de áudio falhou.

    Usado para escalonar p/ humano quando o lead insiste em áudio que não transcreve,
    em vez de repetir "me manda em texto" num loop (auditoria 2026-06-22: Cris Bonanno).
    Fail-open: 0 em qualquer erro (nunca bloqueia o fluxo por causa da contagem).
    """
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("role", "user")
            .ilike("content", f"%{_AUDIO_FAIL_MARKER}%")
            .gte("created_at", cutoff)
            .execute()
        )
        return len(result.data)
    except Exception as exc:
        logger.warning("[AUDIO] falha ao contar áudios sem transcrição p/ conv %s: %s", conversation_id, exc)
        return 0


async def process_buffered_messages(
    phone: str, combined_text: str, channel_id: str = "",
    wamid: str | None = None, quoted_wamid: str | None = None,
):
    """Process accumulated buffer messages for a lead on a specific channel."""
    try:
        lead = get_or_create_lead(phone)
        channel = get_channel_by_id(channel_id) if channel_id else None
        if not channel:
            logger.warning(f"No channel found for {phone} (channel_id={channel_id}), skipping")
            return

        provider = get_provider(channel)
        conversation = get_or_create_conversation(lead["id"], channel_id)
    except Exception as e:
        logger.error(f"Fatal setup error for {phone}: {e}", exc_info=True)
        return

    # Activate conversation when lead first responds after template dispatch
    if conversation.get("status") in ("imported", "template_sent"):
        try:
            activate_conversation(conversation["id"])
            conversation["status"] = "active"
        except Exception as e:
            logger.warning(f"Failed to activate conversation {conversation['id']}: {e}")

    # Resolve media placeholders (also uploads audio to Supabase Storage)
    _media_url: str | None = None
    _message_type: str | None = None
    _document_name: str | None = None
    _metadata: dict | None = None
    try:
        resolved_text, _media_url, _message_type, _document_name, _metadata = await _resolve_media(combined_text, provider)
    except Exception as e:
        logger.warning(f"Failed to resolve media for {phone}: {e}")
        resolved_text = combined_text

    # B3 (graceful degradation de mídia): imagem/documento/vídeo/figurinha são resolvidos para
    # texto VAZIO (o marcador é removido em _resolve_media e o conteúdo não é baixado). Sem um
    # sinal textual, o agente recebe "" e divaga ou diz "chegou cortada" — exatamente a cegueira
    # de imagem da auditoria (lead 5561991573036 mandou a arte e foi ignorada). Injeta um marcador
    # legível que a persona reconhece (ver "TRATAMENTO DE MÍDIA" no base.py) e que vira preview no
    # CRM. Áudio tem fluxo próprio (transcrição/_AUDIO_FAIL_MARKER) e não entra aqui.
    resolved_text = _apply_media_signal(resolved_text, _message_type)

    # Dedup (wamid backstop — durable, defense-in-depth): runs FIRST because it is one cheap
    # indexed query with no time-window blind spot, making it the most reliable gate.
    # Rationale: catches duplicates that survive a Redis flush/restart (the SETNX layer at
    # ingestion would re-allow them after a flush, so this DB check is the last-resort backstop).
    # NOT race-safe: two concurrent deliveries of the same wamid can both pass here before either
    # saves. The Redis SETNX layer handles that race; this DB layer is last-resort only.
    # TODO: wrap blocking Supabase call in asyncio.to_thread (same pre-existing pattern as _is_recent_duplicate)
    if wamid:  # empty-string wamids are intentionally treated as absent (same as None)
        if _wamid_already_processed(wamid):
            logger.warning(
                "[DEDUP-DB] wamid=%s já persistido no banco — descartando duplicata para phone=%s",
                wamid, phone,
            )
            return

    # Dedup por conteúdo+tempo SOMENTE quando NÃO há wamid.
    # Quando a Meta fornece wamid (sempre, no fluxo Meta Cloud), os layers por wamid
    # (Redis SETNX na ingestão + _wamid_already_processed acima) são a autoridade: cada
    # mensagem é unicamente identificada, e retries da Meta repetem o MESMO wamid.
    # O dedup por conteúdo dava FALSO POSITIVO em respostas curtas legítimas e repetidas
    # ("sim", "ok", "não") a perguntas consecutivas — wamids distintos, mas mesmo texto
    # dentro da janela → a 2ª resposta era descartada (bug: lead 5534932262600, 2026-06-16).
    # Sem wamid (ex.: providers sem id de mensagem), mantemos a rede de segurança.
    if not wamid and _is_recent_duplicate(conversation["id"], resolved_text, "user"):
        logger.warning(f"Duplicate user message detected for {phone} (sem wamid), skipping")
        return

    # CA#1: tique azul SÓ AGORA — o turno da IA está começando (mensagem nova, pós-dedup).
    # Antes o read receipt era disparado na ingestão do webhook (tique de robô instantâneo).
    # Marcar a última mensagem como lida é cumulativo no WhatsApp (cobre todo o buffer).
    if wamid:
        try:
            await provider.mark_read(wamid)
        except Exception as e:
            logger.warning(f"[READ] falha ao marcar mensagem lida ({wamid}) p/ {phone}: {e}")

    # Always save the incoming user message
    try:
        _saved_user = await _save_with_retry(
            f"save user msg {phone}",
            save_message,
            conversation["id"], lead["id"], "user",
            resolved_text, conversation.get("stage"),
            sent_by="user",
            media_url=_media_url,
            message_type=_message_type,
            document_name=_document_name,
            metadata=_metadata,
            wamid=wamid,
            quoted_wamid=quoted_wamid,
        )
    except Exception as e:
        logger.error(f"Failed to save user message for {phone}: {e}", exc_info=True)
        # Abort: do not run agent without persistence — avoids unlogged AI responses
        return

    # Watermark do turno = created_at (autoritativo do DB) da mensagem que engatilhou ESTE
    # worker. É a régua do re-coalescing: se aparecer um inbound do cliente MAIS NOVO que
    # este (ao adquirir o lock OU durante o envio das bolhas), abortamos para o worker
    # posterior — já na fila do lock — responder o contexto COMPLETO numa única resposta,
    # em vez de empilhar blocos atropelados (auditoria 5533999429785, 2026-06-25).
    turn_watermark = _saved_user.get("created_at") if isinstance(_saved_user, dict) else None

    # Registrar resposta ao disparo se o lead tiver um broadcast_lead ativo
    try:
        from app.broadcast.service import record_broadcast_reply
        record_broadcast_reply(lead["id"])
    except Exception as e:
        logger.warning("Failed to record broadcast reply for %s: %s", phone, e)

    # REFLEXO DE SISTEMA (sem LLM): card aberto em 'Disparo feito' do funil frio da Valéria
    # → 'Respondeu'. A IA não gasta tokens com isso; é um reflexo do backend. Idempotente e
    # auto-escopado (no-op fora do funil frio), roda mesmo com ai_enabled=false. Fail-soft.
    try:
        advance_cold_deal_on_reply(lead["id"])
    except Exception as e:
        logger.warning("[REFLEX] advance_cold_deal_on_reply falhou p/ %s: %s", phone, e)

    # Notify campaign worker of reply
    try:
        from app.campaigns.worker import handle_campaign_reply
        handle_campaign_reply(lead["id"])
    except Exception as ce:
        logger.debug("[CAMPAIGNS] handle_campaign_reply error: %s", ce)

    # Fire keyword_received trigger for automation campaigns
    try:
        import asyncio as _asyncio
        from app.automation.triggers import fire_trigger
        _asyncio.create_task(fire_trigger(
            "message_received",
            lead_id=lead["id"],
            data={"body": resolved_text},
        ))
    except Exception as ke:
        logger.debug("[AUTOMATION] keyword fire_trigger error: %s", ke)

    # Track last inbound message time for WhatsApp 24h window enforcement
    try:
        run_with_retry(
            lambda: get_supabase().table("leads").update(
                {"last_customer_message_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", lead["id"]).execute(),
            label="last_customer_message_at",
        )
    except Exception as e:
        logger.warning(f"Failed to update last_customer_message_at for {lead['id']}: {e}")

    # Incrementa contador de não-lidas para o vendedor (resetado quando o vendedor responde)
    try:
        current = run_with_retry(
            lambda: get_supabase()
            .table("conversations")
            .select("unread_count")
            .eq("id", conversation["id"])
            .single()
            .execute(),
            label="unread_count read",
        )
        new_count = (current.data.get("unread_count") or 0) + 1
        run_with_retry(
            lambda: get_supabase().table("conversations").update(
                {"unread_count": new_count}
            ).eq("id", conversation["id"]).execute(),
            label="unread_count write",
        )
    except Exception as e:
        logger.warning(f"Failed to increment unread_count for {conversation['id']}: {e}")

    # Channel-level gate: human channels never run AI or schedule follow-ups
    if channel.get("mode", "ai") == "human":
        logger.info(
            f"[HUMAN CHANNEL] mode=human — IA e follow-up desativados "
            f"channel_id={channel_id} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # If AI is disabled globally, skip agent
    if not VALERIA_ENABLED:
        logger.info(
            f"[AI DISABLED] kill switch ativo — conv={conversation['id']} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # Single AI gate: lead.ai_enabled is the sole source of truth
    if not lead.get("ai_enabled", True):
        logger.info(
            f"[AI DISABLED] lead.ai_enabled=false — conv={conversation['id']} phone={phone}"
        )
        _update_last_msg(conversation["id"])
        return

    # Channel gate: if AI_PHONE_NUMBER_ID is configured, only those channels run AI
    allowed_ids = settings.ai_phone_number_ids
    if allowed_ids:
        channel_phone_number_id = (channel.get("provider_config") or {}).get("phone_number_id")
        if channel_phone_number_id not in allowed_ids:
            logger.info(
                f"[AI DISABLED] channel phone_number_id={channel_phone_number_id!r} not in allowlist "
                f"— conv={conversation['id']} phone={phone}"
            )
            _update_last_msg(conversation["id"])
            return

    # Resolve agent profile: conversation takes priority over channel default
    # None means no explicit profile — orchestrator defaults to valeria_inbound
    agent_profile_id = _resolve_agent_profile_id(conversation, channel)
    # Persona (prompt_key) usada nesta resposta — persistida para rastreabilidade.
    agent_persona = resolve_prompt_key(agent_profile_id)

    # Frustration guardrail: bypass LLM for unambiguous desistência / explicit human requests.
    if await _check_frustration_guardrail(resolved_text, lead["id"], phone, conversation["id"]):
        _update_last_msg(conversation["id"])
        return

    # Áudio insistente sem transcrição: escala p/ humano em vez de pedir texto em loop.
    # (auditoria 2026-06-22: Cris Bonanno mandou 4 áudios, recebeu só "manda em texto" e
    # quase abandonou.) Só dispara a partir do 2º áudio falho na janela — o 1º ainda pede texto.
    if _AUDIO_FAIL_MARKER in resolved_text:
        failed_audios = _count_recent_failed_audio(conversation["id"])
        if failed_audios >= 2:
            logger.warning(
                "[AUDIO ESCALATION] %d áudios sem transcrição p/ conv %s (phone=%s) — encaminhando humano",
                failed_audios, conversation["id"], phone,
            )
            try:
                from app.agent.tools import execute_tool
                await execute_tool(
                    "encaminhar_humano",
                    {
                        "vendedor": "Joao Bras",
                        "motivo": (
                            "lead enviando áudios que o sistema não conseguiu transcrever — "
                            "escalonado p/ atendimento humano"
                        ),
                    },
                    lead_id=lead["id"], phone=phone, conversation_id=conversation["id"],
                )
            except Exception as exc:
                logger.error(
                    "[AUDIO ESCALATION] execute_tool(encaminhar_humano) falhou p/ conv %s: %s",
                    conversation["id"], exc, exc_info=True,
                )
            _update_last_msg(conversation["id"])
            return

    # Run AI agent — up to 3 attempts with 5s backoff between failures
    _AGENT_MAX_ATTEMPTS = 3
    _AGENT_RETRY_DELAY = 5

    conversation["leads"] = lead
    lead_context = lead.get("metadata") or {}
    # Sinal "já é cliente / em tratativa": evita rodar o funil de lead novo com quem já
    # compra/está em atendimento (auditoria 2026-06-22: Grazieli). Surface via base prompt.
    try:
        from app.leads.service import lead_has_active_relationship
        if lead_has_active_relationship(lead["id"]):
            lead_context = {**lead_context, "lead_is_customer": True}
    except Exception as exc:
        logger.debug("[CUSTOMER SIGNAL] falha ao checar relacionamento p/ %s: %s", lead["id"], exc)

    # Personalização: dados que existem mas não chegavam ao prompt. lead_region é derivada
    # do DDD do telefone (proxy geográfico — único disponível em escala); company quando houver.
    personalization: dict = {}
    try:
        region = ddd_to_region(lead.get("phone"))
        if region:
            personalization["lead_region"] = region
    except Exception as exc:
        logger.debug("[PERSONALIZATION] falha ao derivar região do DDD p/ %s: %s", lead["id"], exc)
    if lead.get("company"):
        personalization["company"] = lead["company"]
    if personalization:
        lead_context = {**lead_context, **personalization}

    # SERIALIZAÇÃO POR LEAD (mutex Redis) + EARLY TYPING — auditoria race condition do
    # lead 5544991611703 (2026-06-24). A latência de 30-47s do LLM cria um vácuo; o lead
    # double-texta achando que travou; o 2º flush rodava CONCORRENTE e lia o histórico
    # antes do 1º persistir as bolhas → saída duplicada/atropelada. O lock serializa o
    # turno por lead (a RUN 2 espera a RUN 1 liberar); o early typing mostra "digitando…"
    # imediatamente e pulsa enquanto a IA pensa, fechando o vácuo que dispara o double-text.
    is_rehearsal = os.environ.get("REHEARSAL_MODE", "").lower() == "true"
    _typing_task = _start_typing_pulse(provider, wamid, is_rehearsal)
    try:
        async with lead_run_lock(lead["id"]):
            # RE-COALESCING (stale worker abort): enquanto este worker esperava na fila do
            # lock, o cliente pode ter mandado OUTRA mensagem — já salva por um worker que
            # está logo atrás na fila. Esse worker posterior lerá o histórico COMPLETO
            # (inclusive a mensagem deste turno) e formulará UMA resposta holística. Então
            # abortamos este turno stale em SILÊNCIO, sem gerar nem enviar nada — evita os
            # blocos empilhados/contraditórios da auditoria 5533999429785.
            if _has_newer_inbound(conversation["id"], turn_watermark):
                logger.info(
                    "[RECOALESCE] inbound mais novo ao adquirir lock (conv=%s, phone=%s) — "
                    "abortando turno stale; worker posterior responde o contexto completo.",
                    conversation["id"], phone,
                )
                pop_interest_marked(conversation["id"])  # não vaza flag p/ o próximo turno
                _update_last_msg(conversation["id"])
                return

            response = None
            _agent_t0 = time.monotonic()  # latência da LLM → desconta do delay do 1º balão (CA#4)
            for attempt in range(1, _AGENT_MAX_ATTEMPTS + 1):
                try:
                    response = await run_agent(
                        conversation, resolved_text,
                        lead_context=lead_context,
                        agent_profile_id=agent_profile_id,
                    )
                    break
                except Exception as e:
                    if attempt < _AGENT_MAX_ATTEMPTS:
                        logger.warning(
                            f"[AGENT RETRY] Tentativa {attempt}/{_AGENT_MAX_ATTEMPTS} falhou para {phone} "
                            f"(conv={conversation['id']}): {e} — nova tentativa em {_AGENT_RETRY_DELAY}s"
                        )
                        await asyncio.sleep(_AGENT_RETRY_DELAY)
                    else:
                        logger.error(
                            f"[AGENT FAILED] Todas as {_AGENT_MAX_ATTEMPTS} tentativas falharam para {phone} "
                            f"(conv={conversation['id']}): {e}",
                            exc_info=True,
                        )
                        pop_interest_marked(conversation["id"])  # evita leak do flag para o próximo turno
                        _update_last_msg(conversation["id"])
                        return

            # LLM terminou de pensar/resolver tools → encerra o pulso de "digitando…": daqui
            # o pacing das bolhas (_sleep_with_typing_renewal) assume a renovação do indicador.
            _stop_typing_pulse(_typing_task)

            # Pop the interest flag once right after the agent attempt — before any early returns
            # so stale state never leaks into the next turn (handoff, empty-response, or normal path).
            interest = pop_interest_marked(conversation["id"])

            if response is None:
                # Intentional: encaminhar_humano was called — handoff message already sent by the tool.
                logger.info(
                    "[AGENT HANDOFF] encaminhar_humano executado para %s (conv=%s, stage=%s) — "
                    "mensagem de handoff enviada pela tool.",
                    phone, conversation["id"], conversation.get("stage"),
                )
                _update_last_msg(conversation["id"])
                return

            if not response.strip():
                # Unexpected empty response — the AI returned no text and no handoff tool was called.
                logger.warning(
                    "[AGENT EMPTY RESPONSE] resposta de texto vazia inesperada para %s "
                    "(conv=%s, stage=%s) — nenhuma mensagem enviada ao lead.",
                    phone, conversation["id"], conversation.get("stage"),
                )
                _update_last_msg(conversation["id"])
                return

            # Send bubbles — persist only after all bubbles are delivered.
            # Destino de envio = wa_id real do lead quando houver (entregável); senão phone.
            # Evita 131026 em números BR registrados sem o 9º dígito (ver resolve_send_target).
            send_to = resolve_send_target(lead, phone)
            bubbles = split_into_bubbles(response)
            llm_latency = time.monotonic() - _agent_t0
            delays = _bubble_delays(bubbles, is_rehearsal, llm_latency=llm_latency)
            send_ok = True
            # B2: handoff/opt-out concorrente desligou a IA durante o envio → abortamos as
            # bolhas restantes (e a mídia/follow-up abaixo). O handoff é a última ação.
            handoff_aborted = False
            # RE-COALESCING em voo: cliente mandou inbound novo no meio do envio. Cortamos a
            # cauda (bolhas restantes + mídia diferida) e liberamos o lock cedo — o worker
            # posterior responde o contexto completo. Otimiza a cauda do lock só quando ela
            # empilharia (auditoria 5533999429785). Sem isso, mover a mídia p/ fora do lock
            # quebraria a ordem (fotos do turno antigo interleavando com o texto do novo).
            superseded = False
            sent_wamids: list[str | None] = []
            # Fechamento do gap de status (CA#4): os delays já foram TODOS pré-calculados acima.
            # _sleep_with_typing_renewal pulsa o "digitando…" no início e a cada ~10s durante a
            # espera, mantendo o status na tela do lead mesmo em delays longos (a Meta expira o
            # indicador em ~25s). O primeiro pulso é imediato, então — como não há await entre o
            # send_text de um balão e a entrada no helper do próximo — o "digitando…" reaparece
            # logo após cada balão, sem lacuna além da latência de rede inerente.
            for delay, bubble in zip(delays, bubbles):
                if delay > 0:
                    await _sleep_with_typing_renewal(delay, provider, wamid)
                # Trava anti-race (B2): se um handoff/opt-out concorrente desligou a IA
                # enquanto pacejávamos, não despeja mais bolha de venda em cima do lead
                # já transbordado — para imediatamente e preserva só o que já saiu.
                if not _ai_still_enabled(lead["id"]):
                    handoff_aborted = True
                    logger.warning(
                        "[HANDOFF GUARD] ai_enabled=false durante o envio — abortando bolhas "
                        "restantes (%d já enviadas) p/ conv %s",
                        len(sent_wamids), conversation["id"],
                    )
                    break
                # Trava de re-coalescing in-flight: o cliente falou no meio do envio. Paramos
                # de despejar o resto deste turno (já há um worker na fila p/ o inbound novo);
                # ele responderá imagem+texto numa única resposta, sem atropelar este bloco.
                if _has_newer_inbound(conversation["id"], turn_watermark):
                    superseded = True
                    logger.info(
                        "[RECOALESCE] inbound mais novo durante o envio — abortando %d bolha(s) "
                        "restante(s) p/ conv %s; worker posterior responde holisticamente.",
                        len(bubbles) - len(sent_wamids), conversation["id"],
                    )
                    break
                try:
                    send_result = await provider.send_text(send_to, bubble)
                    sent_wamids.append(extract_wamid(send_result))
                except Exception as e:
                    logger.error(f"Failed to send bubble to {send_to}: {e}", exc_info=True)
                    send_ok = False
                    break

            # Handoff concorrente OU re-coalescing in-flight: drena o catálogo de fotos
            # enfileirado sem enviar (handoff = transbordo; superseded = o worker posterior
            # reavalia a mídia no contexto completo). Popar evita que vaze ao próximo turno.
            if handoff_aborted or superseded:
                pop_deferred_media(conversation["id"])

            if send_ok:
                for bubble, bubble_wamid in zip(bubbles, sent_wamids):
                    try:
                        await _save_with_retry(
                            f"save assistant msg {phone}",
                            save_message,
                            conversation["id"], lead["id"], "assistant",
                            bubble, conversation.get("stage"),
                            sent_by="agent",
                            wamid=bubble_wamid,
                            agent_persona=agent_persona,
                        )
                    except Exception as e:
                        logger.error(f"Failed to save assistant message for {phone}: {e}", exc_info=True)

                # Agenda follow-up em dois gatilhos:
                #  (1) interesse comercial claro (marcar_interesse) — qualquer fluxo;
                #  (2) OUTBOUND "engajou e esfriou": o lead respondeu à abordagem ativa e pode sumir
                #      em seguida. Agendamos proativamente para resgatar o vácuo (ghosting), mesmo sem
                #      interesse declarado. schedule_followup é idempotente (cancela+recria), então se o
                #      lead responder de novo antes do disparo, o ciclo é reagendado.
                # Guard crítico do gatilho (2): opt-out e soft-rejection desativam a IA no mesmo turno —
                # nesses casos NÃO se agenda follow-up (re-checa ai_enabled fresco do banco). Handoff
                # retorna response=None e já saiu antes deste bloco.
                is_outbound = agent_persona == "valeria_outbound"
                # Não agenda follow-up se a IA foi desligada por handoff/opt-out concorrente
                # durante o envio (B2) — o lead já está com o vendedor humano.
                if conversation.get("followup_enabled", True) and channel and not handoff_aborted and not superseded:
                    should_schedule = bool(interest)
                    reason = "interesse comercial" if interest else ""
                    if not should_schedule and is_outbound:
                        fresh = get_lead(lead["id"]) or {}
                        if fresh.get("ai_enabled", True):
                            should_schedule = True
                            reason = "outbound engajou-e-esfriou"
                        else:
                            logger.info(
                                "[FOLLOWUP] outbound com IA desativada (opt-out/soft) — não agenda p/ %s",
                                phone,
                            )
                    if should_schedule:
                        try:
                            _schedule_followup(
                                conversation_id=conversation["id"],
                                lead_id=lead["id"],
                                channel_id=channel["id"],
                            )
                            logger.info("[FOLLOWUP] agendado (%s) para %s", reason, phone)
                        except Exception as e:
                            logger.warning(f"[FOLLOWUP] Falha ao agendar follow-up para {phone}: {e}")
                    else:
                        logger.info(
                            "[FOLLOWUP] sem gatilho de follow-up — não agendado para %s",
                            phone,
                        )

                # Dispatch deferred media (enviar_fotos / enviar_foto_produto) after text so
                # WhatsApp shows the explanatory text BEFORE the photos — preserves message order.
                # B2: se o handoff abortou o turno, a fila já foi drenada acima — não despeja
                # catálogo de fotos sobre o lead transbordado.
                deferred = [] if (handoff_aborted or superseded) else pop_deferred_media(conversation["id"])
                for item in deferred:
                    try:
                        await provider.send_image_base64(
                            send_to, item["b64"], item["mimetype"], caption=item.get("caption", "")
                        )
                        await asyncio.sleep(1)
                    except Exception as _e:
                        logger.error(
                            "Failed to send deferred media to %s: %s", send_to, _e, exc_info=True
                        )

            _update_last_msg(conversation["id"])
    finally:
        # Rede de segurança: garante que o pulso de digitação nunca vaza (idempotente).
        _stop_typing_pulse(_typing_task)


def _ai_still_enabled(lead_id: str) -> bool:
    """Re-lê ai_enabled fresco do banco — trava anti-race ENTRE gerar e ENVIAR as bolhas.

    B2 (auditoria lead 5544991611703, 2026-06-24): um turno concorrente (ou um guardrail
    no mesmo lead) chamou encaminhar_humano/registrar_optout e desligou a IA enquanto as
    bolhas deste turno ainda eram pacejadas — e três bolhas de PREÇO saíram coladas no
    handoff do João. Antes de cada bolha revalidamos: se a IA já foi desligada, paramos de
    despejar venda sobre um lead que já foi transbordado. O handoff é a ação definitiva.

    Fail-open: erro de leitura → True (na dúvida, não engole a mensagem do lead legítimo).
    """
    try:
        fresh = get_lead(lead_id) or {}
        return bool(fresh.get("ai_enabled", True))
    except Exception as exc:
        logger.warning(
            "[HANDOFF GUARD] falha ao reler ai_enabled p/ %s: %s — assume habilitado",
            lead_id, exc,
        )
        return True


def _has_newer_inbound(conversation_id: str, after_created_at: str | None) -> bool:
    """True se já existe mensagem do cliente (role='user') MAIS NOVA que a que engatilhou
    este turno (created_at > watermark).

    Régua do re-coalescing (auditoria 5533999429785, 2026-06-25), usada em dois pontos:
      (a) ao adquirir o lead_run_lock → aborta o turno stale (worker posterior responde tudo);
      (b) entre as bolhas do envio → corta a cauda quando o cliente fala no meio.
    Em ambos, a meta é uma ÚNICA resposta holística em vez de blocos empilhados.

    Fail-open: sem watermark (ex.: save não devolveu created_at) ou erro de leitura → False.
    NUNCA abortamos às cegas — engolir a única resposta de um lead legítimo é pior que o
    raro empilhamento que esta trava existe para evitar.
    """
    if not after_created_at:
        return False
    try:
        sb = get_supabase()
        result = (
            sb.table("messages")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("role", "user")
            .gt("created_at", after_created_at)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as exc:
        logger.warning(
            "[RECOALESCE] falha ao checar inbound mais novo p/ conv %s: %s — fail-open (não aborta)",
            conversation_id, exc,
        )
        return False


def _update_last_msg(conversation_id: str) -> None:
    try:
        update_conversation(
            conversation_id,
            last_msg_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        logger.warning(f"Failed to update last_msg_at for {conversation_id}: {e}")


def _upload_audio_to_storage(audio_bytes: bytes, content_type: str, media_ref: str, ext: str) -> str | None:
    """Upload audio to Supabase Storage and return permanent public URL."""
    try:
        from app.db.supabase import get_supabase
        sb = get_supabase()
        path = f"{media_ref}.{ext}"
        sb.storage.from_("audio").upload(
            path, audio_bytes,
            file_options={"content-type": content_type, "x-upsert": "true"},
        )
        return sb.storage.from_("audio").get_public_url(path)
    except Exception as e:
        logger.warning(f"Failed to upload audio to storage: {e}")
        return None


async def _resolve_media(
    text: str, provider
) -> tuple[str, str | None, str | None, str | None, dict | None]:
    """Replace media placeholders with type/url metadata.

    Returns (resolved_text, media_url, message_type, document_name, metadata).
    Audio: downloaded, transcribed, uploaded to Supabase Storage.
    Image/video/document/sticker: media_id extracted only, no download.
    Location/contact/reaction: metadata dict extracted from base64 JSON.
    """
    audio_id_pattern = r"\[audio: media_id=(\S+)\]"
    audio_url_pattern = r"\[audio: media_url=(\S+)\]"
    image_id_pattern = r"\[image: media_id=(\S+)\]"
    image_url_pattern = r"\[image: media_url=(\S+)\]"
    video_id_pattern = r"\[video: media_id=(\S+)\]"
    video_url_pattern = r"\[video: media_url=(\S+)\]"
    doc_url_pattern = r"\[document: media_url=(\S+?)(?:\s+filename_b64=([A-Za-z0-9+/=]+))?\]"
    sticker_url_pattern = r"\[sticker: media_url=(\S+)\]"
    meta_b64_pattern = r"\[(\w+): meta_b64=([A-Za-z0-9+/=]+)\]"

    storage_url: str | None = None
    message_type: str | None = None
    document_name: str | None = None
    metadata: dict | None = None

    for pattern in [audio_id_pattern, audio_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            message_type = "audio"
            storage_url = media_ref

            # ETAPA 1 — DOWNLOAD (com retry em erro transiente). Instrumentado p/
            # distinguir falha de download de falha de transcrição (auditoria 2026-06-22).
            try:
                audio_bytes, content_type = await _download_media_with_retry(provider, media_ref)
            except Exception as e:
                logger.error(
                    "[AUDIO] DOWNLOAD falhou definitivamente para %s: %s: %s",
                    media_ref, type(e).__name__, e,
                )
                text = text.replace(match.group(0), _AUDIO_FAIL_MARKER)
                continue

            ext = "ogg" if "ogg" in (content_type or "") else "mp4"
            uploaded_url = _upload_audio_to_storage(audio_bytes, content_type, media_ref, ext)
            if uploaded_url:
                storage_url = uploaded_url

            # ETAPA 2 — TRANSCRIÇÃO (Gemini generateContent). Log granular do erro real.
            try:
                transcript_text = await _transcribe_audio(audio_bytes, content_type)
                text = text.replace(match.group(0), f"[audio transcrito: {transcript_text}]")
            except httpx.HTTPStatusError as e:
                logger.error(
                    "[AUDIO] TRANSCRICAO HTTP %s para %s (model=%s, mime=%s): %s",
                    e.response.status_code, media_ref, settings.transcription_model,
                    _audio_mime_type(content_type), e.response.text[:300],
                )
                text = text.replace(match.group(0), _AUDIO_FAIL_MARKER)
            except Exception as e:
                logger.error(
                    "[AUDIO] TRANSCRICAO falhou para %s (model=%s, mime=%s, bytes=%d): %s: %s",
                    media_ref, settings.transcription_model, _audio_mime_type(content_type),
                    len(audio_bytes), type(e).__name__, e,
                )
                text = text.replace(match.group(0), _AUDIO_FAIL_MARKER)

    for pattern in [image_id_pattern, image_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            if message_type is None:
                message_type = "image"
                storage_url = media_ref
            text = text.replace(match.group(0), "")

    for pattern in [video_id_pattern, video_url_pattern]:
        for match in re.finditer(pattern, text):
            media_ref = match.group(1)
            if message_type is None:
                message_type = "video"
                storage_url = media_ref
            text = text.replace(match.group(0), "")

    for match in re.finditer(doc_url_pattern, text):
        media_ref = match.group(1)
        fname_b64 = match.group(2)
        if message_type is None:
            message_type = "document"
            storage_url = media_ref
            if fname_b64:
                try:
                    document_name = base64.b64decode(fname_b64).decode()
                except Exception:
                    pass
        text = text.replace(match.group(0), "")

    for match in re.finditer(sticker_url_pattern, text):
        media_ref = match.group(1)
        if message_type is None:
            message_type = "sticker"
            storage_url = media_ref
        text = text.replace(match.group(0), "")

    for match in re.finditer(meta_b64_pattern, text):
        meta_type = match.group(1)
        replacement = ""
        if meta_type in ("location", "contact", "reaction") and message_type is None:
            try:
                metadata = json.loads(base64.b64decode(match.group(2)).decode())
                message_type = meta_type
                if meta_type == "reaction":
                    # Reação NUNCA pode ser salva em branco — senão vira "mensagem fantasma"
                    # no CRM, sem o vendedor saber o que houve (auditoria 2026-06-22, lead
                    # 5531985712321). Mostra o emoji; o alvo é resolvido via target_wamid.
                    _emoji = (metadata or {}).get("emoji") or "👍"
                    replacement = f"[reagiu com {_emoji}]"
            except Exception as e:
                logger.warning(f"Failed to decode metadata for {meta_type}: {e}")
        text = text.replace(match.group(0), replacement)

    return text.strip(), storage_url, message_type, document_name, metadata
