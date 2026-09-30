"""O despacho do inbound entre os DOIS fluxos de botões e o LLM — 2026-09-30.

`buffer/processor.py` é o estreitamento por onde passa TODA mensagem recebida. Até
aqui ele decidia entre duas coisas (o bot de Recuperação e o LLM) e a pergunta era um
booleano; com a ValerIA de botões passam a ser TRÊS destinos, e a pergunta é "qual
fluxo?" — `runner.fluxo_da_conversa` devolve o id, não um sim/não.

O que este arquivo trava, e por que cada item é caro:

  1. COM TUDO DESLIGADO, NADA MUDA — e nem uma consulta a mais acontece. O gate roda
     em todo inbound do backend; resolver de qual fluxo é a conversa custa uma leitura
     de `agent_profiles` por mensagem. `config.algum_fluxo_ligado()` existe para que,
     com os dois switches off, a resposta saia sem tocar no banco.
  2. NA VALERIA DE BOTÕES O LLM NÃO RODA. "Zero IA" não é "o classificador está
     desligado": é o orquestrador nunca ser chamado para esta conversa.
  3. A RECUPERAÇÃO CONTINUA NO RUNNER DELA (regressão). Ligar um fluxo não pode
     redirecionar o outro — é a mesma razão de os kill switches serem separados.
  4. ERRO AO RESOLVER O FLUXO CAI NO LLM (fail-OPEN). Fail-closed sequestraria uma
     conversa humana por causa de uma leitura que falhou.
  5. A COLISÃO DE OPT-OUT COBRE OS DOIS FLUXOS. `_optout_deterministico_cabe` usava
     um predicado que responde só pela Recuperação; com a ValerIA ligada, um lead
     tocando no opt-out dela rodaria os DOIS caminhos de opt-out no mesmo turno — a
     colisão que `tests/test_optout_colisao_button_flow.py` documenta.
  6. A PONTE PÓS-HANDOFF MANDA O CARTÃO DE QUEM DE FATO RECEBEU O LEAD. A ValerIA de
     botões entrega os leads de EXPORTAÇÃO ao Arthur; a ponte reenviava o cartão do
     João com o texto "tá com o João". Errar a pessoa aqui é errar no único degrau
     que o lead tem para alcançar o vendedor — e a troca de número já perde 26% dos
     leads (131 de 500, Diagnóstico 01/09 p.5).

Os testes de despacho dirigem `process_buffered_messages` de ponta a ponta de
propósito (molde: tests/test_button_flow_runner_2026_09_09.py:599). Um teste que
olhasse só o despachante não pegaria uma regressão de POSIÇÃO — e a posição do gate,
antes dos gates de canal humano / VALERIA_ENABLED / ai_enabled, é o desenho inteiro.
"""
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.tools import (
    EXPORTACAO_NAME,
    EXPORTACAO_PHONE,
    SUPERVISOR_NAME,
    SUPERVISOR_PHONE,
)
from app.buffer import processor as P
from app.button_flow import runner
from tests.test_processor_handoff_bridge_2026_07_03 import _BridgeFakeRedis


FLUXO_VALERIA = "valeria_botoes_v1"
FLUXO_RECUP = "recuperacao_v1"

# Canal da ValerIA (mode='ai') e canal do João (mode='human'). A ValerIA de botões
# roda no primeiro; a Recuperação, no segundo.
CANAL_VALERIA = {
    "id": "674beb13", "mode": "ai", "phone": "5534999999999",
    "provider_config": {"phone_number_id": "123", "access_token": "tok"},
    "agent_profiles": {"id": "p-llm", "stages": {}},
}
CANAL_JOAO = {
    "id": "a3a607b1", "mode": "human", "phone": SUPERVISOR_PHONE,
    "provider_config": {"phone_number_id": "456", "access_token": "tok"},
    "agent_profiles": {"id": "p-llm", "stages": {}},
}


def _lead(**over) -> dict:
    base = {
        "id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
        "name": "Roner Silva", "stage": "atacado", "status": "active",
        "ai_enabled": True, "human_control": False, "opt_out": False,
        "metadata": {},
    }
    base.update(over)
    return base


