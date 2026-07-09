"""TDD Onda 2: estacionamento de turnos no LLM-down (substitui o handoff imediato).

Auditoria 08/07: o outage de 13min (17:39-17:52) queimou 2/9 respostas do run com
handoff CEGO — o lead mandou "Sim" e recebeu na hora o cartão do João, sem a Valéria
nunca ter falado. Handoff é ação DEFINITIVA (desliga a IA); um outage de minutos não
deveria custar o funil inteiro do lead.

Contrato novo: LLM fora → o turno é ESTACIONADO em Redis (hash llm:parked, 1 entrada
por conversa). O worker drena a cada tick: LLM voltou → responde o turno normalmente
(bolhas + save); ainda fora e dentro da janela → mantém; janela estourada
(LLM_PARK_MAX_MINUTES, default 30) → handoff pelo caminho atual (nunca fantasma).
Kill-switch: LLM_PARKING=off restaura o handoff imediato.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.buffer.parking as PK
from app.buffer import processor as P
from app.agent.orchestrator import LLMUnavailableError


def _entry(parked_minutes_ago=1, conv_id="conv-park-1"):
    parked_at = (datetime.now(timezone.utc) - timedelta(minutes=parked_minutes_ago)).isoformat()
    return conv_id, json.dumps({
        "lead_id": "lead-park-1", "phone": "5567999295671", "channel_id": "ch-1",
        "stage": "secretaria", "text": "Sim", "parked_at": parked_at,
    })


@pytest.fixture
def parked_redis(fake_redis, monkeypatch):
    monkeypatch.setattr(PK, "_get_parking_redis", lambda: fake_redis)
    return fake_redis


# ---------------------------------------------------------------------------
# park_turn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_park_turn_grava_no_redis(parked_redis):
    conversation = {"id": "conv-park-1", "stage": "secretaria", "channel_id": "ch-1"}
    lead = {"id": "lead-park-1"}
    ok = await PK.park_turn(conversation, lead, "5567999295671", "Sim")
    assert ok is True
    raw = await parked_redis.hget(PK.PARKED_KEY, "conv-park-1")
    data = json.loads(raw)
    assert data["lead_id"] == "lead-park-1"
    assert data["phone"] == "5567999295671"
    assert data["channel_id"] == "ch-1"
    assert data["text"] == "Sim"
    assert data["parked_at"]


# ---------------------------------------------------------------------------
# _handle_llm_down estaciona (e preserva contador/alerta/supressão de autoresponder)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_llm_down_estaciona_em_vez_de_handoff(monkeypatch):
    monkeypatch.delenv("LLM_PARKING", raising=False)
    lead = {"id": "lead-1", "phone": "5567999295671"}
    conversation = {"id": "conv-1", "stage": "secretaria", "channel_id": "ch-1"}
    with patch.object(P, "_record_llm_failure", new=AsyncMock(return_value=1)), \
         patch.object(P, "_broadcast_recently_active", return_value=False), \
         patch("app.buffer.parking.park_turn", new=AsyncMock(return_value=True)) as m_park, \
         patch("app.agent.tools.execute_tool", new=AsyncMock()) as m_tool:
        await P._handle_llm_down(lead, "5567999295671", conversation, inbound_text="Sim")
    m_park.assert_awaited_once()
    m_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_llm_down_off_mantem_handoff(monkeypatch):
    monkeypatch.setenv("LLM_PARKING", "off")
    lead = {"id": "lead-1", "phone": "5567999295671"}
    conversation = {"id": "conv-1", "stage": "secretaria"}
    with patch.object(P, "_record_llm_failure", new=AsyncMock(return_value=1)), \
         patch.object(P, "_broadcast_recently_active", return_value=False), \
         patch("app.buffer.parking.park_turn", new=AsyncMock()) as m_park, \
         patch("app.agent.tools.execute_tool", new=AsyncMock()) as m_tool:
        await P._handle_llm_down(lead, "5567999295671", conversation, inbound_text="Sim")
    m_park.assert_not_awaited()
    m_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_llm_down_autoresponder_nem_estaciona_nem_handoff(monkeypatch):
    monkeypatch.delenv("LLM_PARKING", raising=False)
    lead = {"id": "lead-1", "phone": "5567999295671"}
    conversation = {"id": "conv-1"}
    autoresponder = (
        "‎ Olá! Recebemos sua mensagem. Escolha uma opção:\n"
        "1. Cardápio https://gelateria.com/menu\n2. Horários https://gelateria.com/horarios"
    )
    with patch.object(P, "_record_llm_failure", new=AsyncMock(return_value=1)), \
         patch.object(P, "_broadcast_recently_active", return_value=False), \
         patch("app.buffer.parking.park_turn", new=AsyncMock()) as m_park, \
         patch("app.agent.tools.execute_tool", new=AsyncMock()) as m_tool:
        await P._handle_llm_down(lead, "5567999295671", conversation, inbound_text=autoresponder)
    m_park.assert_not_awaited()
    m_tool.assert_not_awaited()


# ---------------------------------------------------------------------------
# drain_parked_llm_turns
# ---------------------------------------------------------------------------

def _drain_patches(**over):
    """Patches padrão do caminho feliz do drain; sobrescreva pontos por teste."""
    provider = MagicMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid-x"}]})
    defaults = {
        "get_lead": MagicMock(return_value={"id": "lead-park-1", "ai_enabled": True,
                                            "phone": "5567999295671"}),
        "_fetch_conversation": MagicMock(return_value={
            "id": "conv-park-1", "stage": "secretaria", "channel_id": "ch-1",
            "agent_persona": "valeria_outbound",
        }),
        "_has_newer_activity": MagicMock(return_value=False),
        "run_agent": AsyncMock(return_value="oi, desculpa a demora\n\nera você mesmo?"),
        "get_channel_by_id": MagicMock(return_value={"id": "ch-1"}),
        "get_provider": MagicMock(return_value=provider),
        "save_message": MagicMock(),
        "execute_tool": AsyncMock(),
    }
    defaults.update(over)
    return provider, defaults


async def _run_drain(parked_redis, patches):
    with patch.multiple(PK, **patches), \
         patch.object(PK.asyncio, "sleep", new=AsyncMock()):
        return await PK.drain_parked_llm_turns()


@pytest.mark.asyncio
async def test_drain_sucesso_envia_salva_e_limpa(parked_redis):
    conv_id, raw = _entry(parked_minutes_ago=2)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches()

    resolved = await _run_drain(parked_redis, patches)

    assert resolved == 1
    assert provider.send_text.await_count >= 1
    assert patches["save_message"].called
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None
    patches["execute_tool"].assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_llm_ainda_fora_mantem_estacionado(parked_redis):
    conv_id, raw = _entry(parked_minutes_ago=2)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        run_agent=AsyncMock(side_effect=LLMUnavailableError("429")),
    )

    resolved = await _run_drain(parked_redis, patches)

    assert resolved == 0
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is not None
    patches["execute_tool"].assert_not_awaited()
    provider.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_drain_janela_estourada_faz_handoff(parked_redis):
    conv_id, raw = _entry(parked_minutes_ago=45)  # > LLM_PARK_MAX_MINUTES (30)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        run_agent=AsyncMock(side_effect=LLMUnavailableError("429")),
    )

    await _run_drain(parked_redis, patches)

    patches["execute_tool"].assert_awaited_once()
    assert patches["execute_tool"].await_args.args[0] == "encaminhar_humano"
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


@pytest.mark.asyncio
async def test_drain_superseded_pop_sem_envio(parked_redis):
    """Turno mais novo já respondeu a conversa → entrada morre sem reprocessar."""
    conv_id, raw = _entry(parked_minutes_ago=2)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        _has_newer_activity=MagicMock(return_value=True),
    )

    await _run_drain(parked_redis, patches)

    patches["run_agent"].assert_not_awaited()
    provider.send_text.assert_not_awaited()
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


@pytest.mark.asyncio
async def test_drain_ai_desligada_pop_sem_envio(parked_redis):
    """Humano assumiu (handoff/opt-out) enquanto estava estacionado → descarta."""
    conv_id, raw = _entry(parked_minutes_ago=2)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        get_lead=MagicMock(return_value={"id": "lead-park-1", "ai_enabled": False}),
    )

    await _run_drain(parked_redis, patches)

    patches["run_agent"].assert_not_awaited()
    provider.send_text.assert_not_awaited()
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


@pytest.mark.asyncio
async def test_drain_erro_generico_handoff_visivel(parked_redis):
    """Falha não-transitória no retry → handoff (nunca fantasma silencioso)."""
    conv_id, raw = _entry(parked_minutes_ago=2)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        run_agent=AsyncMock(side_effect=RuntimeError("bug")),
    )

    await _run_drain(parked_redis, patches)

    patches["execute_tool"].assert_awaited_once()
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None
