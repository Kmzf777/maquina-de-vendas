"""Regra 18 do prompt: adiamento morno NÃO é descarte (forense 11/07, caso Anderson).

"vou analisar e te chamo, muito obrigado" foi classificado como soft rejection —
lead morno perdeu follow-up e IA. A regra 18 ganha a categoria (C) ADIAMENTO MORNO
(responder curto + agendar_retorno quando houver prazo; nunca sem_interesse na 1ª
sinalização), "vou pensar e te falo" sai dos gatilhos de SOFT, e a despedida dos
descartes passa a ir no parâmetro mensagem_despedida (a tool envia — o texto do
turno é abortado pela trava B2).
"""
from datetime import datetime

from app.agent.prompts.base import build_base_prompt


def _prompt() -> str:
    return build_base_prompt(None, None, datetime(2026, 7, 11, 10, 0))


def test_regra18_tem_categoria_adiamento_morno():
    p = _prompt()
    assert "ADIAMENTO MORNO" in p
    assert "vou analisar e te chamo" in p
    assert "agendar_retorno" in p


def test_soft_gatilhos_nao_incluem_mais_vou_pensar():
    p = _prompt()
    soft_start = p.index("(B) SOFT REJECTION")
    soft_end = p.index("(C)", soft_start)
    soft_section = p[soft_start:soft_end]
    assert "vou pensar" not in soft_section
    assert "vou analisar" not in soft_section


def test_regra18_despedida_via_parametro_da_tool():
    p = _prompt()
    assert "mensagem_despedida" in p
    # A instrução antiga ("Escreva UMA mensagem de despedida ... Chame registrar_*")
    # não pode sobrar — ela mandava a despedida pro texto do turno, que é abortado.
    assert "Escreva UMA mensagem de despedida respeitosa" not in p
    assert "Escreva UMA mensagem de despedida cordial" not in p
