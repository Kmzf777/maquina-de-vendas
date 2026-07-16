"""TDD Wartime T1 (10/07/2026): parking de exaustão de budget/quota (modo "cofre vazio").

Problema: LLMBudgetExceededError herdava só de LLMUnavailableError, então o estouro do
teto diário (budget_guard) e a exaustão de quota diária do Google caíam no MESMO parking
de 30min. Como o bloqueio dura até a virada do dia, todo lead que respondia ao disparo
após o estouro era estacionado por 30min e depois recebia handoff CEGO definitivo
(ai_enabled=false) — o funil do dia inteiro queimado (repetição industrializada do
incidente de 08/07: 2/9 respostas com handoff cego em 13min de outage).

Contrato novo (spec 2026-07-10-wartime-budget-parking-alerts-design.md):
  1. 429 "per day" → LLMQuotaExhaustedError IMEDIATO (sem retry); 403 → exausto após
     3 retries; 429 comum e 5xx → comportamento atual (LLMUnavailableError).
  2. Budget estourado + lead escreve → turno estacionado com reason="budget", deadline
     na virada UTC + folga, mensagem de espera 1x (cooldown, suprimida em rehearsal),
     NENHUM handoff, NENHUM alerta llm_down.
  3. Drain: budget ainda estourado → pula sem API call; liberado → responde e limpa;
     deadline vencido com LLM fora → handoff visível; quota → throttle de retry.
  4. Entrada legada (sem deadline) → comportamento antigo (parked_at + 30min).
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from google.genai import errors as genai_errors

import app.buffer.parking as PK
from app.buffer import processor as P
from app.agent.gemini_client import user_content
from app.agent.orchestrator import (
    _generate_with_retry,
    LLMUnavailableError,
    LLMExhaustedError,
    LLMBudgetExceededError,
    LLMQuotaExhaustedError,
)


# ---------------------------------------------------------------------------
# Helpers (mesmo padrão de test_llm_retry_resilience_2026_07_01.py)
# ---------------------------------------------------------------------------

def _status_error(status: int, message: str = "") -> genai_errors.APIError:
    """Erro nativo google-genai com status em `.code` e mensagem custom (o marcador de
    quota diária é detectado em str(exc))."""
    body = {"error": {"code": status, "message": message or f"synthetic {status}",
                      "status": "SYNTHETIC"}}
    if status >= 500:
        return genai_errors.ServerError(status, body)
    return genai_errors.ClientError(status, body)


def _gen_raising(*exceptions) -> AsyncMock:
    """Mock de generate() que lança cada exceção em sequência; depois devolve 'OK'."""
    async def _side_effect(**kwargs):
        i = _side_effect.calls
        _side_effect.calls += 1
        if i < len(exceptions):
            raise exceptions[i]
        return "OK"
    _side_effect.calls = 0
    return AsyncMock(side_effect=_side_effect)


async def _call_with(m_gen: AsyncMock):
    with patch("app.agent.orchestrator.generate", new=m_gen), \
         patch("app.agent.orchestrator.asyncio.sleep", new=AsyncMock()):
        return await _generate_with_retry(
            model="gemini-2.5-flash", contents=[user_content("ping")],
        )


# ---------------------------------------------------------------------------
# Critério 1 — classificação de erro em _generate_with_retry
# ---------------------------------------------------------------------------

def test_hierarquia_retrocompativel():
    """Tudo continua sendo LLMUnavailableError — nenhum `except` existente quebra."""
    assert issubclass(LLMExhaustedError, LLMUnavailableError)
    assert issubclass(LLMBudgetExceededError, LLMExhaustedError)
    assert issubclass(LLMQuotaExhaustedError, LLMExhaustedError)
    assert issubclass(LLMQuotaExhaustedError, LLMUnavailableError)


async def test_429_per_day_exaure_imediato_sem_retry():
    m_gen = _gen_raising(
        _status_error(429, "Quota exceeded for quota metric 'requests per day'"),
    )
    with pytest.raises(LLMQuotaExhaustedError):
        await _call_with(m_gen)
    assert m_gen.await_count == 1  # retry seria inútil e queimaria RPM


async def test_429_perday_camelcase_exaure_imediato():
    m_gen = _gen_raising(
        _status_error(429, "GenerateRequestsPerDayPerProjectPerModel limit exceeded"),
    )
    with pytest.raises(LLMQuotaExhaustedError):
        await _call_with(m_gen)
    assert m_gen.await_count == 1


async def test_429_comum_mantem_retry_e_nao_vira_exausto():
    """429 de rate-limit por minuto: comportamento atual intocado."""
    m_gen = _gen_raising(_status_error(429, "requests per minute exceeded"))
    result = await _call_with(m_gen)
    assert result == "OK"
    assert m_gen.await_count == 2  # 1 falha + 1 sucesso


async def test_429_comum_esgotado_nao_e_exausto():
    m_gen = _gen_raising(*[_status_error(429, "requests per minute exceeded")] * 5)
    with pytest.raises(LLMUnavailableError) as exc_info:
        await _call_with(m_gen)
    assert not isinstance(exc_info.value, LLMExhaustedError)
    assert m_gen.await_count == 3  # _LLM_RETRY_ATTEMPTS


async def test_403_esgotado_vira_quota_exhausted():
    """403 (billing/permissão) mantém os 3 retries; ao esgotar → exaustão longa."""
    m_gen = _gen_raising(*[_status_error(403, "billing disabled")] * 5)
    with pytest.raises(LLMQuotaExhaustedError):
        await _call_with(m_gen)
    assert m_gen.await_count == 3


async def test_403_transitorio_recupera_sem_exaustao():
    """403 seguido de sucesso: os retries continuam funcionando como antes."""
    m_gen = _gen_raising(_status_error(403, "billing disabled"))
    result = await _call_with(m_gen)
    assert result == "OK"
    assert m_gen.await_count == 2


async def test_5xx_esgotado_permanece_transitorio():
    m_gen = _gen_raising(*[_status_error(503)] * 5)
    with pytest.raises(LLMUnavailableError) as exc_info:
        await _call_with(m_gen)
    assert not isinstance(exc_info.value, LLMExhaustedError)
    assert m_gen.await_count == 3


# ---------------------------------------------------------------------------
# Critério 2 — park_turn: reason + deadline + mensagem de espera
# ---------------------------------------------------------------------------

@pytest.fixture
def parked_redis(fake_redis, monkeypatch):
    monkeypatch.setattr(PK, "_get_parking_redis", lambda: fake_redis)
    return fake_redis


def _conv(conv_id="conv-wt-1"):
    return {"id": conv_id, "stage": "secretaria", "channel_id": "ch-1"}


def _lead():
    return {"id": "lead-wt-1", "phone": "5567999295671"}


def _iso(entry_field: str) -> datetime:
    return datetime.fromisoformat(entry_field.replace("Z", "+00:00"))


async def _park(parked_redis, reason, monkeypatch=None, conv_id="conv-wt-1", hold_mock=None):
    hold = hold_mock if hold_mock is not None else AsyncMock()
    with patch.object(PK, "_maybe_send_hold_message", new=hold):
        ok = await PK.park_turn(_conv(conv_id), _lead(), "5567999295671", "Sim", reason=reason)
    assert ok is True
    raw = await parked_redis.hget(PK.PARKED_KEY, conv_id)
    return json.loads(raw), hold


async def test_park_transient_deadline_30min_sem_hold_msg(parked_redis):
    entry, hold = await _park(parked_redis, "transient")
    assert entry["reason"] == "transient"
    assert _iso(entry["deadline"]) - _iso(entry["parked_at"]) == timedelta(minutes=30)
    hold.assert_not_awaited()  # espera é só p/ exaustão


async def test_park_budget_deadline_virada_utc_mais_folga(parked_redis, monkeypatch):
    monkeypatch.setenv("LLM_PARK_EXHAUSTED_GRACE_MINUTES", "30")
    entry, hold = await _park(parked_redis, "budget")
    assert entry["reason"] == "budget"
    parked_at = _iso(entry["parked_at"])
    esperado_virada = (parked_at + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    esperado = min(
        esperado_virada + timedelta(minutes=30),
        parked_at + timedelta(hours=26),
    )
    assert _iso(entry["deadline"]) == esperado
    hold.assert_awaited_once()


async def test_park_quota_deadline_virada_los_angeles(parked_redis, monkeypatch):
    monkeypatch.setenv("LLM_PARK_EXHAUSTED_GRACE_MINUTES", "30")
    entry, hold = await _park(parked_redis, "quota")
    assert entry["reason"] == "quota"
    parked_at = _iso(entry["parked_at"])
    la = ZoneInfo("America/Los_Angeles")
    local = parked_at.astimezone(la)
    esperado_virada = (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    ).astimezone(timezone.utc)
    esperado = min(
        esperado_virada + timedelta(minutes=30),
        parked_at + timedelta(hours=26),
    )
    assert _iso(entry["deadline"]) == esperado
    hold.assert_awaited_once()


async def test_park_exausto_respeita_teto_duro(parked_redis, monkeypatch):
    monkeypatch.setenv("LLM_PARK_EXHAUSTED_MAX_HOURS", "1")
    entry, _ = await _park(parked_redis, "budget")
    assert _iso(entry["deadline"]) - _iso(entry["parked_at"]) <= timedelta(hours=1)


def _hold_send_patches(provider=None):
    provider = provider or MagicMock()
    if not isinstance(provider.send_text, AsyncMock):
        provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid-hold"}]})
    return provider, {
        "get_channel_by_id": MagicMock(return_value={"id": "ch-1"}),
        "get_provider": MagicMock(return_value=provider),
        "resolve_send_target": MagicMock(return_value="5567999295671"),
        "save_message": MagicMock(),
    }


async def test_hold_msg_enviada_uma_vez_com_cooldown(parked_redis):
    provider, patches = _hold_send_patches()
    with patch.multiple(PK, **patches):
        ok1 = await PK.park_turn(_conv(), _lead(), "5567999295671", "Sim", reason="budget")
        # lead escreve de novo durante o estouro → re-park; SETNX segura a repetição
        ok2 = await PK.park_turn(_conv(), _lead(), "5567999295671", "e aí?", reason="budget")
    assert ok1 is True and ok2 is True
    provider.send_text.assert_awaited_once()
    assert provider.send_text.await_args.args[1] == PK._HOLD_MSG
    patches["save_message"].assert_called_once()
    # persistida como assistant p/ aparecer no CRM
    assert patches["save_message"].call_args.args[2] == "assistant"
    assert await parked_redis.get("llm:hold_msg:conv-wt-1") is not None


async def test_hold_msg_suprimida_em_rehearsal(parked_redis, monkeypatch):
    monkeypatch.setenv("REHEARSAL_MODE", "true")
    provider, patches = _hold_send_patches()
    with patch.multiple(PK, **patches):
        ok = await PK.park_turn(_conv(), _lead(), "5567999295671", "Sim", reason="budget")
    assert ok is True  # o park em si acontece normalmente
    provider.send_text.assert_not_awaited()


async def test_hold_msg_falha_de_envio_nao_impede_park(parked_redis):
    provider = MagicMock()
    provider.send_text = AsyncMock(side_effect=RuntimeError("meta 500"))
    provider, patches = _hold_send_patches(provider)
    with patch.multiple(PK, **patches):
        ok = await PK.park_turn(_conv(), _lead(), "5567999295671", "Sim", reason="budget")
    assert ok is True
    assert await parked_redis.hget(PK.PARKED_KEY, "conv-wt-1") is not None
    patches["save_message"].assert_not_called()  # sem envio real, sem marcador mentiroso


# ---------------------------------------------------------------------------
# Critério 2 (processor) — budget estaciona com reason, sem handoff, sem llm_down
# ---------------------------------------------------------------------------

def test_llm_down_reason_mapeia_tipo_da_excecao():
    assert P._llm_down_reason(LLMBudgetExceededError("teto")) == "budget"
    assert P._llm_down_reason(LLMQuotaExhaustedError("quota")) == "quota"
    assert P._llm_down_reason(LLMUnavailableError("429")) == "transient"
    assert P._llm_down_reason(RuntimeError("bug")) == "transient"


async def test_handle_llm_down_budget_estaciona_sem_handoff_sem_alerta(monkeypatch):
    monkeypatch.delenv("LLM_PARKING", raising=False)
    lead, conversation = _lead(), _conv()
    with patch.object(P, "_record_llm_failure", new=AsyncMock(return_value=5)) as m_count, \
         patch.object(P, "_broadcast_recently_active", return_value=False), \
         patch.object(P, "_fire_llm_down_alert") as m_alert, \
         patch("app.buffer.parking.park_turn", new=AsyncMock(return_value=True)) as m_park, \
         patch("app.agent.tools.execute_tool", new=AsyncMock()) as m_tool:
        await P._handle_llm_down(
            lead, "5567999295671", conversation, inbound_text="Sim", reason="budget",
        )
    m_park.assert_awaited_once()
    assert m_park.await_args.kwargs.get("reason") == "budget"
    m_tool.assert_not_awaited()      # nenhum handoff
    m_alert.assert_not_called()      # alerta dedicado de budget (Pacote B) cobre
    m_count.assert_awaited_once()    # contador consecutivo continua rodando


async def test_handle_llm_down_transient_mantem_alerta(monkeypatch):
    monkeypatch.delenv("LLM_PARKING", raising=False)
    with patch.object(P, "_record_llm_failure", new=AsyncMock(return_value=5)), \
         patch.object(P, "_broadcast_recently_active", return_value=False), \
         patch.object(P, "_fire_llm_down_alert") as m_alert, \
         patch("app.buffer.parking.park_turn", new=AsyncMock(return_value=True)):
        await P._handle_llm_down(_lead(), "5567999295671", _conv(), inbound_text="Sim")
    m_alert.assert_called_once()


async def test_handle_llm_down_quota_estaciona_com_reason_quota(monkeypatch):
    monkeypatch.delenv("LLM_PARKING", raising=False)
    with patch.object(P, "_record_llm_failure", new=AsyncMock(return_value=1)), \
         patch.object(P, "_broadcast_recently_active", return_value=False), \
         patch("app.buffer.parking.park_turn", new=AsyncMock(return_value=True)) as m_park:
        await P._handle_llm_down(
            _lead(), "5567999295671", _conv(), inbound_text="Sim", reason="quota",
        )
    assert m_park.await_args.kwargs.get("reason") == "quota"


# ---------------------------------------------------------------------------
# Critérios 3 e 4 — drain: skip de budget, throttle de quota, deadline, legado
# ---------------------------------------------------------------------------

def _entry(conv_id="conv-wt-1", parked_minutes_ago=2, reason=None, deadline_minutes=None,
           last_attempt_minutes_ago=None):
    """Entrada do hash llm:parked. reason/deadline None = entrada LEGADA (pré-wartime)."""
    now = datetime.now(timezone.utc)
    data = {
        "lead_id": "lead-wt-1", "phone": "5567999295671", "channel_id": "ch-1",
        "stage": "secretaria", "text": "Sim",
        "parked_at": (now - timedelta(minutes=parked_minutes_ago)).isoformat(),
    }
    if reason is not None:
        data["reason"] = reason
    if deadline_minutes is not None:
        data["deadline"] = (now + timedelta(minutes=deadline_minutes)).isoformat()
    if last_attempt_minutes_ago is not None:
        data["last_attempt_at"] = (now - timedelta(minutes=last_attempt_minutes_ago)).isoformat()
    return conv_id, json.dumps(data)


def _drain_patches(**over):
    provider = MagicMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid-x"}]})
    defaults = {
        "get_lead": MagicMock(return_value={"id": "lead-wt-1", "ai_enabled": True,
                                            "phone": "5567999295671"}),
        "_fetch_conversation": MagicMock(return_value={
            "id": "conv-wt-1", "stage": "secretaria", "channel_id": "ch-1",
        }),
        "_has_newer_activity": MagicMock(return_value=False),
        "run_agent": AsyncMock(return_value="oi! consegui voltar aqui"),
        "get_channel_by_id": MagicMock(return_value={"id": "ch-1"}),
        "get_provider": MagicMock(return_value=provider),
        "save_message": MagicMock(),
        "execute_tool": AsyncMock(),
    }
    defaults.update(over)
    return provider, defaults


async def _run_drain(patches, budget_exceeded=False):
    with patch.multiple(PK, **patches), \
         patch("app.agent.budget_guard.is_exceeded", return_value=budget_exceeded), \
         patch.object(PK.asyncio, "sleep", new=AsyncMock()):
        return await PK.drain_parked_llm_turns()


async def test_drain_budget_estourado_pula_sem_chamar_api(parked_redis):
    conv_id, raw = _entry(reason="budget", deadline_minutes=120)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches()

    resolved = await _run_drain(patches, budget_exceeded=True)

    assert resolved == 0
    patches["run_agent"].assert_not_awaited()       # custo zero
    provider.send_text.assert_not_awaited()
    patches["execute_tool"].assert_not_awaited()    # nenhum handoff dentro do prazo
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is not None


async def test_drain_budget_liberado_responde_e_limpa(parked_redis):
    conv_id, raw = _entry(reason="budget", deadline_minutes=120)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches()

    resolved = await _run_drain(patches, budget_exceeded=False)

    assert resolved == 1
    patches["run_agent"].assert_awaited_once()
    assert provider.send_text.await_count >= 1
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


async def test_drain_budget_deadline_vencido_handoff_visivel(parked_redis):
    """Último recurso: reset + folga passaram e o cofre segue vazio → handoff, nunca fantasma."""
    conv_id, raw = _entry(reason="budget", deadline_minutes=-5)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches()

    await _run_drain(patches, budget_exceeded=True)

    patches["run_agent"].assert_not_awaited()
    patches["execute_tool"].assert_awaited_once()
    assert patches["execute_tool"].await_args.args[0] == "encaminhar_humano"
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


async def test_drain_quota_dentro_do_throttle_nao_retenta(parked_redis, monkeypatch):
    monkeypatch.setenv("LLM_PARK_RETRY_MINUTES", "5")
    conv_id, raw = _entry(reason="quota", deadline_minutes=120, last_attempt_minutes_ago=1)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches()

    resolved = await _run_drain(patches)

    assert resolved == 0
    patches["run_agent"].assert_not_awaited()  # não queima RPM a cada tick de 30s
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is not None


async def test_drain_quota_apos_throttle_retenta_e_grava_last_attempt(parked_redis, monkeypatch):
    monkeypatch.setenv("LLM_PARK_RETRY_MINUTES", "5")
    conv_id, raw = _entry(reason="quota", deadline_minutes=120, last_attempt_minutes_ago=10)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        run_agent=AsyncMock(side_effect=LLMQuotaExhaustedError("per day")),
    )

    antes = datetime.now(timezone.utc)
    resolved = await _run_drain(patches)

    assert resolved == 0
    patches["run_agent"].assert_awaited_once()
    entry = json.loads(await parked_redis.hget(PK.PARKED_KEY, conv_id))
    # tentativa falha re-arma o throttle p/ o próximo tick
    assert datetime.fromisoformat(entry["last_attempt_at"]) >= antes - timedelta(seconds=5)
    patches["execute_tool"].assert_not_awaited()


async def test_drain_quota_sem_last_attempt_tenta_na_hora(parked_redis):
    conv_id, raw = _entry(reason="quota", deadline_minutes=120)
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches()

    resolved = await _run_drain(patches)

    assert resolved == 1
    patches["run_agent"].assert_awaited_once()
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


async def test_drain_entrada_legada_sem_deadline_expira_em_30min(parked_redis):
    """Critério 4: entrada estacionada por versão anterior (sem reason/deadline)
    mantém o contrato antigo — parked_at + 30min, depois handoff."""
    conv_id, raw = _entry(parked_minutes_ago=45)  # legada, > LLM_PARK_MAX_MINUTES
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        run_agent=AsyncMock(side_effect=LLMUnavailableError("429")),
    )

    await _run_drain(patches)

    patches["execute_tool"].assert_awaited_once()
    assert patches["execute_tool"].await_args.args[0] == "encaminhar_humano"
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is None


async def test_drain_entrada_legada_dentro_da_janela_mantem(parked_redis):
    conv_id, raw = _entry(parked_minutes_ago=2)  # legada, dentro dos 30min
    await parked_redis.hset(PK.PARKED_KEY, conv_id, raw)
    provider, patches = _drain_patches(
        run_agent=AsyncMock(side_effect=LLMUnavailableError("429")),
    )

    resolved = await _run_drain(patches)

    assert resolved == 0
    patches["execute_tool"].assert_not_awaited()
    assert await parked_redis.hget(PK.PARKED_KEY, conv_id) is not None
