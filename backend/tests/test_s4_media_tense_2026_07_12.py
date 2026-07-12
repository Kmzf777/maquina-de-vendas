"""S4 (auditoria 12/07): componente IA da corrida texto-antes-das-fotos.

A ordem texto→fotos é deliberada (processor: texto explicativo primeiro) e a
latência de 4–9s/foto é física (upload do binário à Meta a cada envio). O que
É escopo da Valéria: o prompt ensinava o fechamento pós-mídia no PASSADO
("Enviei aqui as fotos...") — frase falsa durante a janela de upload (6
ocorrências na varredura; foi essa moldura que degenerou na alucinação N1).
Fix: exemplos e regra no presente-progressivo ("tô te mandando...") — o texto
fica honesto enquanto as fotos sobem — e a guarda N1 estendida para alegações
progressivas, cobrindo o novo fraseado.
"""
from datetime import datetime

from app.agent.prompts.base import build_base_prompt


def _prompt() -> str:
    return build_base_prompt(None, None, datetime(2026, 7, 12, 14, 0))


def _fechamento_section(p: str) -> str:
    start = p.index("## Fechamento obrigatorio apos envio de fotos/catalogo")
    end = p.index("---", start)
    return p[start:end]


# ---------------------------------------------------------------------------
# Prompt: fechamento pós-mídia não pode mais ensinar o passado
# ---------------------------------------------------------------------------

def test_fechamento_nao_ensina_mais_tempo_passado():
    s = _fechamento_section(_prompt())
    assert "Enviei aqui as fotos" not in s
    assert "Mandei as imagens" not in s
    assert "Ta ai o catalogo" not in s


def test_fechamento_ensina_presente_progressivo():
    s = _fechamento_section(_prompt())
    assert "mandando" in s
    # Regra explícita: as fotos chegam DEPOIS do texto — nunca afirmar no passado.
    assert "DEPOIS do texto" in s
    assert "passado" in s.lower()


def test_anti_spam_reenvio_continua_no_passado():
    """Referência a fotos JÁ entregues em turno anterior segue legítima no passado."""
    p = _prompt()
    assert "enviei aqui no chat" in p


# ---------------------------------------------------------------------------
# Guarda N1: alegações progressivas também são cobertas
# ---------------------------------------------------------------------------

class TestPhotoClaimProgressive:
    def _fn(self, text) -> bool:
        from app.agent.orchestrator import _looks_like_photo_send_claim
        return _looks_like_photo_send_claim(text)

    def test_to_te_mandando_as_fotos(self):
        assert self._fn("tô te mandando aqui as fotos do nosso portfolio") is True

    def test_estou_enviando_as_imagens(self):
        assert self._fn("estou enviando as imagens dos produtos") is True

    def test_mandando_o_catalogo(self):
        assert self._fn("tô mandando o catalogo com as embalagens aqui") is True

    def test_passado_continua_coberto(self):
        assert self._fn("enviei aqui as fotos do nosso portfólio") is True

    def test_oferta_futura_continua_fora(self):
        assert self._fn("quer que eu te mostre como fica?") is False

    def test_recebimento_continua_fora(self):
        assert self._fn("recebi sua foto aqui, vou deixar salvo pro Joao") is False
