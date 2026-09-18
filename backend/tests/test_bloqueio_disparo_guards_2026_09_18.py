"""Guards de DISPARO para lead bloqueado — os 7 furos fechados em 18/09/2026.

Bloqueio = o hard opt-out que já existe: `leads.opt_out IS TRUE` **OU** card no funil
Blacklist. É o critério de `is_lead_blacklisted` (`app/leads/service.py:381`) — não há
coluna nova. Um lead bloqueado não pode receber NENHUM disparo ativo.

Já existiam guardas em: loop principal do broadcast (`worker.py`, camada 2 via
`_blacklist_guardrail`), criação do disparo (`broadcast/router.py`, camada 1),
`campaigns/worker.py` e `automation/engine.py`. Estes testes cobrem os caminhos que
NÃO tinham nenhuma — cada um deles manda mensagem de verdade:

  1. `broadcast/worker._retry_single_undelivered` — reenvia o template do 9º dígito
     horas/dias depois, na janela exata em que o opt-out acontece.
  2. `follow_up/scheduler._lead_stop_reason` — backstop único de 6 caminhos de envio,
     que só olhava `leads.opt_out`/`metadata.blacklisted_at` e ignorava o funil.
  3. `follow_up/scheduler.send_joao_handoff_template` — disparo síncrono FORA do loop
     que tem o backstop.
  4. `campaigns/router.api_enroll_lead` — matrícula manual sem camada 1.
  5. `automation/triggers._safe_enroll` — ponto comum de TODOS os gatilhos de polling.
  6. `button_flow/runner._motivo_para_nao_rodar` — e a posição importa: o guarda NÃO
     pode ficar em `_enviar`, senão engole a confirmação do próprio opt-out.
  7. `automation/test_runner` (o "testar campanha" envia de verdade) e
     `channels/router.send_message` (envio manual do operador pelo backend).

Regra de todos: fail-open na CHECAGEM (erro de consulta não bloqueia envio — é o que
`is_lead_blacklisted` já faz). A proteção vem das camadas somadas, não de fail-closed.

Cada teste prova o par: com lead bloqueado o `send_*` NÃO é chamado; com lead normal É.
"""
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.button_flow import effects, engine, flows, runner


# ──────────────────────────────────────────────────────────────────────────────
# 1. broadcast/worker._retry_single_undelivered — retentativa do 9º dígito
# ──────────────────────────────────────────────────────────────────────────────

def _bl_retry(lead_id="lead-1"):
    """Linha de `broadcast_leads` no shape de `_BL_RETRY_SELECT` (join leads+broadcasts)."""
    return {
        "id": "bl-1",
        "broadcast_id": "bc-1",
        "lead_id": lead_id,
        "wamid": "wamid.velho",
        # 13 dígitos com o 9 → `_toggle_br_ninth_digit` devolve a forma de 12.
        "leads": {"id": lead_id, "phone": "5511999990000", "wa_id": "5511999990000"},
        "broadcasts": {
            "channel_id": "ch-1",
            "template_name": "atualizacao_cadastro",
            "template_language_code": "pt_BR",
            "template_variables": {},
            "agent_profile_id": None,
        },
    }


def _sb_claim_ok():
    """Supabase em que o claim atômico (`delivery_retried` false→true) VENCE."""
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.is_.return_value.execute.return_value.data = [
        {"id": "bl-1"}
    ]
    return sb


async def _run_retry(blacklisted: bool):
    from app.broadcast import worker as W
    provider = MagicMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.novo"}]})
    with ExitStack() as stack:
        p = lambda alvo, **kw: stack.enter_context(patch(f"app.broadcast.worker.{alvo}", **kw))
        p("is_lead_blacklisted", return_value=blacklisted)
        p("get_channel_by_id", return_value={"id": "ch-1", "provider_config": {}})
        p("get_provider", return_value=provider)
        p("_build_template_components", return_value=[])
        p("get_or_create_conversation", return_value=None)
        marcar = p("mark_broadcast_lead_failed")
        await W._retry_single_undelivered(_sb_claim_ok(), _bl_retry())
    return provider, marcar


@pytest.mark.asyncio
async def test_retry_do_9o_digito_nao_reenvia_para_lead_bloqueado():
    provider, marcar = await _run_retry(blacklisted=True)
    provider.send_template.assert_not_awaited()
    # O claim já queimou a retentativa; marcar o motivo deixa a razão visível no CRM.
    assert marcar.call_count == 1
    assert "blacklist" in marcar.call_args.args[1].lower()


