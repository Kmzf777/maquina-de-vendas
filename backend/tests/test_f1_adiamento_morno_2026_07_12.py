"""F1 + resíduos da varredura pós-polimento 12/07 (laudo varredura_pos_polimento_2026_07_12.md).

F1 (caso Rogério 5532988382873, 17:39 UTC): lead quente disse "vou apresentar para meu
genro que é meu sócio e retorno a você" e o modelo chamou registrar_sem_interesse_atual
com motivo CONFESSANDO o erro ("Não é rejeição, mas pedido de tempo para decisão") —
violação da regra 18C, que já listava "vou ver com meu socio" como gatilho. Como o
prompt sozinho não segurou, a defesa vira determinística: a própria tool aborta o
descarte quando o motivo indica adiamento morno (espelho do guardrail de cliente ativo).

Resíduo A (Daniel/Edimilson/Brito): o run-on pitch+pergunta persiste fora do escopo da
guarda de saudação — sempre a MESMA pergunta roteirizada do funil ("voce ja tem uma
marca criada..."). Seam determinística no splitter: a pergunta roteirizada colada no
meio de uma bolha vira bolha própria.

Resíduo B (Empório Da Canastra): pushname de EMPRESA usado como vocativo ("fechado,
Empório Da Canastra") — sanitize_display_name ganha blocklist de tokens de negócio.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.humanizer.splitter import split_into_bubbles
from app.leads.service import sanitize_display_name


_MOTIVO_ROGERIO = (
    "Lead vai apresentar para o sócio e retorna. "
    "Não é rejeição, mas pedido de tempo para decisão."
)


# ---------------------------------------------------------------------------
# F1 / Secao 1: função pura _motivo_indica_adiamento
# ---------------------------------------------------------------------------

class TestMotivoIndicaAdiamento:
    def _fn(self, motivo) -> bool:
        from app.agent.tools import _motivo_indica_adiamento
        return _motivo_indica_adiamento(motivo)

    def test_motivo_real_do_caso_rogerio(self):
        assert self._fn(_MOTIVO_ROGERIO) is True

    def test_nao_e_rejeicao_dispara(self):
        assert self._fn("nao e rejeicao, so quer decidir depois") is True

    def test_pedido_de_tempo_dispara(self):
        assert self._fn("lead fez um pedido de tempo para avaliar") is True

    def test_promete_retornar_dispara(self):
        assert self._fn("disse que vai retornar na segunda com a resposta") is True

    def test_rejeicao_legitima_nao_dispara(self):
        assert self._fn("lead disse que ja tem fornecedor e nao quer mudar") is False

    def test_sem_interesse_apos_contorno_nao_dispara(self):
        assert self._fn("reafirmou que nao tem interesse, achou caro") is False

    def test_none_nao_dispara(self):
        assert self._fn(None) is False


# ---------------------------------------------------------------------------
# F1 / Secao 2: a tool ABORTA o descarte quando o motivo confessa adiamento
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_descarte_com_motivo_de_adiamento_e_abortado():
    from app.agent.tools import execute_tool

    with patch("app.agent.tools.lead_has_active_relationship", return_value=False), \
         patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools._send_despedida_descarte", new_callable=AsyncMock) as mock_bye, \
         patch("app.agent.tools.move_lead_deals_to_perdido") as mock_deals, \
         patch("app.agent.tools.cancel_followups_by_phone"), \
         patch("app.agent.tools.append_lead_observation"), \
         patch("app.agent.tools.save_message") as mock_save:
        result = await execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": _MOTIVO_ROGERIO, "mensagem_despedida": "sem problema, fico a disposicao"},
            "lead-f1-001", "5532988382873", "conv-f1-001",
        )

    # O lead NÃO pode ser tocado: nada de stage=perdido, nada de despedida de descarte.
    assert not mock_update.called, "guarda 18C deve abortar ANTES de mexer no lead"
    assert not mock_bye.called, "despedida de descarte não sai num adiamento morno"
    assert not mock_deals.called
    # O retorno instrui o modelo a seguir a 18C (resposta curta / agendar_retorno).
    assert "18C" in result or "adiamento" in result.lower()
    # Marcador QA persistido para auditoria.
    assert mock_save.called
    marker = mock_save.call_args.args[2]
    assert "ABORTADO" in marker


@pytest.mark.asyncio
async def test_descarte_legitimo_continua_funcionando():
    from app.agent.tools import execute_tool

    with patch("app.agent.tools.lead_has_active_relationship", return_value=False), \
         patch("app.agent.tools.update_lead") as mock_update, \
         patch("app.agent.tools._send_despedida_descarte", new_callable=AsyncMock) as mock_bye, \
         patch("app.agent.tools.move_lead_deals_to_perdido"), \
         patch("app.agent.tools.cancel_followups_by_phone"), \
         patch("app.agent.tools.append_lead_observation"), \
         patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "registrar_sem_interesse_atual",
            {"motivo": "reafirmou que nao tem interesse apos o contorno, achou caro"},
            "lead-f1-002", "5532988382874", "conv-f1-002",
        )

    assert mock_update.called, "soft rejection legítima segue descartando"
    assert mock_bye.called
    assert "sem interesse" in result.lower()


# ---------------------------------------------------------------------------
# F1 / Secao 3: prompt — gatilho explícito e aviso da guarda na 18C
# ---------------------------------------------------------------------------

def test_18c_lista_vou_apresentar_como_gatilho():
    from datetime import datetime
    from app.agent.prompts.base import build_base_prompt
    p = build_base_prompt(None, None, datetime(2026, 7, 12, 18, 0))
    start = p.index("(C) ADIAMENTO MORNO")
    section = p[start:p.index("REGRAS COMUNS", start)]
    assert "vou apresentar" in section


def test_18b_avisa_que_a_tool_recusa_motivo_de_adiamento():
    from datetime import datetime
    from app.agent.prompts.base import build_base_prompt
    p = build_base_prompt(None, None, datetime(2026, 7, 12, 18, 0))
    start = p.index("(B) SOFT REJECTION")
    section = p[start:p.index("(C) ADIAMENTO MORNO", start)]
    assert "nao e rejeicao" in section
    assert "REJEITA" in section or "recusa" in section.lower()


# ---------------------------------------------------------------------------
# Resíduo A: pergunta roteirizada colada no meio da bolha vira bolha própria
# ---------------------------------------------------------------------------

class TestScriptedQuestionSeam:
    def test_caso_daniel_pitch_e_pergunta_separam(self):
        raw = (
            "marca própria é o que a gente mais gosta de fazer aqui na Café Canastra "
            "você já tem uma marca criada ou tá pensando em lançar do zero?"
        )
        bubbles = split_into_bubbles(raw)
        assert len(bubbles) == 2
        assert bubbles[0].endswith("Café Canastra")
        assert bubbles[1].startswith("você já tem uma marca criada")

    def test_caso_brito_com_vocativo_no_meio(self):
        raw = (
            "marca própria é o que a gente mais gosta de fazer aqui, Brito "
            "você já tem uma marca criada ou tá pensando em lançar do zero?"
        )
        bubbles = split_into_bubbles(raw)
        assert len(bubbles) == 2
        assert bubbles[0].endswith("Brito")
        assert bubbles[1].startswith("você já tem uma marca criada")

    def test_sem_acentos_tambem_separa(self):
        raw = "marca propria e o que a gente mais gosta de fazer aqui voce ja tem uma marca criada ou ta pensando em lancar do zero?"
        bubbles = split_into_bubbles(raw)
        assert len(bubbles) == 2

    def test_pergunta_no_inicio_da_bolha_fica_intacta(self):
        raw = "você já tem uma marca criada ou tá pensando em lançar do zero?"
        assert split_into_bubbles(raw) == [raw]

    def test_pergunta_em_bolha_propria_via_paragrafo_fica_intacta(self):
        raw = "marca própria é o que a gente mais gosta de fazer aqui\n\nvocê já tem uma marca criada ou tá pensando em lançar do zero?"
        assert split_into_bubbles(raw) == [
            "marca própria é o que a gente mais gosta de fazer aqui",
            "você já tem uma marca criada ou tá pensando em lançar do zero?",
        ]


# ---------------------------------------------------------------------------
# Resíduo B: nome de EMPRESA não vira vocativo
# ---------------------------------------------------------------------------

class TestBusinessNameNotVocative:
    def test_emporio_da_canastra_cai_em_sem_nome(self):
        assert sanitize_display_name("Empório Da Canastra") is None

    def test_cafe_do_joao_cai_em_sem_nome(self):
        assert sanitize_display_name("Café do João") is None

    def test_distribuidora_cai_em_sem_nome(self):
        assert sanitize_display_name("RS Distribuidora") is None

    def test_nome_de_pessoa_passa(self):
        assert sanitize_display_name("João Silva") == "João Silva"

    def test_nome_simples_passa(self):
        assert sanitize_display_name("Ana") == "Ana"
