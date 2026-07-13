# backend/app/agent/prompts/__init__.py
from app.agent.prompts.valeria_inbound.secretaria import SECRETARIA_PROMPT as _IN_SEC
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT as _IN_ATA
from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT as _IN_PL
from app.agent.prompts.valeria_inbound.exportacao import EXPORTACAO_PROMPT as _IN_EXP
from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT as _IN_CON

from app.agent.prompts.valeria_outbound.playbook import POSTURA_HUNTER
from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT as _OUT_SEC
from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT as _OUT_ATA
from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT as _OUT_PL
from app.agent.prompts.valeria_outbound.exportacao import EXPORTACAO_PROMPT as _OUT_EXP
from app.agent.prompts.valeria_outbound.consumo import CONSUMO_PROMPT as _OUT_CON


def _hunter(stage_prompt: str) -> str:
    """A lei de postura outbound abre TODO prompt de estagio do valeria_outbound.

    Vem antes do funil porque e regra de POSTURA (quem conduz), nao de roteiro — e
    porque precisa vencer a regra 26 do BASE_STATIC, escrita para o inbound.
    """
    return POSTURA_HUNTER + "\n" + stage_prompt


PROMPT_REGISTRY: dict[str, dict[str, str]] = {
    "valeria_inbound": {
        "secretaria": _IN_SEC,
        "atacado": _IN_ATA,
        "private_label": _IN_PL,
        "exportacao": _IN_EXP,
        "consumo": _IN_CON,
    },
    "valeria_outbound": {
        "secretaria": _hunter(_OUT_SEC),
        "atacado": _hunter(_OUT_ATA),
        "private_label": _hunter(_OUT_PL),
        "exportacao": _hunter(_OUT_EXP),
        "consumo": _hunter(_OUT_CON),
    },
}


def get_stage_prompts(prompt_key: str) -> dict[str, str]:
    """Return the stage prompt dict for the given prompt_key.
    Falls back to valeria_inbound if key is unknown.
    """
    return PROMPT_REGISTRY.get(prompt_key, PROMPT_REGISTRY["valeria_inbound"])
