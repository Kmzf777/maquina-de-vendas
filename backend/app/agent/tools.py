import asyncio
import base64
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.leads.service import update_lead, save_message, create_deal, get_lead, get_history, apply_optout_side_effects
from app.conversations.service import update_conversation, get_history as get_conversation_history
from app.whatsapp.registry import get_provider
from app.whatsapp.meta import extract_wamid
from app.channels.service import get_channel_for_lead
from app.follow_up.service import schedule_handoff_rescue

logger = logging.getLogger(__name__)

_TZ_BR = timezone(timedelta(hours=-3))

# Per-conversation deferred media queue: photos queued during tool execution that
# should be dispatched by the processor AFTER the text response is sent.
# Keyed by conversation_id to avoid cross-contamination between concurrent calls.
_deferred_media: dict[str, list[dict]] = {}


def pop_deferred_media(conversation_id: str) -> list[dict]:
    """Return and clear deferred media for a conversation.

    Each entry: {"b64": str, "mimetype": str, "caption": str}.
    Called by processor.py after text bubbles are sent.
    """
    return _deferred_media.pop(conversation_id, [])


# Per-conversation flag: set when the LLM calls marcar_interesse during this turn.
# Popped by the processor to decide whether to (re)schedule follow-ups.
_interest_marked: dict[str, dict] = {}


def pop_interest_marked(conversation_id: str) -> dict | None:
    """Return and clear the interest signal for a conversation (None if not set)."""
    return _interest_marked.pop(conversation_id, None)


PHOTO_CAPTIONS: dict[str, dict[str, str]] = {
    "atacado": {
        "foto_1": "Classico — torra media-escura, notas achocolatadas",
        "foto_2": "Suave — torra media, notas de melaco e frutas amarelas",
        "foto_3": "Canela — caramelizado com toque de canela",
        "foto_4": "Microlote — notas de mel, caramelo e cacau",
        "foto_5": "Drip Coffee e Capsulas Nespresso",
    },
    "private_label": {
        "foto_1": "Embalagem personalizada com sua marca",
        "foto_2": "Modelo de embalagem standup",
        "foto_3": "Exemplo de silk com logo do cliente",
        "foto_4": "Produto final pronto para comercializacao",
    },
}

PRODUTO_PHOTO_MAP: dict[str, dict[str, dict[str, str]]] = {
    "atacado": {
        "classico": {"file": "foto_1.jpg", "caption": "Classico — torra media-escura, notas achocolatadas"},
        "suave": {"file": "foto_2.jpg", "caption": "Suave — torra media, notas de melaco e frutas amarelas"},
        "canela": {"file": "foto_3.png", "caption": "Canela — caramelizado com toque de canela"},
        "microlote": {"file": "foto_4.jpg", "caption": "Microlote — notas de mel, caramelo e cacau"},
        "drip": {"file": "foto_5.jpg", "caption": "Drip Coffee e Capsulas Nespresso"},
        "capsulas": {"file": "foto_5.jpg", "caption": "Drip Coffee e Capsulas Nespresso"},
    },
    "private_label": {
        "embalagem": {"file": "foto_1.jpg", "caption": "Embalagem personalizada com sua marca"},
        "standup": {"file": "foto_2.jpg", "caption": "Modelo de embalagem standup"},
        "silk": {"file": "foto_3.jpg", "caption": "Exemplo de silk com logo do cliente"},
        "final": {"file": "foto_4.jpg", "caption": "Produto final pronto para comercializacao"},
    },
}

