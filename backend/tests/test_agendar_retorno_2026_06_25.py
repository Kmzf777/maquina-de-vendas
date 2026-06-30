"""Cadência autônoma: tool agendar_retorno + handler ai_scheduled_return.

A IA agenda o próprio retorno (ex.: lead diz "falo com você na sexta") inserindo um job
em follow_up_jobs, sem depender do motor genérico de follow-up.
"""
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
import pytest


# ─────────────────────────── tool agendar_retorno ───────────────────────────

@pytest.mark.asyncio
async def test_agendar_retorno_insere_job_e_nao_desativa_ia(monkeypatch):
    from app.agent import tools

    captured = {}

    def fake_schedule(*, conversation_id, lead_id, channel_id, fire_at, metadata):
        captured.update(
            conversation_id=conversation_id, lead_id=lead_id,
            channel_id=channel_id, fire_at=fire_at, metadata=metadata,
        )
        return fire_at  # devolve o (já clampado) fire_at

    update_calls = []
    monkeypatch.setattr(tools, "schedule_ai_return", fake_schedule)
    monkeypatch.setattr(tools, "get_channel_for_lead", lambda lead_id: {"id": "ch-1"})
    monkeypatch.setattr(tools, "get_lead", lambda lead_id: {"id": lead_id, "name": "Carlos"})
    monkeypatch.setattr(tools, "update_lead", lambda lead_id, **kw: update_calls.append(kw))

    data_hora = (datetime.now(timezone.utc) + timedelta(days=2)).astimezone(
        timezone(timedelta(hours=-3))
    ).replace(microsecond=0).isoformat()

    with patch("app.agent.tools.save_message"):
        result = await tools.execute_tool(
            "agendar_retorno",
            {"data_hora": data_hora, "motivo": "lead disse que fala sexta", "contexto": "fechar pedido de 30kg"},
            lead_id="lead-1",
            phone="5511999999999",
            conversation_id="conv-1",
        )

    assert captured["lead_id"] == "lead-1"
    assert captured["channel_id"] == "ch-1"
    assert captured["metadata"]["motivo"] == "lead disse que fala sexta"
    assert captured["metadata"]["contexto"] == "fechar pedido de 30kg"
    # NÃO desativa a IA — o lead continua conversando normalmente
    assert update_calls == []
    assert "agendad" in result.lower()


@pytest.mark.asyncio
async def test_agendar_retorno_rejeita_data_invalida(monkeypatch):
    from app.agent import tools

    monkeypatch.setattr(tools, "schedule_ai_return", lambda **k: pytest.fail("não deveria agendar"))
    monkeypatch.setattr(tools, "get_channel_for_lead", lambda lead_id: {"id": "ch-1"})

    result = await tools.execute_tool(
        "agendar_retorno",
        {"data_hora": "sexta que vem", "motivo": "x"},
        lead_id="lead-1", phone="5511999999999", conversation_id="conv-1",
    )
    assert result.upper().startswith("ERRO")


@pytest.mark.asyncio
async def test_agendar_retorno_rejeita_data_passada(monkeypatch):
    from app.agent import tools

    monkeypatch.setattr(tools, "schedule_ai_return", lambda **k: pytest.fail("não deveria agendar"))
    monkeypatch.setattr(tools, "get_channel_for_lead", lambda lead_id: {"id": "ch-1"})

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    result = await tools.execute_tool(
        "agendar_retorno",
        {"data_hora": past, "motivo": "x"},
        lead_id="lead-1", phone="5511999999999", conversation_id="conv-1",
    )
    assert result.upper().startswith("ERRO")


def test_agendar_retorno_disponivel_em_todos_os_stages_de_conversa():
    from app.agent.tools import get_tools_for_stage

    for stage in ("secretaria", "atacado", "private_label", "exportacao", "consumo"):
        names = [t["function"]["name"] for t in get_tools_for_stage(stage)]
        assert "agendar_retorno" in names, f"agendar_retorno ausente no stage {stage}"


# ─────────────────────── schedule_ai_return (service) ────────────────────────

def test_schedule_ai_return_insere_job_ai_scheduled_return(monkeypatch):
    from app.follow_up import service

    inserted = {}

    class _Tbl:
        def insert(self, payload):
            inserted.update(payload)
            return self

        def execute(self):
            return MagicMock(data=[inserted])

    monkeypatch.setattr(service, "get_supabase", lambda: MagicMock(table=lambda n: _Tbl()))
    monkeypatch.setenv("REHEARSAL_MODE", "false")

    fire_at = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)  # sexta 09h SP-ish dentro da janela
    result = service.schedule_ai_return(
        conversation_id="conv-1", lead_id="lead-1", channel_id="ch-1",
        fire_at=fire_at, metadata={"motivo": "fala sexta"},
    )

    assert inserted["job_type"] == "ai_scheduled_return"
    assert inserted["lead_id"] == "lead-1"
    assert inserted["metadata"]["motivo"] == "fala sexta"
    assert isinstance(result, datetime)


