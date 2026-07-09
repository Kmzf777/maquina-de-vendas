"""TDD Onda 2: tool registrar_indicacao (playbook de referral estruturado).

Auditoria 08/07 (caso Aline, ex-dona da Divina Terra): "vendi a loja" passou sem
pergunta de indicação e sem registro. A seção INDICAÇÃO do prompt (d56d977) ensina a
perguntar; esta tool dá onde GRAVAR a resposta — nota no CRM, metadata.referral e tag
— para o João acionar o sucessor depois. A tool NÃO cria lead novo: contato frio de
terceiro é decisão do vendedor humano.
"""
from unittest.mock import MagicMock, patch

import pytest

import app.agent.tools as tools


@pytest.mark.asyncio
async def test_registrar_indicacao_completa():
    with patch.object(tools, "get_lead", return_value={"id": "lead-1", "metadata": {}}), \
         patch.object(tools, "update_lead") as m_upd, \
         patch.object(tools, "append_lead_observation") as m_note, \
         patch.object(tools, "add_tags_to_lead") as m_tags, \
         patch.object(tools, "save_message") as m_save:
        result = await tools.execute_tool(
            "registrar_indicacao",
            {"contexto": "vendeu a Divina Terra; sucessor assumiu a loja",
             "nome": "Carlos", "telefone": "5534999990000"},
            lead_id="lead-1", phone="5534988887777", conversation_id="conv-1",
        )

    nota = m_note.call_args.args[1]
    assert "INDICAÇÃO" in nota or "INDICACAO" in nota
    assert "Carlos" in nota and "5534999990000" in nota
    referral = (m_upd.call_args.kwargs.get("metadata") or {}).get("referral") or {}
    assert referral.get("nome") == "Carlos"
    assert referral.get("telefone") == "5534999990000"
    assert referral.get("contexto")
    m_tags.assert_called_once_with("lead-1", ["indicacao"])
    assert "[registrar_indicacao]" in m_save.call_args.args[2]
    assert "registrada" in result.lower()


@pytest.mark.asyncio
async def test_registrar_indicacao_sem_contato_ainda_registra():
    """Só o contexto (ex.: 'quem ficou foi meu irmão, passo seu contato') já vale registro."""
    with patch.object(tools, "get_lead", return_value={"id": "lead-2", "metadata": {}}), \
         patch.object(tools, "update_lead") as m_upd, \
         patch.object(tools, "append_lead_observation") as m_note, \
         patch.object(tools, "add_tags_to_lead"), \
         patch.object(tools, "save_message"):
        result = await tools.execute_tool(
            "registrar_indicacao",
            {"contexto": "fechou a cafeteria; irmão ficou com o ponto, vai repassar o contato"},
            lead_id="lead-2", phone="5534988887777", conversation_id="conv-2",
        )

    assert m_note.called
    referral = (m_upd.call_args.kwargs.get("metadata") or {}).get("referral") or {}
    assert referral.get("contexto")
    assert referral.get("nome") == ""
    assert "registrada" in result.lower()


def test_disponivel_nos_stages_comerciais():
    for stage in ("secretaria", "atacado", "private_label"):
        names = [t["function"]["name"] for t in tools.get_tools_for_stage(stage)]
        assert "registrar_indicacao" in names, stage
