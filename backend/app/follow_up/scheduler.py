# backend/app/follow_up/scheduler.py
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone, timedelta

import httpx

from app.agent.gemini_client import generate, user_content
from app.config import settings
from app.follow_up.service import get_due_followups, should_proactive_handoff, _ENV_TAG
from app.leads.service import (
    resolve_send_target, create_deal, record_dispatch_note,
    strip_greeting_prefix, sanitize_display_name,
)
from app.whatsapp.registry import get_provider
from app.db.supabase import get_supabase
from app.channels.service import get_channel_by_provider_config
from app.conversations.service import get_or_create_conversation
from app.conversations.service import save_message as save_message_conv
from app.whatsapp.meta import MetaCloudClient, extract_wamid
from app.humanizer.splitter import split_into_bubbles
from app.agent.prompts.voice_card import VALERIA_VOICE_CARD
from app.agent.token_tracker import track_token_usage
from app.templates.intent import dispatch_metadata
from app.alerts.service import create_system_alert

logger = logging.getLogger(__name__)

_last_health_check: datetime | None = None
_HEALTH_CHECK_INTERVAL = timedelta(hours=1)

_BILLING_ERROR_CODE = 131042
_META_API_BASE = "https://graph.facebook.com/v21.0"
# Eixo 3B / Rodada 5 (10/07): template utility aprovado usado para reabrir a janela 24h
# quando um toque da cadência (ou retorno agendado) vence com a janela fechada. O antigo
# `continuar_conversa` pedia desculpas por atraso NOSSO ("não consegui te responder a
# tempo") num gatilho onde quem silenciou foi o LEAD — incoerência comercial. O novo
# enquadra a pendência no lead: "O Cafe Canastra esta aguardando sua confirmacao sobre
# {{2}} desde {{3}}" + QUICK_REPLYs (inclusive saída digna "Nao tenho interesse").
# ATENÇÃO (locale): a APROVAÇÃO é `en_US` (corpo em português) — o language_code enviado
# DEVE ser o da aprovação; e o BODY exige exatamente 3 params POSICIONAIS.
_REOPEN_TEMPLATE_NAME = "utilidade_geral_confirmacao_v1"
_REOPEN_TEMPLATE_LANGUAGE = "en_US"
# Assunto ({{2}}) fixo e honesto: há de fato um atendimento em aberto — a conversa.
_REOPEN_TOPIC = "a continuidade do atendimento"

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

# Task C-4 (higiene de nome): fallback neutro para {{primeiro_nome}}/nome_do_lead quando
# não há nome real — nem antes (lead_name vazio), nem depois de strip_greeting_prefix
# remover uma saudação que tinha vazado pro campo nome ("Olá, boa tarde", "Boa tarde.").
# Decisão DELIBERADA (não acidental): a Meta REJEITA parâmetro de template com texto
# vazio (""), e omitir o componente inteiro arrisca rejeição por parâmetro nomeado
# ausente (o template exige o param). "tudo bem" é uma leitura natural no WhatsApp tanto
# como saudação própria ("Olá, tudo bem!") quanto como abertura ("olá tudo bem, recebemos
# sua solicitação..."). Sem isso, "Olá, boa tarde" virava o nome "Olá," e cascateava pros
# templates: o disparo de LP saudou "olá Olá," e o resgate do João abriu "Olá, Olá,!".
_NAME_FALLBACK = "tudo bem"


