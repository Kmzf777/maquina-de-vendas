"""Fix do parse do dossiê (rolling_summary) — auditoria 2026-07-08.

Em 08/07 o worker de dossiê fez 1.366 chamadas LLM (~93 por lead) e NENHUM
`leads.rolling_summary` foi persistido: a saída do modelo vinha embrulhada
(cerca de código / prosa em volta do JSON) e `json.loads` cru rejeitava tudo —
`generate_rolling_summary` devolvia o prior silenciosamente, e no código
pré-53bcdf2 a marca d'água nunca avançava (o loop). Estes testes travam:

- extração tolerante do objeto JSON (cerca ```json, prosa em volta);
- falha de parse deixa de ser silenciosa (alerta memory_parse_fail).
"""
import json

import pytest
from unittest.mock import AsyncMock, patch

from app.agent import memory_manager
from app.agent.memory_manager import _extract_json_object, generate_rolling_summary
from tests.gemini_fakes import fake_text

_FIELDS = {
    "perfil_empresa": "Nayara, cafeteria em Pirassununga",
    "interesse_preferencias": "Drip Coffee sachê de bolso, ~100un",
    "objecoes": "Não informado",
    "estagio_negocio": "cliente com compra em maio",
    "proximo_passo": "ofertar reposição do drip",
}


def test_extrai_json_com_cerca_markdown():
    content = "```json\n" + json.dumps(_FIELDS, ensure_ascii=False) + "\n```"
    assert _extract_json_object(content) == _FIELDS


def test_extrai_json_com_prosa_em_volta():
    content = "claro! aqui está o dossiê atualizado: " + json.dumps(_FIELDS, ensure_ascii=False) + " espero ter ajudado"
    assert _extract_json_object(content) == _FIELDS


def test_extrai_json_puro():
    assert _extract_json_object(json.dumps(_FIELDS, ensure_ascii=False)) == _FIELDS


def test_conteudo_sem_json_levanta():
    with pytest.raises(ValueError):
        _extract_json_object("desculpe, não posso ajudar com isso")


def _patch_generate(content: str):
    """Patch do núcleo nativo (app.agent.memory_manager.generate) devolvendo `content`."""
    return patch(
        "app.agent.memory_manager.generate",
        new=AsyncMock(side_effect=[fake_text(content)]),
    )


@pytest.mark.asyncio
async def test_generate_persiste_dossie_mesmo_com_cerca():
    content = "```json\n" + json.dumps(_FIELDS, ensure_ascii=False) + "\n```"
    delta = [{"role": "user", "content": "quero repor o drip"}]
    with _patch_generate(content):
        result = await generate_rolling_summary("", delta, "gemini-2.5-flash-lite")
    assert "## DOSSIÊ DO LEAD" in result
    assert "Drip Coffee" in result


@pytest.mark.asyncio
async def test_generate_lixo_preserva_prior_e_alerta(monkeypatch):
    fired = {}
    monkeypatch.setattr(memory_manager, "_fire_memory_parse_alert", lambda *a, **k: fired.setdefault("x", True))
    delta = [{"role": "user", "content": "oi"}]
    with _patch_generate("não consigo gerar isso"):
        result = await generate_rolling_summary(
            "## DOSSIÊ DO LEAD\nanterior", delta, "gemini-2.5-flash-lite",
        )
    assert result == "## DOSSIÊ DO LEAD\nanterior"
    assert fired.get("x") is True
