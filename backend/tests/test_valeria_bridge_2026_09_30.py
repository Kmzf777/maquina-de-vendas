"""O handoff dos fluxos de botões e a ponte pós-handoff — 2026-09-30.

O DEFEITO: `effects._aplicar_handoff` desligava a IA (`ai_enabled=False`) e NÃO
carimbava `leads.human_control`. Só `agent/tools.py` (`encaminhar_humano` e as duas
irmãs) escrevia esse campo. A consequência é que um handoff feito por um fluxo de
botões produzia um lead com uma FORMA diferente da de um handoff feito pelo LLM — e
três consumidores leem exatamente essa forma:

  1. a ponte pós-handoff (`buffer/processor._maybe_send_handoff_bridge`) EXIGE
     `human_control is True` para distinguir o transbordo formal de um órfão (o caso
     Rafael, que o Check 2 do watchdog cobre). Sem o carimbo, o trabalho de
     30/09 que fez a ponte resolver o vendedor CERTO — João no atacado e na marca
     própria, Arthur na exportação, lido de `leads.metadata.handoff.vendedor` — era
     código morto para os leads da ValerIA de botões;
  2. `button_flow/runner._motivo_para_nao_rodar`, que é o guarda de "um humano já
     assumiu esta conversa". Sem o carimbo, o motor da ValerIA de botões seguia
     rodando DEPOIS do handoff: o nó terminal `T_HANDOFF` tem tupla de botões vazia,
     então `valeria_engine.decidir` cai na última linha (`_ir_para(ID_HUMANO)`) e
     reaplica `T_HUMANO` A CADA MENSAGEM do lead — tag `TAG_HUMANO` regravada,
     observação e mensagem de sistema novas toda vez, em cima da conversa mais
     valiosa do funil. É o mesmo ruído que `_notificar_sem_rodar` existe para evitar;
  3. o CRM: `lead-card.tsx` e `chat-panel.tsx` só mostram o selo de atendimento
     humano quando `lead.human_control` é verdadeiro.

O CONSERTO É ESTREITO, E A MEDIDA DA ESTREITEZA ESTÁ NESTE ARQUIVO: só a ValerIA de
botões assume o controle humano. A Recuperação — o fluxo que JÁ está em produção —
continua gravando byte a byte o que gravava. As razões estão em
`TestARecuperacaoNaoMuda` e valem mais que um comentário: o fluxo dela roda no número
PESSOAL do vendedor (`mode='human'`), onde a ponte nunca pode rodar (o gate de canal
humano do processor retorna antes dela) e onde o texto dela seria absurdo ("chama ele
direto no contato que te mandei" — na thread dele); o motor dela JÁ ignora os turnos
pós-handoff (nó `encerrado`), então não há ruído a consertar; e `human_control` NÃO é
zerado por um disparo novo em canal humano (`broadcast/worker._build_lead_updates` só
o zera quando `ai_enabled` vai para True, e `_broadcast_ai_enabled` força False em
canal humano) — o carimbo tiraria o bot de cena PARA SEMPRE para aquele lead, em todas
as ondas seguintes, sem nenhum ganho em troca.

A LACUNA QUE ERA ABERTA FOI FECHADA EM 01/10/2026 — ver `TestOQueOCarimboAindaNaoAlcanca`
no fim do arquivo, que passou a pinar o estado novo. Era esta: com o fluxo ATIVO a ponte
não era sequer CHAMADA para a conversa que produziu o handoff, porque o gate dos fluxos
de botões do processor retorna incondicionalmente (e isso continua deliberado — é o que
faz de "zero IA" um fato). O carimbo satisfazia o PORTÃO da ponte e faltava o CALL SITE.
No primeiro dia do fluxo em produção dois leads transbordados voltaram a escrever e
receberam silêncio; agora `valeria_runner.processar_inbound` devolve o MOTIVO de não ter
rodado e o gate chama a ponte quando ele é `runner.MOTIVO_HANDOFF_FORMAL` — e só nele, e
só em canal de IA — ANTES do mesmo `return`, que segue intacto.
"""
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.handoff import handoff_system_marker
from app.agent.tools import (
    EXPORTACAO_NAME,
    EXPORTACAO_PHONE,
    SUPERVISOR_NAME,
    SUPERVISOR_PHONE,
)
from app.buffer import processor as P
from app.button_flow import effects, flows, runner
from app.button_flow import valeria_registry as reg
from app.button_flow.engine import Efeitos

