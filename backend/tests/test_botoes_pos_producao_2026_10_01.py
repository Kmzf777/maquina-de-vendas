"""Os dois defeitos de inbound lidos no PRIMEIRO DIA do fluxo em produção — 01/10/2026.

Não são hipóteses: os dois foram lidos nas mensagens gravadas das 10 primeiras
conversas reais do `valeria_botoes_v1`, ativado no canal `553492009777` em 01/10 02:47.

DEFEITO 1 — O LEAD TRANSBORDADO QUE VOLTA RECEBIA SILÊNCIO. Duas das 10 conversas
nunca viram a tela de entrada: são leads que o João assumiu em 31/07 e 28/08. O lead
`5511950821962` escreveu "O kilo sai 25 reais" às 12:47 e não recebeu NADA. No
histórico dele, ANTES da ativação, a mesma situação era respondida — "recebi sua
mensagem! seu atendimento já tá com o João e ele te responde…", que é exatamente o
`P._BRIDGE_ACK_TEXT` deste arquivo. A causa é de POSIÇÃO: o `_maybe_send_handoff_bridge`
mora no ramo de `ai_enabled`, ABAIXO do `return` incondicional do gate dos fluxos de
botões. Antes da ativação o gate não reivindicava a conversa e o inbound chegava lá;
depois, o gate reivindica, `_motivo_para_nao_rodar` recusa em `human_control` e o
`return` fecha o caminho antes da ponte.

O conserto NÃO é um fall-through, e a diferença é o projeto inteiro: aquele `return`
incondicional é o que faz de "zero IA" um FATO (o gate roda antes de `VALERIA_ENABLED`
e de `lead.ai_enabled`, então deixar o inbound seguir reabriria o caminho até
`run_agent` para todo lead com `ai_enabled=True`). Então o GATE chama a ponte e CONTINUA
retornando — e para escolher o ramo ele precisa saber POR QUE o fluxo não rodou:

  • `runner.MOTIVO_HANDOFF_FORMAL` → ponte: há uma pessoa do outro lado, e o lead está
    esperando resposta dela;
  • blacklist → silêncio: o lead pediu para sair, mandar qualquer coisa é o oposto;
  • etapa de deal incompatível → silêncio: não há promessa pendente ao lead.

A comparação é contra a CONSTANTE do módulo dono da frase (`button_flow/runner`), nunca
contra uma segunda cópia do texto: a frase é prosa que vai para a nota do operador, e
uma cópia divergente deixaria o consumidor sem casar nunca — em silêncio. É a classe de
bug que `campaigns/node_registry.py` documenta.

DEFEITO 2 — O NUDGE REENVIAVA A FOTO COMO MENSAGEM FATURADA. Conversa `3c236b3c`: o
lead recebeu a tela de fechamento (foto + preço + botões), escreveu "Valores" e a
resposta foi A IMAGEM DE NOVO, com o texto do nudge na legenda. O nudge devolve
`proximo_no = no_atual` e a estrutura do envio vem de `no.tela`, que em
`N5`/`N5b`/`P4`/`P4b` é `foto_botoes`. Agora o runner lê `decisao.marcar_nudge` (campo
que já existia) e reoferece os botões SEM header de imagem — o nó não muda, muda a forma
de reenviar. O corpo do nudge também deixou de falar de preço: em produção ele respondeu
a um ÁUDIO de número errado e a um VÍDEO, onde "pra eu te passar o valor certo" não faz
sentido nenhum.

Os dublês são os que `tests/test_valeria_processor_2026_09_30.py` e
`tests/test_valeria_runner_2026_09_29.py` já estabelecem — emprestados, não recriados:
uma cópia local do pipeline do processor divergiria na primeira porta nova e passaria a
exercitar o runner de verdade contra um Supabase dublado, em silêncio.
"""
import ast
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor as P
from app.button_flow import effects, valeria_content
from app.button_flow import runner as R
from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as VR
from tests.test_processor_handoff_bridge_2026_07_03 import _BridgeFakeRedis
from tests.test_valeria_processor_2026_09_30 import (
    CANAL_JOAO,
    CANAL_VALERIA,
    FLUXO_RECUP,
    FLUXO_VALERIA,
    _conversa,
    _lead,
    _patch_pipeline,
    _perfil,
)
from tests.test_valeria_runner_2026_09_29 import ProvedorFalso

