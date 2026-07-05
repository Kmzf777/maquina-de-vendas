"""Testes das guardas determinísticas de aderência (app.agent.adherence, 2026-07-04).

Cobre:
  1. strip_prohibited_phrases: frase proibida removida preservando o resto da
     mensagem; variações de acento/caixa; texto limpo permanece inalterado.
  2. detect_auto_producer: cada família de sinais de auto-produtor é detectada;
     frases benignas (consumo, compra, elípticas ambíguas) NÃO são detectadas.
"""

from app.agent.adherence import detect_auto_producer, strip_prohibited_phrases


# ---------------------------------------------------------------------------
# strip_prohibited_phrases
# ---------------------------------------------------------------------------

class TestStripProhibitedPhrases:
    def test_removes_phrase_preserving_rest_of_message(self):
        text = "me conta um pouco mais pra te direcionar da melhor forma, blz?"
        result = strip_prohibited_phrases(text)
        assert "direcionar" not in result
        assert "me conta um pouco mais" in result
        assert "blz" in result

    def test_removes_phrase_without_sufix(self):
        text = "preciso de mais info pra te direcionar certinho"
        result = strip_prohibited_phrases(text)
        assert "te direcionar" not in result
        assert "certinho" in result

    def test_removes_para_variant(self):
        text = "vou perguntar mais coisas para te direcionar da melhor forma"
        result = strip_prohibited_phrases(text)
        assert "direcionar" not in result

    def test_removes_pra_eu_te_direcionar_variant(self):
        text = "me fala seu nome pra eu te direcionar da melhor forma"
        result = strip_prohibited_phrases(text)
        assert "direcionar" not in result
        assert "me fala seu nome" in result

    def test_accent_and_case_insensitive_matching(self):
        text = "Me conta mais PRA TE DIRECIONAR DA MELHOR FORMA, tá bom?"
        result = strip_prohibited_phrases(text)
        assert "DIRECIONAR" not in result.upper() or "direcionar" not in result.lower()
        assert "tá bom" in result or "ta bom" in result.lower()

    def test_clean_text_unchanged(self):
        text = "bom dia! qual café você quer conhecer hoje?"
        assert strip_prohibited_phrases(text) == text

    def test_empty_text_unchanged(self):
        assert strip_prohibited_phrases("") == ""

    def test_none_like_falsy_returns_as_is(self):
        # Função é tipada para str, mas deve degradar com segurança em falsy.
        assert strip_prohibited_phrases("") == ""

    def test_collapses_double_punctuation_after_removal(self):
        text = "show, pra te direcionar da melhor forma, me conta seu nome"
        result = strip_prohibited_phrases(text)
        assert ",," not in result
        assert "  " not in result
        assert "direcionar" not in result

    def test_removes_multiple_occurrences(self):
        text = "pra te direcionar bem me fala seu nome, e pra te direcionar da melhor forma me fala a cidade"
        result = strip_prohibited_phrases(text)
        assert "direcionar" not in result
        assert "me fala seu nome" in result
        assert "me fala a cidade" in result

    def test_preserves_multiline_structure(self):
        text = "oi! tudo bem?\n\nmé fala mais pra te direcionar da melhor forma"
        result = strip_prohibited_phrases(text)
        assert "direcionar" not in result
        assert "oi! tudo bem?" in result


# ---------------------------------------------------------------------------
# detect_auto_producer
# ---------------------------------------------------------------------------

class TestDetectAutoProducer:
    def test_eu_que_produzo(self):
        assert detect_auto_producer("nao preciso comprar, eu que produzo o cafe aqui") is True

    def test_eu_mesmo_torro(self):
        assert detect_auto_producer("eu mesmo torro meus graos aqui na fazenda") is True

    def test_eu_mesma_torro(self):
        assert detect_auto_producer("eu mesma torro o cafe que vendo") is True

    def test_sou_produtor(self):
        assert detect_auto_producer("sou produtor de cafe la em minas") is True

    def test_sou_produtora(self):
        assert detect_auto_producer("sou produtora, nao compradora") is True

    def test_produzo_meu_cafe(self):
        assert detect_auto_producer("produzo meu cafe desde 2015") is True

    def test_produzo_meu_proprio_cafe(self):
        assert detect_auto_producer("produzo meu proprio cafe aqui na regiao") is True

    def test_meu_proprio_cafe(self):
        assert detect_auto_producer("eu tenho meu proprio cafe, plantacao pequena") is True

    def test_tenho_minha_marca_de_cafe(self):
        assert detect_auto_producer("tenho minha marca de cafe ja registrada") is True

    def test_tenho_minha_fazenda_de_cafe(self):
        assert detect_auto_producer("tenho minha fazenda de cafe no sul de minas") is True

    def test_tenho_minha_propria_marca_de_cafe(self):
        assert detect_auto_producer("tenho minha propria marca de cafe, a Fulano Cafes") is True

    def test_accent_and_case_insensitive(self):
        assert detect_auto_producer("SOU PRODUTORA de Café especial") is True
        assert detect_auto_producer("Tenho Minha Fazenda de Café") is True

    # --- Casos benignos (NÃO devem disparar) ---

    def test_benign_tomo_cafe_todo_dia(self):
        assert detect_auto_producer("tomo cafe todo dia de manha") is False

    def test_benign_quero_comprar_cafe(self):
        assert detect_auto_producer("quero comprar cafe pra minha casa") is False

    def test_benign_sou_eu_mesma_isolada(self):
        assert detect_auto_producer("sou eu mesma quem decide as compras aqui") is False

    def test_empty_text(self):
        assert detect_auto_producer("") is False

    def test_unrelated_text(self):
        assert detect_auto_producer("qual o valor do frete pra minha cidade?") is False
