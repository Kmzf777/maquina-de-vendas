"""Sanitizador determinístico de vazamento de function-call em código — lead 5575992317829.

Auditoria 2026-06-25: o gemini-2.5-flash (via endpoint OpenAI-compat) ocasionalmente
serializa o function-call na sua forma de CÓDIGO nativa DENTRO de message.content (em vez
de tool_calls), vazando texto cru pro cliente, ex.:
    <tool_code> print(enviar_fotos("private_label")) </tool_code>
    <tool_code> print(default_api.encaminhar_humano(mensagem_despedida='...', motivo='...')) </tool_code>
Como tool_calls fica vazio, o orchestrator nunca executa a tool e manda o código ao lead.

_strip_leaked_tool_code é a rede de segurança: remove QUALQUER assinatura desse vazamento
do texto final, preservando o texto humano legítimo.
"""


def test_remove_tool_code_com_funcao_posicional():
    from app.agent.orchestrator import _strip_leaked_tool_code
    leak = '<tool_code> print(enviar_fotos("private_label")) </tool_code>'
    assert _strip_leaked_tool_code(leak) == ""


def test_remove_tool_code_com_default_api_e_kwargs():
    from app.agent.orchestrator import _strip_leaked_tool_code
    leak = (
        "<tool_code> print(default_api.encaminhar_humano("
        "mensagem_despedida='to deixando o contato do joão aqui embaixo', "
        "motivo='fotos nao enviadas')) </tool_code>"
    )
    assert _strip_leaked_tool_code(leak) == ""


def test_preserva_texto_humano_e_remove_so_o_codigo():
    """Caso real do lead: bolha humana + bolha de código no MESMO content.
    O texto humano sobrevive; só o código some."""
    from app.agent.orchestrator import _strip_leaked_tool_code
    mixed = (
        "eita, vou reenviar as fotos aqui\n\n"
        "<tool_code> print(default_api.enviar_fotos(categoria='private_label')) </tool_code>"
    )
    assert _strip_leaked_tool_code(mixed) == "eita, vou reenviar as fotos aqui"


def test_remove_chamada_crua_sem_tags():
    from app.agent.orchestrator import _strip_leaked_tool_code
    leak = "print(default_api.enviar_fotos(categoria='private_label'))"
    assert _strip_leaked_tool_code(leak) == ""


def test_remove_bloco_markdown_cercado_por_crases():
    from app.agent.orchestrator import _strip_leaked_tool_code
    leak = "```python\nprint(enviar_fotos(\"private_label\"))\n```"
    assert _strip_leaked_tool_code(leak) == ""


def test_nao_altera_texto_legitimo_com_parenteses():
    """Mensagem real de venda com parênteses/valores NÃO pode ser tocada."""
    from app.agent.orchestrator import _strip_leaked_tool_code
    legit = "o 250g fica por volta de R$25,70 a unidade (já com a sua logo)"
    assert _strip_leaked_tool_code(legit) == legit


def test_nao_altera_texto_legitimo_simples():
    from app.agent.orchestrator import _strip_leaked_tool_code
    legit = "criar sua marca do zero é o melhor investimento que você pode fazer nesse ramo"
    assert _strip_leaked_tool_code(legit) == legit


def test_string_vazia_passa_intacta():
    from app.agent.orchestrator import _strip_leaked_tool_code
    assert _strip_leaked_tool_code("") == ""
