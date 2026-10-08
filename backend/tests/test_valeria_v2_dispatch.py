"""Kill switch e despacho da ValerIA v2: quem atende o inbound é o fluxo da CONVERSA.

Trocar o perfil do canal de v1 para v2 (ou de volta) não pode reiniciar quem está no
meio do atendimento: o `flow_state.flow` gravado é a memória de qual registry entende
o `node` salvo. `runner.fluxo_efetivo` aplica essa precedência, e só entre os fluxos
da ValerIA — a Recuperação e o perfil desligado continuam como estavam.
"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor as P
from app.button_flow import config, runner
from app.button_flow import valeria_runner_v2
from tests.test_valeria_processor_2026_09_30 import (
    CANAL_VALERIA,
    _conversa,
    _lead,
    _patch_pipeline,
    _perfil,
)

V1 = "valeria_botoes_v1"
V2 = "valeria_botoes_v2"
RECUP = "recuperacao_v1"


@pytest.fixture(autouse=True)
def _cache_limpo():
    runner.limpar_cache_de_perfis()
    yield
    runner.limpar_cache_de_perfis()


@pytest.fixture
def valeria_ligada(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")


def _perfil_do_banco(monkeypatch, flow_id):
    monkeypatch.setattr(runner, "get_agent_profile", lambda _id: _perfil(flow_id))


def _conv(flow_state):
    return {"id": "C1", "agent_profile_id": "P-BOT", "flow_state": flow_state}


def _ha(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _no_meio(flow, node, **delta):
    """`flow_state` de quem está no meio do fluxo: nó vivo, gravado há pouco."""
    return {"flow": flow, "node": node, "updated_at": _ha(**(delta or {"hours": 2}))}


# ── Kill switch ──────────────────────────────────────────────────────────────
def test_v2_responde_a_mesma_chave_da_v1(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    assert config.enabled(V2) is True
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "off")
    assert config.enabled(V2) is False
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    assert config.enabled(V2) is False


def test_v2_nao_liga_a_recuperacao(monkeypatch):
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    assert config.enabled(RECUP) is False


# ── fluxo_efetivo ────────────────────────────────────────────────────────────
def test_conversa_em_andamento_na_v2_termina_na_v2(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V1)
    assert runner.fluxo_efetivo(_conv(_no_meio(V2, "QA1")), {}) == V2


def test_conversa_em_andamento_na_v1_termina_na_v1(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(_no_meio(V1, "N2")), {}) == V1


def test_timestamp_com_z_e_aceito(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V2)
    quando = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    estado = {"flow": V1, "node": "N2", "updated_at": quando}
    assert runner.fluxo_efetivo(_conv(estado), {}) == V1


# ── "Em andamento" é estreito: senão todo lead que um dia tocou na v1 ficaria
#    na v1 para sempre depois de o canal virar v2 (o flow_state nunca é limpo).
@pytest.mark.parametrize("flow,terminal", [(V1, "T_HANDOFF"), (V1, "T_OPTOUT"),
                                           (V1, "T_ADIADO"), (V2, "T_KIT"), (V2, "T_HANDOFF_PL")])
def test_conversa_encerrada_num_terminal_vai_para_o_perfil(monkeypatch, valeria_ligada,
                                                           flow, terminal):
    perfil = V2 if flow == V1 else V1
    _perfil_do_banco(monkeypatch, perfil)
    assert runner.fluxo_efetivo(_conv(_no_meio(flow, terminal)), {}) == perfil


def test_t_adiar_nao_encerra_e_continua_no_fluxo_gravado(monkeypatch, valeria_ligada):
    """`T_ADIAR` pergunta o prazo e espera o toque: não é desfecho."""
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(_no_meio(V1, "T_ADIAR")), {}) == V1


def test_no_que_o_fluxo_gravado_nao_conhece_vai_para_o_perfil(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(_no_meio(V1, "QA1")), {}) == V2


def test_estado_com_mais_de_7_dias_vai_para_o_perfil(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(_no_meio(V1, "N2", days=7, minutes=1)), {}) == V2
    assert runner.fluxo_efetivo(_conv(_no_meio(V1, "N2", days=6, hours=23)), {}) == V1


@pytest.mark.parametrize("quando", [None, "", "ontem", 12345, "2026-13-45T00:00:00"])
def test_updated_at_ausente_ou_corrompido_vai_para_o_perfil(monkeypatch, valeria_ligada, quando):
    _perfil_do_banco(monkeypatch, V2)
    estado = {"flow": V1, "node": "N2"}
    if quando is not None:
        estado["updated_at"] = quando
    assert runner.fluxo_efetivo(_conv(estado), {}) == V2


def test_sem_flow_state_vale_o_perfil(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(None), {}) == V2


def test_flow_state_da_recuperacao_nao_sequestra_a_valeria(monkeypatch, valeria_ligada):
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(_no_meio(RECUP, "interesse")), {}) == V2


@pytest.mark.parametrize("estado", ["lixo", ["flow"], {"node": "N1"}, {"flow": None},
                                    {"flow": "fluxo_que_nao_existe"}])
def test_flow_state_corrompido_vale_o_perfil(monkeypatch, valeria_ligada, estado):
    _perfil_do_banco(monkeypatch, V2)
    assert runner.fluxo_efetivo(_conv(estado), {}) == V2


def test_perfil_desligado_continua_none(monkeypatch):
    """Perfil desligado → None continua None, mesmo com a conversa no meio da v2."""
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    _perfil_do_banco(monkeypatch, V1)
    assert runner.fluxo_efetivo(_conv(_no_meio(V2, "QA1")), {}) is None


def test_perfil_llm_nao_vira_valeria_pelo_flow_state(monkeypatch, valeria_ligada):
    """Conversa devolvida ao LLM com `flow_state` velho: o perfil manda."""
    monkeypatch.setattr(runner, "get_agent_profile",
                        lambda _id: {"kind": "llm", "flow_id": None})
    assert runner.fluxo_efetivo(_conv(_no_meio(V2, "QA1")), {}) is None


def test_perfil_da_recuperacao_nao_vira_valeria_pelo_flow_state(monkeypatch):
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    _perfil_do_banco(monkeypatch, RECUP)
    assert runner.fluxo_efetivo(_conv(_no_meio(V2, "QA1")), {}) == RECUP


# ── O despachante ────────────────────────────────────────────────────────────
def test_v2_tem_runner_proprio():
    assert P._runner_do_fluxo(V2) is P.run_valeria_botoes_v2
    assert P.run_valeria_botoes_v2 is valeria_runner_v2.processar_inbound
    assert P._runner_do_fluxo(V1) is P.run_valeria_botoes


def test_despacho_v2_enxerga_o_patch_do_modulo():
    dublê = AsyncMock()
    with patch.object(P, "run_valeria_botoes_v2", dublê):
        assert P._runner_do_fluxo(V2) is dublê


# ── Ponta a ponta: o call site usa o fluxo EFETIVO ──────────────────────────
@pytest.mark.asyncio
async def test_inbound_de_conversa_na_v2_vai_para_o_runner_v2_com_perfil_v1(valeria_ligada):
    v2 = AsyncMock(return_value=None)
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA,
            conversation=_conversa(flow_state=_no_meio(V2, "QA1")),
            lead=_lead(), texto="Cafeteria", message_type="interactive",
            metadata={"payload": "cafeteria", "title": "Cafeteria"},
        )
        stack.enter_context(patch.object(P, "run_valeria_botoes_v2", v2))
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(V1)),
        ))
        await P.process_buffered_messages(
            "5534988861441", "Cafeteria", "674beb13", wamid="wamid.in",
        )

    v2.assert_awaited_once()
    assert v2.await_args.kwargs["metadata"]["payload"] == "cafeteria"
    destinos["valeria"].assert_not_awaited()
    destinos["llm"].assert_not_awaited()


@pytest.mark.asyncio
async def test_perfil_v2_sem_flow_state_vai_para_o_runner_v2(valeria_ligada):
    v2 = AsyncMock(return_value=None)
    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA, conversation=_conversa(), lead=_lead(),
            texto="oi",
        )
        stack.enter_context(patch.object(P, "run_valeria_botoes_v2", v2))
        stack.enter_context(patch.object(
            runner, "get_agent_profile", MagicMock(return_value=_perfil(V2)),
        ))
        await P.process_buffered_messages("5534988861441", "oi", "674beb13", wamid="wamid.in")

    v2.assert_awaited_once()
    destinos["valeria"].assert_not_awaited()
    destinos["llm"].assert_not_awaited()


# ── Opt-out determinístico: "é de ALGUM fluxo" continua verdadeiro na v2 ────
def test_conversa_da_v2_nao_roda_o_optout_deterministico(monkeypatch, valeria_ligada):
    monkeypatch.setattr(P, "VALERIA_ENABLED", True)
    _perfil_do_banco(monkeypatch, V2)
    canal = {"mode": "human"}
    assert P._optout_deterministico_cabe(canal, _lead(), _conv(None)) is False


# ── O runner v2 respeita o kill switch ──────────────────────────────────────
@pytest.mark.asyncio
async def test_runner_v2_com_kill_switch_desligado_nao_faz_nada(monkeypatch):
    """Desligado, o runner sai antes de ler banco ou falar com a Meta."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "off")
    provedor = MagicMock()
    with patch.object(valeria_runner_v2.v1, "_reler_estado") as reler:
        motivo = await valeria_runner_v2.processar_inbound(
            lead={"id": "L1"}, conversation={"id": "C1"}, channel={},
            provider=provedor, texto="oi")
    assert motivo is None
    reler.assert_not_called()
    assert provedor.method_calls == []
