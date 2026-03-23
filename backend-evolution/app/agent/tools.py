import logging
from typing import Any

from app.leads.service import update_lead, save_message
from app.whatsapp.client import send_text

logger = logging.getLogger(__name__)

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
]


def get_tools_for_stage(stage: str) -> list[dict]:
    """Return tools available for a given stage."""
    stage_tools = {
        "secretaria": ["salvar_nome", "mudar_stage"],
        "atacado": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
        "private_label": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
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
        # TODO: implement actual human handoff (e.g., notify via WhatsApp group or webhook)
        update_lead(lead_id, status="converted")
        save_message(lead_id, "system", f"Lead encaminhado para {args['vendedor']}: {args['motivo']}")
        return f"Lead encaminhado para {args['vendedor']}"

    elif tool_name == "enviar_fotos":
        # TODO: implement photo sending with actual image URLs
        categoria = args["categoria"]
        save_message(lead_id, "system", f"Fotos de {categoria} enviadas")
        return f"Fotos de {categoria} enviadas ao lead"

    return f"Tool {tool_name} nao reconhecida"