# Dublês reusados em vez de recriados: `_crm_mockado` é a lista completa das portas
# de escrita de `effects` (uma cópia local ficaria desatualizada na primeira porta
# nova e deixaria um efeito batendo no Supabase de verdade), e `_BridgeFakeRedis` tem
# a semântica NX de que o cooldown fail-closed da ponte depende. É o mesmo
# empréstimo que tests/test_valeria_processor_2026_09_30.py já faz.
from tests.test_button_flow_effects_2026_08_20 import (
    MARCADOR_DO_DASHBOARD,
    _crm_mockado,
    _mensagens_de_sistema,
    _stages_movidos,
)
from tests.test_processor_handoff_bridge_2026_07_03 import _BridgeFakeRedis
from tests.test_valeria_processor_2026_09_30 import (
    CANAL_VALERIA,
    FLUXO_VALERIA,
    _conversa,
    _patch_pipeline,
    _perfil,
)

# Os dois motivos, já resolvidos: `_motivo_handoff` costura o rótulo do fluxo na
# frase, e o MESMO texto vai para o carimbo `metadata.handoff` e para o marcador que
# o dashboard conta. Escritos aqui à mão de propósito — derivá-los da função sob
# teste faria o teste concordar com qualquer coisa que ela devolvesse.
MOTIVO_RECUPERACAO = "bot de recuperação: lead pediu atendimento do vendedor"
MOTIVO_VALERIA = "bot de botões da ValerIA: lead pediu atendimento do vendedor"


@pytest.fixture(autouse=True)
def _cache_de_perfis_limpo():
    """O cache do gate é global ao processo e sobrevive entre testes."""
    runner.limpar_cache_de_perfis()
    yield
    runner.limpar_cache_de_perfis()


def _lead_cru(**over) -> dict:
    """Lead ANTES do handoff, com as 4 colunas que a ponte lê."""
    lead = {
        "id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
        "name": "Roner Silva", "stage": "atacado", "status": "active",
        "ai_enabled": True, "human_control": False, "opt_out": False,
        "metadata": {},
    }
    lead.update(over)
    return lead


def _handoff(fluxo: str, *, vendedor: str | None = None,
             silenciar_ia: bool = False, tags: tuple = ()) -> tuple[dict, object]:
    """Roda o handoff e devolve (a LINHA do lead como o banco ficaria, o CRM dublado).

    As escritas são REPLAYADAS no dict: `update_lead` está dublado, então o `lead` em
    memória só recebe o `metadata` (por `atualizar_metadata`). Aplicar por cima dele
    tudo o que foi para `update_lead` é o que torna os testes da ponte honestos — eles
    recebem a forma que o próximo `get_or_create_lead` leria do banco, não uma forma
    escrita à mão que poderia divergir do que o efeito de fato grava.
    """
    lead = _lead_cru()
    with _crm_mockado() as crm:
        ok = effects.aplicar(
            Efeitos(tags=tuple(tags), handoff=True, silenciar_ia=silenciar_ia,
                    vendedor=vendedor),
            lead=lead, conversation_id="c1", fluxo=fluxo,
        )
    assert ok is True, "handoff é fail-soft: nunca bloqueia o avanço do nó"
    for chamada in crm.upd.call_args_list:
        lead.update(chamada.kwargs)
    return lead, crm


def _colunas_gravadas(crm) -> list[dict]:
    """Os updates de COLUNA (sem o de `metadata`), na ordem em que saíram."""
    return [c.kwargs for c in crm.upd.call_args_list if "metadata" not in c.kwargs]


