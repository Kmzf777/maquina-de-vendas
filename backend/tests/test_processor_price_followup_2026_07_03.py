"""TDD — Frente B, Task 3 (B3): gatilho determinístico de follow-up quando o turno cotou preço.

Casos reais: Samuel/Angelo/Welita (01-02/07) receberam preço, sumiram, e ZERO follow-ups
foram agendados — o gatilho antigo dependia 100% do LLM chamar marcar_interesse, que não
disparou nenhuma vez na janela desses casos.

Cobre:
  A. tools.py — _quote_executed/pop_quote_executed (espelho de _interest_marked): setado
     SÓ nos dois retornos de calcular_orcamento com valores resolvidos (subtotal-sem-UF e
     orçamento completo com frete); NUNCA nos retornos de erro/validação/desambiguação.
  B. processor.py — bloco de agendamento: novo gatilho inbound "cotou preço"
     (quote_flag OU "R$" no texto final da resposta), com re-check de ai_enabled fresco
     (mesmo guard do gatilho outbound engajou-e-esfriou) e drenagem da flag nos mesmos
     early-returns onde pop_interest_marked já é drenado (recoalesce/handoff/empty), para
     nunca vazar para o próximo turno.
"""
import logging
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# A. tools.py — _quote_executed / pop_quote_executed (espelho de _interest_marked)
# ===========================================================================

_FAKE_PRODUCTS = [
    {"sector": "atacado", "name": "Café Clássico 500g", "price_formatted": "R$ 100,00",
     "min_lot": "10", "description": "Torra média-escura", "image_urls": ""},
    {"sector": "atacado", "name": "Café Suave 500g", "price_formatted": "R$ 80,00",
     "min_lot": "10", "description": "Torra média", "image_urls": ""},
    {"sector": "atacado", "name": "Café Suave Premium 500g", "price_formatted": "R$ 120,00",
     "min_lot": "5", "description": "Microlote suave", "image_urls": ""},
]


def _reset_quote(conversation_id: str) -> None:
    """Garante que não há estado vazado de outro teste (mesmo padrão de _reset_interest)."""
    from app.agent.tools import _quote_executed
    _quote_executed.pop(conversation_id, None)


async def _exec_orcamento(args: dict, conv: str) -> str:
    from app.agent.tools import execute_tool
    with patch("app.agent.tools._fetch_active_products", return_value=_FAKE_PRODUCTS):
        return await execute_tool(
            "calcular_orcamento", args, lead_id="lead-b3-tool", phone="5511999999999",
            conversation_id=conv,
        )


@pytest.mark.asyncio
async def test_calcular_orcamento_sets_flag_on_full_quote():
    """Orçamento completo (com frete) resolvido → flag setada (caso Samuel/Angelo)."""
    from app.agent.tools import pop_quote_executed
    conv = "conv-b3-tool-full"
    _reset_quote(conv)

    result = await _exec_orcamento(
        {"itens": [{"produto": "classico", "quantidade": 2}], "estado": "SP"}, conv,
    )

    assert "R$" in result  # sanity: é mesmo um orçamento com valores
    assert pop_quote_executed(conv) is True
    assert pop_quote_executed(conv) is False, "pop deve limpar a flag (não vazar pro próximo turno)"


@pytest.mark.asyncio
async def test_calcular_orcamento_sets_flag_on_subtotal_sem_uf():
    """Subtotal sem UF (pede estado) TAMBÉM tem valores resolvidos → flag setada."""
    from app.agent.tools import pop_quote_executed
    conv = "conv-b3-tool-subtotal"
    _reset_quote(conv)

    result = await _exec_orcamento(
        {"itens": [{"produto": "classico", "quantidade": 2}]}, conv,  # sem estado, sem cidade
    )

    assert "estado" in result.lower()
    assert pop_quote_executed(conv) is True


@pytest.mark.asyncio
async def test_calcular_orcamento_does_not_set_flag_on_validation_error():
    """itens=[] viola min_length → erro de validação, NUNCA setar a flag."""
    from app.agent.tools import pop_quote_executed
    conv = "conv-b3-tool-err-validation"
    _reset_quote(conv)

    await _exec_orcamento({"itens": []}, conv)

    assert pop_quote_executed(conv) is False


