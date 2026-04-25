from datetime import datetime, timezone, timedelta
from app.agent.prompts.base import build_base_prompt

TZ_BR = timezone(timedelta(hours=-3))

def _now():
    return datetime.now(TZ_BR)


def test_base_prompt_no_context():
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now())
    assert "Valeria" in prompt
    assert "Cafe Canastra" in prompt
    assert "CONTEXTO DO LEAD" not in prompt


def test_base_prompt_with_name():
    prompt = build_base_prompt(lead_name="João", lead_company=None, now=_now())
    assert "João" in prompt


def test_base_prompt_with_lead_context_name():
    ctx = {"name": "Maria", "company": "Hotel Sol", "previous_stage": "atacado", "notes": "Quer 50kg/mês"}
    prompt = build_base_prompt(lead_name=None, lead_company=None, now=_now(), lead_context=ctx)
    assert "Maria" in prompt
    assert "Hotel Sol" in prompt
    assert "atacado" in prompt
    assert "50kg" in prompt


def test_base_prompt_lead_context_overrides_name():
    """lead_context.name takes priority over lead_name when both provided."""
    ctx = {"name": "Maria"}
    prompt = build_base_prompt(lead_name="João", lead_company=None, now=_now(), lead_context=ctx)
    assert "Maria" in prompt


def test_private_label_prompt_responde_pergunta_direta():
    """A regra de perguntas diretas deve estar no prompt de private_label."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "PERGUNTA DIRETA" in PRIVATE_LABEL_PROMPT, (
        "Prompt private_label não contém a regra PERGUNTA DIRETA"
    )
    assert "ANTES de qualquer" in PRIVATE_LABEL_PROMPT or \
           "antes de qualquer" in PRIVATE_LABEL_PROMPT or \
           "ANTES DE qualquer" in PRIVATE_LABEL_PROMPT, (
        "Regra de prioridade ausente"
    )