# ── 1. O carimbo ────────────────────────────────────────────────────────────
class TestOCarimboDeControleHumano:
    def test_handoff_da_valeria_grava_human_control_junto_de_ai_enabled(self):
        """Num update só, e é o ponto: `ai_enabled=False` sem `human_control=true`
        produz o "órfão" que a ponte recusa de propósito. Os dois campos descrevem o
        MESMO fato (um humano assumiu) e gravá-los em momentos diferentes abriria uma
        janela em que o lead está mudo e ninguém consta como responsável."""
        lead, crm = _handoff(effects.FLUXO_VALERIA, vendedor=reg.VENDEDOR_ATACADO)

        assert _colunas_gravadas(crm) == [{"ai_enabled": False, "human_control": True}]
        assert lead["ai_enabled"] is False
        assert lead["human_control"] is True

    def test_o_terminal_real_silencia_a_ia_e_depois_assume_o_controle(self):
        """`T_HANDOFF`, `T_HANDOFF_PL` e `T_HANDOFF_ARTHUR` declaram os DOIS efeitos
        (`silenciar_ia=True` e `handoff=True`), então o turno faz duas gravações de
        coluna. A segunda não pode perder o carimbo — nem a primeira ganhá-lo:
        `silenciar_ia` é o caminho de quem só insistiu em texto livre, e carimbar
        controle humano lá marcaria como transbordo formal quem nunca foi entregue a
        ninguém (é o que `_silenciar_ia` documenta não querer)."""
        lead, crm = _handoff(effects.FLUXO_VALERIA, vendedor=reg.VENDEDOR_EXPORTACAO,
                             silenciar_ia=True, tags=(reg.TAG_QUALIFICADO,))

        assert _colunas_gravadas(crm) == [
            {"ai_enabled": False},
            {"ai_enabled": False, "human_control": True},
        ]
        assert lead["human_control"] is True
        # E o carimbo que a ponte lê depois: o vendedor do terminal (não o padrão) e
        # o motivo com o rótulo DESTE bot — é o que o vendedor lê antes de abordar.
        assert lead["metadata"]["handoff"]["vendedor"] == reg.VENDEDOR_EXPORTACAO
        assert lead["metadata"]["handoff"]["motivo"] == MOTIVO_VALERIA

    def test_silenciar_ia_sozinho_nao_assume_o_controle(self):
        """`T_HUMANO` (pediu pessoa / digitou 3 vezes) não é transbordo formal: não
        carimba `metadata.handoff`, então a ponte não teria de quem falar e cairia no
        vendedor padrão — o João — inclusive para um lead de exportação."""
        lead = _lead_cru()
        with _crm_mockado() as crm:
            effects.aplicar(Efeitos(tags=(reg.TAG_HUMANO,), silenciar_ia=True),
                            lead=lead, conversation_id="c1",
                            fluxo=effects.FLUXO_VALERIA)

        assert _colunas_gravadas(crm) == [{"ai_enabled": False}]
        assert lead["human_control"] is False


# ── 2. A Recuperação não muda ───────────────────────────────────────────────
class TestARecuperacaoNaoMuda:
    """O fluxo em produção grava byte a byte o que gravava antes de 30/09.

    Três razões para NÃO estender o carimbo a ele, e a terceira é a que torna a
    mudança larga uma regressão:

      • a ponte nunca roda no número dele. O gate `channel.mode == 'human'` do
        processor retorna ANTES da chamada da ponte, e o texto dela ("chama ele direto
        no contato que te mandei") seria absurdo na própria thread do vendedor;
      • não há ruído a consertar. Depois do handoff o nó é `encerrado` e
        `engine.decidir` devolve `ignorar` — os turnos seguintes já são silenciosos,
        ao contrário do motor da ValerIA de botões;
      • `human_control` NÃO é zerado por uma onda nova em canal humano
        (`broadcast/worker._build_lead_updates` só o zera quando `ai_enabled` vai para
        True, e `_broadcast_ai_enabled` força False em canal humano), enquanto
        `_seed_flow_state` RESETA o `flow_state` a cada envio — de propósito, "um
        template novo reabre a pergunta". Ou seja: o guarda de etapa é reversível pelo
        disparo e o carimbo não seria. Um lead transbordado na onda 1 e reincluído na
        onda 3 receberia o template e ficaria SEM RESPOSTA ao clique.
    """

    def test_o_handoff_da_recuperacao_grava_exatamente_o_que_gravava(self):
        lead, crm = _handoff(effects.FLUXO_RECUPERACAO, tags=(flows.TAG_QUENTE,))

        # 1. Colunas: só `ai_enabled`. A chave `human_control` não aparece em NENHUM
        #    update — nem com valor False, que também seria uma escrita nova.
        assert _colunas_gravadas(crm) == [{"ai_enabled": False}]
        assert not any("human_control" in c.kwargs for c in crm.upd.call_args_list)
        assert lead["human_control"] is False

        # 2. Tag pelo helper existente.
        crm.add.assert_called_once_with("L1", [flows.TAG_QUENTE])

        # 3. Carimbo `metadata.handoff` — o que `follow_up.should_proactive_handoff`
        #    lê para não reentregar sozinho um lead já entregue, e de onde a ponte
        #    resolve o vendedor. Forma COMPLETA: um campo a mais ou a menos aqui muda
        #    o contrato de dois consumidores.
        carimbo = lead["metadata"]["handoff"]
        assert set(carimbo) == {"vendedor", "motivo", "at", "origem"}
        assert carimbo["vendedor"] == SUPERVISOR_NAME
        assert carimbo["motivo"] == MOTIVO_RECUPERACAO
        assert carimbo["origem"] == "button_flow"
        assert carimbo["at"].startswith("20")

        # 4. Marcador do dashboard: exatamente UM (o KPI faz count(*)).
        marcadores = [t for t in _mensagens_de_sistema(crm.save)
                      if t.startswith(MARCADOR_DO_DASHBOARD)]
        assert marcadores == [handoff_system_marker(SUPERVISOR_NAME, MOTIVO_RECUPERACAO)]

        # 5. Card para "Quer repor" — a conversão do agente (`conversion_event`).
        assert _stages_movidos(crm) == [effects.STAGE_QUER_REPOR[0]]

        # 6. Observação de transbordo, uma só.
        assert crm.obs.call_count == 1
        assert crm.obs.call_args.args[1].startswith(
            f"➡️ [TRANSBORDO p/ {SUPERVISOR_NAME}] {MOTIVO_RECUPERACAO}")

    def test_o_default_de_aplicar_continua_sendo_a_recuperacao(self):
        """Quem chama sem `fluxo` é o runner em produção: o default não pode assumir
        controle humano por omissão."""
        lead = _lead_cru()
        with _crm_mockado() as crm:
            effects.aplicar(Efeitos(handoff=True), lead=lead, conversation_id="c1")

        assert _colunas_gravadas(crm) == [{"ai_enabled": False}]
        assert lead["metadata"]["handoff"]["motivo"] == MOTIVO_RECUPERACAO


