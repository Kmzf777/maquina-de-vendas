import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

from app.leads.service import update_lead, save_message, create_deal
from app.whatsapp.client import send_text, send_image_base64

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
            "description": "Transfere o lead para outro stage quando a necessidade for identificada. Usar de forma silenciosa, sem avisar o cliente.",
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
            "description": "Encaminha o lead qualificado para um vendedor humano continuar o atendimento",
            "parameters": {
                "type": "object",
                "properties": {
                    "vendedor": {"type": "string", "description": "Nome do vendedor"},
                    "motivo": {"type": "string", "description": "Motivo do encaminhamento"},
                },
                "required": ["vendedor", "motivo"],
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
        "secretaria": ["salvar_nome", "mudar_stage"],
        "atacado": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"],
        "exportacao": ["salvar_nome", "mudar_stage", "encaminhar_humano"],
        "consumo": ["salvar_nome"],
    }
    allowed = stage_tools.get(stage, ["salvar_nome"])
    return [t for t in TOOLS_SCHEMA if t["function"]["name"] in allowed]


async def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    lead_id: str,
    phone: str,
) -> str:
    """Execute a tool call and return a result string for the AI."""
    logger.info(f"Executing tool {tool_name} with args {args} for lead {lead_id}")

    if tool_name == "salvar_nome":
        update_lead(lead_id, name=args["name"])
        return f"Nome salvo: {args['name']}"

    elif tool_name == "mudar_stage":
        new_stage = args["stage"]
        update_lead(lead_id, stage=new_stage)
        return f"Stage alterado para: {new_stage}"

    elif tool_name == "encaminhar_humano":
        update_lead(lead_id, status="converted", human_control=True)
        create_deal(lead_id, title=f"{args.get('vendedor', 'Vendedor')} - {args['motivo']}")
        save_message(lead_id, "system", f"Lead encaminhado para {args['vendedor']}: {args['motivo']}")
        return f"Lead encaminhado para {args['vendedor']}"

    elif tool_name == "enviar_fotos":
        categoria = args["categoria"]
        photos_dir = Path(__file__).parent.parent / "photos" / categoria
        if not photos_dir.exists():
            return f"Categoria {categoria} nao encontrada"

        photos = sorted(photos_dir.glob("foto_*.*"))
        if not photos:
            return f"Nenhuma foto encontrada para {categoria}"

        captions = PHOTO_CAPTIONS.get(categoria, {})
        sent = 0
        for photo in photos:
            b64 = base64.b64encode(photo.read_bytes()).decode()
            mimetype = "image/png" if photo.suffix == ".png" else "image/jpeg"
            stem = photo.stem  # e.g. "foto_1"
            caption = captions.get(stem, "")
            try:
                await send_image_base64(phone, b64, mimetype, caption=caption)
                sent += 1
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning(f"Failed to send photo {photo.name}: {e}")

        save_message(lead_id, "system", f"Fotos de {categoria} enviadas ({sent}/{len(photos)})")
        return f"{sent} fotos de {categoria} enviadas ao lead"

    elif tool_name == "enviar_foto_produto":
        categoria = args["categoria"]
        produto = args["produto"].lower().strip()
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
        try:
            await send_image_base64(phone, b64, mimetype, caption=entry["caption"])
            save_message(lead_id, "system", f"Foto de {produto} enviada")
            return f"foto de {produto} enviada ao lead"
        except Exception as e:
            logger.warning(f"Failed to send product photo {produto}: {e}")
            return f"erro ao enviar foto de {produto}"

    return f"Tool {tool_name} nao reconhecida"
