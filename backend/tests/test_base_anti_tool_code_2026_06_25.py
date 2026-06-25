"""Guardrail anti-tool_code no prompt base — lead 5575992317829 (auditoria 2026-06-25).

A Valéria vazou o function-call como TEXTO/código (`<tool_code> print(default_api...) `)
em vez de usar o Function Calling nativo. Além da rede de segurança no código, o prompt
ganha uma PROIBIÇÃO ABSOLUTA explícita de emitir código/XML/pseudo-código, e a linguagem
que primava "imprimir na saída" (que induz o `print(...)`) foi reescrita.
"""
from datetime import datetime


def _p():
    from app.agent.prompts.base import build_base_prompt
    return build_base_prompt(None, None, datetime(2026, 6, 25, 15, 0))


def test_prompt_tem_proibicao_explicita_de_tool_code():
    low = _p().lower()
    assert "tool_code" in low
    # Proíbe blocos de código / pseudo-código / XML como resposta
    assert "proibido" in low
    assert ("bloco" in low and ("codigo" in low or "código" in low))


def test_prompt_exige_function_calling_nativo():
    low = _p().lower()
    assert "function calling" in low
    # Nunca escrever o nome da ferramenta/parametros no corpo do texto
    assert "nativo" in low


def test_prompt_nao_usa_linguagem_de_imprimir_na_saida():
    """A instrução 'Nunca imprima seu plano na saída final' primava o print(...).
    Reescrita para não usar o verbo 'imprimir' acoplado a 'saída'."""
    low = _p().lower()
    assert "nunca imprima seu plano na saida" not in low
    assert "nunca imprima seu plano na saída" not in low