# O texto REAL do caso que dói, com o número REAL da conversa. Escrito aqui à mão de
# propósito: é o dado de produção que este arquivo existe para reproduzir.
TEXTO_REAL = "O kilo sai 25 reais"
FONE_REAL = "5511950821962"

# Os quatro nós de `foto_botoes` do registry — os únicos em que o defeito 2 aparecia.
NOS_COM_FOTO = ("N5", "N5b", "P4", "P4b")


@pytest.fixture(autouse=True)
def _cache_de_perfis_limpo():
    """O cache de perfis do gate é global ao processo e sobrevive entre testes."""
    R.limpar_cache_de_perfis()
    yield
    R.limpar_cache_de_perfis()


# ═══════════════════════════════════════════════════════════════════════════════
# Defeito 1 · parte A — o MOTIVO sobe do runner
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def turno(monkeypatch):
    """Dirige `processar_inbound` com banco, CRM e histórico dublados.

    Mesma forma das fixtures de `test_valeria_runner_2026_09_29.py` e
    `test_valeria_runner_gaps_2026_09_30.py`, com duas diferenças que os testes deste
    arquivo precisam: devolve o VALOR de `processar_inbound` (o motivo, ou None) e
    conta as PUBLICAÇÕES de foto, que é como se prova que o nudge não republica a
    imagem no bucket.
    """
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    registro = {"efeitos": [], "mensagens": [], "notas": [], "estados": [],
                "publicacoes": []}
    conversa = {"id": "C1", "stage": "atacado", "flow_state": None}
    lead = {"id": "L1", "phone": FONE_REAL, "wa_id": FONE_REAL,
            "name": "Lead", "human_control": False, "metadata": {}}

    def _gravar_estado(_cid, **kw):
        conversa["flow_state"] = kw["flow_state"]
        registro["estados"].append(kw["flow_state"])

    def _publicar(caminho):
        registro["publicacoes"].append(caminho)
        return f"https://storage.exemplo/{caminho}"

    monkeypatch.setattr(VR, "_reler_estado", lambda c: c.get("flow_state"))
    monkeypatch.setattr(VR, "get_open_deal", lambda _l: None)
    monkeypatch.setattr(VR, "update_conversation", _gravar_estado)
    monkeypatch.setattr(VR, "save_message",
                        lambda *a, **k: registro["mensagens"].append({"corpo": a[3], **k}))
    monkeypatch.setattr(VR, "url_publica_da_foto", _publicar)
    monkeypatch.setattr(VR, "preco_do_no", lambda _no: "R$ 28,70")
    monkeypatch.setattr(VR, "save_score_evidence", lambda **_kw: None)
    # O detector de autoresponder pede o lag da nossa última saída; sem dublê cada
    # turno de texto tenta resolver DNS e cai no fail-soft — lentidão por turno.
    monkeypatch.setattr(VR, "_historico", lambda _cid: [])
    # `_motivo_para_nao_rodar` é reusado do irmão e resolve `is_lead_blacklisted` no
    # namespace DELE.
    monkeypatch.setattr(R, "is_lead_blacklisted", lambda _lead_id: False)
    monkeypatch.setattr(valeria_content, "carregar", lambda _f: {})
    monkeypatch.setattr(effects, "anotar", lambda *a: registro["notas"].append(a[2]))
    monkeypatch.setattr(effects, "atualizar_metadata",
                        lambda *_a, **_k: True)

    def _aplicar(efeitos, **_kw):
        registro["efeitos"].append(efeitos)
        return True
    monkeypatch.setattr(effects, "aplicar", _aplicar)

    provedor = ProvedorFalso()

    async def _rodar(texto, *, no=None, payload=None, titulo="", deal=None,
                     blacklist=False):
        if no is not None:
            conversa["flow_state"] = {"flow": reg.FLOW_ID, "node": no, "nudges": 0}
        if deal is not None:
            monkeypatch.setattr(VR, "get_open_deal", lambda _l: deal)
        if blacklist:
            monkeypatch.setattr(R, "is_lead_blacklisted", lambda _lead_id: True)
        meta = {"payload": payload, "title": titulo} if payload else None
        return await VR.processar_inbound(
            lead=lead, conversation=conversa, channel={"mode": "ai"},
            provider=provedor, texto=texto, metadata=meta, wamid="wamid.in",
        )

    _rodar.provedor = provedor
    _rodar.registro = registro
    _rodar.lead = lead
    _rodar.conversa = conversa
    return _rodar