# ── 3. O portão da ponte ────────────────────────────────────────────────────
async def _rodar_ponte(lead: dict):
    """Chama a ponte com o lead na forma em que o handoff o deixou."""
    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.ponte"}]})
    provider.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.cartao"}]})
    conversa = {"id": "C-ponte", "stage": lead.get("stage")}
    with patch.object(P, "_get_buffer_redis", return_value=_BridgeFakeRedis()), \
         patch.object(P, "save_message", MagicMock()):
        enviado = await P._maybe_send_handoff_bridge(
            lead, lead["phone"], conversa, CANAL_VALERIA, provider,
        )
    return enviado, provider


class TestAPonteAceitaOLeadDaValeria:
    @pytest.mark.asyncio
    async def test_o_lead_de_exportacao_passa_no_portao_e_recebe_o_cartao_do_arthur(self):
        """O portão e o destinatário no mesmo teste: sem `human_control` a ponte nem
        chegava a resolver o vendedor, e o conserto de 30/09 (carimbo →
        `_vendedor_da_ponte`) ficava inalcançável justamente para os leads que ele
        existe para atender."""
        lead, _ = _handoff(effects.FLUXO_VALERIA, vendedor=reg.VENDEDOR_EXPORTACAO,
                           silenciar_ia=True, tags=(reg.TAG_QUALIFICADO,))

        enviado, provider = await _rodar_ponte(lead)

        assert enviado is True
        provider.send_contact.assert_awaited_once_with(
            lead["phone"], contact_name=EXPORTACAO_NAME, contact_phone=EXPORTACAO_PHONE,
        )
        assert "Arthur" in provider.send_text.await_args.args[1]

    @pytest.mark.asyncio
    async def test_o_lead_de_atacado_recebe_o_cartao_do_joao(self):
        lead, _ = _handoff(effects.FLUXO_VALERIA, vendedor=reg.VENDEDOR_ATACADO,
                           silenciar_ia=True, tags=(reg.TAG_QUALIFICADO,))

        enviado, provider = await _rodar_ponte(lead)

        assert enviado is True
        provider.send_contact.assert_awaited_once_with(
            lead["phone"], contact_name=SUPERVISOR_NAME, contact_phone=SUPERVISOR_PHONE,
        )

    @pytest.mark.asyncio
    async def test_o_lead_da_recuperacao_continua_fora_da_ponte(self):
        """Regressão do estreitamento: o fluxo da Recuperação roda no número do
        próprio vendedor, onde a ponte é absurda — e o processor nem a chama lá."""
        lead, _ = _handoff(effects.FLUXO_RECUPERACAO, tags=(flows.TAG_QUENTE,))

        enviado, provider = await _rodar_ponte(lead)

        assert enviado is False
        provider.send_text.assert_not_awaited()
        provider.send_contact.assert_not_awaited()


