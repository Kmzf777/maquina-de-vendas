"""Evento `lead_events.repasse` (B3, cartão 7b143561).

Cada repasse ao closer vira um evento estruturado, sem sobrescrever o anterior
(o carimbo `metadata.handoff` sobrescreve). O evento é fail-soft: a mensagem-marcador
e o carimbo continuam iguais, porque follow-up, buffer, watchdog e conversões os leem.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.leads import repasse


@pytest.fixture(autouse=True)
def _qualificado_sem_rede(monkeypatch):
    """registrar_repasse agora grava também o evento `qualificado` (b67f1c6b), por
    outro módulo; sem isto os testes do helper bateriam na URL fake do Supabase."""
    monkeypatch.setattr("app.leads.qualificado.get_supabase", lambda: MagicMock())


def _sb_ok():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    return sb


# --------------------------------------------------------------------------- helper

def test_registrar_repasse_grava_evento(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    ok = repasse.registrar_repasse(
        lead_id="L1", conversation_id="C1", message_id="M1",
        occurred_at="2026-10-19T10:00:00-03:00", source="ia",
        vendedor_id="U1", vendedor="João", segmento="atacado", motivo="lead qualificado")
    assert ok is True
    sb.table.assert_called_with("lead_events")
    ev = sb.table.return_value.insert.call_args.args[0]
    assert ev["lead_id"] == "L1"
    assert ev["event_type"] == "repasse"
    assert ev["dedupe_key"] == "repasse:M1"
    assert ev["source"] == "ia"
    assert ev["occurred_at"] == "2026-10-19T10:00:00-03:00"
    assert ev["metadata"] == {"vendedor_id": "U1", "vendedor": "João", "segmento": "atacado",
                              "motivo": "lead qualificado", "conversation_id": "C1",
                              "message_id": "M1"}


def test_sem_occurred_at_deixa_o_default_do_banco(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    assert repasse.registrar_repasse(lead_id="L1", conversation_id="C1", message_id="M1",
                                     occurred_at=None, source="button_flow") is True
    ev = sb.table.return_value.insert.call_args.args[0]
    assert "occurred_at" not in ev


def test_registrar_repasse_fail_soft(monkeypatch):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("boom")
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    assert repasse.registrar_repasse(lead_id="L1", conversation_id=None, message_id="M1",
                                     occurred_at=None, source="button_flow") is False


def test_sem_message_id_nao_grava(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    assert repasse.registrar_repasse(lead_id="L1", conversation_id="C1", message_id=None,
                                     occurred_at=None, source="ia") is False
    sb.table.assert_not_called()


# ------------------------------------------------------------ caminho da IA (tools)

MARKER_ROW = {"id": "msg-marker-1", "created_at": "2026-10-19T13:00:00+00:00"}


def _save_message_fake(chamadas):
    def fake(lead_id, role, content, *a, **k):
        chamadas.append((role, content))
        if role == "system" and content.startswith("[encaminhar_humano] Lead encaminhado"):
            return dict(MARKER_ROW)
        return {"id": f"msg-{len(chamadas)}", "created_at": "2026-10-19T13:00:01+00:00"}
    return fake


def _tools_mockado(monkeypatch, updates):
    lead = {"id": "lead-1", "stage": "atacado", "phone": "+5511999999999", "metadata": {}}
    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: lead)
    monkeypatch.setattr("app.agent.tools.vendor_user_id_for_segment", lambda seg: "user-joao")
    monkeypatch.setattr("app.agent.tools.update_lead",
                        lambda lead_id, **kw: updates.append(kw))
    monkeypatch.setattr("app.agent.tools.cancel_followups_by_phone", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.tools.move_deal_to_vendor_pipeline", lambda *a, **k: True)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)
    monkeypatch.setattr("app.agent.tools.get_conversation_history",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem resumo")))
    monkeypatch.setattr("app.agent.tools.append_lead_observation", lambda *a, **k: None)


async def _encaminhar():
    from app.agent.tools import execute_tool
    return await execute_tool(
        "encaminhar_humano", {"vendedor": "Joao Bras", "motivo": "qualificado"},
        lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1")


@pytest.mark.asyncio
async def test_ia_registra_repasse_com_id_do_marcador(monkeypatch):
    updates, salvas = [], []
    _tools_mockado(monkeypatch, updates)
    monkeypatch.setattr("app.agent.tools.save_message", _save_message_fake(salvas))
    with patch("app.leads.repasse.registrar_repasse", return_value=True) as reg:
        await _encaminhar()
    reg.assert_called_once()
    kw = reg.call_args.kwargs
    assert kw["lead_id"] == "lead-1"
    assert kw["conversation_id"] == "conv-1"
    assert kw["message_id"] == "msg-marker-1"
    assert kw["occurred_at"] == MARKER_ROW["created_at"]
    assert kw["source"] == "ia"
    assert kw["vendedor_id"] == "user-joao"
    assert kw["vendedor"] == "Joao Bras"
    assert kw["segmento"] == "atacado"
    assert kw["motivo"] == "qualificado"


@pytest.mark.asyncio
async def test_ia_falha_do_evento_nao_muda_o_repasse(monkeypatch):
    # Rodada de referência (evento ok) x rodada com o evento explodindo: retorno da
    # tool, mensagens gravadas e carimbo metadata.handoff têm de ser os mesmos.
    resultados = []
    for efeito in (None, RuntimeError("lead_events fora")):
        updates, salvas = [], []
        _tools_mockado(monkeypatch, updates)
        monkeypatch.setattr("app.agent.tools.save_message", _save_message_fake(salvas))
        with patch("app.leads.repasse.registrar_repasse", side_effect=efeito,
                   return_value=True):
            ret = await _encaminhar()
        carimbos = [u["metadata"]["handoff"] for u in updates if "metadata" in u]
        assert carimbos, "carimbo metadata.handoff precisa existir"
        for c in carimbos:
            c.pop("at")
        resultados.append((ret, salvas, carimbos))
    assert resultados[0] == resultados[1]


# ------------------------------------------------- caminho dos botões (effects)

def _effects_mockado(save_side_effect=None):
    from contextlib import ExitStack
    pilha = ExitStack()
    p = lambda alvo, **kw: pilha.enter_context(patch(alvo, **kw))  # noqa: E731
    mocks = {
        "upd": p("app.button_flow.effects.update_lead"),
        "save": p("app.button_flow.effects.save_message",
                  side_effect=save_side_effect, return_value=dict(MARKER_ROW)),
        "obs": p("app.button_flow.effects.append_lead_observation"),
        "add": p("app.button_flow.effects.add_tags_to_lead"),
        "deal": p("app.button_flow.effects.get_open_deal", return_value=None),
        "mover": p("app.button_flow.effects.move_deal_to_stage_key", return_value=True),
    }
    return pilha, mocks


def _lead():
    return {"id": "lead-1", "phone": "5511999999999", "name": "Fulano",
            "stage": "atacado", "metadata": {}}


def test_botoes_registram_repasse_com_id_do_marcador():
    from app.button_flow import effects
    pilha, m = _effects_mockado()
    with pilha, patch("app.leads.repasse.registrar_repasse", return_value=True) as reg:
        effects._aplicar_handoff(_lead(), "conv-1", vendedor="Arthur")
    reg.assert_called_once()
    kw = reg.call_args.kwargs
    assert kw["lead_id"] == "lead-1"
    assert kw["conversation_id"] == "conv-1"
    assert kw["message_id"] == "msg-marker-1"
    assert kw["occurred_at"] == MARKER_ROW["created_at"]
    assert kw["source"] == "button_flow"
    assert kw["vendedor_id"] is None
    assert kw["vendedor"] == "Arthur"
    assert kw["segmento"] == "atacado"
    assert kw["motivo"]


def test_botoes_falha_do_evento_nao_muda_o_repasse():
    from app.button_flow import effects
    resultados = []
    for efeito in (None, RuntimeError("lead_events fora")):
        pilha, m = _effects_mockado()
        with pilha, patch("app.leads.repasse.registrar_repasse", side_effect=efeito,
                          return_value=True):
            effects._aplicar_handoff(_lead(), "conv-1", vendedor="Arthur")
        carimbos = [dict(c.kwargs["metadata"]["handoff"]) for c in m["upd"].call_args_list
                    if "metadata" in c.kwargs]
        assert carimbos
        for c in carimbos:
            c.pop("at")
        resultados.append((carimbos, [c.args for c in m["save"].call_args_list],
                           m["obs"].call_count))
    assert resultados[0] == resultados[1]


def test_botoes_marcador_que_falha_nao_gera_evento():
    from app.button_flow import effects
    pilha, m = _effects_mockado(save_side_effect=RuntimeError("messages fora"))
    with pilha, patch("app.leads.repasse.registrar_repasse", return_value=False) as reg:
        effects._aplicar_handoff(_lead(), "conv-1", vendedor="Arthur")
    # Sem marcador não há message_id: o helper recebe None e não grava.
    if reg.called:
        assert reg.call_args.kwargs["message_id"] is None


def test_botoes_carimbo_at_em_brt():
    from app.button_flow import effects
    pilha, m = _effects_mockado()
    with pilha, patch("app.leads.repasse.registrar_repasse", return_value=True):
        effects._aplicar_handoff(_lead(), "conv-1", vendedor="Arthur")
    carimbo = [c.kwargs["metadata"]["handoff"] for c in m["upd"].call_args_list
               if "metadata" in c.kwargs][0]
    assert carimbo["at"].endswith("-03:00")
