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


def test_atacado_prompt_fardo_escala_joao_bras():
    """Quando lead pede preço de fardo, prompt deve obrigar escalação para João Brás."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    assert "REGRA ABSOLUTA" in ATACADO_PROMPT and "fardo" in ATACADO_PROMPT.lower(), (
        "Prompt atacado não tem REGRA ABSOLUTA para fardo"
    )
    assert "NAO cite preco por unidade" in ATACADO_PROMPT or \
           "NAO sao precos de fardo" in ATACADO_PROMPT, (
        "Prompt atacado não instrui que preços unitários ≠ preços de fardo"
    )


def test_consumo_prompt_anti_loop():
    """Prompt consumo deve ter regra anti-loop após link enviado."""
    from app.agent.prompts.valeria_inbound.consumo import CONSUMO_PROMPT
    assert "NAO REPITA O LINK" in CONSUMO_PROMPT or "NAO repita o link" in CONSUMO_PROMPT, (
        "Prompt consumo não contém regra anti-repetição de link"
    )
    assert "PERGUNTA DIRETA" in CONSUMO_PROMPT or "pergunta direta" in CONSUMO_PROMPT.lower(), (
        "Prompt consumo não contém regra de pergunta direta pós-link"
    )
    assert "SEM RETOMADA" in CONSUMO_PROMPT or "retomada" in CONSUMO_PROMPT.lower(), (
        "Prompt consumo não contém regra de sem retomada"
    )


def test_base_prompt_silencio_pos_handoff():
    """Base prompt deve ter regra de silêncio após encaminhar_humano."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime, timezone, timedelta
    prompt = build_base_prompt(
        lead_name=None, lead_company=None,
        now=datetime.now(timezone(timedelta(hours=-3)))
    )
    assert "ULTIMO TURNO" in prompt or "ultimo turno" in prompt.lower(), (
        "Base prompt não contém regra de silêncio pós-handoff (ULTIMO TURNO)"
    )
    assert "NAO pergunte nome" in prompt or "nao pergunte nome" in prompt.lower(), (
        "Base prompt não proíbe perguntar nome após handoff"
    )


def test_private_label_proibe_nome_apos_handoff():
    """Prompt private_label deve proibir perguntar nome após handoff."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "PROIBIDO na mensagem de handoff" in PRIVATE_LABEL_PROMPT, (
        "Prompt private_label não contém proibição explícita na mensagem de handoff"
    )


def test_private_label_calcula_preco_por_quantidade():
    """Prompt private_label deve ter regra de cálculo de preço por quantidade."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "CALCULE" in PRIVATE_LABEL_PROMPT, (
        "Prompt private_label não contém instrução CALCULE por quantidade"
    )
    assert "NUNCA diga que nao sabe calcular" in PRIVATE_LABEL_PROMPT, (
        "Prompt private_label não proíbe dizer que não sabe calcular"
    )


def test_atacado_fardo_qualifica_antes_de_escalar():
    """Prompt atacado deve pedir produto antes de escalar fardo quando não há qualificação prévia."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    assert "SEM QUALIFICACAO PREVIA" in ATACADO_PROMPT, (
        "Prompt atacado não contém exceção SEM QUALIFICACAO PREVIA para fardo"
    )
    assert "qual produto voce precisa" in ATACADO_PROMPT, (
        "Prompt atacado não pergunta qual produto antes de escalar fardo sem contexto"
    )


def test_base_prompt_espelha_saudacao_lead():
    """Base prompt deve ter regra de espelhar a saudação do lead."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime, timezone, timedelta
    prompt = build_base_prompt(
        lead_name=None, lead_company=None,
        now=datetime.now(timezone(timedelta(hours=-3)))
    )
    assert "SAUDACAO DO LEAD" in prompt, (
        "Base prompt não contém regra SAUDACAO DO LEAD"
    )
    assert "ESPELHE" in prompt, (
        "Base prompt não contém instrução ESPELHE para saudação do lead"
    )
