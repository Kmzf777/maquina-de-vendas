"""Eixo 4 — Framework de descoberta (SPIN) + viabilidade financeira no base.py.

Bug do Helio (5511996391971): lead iniciante recebeu lote mínimo de 100un (~R$2.670) sem
dimensionamento; à objeção de margem ("fica salgado pra revenda") a IA re-cotou −R$1. O bloco
força descobrir porte antes de cravar preço, faz a conta da revenda na objeção de margem, e usa
um <scratchpad> p/ travar 1 pergunta por turno (anti-aceleração do Gemini).
"""
from datetime import datetime
from app.agent.prompts.base import build_base_prompt


def _p():
    return build_base_prompt("Helio", None, datetime(2026, 6, 26, 14, 0))


def test_base_tem_bloco_descoberta_antes_de_preco():
    assert "DESCOBERTA ANTES DE PREÇO" in _p()


def test_base_tem_scratchpad_anti_aceleracao():
    p = _p()
    assert "<scratchpad>" in p
    low = p.lower()
    assert "estágio" in low or "estagio" in low


def test_base_tem_play_de_objecao_de_margem():
    low = _p().lower()
    assert "margem" in low
    assert "revenda" in low
    # não re-cotar mecanicamente
    assert "re-cot" in low or "recot" in low or "conta da revenda" in low


def test_base_exige_dimensionar_porte_antes_do_minimo():
    low = _p().lower()
    assert "porte" in low or "dimension" in low
    assert "pedido mínimo" in low or "pedido minimo" in low or "lote mínimo" in low or "lote minimo" in low
