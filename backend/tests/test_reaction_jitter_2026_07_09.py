"""Latência humana variável — auditoria 2026-07-08.

Todas as 12 respostas do dia saíram em 16–31s, a qualquer hora (13h, 18h,
21h37) — constância inumana. O jitter alonga o "tempo digitando" do 1º balão
por faixa horária, sem tocar nos balões seguintes nem no rehearsal.
"""
import random

from app.buffer.processor import (
    _bubble_delays,
    _human_extra_first_delay,
)


def test_banda_comercial():
    rng = random.Random(42)
    for _ in range(20):
        d = _human_extra_first_delay(10, rng=rng)
        assert 0.0 <= d <= 8.0


def test_banda_noite_cedo():
    rng = random.Random(42)
    for _ in range(20):
        d = _human_extra_first_delay(21, rng=rng)
        assert 5.0 <= d <= 20.0


def test_banda_madrugada():
    rng = random.Random(42)
    for _ in range(20):
        d = _human_extra_first_delay(2, rng=rng)
        assert 10.0 <= d <= 35.0


def test_desligado_zera():
    assert _human_extra_first_delay(21, enabled=False) == 0.0


def test_bubble_delays_soma_extra_no_primeiro_balao():
    # "Olá!" → piso 5.0; extra 3.0 → 8.0 no 1º balão apenas.
    assert _bubble_delays(["Olá!"], is_rehearsal=False, extra_first_delay=3.0) == [8.0]


def test_bubble_delays_default_inalterado():
    assert _bubble_delays(["Olá!"], is_rehearsal=False) == [5.0]


def test_rehearsal_ignora_extra():
    assert _bubble_delays(["Olá!"], is_rehearsal=True, extra_first_delay=9.0) == [0.0]