# ──────────────────── _process_ai_scheduled_return (handler) ─────────────────

def _job(metadata=None, last_customer_message_at=None):
    return {
        "id": "job-1",
        "lead_id": "lead-1",
        "conversation_id": "conv-1",
        "channels": {"id": "ch-1", "mode": "ai", "provider": "meta_cloud"},
        "conversations": {"id": "conv-1", "stage": "atacado",
                          "last_customer_message_at": last_customer_message_at},
        "metadata": metadata or {"motivo": "fala sexta"},
    }


@pytest.mark.asyncio
async def test_handler_janela_aberta_roda_agente_e_envia(monkeypatch):
    from app.follow_up import scheduler

    now = datetime.now(timezone.utc)
    job = _job(last_customer_message_at=(now - timedelta(hours=1)).isoformat())

    lead = {"id": "lead-1", "phone": "5511999999999", "name": "Carlos",
            "ai_enabled": True, "last_customer_message_at": (now - timedelta(hours=1)).isoformat(),
            "metadata": {}, "wa_id": None}
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=lead)
    monkeypatch.setattr(scheduler, "get_supabase", lambda: sb)

    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
    monkeypatch.setattr(scheduler, "get_provider", lambda channel: provider)
    monkeypatch.setattr(scheduler, "resolve_send_target", lambda lead, phone: phone)
    monkeypatch.setattr(scheduler, "split_into_bubbles", lambda r: [r], raising=False)
    monkeypatch.setattr(scheduler, "_mark_sent", lambda jid: None)
    monkeypatch.setattr(scheduler, "save_message_conv", lambda **k: None)

    async def fake_run_agent(conversation, text, lead_context=None, agent_profile_id=None,
                             *, suppress_generic_fallback=False):
        assert "RETORNO AGENDADO" in text  # gatilho interno foi montado do metadata
        # Gatilho interno (reabertura proativa) deve suprimir o fallback genérico de re-engajamento.
        assert suppress_generic_fallback is True
        return "oi Carlos, voltando como combinamos"

    monkeypatch.setattr("app.agent.orchestrator.run_agent", fake_run_agent)

    await scheduler._process_ai_scheduled_return(job, now)

    provider.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_janela_fechada_dispara_reabertura_em_vez_de_cancelar(monkeypatch):
    """Eixo 3B: janela fechada NÃO cancela mais em silêncio — dispara template de reabertura
    e marca awaiting_reopen (ver test_window_reopen_2026_06_26.py p/ cobertura completa)."""
    from app.follow_up import scheduler

    now = datetime.now(timezone.utc)
    # última mensagem do cliente há 48h → janela fechada
    job = _job(last_customer_message_at=(now - timedelta(hours=48)).isoformat())
    job["channels"]["provider_config"] = {"phone_number_id": "pid"}

    lead = {"id": "lead-1", "phone": "5511999999999", "name": "Carlos",
            "ai_enabled": True, "last_customer_message_at": (now - timedelta(hours=48)).isoformat(),
            "metadata": {}, "wa_id": None}
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=lead)
    monkeypatch.setattr(scheduler, "get_supabase", lambda: sb)

    cancels, reopens = [], []
    monkeypatch.setattr(scheduler, "_cancel_job", lambda jid, reason: cancels.append((jid, reason)))
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: reopens.append(jid))
    monkeypatch.setattr(scheduler, "resolve_send_target", lambda lead, phone: phone)
    monkeypatch.setattr(scheduler, "save_message_conv", lambda **k: None)

    class FakeMeta:
        def __init__(self, cfg):
            pass

        async def send_template(self, to, name, components=None, language_code=None):
            return {"messages": [{"id": "wamid.r"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", FakeMeta)
    # Guard de compliance (utility-only) consulta a categoria do template de reabertura;
    # em prod 'continuar_conversa' é UTILITY. Fornecemos p/ o guard não bloquear sob mock genérico.
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")

    await scheduler._process_ai_scheduled_return(job, now)

    assert reopens == ["job-1"]
    assert not cancels  # não descarta em silêncio


@pytest.mark.asyncio
async def test_process_due_followups_roteia_ai_scheduled_return(monkeypatch):
    from app.follow_up import scheduler

    routed = []
    monkeypatch.setattr(scheduler, "get_due_followups",
                        lambda now: [{"job_type": "ai_scheduled_return", "id": "j1"}])

    async def fake_handler(job, now):
        routed.append(job["id"])

    monkeypatch.setattr(scheduler, "_process_ai_scheduled_return", fake_handler)

    await scheduler.process_due_followups(datetime.now(timezone.utc))
    assert routed == ["j1"]
