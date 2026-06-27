"""Erros 1 e 2 (Fanatical Prospecting): correções de prompt no funil outbound atacado.

Testes de conteúdo de prompt — verificam que a instrução crítica está presente na string,
seguindo o padrão de test_outbound_perfeicao.py (asserções de substring no prompt).
"""
from app.agent.prompts.valeria_outbound.atacado import ATACADO_PROMPT
from app.agent.prompts.valeria_inbound.atacado import ATACADO_PROMPT as INBOUND_ATACADO_PROMPT


def _norm(s: str) -> str:
    return s.lower()


# --- Erro 1: produtor/concorrente -> desqualificação suave ---

def test_outbound_atacado_tem_gatilho_produtor_concorrente():
    low = _norm(ATACADO_PROMPT)
    # reconhece o perfil auto-produtor/concorrente
    assert "produtor" in low or "produz" in low
    assert "concorrente" in low
    # exemplos elípticos cobertos
    assert "sou eu mesma" in low or "eu que produzo" in low


def test_outbound_atacado_produtor_dispara_sem_interesse_e_nao_converte():
    low = _norm(ATACADO_PROMPT)
    # a ação de desqualificação suave usa registrar_sem_interesse_atual (sem nova tool)
    assert "registrar_sem_interesse_atual" in low
    # postura: não tentar converter / não fazer diagnóstico de dor para esse perfil
    assert "nao tente converter" in low or "não tente converter" in low


def test_outbound_atacado_produtor_excecao_private_label():
    low = _norm(ATACADO_PROMPT)
    # única exceção: lead pede explicitamente private label / marca própria
    assert "private_label" in low or "private label" in low or "marca propria" in low or "marca própria" in low


# --- Erro 2: anti-interrogação / reagir antes da pergunta de valor ---

def test_outbound_atacado_regra30_exige_reagir_e_validar():
    low = _norm(ATACADO_PROMPT)
    # a regra de valor (WIIFM/regra 30) deve obrigar reagir/validar antes de perguntar
    assert "anti-interrogacao" in low or "anti-interrogação" in low
    assert "reaja" in low or "reagir" in low
    assert "valide" in low or "validar" in low
    # menciona explicitamente o risco da frase elíptica
    assert "eliptic" in low or "sou eu mesma" in low


def test_inbound_atacado_anti_interrogacao_preservada_sem_regressao():
    # regressão: o inbound já tinha a anti-interrogação (Etapa 1) e não pode perdê-la
    low = _norm(INBOUND_ATACADO_PROMPT)
    assert "anti-interrogacao" in low or "anti-interrogação" in low
    assert "reaja" in low or "reagir" in low
