"""Rede de segurança do handoff durante indisponibilidade do LLM (27/07/2026).

Spec:  docs/superpowers/specs/2026-07-27-llm-outage-handoff-safety-net-design.md
Plano: docs/superpowers/plans/2026-07-27-llm-outage-handoff-safety-net-plan.md

Contexto: apagão de `gemini-2.5-flash` desde 22/07 17:48 BRT. O fallback de handoff
FUNCIONOU (29 handoffs medidos, todos entre 30,5 e 31,9 min do inbound), mas a auditoria
expôs três defeitos que só aparecem quando o apagão é LONGO:

  1. o parking de 30min vira silêncio inútil quando o LLM está fora há dias;
  2. todo job `handoff_rescue` morre no backstop `ai_disabled` (144/144 em 5 dias) —
     circular, porque é o handoff que desliga a IA (caso Wilson Demuth, 26/07);
  3. o dossiê do João sai vazio de informação quando o resumo por LLM falha (63/64).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.agent import summary as SUM
from app.buffer import parking as PK
from app.follow_up import scheduler as S


_PARKED_AT = datetime(2026, 7, 27, 14, 5, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fase 1 — deadline do parking sensível à DURAÇÃO do apagão
# ---------------------------------------------------------------------------


def test_transient_curto_mantem_30min():
    """Blip de LLM (contador zerado) segue com a janela integral da Onda 2."""
    got = PK._compute_deadline("transient", _PARKED_AT, 0)
    assert got == _PARKED_AT + timedelta(minutes=30)


def test_transient_abaixo_do_limiar_mantem_30min():
    got = PK._compute_deadline("transient", _PARKED_AT, 9)
    assert got == _PARKED_AT + timedelta(minutes=30)


def test_transient_apagao_sustentado_encurta():
    """No limiar exato (10 falhas consecutivas) a janela curta já vale."""
    got = PK._compute_deadline("transient", _PARKED_AT, 10)
    assert got == _PARKED_AT + timedelta(minutes=3)


def test_transient_apagao_longo_encurta():
    """158 = contador real medido em produção em 27/07 14:05."""
    got = PK._compute_deadline("transient", _PARKED_AT, 158)
    assert got == _PARKED_AT + timedelta(minutes=3)


def test_default_failure_count_preserva_comportamento():
    """Chamador que não passa a contagem mantém o contrato de hoje byte a byte."""
    got = PK._compute_deadline("transient", _PARKED_AT)
    assert got == _PARKED_AT + timedelta(minutes=30)


def test_budget_ignora_failure_count():
    """Modo cofre-vazio tem deadline próprio (virada do dia) — contagem não o perturba."""
    esperado = min(
        PK._next_midnight(_PARKED_AT, timezone.utc)
        + timedelta(minutes=PK._exhausted_grace_minutes()),
        _PARKED_AT + timedelta(hours=PK._exhausted_max_hours()),
    )
    assert PK._compute_deadline("budget", _PARKED_AT, 999) == esperado
    assert PK._compute_deadline("budget", _PARKED_AT, 0) == esperado


def test_quota_ignora_failure_count():
    esperado = min(
        PK._next_midnight(_PARKED_AT, PK._la_timezone())
        + timedelta(minutes=PK._exhausted_grace_minutes()),
        _PARKED_AT + timedelta(hours=PK._exhausted_max_hours()),
    )
    assert PK._compute_deadline("quota", _PARKED_AT, 999) == esperado
    assert PK._compute_deadline("quota", _PARKED_AT, 0) == esperado


def test_knobs_por_env(monkeypatch):
    monkeypatch.setenv("LLM_PARK_OUTAGE_FAILURES", "2")
    monkeypatch.setenv("LLM_PARK_OUTAGE_MINUTES", "1")
    assert PK._compute_deadline("transient", _PARKED_AT, 1) == _PARKED_AT + timedelta(minutes=30)
    assert PK._compute_deadline("transient", _PARKED_AT, 2) == _PARKED_AT + timedelta(minutes=1)


def test_rollback_por_env_restaura_30min(monkeypatch):
    """Knob de rollback documentado na spec: limiar altíssimo desliga o encurtamento."""
    monkeypatch.setenv("LLM_PARK_OUTAGE_FAILURES", "999999")
    assert PK._compute_deadline("transient", _PARKED_AT, 158) == _PARKED_AT + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_park_turn_propaga_failure_count():
    """A contagem chega ao Redis na entrada estacionada (diagnóstico no drain)."""
    import json

    fake_redis = AsyncMock()
    with patch.object(PK, "_get_parking_redis", return_value=fake_redis):
        ok = await PK.park_turn(
            {"id": "conv-1", "channel_id": "ch-1", "stage": "secretaria"},
            {"id": "lead-1"}, "5541991953960", "Oii",
            reason="transient", failure_count=158,
        )
    assert ok is True
    entry = json.loads(fake_redis.hset.await_args.args[2])
    assert entry["failure_count"] == 158
    # deadline curto: 3min após o park, não 30
    parked = datetime.fromisoformat(entry["parked_at"])
    assert datetime.fromisoformat(entry["deadline"]) - parked == timedelta(minutes=3)


# ---------------------------------------------------------------------------
# Fase 2 — `handoff_rescue` imune ao stop `ai_disabled`
# ---------------------------------------------------------------------------


def test_ai_disabled_nao_cancela_handoff_rescue():
    """O handoff DESLIGA a IA e é ele quem agenda o resgate — cancelar por
    `ai_disabled` mata o job na origem (144/144 em produção, 22-27/07)."""
    assert S._stop_reason_applies("ai_disabled", "handoff_rescue") is False


def test_ai_disabled_cancela_cadencia_normal():
    """Caso 5511910402026 (15/07), que motivou o backstop: segue valendo."""
    assert S._stop_reason_applies("ai_disabled", "standard") is True
    assert S._stop_reason_applies("ai_disabled", "followup") is True


def test_ai_disabled_cancela_lp_welcome():
    assert S._stop_reason_applies("ai_disabled", "lp_welcome") is True


def test_opt_out_cancela_handoff_rescue():
    """A isenção é só de `ai_disabled` — quem pediu para sair não recebe template."""
    assert S._stop_reason_applies("opt_out", "handoff_rescue") is True


def test_wrong_number_cancela_handoff_rescue():
    assert S._stop_reason_applies("wrong_number", "handoff_rescue") is True


def test_blacklisted_cancela_handoff_rescue():
    assert S._stop_reason_applies("blacklisted", "handoff_rescue") is True


def test_reason_none_nunca_aplica():
    assert S._stop_reason_applies(None, "handoff_rescue") is False
    assert S._stop_reason_applies(None, "standard") is False


def test_lead_stop_reason_inalterada():
    """Regressão: a função que classifica o LEAD não muda — quem decide se o motivo
    se aplica AO JOB é o chamador."""
    assert S._lead_stop_reason({"ai_enabled": False}) == "ai_disabled"
    assert S._lead_stop_reason({"opt_out": True}) == "opt_out"
    assert S._lead_stop_reason({"ai_enabled": True}) is None


def _make_rescue_job() -> dict:
    return {
        "id": "job-rescue-1",
        "job_type": "handoff_rescue",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5547992221012", "name": "Wilson"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": None},
        "metadata": {"lead_phone": "5547992221012"},
    }


async def _run_rescue_with_lead(fresh_lead):
    job = _make_rescue_job()
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._process_handoff_rescue",
               new_callable=AsyncMock) as mock_rescue:
        await S.process_due_followups(now=datetime.now(timezone.utc))
    return mock_cancel, mock_rescue


@pytest.mark.asyncio
async def test_backstop_deixa_rescue_passar_com_ia_desligada():
    """Caso Wilson Demuth: handoff feito (ai_enabled=False), o resgate PRECISA rodar."""
    fresh = {"id": "lead-1", "phone": "5547992221012", "opt_out": False,
             "ai_enabled": False, "stage": "atacado", "metadata": {}}
    mock_cancel, mock_rescue = await _run_rescue_with_lead(fresh)
    mock_rescue.assert_awaited_once()
    assert mock_cancel.call_args_list == []


@pytest.mark.asyncio
async def test_backstop_ainda_mata_rescue_de_lead_opt_out():
    fresh = {"id": "lead-1", "phone": "5547992221012", "opt_out": True,
             "ai_enabled": False, "stage": "atacado", "metadata": {}}
    mock_cancel, mock_rescue = await _run_rescue_with_lead(fresh)
    mock_rescue.assert_not_awaited()
    mock_cancel.assert_called_once_with("job-rescue-1", "opt_out")


# ---------------------------------------------------------------------------
# Fase 3 — dossiê determinístico quando o resumo por LLM falha
# ---------------------------------------------------------------------------


_LEAD = {"id": "lead-1", "name": "Wilson Demuth", "company": "Padaria Sul",
         "stage": "atacado"}

_HISTORY = [
    {"role": "user", "content": "Olá! Quero saber mais sobre compra por atacado."},
    {"role": "assistant", "content": "oi wilson, que bom te ver por aqui"},
    {"role": "user", "content": "Trabalho com uma padaria em Joinville"},
]


def _briefing(history=None, lead=None, motivo="teste", handoff_at="26/07/2026 16:04"):
    return SUM._fallback_briefing(
        history if history is not None else _HISTORY,
        lead if lead is not None else _LEAD,
        motivo, handoff_at,
    )


def test_briefing_contem_dados_do_lead():
    out = _briefing()
    assert "Wilson Demuth" in out
    assert "Padaria Sul" in out
    assert "atacado" in out


def test_briefing_contem_motivo_e_data():
    out = _briefing(motivo="IA temporariamente indisponível", handoff_at="26/07/2026 16:04")
    assert "IA temporariamente indisponível" in out
    assert "26/07/2026 16:04" in out


def test_briefing_inclui_mensagens_do_lead():
    out = _briefing()
    assert "compra por atacado" in out
    assert "padaria em Joinville" in out


def test_briefing_exclui_falas_da_valeria():
    """O dossiê existe porque a Valéria falhou — repetir a fala dela é ruído."""
    assert "que bom te ver por aqui" not in _briefing()


def test_briefing_limita_a_6_mensagens():
    history = [{"role": "user", "content": f"mensagem numero {i}"} for i in range(10)]
    out = _briefing(history=history)
    assert "mensagem numero 0" not in out
    assert "mensagem numero 3" not in out
    assert "mensagem numero 4" in out
    assert "mensagem numero 9" in out


def test_briefing_trunca_mensagem_longa():
    history = [{"role": "user", "content": "x" * 1000}]
    out = _briefing(history=history)
    assert "x" * 280 in out
    assert "x" * 400 not in out


def test_briefing_sem_historico_nao_quebra():
    out = _briefing(history=[])
    assert isinstance(out, str) and out.strip()
    assert "NOVO LEAD QUALIFICADO PELA VALÉRIA" in out


def test_briefing_campos_ausentes():
    out = _briefing(lead={"id": "lead-1"})
    assert "None" not in out
    assert "Não informado" in out


def test_briefing_mantem_cabecalho():
    assert _briefing().startswith("## NOVO LEAD QUALIFICADO PELA VALÉRIA")


def test_briefing_nunca_diz_erro_ao_gerar():
    """Regressão do texto que foi para 63 de 64 dossiês da janela do apagão."""
    assert "Erro ao gerar resumo" not in _briefing()


class _FakeResult:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


@pytest.mark.asyncio
async def test_excecao_do_llm_cai_no_briefing():
    with patch.object(SUM, "generate", new_callable=AsyncMock) as gen:
        gen.side_effect = RuntimeError("503 model unavailable")
        out = await SUM.generate_qualification_summary(
            _HISTORY, _LEAD, "gemini-2.5-flash-lite",
            motivo="IA indisponível", handoff_at="26/07/2026 16:04",
        )
    assert "Erro ao gerar resumo" not in out
    assert "Wilson Demuth" in out
    assert "compra por atacado" in out


@pytest.mark.asyncio
async def test_resposta_vazia_cai_no_briefing():
    with patch.object(SUM, "generate", new_callable=AsyncMock) as gen:
        gen.return_value = _FakeResult("")
        out = await SUM.generate_qualification_summary(
            _HISTORY, _LEAD, "gemini-2.5-flash-lite",
            motivo="IA indisponível", handoff_at="26/07/2026 16:04",
        )
    assert "Resumo indisponível" not in out
    assert "compra por atacado" in out


@pytest.mark.asyncio
async def test_sucesso_do_llm_inalterado():
    """Caminho feliz byte-idêntico ao de hoje."""
    with patch.object(SUM, "generate", new_callable=AsyncMock) as gen:
        gen.return_value = _FakeResult("## NOVO LEAD QUALIFICADO PELA VALÉRIA\nresumo real")
        out = await SUM.generate_qualification_summary(
            _HISTORY, _LEAD, "gemini-2.5-flash-lite",
        )
    assert out == "## NOVO LEAD QUALIFICADO PELA VALÉRIA\nresumo real"
