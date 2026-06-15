"""Tests for the marcar_interesse tool — flag set/pop, schema presence, stage availability."""
import pytest
import asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_interest(conversation_id: str) -> None:
    """Ensure no stale state between tests."""
    from app.agent.tools import _interest_marked
    _interest_marked.pop(conversation_id, None)


# ---------------------------------------------------------------------------
# 1. execute_tool sets the flag; pop_interest_marked returns then clears it
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_marcar_interesse_sets_flag():
    """Calling marcar_interesse via execute_tool populates _interest_marked."""
    from app.agent.tools import execute_tool, pop_interest_marked

    conv_id = "test-conv-interesse-1"
    _reset_interest(conv_id)

    result = await execute_tool(
        "marcar_interesse",
        {"nivel": "quente", "motivo": "perguntou preço do atacado"},
        lead_id="lead-1",
        phone="+5511999999999",
        conversation_id=conv_id,
    )

    assert "quente" in result

    signal = pop_interest_marked(conv_id)
    assert signal is not None
    assert signal["nivel"] == "quente"
    assert "preço" in signal["motivo"]


@pytest.mark.asyncio
async def test_pop_interest_marked_clears_flag():
    """pop_interest_marked returns None on second call (flag consumed)."""
    from app.agent.tools import execute_tool, pop_interest_marked

    conv_id = "test-conv-interesse-2"
    _reset_interest(conv_id)

    await execute_tool(
        "marcar_interesse",
        {"nivel": "morno"},
        lead_id="lead-2",
        phone="+5511999999999",
        conversation_id=conv_id,
    )

    first = pop_interest_marked(conv_id)
    assert first is not None

    second = pop_interest_marked(conv_id)
    assert second is None


@pytest.mark.asyncio
async def test_pop_interest_marked_returns_none_when_not_set():
    """pop_interest_marked returns None if marcar_interesse was never called."""
    from app.agent.tools import pop_interest_marked

    result = pop_interest_marked("conv-never-set")
    assert result is None


@pytest.mark.asyncio
async def test_marcar_interesse_defaults_nivel_to_morno():
    """When nivel is omitted, it defaults to 'morno'."""
    from app.agent.tools import execute_tool, pop_interest_marked

    conv_id = "test-conv-interesse-3"
    _reset_interest(conv_id)

    await execute_tool(
        "marcar_interesse",
        {},
        lead_id="lead-3",
        phone="+5511999999999",
        conversation_id=conv_id,
    )

    signal = pop_interest_marked(conv_id)
    assert signal is not None
    assert signal["nivel"] == "morno"


@pytest.mark.asyncio
async def test_marcar_interesse_no_conversation_id_does_not_crash():
    """When conversation_id is empty, tool returns confirmation without setting flag."""
    from app.agent.tools import execute_tool, pop_interest_marked

    result = await execute_tool(
        "marcar_interesse",
        {"nivel": "quente"},
        lead_id="lead-4",
        phone="+5511999999999",
        conversation_id="",
    )

    # Should not raise and should return a string
    assert isinstance(result, str)
    # Nothing should be set for empty conversation_id
    assert pop_interest_marked("") is None


# ---------------------------------------------------------------------------
# 2. get_tools_for_stage includes marcar_interesse in every relevant stage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stage", ["secretaria", "atacado", "private_label", "exportacao", "consumo"])
def test_get_tools_for_stage_includes_marcar_interesse(stage):
    """marcar_interesse must appear in tools list for every relevant stage."""
    from app.agent.tools import get_tools_for_stage

    tools = get_tools_for_stage(stage)
    names = [t["function"]["name"] for t in tools]
    assert "marcar_interesse" in names, (
        f"marcar_interesse ausente no stage '{stage}'. Tools presentes: {names}"
    )


# ---------------------------------------------------------------------------
# 3. Tool schema is present in TOOLS_SCHEMA
# ---------------------------------------------------------------------------

def test_marcar_interesse_in_tools_schema():
    """TOOLS_SCHEMA must contain an entry named 'marcar_interesse'."""
    from app.agent.tools import TOOLS_SCHEMA

    names = [t["function"]["name"] for t in TOOLS_SCHEMA]
    assert "marcar_interesse" in names


def test_marcar_interesse_schema_structure():
    """marcar_interesse schema must have expected parameters."""
    from app.agent.tools import TOOLS_SCHEMA

    schema = next(
        t for t in TOOLS_SCHEMA if t["function"]["name"] == "marcar_interesse"
    )
    params = schema["function"]["parameters"]
    assert "nivel" in params["properties"]
    assert "motivo" in params["properties"]
    # required is [] (both params optional)
    assert schema["function"]["parameters"].get("required", []) == []


def test_marcar_interesse_nivel_enum():
    """nivel parameter must be an enum with 'morno' and 'quente'."""
    from app.agent.tools import TOOLS_SCHEMA

    schema = next(
        t for t in TOOLS_SCHEMA if t["function"]["name"] == "marcar_interesse"
    )
    nivel_prop = schema["function"]["parameters"]["properties"]["nivel"]
    assert set(nivel_prop["enum"]) == {"morno", "quente"}