@pytest.mark.asyncio
async def test_retry_do_9o_digito_segue_para_lead_normal():
    provider, marcar = await _run_retry(blacklisted=False)
    provider.send_template.assert_awaited_once()
    assert provider.send_template.await_args.kwargs["to"] == "551199990000"
    marcar.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 2. follow_up/scheduler._lead_stop_reason — backstop de 6 caminhos de envio
# ──────────────────────────────────────────────────────────────────────────────

def _job_followup():
    return {
        "id": "job-1",
        "job_type": "standard",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 2,
        "leads": {"id": "lead-1", "phone": "5511910402026", "name": "Cliente"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {
            "id": "conv-1",
            "stage": "secretaria",
            "followup_enabled": True,
            "last_customer_message_at": None,
        },
        "metadata": {},
    }


async def _run_followups(blacklisted: bool):
    """Dirige `process_due_followups` com um lead SEM nenhuma flag em memória.

    O ponto do teste está aí: `opt_out=False`, `ai_enabled=True` e `metadata` vazio —
    o lead só está bloqueado pelo CARD no funil Blacklist, que é justamente o braço do
    critério que o backstop não enxergava.
    """
    from app.follow_up import scheduler as S
    fresh = {"id": "lead-1", "phone": "5511910402026", "opt_out": False,
             "ai_enabled": True, "stage": "secretaria", "metadata": {}}
    with patch("app.follow_up.scheduler.is_lead_blacklisted", return_value=blacklisted), \
         patch("app.follow_up.scheduler.get_due_followups", return_value=[_job_followup()]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh), \
         patch("app.follow_up.scheduler._cancel_job") as cancelar, \
         patch("app.follow_up.scheduler.fire_reopen_template", new_callable=AsyncMock) as reabrir, \
         patch("app.follow_up.scheduler._generate_followup_message", new_callable=AsyncMock) as gerar:
        await S.process_due_followups(now=datetime.now(timezone.utc))
    return cancelar, reabrir, gerar


@pytest.mark.asyncio
async def test_backstop_para_lead_so_com_card_na_blacklist():
    cancelar, reabrir, gerar = await _run_followups(blacklisted=True)
    cancelar.assert_called_once_with("job-1", "blacklisted")
    reabrir.assert_not_awaited()
    gerar.assert_not_called()


@pytest.mark.asyncio
async def test_backstop_nao_para_lead_normal():
    """Sem bloqueio o backstop não age — o job segue e morre pelo motivo de sempre."""
    cancelar, _, _ = await _run_followups(blacklisted=False)
    assert cancelar.call_args.args[1] != "blacklisted"


def test_blacklist_vence_ai_disabled_no_motivo_de_parada():
    """Ordem, não estética: `ai_disabled` é o ÚNICO motivo com isenção
    (`_STOP_REASON_EXEMPT_JOB_TYPES` → handoff_rescue), e todo lead bloqueado tem
    `ai_enabled=False` junto. Se a checagem viesse depois, o resgate isento mandaria
    template para quem está na Blacklist."""
    from app.follow_up.scheduler import _lead_stop_reason, _stop_reason_applies
    lead = {"id": "lead-1", "opt_out": False, "ai_enabled": False, "metadata": {}}
    with patch("app.follow_up.scheduler.is_lead_blacklisted", return_value=True):
        assert _lead_stop_reason(lead) == "blacklisted"
    assert _stop_reason_applies("blacklisted", "handoff_rescue") is True, \
        "blacklisted não pode virar motivo isento"


def test_motivo_de_parada_nao_consulta_o_banco_a_toa():
    """As checagens em memória vêm antes: quem já parou por `opt_out` não gera query."""
    from app.follow_up.scheduler import _lead_stop_reason
    with patch("app.follow_up.scheduler.is_lead_blacklisted") as consulta:
        assert _lead_stop_reason({"id": "lead-1", "opt_out": True}) == "opt_out"
    consulta.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# 3. follow_up/scheduler.send_joao_handoff_template — disparo fora do loop
# ──────────────────────────────────────────────────────────────────────────────

async def _run_handoff_template(blacklisted: bool):
    from app.follow_up import scheduler as S
    cliente = MagicMock()
    cliente.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.joao"}]})
    with patch("app.follow_up.scheduler.is_lead_blacklisted", return_value=blacklisted), \
         patch("app.follow_up.scheduler.get_channel_by_provider_config",
               return_value={"id": "ch-joao", "provider_config": {}}), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=cliente), \
         patch("app.follow_up.scheduler._persist_joao_handoff_message"):
        ok = await S.send_joao_handoff_template("5511910402026", "Cliente", lead_id="lead-1")
    return ok, cliente