def _conversa(**over) -> dict:
    conv = {
        "id": "C1", "lead_id": "L1", "channel_id": "674beb13", "stage": "atacado",
        "status": "active", "agent_profile_id": "P-BOT", "flow_state": None,
        "followup_enabled": True,
    }
    conv.update(over)
    return conv


def _perfil(flow_id: str | None) -> dict:
    """Perfil de botões como o banco o devolve. `flow_id=None` = coluna NULL."""
    return {"id": "P-BOT", "kind": "button_flow", "flow_id": flow_id}


def _sb() -> MagicMock:
    """Supabase mínimo p/ os blocos pré-gate (unread_count, last_customer_message_at)."""
    return MagicMock(table=MagicMock(return_value=MagicMock(
        update=MagicMock(return_value=MagicMock(
            eq=MagicMock(return_value=MagicMock(execute=MagicMock())))),
        select=MagicMock(return_value=MagicMock(eq=MagicMock(return_value=MagicMock(
            single=MagicMock(return_value=MagicMock(
                execute=MagicMock(return_value=MagicMock(data={"unread_count": 0})))),
        )))),
    )))


def _patch_pipeline(stack: ExitStack, *, channel: dict, conversation: dict,
                    lead: dict, texto: str, message_type: str | None = "text",
                    metadata: dict | None = None) -> dict:
    """Mocks canônicos de `process_buffered_messages` (molde:
    tests/test_button_flow_runner_2026_09_09.py:599).

    Devolve os três destinos possíveis do turno, todos espiões: o runner da ValerIA
    de botões, o da Recuperação e o orquestrador do LLM.
    """
    p = lambda name, *a, **kw: stack.enter_context(patch.object(P, name, *a, **kw))

    p("get_or_create_lead", return_value=lead)
    p("get_channel_by_id", return_value=channel)
    p("get_or_create_conversation", return_value=conversation)
    p("get_provider", return_value=AsyncMock())
    p("update_conversation", MagicMock())
    p("get_supabase", MagicMock(return_value=_sb()))
    p("run_with_retry", MagicMock(return_value=MagicMock(data={"unread_count": 0})))
    p("_wamid_already_processed", return_value=False)
    p("_is_recent_duplicate", return_value=False)
    p("save_message", MagicMock(return_value={"created_at": "2026-09-30T12:00:00Z"}))
    p("_update_last_msg", MagicMock())
    p("advance_deal_on_reply", MagicMock())
    p("_schedule_followup", MagicMock())
    p("get_active_enrollment", MagicMock(return_value=None))
    p("_resolve_media", new=AsyncMock(return_value=(texto, None, message_type, None, metadata)))
    # Réguas do re-coalescing: sem mock elas bateriam no Supabase/Redis mockados e
    # devolveriam MagicMock (truthy), abortando todo turno em silêncio.
    p("_has_newer_inbound", MagicMock(return_value=False))
    p("_has_pending_buffered_inbound", new=AsyncMock(return_value=False))
    p("_handle_autoresponder", new=AsyncMock(return_value=False))

    @asynccontextmanager
    async def _lock(_lead_id):
        yield True

    p("lead_run_lock", _lock)

    stack.enter_context(patch("app.broadcast.service.record_broadcast_reply", MagicMock()))
    stack.enter_context(patch("app.campaigns.worker.handle_campaign_reply", MagicMock()))
    stack.enter_context(patch("app.campaigns.worker.handle_optout_reply", MagicMock()))
    stack.enter_context(patch("app.automation.triggers.fire_trigger", new=AsyncMock()))
    stack.enter_context(patch("app.leads.service.get_open_deal", MagicMock(return_value=None)))

    destinos = {
        "valeria": AsyncMock(),
        "recuperacao": AsyncMock(),
        # `run_agent` devolvendo None é o caminho curto e limpo do orquestrador
        # ("encaminhar_humano já respondeu"): o processor loga e retorna, sem pacing
        # de bolhas. O que se afirma aqui é SE ele foi chamado, não o que ele produz.
        "llm": AsyncMock(return_value=None),
    }
    p("run_valeria_botoes", new=destinos["valeria"])
    p("run_button_flow", new=destinos["recuperacao"])
    p("run_agent", new=destinos["llm"])
    return destinos


@pytest.fixture(autouse=True)
def _cache_limpo():
    """O cache de perfis do gate é global ao processo e sobrevive entre testes."""
    runner.limpar_cache_de_perfis()
    yield
    runner.limpar_cache_de_perfis()


