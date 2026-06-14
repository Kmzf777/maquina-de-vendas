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
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert "pergunta direta" in prompt_lower, (
        "Prompt private_label não contém a regra de pergunta direta"
    )
    assert "antes de qualquer" in prompt_lower or "responda a pergunta primeiro" in prompt_lower, (
        "Regra de prioridade ausente"
    )


def test_atacado_prompt_responde_pergunta_direta():
    """A regra de perguntas diretas deve estar no prompt de atacado."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    assert "pergunta direta" in prompt_lower, (
        "Prompt atacado não contém a regra de pergunta direta"
    )
    # Regra deve aparecer antes das etapas
    idx_regra = prompt_lower.find("pergunta direta")
    for marker in ["etapa 1", "## etapa", "fluxo:"]:
        idx_marker = prompt_lower.find(marker)
        if idx_marker != -1:
            assert idx_regra < idx_marker, (
                f"Regra de pergunta direta deve aparecer antes de '{marker}' no prompt"
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
    prompt_lower = ATACADO_PROMPT.lower()
    assert "fardo" in prompt_lower, (
        "Prompt atacado não contém instrução para fardo"
    )
    assert "nao cite preco por unidade" in prompt_lower or \
           "nao sao precos de fardo" in prompt_lower or \
           "preco de fardo" in prompt_lower, (
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
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert ("proibido na mensagem de handoff" in prompt_lower or
            "proibido" in prompt_lower and "handoff" in prompt_lower), (
        "Prompt private_label não contém proibição explícita na mensagem de handoff"
    )


def test_private_label_calcula_preco_por_quantidade():
    """Prompt private_label deve ter regra de cálculo de preço por quantidade."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    assert "calcule" in prompt_lower or "calcul" in prompt_lower, (
        "Prompt private_label não contém instrução de cálculo por quantidade"
    )
    assert "nao sabe calcular" in prompt_lower or "nao diga que nao sabe" in prompt_lower, (
        "Prompt private_label não proíbe dizer que não sabe calcular"
    )


def test_atacado_fardo_qualifica_antes_de_escalar():
    """Prompt atacado deve pedir produto antes de escalar fardo quando não há qualificação prévia."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    assert "qualificacao previa" in prompt_lower or "sem qualificacao" in prompt_lower or \
           "nao ha qualificacao" in prompt_lower, (
        "Prompt atacado não contém exceção de qualificação prévia para fardo"
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


def test_atacado_inbound_handoff_instrui_encaminhar_humano():
    """Seção de handoff do atacado inbound deve instruir encaminhar_humano diretamente."""
    from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT
    prompt_lower = ATACADO_PROMPT.lower()
    # Encontra a seção de handoff (case-insensitive)
    for marker in ["## etapa de handoff para fechamento", "etapa de handoff", "handoff para fechamento"]:
        idx = prompt_lower.find(marker)
        if idx != -1:
            handoff_section = ATACADO_PROMPT[idx:]
            assert "encaminhar_humano" in handoff_section
            return
    assert False, "Seção de handoff não encontrada no prompt atacado"


def test_private_label_inbound_etapa3_responde_todas_perguntas():
    """Etapa 3 do private_label não deve limitar respostas a 1 pergunta antes do handoff."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    prompt_lower = PRIVATE_LABEL_PROMPT.lower()
    # O texto antigo proibia responder mais de 1 pergunta antes do handoff
    assert "no maximo 1 pergunta de detalhe" not in prompt_lower
    # Deve instruir a responder todas as perguntas
    assert ("responda quantas" in prompt_lower or
            "todas as perguntas" in prompt_lower or
            "perguntas diretas" in prompt_lower), (
        "Prompt private_label não instrui a responder perguntas diretas antes do handoff"
    )



