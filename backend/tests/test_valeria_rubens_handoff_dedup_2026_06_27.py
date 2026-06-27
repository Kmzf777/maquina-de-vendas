"""Dedup do handoff (caso Rubens 5531999844461): não reenviar a despedida que a IA já disse."""
from unittest.mock import patch
import app.agent.tools as tools


def _norm(s):
    return tools._normalize_for_dedup(s)


def test_normalize_para_dedup_ignora_caixa_e_pontuacao():
    assert _norm("Pra pedir o KIT amostra, fala com o João!") == _norm("pra pedir o kit amostra fala com o joao")


def test_despedida_ja_enviada_detecta_repeticao():
    recent = ["pra pedir o kit amostra, você pode falar direto com o nosso supervisor, o joão bras"]
    with patch("app.agent.tools._recent_assistant_texts", return_value=recent):
        assert tools._despedida_ja_enviada(
            "conv-1",
            "pra pedir o kit amostra, você pode falar direto com o nosso supervisor, o João Brás",
        ) is True


def test_despedida_nova_nao_e_duplicata():
    recent = ["boa, já te mandei as fotos do portfólio"]
    with patch("app.agent.tools._recent_assistant_texts", return_value=recent):
        assert tools._despedida_ja_enviada("conv-1", "vou te passar pro João finalizar o pedido") is False