@pytest.fixture
def desligados(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)


@pytest.fixture
def valeria_ligada(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")


@pytest.fixture
def recuperacao_ligada(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)


# ── 1. Com tudo desligado, nada muda — e nem uma consulta a mais ─────────────
@pytest.mark.asyncio
async def test_com_os_dois_fluxos_off_o_inbound_vai_para_o_LLM_sem_ler_perfil(desligados):
    """O contrato de custo do gate: com todos os fluxos off ele responde sem TOCAR NO
    BANCO. Sem isso, cada mensagem de cada número do CRM pagaria uma consulta a
    `agent_profiles` para descobrir algo que já está decidido."""
    perfil = MagicMock()
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA, conversation=_conversa(), lead=_lead(),
            texto="bom dia, queria saber dos preços",
        )
        stack.enter_context(patch.object(runner, "get_agent_profile", perfil))
        await P.process_buffered_messages(
            "5534988861441", "bom dia, queria saber dos preços", "674beb13",
            wamid="wamid.in",
        )

    perfil.assert_not_called()
    destinos["valeria"].assert_not_awaited()
    destinos["recuperacao"].assert_not_awaited()
    destinos["llm"].assert_awaited_once()


# ── 2. Na ValerIA de botões o LLM não roda ──────────────────────────────────
@pytest.mark.asyncio
async def test_conversa_da_valeria_vai_para_o_runner_dela(valeria_ligada):
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA, conversation=_conversa(), lead=_lead(),
            texto="Quero comprar", message_type="button",
            metadata={"payload": "comprar", "title": "Quero comprar"},
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(FLUXO_VALERIA)),
        ))
        await P.process_buffered_messages(
            "5534988861441", "Quero comprar", "674beb13", wamid="wamid.in",
        )

    destinos["valeria"].assert_awaited_once()
    kwargs = destinos["valeria"].await_args.kwargs
    assert kwargs["metadata"]["payload"] == "comprar"
    assert kwargs["texto"] == "Quero comprar"
    assert kwargs["wamid"] == "wamid.in"
    assert kwargs["conversation"]["id"] == "C1"
    destinos["recuperacao"].assert_not_awaited()


@pytest.mark.asyncio
async def test_a_valeria_de_botoes_nunca_chama_o_orquestrador(valeria_ligada):
    """"Zero IA" é o orquestrador NÃO SER CHAMADO, não o classificador estar off.

    O gate fica antes de `VALERIA_ENABLED` e de `lead.ai_enabled`, então este lead
    (ai_enabled=True, canal mode='ai') é exatamente quem o LLM atenderia — e é por
    isso que o `return` depois do fluxo é incondicional."""
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA, conversation=_conversa(),
            lead=_lead(ai_enabled=True), texto="quero 20kg de café",
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(FLUXO_VALERIA)),
        ))
        await P.process_buffered_messages(
            "5534988861441", "quero 20kg de café", "674beb13", wamid="wamid.in",
        )

    destinos["valeria"].assert_awaited_once()
    destinos["llm"].assert_not_awaited()


# ── 3. A Recuperação continua no runner dela (regressão) ────────────────────
@pytest.mark.asyncio
async def test_conversa_da_recuperacao_continua_no_runner_da_recuperacao(recuperacao_ligada):
    """`flow_id` NULL é `recuperacao_v1`: o perfil que já roda em produção continua
    funcionando sem nenhum UPDATE (20260929_valeria_botoes.sql, §2)."""
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(channel_id="a3a607b1"),
            lead=_lead(ai_enabled=False), texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(None)),
        ))
        await P.process_buffered_messages(
            "5534988861441", "Preciso repor", "a3a607b1", wamid="wamid.in",
        )

    destinos["recuperacao"].assert_awaited_once()
    assert destinos["recuperacao"].await_args.kwargs["metadata"]["payload"] == "repor"
    destinos["valeria"].assert_not_awaited()
    destinos["llm"].assert_not_awaited()