@pytest.mark.asyncio
async def test_calcular_orcamento_does_not_set_flag_on_product_not_found():
    """Produto fora do catálogo → erro claro, NUNCA setar a flag."""
    from app.agent.tools import pop_quote_executed
    conv = "conv-b3-tool-err-notfound"
    _reset_quote(conv)

    await _exec_orcamento(
        {"itens": [{"produto": "produto inexistente xyz", "quantidade": 1}], "estado": "SP"}, conv,
    )

    assert pop_quote_executed(conv) is False


@pytest.mark.asyncio
async def test_calcular_orcamento_does_not_set_flag_on_disambiguation():
    """'suave' bate em 2 produtos → pede desambiguação, NUNCA setar a flag."""
    from app.agent.tools import pop_quote_executed
    conv = "conv-b3-tool-err-ambig"
    _reset_quote(conv)

    await _exec_orcamento({"itens": [{"produto": "suave", "quantidade": 1}]}, conv)

    assert pop_quote_executed(conv) is False


@pytest.mark.asyncio
async def test_pop_quote_executed_returns_false_when_never_set():
    from app.agent.tools import pop_quote_executed
    assert pop_quote_executed("conv-b3-tool-never-set") is False


# ===========================================================================
# B. processor.py — bloco de agendamento: gatilho "inbound cotou preço"
# ===========================================================================

def _lead(id_="lead-b3p"):
    return {"id": id_, "phone": "5531999990000", "stage": "atacado",
            "status": "active", "human_control": False, "metadata": {}}


def _conv(id_="conv-b3p"):
    return {"id": id_, "stage": "atacado", "status": "active",
            "ai_enabled": True, "agent_profile_id": None, "followup_enabled": True}


def _b3_patches(lead, conv, schedule_mock, response, persona="valeria_inbound",
                 ai_enabled_fresh=True, quote_flag=False, quote_pop_mock=None, interest=None):
    """Conjunto comum de patches para exercitar o bloco de agendamento do processor.

    Mesma forma de _b_patches (test_outbound_perfeicao.py, Épico B — gatilho
    engajou-e-esfriou), com os sinais de interesse/cotação plugáveis por parâmetro.
    """
    bubbles = [response] if response else []
    pop_quote = quote_pop_mock if quote_pop_mock is not None else MagicMock(return_value=quote_flag)
    return [
        patch("app.buffer.processor.get_or_create_lead", return_value=lead),
        patch("app.buffer.processor.get_channel_by_id", return_value={"id": "ch", "agent_profiles": None}),
        patch("app.buffer.processor.get_provider"),
        patch("app.buffer.processor.get_or_create_conversation", return_value=conv),
        patch("app.buffer.processor._is_recent_duplicate", return_value=False),
        patch("app.buffer.processor.get_active_enrollment", return_value=None),
        patch("app.buffer.processor.save_message", return_value={}),
        patch("app.buffer.processor.get_supabase", new=MagicMock()),
        patch("app.buffer.processor.run_agent", new=AsyncMock(return_value=response)),
        patch("app.buffer.processor._resolve_media", new=AsyncMock(side_effect=lambda t, p: t)),
        patch("app.buffer.processor.split_into_bubbles", return_value=bubbles),
        patch("app.buffer.processor.get_lead", return_value={"id": lead["id"], "ai_enabled": ai_enabled_fresh}),
        patch("app.buffer.processor._schedule_followup", new=schedule_mock),
        patch("app.buffer.processor.pop_quote_executed", new=pop_quote),
        patch("app.buffer.processor.pop_interest_marked", return_value=interest),
        patch("app.buffer.processor.resolve_prompt_key", return_value=persona),
    ]


def _run_b3(stack, lead, conv, schedule_mock, response, **kwargs):
    for p in _b3_patches(lead, conv, schedule_mock, response, **kwargs):
        stack.enter_context(p)
    prov = stack.enter_context(patch("app.buffer.processor.get_provider"))
    prov.return_value.send_text = AsyncMock(return_value={})
    return prov