def _build_joao_handoff_components(lead_name: str, vendedor: str = JOAO_VENDEDOR_NAME) -> list:
    """Componentes BODY do template automacao_valeria_to_joao.

    O template aprovado usa DOIS params NOMEADOS (`nome_do_lead`, `nome_do_vendedor`) —
    enviar 1 param posicional (como o código antigo fazia) causa erro de parâmetros na Meta.
    Usa o primeiro nome do lead (após strip_greeting_prefix); cai no fallback
    _NAME_FALLBACK quando não sobra nome real. `vendedor` default João.
    """
    stripped = strip_greeting_prefix(lead_name)
    first_name = stripped.split()[0] if stripped else _NAME_FALLBACK
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
    """Renderiza o corpo do template do João com os params, para persistência no histórico.

    Mesma lógica de nome de _build_joao_handoff_components (strip_greeting_prefix +
    fallback _NAME_FALLBACK) — o texto PERSISTIDO precisa renderizar o MESMO nome/fallback
    que foi de fato ENVIADO à Meta, senão o histórico no CRM diverge do que o lead recebeu.
    """
    stripped = strip_greeting_prefix(lead_name)
    first_name = stripped.split()[0] if stripped else _NAME_FALLBACK
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
        save_message_conv(
            conversation_id=conv["id"],
            lead_id=lead_id,
            role="assistant",
            content=_render_joao_handoff_text(lead_name),
            sent_by="followup",
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


_FOLLOWUP_MODEL = "gemini-2.5-flash"  # sunset REAL do 2.5 e 16/10/2026 — migrar p/ 3.x antes
# gemini-2.5-flash conta tokens de thinking + texto no MESMO budget de saída.
# Com teto baixo E thinking ligado, o modelo consome o budget pensando e trunca a saída
# (auditoria leads 5566999975586 / 5531996039118, 2026-06-25: "...o que te fez pensar em").
# A cura é DUPLA e espelha o orchestrator (MAX_OUTPUT_TOKENS=4096 + thinking off):
#   1) desligar o thinking na chamada (thinking_off=True → thinking_budget=0 nativo);
#   2) dar teto folgado (4096). Mesmo assim, finish_reason="MAX_TOKENS" é barrado em
#      process_due_followups — nunca enviamos mensagem pela metade.
_FOLLOWUP_MAX_TOKENS = 4096


_FOLLOWUP_TZ_BR = timezone(timedelta(hours=-3))

# Sentinela de adiamento: quando a ÚLTIMA mensagem do cliente pede para ser contatado depois,
# o LLM devolve EXATAMENTE esta string (e nada mais) e o scheduler aborta o disparo silenciosamente.
# Ver auditoria do lead 5566999975586 (2026-06-25): o cliente disse "estou em viagem essa semana,
# mas na próxima já estarei mais tranquilo" e o follow-up disparou ~1h42 depois, ignorando o pedido.
_DEFERRAL_MARKER = "[ADIAMENTO_DETECTADO]"

# Estrutura em headings Markdown consistentes (gemini-prompting-strategies.md → "Use consistent
# structure" + "Prioritize critical instructions at the very beginning"): a verificação de
# adiamento é a instrução crítica e vem como a 1ª seção. Linguagem direta e precisa, sem retórica.
_FOLLOWUP_REENGAGE_INSTRUCTION = (
    "# TAREFA — FOLLOW-UP DE REENGAJAMENTO\n\n"
    "## 1. Verificação de adiamento (faça ANTES de tudo)\n"
    "Analise a ÚLTIMA mensagem do cliente no histórico. Se ele pediu explicitamente para ser "
    "contatado depois, em outra data ou momento futuro, ou disse que estava viajando, ocupado ou "
    "sem tempo agora (ex.: 'me chama semana que vem', 'depois eu te falo', 'estou em viagem essa "
    "semana', 'agora não dá', 'mês que vem a gente fala'), responda EXATAMENTE com a string "
    f"{_DEFERRAL_MARKER} e nada mais — não gere mensagem de acompanhamento. Insistir num lead que "
    "já marcou um retorno é a falha mais grave deste fluxo.\n\n"
    "## 2. Tarefa (apenas se NÃO houver adiamento)\n"
    "Você está retomando o contato com um lead que parou de responder (mensagem de follow-up no "
    "WhatsApp). Com base no histórico, escreva UMA mensagem curta de reengajamento, contextual ao "
    "que já foi conversado. Siga TODAS as regras de voz e formato da persona acima (minúsculas, "
    "acentos, SEM ponto final, no máximo 3 bolhas curtas separadas por uma linha em branco, "
    "sem emoji). Use quebras de linha REAIS para separar as bolhas — nunca escreva os "
    "caracteres literais barra-n no texto.\n\n"
    "## 3. Proibições\n"
    "- PROIBIDO abrir com saudação formal ('Olá', 'Bom dia'). O uso do nome do lead segue a "
    "moderação de nome da persona acima.\n"
    "- PROIBIDO abertura ou pergunta vazia de preenchimento: 'tudo joia?', 'tudo bem?', 'tudo certo "
    "por aí?', 'e aí, sumiu?'. Elas não acrescentam nada e escancaram a automação.\n"
    "- PROIBIDO inventar período de tempo. NAO diga 'outro dia', 'semana passada', 'mes passado' ou "
    "qualquer intervalo que voce nao tenha certeza. Use APENAS o tempo informado no contexto temporal "
    "abaixo (se houver). Na duvida, nao cite quando foi a ultima conversa.\n\n"
    "## 4. Conteúdo\n"
    "A mensagem DEVE retomar pelo ASSUNTO CONCRETO que ficou em aberto (o produto que ele olhava, a "
    "dúvida, o interesse que demonstrou) e trazer algo de valor ou uma pergunta específica sobre "
    "aquilo — nunca um check-in genérico."
)


# GUARDRAIL DE SANIDADE (auditoria lead 5561984336980, 2026-06-24).
# O LLM às vezes RECUSA a tarefa de follow-up e devolve um meta-comentário em vez de
# uma mensagem ("Não é apropriado enviar..."; "Como uma IA, não posso..."; "O lead
# informou que..."). Antes, `process_due_followups` só barrava resposta VAZIA — o texto
# cru da recusa ia direto pro cliente. Estes marcadores nunca aparecem numa mensagem
# real da Valéria (minúscula, casual, sobre o assunto em aberto), então servem de filtro
# seguro. Normalizamos sem acento + minúsculo antes de casar.
_META_COMMENT_MARKERS = (
    "nao e apropriado", "nao seria apropriado",
    "nao e adequado", "nao seria adequado",
    "como uma ia", "sou uma ia", "enquanto ia", "como ia,",
    "desculpe, mas", "desculpe mas",
    "o lead informou", "o lead disse", "o cliente informou", "o lead afirmou",
    "nao posso enviar", "nao posso gerar", "nao posso criar", "nao vou enviar",
    "nao e possivel enviar", "nao faz sentido enviar",
    "mensagem de follow-up", "mensagem de followup",
    "follow-up neste caso", "followup neste caso",
)


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _is_meta_comment(text: str) -> bool:
    """True se o texto tem cara de meta-comentário/recusa do LLM (não uma mensagem real).

    Filtro source-agnostic: pega qualquer recusa, independente do modelo/temperatura.
    Falso positivo é tolerável (no pior caso cancela um follow-up legítimo raro); um
    falso negativo vaza a recusa pro cliente — o erro grave que estamos blindando.
    """
    norm = _strip_accents((text or "")).lower()
    return any(marker in norm for marker in _META_COMMENT_MARKERS)


def _normalize_literal_newlines(text: str) -> str:
    r"""Converte sequências de quebra de linha LITERAIS (barra-invertida + 'n') em
    quebras de linha reais.

    O LLM às vezes devolve o texto cru ``\n`` — DOIS caracteres, a barra ``\`` e o ``n`` —
    em vez de uma quebra de linha de verdade, e o sistema persiste/envia isso tal e qual,
    fazendo o cliente LER ``\n`` na tela do WhatsApp. Aconteceu nos follow-ups do dia 2
    (auditoria leads 5511914799202 / 5519998390320 / 5511965704656, 2026-06-25:
    "...chegam frescos\n\nou se for pro seu negócio..."). Cobre ``\r\n``, ``\n`` e ``\r``.
    """
    if not text:
        return text
    return (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
    )


def _humanize_elapsed(now: datetime, last_ts: datetime) -> str:
    """Rótulo temporal calendário-consciente para ancorar o follow-up (anti-'outro dia').

    Usa a DATA local (America/Sao_Paulo via _FOLLOWUP_TZ_BR), não horas decorridas: um toque que
    dispara de manhã sobre uma mensagem da tarde anterior é 'ontem', não 'hoje, há ~20 horas'.
    """
    now_local = now.astimezone(_FOLLOWUP_TZ_BR)
    ts_local = last_ts.astimezone(_FOLLOWUP_TZ_BR)
    day_diff = (now_local.date() - ts_local.date()).days
    if day_diff <= 0:
        secs = max(0, int((now - last_ts).total_seconds()))
        if secs < 90 * 60:
            return "hoje mesmo, há pouco tempo"
        hours = secs // 3600
        return f"hoje, há ~{hours} hora{'s' if hours != 1 else ''}"
    if day_diff == 1:
        return "ontem"
    return f"há ~{day_diff} dias"


def _build_followup_system_prompt(
    sequence: int, objetivo: str | None = None, last_msg_age: str | None = None
) -> str:
    """System prompt do follow-up — usa o CARTÃO DE VOZ da Valéria (persona destilada).

    Garante que a mensagem de reengajamento siga as mesmas regras de voz das respostas
    normais da Valéria. FinOps 08/07: antes vinha a persona COMPLETA via build_base_prompt
    (~21K tokens de regras de funil/ferramenta irrelevantes numa chamada text-only de 1-2
    bolhas); o cartão de voz (app/agent/prompts/voice_card.py) carrega só identidade,
    voz/formato, blacklist, moderação de nome e grounding (~2K tokens, −90% de input).

    O TOM segue o OBJETIVO do toque, NÃO o número da sequência. Só o toque que é de fato o
    último da cadência (objetivo 'ultima_chamada') usa o tom de "última tentativa"; todos os
    demais usam o tom de reengajamento leve. Isto blinda o lead frio (warm=False): como ele
    pula o T1 e seu primeiro toque agendado é a sequence=2, keyar o tom em `sequence == 1`
    jogava esse primeiro contato no ramo de "última tentativa" — a cobrança prematura que o
    Erro 3 removeu. `sequence` é mantido por compatibilidade/observabilidade.

    `last_msg_age`: quando informado, injeta a âncora temporal (Erro 3 / parte 2) para que o
    LLM não invente intervalos como 'outro dia' quando o contato foi na mesma manhã.
    """
    is_last_attempt = objetivo == "ultima_chamada"
    seq_tone = (
        "esta é a última tentativa antes da janela de atendimento expirar: seja mais direta, "
        "crie senso de oportunidade, mas sem ser agressiva"
        if is_last_attempt
        else
        "esta é uma retomada de reengajamento: leve, curiosa e natural, sem pressionar — "
        "retome pelo assunto que ficou em aberto e demonstre interesse genuíno"
    )
    persona = VALERIA_VOICE_CARD
    temporal = (
        f"\nContexto temporal (GROUNDING): a última mensagem desta conversa foi enviada {last_msg_age}. "
        "Use exatamente essa referência — não invente outro intervalo."
        if last_msg_age else ""
    )
    return f"{persona}\n\n{_FOLLOWUP_REENGAGE_INSTRUCTION}\nTom desta tentativa: {seq_tone}{temporal}"


async def _generate_followup_message(
    history: list[dict],
    sequence: int,
    lead_id: str | None = None,
    stage: str | None = None,
    objective_prompt: str | None = None,
    objetivo: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str | None]:
    """Gera mensagem contextualizada via LLM para o follow-up, na voz da Valéria.

    Retorna `(texto, finish_reason)`. O `finish_reason` é vital: gemini-2.5-flash conta
    thinking + texto no mesmo budget, então mesmo com o thinking desligado um histórico
    longo pode estourar o teto — `finish_reason="MAX_TOKENS"` (nome nativo do Gemini)
    sinaliza corte e o chamador (process_due_followups) ABORTA o envio em vez de mandar
    mensagem pela metade.
    """
    messages_text = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Vendedor'}: {m['content']}"
        for m in history
    )

    # Âncora temporal (Erro 3): Δt da última mensagem do histórico, para o LLM não inventar 'outro dia'.
    last_msg_age = None
    if now is not None and history:
        last_created = history[-1].get("created_at")
        if last_created:
            try:
                ts = datetime.fromisoformat(str(last_created).replace("Z", "+00:00"))
                last_msg_age = _humanize_elapsed(now, ts)
            except Exception:
                last_msg_age = None

    system_prompt = _build_followup_system_prompt(sequence, objetivo=objetivo, last_msg_age=last_msg_age)
    if objective_prompt:
        system_prompt = f"{system_prompt}\n\nOBJETIVO DESTE TOQUE (Next Best Action): {objective_prompt}"

    result = await generate(
        _FOLLOWUP_MODEL,
        contents=[
            user_content(f"Histórico da conversa:\n{messages_text}\n\nEscreva o follow-up:"),
        ],
        system_instruction=system_prompt,
        max_output_tokens=_FOLLOWUP_MAX_TOKENS,
        temperature=0.8,
        # Desliga o thinking do Gemini 2.5 — sem isso o budget é gasto pensando e a saída corta.
        thinking_off=True,
    )

    # Observabilidade: o follow-up nunca rastreava custo (a tabela token_usage só via o
    # agente principal). Sem isto, cortes/anomalias do follow-up ficam invisíveis no banco.
    usage = result.usage_metadata
    if usage and lead_id:
        try:
            track_token_usage(
                lead_id=lead_id,
                stage=stage or "followup",
                model=_FOLLOWUP_MODEL,
                call_type="followup",
                prompt_tokens=usage.prompt_token_count,
                # thinking é COBRADO como saída → completion = candidates + thoughts
                completion_tokens=usage.billed_output_tokens,
                cached_tokens=usage.cached_content_token_count,
                reasoning_tokens=usage.thoughts_token_count,
            )
        except Exception as exc:
            logger.error("[FOLLOWUP] falha ao registrar token_usage: %s", exc)

    return (result.text or "").strip(), result.finish_reason