class TestOMotivoSobeAoGate:
    """`processar_inbound` deixa de ser `-> None`: devolve o motivo de não ter rodado.

    É a única informação que falta ao gate para escolher entre falar com o lead e
    continuar em silêncio, e ela já existia dentro do runner — só morria ali.
    """

    @pytest.mark.asyncio
    async def test_handoff_formal_devolve_o_motivo_e_ainda_grava_a_nota(self, turno):
        """Dois públicos, duas saídas: a NOTA diz ao operador que o bot saiu de cena;
        o MOTIVO é o que permite ao gate dizer ao LEAD que alguém o atenderá. Nenhuma
        das duas substitui a outra, e o runner continua sem enviar nada por conta
        própria — quem fala com o lead neste caso é a ponte."""
        turno.lead["human_control"] = True

        motivo = await turno(TEXTO_REAL)

        assert motivo == R.MOTIVO_HANDOFF_FORMAL
        assert len(turno.registro["notas"]) == 1, "a nota do operador não saiu"
        assert turno.provedor.chamadas == [], "o runner falou por cima do vendedor"
        assert turno.registro["efeitos"] == [], "o guarda deixou de ser o primeiro"

    @pytest.mark.asyncio
    async def test_motivo_e_a_constante_do_modulo_dono_da_frase(self, turno):
        """A frase mora em UM lugar só. Comparar contra uma segunda cópia é a
        divergência que `campaigns/node_registry.py` documenta — e aqui ela deixaria o
        lead no vácuo em silêncio, porque nada falharia."""
        turno.lead["human_control"] = True

        motivo = await turno(TEXTO_REAL)

        assert motivo is R.MOTIVO_HANDOFF_FORMAL, "a frase foi recopiada"
        assert R.MOTIVO_HANDOFF_FORMAL.startswith("human_control=true")

    @pytest.mark.asyncio
    async def test_turno_atendido_devolve_None(self, turno):
        """None quer dizer "nada mais a fazer com este inbound" — o lead já foi
        respondido pelo próprio fluxo."""
        devolvido = await turno("oi, queria saber sobre café")

        assert devolvido is None
        assert turno.provedor.chamadas[0][0] == "lista", "a tela de entrada não saiu"

    @pytest.mark.asyncio
    async def test_evento_ignorado_tambem_devolve_None(self, turno):
        """Conversa encerrada: o motor devolve `ignorar`. Ninguém está esperando
        resposta de pessoa nenhuma por causa deste turno — silêncio é a resposta
        certa, e é o que o `return` incondicional do gate já fazia."""
        devolvido = await turno("e aí, tem novidade?", no="T_FIM")

        assert devolvido is None
        assert turno.provedor.chamadas == []

    @pytest.mark.asyncio
    async def test_blacklist_devolve_o_motivo_dela(self, turno):
        """E ele NÃO é o do handoff: quem está na blacklist pediu para sair."""
        devolvido = await turno(TEXTO_REAL, blacklist=True)

        assert devolvido == "blacklist"
        assert devolvido != R.MOTIVO_HANDOFF_FORMAL

    @pytest.mark.asyncio
    async def test_etapa_incompativel_devolve_o_motivo_dela(self, turno):
        """O vendedor já mexeu no card: o bot sai de cena, e não há promessa pendente
        ao lead que justifique mandar qualquer coisa."""
        turno.conversa["flow_state"] = {
            "flow": reg.FLOW_ID, "node": "N1", "nudges": 0,
            "deal_stage_id": "stage-antigo",
        }

        devolvido = await turno(TEXTO_REAL, deal={"id": "d1", "stage_id": "stage-novo"})

        assert devolvido is not None
        assert devolvido.startswith("deal mudou de etapa")
        assert devolvido != R.MOTIVO_HANDOFF_FORMAL

    @pytest.mark.asyncio
    async def test_excecao_no_turno_devolve_None(self, turno, monkeypatch):
        """Fail-soft: o runner nunca levanta. E não aciona a ponte — sobre um estado
        que não se conhece, responder ao lead é pior que calar."""
        def explode(_c):
            raise RuntimeError("PostgREST fora")
        monkeypatch.setattr(VR, "_reler_estado", explode)

        assert await turno(TEXTO_REAL) is None