@pytest.mark.asyncio
async def test_b3_1_samuel_inbound_com_rs_agenda_warm_true(caplog):
    """Caso Samuel: persona inbound, resposta com 'R$26,70' → agenda com warm=True; reason logada."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-1"), _conv("conv-b3p-1")
    schedule_mock = MagicMock()

    with ExitStack() as stack:
        _run_b3(stack, lead, conv, schedule_mock, response="Fechado! Sai R$26,70 o kg.")
        with caplog.at_level(logging.INFO, logger="app.buffer.processor"):
            await process_buffered_messages("+5531999990000", "quanto fica?", channel_id="ch")

    schedule_mock.assert_called_once_with(
        conversation_id="conv-b3p-1", lead_id="lead-b3p-1", channel_id="ch", warm=True,
    )
    assert "inbound cotou pre" in caplog.text  # "inbound cotou preço" (tolera encoding do console)


@pytest.mark.asyncio
async def test_b3_2_tool_executada_sem_rs_no_texto_agenda_mesmo_assim():
    """calcular_orcamento rodou no turno (flag) mas o texto final não repete 'R$'
    (ex.: só o breakdown foi passado como mensagem da tool) → agenda mesmo assim."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-2"), _conv("conv-b3p-2")
    schedule_mock = MagicMock()

    with ExitStack() as stack:
        _run_b3(
            stack, lead, conv, schedule_mock,
            response="Beleza, já te passei os valores certinhos, qualquer duvida me chama.",
            quote_flag=True,
        )
        await process_buffered_messages("+5531999990000", "quanto fica?", channel_id="ch")

    schedule_mock.assert_called_once_with(
        conversation_id="conv-b3p-2", lead_id="lead-b3p-2", channel_id="ch", warm=True,
    )


@pytest.mark.asyncio
async def test_b3_3a_sem_preco_sem_flag_sem_interesse_nao_agenda():
    """Small talk de secretaria, sem preço/flag/interesse → NÃO agenda (comportamento antigo)."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-3a"), _conv("conv-b3p-3a")
    schedule_mock = MagicMock()

    with ExitStack() as stack:
        _run_b3(stack, lead, conv, schedule_mock, response="Oi! Tudo bem, e você?")
        await process_buffered_messages("+5531999990000", "oi", channel_id="ch")

    schedule_mock.assert_not_called()


@pytest.mark.asyncio
async def test_b3_3b_sem_preco_com_interesse_ainda_agenda_regressao():
    """Regressão: sem preço/flag mas COM interesse (marcar_interesse) → gatilho antigo
    continua agendando (interest tem precedência sobre o novo gatilho)."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-3b"), _conv("conv-b3p-3b")
    schedule_mock = MagicMock()
    interest_signal = {"nivel": "quente", "motivo": "topou fechar"}

    with ExitStack() as stack:
        _run_b3(
            stack, lead, conv, schedule_mock, response="Fechado, combinamos então!",
            interest=interest_signal,
        )
        await process_buffered_messages("+5531999990000", "fechado", channel_id="ch")

    schedule_mock.assert_called_once_with(
        conversation_id="conv-b3p-3b", lead_id="lead-b3p-3b", channel_id="ch", warm=True,
    )


@pytest.mark.asyncio
async def test_b3_4_ai_enabled_false_no_recheck_nao_agenda():
    """ai_enabled virou false no meio do turno (handoff/opt-out concorrente) → o re-check
    fresco barra o agendamento mesmo com preço no texto."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-4"), _conv("conv-b3p-4")
    schedule_mock = MagicMock()

    with ExitStack() as stack:
        _run_b3(
            stack, lead, conv, schedule_mock, response="Sai R$26,70 o kg.",
            ai_enabled_fresh=False,
        )
        await process_buffered_messages("+5531999990000", "quanto fica?", channel_id="ch")

    schedule_mock.assert_not_called()


@pytest.mark.asyncio
async def test_b3_5_outbound_com_rs_preserva_gatilho_atual_uma_chamada_so():
    """Persona outbound com R$ → comportamento ATUAL preservado (gatilho engajou-e-esfriou
    já cobre); o novo gatilho é exclusivo de valeria_inbound — sem dupla chamada."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-5"), _conv("conv-b3p-5")
    schedule_mock = MagicMock()

    with ExitStack() as stack:
        _run_b3(
            stack, lead, conv, schedule_mock, response="Fechado, sai R$26,70 o kg.",
            persona="valeria_outbound",
        )
        await process_buffered_messages("+5531999990000", "quanto fica?", channel_id="ch")

    assert schedule_mock.call_count == 1, "gatilho outbound + novo gatilho inbound dispararam em dobro"
    schedule_mock.assert_called_once_with(
        conversation_id="conv-b3p-5", lead_id="lead-b3p-5", channel_id="ch", warm=False,
    )


