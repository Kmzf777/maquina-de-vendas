"""Guard de abertura orgânica no outbound secretaria (defesa em profundidade).

Falha real: lead 5593984031598 abriu com "boa tarde" (sem template enviado) e a persona
outbound respondeu "cadastro confirmado…" — um cadastro fantasma. O guard instrui o LLM a só
usar o frame de "cadastro" quando houver template real no histórico; numa abertura orgânica,
saúda natural e constrói a ponte de valor SEM citar cadastro.

Testes de conteúdo de prompt (substring), no padrão de test_base_prompt.py.
"""
from app.agent.prompts import get_stage_prompts


def _sec() -> str:
    return get_stage_prompts("valeria_outbound")["secretaria"].lower()


def test_guard_distingue_abertura_organica_de_template():
    low = _sec()
    assert "abertura organica" in low
    # instrução crítica de verificar o histórico antes de assumir o template
    assert "verifique" in low or "verificar" in low or "olhe o historico" in low


def test_guard_proibe_cadastro_em_abertura_organica():
    low = _sec()
    # proibição explícita de citar "cadastro" quando o lead abriu sozinho
    assert "proibido" in low and "cadastro" in low
    assert "cadastro fantasma" in low or "nunca recebeu esse template" in low


def test_fewshot_abertura_organica_presente():
    low = _sec()
    # exemplo do cenário orgânico: lead manda só "boa tarde", IA não cita cadastro
    assert "boa tarde" in low
    assert "abertura organica" in low
    # ponte de valor sem cadastro (frase de valor da torrefação)
    assert "torrefacao de cafe especial da serra da canastra" in low
    # referência à falha real
    assert "5593984031598" in low


def test_frame_template_preservado_sem_regressao():
    low = _sec()
    # cenário (A) — quando HÁ template — continua usando "cadastro confirmado"
    assert "cadastro confirmado" in low
    assert "esse cadastro era so pra confirmar" in low
