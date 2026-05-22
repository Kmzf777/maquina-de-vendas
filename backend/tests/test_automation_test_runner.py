# backend/tests/test_automation_test_runner.py
import pytest
from app.automation.test_runner import _build_node_sequence, _format_sse


class TestBuildNodeSequence:
    def test_linear_sequence(self):
        nodes = [
            {"id": "a", "type": "trigger", "next_node_id": "b", "yes_node_id": None, "no_node_id": None},
            {"id": "b", "type": "send",    "next_node_id": "c", "yes_node_id": None, "no_node_id": None},
            {"id": "c", "type": "end",     "next_node_id": None, "yes_node_id": None, "no_node_id": None},
        ]
        result = _build_node_sequence(nodes)
        assert [n["id"] for n in result] == ["b", "c"]  # trigger is skipped

    def test_empty_when_only_trigger(self):
        nodes = [{"id": "a", "type": "trigger", "next_node_id": None, "yes_node_id": None, "no_node_id": None}]
        assert _build_node_sequence(nodes) == []


class TestFormatSSE:
    def test_format(self):
        result = _format_sse({"node_id": "abc", "status": "running"})
        assert result == 'data: {"node_id": "abc", "status": "running"}\n\n'
