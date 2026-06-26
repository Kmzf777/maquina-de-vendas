"""Injeção do Dossiê (rolling_summary) no prompt via bloco <lead_memory>."""
from datetime import datetime


def _now():
    return datetime(2026, 6, 26, 14, 0, 0)


def test_lead_memory_block_emitted_when_rolling_summary_present():
    from app.agent.prompts.base import build_base_prompt

    dossie = "## DOSSIÊ DO LEAD\n* **Perfil / Empresa:** Cafeteria em BH"
    prompt = build_base_prompt(
        lead_name="Ana",
        lead_company=None,
        now=_now(),
        lead_context={"rolling_summary": dossie},
    )

    assert "<lead_memory>" in prompt
    assert "</lead_memory>" in prompt
    assert "Cafeteria em BH" in prompt


def test_lead_memory_block_absent_when_no_rolling_summary():
    from app.agent.prompts.base import build_base_prompt

    prompt = build_base_prompt(
        lead_name="Ana",
        lead_company=None,
        now=_now(),
        lead_context={"notes": "alguma nota"},
    )

    assert "<lead_memory>" not in prompt


def test_lead_memory_block_absent_when_no_context():
    from app.agent.prompts.base import build_base_prompt

    prompt = build_base_prompt(
        lead_name=None, lead_company=None, now=_now(), lead_context=None
    )

    assert "<lead_memory>" not in prompt
