"""Trilha B / B3 — critério de qualificação do handoff (prompt/descrição, SEM bloqueio).

A auditoria de 10/07 flagrou handoff prematuro: encaminhar_humano disparado após "SIM
aaaaaaaaa"/"👏👏👏👏" sem âncora, e oferta condicional executada sem resposta afirmativa.
A correção é de LINGUAGEM (descrição da tool + prompts), não de código com bloqueio — o
funil não pode engessar. Estes guardas garantem que o critério não seja silenciosamente
removido numa edição futura.
"""
from app.agent.prompts.valeria_inbound.private_label import PRIVATE_LABEL_PROMPT
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT


def _encaminhar_humano_description() -> str:
    from app.agent.tools import TOOL_DECLARATIONS
    decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "encaminhar_humano")
    return decl["description"]


def _mudar_stage_description() -> str:
    from app.agent.tools import TOOL_DECLARATIONS
    decl = next(d for d in TOOL_DECLARATIONS if d["name"] == "mudar_stage")
    return decl["description"]


def test_encaminhar_humano_caso1_exige_finalidade_e_sinal_ativo():
    desc = _encaminhar_humano_description()
    assert "finalidade concreta" in desc
    assert "sinal ativo de avanco" in desc
    # Emojis/monossílabos/simpatia não qualificam sozinhos.
    assert "NAO qualificam" in desc
    assert "qualificar_lead" in desc


def test_mudar_stage_exige_declaracao_explicita_e_correcao_para_reverter():
    desc = _mudar_stage_description()
    assert "declaracao EXPLICITA" in desc
    assert "audio truncado" in desc
    assert "na verdade eu quero" in desc


def test_prompts_espelham_criterio_e_oferta_condicional():
    for prompt in (PRIVATE_LABEL_PROMPT, ATACADO_PROMPT):
        assert "finalidade concreta" in prompt
        assert "NAO qualificam sozinhos" in prompt
        # Aguardar a resposta afirmativa antes de executar uma oferta condicional.
        assert "aguarde a resposta afirmativa" in prompt
        # Não engessa o circuit breaker existente.
        assert "circuit breaker" in prompt.lower()
