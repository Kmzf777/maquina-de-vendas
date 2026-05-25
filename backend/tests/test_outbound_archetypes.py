"""Testes unitários para os archetypes outbound O1-O4."""
import pytest
from scripts.rehearsal.outbound_archetypes import (
    ALL_OUTBOUND_ARCHETYPES,
    OUTBOUND_ARCHETYPES,
    O1, O2, O3, O4,
)


def test_all_archetypes_present():
    assert len(ALL_OUTBOUND_ARCHETYPES) == 4
    ids = [a.id for a in ALL_OUTBOUND_ARCHETYPES]
    assert ids == ["O1", "O2", "O3", "O4"]


def test_archetype_dict_keys():
    assert set(OUTBOUND_ARCHETYPES.keys()) == {
        "O1-confirmacao-qualificado",
        "O2-negacao-potencial",
        "O3-opt-out",
        "O4-textual-ambiguo",
    }


def test_first_messages_are_button_replies_or_text():
    """O1/O2/O3 iniciam com dict (button_reply), O4 com string."""
    assert isinstance(O1.first_message, dict)
    assert O1.first_message["type"] == "button_reply"
    assert O1.first_message["button_id"] == "sim"

    assert isinstance(O2.first_message, dict)
    assert O2.first_message["button_id"] == "nao"

    assert isinstance(O3.first_message, dict)
    assert O3.first_message["button_id"] == "parar_mensagens"

    assert isinstance(O4.first_message, str)


def test_hard_checks_defined():
    for arch in ALL_OUTBOUND_ARCHETYPES:
        assert len(arch.hard_checks) >= 1, f"{arch.id} sem hard_checks"


def test_forbids_defined():
    for arch in ALL_OUTBOUND_ARCHETYPES:
        assert len(arch.forbids) >= 1, f"{arch.id} sem forbids"
