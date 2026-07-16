"""Sentinel ciente do handoff em CASCATA — fix S1, auditoria 2026-07-11.

Contexto forense (caso Prof. Sebastião, 11/07 15:29 BRT):
  qualificar_lead com finalidade+volume chama encaminhar_humano DENTRO do
  execute_tool (cascata) — o nome "encaminhar_humano" nunca aparece nos
  function_calls do turno. O sentinel antigo (`any(fc.name == "encaminhar_humano")`)
  não disparava, o turno seguia para a chamada pós-tool, o LLM verbalizava a
  transferência e a GUARDA DETERMINÍSTICA DE HANDOFF VERBALIZADO executava um
  SEGUNDO encaminhar_humano → 2 despedidas + 2 cartões em ~15s.

Mudanças validadas aqui:
  1. Cenário do bug: qualificar_lead cujo resultado começa com HANDOFF_RESULT_PREFIX
     → run_agent retorna None (sentinel), SEM chamada pós-tool e SEM 2º handoff
     pela guarda verbal.
  2. Regressão: qualificar_lead com retorno normal (âncoras incompletas) não seta
     a flag — o turno segue para a chamada pós-tool normalmente.
  3. Regressão: handoff explícito por tool-call continua retornando None.
  4. Puro: execute_tool("qualificar_lead", âncoras completas) propaga verbatim o
     retorno da cascata — string que começa com HANDOFF_RESULT_PREFIX.
"""
import pytest
from unittest.mock import AsyncMock, patch

from tests.gemini_fakes import fake_text, fake_tool_calls


# ---------------------------------------------------------------------------
# Helpers (mesmo padrão de test_handoff_verbal_guard_2026_06_30.py)
# ---------------------------------------------------------------------------

def _conversation(stage: str = "atacado") -> dict:
    return {
        "id": "conv-cascade-001",
        "stage": stage,
        "leads": {
            "id": "lead-cascade-001",
            "name": "Prof. Sebastião",
            "phone": "5511900000077",
            "ai_enabled": True,
        },
    }


def _history_one_user_msg() -> list:
    return [
        {
            "role": "user",
            "content": "quero revender, uns 500kg por mês",
            "stage": "atacado",
            "created_at": "2026-07-11T15:29:00Z",
            "wamid": "wamid-cascade-01",
            "quoted_wamid": None,
            "message_type": "text",
            "metadata": None,
        }
    ]


_QUALIFICAR_FC = fake_tool_calls(
    [("qualificar_lead", {"finalidade": "Revenda", "volume": "500kg a 1 tonelada mensal"})]
)


# ---------------------------------------------------------------------------
# Secao 1: o cenário do bug — cascata via qualificar_lead dispara o sentinel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cascata_qualificar_lead_dispara_sentinel_sem_segundo_handoff():
    """Handoff em cascata → None; sem chamada pós-tool; guarda verbal nunca roda."""
    from app.agent.orchestrator import run_agent

    m_gen = AsyncMock(return_value=_QUALIFICAR_FC)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cascade-001", "phone": "5511900000077", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="Lead encaminhado para João Brás") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation(), "quero revender, uns 500kg por mês")

    # Sentinel: handoff (mesmo em cascata) retorna None
    assert result is None, f"esperado None (handoff sentinel), got {result!r}"

    # execute_tool rodou EXATAMENTE 1 vez (qualificar_lead) e NUNCA com
    # encaminhar_humano — prova que a guarda verbal não disparou o 2º handoff
    # (só 1 despedida + 1 cartão pro lead).
    assert mock_exec.await_count == 1, (
        f"execute_tool deveria rodar 1x, rodou {mock_exec.await_count}x: "
        f"{[c.args[0] for c in mock_exec.call_args_list]}"
    )
    for call in mock_exec.call_args_list:
        assert call.args[0] != "encaminhar_humano", (
            "guarda verbal não pode disparar um 2º encaminhar_humano quando o "
            "handoff já rodou em cascata"
        )
    assert mock_exec.call_args_list[0].args[0] == "qualificar_lead"

    # Sem chamada PÓS-TOOL: o LLM nunca teve a chance de verbalizar a transferência.
    assert m_gen.await_count == 1, (
        f"generate deveria rodar 1x (sem pós-tool), rodou {m_gen.await_count}x"
    )