def test_base_prompt_regra_nome_moderacao_forte():
    """base_prompt deve conter regra explícita de frequência máxima de uso do nome."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    prompt = build_base_prompt("Débora", None, datetime.now())
    assert "4-5" in prompt or "cinco" in prompt or "5 turnos" in prompt, (
        "Regra de frequência de nome (máx 1 vez a cada 4-5 turnos) não encontrada no prompt."
    )
    assert "consecutiv" in prompt.lower(), (
        "Regra proibindo uso do nome em mensagens consecutivas não encontrada no prompt."
    )


def test_base_prompt_nome_no_antipadrao():
    """ANTI-PADRÕES deve listar repetição de nome como proibido."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    prompt = build_base_prompt("Débora", None, datetime.now())
    antipadrao_section = prompt.split("ANTI-PADROES")[1].split("COMO VOCE FALA")[0] if "ANTI-PADROES" in prompt else ""
    assert "nome" in antipadrao_section.lower(), (
        "ANTI-PADROES não menciona proibição de repetição do nome do lead."
    )


def test_base_prompt_checklist_verifica_nome():
    """CHECKLIST deve incluir verificação de uso excessivo do nome."""
    from app.agent.prompts.base import build_base_prompt
    from datetime import datetime
    prompt = build_base_prompt("Débora", None, datetime.now())
    checklist_section = prompt.split("CHECKLIST ANTES DE RESPONDER")[1] if "CHECKLIST ANTES DE RESPONDER" in prompt else ""
    assert "nome" in checklist_section.lower(), (
        "CHECKLIST não inclui verificação de uso do nome do lead."
    )


def test_private_label_inbound_preco_vem_do_csv():
    """Preços no prompt inbound devem vir do CSV, não hardcoded."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "R$26,70" in PRIVATE_LABEL_PROMPT, "250g com embalagem (CSV) ausente no inbound"
    assert "R$48,70" in PRIVATE_LABEL_PROMPT, "500g com embalagem (CSV) ausente no inbound"
    assert "R$23,90" not in PRIVATE_LABEL_PROMPT, "Preço antigo 250g ainda presente no inbound"
    assert "R$44,90" not in PRIVATE_LABEL_PROMPT, "Preço antigo 500g ainda presente no inbound"


def test_private_label_inbound_sem_produtos_removidos():
    """Drip Coffee e Cápsulas Nespresso não devem estar no prompt inbound."""
    from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
    assert "Drip Coffee" not in PRIVATE_LABEL_PROMPT
    assert "Capsulas Nespresso" not in PRIVATE_LABEL_PROMPT


def test_private_label_outbound_preco_vem_do_csv():
    """Preços no prompt outbound devem vir do CSV."""
    from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT
    assert "R$26,70" in PRIVATE_LABEL_PROMPT, "250g com embalagem (CSV) ausente no outbound"
    assert "R$48,70" in PRIVATE_LABEL_PROMPT, "500g com embalagem (CSV) ausente no outbound"
    assert "R$23,90" not in PRIVATE_LABEL_PROMPT, "Preço antigo 250g ainda presente no outbound"
    assert "R$44,90" not in PRIVATE_LABEL_PROMPT, "Preço antigo 500g ainda presente no outbound"


def test_private_label_outbound_sem_produtos_removidos():
    """Drip Coffee e Cápsulas Nespresso não devem estar no prompt outbound."""
    from app.agent.prompts.valeria_outbound.private_label import PRIVATE_LABEL_PROMPT
    assert "Drip Coffee" not in PRIVATE_LABEL_PROMPT
    assert "Capsulas Nespresso" not in PRIVATE_LABEL_PROMPT


def test_outbound_secretaria_trata_abertura_template():
    from app.agent.prompts import get_stage_prompts
    p = get_stage_prompts("valeria_outbound")["secretaria"]
    # seção dedicada a responder o lead após o template "atualizando cadastro / Falo com X?"
    assert "## RESPOSTA À ABERTURA" in p
    assert "cadastro" in p.lower()