# ── 4. O turno SEGUINTE ao handoff ──────────────────────────────────────────
class TestOTurnoSeguinteAoHandoff:
    """O que `_motivo_para_nao_rodar` passa a responder, fixado explicitamente.

    Carimbar `human_control` muda o turno seguinte, e essa mudança é o SEGUNDO ganho
    do conserto (o primeiro é a ponte): sem ela o motor da ValerIA de botões seguia
    rodando depois do handoff — `T_HANDOFF` tem tupla de botões vazia, `decidir` cai
    em `_ir_para(ID_HUMANO)` e reaplica `T_HUMANO` a CADA mensagem, regravando tag,
    observação e mensagem de sistema. Com o carimbo, o guarda tira o bot de cena e
    `_notificar_sem_rodar` anota UMA vez por conversa.
    """

    ESTADO_POS_HANDOFF = {"flow": reg.FLOW_ID, "node": "T_HANDOFF", "nudges": 0}

    def test_a_valeria_recusa_o_turno_e_nem_consulta_a_blacklist(self):
        lead, _ = _handoff(effects.FLUXO_VALERIA, vendedor=reg.VENDEDOR_ATACADO,
                           silenciar_ia=True)

        with patch.object(runner, "is_lead_blacklisted", MagicMock()) as blacklist:
            motivo = runner._motivo_para_nao_rodar(lead, self.ESTADO_POS_HANDOFF, None)

        assert motivo == "human_control=true (handoff formal já registrado)"
        # O guarda de memória é o primeiro da ordem de propósito: o terceiro vai ao
        # banco, e ele não deve custar uma consulta num turno já decidido.
        blacklist.assert_not_called()

    def test_a_recuperacao_continua_sem_motivo_para_sair_de_cena(self):
        """Pinagem do lado que NÃO mudou. O turno seguinte segue entrando no motor,
        que devolve `ignorar` no nó `encerrado` — silêncio, como antes."""
        lead, _ = _handoff(effects.FLUXO_RECUPERACAO, tags=(flows.TAG_QUENTE,))

        with patch.object(runner, "is_lead_blacklisted", MagicMock(return_value=False)):
            motivo = runner._motivo_para_nao_rodar(
                lead, {"flow": flows.FLOW_ID, "node": flows.NO_ENCERRADO}, None,
            )

        assert motivo is None


