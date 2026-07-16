"""
Frente C (spec 2026-07-15) — legendas sensoriais canônicas + sanitização de ingresso
de nome em salvar_nome (tools.py).

Guarda 1: as notas sensoriais do Atacado vivem em UMA fonte só
(SENSORY_CAPTIONS_ATACADO); PHOTO_CAPTIONS e PRODUTO_PHOTO_MAP derivam dela, então as
legendas casam byte-a-byte e a divergência da auditoria ("melaco" vazando pro Suave)
não pode voltar.

Guarda 2: _t_salvar_nome aplica sanitize_display_name no ingresso — "meu nome é
Ricardo" persiste "Ricardo"; saudação pura ("boa tarde") é ignorada sem sobrescrever
nome bom.
"""

import pytest
from unittest.mock import patch

from app.agent.tools import (
    PHOTO_CAPTIONS,
    PRODUTO_PHOTO_MAP,
    SENSORY_CAPTIONS_ATACADO,
    _t_salvar_nome,
)
from app.agent.tool_registry import ToolContext


# ---------------------------------------------------------------------------
# 1. Consistência das legendas — fonte única
# ---------------------------------------------------------------------------

def _atacado_captions() -> list[str]:
    return list(PHOTO_CAPTIONS["atacado"].values())


def test_melaco_aparece_somente_no_microlote():
    """"melaco" só pode estar na legenda do Microlote (banco: Suave = achocolatadas)."""
    com_melaco = [c for c in _atacado_captions() if "melaco" in c]
    assert com_melaco == [SENSORY_CAPTIONS_ATACADO["microlote"]]
    # Explicitamente: Suave NÃO carrega melaco.
    assert "melaco" not in PHOTO_CAPTIONS["atacado"]["foto_2"]


def test_suave_e_achocolatadas():
    assert "achocolatadas" in PHOTO_CAPTIONS["atacado"]["foto_2"]
    assert "frutas amarelas" not in PHOTO_CAPTIONS["atacado"]["foto_2"]


def test_classico_caramelizadas_e_achocolatadas():
    assert "caramelizadas e achocolatadas" in PHOTO_CAPTIONS["atacado"]["foto_1"]


def test_suave_fonte_unica_byte_identica():
    """A legenda de foto e a do mapa produto→foto vêm do MESMO string."""
    assert (
        PHOTO_CAPTIONS["atacado"]["foto_2"]
        == PRODUTO_PHOTO_MAP["atacado"]["suave"]["caption"]
        == SENSORY_CAPTIONS_ATACADO["suave"]
    )
    assert "frutas amarelas" not in PRODUTO_PHOTO_MAP["atacado"]["suave"]["caption"]


def test_todas_atacado_derivam_da_fonte_canonica():
    """foto_1..foto_5 e as entradas do PRODUTO_PHOTO_MAP são idênticas à fonte."""
    ordem = ["classico", "suave", "canela", "microlote", "drip"]
    for i, chave in enumerate(ordem, start=1):
        canonico = SENSORY_CAPTIONS_ATACADO[chave]
        assert PHOTO_CAPTIONS["atacado"][f"foto_{i}"] == canonico
        # microlote/drip têm chaves próprias no mapa de produto
        prod = chave if chave != "capsulas" else "capsulas"
        assert PRODUTO_PHOTO_MAP["atacado"][prod]["caption"] == canonico
    # capsulas compartilha a legenda (e a foto) do drip
    assert (
        PRODUTO_PHOTO_MAP["atacado"]["capsulas"]["caption"]
        == SENSORY_CAPTIONS_ATACADO["drip"]
    )


def test_drip_caption_inalterada():
    assert PHOTO_CAPTIONS["atacado"]["foto_5"] == "Drip Coffee e Capsulas Nespresso"
    assert PRODUTO_PHOTO_MAP["atacado"]["drip"]["caption"] == "Drip Coffee e Capsulas Nespresso"


def test_files_do_mapa_preservados():
    """Os nomes de arquivo (inclusive foto_3.png) não mudam com a derivação."""
    m = PRODUTO_PHOTO_MAP["atacado"]
    assert m["classico"]["file"] == "foto_1.jpg"
    assert m["suave"]["file"] == "foto_2.jpg"
    assert m["canela"]["file"] == "foto_3.png"
    assert m["microlote"]["file"] == "foto_4.jpg"
    assert m["drip"]["file"] == "foto_5.jpg"
    assert m["capsulas"]["file"] == "foto_5.jpg"


# ---------------------------------------------------------------------------
# 2. Sanitização de ingresso em salvar_nome
# ---------------------------------------------------------------------------

def _ctx(name: str) -> ToolContext:
    return ToolContext(
        args={"name": name},
        lead_id="lead-cap-1",
        phone="5511999990001",
        conversation_id="conv-cap-1",
    )


@pytest.mark.asyncio
async def test_salvar_nome_extrai_nome_de_frase_de_apresentacao():
    """"meu nome é Ricardo" deve persistir apenas "Ricardo" (Frente B já merged)."""
    with patch("app.agent.tools.update_lead") as mock_update:
        result = await _t_salvar_nome(_ctx("meu nome é Ricardo"))

    mock_update.assert_called_once_with("lead-cap-1", name="Ricardo")
    assert "Ricardo" in result
    assert result == "Nome salvo: Ricardo"


@pytest.mark.asyncio
async def test_salvar_nome_ignora_saudacao_pura():
    """"boa tarde" → sanitize None → NÃO chama update_lead (não sobrescreve nome bom)."""
    with patch("app.agent.tools.update_lead") as mock_update:
        result = await _t_salvar_nome(_ctx("boa tarde"))

    mock_update.assert_not_called()
    assert "ignorado" in result.lower()


@pytest.mark.asyncio
async def test_salvar_nome_persiste_nome_real_intacto():
    """Nome legítimo passa sem alteração."""
    with patch("app.agent.tools.update_lead") as mock_update:
        result = await _t_salvar_nome(_ctx("Ricardo Silva"))

    mock_update.assert_called_once_with("lead-cap-1", name="Ricardo Silva")
    assert result == "Nome salvo: Ricardo Silva"