class TestARecuperacaoNaoMuda:
    """O fluxo em produção continua devolvendo None — comportamento byte-idêntico.

    O call site é um só e compartilhado: se `run_button_flow` passasse a devolver o
    motivo, o gate chamaria a ponte no número PESSOAL do vendedor, onde o texto dela
    ("chama ele direto no contato que te mandei") é absurdo na própria thread dele.
    """

    @pytest.mark.asyncio
    async def test_o_runner_da_recuperacao_nao_vaza_o_motivo_do_guarda(self, monkeypatch):
        """O guarda é COMPARTILHADO (`_motivo_para_nao_rodar` é do irmão), então o
        motivo existe lá dentro — ele só não sobe. A nota continua sendo gravada, com
        a MESMA frase: o que muda é quem a lê."""
        monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
        monkeypatch.setattr(R, "_reler_estado", lambda c: c.get("flow_state"))
        monkeypatch.setattr(R, "get_open_deal", lambda _l: None)
        monkeypatch.setattr(R, "is_lead_blacklisted", lambda _lead_id: False)
        avisou = AsyncMock()
        monkeypatch.setattr(R, "_notificar_sem_rodar", avisou)

        devolvido = await R.run_button_flow(
            lead={"id": "L1", "phone": FONE_REAL, "human_control": True},
            conversation={"id": "C1", "flow_state": None}, channel=CANAL_JOAO,
            provider=AsyncMock(), texto=TEXTO_REAL, wamid="wamid.in",
        )

        assert devolvido is None, "a Recuperação acionaria a ponte no número do João"
        avisou.assert_awaited_once()
        assert avisou.await_args.args[3] == R.MOTIVO_HANDOFF_FORMAL


# ═══════════════════════════════════════════════════════════════════════════════
# Defeito 1 · parte B — o GATE chama a ponte e CONTINUA retornando
# ═══════════════════════════════════════════════════════════════════════════════
def _lead_transbordado(**over) -> dict:
    """Lead pós-handoff formal: as 4 colunas que o portão da ponte lê."""
    campos = {"id": "L-transbordado", "phone": FONE_REAL, "wa_id": FONE_REAL,
              "human_control": True, "ai_enabled": False, "opt_out": False,
              "stage": "atacado"}
    campos.update(over)
    return _lead(**campos)


def _montar_gate(stack: ExitStack, *, lead: dict, channel: dict = CANAL_VALERIA,
                 perfil: str | None = FLUXO_VALERIA, texto: str = TEXTO_REAL):
    """Pipeline do processor + o espião da ponte. Devolve (destinos, ponte)."""
    destinos = _patch_pipeline(
        stack, channel=channel, conversation=_conversa(channel_id=channel["id"]),
        lead=lead, texto=texto,
    )
    stack.enter_context(patch.object(
        R, "get_agent_profile", MagicMock(return_value=_perfil(perfil)),
    ))
    ponte = stack.enter_context(patch.object(
        P, "_maybe_send_handoff_bridge", new=AsyncMock(return_value=True),
    ))
    return destinos, ponte


@pytest.fixture
def valeria_ligada(monkeypatch):
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)


@pytest.mark.asyncio
async def test_o_gate_chama_a_ponte_UMA_vez_no_motivo_do_handoff(valeria_ligada):
    """O conserto, no ponto exato: o fluxo recusou o turno por handoff formal e o lead
    é respondido ANTES do `return` — uma única vez, e com o inbound do turno, que é o
    que escolhe o ramo da escada da ponte (reação / encerramento social / reclamação /
    pergunta de negócio)."""
    with ExitStack() as stack:
        destinos, ponte = _montar_gate(stack, lead=_lead_transbordado())
        destinos["valeria"].return_value = R.MOTIVO_HANDOFF_FORMAL
        await P.process_buffered_messages(
            FONE_REAL, TEXTO_REAL, CANAL_VALERIA["id"], wamid="wamid.in",
        )

    destinos["valeria"].assert_awaited_once()
    ponte.assert_awaited_once()
    assert ponte.await_args.kwargs["inbound_text"] == TEXTO_REAL
    assert ponte.await_args.kwargs["inbound_wamid"] == "wamid.in"


