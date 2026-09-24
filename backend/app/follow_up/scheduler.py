# backend/app/follow_up/scheduler.py
import asyncio
import logging
import unicodedata
from datetime import datetime, timezone, timedelta

import httpx

from app.agent.gemini_client import generate, user_content
from app.config import settings
from app.follow_up.service import (
    get_due_followups,
    lead_marked_wrong_number,
    should_proactive_handoff,
    _ENV_TAG,
)
# Import de topo, sem risco de ciclo: `cadence_joao` é config-as-code pura (zero I/O,
# nenhum import de `app.*` no topo). É a autoridade sobre qual ETAPA cada cadência vigia
# — o que o job de mover precisa saber para não desfazer um move manual do João.
from app.follow_up.cadence_joao import cadencia_do_funil
from app.leads.service import (
    resolve_send_target, create_deal, record_dispatch_note,
    strip_greeting_prefix, sanitize_display_name, is_lead_blacklisted,
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

# ─────────────────────────────────────────────────────────────────────────────
# MOTOR DE FOLLOW-UP DO JOÃO — spec 2026-09-18, §3
#
# As cadências do vendedor NÃO são um segundo motor: são novos `job_type` no mesmo
# `follow_up_jobs`, despachados por `process_due_followups` para um handler autocontido
# (`_process_joao_touch`), exatamente como `lp_welcome`/`handoff_rescue`/`ai_reengage`.
#
# A diferença de fundo com o caminho da ValerIA: ela gera o texto por LLM porque a janela
# de 24h está ABERTA. O lead do João está em silêncio POR DEFINIÇÃO (é o que o gatilho
# mede) — janela fechada — então só TEMPLATE APROVADO sai. Nenhuma linha deste ramo chama
# o LLM: free-text com a janela fechada seria rejeitado pela Meta (#131047).
#
# O despacho aceita qualquer tipo com o prefixo `joao_` justamente porque a FORMA da
# cadência (um tipo só, ou um por cadência) é definida em `follow_up/cadence_joao.py` e
# pelo agendador — este handler não pode depender de qual das duas eles escolherem.
# ─────────────────────────────────────────────────────────────────────────────
JOAO_JOB_TYPE = "joao_touch"
JOAO_JOB_TYPE_PREFIX = "joao_"
# Os tipos nomeados (um por cadência da ata) — redundantes com o prefixo, e declarados
# para que o contrato apareça por extenso em log/teste/leitura.
JOAO_JOB_TYPES: frozenset[str] = frozenset({
    JOAO_JOB_TYPE, "joao_novo", "joao_em_conversa", "joao_proposta", "joao_reposicao",
    "joao_em_atencao",
})

# A MARCA do job que MOVE o card em vez de mandar mensagem (spec 2026-09-23 §3), gravada
# pelo agendador em `metadata.acao`. É a ÚNICA condição do ramo: inferir "é move" pelo
# template nulo moveria o card no lugar de tocar o lead em TODOS os 22 toques das três
# cadências de prospecção, que hoje nascem sem template de propósito (cadence_joao,
# decisão 4).
ACAO_MOVER_ETAPA = "mover_etapa"

# Os 24 templates das esteiras do João foram APROVADOS em pt_BR com UM param POSICIONAL
# ({{1}} = primeiro nome) — ver scripts/create_templates_esteiras_joao.py. O default abaixo
# é o mesmo mapeamento que o modal de disparo grava em `broadcasts.template_variables`,
# para que `_build_template_components` (reusado de broadcast/worker.py) resolva o nome do
# lead pelo MESMO caminho do disparo manual. Job que precise de outra forma manda
# `metadata.template_variables`.
JOAO_TOUCH_TEMPLATE_LANGUAGE = "pt_BR"
JOAO_TOUCH_TEMPLATE_VARIABLES: dict = {"__params_type__": "positional", "1": "{{primeiro_nome}}"}

# Funis do João em produção (medidos na reunião de 10/09/2026). O FUNIL decide o TEXTO
# do toque: mandar o texto de Atacado a um lead de Private Label é o pior erro possível
# desta cadência, e o funil é a única fonte confiável dessa distinção.
PIPELINE_JOAO_ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PIPELINE_JOAO_PRIVATE_LABEL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"
PIPELINE_JOAO_REPOSICAO_ATACADO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"
PIPELINE_JOAO_REPOSICAO_PRIVATE_LABEL = "9c027143-72f6-42d6-861f-a494ba5bbb4f"

# 1:1, sem colisão — spec 2026-09-21 §1/§6: o dicionário antigo (`_LINHA_POR_PIPELINE`)
# mapeava o Atacado normal E a Reposição Atacado para a MESMA string "atacado" (e o
# mesmo valia para Private Label x Reposição Private Label). Era um bug de identidade
# latente no fallback por pipeline_id de `_resolve_joao_funil`: um job de Reposição sem
# `metadata.funil` explícito resolvia para o funil normal, não o de Reposição. Os
# códigos aqui são os mesmos `Funil.codigo` de `cadence_joao.py` (duplicados aqui de
# propósito — este módulo já mantém sua própria cópia das constantes de pipeline, fora
# do escopo deste rename).
_FUNIL_POR_PIPELINE: dict[str, str] = {
    PIPELINE_JOAO_ATACADO: "atacado",
    PIPELINE_JOAO_PRIVATE_LABEL: "private_label",
    PIPELINE_JOAO_REPOSICAO_ATACADO: "reposicao_atacado",
    PIPELINE_JOAO_REPOSICAO_PRIVATE_LABEL: "reposicao_private_label",
}
_FUNIL_CODIGOS_CONHECIDOS: tuple[str, ...] = tuple(dict.fromkeys(_FUNIL_POR_PIPELINE.values()))

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

    # BLOQUEIO: este disparo é síncrono e roda FORA do loop de `process_due_followups`,
    # que é onde mora o backstop (`_lead_stop_reason`) — a tool `retomar_contato_vendedor`
    # chama esta função direto. Sem o guard aqui, o único caminho que manda template pelo
    # número do João escapava de todas as camadas. Só checa quando há `lead_id` (o
    # parâmetro é opcional e a assinatura não muda): sem ele não há o que consultar, e o
    # `False` devolvido leva o chamador ao fallback de reagendamento, que passa pelo
    # backstop no próximo tick.
    if lead_id and is_lead_blacklisted(lead_id):
        logger.warning(
            "[JOAO_REENGAGE][BLACKLIST] lead %s (%s) na blacklist — template do João ABORTADO",
            lead_id, lead_phone,
        )
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
            # Billing normalizado → retoma broadcasts pausados por billing (wartime T4).
            # Fail-soft e import tardio: o health check JAMAIS quebra por causa disto.
            try:
                from app.broadcast.service import resume_broadcasts_after_billing
                resume_broadcasts_after_billing()
            except Exception as exc:
                logger.error("[HEALTH] Falha no auto-resume de broadcasts pós-billing: %s", exc)
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

        # REDE DE SEGURANÇA DE PARADA (defesa em profundidade) — roda para QUALQUER
        # job_type, logo após a reivindicação e ANTES de qualquer despacho. A interrupção
        # da cadência não pode depender só do cancelamento-na-escrita ter alcançado a
        # linha certa (caso 5511910402026, 15/07: a cliente pediu ao humano para a IA
        # parar, mas nada disso virou estado — opt_out/ai_enabled intactos — e os toques
        # seguiram). Aqui relemos o lead e, se ele está marcado para parar (opt-out,
        # blacklist, número errado, IA desligada), cancelamos o job seja qual for o tipo
        # ou estado, sem enviar. Fail-soft: releitura falha → None → não age (o job segue
        # para o fluxo normal, exatamente como antes).
        stop_lead_id = job.get("lead_id")
        if stop_lead_id:
            try:
                stop_reason = _lead_stop_reason(_fetch_lead_for_backstop(stop_lead_id))
            except Exception as exc:
                logger.error(
                    "[FOLLOWUP] falha no backstop de parada (lead %s) — seguindo para o "
                    "fluxo normal: %s", stop_lead_id, exc, exc_info=True,
                )
                stop_reason = None
            # A decisão é (motivo, tipo de job) — não só o motivo: `ai_disabled` não pode
            # matar o `handoff_rescue`, que existe justamente porque a IA foi desligada.
            # Ver _STOP_REASON_EXEMPT_JOB_TYPES (auditoria 27/07, caso Wilson Demuth).
            if _stop_reason_applies(stop_reason, job.get("job_type")):
                _cancel_job(job["id"], stop_reason)
                logger.info(
                    "[FOLLOWUP] lead %s marcado para parar (%s) — job %s (%s) suprimido no envio",
                    stop_lead_id, stop_reason, job["id"], job.get("job_type"),
                )
                continue
            if stop_reason:
                logger.info(
                    "[FOLLOWUP] lead %s marcado para parar (%s) mas job %s (%s) é isento — seguindo",
                    stop_lead_id, stop_reason, job["id"], job.get("job_type"),
                )

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

        # Cadências do VENDEDOR (spec 2026-09-18): template aprovado, sem LLM. Casa por
        # prefixo `joao_` — ver _is_joao_job_type para o porquê. Precisa vir ANTES do
        # caminho `standard`: o canal do João é `mode='human'`, e lá embaixo o guard de
        # canal humano cancelaria o toque em silêncio.
        if _is_joao_job_type(job.get("job_type")):
            await _process_joao_touch(job, now)
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
        # Relê o lead UMA vez para os dois guards seguintes (número errado + backstop
        # pós-catálogo). Fail-soft: erro na releitura → None e nenhum guard age (o
        # job segue para o fluxo padrão — nunca derruba o tick).
        try:
            fresh_lead = _fetch_lead_for_backstop(job["lead_id"])
        except Exception as exc:
            logger.error(
                "[FOLLOWUP] falha ao reler lead %s para os guards do toque — seguindo "
                "para o follow-up padrão: %s",
                job["lead_id"], exc, exc_info=True,
            )
            fresh_lead = None

        # Guard: número errado (caso Maria, 10/07) — quem negou ser o dono do número
        # não recebe toque de cadência NEM reopen (o reopen dispara deste mesmo
        # caminho, no guard de janela abaixo). Roda ANTES do backstop: wrong_number
        # com catalog_shown não pode virar handoff proativo.
        if lead_marked_wrong_number(fresh_lead):
            _cancel_job(job["id"], "wrong_number")
            logger.info(
                "[FOLLOWUP] lead %s marcado wrong_number — toque suprimido seq=%s conversation=%s",
                job["lead_id"], sequence, conversation_id,
            )
            continue

        try:
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


def _lead_stop_reason(lead: dict | None) -> str | None:
    """Motivo de PARADA do lead, ou None se ele deve seguir recebendo follow-up.

    Fonte única do backstop de envio de `process_due_followups`. Ordem de prioridade dá
    o `cancel_reason` gravado (preserva a semântica de analytics já existente: `opt_out`,
    `wrong_number`, `ai_disabled`). Fail-open: lead None/sem flags → None (na dúvida, o
    fluxo normal segue). `ai_enabled` só para quando é EXPLICITAMENTE False (ausente/None
    não dispara — o lead veio de um select que pode não trazer o campo).

    NÃO é mais uma função pura: o último critério (`is_lead_blacklisted`) vai ao banco.
    A troca é deliberada — este é o backstop ÚNICO de 6 caminhos de envio e ele só
    enxergava `leads.opt_out` e `metadata.blacklisted_at`. Um lead BLOQUEADO só pelo card
    no funil Blacklist (o outro braço do critério canônico, e o único que sobra quando a
    coluna de evidência não existe) passava reto e seguia recebendo toque. As checagens
    em memória vêm antes de propósito: a consulta só acontece para o lead que, pelo que
    está em mãos, seguiria recebendo.
    """
    if not isinstance(lead, dict):
        return None
    if lead.get("opt_out"):
        return "opt_out"
    meta = lead.get("metadata") or {}
    if isinstance(meta, dict):
        if meta.get("blacklisted_at"):
            return "blacklisted"
        if meta.get("wrong_number_at"):
            return "wrong_number"
    # ANTES de `ai_disabled`, e a ordem é o ponto: `ai_disabled` é o único motivo com
    # isenção (`_STOP_REASON_EXEMPT_JOB_TYPES` → handoff_rescue). Um lead bloqueado tem
    # `ai_enabled=False` junto, então checar depois devolveria "ai_disabled" e o resgate
    # isento dispararia template para quem está na Blacklist. "blacklisted" não é isento
    # de nada — e continua não sendo.
    if lead.get("id") and is_lead_blacklisted(lead["id"]):
        logger.info(
            "[FOLLOWUP][BLACKLIST] lead %s na blacklist (opt-out ou funil Blacklist) — follow-up barrado",
            lead["id"],
        )
        return "blacklisted"
    if lead.get("ai_enabled") is False:
        return "ai_disabled"
    return None


# Exceções do backstop de parada, por MOTIVO (não por tipo de job) — auditoria 27/07.
#
# `ai_disabled` x `handoff_rescue` é CIRCULAR: `encaminhar_humano` desliga a IA ao fazer o
# handoff, e é esse mesmo handoff que agenda o resgate. O job nascia condenado — 144 jobs
# criados entre 22 e 27/07, 144 cancelados com `ai_disabled`, ZERO enviados. O roteador
# dedicado (`_process_handoff_rescue`, comentado como "antes de qualquer guard padrão")
# nunca era alcançado, porque o backstop roda antes dele.
#
# Custo real: lead Wilson Demuth (5547992221012) recebeu handoff + cartão em 26/07 16:04,
# mandou um áudio às 17:32 e nunca apareceu no canal do João — >21h no vácuo. O
# `handoff_rescue` era exatamente o anteparo desse caso.
#
# A isenção é SÓ de `ai_disabled`. `opt_out`, `blacklisted` e `wrong_number` continuam
# cancelando o resgate: não se manda template para quem pediu para sair nem para número
# errado. O caso que motivou o backstop (5511910402026, 15/07 — cliente pediu ao humano
# para a IA parar e os toques seguiram) é de cadência ao LEAD e segue integralmente coberto;
# `handoff_rescue` não é cadência, é uma notificação por template ao VENDEDOR.
_STOP_REASON_EXEMPT_JOB_TYPES: dict[str, frozenset[str]] = {
    "ai_disabled": frozenset({"handoff_rescue"}),
}


def _stop_reason_applies(reason: str | None, job_type: str | None) -> bool:
    """True quando `reason` deve cancelar um job deste `job_type`.

    Função PURA, separada de `_lead_stop_reason` de propósito: aquela responde "este LEAD
    está marcado para parar?" (e continua inalterada — a resposta segue sendo sim); esta
    responde "esse motivo se aplica a ESTE job?". Sem a separação, a única forma de isentar
    o resgate seria mentir sobre o estado do lead.
    """
    if not reason:
        return False
    # Cadências do João x `ai_disabled`: MESMA circularidade do handoff_rescue, e pelo mesmo
    # motivo — o lead só está no funil do vendedor porque a IA foi desligada nele (é o que
    # `encaminhar_humano` faz no handoff). Sem esta isenção TODO job do João nasceria
    # condenado, repetindo o custo já medido no resgate: 144 jobs criados entre 22 e 27/07,
    # 144 cancelados com `ai_disabled`, ZERO enviados.
    # A isenção é SÓ de `ai_disabled`: `opt_out`, `blacklisted` e `wrong_number` continuam
    # cancelando o toque do João, que são exatamente as paradas que o spec §9 exige.
    # Fora da tabela `_STOP_REASON_EXEMPT_JOB_TYPES` porque o casamento do João é por
    # PREFIXO (ver _is_joao_job_type), não por lista fechada de tipos.
    if reason == "ai_disabled" and _is_joao_job_type(job_type):
        return False
    return job_type not in _STOP_REASON_EXEMPT_JOB_TYPES.get(reason, frozenset())


def _fetch_lead_for_backstop(lead_id: str) -> dict | None:
    """Relê o lead para os backstops de parada e a decisão `should_proactive_handoff`.

    O select de `get_due_followups` (join `leads!inner(...)`) não traz `stage`, `metadata`,
    `opt_out` nem `ai_enabled` — só id/phone/name/last_customer_message_at/wa_id — então a
    decisão precisa reler o lead à parte, mesmo padrão de `_process_ai_reengage`/
    `_process_ai_scheduled_return`. Fail-soft: erro de DB → None (tanto `_lead_stop_reason`
    quanto `should_proactive_handoff` tratam `None` como não-elegível, então o lead segue
    para o follow-up padrão).
    """
    try:
        sb = get_supabase()
        res = (
            sb.table("leads")
            .select("id, phone, stage, opt_out, ai_enabled, metadata")
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


def _rescue_contact_cutoff(job: dict, now: datetime) -> str:
    """Desde quando procurar por contato do lead com o João, ao decidir se o resgate ainda
    faz sentido.

    Antes era fixo em `now - 15min`, o que só equivale a "desde o handoff" no caso feliz,
    em que o job dispara 15 min depois dele. Quebrava em dois casos reais (auditoria 27/07):

      * `_clamp_to_rescue_window`: handoff às 21h de sexta agenda o resgate para segunda
        09h. A janela de 15 min cobria segunda 08:45-09:00 — um lead que escreveu ao João
        no sábado recebia "o João vai te atender" mesmo já estando com ele.
      * Reagendamento em lote (recovery da regressão de 15/07): 178 jobs criados para
        28/07 09:00 sobre handoffs de até 13 dias antes. A janela de 15 min ignoraria dias
        inteiros de conversa.

    Ordem: `metadata.original_handoff_at` (gravado pelo script de recovery) → `created_at`
    do job (no fluxo normal, o próprio instante do handoff) → `now - 15min` como último
    recurso, preservando o comportamento antigo para job legado/malformado.

    Referência no futuro é descartada: tornaria a janela vazia e o guard inútil.
    """
    for candidato in ((job.get("metadata") or {}).get("original_handoff_at"), job.get("created_at")):
        if not candidato:
            continue
        try:
            ref = datetime.fromisoformat(str(candidato).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        if ref <= now:
            return str(candidato)
    return (now - timedelta(minutes=15)).isoformat()


async def _process_handoff_rescue(job: dict, now: datetime) -> None:
    """Dispara o template de resgate se o lead NÃO procurou o João desde o handoff.

    A janela de checagem vem de `_rescue_contact_cutoff` — "desde o handoff", não um
    intervalo fixo de 15 min (ver o docstring de lá para os casos que isso quebrava)."""
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
    cutoff = _rescue_contact_cutoff(job, now)

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


# ─────────────────────────────────────────────────────────────────────────────
# Toque das cadências do João (spec 2026-09-18). Handler AUTOCONTIDO: o único ponto
# compartilhado com o caminho `standard` da ValerIA é o despacho por `job_type` em
# `process_due_followups`.
# ─────────────────────────────────────────────────────────────────────────────

def _is_joao_job_type(job_type: str | None) -> bool:
    """True para qualquer `job_type` das cadências do João.

    Reconhece pelo PREFIXO (`joao_`), não por uma lista fechada, de propósito: a forma da
    cadência — um tipo único (`joao_touch` + `metadata.cadencia`) ou um tipo por cadência
    (`joao_reposicao`, `joao_em_atencao`, …) — é decidida em `cadence_joao.py`/agendador,
    e o despacho não pode ficar refém dessa escolha. Um tipo do João que NÃO casasse aqui
    cairia no caminho `standard`, onde o canal humano do vendedor o cancelaria em silêncio
    (`human_channel`) — cadência que inscreve, não envia, e caminha até o fim.
    """
    if not job_type:
        return False
    return job_type in JOAO_JOB_TYPES or job_type.startswith(JOAO_JOB_TYPE_PREFIX)


def _funil_key(value: str) -> str:
    """Forma canônica p/ comparar códigos de funil: sem acento, minúsculo, só alfanumérico."""
    return "".join(ch for ch in _strip_accents(value).strip().lower() if ch.isalnum())


def _normalize_joao_funil(value: str | None) -> str | None:
    """'Reposição Private Label' / 'reposicao-private-label' → 'reposicao_private_label'.

    Compara por IGUALDADE contra os códigos conhecidos (`_FUNIL_CODIGOS_CONHECIDOS`),
    nunca por substring: é a correção do bug descrito junto de `_FUNIL_POR_PIPELINE` —
    com substring, "atacado" casava tanto com o funil "atacado" quanto com
    "reposicao_atacado" (a substring aparece dentro dos dois), reintroduzindo a mesma
    colisão pela porta dos fundos. Função pura.
    """
    if not value:
        return None
    chave = _funil_key(str(value))
    for codigo in _FUNIL_CODIGOS_CONHECIDOS:
        if chave == _funil_key(codigo):
            return codigo
    return None


def _resolve_joao_funil(job: dict) -> str | None:
    """Funil (Atacado, Private Label, Reposição Atacado, Reposição Private Label) deste
    toque, ou None se indeterminável.

    Ordem: `metadata.funil` (já resolvido pelo agendador) → `metadata.pipeline_id` → o
    funil do deal (`metadata.deal_id`, senão o deal mais recente do lead num dos quatro
    funis do João). Fail-soft: qualquer erro de leitura → None; quem chama decide (com
    `template_name` explícito o toque segue; sem ele, o job é cancelado em vez de mandar
    o texto do funil errado).
    """
    metadata = job.get("metadata") or {}

    funil = _normalize_joao_funil(metadata.get("funil"))
    if funil:
        return funil

    funil = _FUNIL_POR_PIPELINE.get(str(metadata.get("pipeline_id") or ""))
    if funil:
        return funil

    deal_id = metadata.get("deal_id")
    lead_id = job.get("lead_id")
    if not deal_id and not lead_id:
        return None

    try:
        sb = get_supabase()
        if deal_id:
            res = (
                sb.table("deals").select("id, pipeline_id").eq("id", deal_id).limit(1).execute()
            )
        else:
            res = (
                sb.table("deals").select("id, pipeline_id")
                .eq("lead_id", lead_id)
                .in_("pipeline_id", list(_FUNIL_POR_PIPELINE))
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        rows = res.data if isinstance(res.data, list) else []
        if rows:
            return _FUNIL_POR_PIPELINE.get(str(rows[0].get("pipeline_id") or ""))
    except Exception as exc:
        logger.warning(
            "[JOAO_TOUCH] falha ao resolver o funil do card (deal=%s lead=%s): %s",
            deal_id, lead_id, exc,
        )
    return None


def _joao_template_name(metadata: dict, funil: str | None) -> str | None:
    """Template APROVADO deste toque.

    Duas formas aceitas, nesta ordem — o agendador escolhe a que lhe for natural:
      * `metadata.template_name`: já resolvido por funil na hora de criar o job;
      * `metadata.template_por_funil`: {"atacado": ..., "private_label": ..., ...},
        resolvido aqui contra o funil do card.
    Nenhuma das duas → None, e o toque é cancelado: nunca improvisamos template.
    """
    nome = (metadata.get("template_name") or "").strip()
    if nome:
        return nome
    por_funil = metadata.get("template_por_funil") or {}
    if isinstance(por_funil, dict) and funil:
        nome = (por_funil.get(funil) or "").strip()
        if nome:
            return nome
    return None


def _resolve_joao_channel(metadata: dict) -> dict | None:
    """Canal do VENDEDOR (não o da ValerIA), pelo mesmo caminho de `_process_handoff_rescue`.

    Resolver pelo `phone_number_id` — e não pelo `channels` joinado do job — é deliberado:
    o toque da cadência do vendedor tem de sair do NÚMERO DELE. Um job criado com o
    channel_id errado mandaria o texto assinado "João" pelo número da ValerIA.
    """
    phone_number_id = metadata.get("phone_number_id") or JOAO_PHONE_NUMBER_ID
    return get_channel_by_provider_config("phone_number_id", phone_number_id, "meta_cloud")


async def _persist_joao_touch_message(
    job: dict, channel: dict, template_name: str, template_variables: dict, send_result: dict | None
) -> None:
    """Grava na conversa do canal do João o texto RENDERIZADO do template enviado.

    Mesmo motivo de `_persist_joao_handoff_message`: sem isto o disparo sai pela Meta mas
    não entra em `messages`, e quando o lead responde o CRM mostra só a resposta dele,
    como se tivesse iniciado do nada. Reusa o renderizador do broadcast
    (`_render_template_body`) — import tardio porque `broadcast/worker.py` importa ESTE
    módulo (`process_due_followups`), e o import no topo fecharia o ciclo.

    Nunca levanta e nunca grava o placeholder "[Template: x]" que o renderizador devolve
    quando não acha o corpo: gravar o placeholder como fala do vendedor envenena o
    histórico do CRM (decisão já tomada no disparo de LP, Eixo 2a).
    """
    try:
        from app.broadcast.worker import _render_template_body

        rendered = await _render_template_body(
            template_name, template_variables, job.get("leads") or {}, channel
        )
        if not rendered or rendered.startswith("[Template:"):
            logger.warning(
                "[JOAO_TOUCH] corpo do template '%s' não renderizado — mensagem não persistida",
                template_name,
            )
            return
        conv = get_or_create_conversation(job["lead_id"], channel["id"])
        save_message_conv(
            conversation_id=conv["id"],
            lead_id=job["lead_id"],
            role="assistant",
            content=rendered,
            sent_by="followup",
            wamid=extract_wamid(send_result),
            metadata=dispatch_metadata(template_name),
        )
    except Exception as exc:
        logger.error(
            "[JOAO_TOUCH] falha ao persistir a mensagem do toque (lead %s): %s",
            job.get("lead_id"), exc, exc_info=True,
        )


def _cadencia_declarada(metadata: dict, funil: str | None):
    """A `Cadencia` que criou este job, ou None se o par (funil, cadência) não existe.

    O job de mover só traz o CÓDIGO da cadência e o do funil (`metadata.cadencia` /
    `metadata.funil`); quem sabe qual ETAPA essa cadência vigia é `cadence_joao`, que é
    a origem da configuração. Ler de lá (em vez de gravar a etapa vigiada no job) mantém
    uma única fonte: mudar o gatilho no código muda junto a guarda do move.
    """
    codigo = str(metadata.get("cadencia") or "").strip()
    if not funil or not codigo:
        return None
    return cadencia_do_funil(funil, codigo)


def _mover_card_joao(deal_id: str, etapa_key: str, etapa_vigiada: str | None = None) -> bool:
    """Move o card do João para a etapa `etapa_key`. Defensivo — spec 2026-09-23 §3.

    Mesmo padrão de `quotes/router.py::_move_deal_to_proposal`, com a mesma armadilha
    nomeada: a `key` da etapa de destino é procurada DENTRO do pipeline do próprio deal.
    `key` só é única POR PIPELINE (índice `idx_pipeline_stages_key_unique`), e `em_atencao`
    existe nos quatro funis do João — sem o filtro, o card iria para o funil de outra
    pessoa.

    Duas guardas, e a primeira é a razão de ser desta função:

    * **`etapa_vigiada`**: só move se o card AINDA estiver na etapa que a cadência vigia.
      Se o João já o moveu à mão (ou uma automação o moveu), o move do fim da cadência
      NÃO desfaz o que ele fez. `None` desliga a guarda — quem chama do handler sempre a
      passa, e sem ela desiste de mover (ver `_process_joao_touch`).
    * **etapa de destino inexistente no funil**: registra e devolve False, sem levantar.

    Devolve True só quando o card de fato andou. Erro inesperado de banco NÃO é engolido:
    sobe para quem chama, que o trata como transitório (o job não vira terminal e o
    próximo tick tenta de novo) — cancelar por um soluço de rede seria permanente.
    """
    sb = get_supabase()
    res = (sb.table("deals").select("pipeline_id, stage_id")
           .eq("id", deal_id).limit(1).execute())
    linhas = res.data if isinstance(res.data, list) else []
    deal = linhas[0] if linhas else {}
    pipeline_id = deal.get("pipeline_id")
    if not pipeline_id:
        logger.info("[JOAO_MOVER] deal %s não encontrado (ou sem funil) — nada a mover", deal_id)
        return False

    # Uma consulta só para as etapas do funil: precisamos do alvo E da posição atual.
    etapas_res = (sb.table("pipeline_stages").select("id, key")
                  .eq("pipeline_id", pipeline_id).execute())
    etapas = etapas_res.data if isinstance(etapas_res.data, list) else []

    atual = next((e for e in etapas if e.get("id") == deal.get("stage_id")), None)
    if etapa_vigiada and (atual or {}).get("key") != etapa_vigiada:
        logger.info(
            "[JOAO_MOVER] deal %s já saiu da etapa %s (está em %s) — move da cadência não "
            "desfaz o que o vendedor fez",
            deal_id, etapa_vigiada, (atual or {}).get("key"),
        )
        return False

    alvo = next((e for e in etapas if e.get("key") == etapa_key), None)
    if not alvo:
        # Funil sem a etapa (migration não aplicada, ou key renomeada à mão no CRM): a
        # cadência já terminou de qualquer forma, só o card não anda.
        logger.warning(
            "[JOAO_MOVER] funil %s não tem a etapa %s — deal %s fica onde está",
            pipeline_id, etapa_key, deal_id,
        )
        return False

    (sb.table("deals")
     .update({"stage_id": alvo["id"], "updated_at": datetime.now(timezone.utc).isoformat()})
     .eq("id", deal_id).execute())
    logger.info("[JOAO_MOVER] deal %s movido para a etapa %s (%s)", deal_id, etapa_key, alvo["id"])
    return True


async def _process_joao_touch(job: dict, now: datetime) -> None:
    """Um toque de cadência do vendedor: TEMPLATE APROVADO, sem LLM.

    O lead está em silêncio por definição (é o que o gatilho da cadência mede), então a
    janela de 24h da Meta está fechada e free-text seria rejeitado (#131047). Por isso
    este handler não tem nenhum ramo de geração de texto — ele resolve o funil do card,
    monta os componentes do template, resolve o canal do vendedor, envia e marca.

    Espelha `_process_lp_welcome`/`_process_handoff_rescue` no tratamento de erro da Meta:
    4xx e rejeição embutida (HTTP 200 com erro) são PERMANENTES e cancelam o job; 5xx e
    falha de rede não marcam estado terminal e são retentados no próximo tick.

    UM job deste tipo não manda mensagem nenhuma: o do fim da cadência, marcado com
    `metadata.acao == "mover_etapa"`, que só move o card (spec 2026-09-23 §3).
    """
    metadata = job.get("metadata") or {}
    lead = job.get("leads") or {}
    conversation = job.get("conversations") or {}

    # Guard: conversa finalizada pelo vendedor em /conversas. Mesma parada do caminho
    # `standard` (e do gatilho SQL, `get_deals_stage_stagnant`): quando o João encerra o
    # atendimento na tela, a cadência dele não pode continuar atrás.
    if not conversation.get("followup_enabled", True):
        _cancel_job(job["id"], "followup_disabled")
        logger.info(
            "[JOAO_TOUCH] followup_enabled=false — cancelando job %s conv=%s",
            job["id"], job.get("conversation_id"),
        )
        return

    # ── O job que MOVE o card, e não envia nada (spec 2026-09-23 §3) ─────────────
    # A ÚNICA condição é a marca `metadata.acao` — nunca "o template está nulo", porque
    # job de TOQUE sem template também existe e é hoje a regra, não a exceção (os 22
    # toques das três cadências de prospecção nascem todos sem texto).
    #
    # Vem DEPOIS do guard de `followup_enabled` de propósito: quando o João encerra o
    # atendimento em /conversas, a cadência inteira para — e arrastar o card para "Em
    # atenção" depois disso é continuar a cadência atrás dele, que é exatamente o que
    # aquele guard existe para impedir. Antes de tudo o mais: não resolve template, não
    # resolve canal, não toca no telefone do lead.
    if metadata.get("acao") == ACAO_MOVER_ETAPA:
        funil = _resolve_joao_funil(job)
        cadencia = _cadencia_declarada(metadata, funil)
        deal_id = str(metadata.get("deal_id") or "").strip()
        etapa_final = str(metadata.get("etapa_final_key") or "").strip() or (
            cadencia.etapa_final_key if cadencia else None
        )
        if not deal_id or not etapa_final:
            # Impossível pelo contrato do job (o agendador grava os dois). Cancelar em vez
            # de marcar `sent` é deliberado: job malformado é BUG, e `cancel_reason` é onde
            # ele fica visível numa consulta.
            _cancel_job(job["id"], "mover_etapa_sem_alvo")
            logger.error(
                "[JOAO_MOVER] job %s sem alvo (deal=%s etapa_final=%s cadencia=%s funil=%s)",
                job["id"], deal_id or None, etapa_final, metadata.get("cadencia"), funil,
            )
            return

        etapa_vigiada = cadencia.gatilho_stage_key if cadencia else None
        if not etapa_vigiada:
            # Fail-closed: sem saber que etapa a cadência vigia não há como garantir que o
            # card continua nela, e mover às cegas desfaria um move manual do vendedor.
            logger.error(
                "[JOAO_MOVER] cadência (%s, %s) não resolvida — job %s encerrado SEM mover",
                funil, metadata.get("cadencia"), job["id"],
            )
            _mark_sent(job["id"])
            return

        try:
            movido = _mover_card_joao(deal_id, etapa_final, etapa_vigiada=etapa_vigiada)
        except Exception as exc:
            logger.error(
                "[JOAO_MOVER] falha ao mover o deal %s para %s: %s — será retentado",
                deal_id, etapa_final, exc, exc_info=True,
            )
            return  # transitório → retry no próximo tick

        # `sent` também quando NÃO moveu, e não `cancelled`: o job rodou até o fim e
        # decidiu não mexer no card. Marcar `cancelled` aqui mentiria para o cooldown por
        # matrícula do agendador, que lê job cancelado como "o lead respondeu no meio" e
        # LIBERA a reentrada — um funil sem a etapa de destino passaria a rematricular o
        # mesmo card a cada gatilho.
        logger.info(
            "[JOAO_MOVER] job %s: deal %s → %s (cadencia=%s funil=%s) — %s",
            job["id"], deal_id, etapa_final, metadata.get("cadencia"), funil,
            "movido" if movido else "nada a fazer",
        )
        _mark_sent(job["id"])
        return

    lead_phone = metadata.get("lead_phone") or lead.get("phone") or ""
    if not lead_phone:
        _cancel_job(job["id"], "missing_lead_phone")
        logger.error("[JOAO_TOUCH] job %s sem telefone do lead", job["id"])
        return

    funil = _resolve_joao_funil(job)
    template_name = _joao_template_name(metadata, funil)
    if not template_name:
        _cancel_job(job["id"], "missing_template_name")
        logger.error(
            "[JOAO_TOUCH] job %s sem template (cadencia=%s funil=%s toque=%s) — nada a enviar",
            job["id"], metadata.get("cadencia"), funil, metadata.get("toque"),
        )
        return

    channel = _resolve_joao_channel(metadata)
    if not channel:
        _cancel_job(job["id"], "joao_channel_not_found")
        logger.error(
            "[JOAO_TOUCH] canal do vendedor (phone_number_id=%s) não encontrado — job %s",
            metadata.get("phone_number_id") or JOAO_PHONE_NUMBER_ID, job["id"],
        )
        return

    language_code = metadata.get("language_code") or JOAO_TOUCH_TEMPLATE_LANGUAGE
    template_variables = metadata.get("template_variables") or JOAO_TOUCH_TEMPLATE_VARIABLES
    # Import tardio: broadcast/worker.py importa process_due_followups deste módulo, e o
    # import no topo fecharia o ciclo. Reusar o montador do broadcast (em vez de montar os
    # componentes à mão aqui) é o que mantém UMA única regra de resolução de {{1}}/nome.
    from app.broadcast.worker import _build_template_components

    components = _build_template_components(template_variables, lead)
    # Destino entregável: wa_id real quando houver (evita 131026 em número sem o 9º dígito).
    send_to = resolve_send_target(lead, lead_phone)

    try:
        provider = MetaCloudClient(channel["provider_config"])
        send_result = await provider.send_template(
            send_to, template_name, components=components, language_code=language_code
        )
        logger.info(
            "[JOAO_TOUCH] template '%s' (%s) enviado p/ %s — cadencia=%s funil=%s toque=%s",
            template_name, language_code, send_to,
            metadata.get("cadencia"), funil, metadata.get("toque"),
        )
    except httpx.HTTPStatusError as http_exc:
        status = http_exc.response.status_code
        if 400 <= status < 500:
            _cancel_job(job["id"], f"meta_permanent_error_{status}")
            logger.error(
                "[JOAO_TOUCH] erro permanente Meta HTTP %s para %s — job %s cancelado",
                status, send_to, job["id"],
            )
        else:
            logger.error(
                "[JOAO_TOUCH] erro transitório Meta HTTP %s para %s — será retentado",
                status, send_to, exc_info=True,
            )
        return
    except RuntimeError as exc:
        # HTTP 200 COM erro embutido = rejeição PERMANENTE. Sem cancelar, o job ficaria
        # pending e seria retentado a cada tick para sempre.
        _cancel_job(job["id"], "meta_rejected")
        logger.error(
            "[JOAO_TOUCH] rejeição permanente Meta p/ %s — job %s cancelado: %s",
            send_to, job["id"], exc,
        )
        return
    except Exception as exc:
        logger.error(
            "[JOAO_TOUCH] falha ao enviar template p/ %s: %s", send_to, exc, exc_info=True
        )
        return  # transitório (rede etc.) → retry no próximo tick

    # Idempotência: wamid no job ANTES do estado terminal (ver _save_followup_wamid).
    _save_followup_wamid(job["id"], extract_wamid(send_result))
    await _persist_joao_touch_message(job, channel, template_name, template_variables, send_result)
    _mark_sent(job["id"])


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