# ---------------------------------------------------------------------------
# Secao 2: regressão — retorno normal do qualificar_lead NÃO seta a flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_qualificar_lead_sem_handoff_turno_segue_normal():
    """Âncoras incompletas (retorno normal) → turno segue pra chamada pós-tool."""
    from app.agent.orchestrator import run_agent

    final_text = "legal, e qual volume você pensa?"
    m_gen = AsyncMock(side_effect=[_QUALIFICAR_FC, fake_text(final_text)])

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cascade-002", "phone": "5511900000077", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="Âncoras de qualificação registradas.") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation(), "quero revender")

    assert result == final_text, f"esperado texto final normal, got {result!r}"
    assert mock_exec.await_count == 1
    assert m_gen.await_count == 2, "esperada a chamada pós-tool (turno normal)"


# ---------------------------------------------------------------------------
# Secao 3: regressão — handoff explícito por tool-call preservado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handoff_explicito_por_tool_call_continua_retornando_none():
    """encaminhar_humano explícito nos function_calls → None (comportamento atual)."""
    from app.agent.orchestrator import run_agent

    explicit_fc = fake_tool_calls(
        [("encaminhar_humano", {"mensagem_despedida": "seu atendimento segue com o João"})]
    )
    m_gen = AsyncMock(return_value=explicit_fc)

    with patch("app.agent.orchestrator.get_history", return_value=_history_one_user_msg()), \
         patch("app.agent.orchestrator.get_lead", return_value={
             "id": "lead-cascade-003", "phone": "5511900000077", "ai_enabled": True
         }), \
         patch("app.agent.orchestrator.execute_tool",
               new_callable=AsyncMock,
               return_value="Lead encaminhado para João Brás") as mock_exec, \
         patch("app.agent.orchestrator.track_token_usage"), \
         patch("app.agent.orchestrator.generate", new=m_gen):
        result = await run_agent(_conversation(), "quero falar com um humano")

    assert result is None
    assert mock_exec.await_count == 1
    assert mock_exec.call_args_list[0].args[0] == "encaminhar_humano"
    assert m_gen.await_count == 1


# ---------------------------------------------------------------------------
# Secao 4: puro — a cascata real do execute_tool propaga o prefixo verbatim
# ---------------------------------------------------------------------------

def _base_mocks(monkeypatch, stage="atacado", metadata=None):
    """Réplica de test_handoff_proativo_2026_07_04._base_mocks (fluxo de handoff)."""
    updates = []
    lead = {"id": "lead-1", "stage": stage, "phone": "+5511999999999", "metadata": metadata or {}}
    monkeypatch.setattr("app.agent.tools.get_lead", lambda lead_id: dict(lead))
    monkeypatch.setattr("app.agent.tools.update_lead", lambda lead_id, **kw: updates.append(kw) or None)
    monkeypatch.setattr("app.agent.tools.create_deal", lambda lead_id, title, **kw: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.move_deal_to_vendor_pipeline", lambda *a, **k: {"id": "deal-1"})
    monkeypatch.setattr("app.agent.tools.move_open_deal_for_handoff", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.tools.get_channel_for_lead", lambda lead_id: None)
    monkeypatch.setattr("app.agent.tools.schedule_handoff_rescue", lambda **kw: None)
    monkeypatch.setattr("app.agent.tools.cancel_followups_by_phone", lambda *a, **k: None)
    return updates


@pytest.mark.asyncio
async def test_execute_tool_qualificar_lead_cascata_retorna_prefixo(monkeypatch):
    """execute_tool real: âncoras completas → retorno começa com HANDOFF_RESULT_PREFIX.

    É essa propagação verbatim que o sentinel do orchestrator usa para detectar
    a cascata — se este contrato quebrar, o bug do 2º handoff volta.
    """
    from app.agent.tools import execute_tool, HANDOFF_RESULT_PREFIX

    _base_mocks(monkeypatch, stage="atacado")
    monkeypatch.setattr(
        "app.agent.tools.vendor_user_id_for_segment",
        lambda seg: "1c3c78ed-ef47-4dca-9a63-2052f28e8fd6",
    )

    with patch("app.agent.tools.save_message"):
        result = await execute_tool(
            "qualificar_lead",
            {"finalidade": "Revenda", "volume": "500kg"},
            lead_id="lead-1", phone="+5511999999999", conversation_id="conv-1",
        )

    assert isinstance(result, str)
    assert result.startswith(HANDOFF_RESULT_PREFIX), (
        f"retorno da cascata deve começar com {HANDOFF_RESULT_PREFIX!r}, got {result!r}"
    )