_HANDOFF_MSG = (
    "Perfeito! Seu atendimento agora será continuado pelo João, um dos nossos especialistas.\n\n"
    "👉 Clique no link abaixo e envie uma mensagem para ele agora mesmo para dar continuidade "
    "no seu atendimento com prioridade:\n"
    "http://wa.me/553491461669\n\n"
    "Assim que você chamar, ele já receberá seu contato e continuará seu atendimento."
)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "salvar_nome",
            "description": "Salva o nome do lead quando descoberto durante a conversa",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nome do lead"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mudar_stage",
            "description": (
                "Transfere o lead para outro stage de forma silenciosa — nunca avise o cliente sobre a mudanca. "
                "Gatilhos por stage: "
                "atacado — lead menciona revenda, distribuidora, cafeteria, restaurante ou qualquer negocio querendo cafe em volume; "
                "private_label — lead quer marca propria, embalagem personalizada ou produto com identidade visual propria; "
                "exportacao — lead menciona mercado externo, exportacao ou pais de destino; "
                "consumo — pessoa fisica comprando para uso proprio, sem fins comerciais. "
                "Execute imediatamente ao identificar o gatilho, sem perguntar ao cliente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "stage": {
                        "type": "string",
                        "enum": ["secretaria", "atacado", "private_label", "exportacao", "consumo"],
                        "description": "Stage de destino",
                    }
                },
                "required": ["stage"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "encaminhar_humano",
            "description": (
                "Registra o encerramento da interacao e transfere o controle para um humano. "
                "USE nos seguintes casos: "
                "(1) lead qualificado e pronto para fechar — passe vendedor e motivo; "
                "(2) lead REJEITOU explicitamente o modelo de negocio — passe motivo='Cliente nao aceitou o modelo de negocio'; "
                "(3) circuit breaker: 6+ turnos no stage atacado sem handoff, ou 8+ turnos no stage private_label — chame imediatamente. "
                "NAO use para despedida amigavel ('obrigado', 'logo te procuro', 'vou pensar') — essas NAO sao rejeicao. "
                "Esta ferramenta ENCERRA a conversa automatica: apos chama-la, NAO envie mais nenhuma mensagem de texto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vendedor": {"type": "string", "description": "Nome do vendedor (opcional — omita em casos de rejeicao)"},
                    "motivo": {"type": "string", "description": "Motivo do encaminhamento ou encerramento"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_optout",
            "description": (
                "Registra opt-out silencioso do lead. Use SOMENTE quando o lead pedir explicitamente "
                "para parar de receber mensagens, sair da lista, ou expressar que nao quer mais contato "
                "(incluindo clique no botao 'Parar mensagens'). "
                "Desativa a IA para este lead silenciosamente, sem notificar o time comercial e sem criar negocio. "
                "Antes de chamar esta tool, escreva UMA mensagem de despedida respeitosa no texto do turno. "
                "Apos chamar, NAO envie mais nenhuma mensagem."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {
                        "type": "string",
                        "description": "Descricao do pedido (ex: 'clicou parar mensagens', 'nao quer mais contato')"
                    }
                },
                "required": ["motivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_fotos",
            "description": "Envia catalogo de fotos dos produtos ao lead",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": ["atacado", "private_label"],
                        "description": "Categoria do catalogo",
                    }
                },
                "required": ["categoria"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enviar_foto_produto",
            "description": "Envia a foto de UM produto especifico ao lead com descricao. Use para intercalar texto e foto na conversa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "enum": ["atacado", "private_label"],
                        "description": "Categoria do produto",
                    },
                    "produto": {
                        "type": "string",
                        "description": "Nome do produto (ex: classico, suave, canela, microlote, drip, capsulas, embalagem, standup, silk, final)",
                    },
                },
                "required": ["categoria", "produto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "marcar_interesse",
            "description": (
                "Marca que o lead demonstrou INTERESSE COMERCIAL CLARO nesta conversa "
                "(ex: perguntou preço/condições, pediu detalhes para comprar, demonstrou intenção real de avançar). "
                "NÃO use para resposta educada, 'ok', 'obrigado', 'vou pensar', saudação, ou curiosidade vaga. "
                "Só o interesse genuíno habilita o follow-up automático."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "nivel": {
                        "type": "string",
                        "enum": ["morno", "quente"],
                        "description": "Nivel de interesse do lead",
                    },
                    "motivo": {
                        "type": "string",
                        "description": "Breve descricao do sinal de interesse observado",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retomar_contato_vendedor",
            "description": (
                "Reconecta ao vendedor Joao Bras um lead que JA teve atendimento com ele no passado e esfriou "
                "(cenario de reativacao). USE somente apos as 3 etapas: "
                "(1) voce investigou por que o atendimento anterior nao avancou e contornou a objecao; "
                "(2) o lead demonstrou que quer retomar; "
                "(3) voce perguntou EXPLICITAMENTE se pode encaminha-lo de novo ao Joao e o lead respondeu SIM. "
                "Esta ferramenta dispara uma mensagem pelo numero do Joao para o lead — AGORA se em horario comercial "
                "(09h-16h, dias uteis), senao AGENDA para o proximo dia util — e ENCERRA a conversa automatica (desativa a IA). "
                "O retorno informa se o disparo foi AGORA ou AGENDADO: use isso para se despedir corretamente "
                "('o Joao acabou de te chamar' vs 'o Joao vai te chamar amanha de manha'). "
                "Apos chama-la, escreva APENAS a mensagem de despedida e NAO envie mais nada. "
                "NAO use sem o SIM explicito do lead. Para handoff de lead novo/qualificado, use encaminhar_humano."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "motivo": {
                        "type": "string",
                        "description": "Breve resumo do que esfriou o atendimento anterior e do que o lead quer retomar",
                    }
                },
                "required": [],
            },
        },
    },
]


