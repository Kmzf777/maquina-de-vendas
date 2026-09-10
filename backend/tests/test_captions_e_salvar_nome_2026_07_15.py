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

from pathlib import Path

import pytest
from unittest.mock import patch

from app.agent import tools
from app.agent.tools import (
    CATALOGO_FOTOS,
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
    assert "melaco" not in PHOTO_CAPTIONS["atacado"]["foto_2_suave"]


def test_suave_e_achocolatadas():
    assert "achocolatadas" in PHOTO_CAPTIONS["atacado"]["foto_2_suave"]
    assert "frutas amarelas" not in PHOTO_CAPTIONS["atacado"]["foto_2_suave"]


def test_classico_caramelizadas_e_achocolatadas():
    assert "caramelizadas e achocolatadas" in PHOTO_CAPTIONS["atacado"]["foto_1_classico"]


def test_suave_fonte_unica_byte_identica():
    """A legenda de foto e a do mapa produto→foto vêm do MESMO string."""
    assert (
        PHOTO_CAPTIONS["atacado"]["foto_2_suave"]
        == PRODUTO_PHOTO_MAP["atacado"]["suave"]["caption"]
        == SENSORY_CAPTIONS_ATACADO["suave"]
    )
    assert "frutas amarelas" not in PRODUTO_PHOTO_MAP["atacado"]["suave"]["caption"]


def test_todas_atacado_derivam_da_fonte_canonica():
    """Toda legenda de foto e do PRODUTO_PHOTO_MAP é idêntica à fonte canônica."""
    for slug, arquivo in CATALOGO_FOTOS["atacado"]:
        canonico = SENSORY_CAPTIONS_ATACADO[slug]
        assert PHOTO_CAPTIONS["atacado"][Path(arquivo).stem] == canonico
        assert PRODUTO_PHOTO_MAP["atacado"][slug]["caption"] == canonico


def test_capsulas_e_drip_tem_fotos_distintas():
    """Regressão 08/09: cápsulas dividia foto (e legenda) com o Drip Coffee."""
    assert (
        PRODUTO_PHOTO_MAP["atacado"]["capsulas"]["file"]
        != PRODUTO_PHOTO_MAP["atacado"]["drip"]["file"]
    )
    assert "Nespresso" not in SENSORY_CAPTIONS_ATACADO["drip"]


# ---------------------------------------------------------------------------
# 1b. Vínculo arquivo↔produto (regressão da auditoria QA 08/09, conv 5534988861441)
# ---------------------------------------------------------------------------
# A legenda "Microlote — 86 SCA…" saiu na foto das CÁPSULAS e Clássico/Suave estavam
# trocados entre si. O bug sobreviveu às guardas de 15/07 porque elas só comparavam
# strings de legenda entre si — nada amarrava a legenda ao ARQUIVO que ia junto. Agora
# o slug do produto vive no nome do arquivo, e estas guardas exigem que ele bata.

def test_nome_do_arquivo_carrega_o_slug_do_produto():
    """Se alguém trocar duas fotos de lugar, o nome do arquivo denuncia."""
    for categoria, entradas in CATALOGO_FOTOS.items():
        for slug, arquivo in entradas:
            if categoria != "atacado":
                continue  # private_label usa nomes genéricos (foto_N), sem slug
            assert slug in Path(arquivo).stem, (
                f"{arquivo} deveria conter o slug '{slug}' no nome"
            )


def test_arquivos_do_catalogo_existem_em_disco():
    """O mapa não pode apontar para arquivo inexistente (envio falharia calado)."""
    base = Path(tools.__file__).parent.parent / "photos"
    for categoria, entradas in CATALOGO_FOTOS.items():
        for _slug, arquivo in entradas:
            assert (base / categoria / arquivo).is_file(), f"faltando {categoria}/{arquivo}"


def test_microlote_tem_foto_propria():
    """Regressão direta: o Microlote não pode reusar a foto de outro produto."""
    microlote = PRODUTO_PHOTO_MAP["atacado"]["microlote"]["file"]
    outros = [
        e["file"] for s, e in PRODUTO_PHOTO_MAP["atacado"].items() if s != "microlote"
    ]
    assert microlote not in outros
    assert "microlote" in microlote


def test_files_do_mapa_preservados():
    """Vínculo arquivo↔produto do Atacado, conferido foto a foto contra a embalagem.

    Esta era a guarda que congelava o bug: até 08/09 ela exigia classico=foto_1.jpg e
    suave=foto_2.jpg, mas o JPEG kraft (foto_1) é o SUAVE e o preto (foto_2) é o
    CLÁSSICO — o rótulo na própria embalagem prova. Os valores abaixo foram conferidos
    contra o catálogo oficial (tabela.cafecanastra.com, mesma fonte de
    products.image_urls). A extensão .png do Canela e do Microlote é intencional.
    """
    m = PRODUTO_PHOTO_MAP["atacado"]
    assert m["classico"]["file"] == "foto_1_classico.jpg"   # embalagem PRETA
    assert m["suave"]["file"] == "foto_2_suave.jpg"         # embalagem KRAFT
    assert m["canela"]["file"] == "foto_3_canela.png"       # embalagem VERMELHA
    assert m["microlote"]["file"] == "foto_4_microlote.png"
    assert m["capsulas"]["file"] == "foto_5_capsulas.jpg"
    assert m["drip"]["file"] == "foto_6_drip.jpg"


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