async def process_due_followups(now: datetime | None = None) -> None:
    """Processa jobs de follow-up vencidos. Chamado pelo worker a cada tick."""
    now = now or datetime.now(timezone.utc)
    # Crash-recovery: devolve p/ 'pending' jobs presos em 'processing' (worker morreu
    # após reivindicar, ou falha transitória sem estado terminal) ANTES de buscar os
    # devidos — assim eles reentram na fila deste tick. Espelha broadcast/worker.py.
    await asyncio.to_thread(_recover_stale_followup_jobs, now)
    jobs = await asyncio.to_thread(get_due_followups, now)

    for job in jobs:
        # Reivindicação atômica (anti-duplicidade multi-worker): só ESTE processo segue
        # com o job. Se outro worker já o pegou (claim perdido), pula sem processar —
        # evita template/mensagem duplicados caso o worker seja escalado para N réplicas.
        if not await asyncio.to_thread(_claim_followup_job, job["id"]):
            logger.info("[FOLLOWUP] job %s já reivindicado por outro worker — pulando", job["id"])
            continue

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

        if job.get("job_type") == "ai_scheduled_return":
            await _process_ai_scheduled_return(job, now)
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

        # REDE DE SEGURANÇA (backstop pós-catálogo): lead atacado/private_label que já viu
        # o catálogo e ainda não teve handoff real fica preso na cadência genérica de
        # follow-up indefinidamente — o próximo toque "seria" só mais uma mensagem
        # automática da Valéria quando o sinal real já indica entregar ao vendedor. Roda
        # ANTES do follow-up padrão (guards de janela/LLM abaixo) e nunca colide com o
        # cancelamento de jobs pendentes que o próprio handoff faz (cancel_followups_by_phone
        # dentro de encaminhar_humano só afeta jobs 'pending'; este job já está 'processing'
        # por _claim_followup_job, por isso cancelamos explicitamente no fim).
        # Fail-soft: qualquer erro aqui é logado e o ciclo segue para o follow-up padrão —
        # nunca derruba o tick por causa deste backstop.
        try:
            fresh_lead = _fetch_lead_for_backstop(job["lead_id"])
            if should_proactive_handoff(fresh_lead):
                await _fire_proactive_handoff(job, fresh_lead, phone=lead.get("phone", ""))
                continue
        except Exception as exc:
            logger.error(
                "[FOLLOWUP] falha na rede de segurança pos-catalogo (lead %s) — seguindo "
                "para o follow-up padrão: %s",
                job["lead_id"], exc, exc_info=True,
            )

        # Guard: janela de 24h POR CANAL — fonte é a conversa (lead+canal), não o
        # campo global do lead. A janela pode estar aberta em outro canal e expirada aqui.
        last_msg_str = conversation.get("last_customer_message_at")
        if not last_msg_str:
            _cancel_job(job["id"], "window_expired")
            logger.info(
                f"[FOLLOWUP] Sem last_customer_message_at — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
        window_closed = last_msg + timedelta(hours=24) <= now
        if window_closed:
            objetivo = (job.get("metadata") or {}).get("objetivo", "")
            objective_prompt = (job.get("metadata") or {}).get("objective_prompt", "")
            existing = _pending_reopen_job(conversation_id)
            if existing:
                # R1: não empilha template — escala o contexto do reopen vivo e encerra este toque.
                _store_reopen_context(existing["id"], objetivo, objective_prompt)
                _cancel_job(job["id"], "reopen_context_refreshed")
                logger.info(
                    "[FOLLOWUP] janela fechada + reopen vivo → contexto atualizado p/ '%s' "
                    "seq=%s conv=%s", objetivo, sequence, conversation_id,
                )
            else:
                await fire_reopen_template(
                    job, lead, channel, conversation_id, motivo=objetivo, contexto=objective_prompt
                )
            continue

        # Busca histórico e gera mensagem via LLM
        try:
            sb = get_supabase()
            history_result = (
                sb.table("messages")
                .select("role, content, created_at")
                .eq("conversation_id", conversation_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            history = list(reversed(history_result.data or []))
            history = [m for m in history if m.get("role") and m.get("content")]
            objective_prompt = (job.get("metadata") or {}).get("objective_prompt")
            objetivo = (job.get("metadata") or {}).get("objetivo")
            message, finish_reason = await _generate_followup_message(
                history, sequence, lead_id=job["lead_id"], stage=conversation.get("stage"),
                objective_prompt=objective_prompt, objetivo=objetivo, now=now,
            )
        except Exception as e:
            logger.error(f"[FOLLOWUP] Erro ao gerar mensagem seq={sequence} conversation={conversation_id}: {e}", exc_info=True)
            continue

        # C1: sanitiza newlines literais ANTES dos guardrails e do envio — o LLM às vezes
        # devolve "\n" cru (barra + n) e o cliente lê a barra na tela (auditoria 2026-06-25).
        message = _normalize_literal_newlines(message)

        if not message:
            _cancel_job(job["id"], "empty_response")
            logger.warning(
                f"[FOLLOWUP] LLM retornou vazio — cancelando seq={sequence} conversation={conversation_id}"
            )
            continue

        # GUARDRAIL COMPORTAMENTAL: o cliente pediu para ser contatado depois (viagem, "semana
        # que vem", "agora não dá"). O LLM detecta isso e devolve o sentinela; aqui abortamos
        # SILENCIOSAMENTE — insistir num lead que marcou retorno é a falha mais grave do fluxo
        # (auditoria lead 5566999975586: follow-up disparou ~1h42 após o cliente dizer "estou em
        # viagem essa semana, mas na próxima já estarei mais tranquilo").
        if _DEFERRAL_MARKER in message:
            _cancel_job(job["id"], "deferral_detected")
            logger.info(
                "[FOLLOWUP] adiamento explícito detectado — cancelando sem enviar "
                "seq=%s conversation=%s",
                sequence, conversation_id,
            )
            continue

        # GUARDRAIL TÉCNICO: corte por budget. gemini-2.5-flash pode estourar o teto mesmo com
        # o thinking off (histórico longo), devolvendo finish_reason="MAX_TOKENS" (nome nativo;
        # a fachada antiga traduzia p/ "length") com a frase pela metade. NUNCA enviar mensagem
        # truncada ao cliente (auditoria leads 5566999975586 / 5531996039118: "...o que te fez
        # pensar em"). Cancela; o próximo ciclo tenta de novo.
        if finish_reason == "MAX_TOKENS":
            _cancel_job(job["id"], "length_truncated")
            logger.warning(
                "[FOLLOWUP] resposta cortada (finish_reason=MAX_TOKENS) — cancelando sem enviar "
                "seq=%s conversation=%s: %r",
                sequence, conversation_id, message[-80:],
            )
            continue

        # GUARDRAIL: o LLM recusou e devolveu um meta-comentário em vez de mensagem
        # (ver _is_meta_comment). Aborta SILENCIOSAMENTE — nunca enviar a recusa ao cliente
        # (auditoria lead 5561984336980: o texto "Não é apropriado enviar..." foi entregue).
        if _is_meta_comment(message):
            _cancel_job(job["id"], "meta_comment")
            logger.warning(
                "[FOLLOWUP] LLM devolveu meta-comentário/recusa — cancelando sem enviar "
                "seq=%s conversation=%s: %r",
                sequence, conversation_id, message[:160],
            )
            continue

        # Envia via WhatsApp — destino entregável (wa_id real quando houver; evita 131026)
        send_to = resolve_send_target(lead, lead["phone"])
        try:
            provider = get_provider(channel)
            send_result = await provider.send_text(send_to, message)
        except Exception as e:
            logger.error(
                f"[FOLLOWUP] Falha ao enviar seq={sequence} lead={send_to}: {e}",
                exc_info=True,
            )
            # Intencional per spec: em caso de falha no envio, não atualiza status — job será retentado no próximo tick
            continue

        # Idempotência: grava o wamid no job ANTES de persistir/marcar sent. Se o worker
        # morrer daqui até o _mark_sent, a crash-recovery vê o wamid e conclui como 'sent'
        # em vez de reenviar (fecha a janela residual de envio duplicado multi-worker).
        _save_followup_wamid(job["id"], extract_wamid(send_result))

        # Persiste mensagem
        try:
            save_message_conv(
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


def _fetch_lead_for_backstop(lead_id: str) -> dict | None:
    """Relê o lead com `stage`/`metadata` para a decisão `should_proactive_handoff`.

    O select de `get_due_followups` (join `leads!inner(...)`) não traz `stage` nem
    `metadata` — só id/phone/name/last_customer_message_at/wa_id — então a decisão
    precisa reler o lead à parte, mesmo padrão de `_process_ai_reengage`/
    `_process_ai_scheduled_return`. Fail-soft: erro de DB → None (`should_proactive_handoff`
    trata `None` como não-elegível, então o lead segue para o follow-up padrão).
    """
    try:
        sb = get_supabase()
        res = (
            sb.table("leads")
            .select("id, phone, stage, metadata")
            .eq("id", lead_id)
            .single()
            .execute()
        )
        return res.data
    except Exception as exc:
        logger.warning(
            "[FOLLOWUP] falha ao reler lead %s p/ backstop pos-catalogo: %s", lead_id, exc
        )
        return None


async def _fire_proactive_handoff(job: dict, lead: dict, phone: str) -> None:
    """Dispara o handoff proativo (via `execute_tool("encaminhar_humano", ...)`) para um
    lead qualificado/inativo pós-catálogo, e encerra ESTE job de follow-up.

    `execute_tool` é importado tardiamente (mesmo motivo do `run_agent` lazy: evita o
    ciclo de import scheduler → orchestrator → tools → scheduler). `encaminhar_humano`
    já cancela os jobs 'pending' do lead (cancel_followups_by_phone) e envia a mensagem
    de despedida + cartão de contato — aqui só fechamos o job ATUAL, que já está
    'processing' (reivindicado por `_claim_followup_job` antes deste ponto) e por isso
    não é alcançado por aquele cancelamento (que só mira jobs 'pending').
    """
    from app.agent.tools import execute_tool

    lead_id = job["lead_id"]
    conversation_id = job["conversation_id"]
    logger.info(
        "[FOLLOWUP] handoff proativo pos-catalogo — lead=%s stage=%s conv=%s",
        lead_id, lead.get("stage"), conversation_id,
    )
    await execute_tool(
        "encaminhar_humano",
        {
            "vendedor": "João Brás",
            "motivo": "handoff proativo — qualificado inativo pos-catalogo",
        },
        lead_id=lead_id,
        phone=phone or lead.get("phone", ""),
        conversation_id=conversation_id,
    )
    _cancel_job(job["id"], "proactive_handoff_pos_catalogo")


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
    # Destino entregável: wa_id real do lead quando houver; senão o lead_phone do metadata.
    send_to = resolve_send_target(job.get("leads"), lead_phone)

    try:
        provider = MetaCloudClient(joao_channel["provider_config"])
        send_result = await provider.send_template(send_to, template_name, components=components, language_code=language_code)
        logger.info(f"[HANDOFF_RESCUE] Template '{template_name}' ({language_code}) enviado para {send_to}")
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
    except RuntimeError as exc:
        # MetaCloudClient.send_template levanta RuntimeError quando a Meta responde HTTP 200
        # COM erro embutido (ex.: parâmetro inválido) — rejeição PERMANENTE. Sem cancelar
        # aqui, o job ficava pending e era re-tentado a cada tick para sempre (o
        # "manual_audit_cancel_loop_infinito"). Espelha o ramo já existente em
        # _process_lp_welcome / fire_reopen_template.
        _cancel_job(job["id"], "meta_rejected")
        logger.error(
            f"[HANDOFF_RESCUE] Rejeição permanente Meta para {lead_phone} — job cancelado: {exc}"
        )
        return
    except Exception as exc:
        logger.error(
            f"[HANDOFF_RESCUE] Falha ao enviar template para {lead_phone}: {exc}",
            exc_info=True,
        )
        return  # erro transitório → retry no próximo tick

    # Idempotência: persiste o wamid no job antes de marcar sent (ver _save_followup_wamid).
    _save_followup_wamid(job["id"], extract_wamid(send_result))

    # Persiste a mensagem do template na conversa do canal do João (senão o histórico
    # mostra só a resposta do lead — "como se ele tivesse iniciado do nada").
    _persist_joao_handoff_message(job["lead_id"], joao_channel["id"], lead_name, send_result)

    _mark_sent(job["id"])


def _resolve_lp_pipeline(origem: str) -> tuple[str | None, str | None]:
    """Mapeia a origem da LP → (pipeline_name, stage_label) do CRM.

    `origem` é o slug salvo em leads.metadata.origem ('terceirizacao' / 'atacado'),
    mas o casamento é por substring para também aceitar a URL completa
    (.../terceirizacaocafe, .../cafeatacado). Verificado em `pipelines` (prod):
    'Valeria - Private Label' e 'Valeria - Atacado' têm 'Entrada' como 1ª etapa.

    Origem desconhecida → (None, None): create_deal usa o pipeline padrão (fallback).
    Em ambientes sem esses pipelines (homolog) o fallback também atua.
    """
    o = (origem or "").strip().lower()
    if "terceiriza" in o:        # 'terceirizacao' ou .../terceirizacaocafe
        return "Valeria - Private Label", "Entrada"
    if "atacado" in o:           # 'atacado' ou .../cafeatacado
        return "Valeria - Atacado", "Entrada"
    return None, None


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
    conversation = job["conversations"]

    if not lead_phone or not template_name:
        _cancel_job(job["id"], "missing_metadata")
        logger.error(
            "[LP_WELCOME] Job %s sem lead_phone ou template_name no metadata", job["id"]
        )
        return

    # Guard POR CANAL: só dispara se o lead ainda não respondeu NESTE canal.
    # A janela é independente por canal — usa a conversa (lead+canal), não o lead global.
    if conversation.get("last_customer_message_at"):
        _cancel_job(job["id"], "lead_already_replied")
        logger.info(
            "[LP_WELCOME] Lead já enviou mensagem (last_customer_message_at=%s) — cancelando job %s",
            conversation["last_customer_message_at"],
            job["id"],
        )
        return

    lead_name = metadata.get("lead_name") or (job.get("leads") or {}).get("name") or ""
    # Task C-4: strip_greeting_prefix antes de usar como nome — sem isso, um lead gravado
    # como "Olá, boa tarde" (widget de chat de LP) virava o nome "Olá," e o disparo saudava
    # "olá Olá,". Cai no fallback _NAME_FALLBACK quando não sobra nome real.
    stripped_lp_name = strip_greeting_prefix(lead_name)
    first_name = stripped_lp_name.split()[0] if stripped_lp_name else _NAME_FALLBACK
    # Os templates lp_* aprovados (lp_solicitacao_recebida, lp_confirmacao_pendente,
    # lp_cadastro_registrado) usam o param NOMEADO {{primeiro_nome}}, OBRIGATÓRIO. Enviar
    # posicional faz a Meta rejeitar (causa do loop infinito de 02/06). Espelha o padrão de
    # _build_joao_handoff_components. Verificar em message_templates antes de mudar o template.
    # O param é SEMPRE enviado (nunca omitido) — first_name carrega o fallback neutro
    # (_NAME_FALLBACK) quando não há nome real, evitando tanto texto vazio quanto o
    # parâmetro nomeado ausente: o template exige o param e degradar para components=None
    # manda 0 params → Meta rejeita com #132000 "localizable_params (0) != expected (1)"
    # (caso 5541999736060, 03/07 — conversa importada ficava em branco no CRM).
    components = [{
        "type": "body",
        "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": first_name}],
    }]
    # Destino entregável: wa_id real quando houver (LP lead normalmente não tem → usa lead_phone).
    send_to = resolve_send_target(job.get("leads"), lead_phone)

    try:
        provider = MetaCloudClient(channel["provider_config"])
        send_result = await provider.send_template(send_to, template_name, components=components, language_code=language_code)
        logger.info("[LP_WELCOME] Template '%s' enviado para %s", template_name, send_to)
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
    except RuntimeError as exc:
        # MetaCloudClient.send_template levanta RuntimeError quando a Meta responde
        # HTTP 200 COM erro embutido (ex.: parâmetro inválido) — rejeição PERMANENTE.
        # Sem cancelar aqui, o job ficava pending e era re-tentado a cada tick para
        # sempre (o "manual_audit_cancel_loop_infinito" de 02/06). Cancela explicitamente.
        _cancel_job(job["id"], "meta_rejected")
        logger.error(
            "[LP_WELCOME] Rejeição permanente Meta para %s — job cancelado: %s", lead_phone, exc
        )
        return
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Falha ao enviar template para %s: %s", lead_phone, exc, exc_info=True
        )
        return  # erro transitório (rede etc.) → retry no próximo tick

    # Idempotência: persiste o wamid no job antes de marcar sent (ver _save_followup_wamid).
    _save_followup_wamid(job["id"], extract_wamid(send_result))

    # Persiste o disparo LP em `messages` para que reações/replies a ele sejam rastreáveis.
    # Sem isso, o template (wamid outbound) ficava fora da tabela e qualquer reação do lead
    # virava "mensagem fantasma" no CRM (auditoria 2026-06-22, lead 5531985712321).
    # Eixo 2a: NÃO grava o placeholder cru "[disparo automático — template X]" (vazava no CRM
    # e envenenava o campaign_message do LLM). Grava um corpo limpo e legível e carimba a
    # intenção em metadata.dispatch (warm_lp) p/ a resolução de persona (Eixo 1).
    try:
        # first_name já carrega o fallback _NAME_FALLBACK quando não há nome real —
        # persistência coerente com o que foi de fato enviado no template (mesmo
        # princípio de _render_joao_handoff_text).
        _lp_body = (
            f"olá {first_name}\n\nrecebemos sua solicitação pela nossa landing page e já "
            "estamos por aqui pra te atender"
        )
        save_message_conv(
            lead_id=lead["id"],
            role="assistant",
            content=_lp_body,
            sent_by="broadcast",
            conversation_id=conversation["id"],
            wamid=extract_wamid(send_result),
            metadata=dispatch_metadata(template_name),
        )
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Falha ao persistir mensagem do disparo LP para %s: %s", lead_phone, exc, exc_info=True
        )

    # Card de CRM nasce AQUI: somente quando o disparo outbound da LP realmente acontece
    # (lead não respondeu nos 15 min). Se o lead tivesse chamado a Valéria, o guard
    # `lead_already_replied` acima já teria abortado e o card nasceria mais tarde pelo
    # fluxo de qualificação (encaminhar_humano). Não há card antes deste ponto.
    lead_id = job["lead_id"]
    origem = (metadata.get("origem") or "").strip()
    deal_title = f"Landing Page - {origem}" if origem else "Landing Page"
    pipeline_name, stage_label = _resolve_lp_pipeline(origem)

    # Fail-soft: o template já foi entregue à Meta — uma falha de CRM não pode derrubar
    # nem reverter o disparo. Roteia por origem (terceirizacao→Private Label,
    # atacado→Atacado), stage 'Entrada'. Origem desconhecida/ambiente sem o pipeline →
    # create_deal cai no pipeline padrão. dedupe_open evita duplicar card já existente.
    try:
        create_deal(
            lead_id,
            title=deal_title,
            category=None,
            pipeline_name=pipeline_name,
            stage_label=stage_label,
            dedupe_open=True,
        )
    except Exception as exc:
        logger.error(
            "[LP_WELCOME] Falha ao criar deal para lead %s: %s", lead_id, exc, exc_info=True
        )

    # OBS padronizada de disparo no card recém-criado. `lead_notes` é keyed por lead_id,
    # então a observação aparece na timeline do card. record_dispatch_note é fail-soft.
    record_dispatch_note(lead_id, template_name)

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
            .select("id, phone, name, ai_enabled, last_customer_message_at, metadata, wa_id")
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
    # Destino entregável (wa_id real quando houver; evita 131026).
    send_to = resolve_send_target(lead, phone)

    # Guard: janela de 24h POR CANAL (mesma regra do follow-up standard) — fonte é a
    # conversa (lead+canal), não o campo global do lead. Janela é independente por canal.
    last_msg_str = conversation.get("last_customer_message_at")
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
            send_result = await provider.send_text(send_to, bubble)
            sent_wamids.append(extract_wamid(send_result))
        except Exception as exc:
            logger.error("[AI_REENGAGE] falha ao enviar bubble conv=%s: %s", conversation_id, exc, exc_info=True)
            return  # não marca sent → retry no próximo tick

    for bubble, bubble_wamid in zip(bubbles, sent_wamids):
        try:
            save_message_conv(
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


async def _process_ai_scheduled_return(job: dict, now: datetime) -> None:
    """Retorno autônomo agendado pela tool `agendar_retorno` (job_type='ai_scheduled_return').

    No `fire_at`, a Valéria reabre a conversa PROATIVAMENTE com base no motivo/contexto que ela
    própria salvou (ex.: lead disse "falo sexta"). Diferente do ai_reengage (que responde a uma
    mensagem órfã do lead), aqui montamos um gatilho interno a partir do metadata.

    - Janela 24h ABERTA → roda o agente real (run_agent, persona outbound) e envia as bolhas.
    - Janela 24h FECHADA → cancela ('window_expired'): free-text seria rejeitado pela Meta
      (#131047). Reabertura por template aprovado é um seam futuro (metadata.template_name).

    Guards (qualquer um falha → não envia): canal humano; lead.ai_enabled=False.
    """
    from app.agent.orchestrator import run_agent

    channel = job["channels"]
    conversation = job["conversations"]
    conversation_id = job["conversation_id"]
    metadata = job.get("metadata") or {}

    # Guard: canal humano nunca roda IA
    if channel.get("mode", "ai") == "human":
        _cancel_job(job["id"], "human_channel")
        logger.info("[AI_SCHEDULED_RETURN] mode=human — cancelando conv=%s", conversation_id)
        return

    sb = get_supabase()
    try:
        lead_row = (
            sb.table("leads")
            .select("id, phone, name, ai_enabled, last_customer_message_at, metadata, wa_id")
            .eq("id", job["lead_id"])
            .single()
            .execute()
        )
        lead = lead_row.data
    except Exception as exc:
        logger.error(
            "[AI_SCHEDULED_RETURN] falha ao reler lead %s: %s", job["lead_id"], exc, exc_info=True
        )
        return  # transitório → retry no próximo tick

    if not lead or not lead.get("ai_enabled", False):
        _cancel_job(job["id"], "ai_disabled")
        logger.info("[AI_SCHEDULED_RETURN] ai_enabled=false — cancelando conv=%s", conversation_id)
        return

    phone = lead["phone"]
    send_to = resolve_send_target(lead, phone)

    # Janela 24h POR CANAL (fonte: conversa). Fechada → free-text rejeitado pela Meta.
    last_msg_str = conversation.get("last_customer_message_at")
    window_open = False
    if last_msg_str:
        last_msg = datetime.fromisoformat(last_msg_str.replace("Z", "+00:00"))
        window_open = last_msg + timedelta(hours=24) > now
    if not window_open:
        motivo = (metadata.get("motivo") or "").strip()
        contexto = (metadata.get("contexto") or "").strip()
        await fire_reopen_template(job, lead, channel, conversation_id, motivo=motivo, contexto=contexto)
        return

    motivo = (metadata.get("motivo") or "").strip() or "retomar o contato combinado"
    contexto = (metadata.get("contexto") or "").strip()
    trigger = (
        "[GATILHO INTERNO — RETORNO AGENDADO] Você combinou de retomar o contato com este "
        f"lead agora. Combinado/motivo: {motivo}."
        + (f" Contexto: {contexto}." if contexto else "")
        + " Reabra a conversa de forma natural, curta e pessoal, retomando esse ponto. "
        "NÃO diga que é um lembrete automático nem mencione que houve um agendamento."
    )

    conversation["leads"] = lead
    lead_context = lead.get("metadata") or {}
    try:
        response = await run_agent(
            conversation, trigger,
            lead_context=lead_context,
            agent_profile_id=AI_REENGAGE_PROFILE_ID,
            # Gatilho INTERNO (sem mensagem real do lead): se o modelo ficar mudo, NÃO mandar o
            # fallback estático de último recurso (_SAFETY_FALLBACK_GENERIC ou o reengajamento
            # por stage — orchestrator.py) — seria incoerente numa reabertura proativa. ""
            # → o job é cancelado pelo guard abaixo (empty_response).
            suppress_generic_fallback=True,
        )
    except Exception as exc:
        logger.error(
            "[AI_SCHEDULED_RETURN] run_agent falhou conv=%s: %s", conversation_id, exc, exc_info=True
        )
        return  # transitório → retry

    if response is None:
        # encaminhar_humano foi chamado pela tool — mensagem de handoff já enviada.
        logger.info("[AI_SCHEDULED_RETURN] handoff via tool conv=%s — nada a enviar", conversation_id)
        _mark_sent(job["id"])
        return
    if not response.strip():
        _cancel_job(job["id"], "empty_response")
        logger.warning("[AI_SCHEDULED_RETURN] resposta vazia — cancelando conv=%s", conversation_id)
        return

    provider = get_provider(channel)
    bubbles = split_into_bubbles(response)
    sent_wamids: list[str | None] = []
    for bubble in bubbles:
        try:
            send_result = await provider.send_text(send_to, bubble)
            sent_wamids.append(extract_wamid(send_result))
        except Exception as exc:
            logger.error(
                "[AI_SCHEDULED_RETURN] falha ao enviar bubble conv=%s: %s",
                conversation_id, exc, exc_info=True,
            )
            return  # não marca sent → retry no próximo tick

    for bubble, bubble_wamid in zip(bubbles, sent_wamids):
        try:
            save_message_conv(
                lead_id=job["lead_id"],
                role="assistant",
                content=bubble,
                stage=conversation.get("stage"),
                sent_by="agent",
                conversation_id=conversation_id,
                wamid=bubble_wamid,
                agent_persona="valeria_outbound",
            )
        except Exception as exc:
            logger.error("[AI_SCHEDULED_RETURN] falha ao salvar bubble conv=%s: %s", conversation_id, exc)

    _mark_sent(job["id"])
    logger.info("[AI_SCHEDULED_RETURN] Valéria retornou lead=%s conv=%s", phone, conversation_id)


def _cancel_job(job_id: str, reason: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "cancelled",
        "cancel_reason": reason,
    }).eq("id", job_id).execute()