@pytest.mark.asyncio
async def test_template_do_joao_nao_sai_para_lead_bloqueado():
    ok, cliente = await _run_handoff_template(blacklisted=True)
    cliente.send_template.assert_not_awaited()
    # False é o contrato de falha da função: o chamador cai no reagendamento, que passa
    # pelo backstop no próximo tick. A assinatura e o retorno não mudam.
    assert ok is False


@pytest.mark.asyncio
async def test_template_do_joao_sai_para_lead_normal():
    ok, cliente = await _run_handoff_template(blacklisted=False)
    cliente.send_template.assert_awaited_once()
    assert ok is True


# ──────────────────────────────────────────────────────────────────────────────
# 4. campaigns/router.api_enroll_lead — matrícula manual
# ──────────────────────────────────────────────────────────────────────────────

async def _run_enroll(blacklisted: bool):
    from app.campaigns.router import api_enroll_lead, EnrollRequest
    with patch("app.campaigns.router.is_lead_blacklisted", return_value=blacklisted), \
         patch("app.campaigns.router.is_already_enrolled", return_value=False), \
         patch("app.campaigns.router.get_campaign", return_value={"id": "camp-1"}), \
         patch("app.campaigns.router.list_nodes", return_value=[
             {"id": "n-trigger", "type": "trigger", "next_node_id": "n-send"}]), \
         patch("app.campaigns.router.create_enrollment",
               return_value={"id": "enr-1"}) as matricular:
        try:
            resultado = await api_enroll_lead("camp-1", EnrollRequest(lead_id="lead-1"))
        except HTTPException as exc:
            return exc, matricular
    return resultado, matricular


@pytest.mark.asyncio
async def test_matricula_manual_recusa_lead_bloqueado_com_409():
    erro, matricular = await _run_enroll(blacklisted=True)
    assert isinstance(erro, HTTPException) and erro.status_code == 409
    # O silêncio é o bug: sem o 409 o operador via "matriculado" e nada saía nunca.
    matricular.assert_not_called()


@pytest.mark.asyncio
async def test_matricula_manual_aceita_lead_normal():
    resultado, matricular = await _run_enroll(blacklisted=False)
    assert resultado == {"id": "enr-1"}
    matricular.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 5. automation/triggers._safe_enroll — ponto comum dos gatilhos de polling
# ──────────────────────────────────────────────────────────────────────────────

def _run_safe_enroll(blacklisted: bool):
    from app.automation import triggers as T
    no = {"campaign_id": "camp-1", "next_node_id": "n-1", "type": "lead_tag_added",
          "channel_id": "ch-1"}
    with patch("app.automation.triggers.is_lead_blacklisted", return_value=blacklisted), \
         patch("app.automation.triggers._engine._conversation_followup_disabled",
               return_value=False), \
         patch("app.automation.triggers.create_enrollment") as matricular:
        T._safe_enroll(no, "lead-1", datetime.now(timezone.utc))
    return matricular


def test_gatilho_de_polling_nao_matricula_lead_bloqueado():
    assert _run_safe_enroll(blacklisted=True).call_count == 0


def test_gatilho_de_polling_matricula_lead_normal():
    assert _run_safe_enroll(blacklisted=False).call_count == 1


# ──────────────────────────────────────────────────────────────────────────────
# 6. button_flow/runner — e a POSIÇÃO do guarda
# ──────────────────────────────────────────────────────────────────────────────

def _lead_bf(**over) -> dict:
    base = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "name": "Roner Silva", "ai_enabled": False, "human_control": False,
            "metadata": {"produto_top1": "Café Clássico 1kg"}}
    base.update(over)
    return base


def _estado_bf() -> dict:
    return {"flow": flows.FLOW_ID, "node": flows.NO_INTERESSE, "nudged": False,
            "trilha": flows.TRILHA_ESTOQUE, "campaign_id": "camp-1",
            "sent_at": "2026-09-01T17:00:00+00:00",
            "updated_at": datetime.now(timezone.utc).isoformat()}


CANAL_JOAO = {"id": "a3a607b1", "mode": "human", "provider_config": {},
              "agent_profiles": {"id": "P-LLM", "kind": "llm"}}


def _provider_bf() -> MagicMock:
    p = MagicMock()
    p.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.out"}]})
    p.send_interactive_buttons = AsyncMock(return_value={"messages": [{"id": "wamid.out"}]})
    p.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.card"}]})
    return p