def get_tools_for_stage(stage: str) -> list[dict]:
    """Return tools available for a given stage."""
    stage_tools = {
        "secretaria":    ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout", "marcar_interesse", "retomar_contato_vendedor"],
        "atacado":       ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout", "enviar_fotos", "enviar_foto_produto", "marcar_interesse", "retomar_contato_vendedor"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout", "enviar_fotos", "enviar_foto_produto", "marcar_interesse", "retomar_contato_vendedor"],
        "exportacao":    ["salvar_nome", "mudar_stage", "encaminhar_humano", "registrar_optout", "marcar_interesse", "retomar_contato_vendedor"],
        "consumo":       ["salvar_nome", "mudar_stage", "registrar_optout", "marcar_interesse"],
    }
    allowed = stage_tools.get(stage, ["salvar_nome"])
    return [t for t in TOOLS_SCHEMA if t["function"]["name"] in allowed]


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    lead_id: str,
    phone: str,
    conversation_id: str = "",
) -> str:
    """Execute a tool call and return a result string for the AI."""
    logger.info(f"Executing tool {tool_name} with args {args} for lead {lead_id}")

    if tool_name == "salvar_nome":
        update_lead(lead_id, name=args["name"])
        return f"Nome salvo: {args['name']}"

    elif tool_name == "mudar_stage":
        new_stage = args["stage"]
        if conversation_id:
            update_conversation(conversation_id, stage=new_stage)
        update_lead(lead_id, stage=new_stage)
        save_message(lead_id, "system", f"stage alterado para: {new_stage}", conversation_id=conversation_id)
        return f"Stage alterado para: {new_stage}"

    elif tool_name == "encaminhar_humano":
        motivo = args.get("motivo", "lead qualificado")
        vendedor = args.get("vendedor", "Vendedor")
        try:
            update_lead(lead_id, status="converted", human_control=True, ai_enabled=False)
        except Exception as exc:
            logger.error(
                "CRITICAL: encaminhar_humano failed to set ai_enabled=False for lead %s: %s",
                lead_id, exc, exc_info=True,
            )
            try:
                save_message(
                    lead_id, "system",
                    f"[encaminhar_humano][ERRO] nao foi possivel desativar AI: {exc}",
                    conversation_id=conversation_id,
                )
            except Exception:
                pass
            return f"CRITICAL: erro ao encaminhar para {vendedor} — humano precisa verificar lead manualmente"
        try:
            lead = get_lead(lead_id)
            lead_stage = lead.get("stage") if lead else None
            create_deal(lead_id, title=f"{vendedor} - {motivo}", category=lead_stage)
        except Exception as exc:
            logger.error(
                "encaminhar_humano failed to create deal for lead %s: %s",
                lead_id, exc, exc_info=True,
            )
        save_message(lead_id, "system", f"[encaminhar_humano] Lead encaminhado para {vendedor}: {motivo}", conversation_id=conversation_id)
        # Gera e armazena resumo estruturado da qualificação
        try:
            from app.agent.summary import generate_qualification_summary
            from app.agent.orchestrator import get_ai_client, DEFAULT_MODEL
            from app.db.supabase import get_supabase
            conv_history = get_conversation_history(conversation_id, limit=100)
            fresh_lead = get_lead(lead_id) or {}
            _model = DEFAULT_MODEL
            _handoff_at = datetime.now(_TZ_BR).strftime("%d/%m/%Y %H:%M")
            summary_text = await generate_qualification_summary(
                conv_history, fresh_lead, get_ai_client(_model), _model,
                motivo=motivo,
                handoff_at=_handoff_at,
            )
            _sb = get_supabase()
            _sb.table("lead_notes").insert({
                "lead_id": lead_id,
                "author": "qualificação-ia",
                "content": summary_text,
            }).execute()
            existing_meta = dict(fresh_lead.get("metadata") or {})
            existing_meta["handoff_summary"] = summary_text
            update_lead(lead_id, metadata=existing_meta)
            logger.info("encaminhar_humano: resumo de qualificação salvo para lead %s", lead_id)
        except Exception as _exc:
            logger.error(
                "encaminhar_humano: falha ao gerar/salvar resumo para lead %s: %s",
                lead_id, _exc, exc_info=True,
            )
        channel = get_channel_for_lead(lead_id)
        if channel:
            try:
                send_result = await get_provider(channel).send_text(phone, _HANDOFF_MSG)
                save_message(lead_id, "assistant", _HANDOFF_MSG, sent_by="handoff", conversation_id=conversation_id, wamid=extract_wamid(send_result))
            except Exception as exc:
                logger.error(
                    "encaminhar_humano: falha ao enviar mensagem de handoff para lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
            try:
                schedule_handoff_rescue(
                    lead_id=lead_id,
                    lead_phone=phone,
                    conversation_id=conversation_id,
                    channel_id=channel["id"],
                    lead_name=(lead.get("name") or "") if lead else "",
                )
            except Exception as exc:
                logger.error(
                    "encaminhar_humano: falha ao agendar rescue job para lead %s: %s",
                    lead_id, exc, exc_info=True,
                )
        else:
            logger.warning(
                "encaminhar_humano: nenhum canal ativo para lead %s — mensagem de handoff e rescue job ignorados",
                lead_id,
            )
        return f"Lead encaminhado para {vendedor}"

    elif tool_name == "registrar_optout":
        motivo = args.get("motivo", "opt-out solicitado pelo lead")
        try:
            update_lead(lead_id, ai_enabled=False)
        except Exception as exc:
            logger.error("registrar_optout: falha ao desativar AI para lead %s: %s", lead_id, exc, exc_info=True)
            return f"ERRO ao registrar opt-out: {exc}"
        apply_optout_side_effects(lead_id, phone, reason="optout")
        save_message(
            lead_id, "system",
            f"[registrar_optout] lead solicitou opt-out: {motivo}",
            conversation_id=conversation_id,
        )
        logger.info("registrar_optout: ai_enabled=False para lead %s — motivo: %s", lead_id, motivo)
        return "Opt-out registrado."

    elif tool_name == "enviar_fotos":
        history = get_history(lead_id, limit=100)
        system_messages = [m for m in history if m.get("role") == "system"]
        logger.info(
            "enviar_fotos dedup check: %d system messages no histórico para lead %s",
            len(system_messages), lead_id
        )
        if any("[enviar_fotos]" in m.get("content", "") for m in system_messages):
            logger.info("enviar_fotos: fotos ja enviadas anteriormente para lead %s — reenviando por solicitacao do cliente", lead_id)

        categoria = args["categoria"]
        photos_dir = Path(__file__).parent.parent / "photos" / categoria
        if not photos_dir.exists():
            return f"Categoria {categoria} nao encontrada"

        photos = sorted(photos_dir.glob("foto_*.*"))
        if not photos:
            return f"Nenhuma foto encontrada para {categoria}"

        captions = PHOTO_CAPTIONS.get(categoria, {})

        # Queue photos for deferred dispatch: processor sends them AFTER the text
        # response so the chronological order in WhatsApp is: text first, photos second.
        queue = _deferred_media.setdefault(conversation_id, [])
        for photo in photos:
            b64 = base64.b64encode(photo.read_bytes()).decode()
            mimetype = "image/png" if photo.suffix == ".png" else "image/jpeg"
            stem = photo.stem
            caption = captions.get(stem, "")
            queue.append({"b64": b64, "mimetype": mimetype, "caption": caption})

        save_message(lead_id, "system", f"[enviar_fotos] Fotos de {categoria} enviadas ({len(photos)}/{len(photos)})", conversation_id=conversation_id)
        return f"{len(photos)} fotos de {categoria} enfileiradas para envio após o texto"

    elif tool_name == "enviar_foto_produto":
        categoria = args["categoria"]
        produto = args["produto"].lower().strip()

        history = get_history(lead_id, limit=100)
        marker = f"[enviar_foto_produto] Foto de {produto}"
        if any(marker in m.get("content", "") for m in history if m.get("role") == "system"):
            return f"foto de {produto} ja enviada nesta conversa — nao reenviar"

        cat_map = PRODUTO_PHOTO_MAP.get(categoria, {})
        entry = cat_map.get(produto)
        if not entry:
            return f"produto '{produto}' nao encontrado na categoria {categoria}"

        photos_dir = Path(__file__).parent.parent / "photos" / categoria
        stem = Path(entry["file"]).stem  # e.g. "foto_1"
        matches = list(photos_dir.glob(f"{stem}.*"))
        if not matches:
            return f"foto do produto '{produto}' nao encontrada"
        photo_path = matches[0]

        b64 = base64.b64encode(photo_path.read_bytes()).decode()
        mimetype = "image/png" if photo_path.suffix == ".png" else "image/jpeg"

        # Queue for deferred dispatch so text explanation arrives before the photo.
        _deferred_media.setdefault(conversation_id, []).append(
            {"b64": b64, "mimetype": mimetype, "caption": entry["caption"]}
        )
        save_message(lead_id, "system", f"[enviar_foto_produto] Foto de {produto} enviada", conversation_id=conversation_id)
        return f"foto de {produto} enfileirada para envio após o texto"

    elif tool_name == "marcar_interesse":
        nivel = args.get("nivel", "morno")
        motivo = args.get("motivo", "")
        if conversation_id:
            _interest_marked[conversation_id] = {"nivel": nivel, "motivo": motivo}
        logger.info(
            "marcar_interesse: nivel=%s motivo=%r lead=%s conv=%s",
            nivel, motivo, lead_id, conversation_id,
        )
        return f"Interesse registrado: {nivel}"

    elif tool_name == "retomar_contato_vendedor":
        return await _retomar_contato_vendedor(args, lead_id, phone, conversation_id)

    return f"Tool {tool_name} nao reconhecida"


def _format_next_dispatch(fire_at: datetime | None) -> str:
    """Frase natural (pt-BR) para quando o João vai chamar o lead, a partir do fire_at agendado."""
    if fire_at is None:
        return "o proximo horario comercial"
    local = fire_at.astimezone(_TZ_BR)
    today_local = datetime.now(_TZ_BR).date()
    delta_days = (local.date() - today_local).days
    hora = local.strftime("%Hh%M") if local.minute else local.strftime("%Hh")
    if delta_days <= 0:
        return f"hoje de manha (por volta das {hora})"
    if delta_days == 1:
        return f"amanha de manha (por volta das {hora})"
    return f"no proximo dia util ({local.strftime('%d/%m')} de manha, por volta das {hora})"


async def _retomar_contato_vendedor(
    args: dict[str, Any], lead_id: str, phone: str, conversation_id: str
) -> str:
    """Reabordagem de lead que esfriou apos handoff anterior com o Joao Bras.

    Efeitos (na ordem):
      (c) Desativa a IA imediatamente (ai_enabled=False, human_control=True) — a Valeria para de responder.
      (a) Dispara o template do Joao para o lead AGORA se dentro do horario comercial
          (09h-16h, dias uteis, America/Sao_Paulo); caso contrario, agenda para o
          proximo horario comercial valido (job handoff_rescue).
      (b) Retorna uma string instruindo a Valeria a se despedir conforme o disparo
          tenha sido imediato ou agendado.
    """
    from app.follow_up.service import is_within_business_window
    from app.follow_up.scheduler import send_joao_handoff_template

    motivo = args.get("motivo", "lead pediu para retomar o contato com o vendedor")
    lead = get_lead(lead_id) or {}
    lead_name = lead.get("name") or ""

    # (c) Desativa a IA imediatamente — a partir daqui a Valeria nao responde mais.
    try:
        update_lead(lead_id, ai_enabled=False, human_control=True, status="converted")
    except Exception as exc:
        logger.error(
            "CRITICAL: retomar_contato_vendedor falhou ao desativar IA para lead %s: %s",
            lead_id, exc, exc_info=True,
        )
        return (
            "CRITICAL: erro ao processar a retomada — nao foi possivel desativar a IA. "
            "Peca desculpas brevemente e diga que um vendedor vai assumir; um humano precisa verificar manualmente."
        )

    # Visibilidade para o time comercial: registra o retorno do lead como deal.
    try:
        create_deal(lead_id, title=f"Joao (retomada) - {motivo}", category=lead.get("stage"))
    except Exception as exc:
        logger.error(
            "retomar_contato_vendedor: falha ao criar deal para lead %s: %s", lead_id, exc, exc_info=True
        )

    now = datetime.now(timezone.utc)

    # (a) Dentro do horario comercial: dispara AGORA, sincrono.
    if is_within_business_window(now):
        sent = await send_joao_handoff_template(phone, lead_name)
        if sent:
            save_message(
                lead_id, "system",
                f"[retomar_contato_vendedor] Joao disparou AGORA para o lead — {motivo}",
                conversation_id=conversation_id,
            )
            return (
                "DISPARO REALIZADO AGORA. O Joao acabou de enviar uma mensagem para o lead aqui no WhatsApp. "
                "Despeca-se em UMA mensagem avisando que o Joao ACABOU DE CHAMAR o lead e que e so responder a ele por aqui. "
                "NAO envie mais nenhuma mensagem depois desta."
            )
        # Falha no disparo imediato → reagenda como rede de seguranca (proximo tick do worker).
        fire_at = _safe_schedule_reengage(lead_id, phone, conversation_id, lead_name)
        save_message(
            lead_id, "system",
            f"[retomar_contato_vendedor] disparo imediato falhou — reagendado — {motivo}",
            conversation_id=conversation_id,
        )
        return (
            "DISPARO AGENDADO. Houve um contratempo no envio imediato, mas o Joao vai chamar o lead em instantes. "
            "Despeca-se em UMA mensagem avisando que o Joao vai chamar o lead em breve aqui no WhatsApp. "
            "NAO envie mais nenhuma mensagem depois desta."
        )

    # (a) Fora do horario comercial: agenda para o proximo dia util as 09h.
    fire_at = _safe_schedule_reengage(lead_id, phone, conversation_id, lead_name)
    save_message(
        lead_id, "system",
        f"[retomar_contato_vendedor] disparo agendado fora do horario comercial — {motivo}",
        conversation_id=conversation_id,
    )
    when_label = _format_next_dispatch(fire_at)
    return (
        f"DISPARO AGENDADO para {when_label}. Estamos fora do horario comercial (09h-16h em dias uteis). "
        f"Despeca-se em UMA mensagem avisando que o Joao vai chamar o lead {when_label}, "
        "pedindo pra ele ficar de olho no WhatsApp. "
        "NAO envie mais nenhuma mensagem depois desta."
    )


def _safe_schedule_reengage(
    lead_id: str, phone: str, conversation_id: str, lead_name: str
) -> "datetime | None":
    """Agenda o disparo do Joao via job handoff_rescue (delay 0 → clampa p/ janela comercial).

    Retorna o fire_at agendado, ou None se nao houver canal ativo ou o agendamento falhar.
    """
    from app.follow_up.service import schedule_handoff_rescue

    channel = get_channel_for_lead(lead_id)
    if not channel:
        logger.warning(
            "retomar_contato_vendedor: nenhum canal ativo para lead %s — agendamento ignorado", lead_id
        )
        return None
    try:
        return schedule_handoff_rescue(
            lead_id=lead_id,
            lead_phone=phone,
            conversation_id=conversation_id,
            channel_id=channel["id"],
            delay_minutes=0,
            lead_name=lead_name,
        )
    except Exception as exc:
        logger.error(
            "retomar_contato_vendedor: falha ao agendar disparo para lead %s: %s",
            lead_id, exc, exc_info=True,
        )
        return None
