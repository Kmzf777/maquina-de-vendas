"""Vazamento de raciocinio interno (<scratchpad>) no texto enviado ao cliente.

Falha real 13/07 — lead 56958450295 (Alejandro, private_label): a REPEAT QUESTION GUARD
regenerou a resposta com um nudge de sistema ("Reescreva a resposta INTEIRA...") e o modelo
devolveu o plano em <scratchpad>...</scratchpad> DENTRO do content. O sanitizer so conhecia
<tool_code>/```/print(/default_api., entao o chain-of-thought passou, o splitter fatiou pelos
\\n\\n internos e o lead recebeu 3 bolhas de raciocinio — duas vezes na mesma conversa.
"""
from app.agent.orchestrator import _strip_leaked_reasoning, _sanitize_assistant_text


def test_remove_bloco_scratchpad_e_preserva_a_fala():
    raw = (
        "<scratchpad> O lead perguntou \"De onde vcs é?\".\n\n"
        "Vou reagir e fazer UMA pergunta nova.\n\n"
        "Nova pergunta: \"e qual o seu objetivo com a marca própria?\" </scratchpad> "
        "boa noite\n\na gente é da serra da canastra, em pratinha - MG"
    )
    out = _strip_leaked_reasoning(raw)
    assert "scratchpad" not in out.lower()
    assert "Vou reagir" not in out
    assert out.startswith("boa noite")
    assert "pratinha" in out


def test_scratchpad_orfao_sem_fechamento_corta_ate_o_fim():
    """MAX_TOKENS trunca o bloco: sem </scratchpad>, tudo depois da abertura e raciocinio."""
    raw = "<scratchpad> O lead enviou \"???\". Minha resposta anterior foi \"opa, desculpa\""
    assert _strip_leaked_reasoning(raw) == ""


def test_fechamento_orfao_descarta_o_raciocinio_anterior():
    """Se a abertura foi cortada e so sobrou </scratchpad>, o que vem ANTES e raciocinio."""
    raw = "Revisando as regras: nao repetir perguntas </scratchpad> opa, desculpa Alejandro"
    out = _strip_leaked_reasoning(raw)
    assert out == "opa, desculpa Alejandro"


def test_outras_tags_de_raciocinio():
    for tag in ("thinking", "thought", "reasoning", "plan", "internal_monologue"):
        raw = f"<{tag}>plano secreto</{tag}> oi, tudo bem?"
        assert _strip_leaked_reasoning(raw) == "oi, tudo bem?"


def test_texto_humano_normal_passa_intacto():
    raw = "boa noite Alejandro\n\nmarca própria é o que a gente mais gosta de fazer aqui"
    assert _strip_leaked_reasoning(raw) == raw


def test_sanitizer_do_orchestrator_cobre_raciocinio():
    """Defesa em profundidade: o vazamento tem que morrer no _sanitize_assistant_text."""
    raw = "<scratchpad>plano interno</scratchpad>\n\nboa noite\n\ncomo vai o projeto?"
    out = _sanitize_assistant_text(raw, "conv-1", "private_label", source="initial")
    assert "scratchpad" not in out.lower()
    assert "plano interno" not in out
    assert "boa noite" in out


def test_nudge_da_guarda_de_repeticao_proibe_raciocinio_no_texto():
    """O gatilho: o nudge pede reescrita e o modelo 'pensa em voz alta'. Ele tem que proibir isso."""
    import inspect

    from app.agent import orchestrator

    src = inspect.getsource(orchestrator.run_agent)
    assert "scratchpad" in src.lower(), (
        "o nudge da REPEAT QUESTION GUARD deve proibir explicitamente raciocinio/tags no texto"
    )
