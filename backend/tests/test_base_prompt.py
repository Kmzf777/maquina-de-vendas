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
