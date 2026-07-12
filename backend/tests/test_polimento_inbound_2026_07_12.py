"""Pacote de polimento inbound 12/07 — 4 observações da auditoria (laudo 2026-07-12).

P1 (caso humbertocarvao): o modelo usou \\n simples entre saudação/pitch/pergunta e o
   Step 3 do splitter colapsou tudo numa bolha corrida sem pontuação. Guarda nova no
   splitter: saudação colada em run-on longo vira bolha própria (antes do clamp).
P2 (caso Bianca): [imagem] coalescida com texto do lead no mesmo pacote foi ignorada —
   o Caso 1 de mídia ganha instrução explícita para o pacote misto.
P3 (caso Maria Socorro): mensagem_despedida prometeu que o João "ajuda com o registro
   de marca" logo após a própria Valéria dizer que registro é responsabilidade do
   cliente — regra 16 ganha proibição de sobrepromessa fora de escopo.
P4 (caso Rosangela): turno entregou informação (blend/SCA) e morreu sem pergunta de
   avanço — checklist ganha item de invariante para turno informativo.
"""
from datetime import datetime

from app.agent.prompts.base import build_base_prompt
from app.humanizer.splitter import split_into_bubbles


def _prompt() -> str:
    return build_base_prompt(None, None, datetime(2026, 7, 12, 16, 0))


# ---------------------------------------------------------------------------
# P1 — splitter: saudação colada em run-on vira bolha própria
# ---------------------------------------------------------------------------

class TestGreetingRunOnSplit:
    def test_caso_humbertocarvao_descola_saudacao(self):
        raw = (
            "bom dia marca própria e o que a gente mais gosta de fazer aqui "
            "você já tem uma marca criada ou tá pensando em lancar do zero?"
        )
        bubbles = split_into_bubbles(raw)
        assert bubbles[0] == "bom dia"
        assert bubbles[1].startswith("marca própria")

    def test_run_on_por_quebra_simples_tambem_descola(self):
        """Fonte provável do caso real: \\n simples colapsado em espaço pelo Step 3."""
        raw = (
            "boa tarde\nmarca própria é o que a gente mais gosta de fazer aqui na Café Canastra\n"
            "você já tem uma marca criada ou tá pensando em lançar do zero?"
        )
        bubbles = split_into_bubbles(raw)
        assert bubbles[0] == "boa tarde"

    def test_saudacao_com_resto_curto_fica_junta(self):
        assert split_into_bubbles("bom dia pra você também") == ["bom dia pra você também"]

    def test_saudacao_com_vocativo_curto_fica_junta(self):
        assert split_into_bubbles("boa tarde Ana") == ["boa tarde Ana"]

    def test_saudacao_sozinha_inalterada(self):
        assert split_into_bubbles("olá") == ["olá"]

    def test_paragrafos_normais_inalterados(self):
        raw = "boa tarde\n\nmarca própria é o que a gente mais gosta de fazer aqui\n\nvocê já tem uma marca criada?"
        assert split_into_bubbles(raw) == [
            "boa tarde",
            "marca própria é o que a gente mais gosta de fazer aqui",
            "você já tem uma marca criada?",
        ]

    def test_clamp_max_bubbles_continua_valendo_apos_o_split(self):
        raw = (
            "bom dia aqui vai um pitch bem comprido sobre marca própria de café pra estourar o limite\n\n"
            "segundo parágrafo com mais conteúdo\n\n"
            "terceiro parágrafo com a pergunta final?"
        )
        bubbles = split_into_bubbles(raw)
        assert len(bubbles) <= 3
        assert bubbles[0] == "bom dia"
        # Nenhum conteúdo é descartado — o overflow funde na última bolha.
        assert "pergunta final?" in bubbles[-1]

    def test_bolha_comum_sem_saudacao_inalterada(self):
        raw = "o café Clássico tem notas achocolatadas e é um dos nossos mais pedidos aqui na fazenda"
        assert split_into_bubbles(raw) == [raw]


# ---------------------------------------------------------------------------
# P2 — prompt: mídia coalescida com texto exige reconhecimento explícito
# ---------------------------------------------------------------------------

def test_caso1_cobre_midia_coalescida_com_texto():
    p = _prompt()
    start = p.index("## Caso 1")
    end = p.index("## Caso 2", start)
    s = p[start:end]
    assert "JUNTO com texto" in s
    assert "reconheca" in s.lower() or "reconheça" in s.lower()


# ---------------------------------------------------------------------------
# P3 — prompt: despedida de handoff não promete o que está fora de escopo
# ---------------------------------------------------------------------------

def test_regra16_proibe_sobrepromessa_fora_de_escopo():
    p = _prompt()
    assert "fora do escopo" in p
    # O exemplo concreto da vítima (registro de marca) ancora a regra.
    assert "registro de marca" in p


# ---------------------------------------------------------------------------
# P4 — prompt: checklist ganha invariante de pergunta de avanço
# ---------------------------------------------------------------------------

def test_checklist_tem_item_de_pergunta_de_avanco():
    """Item 30 cobre só preço; o invariante novo (31) cobre turno INFORMATIVO em geral."""
    p = _prompt()
    start = p.index("# CHECKLIST ANTES DE RESPONDER")
    s = p[start:]
    assert "31." in s
    assert "pergunta de avanco" in s.lower() or "pergunta de avanço" in s.lower()


def test_item_31_tem_excecoes_de_encerramento():
    """O invariante não pode forçar pergunta em despedida/descarte/encerramento social."""
    p = _prompt()
    checklist = p.index("# CHECKLIST ANTES DE RESPONDER")
    start = p.index("31.", checklist)
    s = p[start:start + 700]
    assert "despedida" in s.lower()
    assert "NAO force" in s or "não force" in s.lower()