def _patch_bf(stack: ExitStack) -> dict:
    """Neutraliza o I/O do runner e as folhas de escrita do CRM (`effects.aplicar` roda)."""
    for nome, valor in (("get_open_deal", None), ("get_history", []),
                        ("save_message", {}), ("update_conversation", {}),
                        ("get_conversation", None)):
        stack.enter_context(patch.object(runner, nome, new=MagicMock(return_value=valor)))
    stack.enter_context(patch("app.agent.catalog._fetch_active_products",
                              MagicMock(return_value=[])))
    crm = {}
    for nome in ("update_lead", "add_tags_to_lead", "append_lead_observation",
                 "save_message", "apply_optout_side_effects"):
        crm[nome] = stack.enter_context(patch.object(effects, nome, new=MagicMock()))
    crm["get_open_deal"] = stack.enter_context(
        patch.object(effects, "get_open_deal", new=MagicMock(return_value=None)))
    crm["move_deal_to_stage_key"] = stack.enter_context(
        patch.object(effects, "move_deal_to_stage_key", new=MagicMock(return_value=False)))
    return crm


@pytest.fixture
def bf_ligado(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setenv("RECUPERACAO_CLASSIFIER_ENABLED", "off")
    monkeypatch.setenv("RECUPERACAO_JANELA_RETOMA_DIAS", "7")
    runner.limpar_cache_de_perfis()


async def _run_button_flow(blacklisted: bool, *, texto="Preciso repor",
                           message_type="button", metadata=None):
    provider = _provider_bf()
    with ExitStack() as stack:
        crm = _patch_bf(stack)
        stack.enter_context(patch.object(runner, "is_lead_blacklisted",
                                         new=MagicMock(return_value=blacklisted)))
        await runner.run_button_flow(
            lead=_lead_bf(), conversation={"id": "C1", "stage": "atacado",
                                           "agent_profile_id": "P-BOT",
                                           "flow_state": _estado_bf()},
            channel=CANAL_JOAO, provider=provider, texto=texto,
            message_type=message_type,
            metadata=metadata or {"payload": "repor", "title": "Preciso repor"},
        )
    return provider, crm


@pytest.mark.asyncio
async def test_bot_de_botoes_nao_roda_para_lead_bloqueado(bf_ligado):
    provider, crm = await _run_button_flow(blacklisted=True)
    provider.send_text.assert_not_awaited()
    provider.send_interactive_buttons.assert_not_awaited()
    # Sai de cena pelo caminho já existente de "não rodar": anota no CRM e cala a boca.
    assert crm["append_lead_observation"].call_count == 1
    assert "blacklist" in crm["append_lead_observation"].call_args.args[1].lower()


@pytest.mark.asyncio
async def test_bot_de_botoes_roda_para_lead_normal(bf_ligado):
    provider, _ = await _run_button_flow(blacklisted=False)
    assert provider.send_text.await_count or provider.send_interactive_buttons.await_count


@pytest.mark.asyncio
async def test_clique_de_parar_mensagens_ainda_recebe_a_confirmacao(bf_ligado):
    """A ARMADILHA deste guarda, e o motivo de ele NÃO morar em `_enviar`.

    `effects._aplicar_optout` grava `opt_out=true` no próprio clique de "Parar
    mensagens", e `_enviar` roda DEPOIS de `effects.aplicar` no mesmo turno. Um guarda
    lá engoliria justamente a mensagem que confirma ao lead que ele foi atendido — ele
    ficaria sem resposta e sem motivo para tocar no botão de novo. No guarda de
    não-rodar a checagem acontece ANTES, com o estado que o lead tinha ao clicar
    (ainda não bloqueado), então a confirmação sai e só os turnos SEGUINTES ficam mudos.
    """
    provider, crm = await _run_button_flow(
        blacklisted=False, texto="Parar mensagens",
        metadata={"payload": "optout", "title": "Parar mensagens"},
    )
    gravou = [c for c in crm["update_lead"].call_args_list
              if c.kwargs.get("opt_out") is True]
    assert gravou, f"opt_out não gravado: {crm['update_lead'].call_args_list}"
    assert provider.send_text.await_args.args[1] == flows.MSG_OPTOUT


def test_guarda_de_nao_rodar_devolve_o_motivo_blacklist():
    with patch.object(runner, "is_lead_blacklisted", new=MagicMock(return_value=True)):
        assert runner._motivo_para_nao_rodar(_lead_bf(), None, None) == "blacklist"
    with patch.object(runner, "is_lead_blacklisted", new=MagicMock(return_value=False)):
        assert runner._motivo_para_nao_rodar(_lead_bf(), None, None) is None


# ──────────────────────────────────────────────────────────────────────────────
# 7a. automation/test_runner — o "testar campanha" envia de verdade
# ──────────────────────────────────────────────────────────────────────────────

async def _run_no_de_envio(blacklisted: bool, node_type="send"):
    from app.automation import test_runner as TR
    provider = MagicMock()
    provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.t"}]})
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.t"}]})
    node = {"id": "n-1", "type": node_type, "config": {
        "template_name": "atualizacao_cadastro", "message_text": "oi"}}
    lead = {"id": "lead-1", "phone": "5511999990000", "name": "Teste"}
    erro = None
    with patch("app.leads.service.is_lead_blacklisted", return_value=blacklisted), \
         patch("app.automation.engine._resolve_channel",
               return_value={"id": "ch-1", "name": "Canal", "provider_config": {}}), \
         patch("app.whatsapp.registry.get_provider", return_value=provider), \
         patch("app.broadcast.worker._build_template_components", return_value=[]):
        try:
            await TR._execute_test_node(
                node, lead, {"lead_id": "lead-1", "campaign_id": "camp-1"},
                {"id": "camp-1"}, datetime.now(timezone.utc), True,
            )
        except ValueError as exc:
            erro = exc
    return provider, erro


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type,metodo", [("send", "send_template"), ("send_text", "send_text")])
async def test_testar_campanha_nao_envia_para_lead_bloqueado(node_type, metodo):
    provider, erro = await _run_no_de_envio(True, node_type=node_type)
    getattr(provider, metodo).assert_not_awaited()
    # ValueError é a via de erro que o gerador SSE já traduz em evento `failed`.
    assert erro is not None and "bloqueado" in str(erro).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type,metodo", [("send", "send_template"), ("send_text", "send_text")])
async def test_testar_campanha_envia_para_lead_normal(node_type, metodo):
    provider, erro = await _run_no_de_envio(False, node_type=node_type)
    assert erro is None
    getattr(provider, metodo).assert_awaited_once()


# ──────────────────────────────────────────────────────────────────────────────
# 7b. channels/router.send_message — envio manual do operador pelo backend
# ──────────────────────────────────────────────────────────────────────────────

async def _run_envio_manual(blacklisted: bool, conversation_id="conv-1"):
    from app.channels.router import send_message, SendMessage
    provider = MagicMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.m"}]})
    erro = None
    with patch("app.leads.service.is_lead_blacklisted", return_value=blacklisted), \
         patch("app.channels.router.get_channel", return_value={"id": "ch-1"}), \
         patch("app.whatsapp.registry.get_provider", return_value=provider), \
         patch("app.channels.router._conversa_do_envio",
               return_value={"lead_id": "lead-1", "stage": "atacado"}
               if conversation_id else None), \
         patch("app.conversations.service.save_message") as gravar:
        try:
            await send_message("ch-1", SendMessage(
                conversation_id=conversation_id, to="5511999990000", text="oi"))
        except HTTPException as exc:
            erro = exc
    return provider, erro, gravar


@pytest.mark.asyncio
async def test_envio_manual_pelo_backend_barra_lead_bloqueado():
    provider, erro, gravar = await _run_envio_manual(True)
    provider.send_text.assert_not_awaited()
    assert erro is not None and erro.status_code == 403
    gravar.assert_not_called()


@pytest.mark.asyncio
async def test_envio_manual_pelo_backend_segue_para_lead_normal():
    provider, erro, gravar = await _run_envio_manual(False)
    assert erro is None
    provider.send_text.assert_awaited_once()
    gravar.assert_called_once()


@pytest.mark.asyncio
async def test_envio_manual_sem_conversa_nao_trava_o_envio():
    """Fail-open: sem `conversation_id` não há lead a consultar — o envio segue.
    A proteção vem das camadas somadas (e das rotas Next, que veem o lead), nunca de
    travar o operador por falta de dado."""
    provider, erro, _ = await _run_envio_manual(True, conversation_id=None)
    assert erro is None
    provider.send_text.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────────────────
# Fail-open da checagem — vale para todos os guardas
# ──────────────────────────────────────────────────────────────────────────────

def test_erro_de_consulta_nao_bloqueia_disparo():
    """`is_lead_blacklisted` já é fail-open (erro → False) e os guardas herdam isso:
    um Supabase fora do ar não pode parar a operação inteira de disparo."""
    from app.leads.service import is_lead_blacklisted
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch("app.leads.service.get_supabase", return_value=sb):
        assert is_lead_blacklisted("lead-1") is False