@pytest.mark.asyncio
async def test_ligar_a_valeria_nao_redireciona_a_conversa_da_recuperacao(monkeypatch):
    """Os dois ligados ao mesmo tempo: cada conversa vai para o SEU runner."""
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_JOAO, conversation=_conversa(channel_id="a3a607b1"),
            lead=_lead(ai_enabled=False), texto="Preciso repor", message_type="button",
            metadata={"payload": "repor", "title": "Preciso repor"},
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(FLUXO_RECUP)),
        ))
        await P.process_buffered_messages(
            "5534988861441", "Preciso repor", "a3a607b1", wamid="wamid.in",
        )

    destinos["recuperacao"].assert_awaited_once()
    destinos["valeria"].assert_not_awaited()


# ── 4. Erro ao resolver o fluxo cai no LLM (fail-OPEN) ──────────────────────
@pytest.mark.asyncio
async def test_erro_ao_resolver_o_fluxo_cai_no_caminho_normal(valeria_ligada):
    """Perfil apagado, coluna ainda não migrada, banco fora: segue o fluxo normal.
    Fail-closed aqui sequestraria uma conversa humana por erro de leitura."""
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA, conversation=_conversa(), lead=_lead(),
            texto="oi",
        )
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(side_effect=RuntimeError("sem banco")),
        ))
        await P.process_buffered_messages(
            "5534988861441", "oi", "674beb13", wamid="wamid.in",
        )

    destinos["valeria"].assert_not_awaited()
    destinos["recuperacao"].assert_not_awaited()
    destinos["llm"].assert_awaited_once()


# ── O despachante, isolado ──────────────────────────────────────────────────
class TestODespachante:
    """`_runner_do_fluxo` é a decisão "qual motor atende este fluxo" — pequena o
    suficiente para ser exercitada sem o pipeline."""

    def test_sem_fluxo_nao_ha_runner(self):
        assert P._runner_do_fluxo(None) is None

    def test_cada_fluxo_no_seu_runner(self):
        assert P._runner_do_fluxo(FLUXO_VALERIA) is P.run_valeria_botoes
        assert P._runner_do_fluxo(FLUXO_RECUP) is P.run_button_flow

    def test_fluxo_sem_runner_nao_cai_no_runner_errado(self):
        """Um `flow_id` novo em `config._CHAVE_POR_FLUXO` sem despacho aqui não pode
        herdar o runner da Recuperação — seria um robô no número pessoal do vendedor
        por esquecimento de uma linha."""
        assert P._runner_do_fluxo("fluxo_que_nao_existe") is None

    def test_o_despacho_enxerga_o_patch_do_modulo(self):
        """Trava do próprio arquivo: uma tabela de funções congelada no import não é
        alcançada por `patch.object(processor, "run_button_flow", ...)`, e os testes
        de gate passariam a exercitar o runner de verdade em silêncio."""
        with patch.object(P, "run_button_flow", new=AsyncMock()) as dublê:
            assert P._runner_do_fluxo(FLUXO_RECUP) is dublê


# ── 5. A colisão de opt-out cobre os DOIS fluxos ────────────────────────────
class TestColisaoDeOptOut:
    CONVERSA = {"id": "C1", "agent_profile_id": "P-BOT"}

    def _cabe(self, lead, channel, perfil_flow_id) -> bool:
        with patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(perfil_flow_id)),
        ):
            return P._optout_deterministico_cabe(channel, lead, self.CONVERSA)

    def test_conversa_da_valeria_NAO_roda_o_caminho_deterministico(self, valeria_ligada):
        """O conserto. A ValerIA de botões tem opt-out próprio (`effects._aplicar_optout`:
        move o card para "Descadastrado" e grava `opt_out_evidence`). Rodando os dois no
        mesmo turno, `move_lead_deals_to_blacklist` troca o `pipeline_id` de todos os
        deals e a guarda de funil de `effects._mover_deal` recusa mover para
        "Descadastrado" — a etapa nunca recebe ninguém."""
        assert self._cabe({"ai_enabled": False}, CANAL_VALERIA, FLUXO_VALERIA) is False

    def test_conversa_da_recuperacao_tambem_nao_roda(self, recuperacao_ligada):
        assert self._cabe({"ai_enabled": False}, CANAL_JOAO, None) is False

    def test_com_a_valeria_de_botoes_off_o_caminho_deterministico_vale(self, desligados):
        """Kill switch do fluxo desligado devolve o turno ao caminho determinístico —
        ninguém fica sem saída digna."""
        assert self._cabe({"ai_enabled": False}, CANAL_VALERIA, FLUXO_VALERIA) is True

    def test_perfil_llm_no_mesmo_canal_continua_no_caminho_deterministico(self, valeria_ligada):
        """Com a ValerIA de botões ligada, uma conversa de perfil `llm` NO MESMO CANAL
        não é do fluxo — e o opt-out determinístico continua valendo para ela."""
        with patch.object(
            runner, "get_agent_profile", MagicMock(return_value={"id": "p", "kind": "llm"}),
        ):
            assert P._optout_deterministico_cabe(
                CANAL_JOAO, {"ai_enabled": False}, self.CONVERSA,
            ) is True

    def test_publico_da_IA_nem_consulta_o_fluxo(self, valeria_ligada):
        """A ordem das checagens: para quem a IA atende a resposta já está decidida, e
        resolver o fluxo custa uma leitura de `agent_profiles`."""
        perfil = MagicMock()
        with patch.object(runner, "get_agent_profile", perfil), \
             patch.object(P, "VALERIA_ENABLED", True):
            assert P._optout_deterministico_cabe(
                CANAL_VALERIA, {"ai_enabled": True}, self.CONVERSA,
            ) is False
        perfil.assert_not_called()


