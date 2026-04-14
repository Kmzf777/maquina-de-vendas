from app.agent.tools import get_tools_for_stage, PHOTO_CAPTIONS, PRODUTO_PHOTO_MAP


def test_secretaria_tools():
    tools = get_tools_for_stage("secretaria")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "mudar_stage" in names
    assert "encaminhar_humano" not in names


def test_atacado_tools():
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "salvar_nome" in names
    assert "encaminhar_humano" in names
    assert "enviar_fotos" in names


def test_consumo_tools():
    tools = get_tools_for_stage("consumo")
    names = [t["function"]["name"] for t in tools]
    assert names == ["salvar_nome"]


def test_photo_captions_exist_for_atacado():
    assert "atacado" in PHOTO_CAPTIONS
    captions = PHOTO_CAPTIONS["atacado"]
    assert len(captions) == 5
    assert "foto_1" in captions
    assert "Classico" in captions["foto_1"]


def test_photo_captions_exist_for_private_label():
    assert "private_label" in PHOTO_CAPTIONS
    captions = PHOTO_CAPTIONS["private_label"]
    assert len(captions) == 4
    assert "foto_1" in captions


def test_produto_photo_map_has_classico():
    assert "atacado" in PRODUTO_PHOTO_MAP
    assert "classico" in PRODUTO_PHOTO_MAP["atacado"]
    entry = PRODUTO_PHOTO_MAP["atacado"]["classico"]
    assert "file" in entry
    assert "caption" in entry


def test_atacado_tools_include_enviar_foto_produto():
    tools = get_tools_for_stage("atacado")
    names = [t["function"]["name"] for t in tools]
    assert "enviar_foto_produto" in names


def test_private_label_tools_include_enviar_foto_produto():
    tools = get_tools_for_stage("private_label")
    names = [t["function"]["name"] for t in tools]
    assert "enviar_foto_produto" in names


def test_secretaria_tools_exclude_enviar_foto_produto():
    tools = get_tools_for_stage("secretaria")
    names = [t["function"]["name"] for t in tools]
    assert "enviar_foto_produto" not in names