# ── 5. O que o carimbo alcança agora (a lacuna, fechada em 01/10) ───────────
class TestOQueOCarimboAindaNaoAlcanca:
    """A metade que faltava — FECHADA em 01/10/2026, e esta classe passa a pinar isso.

    O que esta classe pinava antes: o portão da ponte passou a ser satisfeito em 30/09
    (o carimbo de `human_control`), mas o CALL SITE dela ficava DEPOIS do gate dos
    fluxos de botões, e esse gate retorna incondicionalmente. Com o fluxo ATIVO a
    conversa que produziu o handoff voltava sempre para o runner, que saía de cena em
    silêncio, e a ponte NÃO era chamada. A docstring dizia: "fechar a outra metade é
    uma decisão de DESPACHO (o gate cair para a ponte quando o fluxo declina o turno, e
    só em canal de IA — em canal humano a ponte seria absurda) […] Se alguém a tomar,
    ESTE teste falha e é aqui que a decisão fica escrita".

    A decisão foi tomada, e não por preferência: no primeiro dia do fluxo em produção
    (01/10) DOIS dos 10 leads reais eram transbordos antigos (31/07 e 28/08) que
    voltaram a escrever e receberam silêncio — o `5511950821962` escreveu "O kilo sai
    25 reais" às 12:47. O conserto é o descrito acima, exatamente: `processar_inbound`
    devolve o MOTIVO de não ter rodado, o gate chama a ponte quando o motivo é
    `runner.MOTIVO_HANDOFF_FORMAL` (e só nele, e só em canal de IA) e CONTINUA
    retornando — o `return` incondicional segue intacto, nenhum caminho novo alcança
    `run_agent`. Ver tests/test_botoes_pos_producao_2026_10_01.py.

    As asserções abaixo invertem: o que era `ponte.assert_not_awaited()` com o fluxo
    ativo agora é `assert_awaited_once()`. O teste do fluxo DESLIGADO não muda uma
    linha — ele sempre descreveu o caminho normal, que continua idêntico. E o nome da
    classe fica: ela continua sendo o lugar onde esta decisão está escrita.
    """

    TEXTO = "e aí, tem novidade do meu pedido?"

    def _lead_transbordado(self) -> dict:
        lead, _ = _handoff(effects.FLUXO_VALERIA, vendedor=reg.VENDEDOR_ATACADO,
                           silenciar_ia=True, tags=(reg.TAG_QUALIFICADO,))
        return lead

    @pytest.mark.asyncio
    async def test_com_o_fluxo_ATIVO_a_ponte_AGORA_e_alcancada(self, monkeypatch):
        """O dublê do runner devolve o MOTIVO porque é o que o runner de verdade
        devolve quando `_motivo_para_nao_rodar` recusa por handoff formal — é a forma
        do contrato novo entre os dois, e `TestOTurnoSeguinteAoHandoff` acima prova que
        esse é o motivo que este lead produz."""
        monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
        monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)

        with ExitStack() as stack:
            destinos = _patch_pipeline(
                stack, channel=CANAL_VALERIA, conversation=_conversa(),
                lead=self._lead_transbordado(), texto=self.TEXTO,
            )
            destinos["valeria"].return_value = runner.MOTIVO_HANDOFF_FORMAL
            stack.enter_context(patch.object(
                runner, "get_agent_profile",
                MagicMock(return_value=_perfil(FLUXO_VALERIA)),
            ))
            ponte = stack.enter_context(patch.object(
                P, "_maybe_send_handoff_bridge", new=AsyncMock(return_value=True),
            ))
            await P.process_buffered_messages(
                "5534988861441", self.TEXTO, "674beb13", wamid="wamid.in",
            )

        destinos["valeria"].assert_awaited_once()
        ponte.assert_awaited_once()
        # O lead que chega à ponte é o mesmo que o handoff deixou: é o carimbo de
        # 30/09 que o portão dela exige, e sem ele este call site novo seria mudo.
        recebido = ponte.await_args.args[0]
        assert recebido["human_control"] is True
        assert recebido["metadata"]["handoff"]["vendedor"] == reg.VENDEDOR_ATACADO
        # E o `return` incondicional segue intacto: a IA generativa não é alcançada.
        destinos["llm"].assert_not_awaited()

    @pytest.mark.asyncio
    async def test_com_o_fluxo_ATIVO_e_turno_atendido_a_ponte_nao_roda(self, monkeypatch):
        """A contra-prova do novo ramo: quando o runner ATENDE o turno (devolve None),
        nada mudou — a ponte em cima de uma tela do fluxo seria uma segunda mensagem
        faturada contradizendo a primeira."""
        monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
        monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)

        with ExitStack() as stack:
            destinos = _patch_pipeline(
                stack, channel=CANAL_VALERIA, conversation=_conversa(),
                lead=self._lead_transbordado(), texto=self.TEXTO,
            )
            destinos["valeria"].return_value = None
            stack.enter_context(patch.object(
                runner, "get_agent_profile",
                MagicMock(return_value=_perfil(FLUXO_VALERIA)),
            ))
            ponte = stack.enter_context(patch.object(
                P, "_maybe_send_handoff_bridge", new=AsyncMock(return_value=False),
            ))
            await P.process_buffered_messages(
                "5534988861441", self.TEXTO, "674beb13", wamid="wamid.in",
            )

        destinos["valeria"].assert_awaited_once()
        ponte.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_com_o_fluxo_DESLIGADO_o_lead_transbordado_chega_a_ponte(self, monkeypatch):
        """E aqui o carimbo já vale hoje: com o kill switch off (o estado do fluxo em
        produção neste momento) a conversa segue o caminho normal e morre no gate de
        `ai_enabled` — que é exatamente onde a ponte vive. O que ela recebe tem de ser
        um lead com controle humano, senão o portão a recusa em silêncio."""
        monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
        monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)

        with ExitStack() as stack:
            destinos = _patch_pipeline(
                stack, channel=CANAL_VALERIA, conversation=_conversa(),
                lead=self._lead_transbordado(), texto=self.TEXTO,
            )
            stack.enter_context(patch.object(P, "VALERIA_ENABLED", True))
            ponte = stack.enter_context(patch.object(
                P, "_maybe_send_handoff_bridge", new=AsyncMock(return_value=True),
            ))
            await P.process_buffered_messages(
                "5534988861441", self.TEXTO, "674beb13", wamid="wamid.in",
            )

        destinos["valeria"].assert_not_awaited()
        destinos["llm"].assert_not_awaited()
        ponte.assert_awaited_once()
        recebido = ponte.await_args.args[0]
        assert recebido["human_control"] is True
        assert recebido["ai_enabled"] is False
        assert recebido["metadata"]["handoff"]["vendedor"] == reg.VENDEDOR_ATACADO