# ── 6. A ponte pós-handoff manda o cartão de quem recebeu o lead ────────────
def _lead_transbordado(vendedor: str | None) -> dict:
    """Lead pós-handoff (as condições da ponte) com o carimbo `metadata.handoff`.

    `effects._aplicar_handoff` e `agent/tools.encaminhar_humano` gravam os dois o
    MESMO carimbo — é ele que diz quem recebeu este lead.
    """
    meta: dict = {}
    if vendedor is not None:
        meta["handoff"] = {"vendedor": vendedor, "motivo": "quer repor", "origem": "button_flow"}
    return _lead(
        id="L-transbordado", human_control=True, ai_enabled=False, opt_out=False,
        stage="atacado", metadata=meta,
    )


async def _rodar_ponte(lead: dict):
    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.ponte"}]})
    provider.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.cartao"}]})
    conversa = _conversa(id="C-ponte")
    with patch.object(P, "_get_buffer_redis", return_value=_BridgeFakeRedis()), \
         patch.object(P, "save_message") as salvas:
        enviado = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversa, CANAL_VALERIA, provider,
        )
    return enviado, provider, salvas


class TestVendedorDaPonte:
    def test_carimbo_do_arthur_resolve_o_cartao_do_arthur(self):
        assert P._vendedor_da_ponte(_lead_transbordado("Arthur")) == (
            EXPORTACAO_NAME, EXPORTACAO_PHONE, "Arthur",
        )

    @pytest.mark.parametrize("gravado", [
        "Joao Bras",            # identificador do registry da ValerIA de botões
        "João Brás",            # o que o LLM manda em `encaminhar_humano`
        SUPERVISOR_NAME,        # o que `effects._aplicar_handoff` grava por default
    ])
    def test_as_grafias_do_joao_resolvem_o_cartao_do_joao(self, gravado):
        """O MESMO vendedor é gravado com grafias diferentes por caminhos diferentes;
        casar a string inteira erraria em quase todas."""
        assert P._vendedor_da_ponte(_lead_transbordado(gravado)) == (
            SUPERVISOR_NAME, SUPERVISOR_PHONE, "João",
        )

    @pytest.mark.parametrize("lead", [
        _lead_transbordado(None),                               # sem carimbo nenhum
        _lead(metadata={"handoff": {}}),                        # carimbo sem vendedor
        _lead(metadata={"handoff": "sim"}),                     # carimbo corrompido
        _lead(metadata=None),                                   # metadata NULL
        _lead(metadata={"handoff": {"vendedor": "Vendedor"}}),  # default do LLM
    ])
    def test_sem_vendedor_reconhecivel_cai_no_joao(self, lead):
        """Fail-open no comportamento de hoje: na dúvida, o vendedor padrão."""
        assert P._vendedor_da_ponte(lead) == (SUPERVISOR_NAME, SUPERVISOR_PHONE, "João")


