"""F2 (06/11/2026): o repasse do fluxo de botões agenda o contato automático do João.

Entre 29/10 e 05/11, 25 leads repassados pelos botões ouviram "o João te responde em
instantes", não tocaram no cartão e ninguém falou com eles: `_aplicar_handoff` não
agendava `schedule_handoff_rescue`, que o repasse da IA (`encaminhar_humano`) agenda.
Relatório: Canastra-Content-Creator/relatorios/crm-sem-resposta-falso-2026-11.md.

O outro lado do contrato (o job desiste se o lead já escreveu ao João) está em
tests/test_handoff_rescue.py::test_handoff_rescue_skips_template_when_lead_already_replied_to_joao.
"""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.button_flow import effects
from app.button_flow.engine import Efeitos


@pytest.fixture
def lead() -> dict:
    return {"id": "lead-1", "phone": "5534999990000", "name": "Jussano Oliveira",
            "metadata": {}}


@contextmanager
def _repasse_mockado(*, conversa=None, schedule_erro: Exception | None = None):
    conversa = {"id": "c1", "channel_id": "canal-valeria"} if conversa is None else conversa
    with patch("app.button_flow.effects.add_tags_to_lead"), \
         patch("app.button_flow.effects.update_lead"), \
         patch("app.button_flow.effects.append_lead_observation"), \
         patch("app.button_flow.effects.save_message"), \
         patch("app.button_flow.effects.get_open_deal", return_value=None), \
         patch("app.button_flow.effects.move_deal_to_stage_key", return_value=True), \
         patch("app.leads.repasse.registrar_repasse"), \
         patch("app.conversations.service.get_conversation",
               return_value=conversa) as get_conv, \
         patch("app.follow_up.service.schedule_handoff_rescue",
               side_effect=schedule_erro) as schedule:
        yield SimpleNamespace(schedule=schedule, get_conv=get_conv)


def test_repasse_da_valeria_para_o_joao_agenda_o_contato_automatico(lead):
    with _repasse_mockado() as m:
        ok = effects.aplicar(Efeitos(handoff=True, vendedor="Joao Bras"), lead=lead,
                             conversation_id="c1", fluxo=effects.FLUXO_VALERIA)

    assert ok is True
    m.schedule.assert_called_once_with(
        lead_id="lead-1", lead_phone="5534999990000", conversation_id="c1",
        channel_id="canal-valeria", lead_name="Jussano Oliveira",
    )
    # Mesmo agendamento da IA: sem delay nem janela próprios (defaults de lá).
    assert "delay_minutes" not in m.schedule.call_args.kwargs
    assert "use_rescue_window" not in m.schedule.call_args.kwargs


def test_repasse_sem_vendedor_explicito_cai_no_joao_e_agenda(lead):
    with _repasse_mockado() as m:
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1",
                        fluxo=effects.FLUXO_VALERIA)
    m.schedule.assert_called_once()


def test_exportacao_do_arthur_nao_agenda(lead):
    """O Arthur atende fora do CRM, pelo fixo: a IA também não agenda (tools.py)."""
    with _repasse_mockado() as m:
        effects.aplicar(Efeitos(handoff=True, vendedor="Arthur"), lead=lead,
                        conversation_id="c1", fluxo=effects.FLUXO_VALERIA)
    m.schedule.assert_not_called()


def test_recuperacao_nao_agenda(lead):
    """A Recuperação roda no número pessoal do vendedor: o lead já está com ele."""
    with _repasse_mockado() as m:
        effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1",
                        fluxo=effects.FLUXO_RECUPERACAO)
    m.schedule.assert_not_called()


def test_lead_sem_telefone_nao_agenda_e_nao_quebra():
    sem_fone = {"id": "lead-1", "phone": "", "metadata": {}}
    with _repasse_mockado() as m:
        ok = effects.aplicar(Efeitos(handoff=True), lead=sem_fone, conversation_id="c1",
                             fluxo=effects.FLUXO_VALERIA)
    assert ok is True
    m.schedule.assert_not_called()


def test_conversa_sem_canal_nao_agenda(lead):
    with _repasse_mockado(conversa={"id": "c1"}) as m:
        ok = effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1",
                             fluxo=effects.FLUXO_VALERIA)
    assert ok is True
    m.schedule.assert_not_called()


def test_falha_ao_agendar_nao_derruba_o_repasse(lead):
    with _repasse_mockado(schedule_erro=RuntimeError("supabase fora")) as m:
        ok = effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1",
                             fluxo=effects.FLUXO_VALERIA)
    assert ok is True
    m.schedule.assert_called_once()


def test_sem_handoff_nao_agenda(lead):
    with _repasse_mockado() as m:
        effects.aplicar(Efeitos(silenciar_ia=True), lead=lead, conversation_id="c1",
                        fluxo=effects.FLUXO_VALERIA)
    m.schedule.assert_not_called()
