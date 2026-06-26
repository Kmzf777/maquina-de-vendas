"""Eixo 4 — Harmonização do cálculo de preço no private_label.

Contradição: private_label.py mandava multiplicar preço×qtd na mão ("NUNCA diga que não
sabe calcular"), mas base.py proíbe cálculo de cabeça e exige calcular_orcamento — e o stage
private_label nem expunha a tool. Unificado: tool disponível + prompt roteia por ela.
"""
from app.agent.tools import get_tools_for_stage
from app.agent.prompts import get_stage_prompts


def test_private_label_expoe_calcular_orcamento():
    names = [t["function"]["name"] for t in get_tools_for_stage("private_label")]
    assert "calcular_orcamento" in names


def test_private_label_prompt_nao_instrui_calculo_manual():
    pl = get_stage_prompts("valeria_outbound")["private_label"]
    low = pl.lower()
    assert "nunca diga que nao sabe calcular" not in low
    assert "calcular_orcamento" in low