@pytest.mark.asyncio
async def test_a_ponte_nao_reabre_o_caminho_do_LLM(valeria_ligada):
    """A trava que torna o conserto aceitável: o `return` incondicional segue intacto.
    Este lead tem `ai_enabled=False`, mas o gate está ANTES desse gate — e o que não
    pode existir é um caminho novo até `run_agent` em fluxo de botões."""
    with ExitStack() as stack:
        destinos, ponte = _montar_gate(
            stack, lead=_lead_transbordado(ai_enabled=True),
        )
        destinos["valeria"].return_value = R.MOTIVO_HANDOFF_FORMAL
        await P.process_buffered_messages(
            FONE_REAL, TEXTO_REAL, CANAL_VALERIA["id"], wamid="wamid.in",
        )

    ponte.assert_awaited_once()
    destinos["llm"].assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("motivo", [
    "blacklist",
    "deal mudou de etapa (stage-antigo -> stage-novo)",
])
async def test_os_outros_dois_motivos_continuam_em_silencio(valeria_ligada, motivo):
    """Blacklist pediu para sair — mandar qualquer coisa é o oposto do pedido. Etapa
    incompatível não tem promessa pendente ao lead. Os dois seguem mudos, e é por isso
    que o gate compara o motivo em vez de olhar "o fluxo recusou?"."""
    with ExitStack() as stack:
        destinos, ponte = _montar_gate(stack, lead=_lead_transbordado())
        destinos["valeria"].return_value = motivo
        await P.process_buffered_messages(
            FONE_REAL, TEXTO_REAL, CANAL_VALERIA["id"], wamid="wamid.in",
        )

    destinos["valeria"].assert_awaited_once()
    ponte.assert_not_awaited()
    destinos["llm"].assert_not_awaited()


@pytest.mark.asyncio
async def test_turno_atendido_pelo_fluxo_nao_chama_a_ponte(valeria_ligada):
    """None é o caso comum (o fluxo respondeu). A ponte em cima de uma tela do fluxo
    seria uma segunda mensagem faturada contradizendo a primeira."""
    with ExitStack() as stack:
        destinos, ponte = _montar_gate(stack, lead=_lead(), texto="Quero comprar")
        destinos["valeria"].return_value = None
        await P.process_buffered_messages(
            FONE_REAL, "Quero comprar", CANAL_VALERIA["id"], wamid="wamid.in",
        )

    destinos["valeria"].assert_awaited_once()
    ponte.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_numero_do_vendedor_a_ponte_nao_roda(monkeypatch):
    """A outra metade da decisão, e ela é um ESTREITAMENTO do pedido: este gate roda
    ANTES do gate de `mode='human'`, então quem fecha a ponte no número do vendedor
    aqui é esta checagem explícita. O texto dela ("chama ele direto no contato que te
    mandei") seria absurdo na própria thread do João. É o que a Recuperação já
    garantia devolvendo None; aqui a garantia não depende de qual runner atendeu."""
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    with ExitStack() as stack:
        destinos, ponte = _montar_gate(
            stack, lead=_lead_transbordado(), channel=CANAL_JOAO,
        )
        destinos["valeria"].return_value = R.MOTIVO_HANDOFF_FORMAL
        await P.process_buffered_messages(
            FONE_REAL, TEXTO_REAL, CANAL_JOAO["id"], wamid="wamid.in",
        )

    destinos["valeria"].assert_awaited_once()
    ponte.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_conversa_da_recuperacao_nao_chega_a_ponte(monkeypatch):
    """Regressão do fluxo que JÁ está em produção: o runner dele devolve None, então o
    ramo novo não existe para ele."""
    monkeypatch.setenv("RECUPERACAO_ENABLED", "on")
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    with ExitStack() as stack:
        destinos, ponte = _montar_gate(
            stack, lead=_lead(ai_enabled=False), channel=CANAL_JOAO,
            perfil=FLUXO_RECUP, texto="Preciso repor",
        )
        destinos["recuperacao"].return_value = None
        await P.process_buffered_messages(
            FONE_REAL, "Preciso repor", CANAL_JOAO["id"], wamid="wamid.in",
        )

    destinos["recuperacao"].assert_awaited_once()
    destinos["valeria"].assert_not_awaited()
    ponte.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Defeito 1 · parte C — o CASO REAL, de ponta a ponta
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_o_lead_transbordado_que_escreve_de_novo_recebe_resposta(monkeypatch):
    """A reprodução do caso `5511950821962`, com o runner e a ponte VERDADEIROS.

    Nenhum dublê entre o inbound e a mensagem que sai: só o banco, o Redis e o
    provedor. "O kilo sai 25 reais" é pergunta de negócio
    (`_looks_like_business_question`), então o desfecho correto da escada da ponte é o
    aviso de RECEBIMENTO — que é, palavra por palavra, o texto que o lead recebia
    nessa mesma situação antes da ativação do fluxo.

    Este é o teste que a lacuna pinada em
    `test_valeria_bridge_2026_09_30.TestOQueOCarimboAindaNaoAlcanca` previa: o carimbo
    de `human_control` satisfazia o PORTÃO da ponte desde 30/09, e o que faltava era o
    CALL SITE.
    """
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    notas: list[str] = []
    provedor = AsyncMock()
    provedor.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.ponte"}]})
    lead = _lead_transbordado()

    with ExitStack() as stack:
        destinos = _patch_pipeline(
            stack, channel=CANAL_VALERIA, conversation=_conversa(), lead=lead,
            texto=TEXTO_REAL,
        )
        stack.enter_context(patch.object(
            R, "get_agent_profile", MagicMock(return_value=_perfil(FLUXO_VALERIA)),
        ))
        # O runner de verdade no lugar do dublê do pipeline (o despacho resolve o
        # runner pelo NOME no módulo, então o patch posterior vence).
        stack.enter_context(patch.object(P, "run_valeria_botoes", new=VR.processar_inbound))
        stack.enter_context(patch.object(P, "get_provider", MagicMock(return_value=provedor)))
        # Ponte de verdade: só o cooldown (Redis) é dublado.
        stack.enter_context(patch.object(
            P, "_get_buffer_redis", MagicMock(return_value=_BridgeFakeRedis()),
        ))
        # Banco e CRM do runner.
        stack.enter_context(patch.object(VR, "_reler_estado", lambda c: c.get("flow_state")))
        stack.enter_context(patch.object(VR, "get_open_deal", lambda _l: None))
        stack.enter_context(patch.object(VR, "update_conversation", MagicMock()))
        stack.enter_context(patch.object(VR, "save_message", MagicMock()))
        stack.enter_context(patch.object(
            effects, "anotar", lambda *a: notas.append(a[2]),
        ))

        await P.process_buffered_messages(
            FONE_REAL, TEXTO_REAL, CANAL_VALERIA["id"], wamid="wamid.in",
        )

    provedor.send_text.assert_awaited_once_with(FONE_REAL, P._BRIDGE_ACK_TEXT)
    assert "recebi sua mensagem" in P._BRIDGE_ACK_TEXT
    assert len(notas) == 1, "a nota do operador sumiu junto"
    destinos["llm"].assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# Defeito 2 · o nudge não reenvia a foto
