"""Testes do épico handoff/reação/blacklist (auditoria 2026-06-22)."""
import base64
import json
from datetime import datetime
import pytest


# --- Problema 1: reação nunca em branco ----------------------------------

@pytest.mark.asyncio
async def test_resolve_media_reaction_nao_fica_em_branco():
    from app.buffer.processor import _resolve_media
    meta = {"emoji": "👍", "target_wamid": "wamid.ALVO"}
    b64 = base64.b64encode(json.dumps(meta).encode()).decode()
    text = f"[reaction: meta_b64={b64}]"
    resolved, _url, mtype, _doc, md = await _resolve_media(text, provider=object())
    assert mtype == "reaction"
    assert resolved == "[reagiu com 👍]"      # nunca string vazia (fantasma)
    assert md.get("target_wamid") == "wamid.ALVO"


# --- Problema 2: CTA de handoff direciona a ação pro lead ----------------

def test_base_prompt_cta_handoff_direciona_lead():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt("Edberto", None, datetime(2026, 6, 22, 14, 0))
    assert "MOTIVE O LEAD A AGIR" in s
    assert 'nunca use\n       "vou te conectar"' in s or "nunca use" in s


# --- Problema 4: blacklist guardrail (soft vs hard) ----------------------

def test_looks_like_soft_rejection_detecta_soft():
    from app.agent.tools import _looks_like_soft_rejection
    assert _looks_like_soft_rejection("não tenho interesse no momento") is True
    assert _looks_like_soft_rejection("sem disponibilidade agora") is True
    assert _looks_like_soft_rejection("ja sou cliente de voces") is True
    assert _looks_like_soft_rejection("vou pensar e te falo") is True


def test_looks_like_soft_rejection_nao_rebaixa_hard():
    from app.agent.tools import _looks_like_soft_rejection
    assert _looks_like_soft_rejection("para de me mandar mensagem") is False
    assert _looks_like_soft_rejection("me tira da lista") is False
    assert _looks_like_soft_rejection("quero descadastrar meu contato") is False
    assert _looks_like_soft_rejection("clicou parar mensagens") is False
    # caso ambíguo sem sinal soft nem hard → não rebaixa (mantém decisão do LLM)
    assert _looks_like_soft_rejection("lead mandou audio") is False


def test_base_prompt_blacklist_proibe_soft_como_optout():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt("Edberto", None, datetime(2026, 6, 22, 14, 0))
    assert "PROIBIDO usar registrar_optout (Blacklist)" in s