def _claim_followup_job(job_id: str) -> bool:
    """Reivindicação atômica de um follow-up job: pending→processing guardado por status.

    Retorna True apenas se ESTE processo venceu a corrida (o UPDATE guardado por
    `.eq("status","pending")` só afeta a linha se ela ainda estiver pendente; sob N
    workers, somente um obtém a linha). Blinda contra envio duplicado quando o worker de
    follow-up for escalado para múltiplas réplicas no Swarm — espelha o claim atômico de
    broadcast_leads (broadcast/worker.py). Fail-open: erro na query → False (não processa,
    o próximo tick tenta de novo) para nunca arriscar um envio não-serializado."""
    try:
        sb = get_supabase()
        res = (
            sb.table("follow_up_jobs")
            .update({"status": "processing", "claimed_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", job_id)
            .eq("status", "pending")
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.warning("[FOLLOWUP] falha ao reivindicar job %s: %s", job_id, exc)
        return False


def _save_followup_wamid(job_id: str, wamid: str | None) -> None:
    """Persiste o wamid do envio no job ANTES de marcá-lo terminal (espelha
    save_broadcast_lead_wamid). É a chave de idempotência: se o worker morrer entre o
    envio à Meta e o _mark_sent, a crash-recovery vê o wamid e conclui o job como 'sent'
    (mensagem já despachada) em vez de reenviar cegamente. No-op se wamid vazio (provider
    sem id → não há o que deduplicar). Fail-soft: nunca derruba o turno."""
    if not wamid:
        return
    try:
        sb = get_supabase()
        sb.table("follow_up_jobs").update({"wamid": wamid}).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("[FOLLOWUP] falha ao persistir wamid do job %s: %s", job_id, exc)


def _recover_stale_followup_jobs(now: datetime, *, stale_minutes: int = 5) -> int:
    """Crash-recovery ciente de idempotência: dois ramos, espelhando broadcast_leads.

    Jobs presos em 'processing' há mais de `stale_minutes` (worker morreu após reivindicar
    ou falha transitória sem estado terminal) são resolvidos pelo wamid:

    - COM wamid → a mensagem JÁ foi despachada à Meta antes do crash: conclui o job como
      'sent' (idempotência) em vez de reenviar. Fecha a janela residual de envio duplicado.
    - SEM wamid → nunca chegou a enviar: devolve p/ 'pending' para o próximo tick retentar.

    Escopado ao env atual. Fail-soft: erro → 0 (o watchdog Check 3 ainda observa presos).
    Retorna o total de jobs recuperados (ambos os ramos)."""
    try:
        sb = get_supabase()
        cutoff = (now - timedelta(minutes=stale_minutes)).isoformat()
        # Ramo idempotente: wamid presente → já despachado → 'sent' (NÃO reenvia).
        sent_res = (
            sb.table("follow_up_jobs")
            .update({"status": "sent", "sent_at": now.isoformat()})
            .eq("status", "processing")
            .eq("env_tag", _ENV_TAG)
            .lt("claimed_at", cutoff)
            .filter("wamid", "not.is", "null")
            .execute()
        )
        # Ramo de retry: wamid nulo → nunca enviou → devolve p/ 'pending'.
        requeue_res = (
            sb.table("follow_up_jobs")
            .update({"status": "pending", "claimed_at": None})
            .eq("status", "processing")
            .eq("env_tag", _ENV_TAG)
            .lt("claimed_at", cutoff)
            .filter("wamid", "is", "null")
            .execute()
        )
        n_sent = len(sent_res.data or [])
        n_requeue = len(requeue_res.data or [])
        if n_sent or n_requeue:
            logger.warning(
                "[FOLLOWUP] crash-recovery: %d concluído(s) como 'sent' (wamid presente, "
                "sem reenvio), %d requeue p/ 'pending' (sem envio) — env=%s",
                n_sent, n_requeue, _ENV_TAG,
            )
        return n_sent + n_requeue
    except Exception as exc:
        logger.warning("[FOLLOWUP] falha na crash-recovery de jobs 'processing': %s", exc)
        return 0


def _mark_sent(job_id: str) -> None:
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "sent",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()


def _mark_awaiting_reopen(job_id: str) -> None:
    """Eixo 3B: janela fechada → disparamos o template de reabertura e aguardamos o lead
    responder. sent_at marca o instante do disparo (base do TTL de retomada)."""
    sb = get_supabase()
    sb.table("follow_up_jobs").update({
        "status": "awaiting_reopen",
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", job_id).execute()


def _store_reopen_context(job_id: str, motivo: str, contexto: str) -> None:
    """Grava motivo/contexto no metadata do job (origem do <retorno_agendado> na retomada)."""
    sb = get_supabase()
    try:
        cur = sb.table("follow_up_jobs").select("metadata").eq("id", job_id).limit(1).execute()
        md = (cur.data[0].get("metadata") if cur.data else None) or {}
        md = {**md, "motivo": motivo, "contexto": contexto}
        sb.table("follow_up_jobs").update({"metadata": md}).eq("id", job_id).execute()
    except Exception as exc:
        logger.warning("[REOPEN] falha ao gravar contexto no job %s: %s", job_id, exc)


def _pending_reopen_job(conversation_id: str) -> dict | None:
    """Job awaiting_reopen vivo desta conversa (R1), ou None. Fail-open: None em erro."""
    try:
        res = (
            get_supabase().table("follow_up_jobs")
            .select("id, metadata")
            .eq("conversation_id", conversation_id)
            .eq("status", "awaiting_reopen")
            .order("fire_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.warning("[FOLLOWUP] falha ao buscar awaiting_reopen conv=%s: %s", conversation_id, exc)
        return None


# Cópia fiel do BODY aprovado do template de reabertura — usada como fallback de
# PERSISTÊNCIA quando message_templates está indisponível. Persistido == enviado
# (QA 10/07, Rodada 4): gravar placeholder interno como fala da Valéria poluía o
# CRM e o histórico que o LLM relê nos turnos seguintes.
_REOPEN_TEMPLATE_BODY_FALLBACK = (
    "Ola, {{1}}! O Cafe Canastra esta aguardando sua confirmacao sobre {{2}} "
    "desde {{3}}. Responda essa mensagem para finalizarmos seu atendimento."
)


def _reopen_body_params(lead: dict, job: dict | None = None) -> list[str]:
    """Os 3 params posicionais do template de reabertura: [nome, assunto, data].

    Nome: sanitizado (saudação/handle/apelido de pushname viram fallback neutro).
    Assunto: constante honesta (_REOPEN_TOPIC). Data: última mensagem do lead
    (dd/mm/YYYY, BRT) — fallback `now` quando o embed da conversa não está no job.
    """
    clean = sanitize_display_name((lead or {}).get("name"))
    first_name = clean.split()[0] if clean else _NAME_FALLBACK

    last_ts = ((job or {}).get("conversations") or {}).get("last_customer_message_at")
    ref = None
    if last_ts:
        try:
            ref = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
        except Exception:
            ref = None
    if ref is None:
        ref = datetime.now(timezone.utc)
    date_str = ref.astimezone(_FOLLOWUP_TZ_BR).strftime("%d/%m/%Y")

    return [first_name, _REOPEN_TOPIC, date_str]


def _build_reopen_components(params: list[str]) -> list[dict]:
    """Componentes BODY (params POSICIONAIS) do template de reabertura."""
    return [{
        "type": "body",
        "parameters": [{"type": "text", "text": p} for p in params],
    }]


def _reopen_template_body(params: list[str]) -> str:
    """BODY real do template de reabertura RENDERIZADO com os params enviados.

    Busca o texto em message_templates (fallback: cópia fiel do corpo aprovado) e
    substitui {{1}}..{{n}} pelos mesmos valores enviados à Meta — persistido ==
    enviado, nunca um placeholder interno.
    """
    text = _REOPEN_TEMPLATE_BODY_FALLBACK
    try:
        res = (
            get_supabase()
            .table("message_templates")
            .select("components")
            .eq("name", _REOPEN_TEMPLATE_NAME)
            .limit(1)
            .execute()
        )
        if res.data:
            body = next(
                (c for c in (res.data[0].get("components") or []) if c.get("type") == "BODY"),
                None,
            )
            if body and body.get("text"):
                text = body["text"]
    except Exception as exc:
        logger.warning(
            "[REOPEN] falha ao buscar corpo do template %s: %s — usando cópia fiel",
            _REOPEN_TEMPLATE_NAME, exc,
        )
    for i, value in enumerate(params, start=1):
        text = text.replace("{{" + str(i) + "}}", value)
    return text


def _reopen_template_category() -> str | None:
    """Categoria (lowercase) do template de reabertura em message_templates, ou None.

    None = não foi possível determinar (linha ausente / erro de DB) → o chamador faz
    fail-open (o template hardcoded _REOPEN_TEMPLATE_NAME é, por construção, UTILITY).
    """
    try:
        res = (
            get_supabase()
            .table("message_templates")
            .select("category")
            .eq("name", _REOPEN_TEMPLATE_NAME)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("category"):
            return str(res.data[0]["category"]).strip().lower()
    except Exception as exc:
        logger.warning("[REOPEN] falha ao verificar categoria do template %s: %s", _REOPEN_TEMPLATE_NAME, exc)
    return None


async def fire_reopen_template(
    job: dict, lead: dict, channel: dict, conversation_id: str, *, motivo: str = "", contexto: str = "",
) -> bool:
    """Janela fechada → dispara o template aprovado de reabertura e marca awaiting_reopen.

    Helper compartilhado por _process_ai_scheduled_return e pelo follow-up multi-touch.
    Retorna True quando o template foi disparado e o job ficou awaiting_reopen; False em erro
    (4xx/rejeição → cancela o job; transitório → não cancela, retry no próximo tick).

    COMPLIANCE (Meta): o template de reabertura DEVE ser da categoria UTILITY — nunca
    Marketing. Se a categoria conhecida não for utility, NÃO envia: cancela o job
    (config error permanente) e levanta um system_alert. Fail-open quando a categoria
    não pode ser determinada (linha ausente), pois o template padrão é utility por construção.
    """
    category = _reopen_template_category()
    if category is not None and category != "utility":
        _cancel_job(job["id"], "reopen_template_not_utility")
        logger.error(
            "[REOPEN] BLOQUEIO DE COMPLIANCE: template '%s' é categoria '%s' (esperado 'utility') "
            "— reabertura abortada conv=%s", _REOPEN_TEMPLATE_NAME, category, conversation_id,
        )
        try:
            create_system_alert(
                "reopen_template_not_utility",
                f"Template de reabertura '{_REOPEN_TEMPLATE_NAME}' não é UTILITY",
                f"Categoria atual: {category}. O follow-up multi-touch só pode reabrir janela com "
                "template de UTILIDADE. Ajuste a categoria do template na Meta.",
                severity="critical",
                metadata={"template": _REOPEN_TEMPLATE_NAME, "category": category},
            )
        except Exception as exc:
            logger.error("[REOPEN] falha ao criar system_alert de compliance: %s", exc)
        return False

    send_to = resolve_send_target(lead, lead.get("phone", ""))
    # Rodada 5: utilidade_geral_confirmacao_v1 exige EXATAMENTE 3 params POSICIONAIS e o
    # language_code da APROVAÇÃO (en_US — corpo em português). Contagem ou locale
    # divergente do aprovado = rejeição da Meta (#132000/404) — a mesma classe de
    # armadilha que derrubou o reopen antigo em 08/07 (lead cintia, 554599367983) e os
    # templates lp_* (param nomeado).
    reopen_params = _reopen_body_params(lead, job)
    try:
        provider_meta = MetaCloudClient(channel["provider_config"])
        send_result = await provider_meta.send_template(
            send_to,
            _REOPEN_TEMPLATE_NAME,
            components=_build_reopen_components(reopen_params),
            language_code=_REOPEN_TEMPLATE_LANGUAGE,
        )
    except httpx.HTTPStatusError as http_exc:
        status = http_exc.response.status_code
        if 400 <= status < 500:
            _cancel_job(job["id"], f"reopen_template_error_{status}")
            logger.error("[REOPEN] erro permanente Meta %s conv=%s", status, conversation_id)
        else:
            logger.error("[REOPEN] erro transitório Meta %s conv=%s — retry", status, conversation_id)
        return False
    except RuntimeError as exc:
        _cancel_job(job["id"], "reopen_template_rejected")
        logger.error("[REOPEN] rejeição permanente conv=%s: %s", conversation_id, exc)
        return False
    except Exception as exc:
        logger.error("[REOPEN] falha ao enviar template conv=%s: %s", conversation_id, exc, exc_info=True)
        return False

    try:
        save_message_conv(
            lead_id=job["lead_id"],
            role="assistant",
            content=_reopen_template_body(reopen_params),
            sent_by="followup",
            conversation_id=conversation_id,
            wamid=extract_wamid(send_result),
            metadata=dispatch_metadata(_REOPEN_TEMPLATE_NAME),
        )
    except Exception as exc:
        logger.error("[REOPEN] falha ao persistir disparo conv=%s: %s", conversation_id, exc)

    _store_reopen_context(job["id"], motivo, contexto)
    _mark_awaiting_reopen(job["id"])
    logger.info("[REOPEN] template '%s' disparado, awaiting_reopen conv=%s", _REOPEN_TEMPLATE_NAME, conversation_id)
    return True
