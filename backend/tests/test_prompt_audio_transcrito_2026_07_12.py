"""Caso 0 de mídia: [audio transcrito: X] é fala do cliente, não falha (forense 12/07).

Caso 5522991014146 (11/07 22:57): áudio transcrito com sucesso, mas o prompt só
definia o fallback de "audio nao transcrito" — o modelo pattern-matchou "audio",
soltou "me manda por texto aqui que eu te ajudo na hora?" E respondeu ao conteúdo
na bolha seguinte (turno autocontraditório). O marcador [audio transcrito: ...]
injetado por processor._resolve_media precisa de instrução própria: tratar X como
fala normal, responder direto, NUNCA pedir texto.
"""
from datetime import datetime

from app.agent.prompts.base import build_base_prompt


def _prompt() -> str:
    return build_base_prompt(None, None, datetime(2026, 7, 12, 10, 0))


def _caso0(p: str) -> str:
    start = p.index("## Caso 0")
    end = p.index("## Caso 1", start)
    return p[start:end]


def test_prompt_define_marcador_audio_transcrito():
    p = _prompt()
    assert "[audio transcrito:" in p
    # A definição vem ANTES do fallback de mídia sem contexto (Caso 2).
    assert p.index("[audio transcrito:") < p.index("me manda por texto aqui que eu te ajudo na hora")


def test_caso0_trata_transcricao_como_fala_normal():
    s = _caso0(_prompt())
    assert "fala normal" in s
    assert "responda direto" in s.lower()


def test_caso0_proibe_pedir_texto_para_audio_transcrito():
    s = _caso0(_prompt())
    assert "NUNCA" in s
    assert "por texto" in s
    # Fallback do Caso 2 fica restrito a transcrição inexistente.
    assert "SOMENTE" in s


def test_fallback_caso2_continua_existindo():
    # Regressão: o Caso 0 não pode remover o fallback legítimo de áudio NÃO transcrito.
    p = _prompt()
    assert "me manda por texto aqui que eu te ajudo na hora" in p
    assert "audio nao transcrito" in p
