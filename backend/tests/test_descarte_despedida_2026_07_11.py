"""Despedida do descarte enviada PELA PRÓPRIA TOOL (forense 11/07).

Causa raiz: registrar_sem_interesse_atual/registrar_optout desligam ai_enabled no
meio do turno e a trava B2 (_ai_still_enabled) aborta as bolhas do PRÓPRIO turno —
a despedida que o prompt manda escrever nunca sai (leads "Sim" e Anderson: mensagem
educada do lead → marcador system → silêncio). Paridade com encaminhar_humano: a
tool recebe `mensagem_despedida`, envia ANTES de desligar a flag e persiste a bolha.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import tools as T


def _channel():
    return {"id": "ch-1", "provider": "meta_cloud", "provider_config": {}}


def _provider(wamid="wamid.BYE1"):
    p = AsyncMock()
    p.send_text = AsyncMock(return_value={"messages": [{"id": wamid}]})
    return p


def _patches(provider, calls, channel=True, despedida_ja_enviada=False):
    """Patches comuns; `calls` registra a ordem send_text × update_lead."""
    def _track_update(*a, **k):
        calls.append(("update_lead", k))
        return {}

    async def _track_send(to, body):
        calls.append(("send_text", body))
        return {"messages": [{"id": "wamid.BYE1"}]}

    provider.send_text = AsyncMock(side_effect=_track_send)

    return [
        patch.object(T, "update_lead", side_effect=_track_update),
        patch.object(T, "get_lead", return_value={"id": "lead-1", "phone": "+551199", "metadata": {}}),
        patch.object(T, "lead_has_active_relationship", return_value=False),
        patch.object(T, "move_lead_deals_to_perdido"),
        patch.object(T, "cancel_followups_by_phone"),
        patch.object(T, "apply_optout_side_effects"),
        patch.object(T, "append_lead_observation"),
        patch.object(T, "save_message"),
        patch.object(T, "get_channel_for_lead", return_value=_channel() if channel else None),
        patch.object(T, "get_provider", return_value=provider),
        patch.object(T, "resolve_send_target", side_effect=lambda lead, phone: phone),
        patch.object(T, "_despedida_ja_enviada", return_value=despedida_ja_enviada),
    ]


async def _run(tool, args, patches):
    from contextlib import ExitStack
    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        result = await T.execute_tool(tool, args, "lead-1", "+551199", "conv-1")
    return result, mocks


@pytest.mark.asyncio
async def test_sem_interesse_envia_despedida_do_llm_antes_de_desligar_ia():
    calls: list = []
    provider = _provider()
    # Motivo de REJEIÇÃO legítima: "lead vai analisar" era adiamento morno e agora é
    # recusado pela guarda 18C (varredura 12/07, caso Rogério) — este teste valida a
    # MECÂNICA da despedida, então usa um motivo que passa pela guarda.
    result, mocks = await _run(
        "registrar_sem_interesse_atual",
        {"motivo": "lead reafirmou que nao tem interesse, achou caro", "mensagem_despedida": "tranquilo, fico por aqui\n\nquando quiser é só chamar"},
        _patches(provider, calls),
    )
    assert "sem interesse" in result.lower() or "Lead marcado" in result
    sends = [c for c in calls if c[0] == "send_text"]
    updates = [c for c in calls if c[0] == "update_lead" and c[1].get("ai_enabled") is False]
    assert len(sends) == 1
    assert sends[0][1].startswith("tranquilo, fico por aqui")
    # ORDEM: despedida sai ANTES do ai_enabled=False (senão a B2 do processor engole)
    assert calls.index(sends[0]) < calls.index(updates[0])


@pytest.mark.asyncio
async def test_sem_interesse_sem_param_usa_despedida_default():
    calls: list = []
    provider = _provider()
    await _run("registrar_sem_interesse_atual", {"motivo": "x"}, _patches(provider, calls))
    sends = [c for c in calls if c[0] == "send_text"]
    assert len(sends) == 1
    assert sends[0][1] == T._SEM_INTERESSE_MSG


@pytest.mark.asyncio
async def test_sem_interesse_persiste_bolha_da_despedida():
    calls: list = []
    provider = _provider()
    patches = _patches(provider, calls)
    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        with patch.object(T, "save_message") as mock_save:
            await T.execute_tool(
                "registrar_sem_interesse_atual", {"motivo": "x"}, "lead-1", "+551199", "conv-1",
            )
    assistant_saves = [c for c in mock_save.call_args_list if c.args[1] == "assistant"]
    assert len(assistant_saves) == 1
    assert assistant_saves[0].args[2] == T._SEM_INTERESSE_MSG
    assert assistant_saves[0].kwargs.get("wamid") == "wamid.BYE1"


@pytest.mark.asyncio
async def test_sem_interesse_falha_no_envio_ainda_descarta():
    calls: list = []
    provider = _provider()
    patches = _patches(provider, calls)
    provider.send_text = AsyncMock(side_effect=RuntimeError("janela fechada"))
    result, _ = await _run("registrar_sem_interesse_atual", {"motivo": "x"}, patches)
    updates = [c for c in calls if c[0] == "update_lead" and c[1].get("ai_enabled") is False]
    assert len(updates) == 1  # descarte procede mesmo sem despedida (fail-soft)
    assert "ERRO" not in result


@pytest.mark.asyncio
async def test_sem_interesse_sem_canal_descarta_sem_crash():
    calls: list = []
    provider = _provider()
    result, _ = await _run(
        "registrar_sem_interesse_atual", {"motivo": "x"}, _patches(provider, calls, channel=False),
    )
    assert [c for c in calls if c[0] == "send_text"] == []
    assert [c for c in calls if c[0] == "update_lead"]


@pytest.mark.asyncio
async def test_sem_interesse_dedup_nao_reenvia_despedida_identica():
    calls: list = []
    provider = _provider()
    await _run(
        "registrar_sem_interesse_atual", {"motivo": "x"},
        _patches(provider, calls, despedida_ja_enviada=True),
    )
    assert [c for c in calls if c[0] == "send_text"] == []


@pytest.mark.asyncio
async def test_cliente_ativo_tambem_recebe_despedida():
    calls: list = []
    provider = _provider()
    patches = _patches(provider, calls)
    patches[2] = patch.object(T, "lead_has_active_relationship", return_value=True)
    await _run("registrar_sem_interesse_atual", {"motivo": "cliente sem demanda"}, patches)
    sends = [c for c in calls if c[0] == "send_text"]
    updates = [c for c in calls if c[0] == "update_lead" and c[1].get("ai_enabled") is False]
    assert len(sends) == 1 and len(updates) == 1
    assert calls.index(sends[0]) < calls.index(updates[0])


@pytest.mark.asyncio
async def test_optout_envia_despedida_antes_de_desligar():
    calls: list = []
    provider = _provider()
    await _run(
        "registrar_optout",
        {"motivo": "pediu pra parar de mandar mensagem e tirar da lista",
         "mensagem_despedida": "sem problema, não te mando mais mensagem por aqui"},
        _patches(provider, calls),
    )
    sends = [c for c in calls if c[0] == "send_text"]
    updates = [c for c in calls if c[0] == "update_lead" and c[1].get("ai_enabled") is False]
    assert len(sends) == 1
    assert sends[0][1].startswith("sem problema")
    assert calls.index(sends[0]) < calls.index(updates[0])


@pytest.mark.asyncio
async def test_optout_rebaixado_para_sem_interesse_preserva_despedida():
    """Guardrail anti-falso-positivo rebaixa optout→sem_interesse: a despedida do
    LLM tem que sobreviver à delegação."""
    calls: list = []
    provider = _provider()
    await _run(
        "registrar_optout",
        {"motivo": "vou pensar", "mensagem_despedida": "tranquilo, combinado"},
        _patches(provider, calls),
    )
    sends = [c for c in calls if c[0] == "send_text"]
    assert len(sends) == 1
    assert sends[0][1] == "tranquilo, combinado"


def test_declaracoes_expõem_mensagem_despedida():
    decls = {d["name"]: d for d in T.TOOL_DECLARATIONS}
    for tool in ("registrar_sem_interesse_atual", "registrar_optout"):
        props = decls[tool]["parameters"]["properties"]
        assert "mensagem_despedida" in props, tool
        assert "mensagem_despedida" in decls[tool]["description"]
