"""Seed the default ValerIA agent profile from existing prompts."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db.supabase import get_supabase
from app.agent.prompts.secretaria import SECRETARIA_PROMPT
from app.agent.prompts.atacado import ATACADO_PROMPT
from app.agent.prompts.private_label import PRIVATE_LABEL_PROMPT
from app.agent.prompts.exportacao import EXPORTACAO_PROMPT
from app.agent.prompts.consumo import CONSUMO_PROMPT
from app.agent.prompts.base import build_base_prompt

from datetime import datetime, timezone, timedelta

TZ_BR = timezone(timedelta(hours=-3))
base_prompt = build_base_prompt(lead_name=None, lead_company=None, now=datetime.now(TZ_BR))

stages = {
    "secretaria": {
        "prompt": SECRETARIA_PROMPT,
        "model": "gpt-4.1",
        "tools": ["salvar_nome", "mudar_stage"],
    },
    "atacado": {
        "prompt": ATACADO_PROMPT,
        "model": "gpt-4.1",
        "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
    },
    "private_label": {
        "prompt": PRIVATE_LABEL_PROMPT,
        "model": "gpt-4.1",
        "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"],
    },
    "exportacao": {
        "prompt": EXPORTACAO_PROMPT,
        "model": "gpt-4.1-mini",
        "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano"],
    },
    "consumo": {
        "prompt": CONSUMO_PROMPT,
        "model": "gpt-4.1-mini",
        "tools": ["salvar_nome"],
    },
}

sb = get_supabase()
result = sb.table("agent_profiles").insert({
    "name": "ValerIA Cafe Canastra",
    "model": "gpt-4.1",
    "stages": stages,
    "base_prompt": base_prompt,
}).execute()

print(f"Created agent profile: {result.data[0]['id']}")
print("Now create a channel and assign this profile ID to it.")