# ═══════════════════════════════════════════════════════════════════════════════
class TestNudgeSemFoto:
    """A tela do nudge é texto + botões. A foto é da ENTRADA no nó, não da reoferta."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("no_id", NOS_COM_FOTO)
    async def test_nudge_manda_UMA_mensagem_sem_image_url(self, no_id, monkeypatch):
        publicadas: list[str] = []
        monkeypatch.setattr(VR, "url_publica_da_foto",
                            lambda c: publicadas.append(c) or f"https://x/{c}")
        p = ProvedorFalso()

        await VR.enviar_no(p, FONE_REAL, reg.NOS[no_id], {"preco": "R$ 28,70"},
                          corpo=reg.CORPO_NUDGE, sem_foto=True)

        assert len(p.chamadas) == 1, "o nudge virou duas mensagens"
        tipo, corpo, botoes, image_url = p.chamadas[0]
        assert tipo == "botoes"
        assert image_url is None, "a foto voltou no nudge"
        assert botoes, "o nudge tem de reoferecer os botões do nó"
        assert corpo == reg.CORPO_NUDGE
        assert publicadas == [], "a foto foi republicada no bucket por um nudge"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("no_id", NOS_COM_FOTO)
    async def test_a_entrada_normal_no_mesmo_no_continua_com_a_foto(self, no_id,
                                                                    monkeypatch):
        """O controle que impede o conserto de virar "a ValerIA perdeu a foto": é a
        mensagem de foto + preço + botões que corta 2 mensagens faturadas por lead."""
        publicadas: list[str] = []
        monkeypatch.setattr(VR, "url_publica_da_foto",
                            lambda c: publicadas.append(c) or f"https://x/{c}")
        p = ProvedorFalso()

        await VR.enviar_no(p, FONE_REAL, reg.NOS[no_id], {"preco": "R$ 28,70"})

        assert len(p.chamadas) == 1
        assert p.chamadas[0][3] == f"https://x/{reg.NOS[no_id].foto}"
        assert publicadas == [reg.NOS[no_id].foto]

    @pytest.mark.asyncio
    async def test_nudge_em_no_de_botoes_comum_continua_igual(self, monkeypatch):
        """Nó sem foto não tinha o defeito, e não pode ganhar um: a mesma chamada, com
        os mesmos argumentos, com e sem a bandeira."""
        monkeypatch.setattr(VR, "url_publica_da_foto",
                            lambda _c: pytest.fail("publicou foto em nó sem foto"))
        com_bandeira, sem_bandeira = ProvedorFalso(), ProvedorFalso()

        await VR.enviar_no(com_bandeira, FONE_REAL, reg.NOS["N1"], {},
                           corpo=reg.CORPO_NUDGE, sem_foto=True)
        await VR.enviar_no(sem_bandeira, FONE_REAL, reg.NOS["N1"], {},
                           corpo=reg.CORPO_NUDGE)

        assert com_bandeira.chamadas == sem_bandeira.chamadas
        assert com_bandeira.chamadas[0][3] is None

    @pytest.mark.asyncio
    async def test_a_lista_de_entrada_nao_e_afetada(self, monkeypatch):
        """`N0` é tela de lista: a bandeira não tem nada a suprimir ali."""
        p = ProvedorFalso()

        await VR.enviar_no(p, FONE_REAL, reg.NOS[reg.NO_ENTRADA], {},
                           corpo=reg.CORPO_NUDGE, sem_foto=True)

        assert p.chamadas[0][0] == "lista"


class TestOTurnoDoNudgeNoNoDeFoto:
    """O defeito como ele aconteceu: conversa `3c236b3c`, nó de fechamento, "Valores"."""

    @pytest.mark.asyncio
    async def test_o_lead_que_digita_no_fechamento_recebe_botoes_nao_a_foto(self, turno):
        assert await turno("Valores", no="N5") is None, "o fluxo atendeu o turno"

        assert len(turno.provedor.chamadas) == 1, "a resposta virou duas mensagens"
        tipo, corpo, _botoes, image_url = turno.provedor.chamadas[0]
        assert tipo == "botoes"
        assert image_url is None, "a imagem foi reenviada como mensagem faturada"
        assert reg.CORPO_NUDGE in corpo
        assert turno.registro["publicacoes"] == [], "republicou a foto no bucket"
        estado = turno.conversa["flow_state"]
        assert estado["node"] == "N5", "o nudge não avança o fluxo"
        assert estado["nudges"] == 1

    @pytest.mark.asyncio
    async def test_a_bolha_do_CRM_nao_mostra_uma_foto_que_o_lead_nao_recebeu(self, turno):
        """O cache de URLs (`_urls_de_foto`) sobrevive ao turno: depois de a tela do nó
        ter saído uma vez com header, um nudge no MESMO nó encontraria a URL cacheada e
        gravaria `media_url` + `message_type="image"` numa mensagem que saiu SEM
        imagem. O vendedor leria no CRM uma foto que o lead não recebeu.

        O cache é semeado à mão porque é assim que ele estaria: cheio, do turno
        anterior, por uma publicação que já aconteceu."""
        VR._urls_de_foto[reg.NOS["N5"].foto] = "https://storage.exemplo/cacheada.jpg"
        try:
            await turno("Valores", no="N5")
        finally:
            VR.limpar_cache_de_fotos()

        assert turno.registro["mensagens"], "a saída do nudge não foi persistida"
        gravada = turno.registro["mensagens"][-1]
        assert gravada["media_url"] is None
        assert gravada["message_type"] is None

    @pytest.mark.asyncio
    async def test_o_clique_que_ENTRA_no_no_de_foto_continua_com_header(self, turno):
        """Contra-prova do turno: o mesmo nó, alcançado por CLIQUE, mantém a foto."""
        await turno("Próximos 15 dias", no="N4", payload="dias15",
                    titulo="Próximos 15 dias")

        estado = turno.conversa["flow_state"]
        assert estado["node"] == "N5", "o clique não avançou para a tela de fechamento"
        assert turno.registro["publicacoes"] == [reg.NOS["N5"].foto]
        assert turno.provedor.chamadas[-1][3], "a entrada no nó perdeu o header"


class TestOCorpoDoNudge:
    @pytest.mark.asyncio
    async def test_o_default_nao_fala_mais_de_preco(self):
        """Em produção o corpo antigo respondeu a um ÁUDIO de número errado e a um
        VÍDEO: "pra eu te passar o valor certo" pressupõe uma pergunta de preço que o
        lead não fez. O nudge responde a QUALQUER coisa que não seja clique."""
        assert "valor" not in reg.CORPO_NUDGE.casefold()
        assert "preco" not in reg.CORPO_NUDGE.casefold()
        assert "pre" + chr(0x00E7) + "o" not in reg.CORPO_NUDGE.casefold()

    @pytest.mark.asyncio
    async def test_continua_editavel_na_tela_pela_chave_reservada(self, turno):
        """Reversível sem deploy: o override da chave `__nudge__` vence o default."""
        from app.button_flow import valeria_content as conteudo
        meu = "toca num dos botoes acima, por favor"
        with patch.object(conteudo, "carregar",
                          MagicMock(return_value={reg.CHAVE_NUDGE: {"corpo": meu}})):
            await turno("Valores", no="N5")

        assert meu in turno.provedor.chamadas[-1][1]
        assert reg.CORPO_NUDGE not in turno.provedor.chamadas[-1][1]


# ═══════════════════════════════════════════════════════════════════════════════
# As armadilhas que já morderam este repo
# ═══════════════════════════════════════════════════════════════════════════════
_TOCADOS = (
    "app/button_flow/valeria_runner.py",
    "app/button_flow/valeria_registry.py",
    "app/button_flow/runner.py",
    "app/buffer/processor.py",
)


@pytest.mark.parametrize("caminho", _TOCADOS)
def test_arquivo_tocado_continua_sendo_python_valido(caminho):
    """Uma quebra de linha REAL dentro de um literal já derrubou um módulo aqui."""
    fonte = Path(__file__).resolve().parent.parent / caminho
    ast.parse(fonte.read_text(encoding="utf-8"), filename=str(fonte))


@pytest.mark.parametrize("caminho", _TOCADOS)
def test_arquivo_tocado_nao_carrega_caractere_invisivel(caminho):
    """Um `\\u200e` decodificado em caractere literal já inverteu um teste em
    silêncio. O codepoint é montado com `chr()`, nunca colado."""
    fonte = (Path(__file__).resolve().parent.parent / caminho).read_text(
        encoding="utf-8")
    proibidos = {chr(0x200E), chr(0x200F), chr(0x200B), chr(0xFEFF), chr(0x00A0)}
    achados = sorted({hex(ord(c)) for c in fonte if c in proibidos})
    assert achados == [], f"{caminho} carrega invisível: {achados}"


def test_o_processor_nao_recopia_a_frase_do_motivo():
    """A trava ESTRUTURAL da constante, porque a comportamental é impossível: uma
    segunda cópia byte-idêntica da frase no processor passaria em todos os testes de
    comportamento deste arquivo — e é exatamente isso que a torna perigosa. Ela só
    divergiria no dia em que alguém reescrevesse a prosa de UM dos dois lados, e aí o
    gate pararia de casar em silêncio, devolvendo o lead ao vácuo que este conserto
    fechou. É a classe de bug que `campaigns/node_registry.py` documenta, e aqui o
    detector é o próprio texto-fonte.

    A frase pode aparecer na prosa de um comentário (ela aparece: a docstring da ponte
    descreve "handoff formal"); o que não pode é a STRING INTEIRA, que é o que seria
    comparado."""
    fonte = (Path(__file__).resolve().parent.parent / "app/buffer/processor.py").read_text(
        encoding="utf-8")
    assert "MOTIVO_HANDOFF_FORMAL" in fonte, "o gate deixou de usar a constante"
    assert R.MOTIVO_HANDOFF_FORMAL not in fonte, "a frase foi recopiada no consumidor"


def test_os_acentos_dos_textos_tocados_atravessaram_intactos():
    """Acento virando '?' é modo de falha recorrente neste repo. Os dois textos que
    esta tarefa escreve ou compara: o corpo novo do nudge (que o LEAD lê) e o motivo
    do handoff (que o OPERADOR lê na nota e o gate compara)."""
    assert reg.CORPO_NUDGE.startswith("pra seguir, " + chr(0x00E9) + " s" + chr(0x00F3))
    assert "op" + chr(0x00E7) + chr(0x00F5) + "es" in reg.CORPO_NUDGE
    assert chr(0x1F447) in reg.CORPO_NUDGE, "a mãozinha do nudge sumiu"
    assert "j" + chr(0x00E1) + " registrado" in R.MOTIVO_HANDOFF_FORMAL
    assert "?" not in reg.CORPO_NUDGE
