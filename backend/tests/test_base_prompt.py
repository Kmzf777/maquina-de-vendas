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
    # Verificar que a regra de prioridade está posicionada antes do roteiro
    idx_regra = PRIVATE_LABEL_PROMPT.find("REGRA PRIORITARIA")
    idx_etapa1 = PRIVATE_LABEL_PROMPT.find("ETAPA 1")
    if idx_etapa1 != -1:  # só valida se ETAPA 1 existe no prompt
        assert idx_regra < idx_etapa1, (
            "REGRA PRIORITARIA deve aparecer antes de ETAPA 1 no prompt"
        )


def test_atacado_prompt_responde_pergunta_direta():
    """A regra de perguntas diretas deve estar no prompt de atacado."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    assert "PERGUNTA DIRETA" in ATACADO_PROMPT, (
        "Prompt atacado não contém a regra PERGUNTA DIRETA"
    )
    # Verificar posicionamento: regra deve aparecer antes das ETAPAS/FLUXO
    idx_regra = ATACADO_PROMPT.find("PERGUNTA DIRETA")
    for marker in ["ETAPA 1", "ETAPA1", "## ETAPA", "FLUXO:"]:
        idx_marker = ATACADO_PROMPT.find(marker)
        if idx_marker != -1:
            assert idx_regra < idx_marker, (
                f"PERGUNTA DIRETA deve aparecer antes de '{marker}' no prompt"
            )
            break


def test_atacado_prompt_tem_circuit_breaker():
    """O prompt de atacado deve ter circuit breaker para evitar loop."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    tem_circuit_breaker = (
        "CIRCUIT BREAKER" in ATACADO_PROMPT or
        "circuit breaker" in ATACADO_PROMPT.lower()
    )
    assert tem_circuit_breaker, (
        "Prompt atacado não contém CIRCUIT BREAKER para evitar loop"
    )


def test_atacado_prompt_guardrail_registrar_pedido():
    """O prompt de atacado deve distinguir pedido confirmado de orçamento."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    tem_guardrail = (
        "orcamento" in prompt_lower or
        "orçamento" in prompt_lower or
        "nao registrar" in prompt_lower or
        "não registrar" in prompt_lower or
        "quanto fica" in prompt_lower
    )
    assert tem_guardrail, (
        "Prompt atacado não distingue pedido confirmado de orçamento/cotação"
    )
