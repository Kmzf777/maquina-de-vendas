"""Rede de segurança (backstop) pós-catálogo (2026-07-04).

Leads em estágio `atacado`/`private_label` que já viram o catálogo (`metadata.catalog_shown`)
mas ainda NÃO tiveram um handoff real (`metadata.handoff` ausente) ficavam presos na cadência
genérica de follow-up indefinidamente — o próximo toque seria só mais uma mensagem automática
da Valéria, quando o sinal já indica que o lead deveria ter sido entregue ao vendedor humano.

Este teste cobre:
1. `should_proactive_handoff` (função pura de decisão) — todos os ramos.
2. O wiring em `process_due_followups`: quando a decisão é True, dispara o handoff
   (via `execute_tool`, mockado) e PULA o follow-up padrão deste job; quando é False,
   segue normalmente para os guards padrão.
3. Fail-soft: erro na rede de segurança nunca derruba o ciclo de follow-up.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.follow_up.service import should_proactive_handoff
from app.follow_up import scheduler as S


# ─── should_proactive_handoff: função pura, todos os ramos ───────────────────

def test_elegivel_atacado_catalogo_mostrado_sem_handoff():
    lead = {
        "id": "lead-1",
        "stage": "atacado",
        "metadata": {"catalog_shown": True, "catalog_shown_at": "2026-07-01T10:00:00Z"},
    }
    assert should_proactive_handoff(lead) is True


def test_elegivel_private_label_catalogo_mostrado_sem_handoff():
    lead = {
        "id": "lead-2",
        "stage": "private_label",
        "metadata": {"catalog_shown": True},
    }
    assert should_proactive_handoff(lead) is True


def test_nao_elegivel_sem_catalog_shown():
    """Stage correto, mas o catálogo nunca foi apresentado — não é o sinal que buscamos."""
    lead = {"id": "lead-3", "stage": "atacado", "metadata": {}}
    assert should_proactive_handoff(lead) is False


def test_nao_elegivel_catalog_shown_false():
    """catalog_shown explicitamente False (não apenas ausente)."""
    lead = {"id": "lead-4", "stage": "atacado", "metadata": {"catalog_shown": False}}
    assert should_proactive_handoff(lead) is False


def test_nao_elegivel_ja_com_handoff():
    """Já existe um handoff real — não deve duplicar a entrega ao vendedor."""
    lead = {
        "id": "lead-5",
        "stage": "atacado",
        "metadata": {
            "catalog_shown": True,
            "handoff": {"vendedor": "João Brás", "motivo": "x", "at": "2026-07-01T10:00:00Z"},
        },
    }
    assert should_proactive_handoff(lead) is False


def test_nao_elegivel_stage_consumo():
    """Segmento fora de {atacado, private_label} não entra no backstop (ex.: consumo/varejo)."""
    lead = {"id": "lead-6", "stage": "consumo", "metadata": {"catalog_shown": True}}
    assert should_proactive_handoff(lead) is False


def test_nao_elegivel_stage_secretaria():
    lead = {"id": "lead-7", "stage": "secretaria", "metadata": {"catalog_shown": True}}
    assert should_proactive_handoff(lead) is False


def test_nao_elegivel_stage_ausente():
    lead = {"id": "lead-8", "metadata": {"catalog_shown": True}}
    assert should_proactive_handoff(lead) is False


def test_nao_elegivel_lead_none():
    """Falha ao reler o lead (ou lead inexistente) → fail-safe: não dispara handoff."""
    assert should_proactive_handoff(None) is False


def test_nao_elegivel_metadata_ausente():
    lead = {"id": "lead-9", "stage": "atacado"}
    assert should_proactive_handoff(lead) is False


def test_elegivel_ignora_outros_campos_de_metadata():
    """Outras chaves em metadata (ex.: qualificacao) não interferem na decisão."""
    lead = {
        "id": "lead-10",
        "stage": "private_label",
        "metadata": {
            "catalog_shown": True,
            "qualificacao": {"finalidade": "revenda", "volume": "500kg", "urgencia": "alta"},
        },
    }
    assert should_proactive_handoff(lead) is True


# ─── Wiring em process_due_followups ─────────────────────────────────────────

def _make_job(**overrides) -> dict:
    job = {
        "id": "job-1",
        "job_type": "standard",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 2,
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Carlos"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {
            "id": "conv-1",
            "stage": "atacado",
            "followup_enabled": True,
            # Sem last_customer_message_at: se o backstop NÃO disparar, o guard padrão
            # seguinte ("window_expired") cancela o job — usamos isso para provar que o
            # fluxo padrão foi alcançado quando a decisão é False/falha.
            "last_customer_message_at": None,
        },
        "metadata": {},
    }
    job.update(overrides)
    return job


@pytest.mark.asyncio
async def test_wiring_dispara_handoff_proativo_e_pula_followup_padrao():
    """Lead elegível: encaminhar_humano é chamado via execute_tool, o job atual é
    cancelado com o motivo do backstop, e o follow-up padrão (LLM/envio) NUNCA roda."""
    job = _make_job()
    fresh_lead = {
        "id": "lead-1",
        "phone": "5511999999999",
        "stage": "atacado",
        "metadata": {"catalog_shown": True},
    }
    mock_execute_tool = AsyncMock(return_value="ok")
    mock_provider = AsyncMock()

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.agent.tools.execute_tool", mock_execute_tool), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler.get_provider", return_value=mock_provider), \
         patch("app.follow_up.scheduler._generate_followup_message") as mock_generate:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_execute_tool.assert_awaited_once()
    call = mock_execute_tool.await_args
    assert call.args[0] == "encaminhar_humano"
    assert call.args[1] == {
        "vendedor": "João Brás",
        "motivo": "handoff proativo — qualificado inativo pos-catalogo",
    }
    assert call.kwargs["lead_id"] == "lead-1"
    assert call.kwargs["conversation_id"] == "conv-1"
    assert call.kwargs["phone"] == "5511999999999"

    mock_cancel.assert_called_once_with("job-1", "proactive_handoff_pos_catalogo")
    mock_sent.assert_not_called()
    mock_generate.assert_not_called()
    mock_provider.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_wiring_nao_dispara_quando_lead_nao_elegivel():
    """Lead não elegível (já com handoff): o backstop não age e o job segue para o
    guard padrão seguinte (window_expired, dado o cenário sem last_customer_message_at)."""
    job = _make_job()
    fresh_lead = {
        "id": "lead-1",
        "phone": "5511999999999",
        "stage": "atacado",
        "metadata": {"catalog_shown": True, "handoff": {"vendedor": "João Brás"}},
    }
    mock_execute_tool = AsyncMock(return_value="ok")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.agent.tools.execute_tool", mock_execute_tool), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_execute_tool.assert_not_awaited()
    # Chegou no guard padrão de janela ausente — prova que o fluxo normal foi alcançado.
    mock_cancel.assert_called_once_with("job-1", "window_expired")


@pytest.mark.asyncio
async def test_wiring_fail_soft_erro_no_backstop_nao_derruba_o_ciclo():
    """Erro ao reler o lead para a decisão (ex.: falha de DB) é logado e o ciclo de
    follow-up CONTINUA normalmente — nunca propaga a exceção nem trava o tick."""
    job = _make_job()
    mock_execute_tool = AsyncMock(return_value="ok")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", side_effect=RuntimeError("db down")), \
         patch("app.agent.tools.execute_tool", mock_execute_tool), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        # Não deve levantar.
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_execute_tool.assert_not_awaited()
    # Seguiu para o guard padrão (window_expired) em vez de travar o tick.
    mock_cancel.assert_called_once_with("job-1", "window_expired")


@pytest.mark.asyncio
async def test_wiring_canal_humano_tem_prioridade_sobre_backstop():
    """Guard de canal humano roda ANTES do backstop — mesmo um lead elegível não deve
    disparar handoff proativo quando o canal já é modo humano (já sob controle humano)."""
    job = _make_job(channels={"id": "ch-1", "mode": "human", "provider_config": {}})
    fresh_lead = {
        "id": "lead-1",
        "phone": "5511999999999",
        "stage": "atacado",
        "metadata": {"catalog_shown": True},
    }
    mock_execute_tool = AsyncMock(return_value="ok")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.agent.tools.execute_tool", mock_execute_tool), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_execute_tool.assert_not_awaited()
    mock_cancel.assert_called_once_with("job-1", "human_channel")