class TestPonteComOVendedorCerto:
    @pytest.mark.asyncio
    async def test_lead_do_arthur_recebe_o_cartao_do_arthur(self):
        """O defeito: um lead de EXPORTAÇÃO que escreve de novo depois do handoff
        recebia o cartão do João e o texto "tá com o João"."""
        enviado, provider, salvas = await _rodar_ponte(_lead_transbordado("Arthur"))

        assert enviado is True
        provider.send_contact.assert_awaited_once_with(
            "5534988861441", contact_name=EXPORTACAO_NAME, contact_phone=EXPORTACAO_PHONE,
        )
        texto = provider.send_text.await_args.args[1]
        assert "Arthur" in texto and "João" not in texto
        marcador = salvas.call_args_list[1].args[3]
        assert marcador == f"[ponte] cartão de contato de {EXPORTACAO_NAME} reenviado"

    @pytest.mark.asyncio
    async def test_lead_do_joao_continua_recebendo_o_cartao_do_joao(self):
        enviado, provider, salvas = await _rodar_ponte(_lead_transbordado("Joao Bras"))

        assert enviado is True
        provider.send_contact.assert_awaited_once_with(
            "5534988861441", contact_name=SUPERVISOR_NAME, contact_phone=SUPERVISOR_PHONE,
        )
        provider.send_text.assert_awaited_once_with("5534988861441", P._BRIDGE_TEXT)

    @pytest.mark.asyncio
    async def test_lead_sem_carimbo_mantem_o_comportamento_de_hoje(self):
        """Trava de regressão: sem vendedor registrado a ponte é byte a byte a de
        antes — texto, cartão e marcador."""
        enviado, provider, salvas = await _rodar_ponte(_lead_transbordado(None))

        assert enviado is True
        provider.send_text.assert_awaited_once_with("5534988861441", P._BRIDGE_TEXT)
        provider.send_contact.assert_awaited_once_with(
            "5534988861441", contact_name=SUPERVISOR_NAME, contact_phone=SUPERVISOR_PHONE,
        )
        assert salvas.call_args_list[1].args[3] == (
            "[ponte] cartão de contato de João - Café Canastra reenviado"
        )

    @pytest.mark.asyncio
    async def test_aviso_de_recebimento_nomeia_o_vendedor_certo(self):
        """Mesma pessoa nos TRÊS textos da ponte: o de roteamento, o aviso de
        recebimento e o de escalonamento. Consertar só um seria meio conserto."""
        lead = _lead_transbordado("Arthur")
        provider = AsyncMock()
        provider.send_text = AsyncMock(return_value={"messages": [{"id": "w.ack"}]})
        with patch.object(P, "_get_buffer_redis", return_value=_BridgeFakeRedis()), \
             patch.object(P, "save_message"):
            await P._maybe_send_handoff_bridge(
                lead, lead["phone"], _conversa(id="C-ack"), CANAL_VALERIA, provider,
                inbound_text="vocês entregam em Maceió?",
            )

        texto = provider.send_text.await_args.args[1]
        assert "Arthur" in texto and "João" not in texto

    @pytest.mark.asyncio
    async def test_escalonamento_nomeia_o_vendedor_certo(self):
        lead = _lead_transbordado("Arthur")
        provider = AsyncMock()
        provider.send_text = AsyncMock(return_value={"messages": [{"id": "w.esc"}]})
        with patch.object(P, "_get_buffer_redis", return_value=_BridgeFakeRedis()), \
             patch.object(P, "save_message"), \
             patch.object(P, "create_system_alert", MagicMock()):
            await P._maybe_send_handoff_bridge(
                lead, lead["phone"], _conversa(id="C-esc"), CANAL_VALERIA, provider,
                inbound_text="que absurdo, ninguém me responde",
            )

        texto = provider.send_text.await_args.args[1]
        assert "Arthur" in texto and "João" not in texto

    def test_os_textos_default_seguem_sendo_os_do_brief(self):
        """Os moldes renderizados com o vendedor padrão têm de ser exatamente os
        textos que a suíte da ponte já trava — o conserto é de destinatário, não de
        copy."""
        assert P._BRIDGE_TEXT == (
            "seu atendimento tá com o João agora\n\n"
            "se preferir, chama ele direto no contato que te mandei aqui em cima "
            "que ele te responde por lá"
        )
        assert P._BRIDGE_ACK_TEXT == (
            "recebi sua mensagem!\n\n"
            "seu atendimento já tá com o João e ele te responde por aqui mesmo, tá?"
        )