@pytest.mark.asyncio
async def test_b3_6a_flag_drenada_no_handoff():
    """response=None (encaminhar_humano) → pop_quote_executed ainda é chamado (drena),
    para não vazar a flag pro próximo turno."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-6a"), _conv("conv-b3p-6a")
    schedule_mock = MagicMock()
    mock_pop_quote = MagicMock(return_value=False)

    with ExitStack() as stack:
        _run_b3(stack, lead, conv, schedule_mock, response=None, quote_pop_mock=mock_pop_quote)
        await process_buffered_messages("+5531999990000", "quanto fica?", channel_id="ch")

    mock_pop_quote.assert_called_once_with("conv-b3p-6a")
    schedule_mock.assert_not_called()


@pytest.mark.asyncio
async def test_b3_6b_flag_drenada_na_resposta_vazia():
    """Resposta vazia inesperada → pop_quote_executed ainda é chamado (drena)."""
    from app.buffer.processor import process_buffered_messages
    lead, conv = _lead("lead-b3p-6b"), _conv("conv-b3p-6b")
    schedule_mock = MagicMock()
    mock_pop_quote = MagicMock(return_value=False)

    with ExitStack() as stack:
        _run_b3(stack, lead, conv, schedule_mock, response="", quote_pop_mock=mock_pop_quote)
        await process_buffered_messages("+5531999990000", "quanto fica?", channel_id="ch")

    mock_pop_quote.assert_called_once_with("conv-b3p-6b")
    schedule_mock.assert_not_called()


@pytest.mark.asyncio
async def test_b3_6c_flag_drenada_no_recoalesce():
    """Worker stale (inbound mais novo já presente ao adquirir o lock) → aborta em silêncio
    ANTES de rodar o agente; pop_quote_executed ainda é chamado (drena)."""
    from app.buffer.processor import process_buffered_messages

    lead = {"id": "lead-b3p-6c", "phone": "+5531999990001", "stage": "atacado",
            "status": "active", "ai_enabled": True, "name": "Rc"}
    channel = {"id": "ch-b3p-6c", "is_active": True, "mode": "ai",
               "agent_profiles": {"id": "p1", "stages": {}}, "provider": "meta_cloud",
               "provider_config": {"phone_number_id": "123", "access_token": "tok"}}
    conv = {"id": "conv-b3p-6c", "lead_id": "lead-b3p-6c", "channel_id": "ch-b3p-6c",
            "stage": "atacado", "status": "active", "followup_enabled": True}

    @asynccontextmanager
    async def _noop_lock(_lead_id):
        yield True

    run_calls: list[str] = []

    async def fake_run_agent(_conversation, text, **_kwargs):
        run_calls.append(text)
        return "nao deveria rodar"

    provider = AsyncMock(send_text=AsyncMock(return_value={}))
    schedule_mock = MagicMock()
    mock_pop_quote = MagicMock(return_value=False)

    P = "app.buffer.processor."
    patches = [
        patch(P + "get_or_create_lead", return_value=lead),
        patch(P + "get_channel_by_id", return_value=channel),
        patch(P + "get_provider", return_value=provider),
        patch(P + "get_or_create_conversation", return_value=conv),
        patch(P + "get_active_enrollment", return_value=None),
        patch(P + "save_message"),
        patch(P + "run_agent", side_effect=fake_run_agent),
        patch(P + "_is_recent_duplicate", return_value=False),
        patch(P + "update_conversation"),
        patch(P + "_schedule_followup", new=schedule_mock),
        patch(P + "pop_interest_marked", return_value=None),
        patch(P + "pop_quote_executed", new=mock_pop_quote),
        patch(P + "pop_deferred_media", return_value=[]),
        patch(P + "get_supabase", new=MagicMock()),
        patch(P + "_check_frustration_guardrail", return_value=False),
        patch(P + "_update_last_msg"),
        patch(P + "_has_newer_inbound", side_effect=[True]),  # pós-lock: já há inbound mais novo
        patch(P + "lead_run_lock", _noop_lock),
    ]

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        await process_buffered_messages("+5531999990001", "mais uma pergunta", channel_id="ch-b3p-6c")

    assert run_calls == [], "worker stale não pode chamar run_agent"
    mock_pop_quote.assert_called_once_with("conv-b3p-6c")
    schedule_mock.assert_not_called()
