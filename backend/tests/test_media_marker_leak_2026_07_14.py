"""#7 (auditoria 14/07, caso Noelson): o marcador de HISTÓRICO de mídia vazou como bolha.

render_history_content envelopa a legenda de fotos que a Valéria enviou como
'[Foto enviada por você: "Modelo de embalagem standup"]' — representação CORRETA e
deliberada para o LLM (fix 13/07, evita o modelo inventar "recebi suas fotos"). Mas o
modelo ECOOU esse marcador como texto da resposta e ele chegou ao WhatsApp do cliente
(onde "você" lê como se o CLIENTE tivesse enviado — autoria aparentemente invertida).

Backstop determinístico: strip_media_history_markers remove QUALQUER marcador-envelope de
mídia do texto de saída, garantindo que nunca vaze ao cliente. O formato do histórico é
PRESERVADO (o LLM continua lendo o envelope) — só a SAÍDA é higienizada.
"""

from app.agent.adherence import strip_media_history_markers


class TestStripMediaHistoryMarkers:
    def test_caso_noelson_dois_marcadores_viram_vazio(self):
        raw = (
            '[Foto enviada por você: "Modelo de embalagem standup"]\n\n'
            '[Foto enviada por você: "Produto final pronto para comercializacao"]'
        )
        assert strip_media_history_markers(raw).strip() == ""

    def test_marcador_de_recebimento_do_lead(self):
        raw = '[Foto recebida do lead: "essa é a logo da minha marca"]'
        assert strip_media_history_markers(raw).strip() == ""

    def test_marcador_no_meio_preserva_texto_real(self):
        raw = '[Foto enviada por você: "standup"] boa, qual chamou mais atenção?'
        out = strip_media_history_markers(raw)
        assert "[Foto" not in out
        assert "enviada por você" not in out.lower()
        assert "qual chamou mais atenção" in out

    def test_outros_tipos_de_midia(self):
        for raw in (
            '[Vídeo enviado por você: "tour da fazenda"]',
            '[Documento enviado por você: "tabela de preços"]',
            '[Figurinha enviada por você: "x"]',
            '[Contato enviado por você: "João Bras"]',
        ):
            assert strip_media_history_markers(raw).strip() == ""

    def test_texto_legitimo_com_palavra_foto_intacto(self):
        raw = "boa, essa foto do standup ficou ótima, quer ver os valores?"
        assert strip_media_history_markers(raw) == raw

    def test_texto_normal_intacto(self):
        raw = "o 250g fica R$26,70 a unidade, faz sentido pra você?"
        assert strip_media_history_markers(raw) == raw

    def test_vazio_e_none(self):
        assert strip_media_history_markers("") == ""
        assert strip_media_history_markers(None) is None
