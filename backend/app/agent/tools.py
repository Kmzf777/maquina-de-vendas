import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

from app.leads.service import update_lead, save_message, create_deal, get_lead, get_history
from app.conversations.service import update_conversation
from app.whatsapp.registry import get_provider
from app.channels.service import get_active_channel

logger = logging.getLogger(__name__)

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
]


def get_tools_for_stage(stage: str) -> list[dict]:
    """Return tools available for a given stage."""
    stage_tools = {
        "secretaria": ["salvar_nome", "mudar_stage", "encaminhar_humano"],
        "atacado": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"],
        "exportacao": ["salvar_nome", "mudar_stage", "encaminhar_humano"],
        "consumo": ["salvar_nome", "mudar_stage"],
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
            save_message(
                lead_id, "system",
                f"[encaminhar_humano][ERRO] nao foi possivel desativar AI: {exc}",
                conversation_id=conversation_id,
            )
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
        return f"Lead encaminhado para {vendedor}"

    elif tool_name == "enviar_fotos":
        history = get_history(lead_id, limit=100)
        system_messages = [m for m in history if m.get("role") == "system"]
        logger.info(
            "enviar_fotos dedup check: %d system messages no histórico para lead %s",
            len(system_messages), lead_id
        )
        if any("[enviar_fotos]" in m.get("content", "") for m in system_messages):
            logger.info("enviar_fotos: dedup ativado — fotos já enviadas para lead %s", lead_id)
            return "fotos ja enviadas nesta conversa — nao reenviar"

        categoria = args["categoria"]
        photos_dir = Path(__file__).parent.parent / "photos" / categoria
        if not photos_dir.exists():
            return f"Categoria {categoria} nao encontrada"

        photos = sorted(photos_dir.glob("foto_*.*"))
        if not photos:
            return f"Nenhuma foto encontrada para {categoria}"

        captions = PHOTO_CAPTIONS.get(categoria, {})
        channel = get_active_channel()
        if not channel:
            return "Nenhum canal ativo disponivel"
        provider = get_provider(channel)

        sent = 0
        for photo in photos:
            b64 = base64.b64encode(photo.read_bytes()).decode()
            mimetype = "image/png" if photo.suffix == ".png" else "image/jpeg"
            stem = photo.stem  # e.g. "foto_1"
            caption = captions.get(stem, "")
            try:
                await provider.send_image_base64(phone, b64, mimetype, caption=caption)
                sent += 1
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(
                    "Failed to send photo %s to %s: %s",
                    photo.name, phone, e, exc_info=True,
                )

        save_message(lead_id, "system", f"[enviar_fotos] Fotos de {categoria} enviadas ({sent}/{len(photos)})", conversation_id=conversation_id)
        return f"{sent} fotos de {categoria} enviadas ao lead"

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

        channel = get_active_channel()
        if not channel:
            return "Nenhum canal ativo disponivel"
        provider = get_provider(channel)

        b64 = base64.b64encode(photo_path.read_bytes()).decode()
        mimetype = "image/png" if photo_path.suffix == ".png" else "image/jpeg"
        try:
            await provider.send_image_base64(phone, b64, mimetype, caption=entry["caption"])
            save_message(lead_id, "system", f"[enviar_foto_produto] Foto de {produto} enviada", conversation_id=conversation_id)
            return f"foto de {produto} enviada ao lead"
        except Exception as e:
            logger.error(
                "Failed to send product photo '%s' to %s: %s",
                produto, phone, e, exc_info=True,
            )
            return f"erro ao enviar foto de {produto}"

    return f"Tool {tool_name} nao reconhecida"
