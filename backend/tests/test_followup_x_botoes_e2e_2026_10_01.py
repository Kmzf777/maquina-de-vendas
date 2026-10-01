"""Follow-up x fluxo de botões, ponta a ponta: a ORDEM entre os dois motores.

Os testes unitários (`tests/test_followup_x_botoes_2026_10_01.py`) provam
`_lead_stop_reason` e `_stop_reason_applies` isolados, cada um chamado à mão com os
dicts já montados. O que eles NÃO provam é a ordem: que um lead que de fato andou
pela árvore de botões — pelo runner REAL, com estado gravado turno a turno — chega
ao `process_due_followups` REAL e é suprimido lá, antes de qualquer despacho, sem
chamada de LLM e sem envio de provedor. Uma troca de posição do backstop (depois do
despacho, ou depois do guard de canal humano) passa em silêncio por todos os testes
unitários e é exatamente o defeito que este arquivo existe para pegar.

── Onde cada dublê entra, e por quê ─────────────────────────────────────────
SUPABASE DO AGENDADOR: dublado em UM seam só, `scheduler.get_supabase` (classe
`BancoFalso`). É o estreitamento por onde passa TODO acesso a banco do tick —
reivindicação, releitura do lead no backstop, cancelamento, `_mark_sent`, wamid,
crash-recovery, histórico. Dublar aqui deixa REAIS `process_due_followups`,
`_claim_followup_job`, `_cancel_job`, `_mark_sent`, `_fetch_lead_for_backstop`,
`_lead_stop_reason` e `_stop_reason_applies` — ou seja, deixa real tudo que decide
a ORDEM, que é o objeto do teste. Dublar `_cancel_job` em vez do banco seria mais
estreito em linhas e mais fraco em conteúdo: as asserções passam a ser o UPDATE que
o agendador de fato escreveu em `follow_up_jobs` (`status`/`cancel_reason`), não "a
função que eu mesmo dublei foi chamada".
  O dublê PROJETA as colunas do `select` (`_projetar`): `_fetch_lead_for_backstop`
pede `id, phone, stage, opt_out, ai_enabled, metadata` e NÃO traz `human_control`,
então o backstop tem de decidir sem ela aqui também. E qualquer método do PostgREST
que o dublê não modela levanta (`_Consulta.__getattr__`) — um dublê que devolvesse
MagicMock para tudo deixaria uma consulta nova passar em silêncio.

`get_due_followups` é dublado à parte (a task pede, e é o único jeito de dirigir o
tick sem reimplementar o embed `agent_profiles(kind, flow_id)` do PostgREST). Os
dicts `channels`/`conversations`/`leads` de cada job trazem EXATAMENTE as colunas
que aquele select pede — nem uma a mais — para o teste não passar por causa de um
campo que a produção não entrega.

CRM DO FLUXO DE BOTÕES: molde de `tests/test_valeria_runner_2026_09_29.py` (folhas
de CRM dubladas, motor e runner reais). Com uma diferença deliberada: `effects` fica
REAL e o que se dubla são as folhas dele (`update_lead`, `add_tags_to_lead`,
`save_message`, `append_lead_observation`, `get_open_deal`). Assim o `ai_enabled=False`
+ `human_control=True` do cenário 2 é RESULTADO do handoff real do fluxo, escrito
pelo `effects._aplicar_handoff` de verdade na linha do lead que o backstop vai reler
— não um campo que o teste preencheu à mão.

── Os espiões, e o limite deles ─────────────────────────────────────────────
Chamada real de LLM (`agent.gemini_client.generate`, `button_flow.classifier.
classificar`) e request HTTP real (`httpx.AsyncClient.send`, o funil por onde
`post`/`request` passam) são espiões que GRAVAM e LEVANTAM.
  Levantar é necessário mas NÃO é suficiente, e isso precisa estar escrito: os
handlers do agendador engolem exceção por desenho (`_process_ai_reengage` tem
`except Exception` em volta de `run_agent` e de cada `send_text`; o caminho
`standard` tem um em volta de `_generate_followup_message`). Um `AssertionError`
levantado lá dentro seria logado e o job apenas ficaria sem desfecho. Por isso cada
cenário também afirma que as listas dos espiões estão VAZIAS e que o job tem o
desfecho esperado — a asserção de lista vazia é o que fica vermelho; o `raise` é a
rede para um caminho que este arquivo não modelou.
  `run_agent` é GRAVADOR e não levantador, porque o cenário 4 exige que ele rode. Os
outros quatro cenários afirmam `tick.agente == []`.

Dados 100% fictícios — ids `*-ficticio-*` e telefones `550000000000x`. O número de
teste real do repo (`reference_numero_teste_whatsapp`) não aparece aqui de propósito:
nada neste arquivo toca rede, e um número real num fixture convida a cópia para um
script que toca.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.button_flow import effects, valeria_content
from app.button_flow import runner as R
from app.button_flow import valeria_registry as reg
from app.button_flow import valeria_runner as VR
from app.follow_up import scheduler as S

# ── Relógio e identidades fictícias ─────────────────────────────────────────
AGORA = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
RECENTE = (AGORA - timedelta(hours=2)).isoformat()

FLUXO = reg.FLOW_ID
PERFIL_BOTOES = "perfil-ficticio-botoes"
PERFIL_LLM = "perfil-ficticio-llm"

LEAD_FLUXO = "lead-ficticio-fluxo"
LEAD_LP = "lead-ficticio-lp"
LEAD_LLM = "lead-ficticio-llm"

TELEFONE_FLUXO = "5500000000000"
TELEFONE_LP = "5500000000001"
TELEFONE_LLM = "5500000000002"

CONV_FLUXO = "conversa-ficticia-fluxo"
CONV_LP = "conversa-ficticia-lp"
CONV_LLM = "conversa-ficticia-llm"

CANAL_ID = "canal-ficticio-valeria"
CANAL_JOAO_ID = "canal-ficticio-joao"
PHONE_NUMBER_ID_JOAO = "0000000000"

# O canal como o `select` de `get_due_followups` o entrega: id, name, provider,
# provider_config, mode, agent_profile_id e o perfil EMBUTIDO. Nada além disso —
# `phone`, por exemplo, não vem, e um teste que dependesse dele passaria mentindo.
# Espelha a produção de 01/10/2026: quem aponta para o perfil de botões é o CANAL.
CANAL_DO_JOB = {
    "id": CANAL_ID,
    "name": "ValerIA (ficticio)",
    "provider": "meta_cloud",
    "provider_config": {"phone_number_id": "1111111111", "access_token": "token-ficticio"},
    "mode": "ai",
    "agent_profile_id": PERFIL_BOTOES,
    "agent_profiles": {"kind": "button_flow", "flow_id": FLUXO},
}

# O canal como o inbound o lê (`get_channel_by_id`, `select *`): tem `phone`, que é
# o que `_cartao_do_terminal` compara para decidir se manda o cartão do vendedor.
CANAL_DO_FLUXO = {
    **CANAL_DO_JOB,
    "phone": "5500000000099",
}

CANAL_DO_JOAO = {
    "id": CANAL_JOAO_ID,
    "name": "Joao (ficticio)",
    "provider": "meta_cloud",
    "mode": "human",
    "provider_config": {"phone_number_id": PHONE_NUMBER_ID_JOAO, "access_token": "token-ficticio"},
}


# ── O dublê do Supabase do agendador ────────────────────────────────────────
class _Resposta:
    def __init__(self, data):
        self.data = data


class _Consulta:
    """Um encadeamento do PostgREST, gravado inteiro.

    Elo que o dublê não conhece levanta (`__getattr__`), de propósito: um dublê
    permissivo deixaria uma consulta NOVA do agendador passar em silêncio e o teste
    afirmaria sobre um caminho que não rodou.
    """

    _ELOS_NEUTROS = frozenset({
        "order", "limit", "range", "neq", "gt", "gte", "lt", "lte", "in_", "is_",
        "not_", "filter", "like", "ilike", "maybe_single",
    })

    def __init__(self, banco, tabela):
        self._banco = banco
        self.tabela = tabela
        self.op = None
        self.colunas = "*"
        self.payload = None
        self.filtros = []
        self.elos = []
        self.unico = False

    def select(self, colunas="*", *_a, **_k):
        self.op = "select"
        self.colunas = colunas
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, campo, valor):
        self.filtros.append((campo, valor))
        return self

    def single(self):
        self.unico = True
        return self

    def execute(self):
        return self._banco.responder(self)

    def __getattr__(self, nome):
        if nome in self._ELOS_NEUTROS:
            def _elo(*a, **_k):
                self.elos.append((nome, a))
                return self
            return _elo
        raise AttributeError(
            f"o dublê do Supabase não modela .{nome}() — a tabela "
            f"{getattr(self, 'tabela', '?')!r} ganhou uma consulta nova no agendador"
        )


def _projetar(linha: dict, colunas: str) -> dict:
    """A linha reduzida às colunas do `select`, como o PostgREST devolveria.

    Projetar importa: `_fetch_lead_for_backstop` não traz `human_control`, e um
    dublê que devolvesse a linha inteira deixaria o backstop decidir com uma coluna
    que a produção não lhe entrega.
    """
    colunas = (colunas or "*").strip()
    if colunas == "*":
        return dict(linha)
    return {c.strip(): linha.get(c.strip()) for c in colunas.split(",") if c.strip()}


class BancoFalso:
    """`scheduler.get_supabase` — o seam único do banco no tick. Ver o docstring."""

    def __init__(self):
        self.leads: dict[str, dict] = {}
        self.mensagens: dict[str, list[dict]] = {}
        self.conversas_por_canal: dict[tuple[str, str], list[dict]] = {}
        # (tabela, payload, filtros) de todo UPDATE — é a prova do desfecho do job.
        self.escritas: list[tuple[str, dict, list]] = []

    def table(self, nome):
        return _Consulta(self, nome)

    def responder(self, q: _Consulta):
        if q.op == "update":
            self.escritas.append((q.tabela, dict(q.payload), list(q.filtros)))
            # O UPDATE guardado por `id` afeta a linha (é o que faz
            # `_claim_followup_job` vencer a corrida); o da crash-recovery, que
            # filtra por status/env, não afeta nenhuma linha neste banco.
            ids = [valor for campo, valor in q.filtros if campo == "id"]
            return _Resposta([{"id": i} for i in ids])
        if q.op != "select":
            raise AssertionError(f"operação não modelada: {q.op!r} em {q.tabela!r}")
        if q.tabela == "leads":
            lead_id = self._filtro(q, "id")
            linha = self.leads.get(lead_id)
            if linha is None:
                raise AssertionError(
                    f"lead {lead_id!r} não registrado no BancoFalso — o cenário leu "
                    f"um lead que não existe"
                )
            projetada = _projetar(linha, q.colunas)
            return _Resposta(projetada if q.unico else [projetada])
        if q.tabela == "messages":
            conv = self._filtro(q, "conversation_id")
            linhas = [_projetar(m, q.colunas) for m in self.mensagens.get(conv, [])]
            return _Resposta(linhas)
        if q.tabela == "conversations":
            chave = (self._filtro(q, "lead_id"), self._filtro(q, "channel_id"))
            return _Resposta(list(self.conversas_por_canal.get(chave, [])))
        raise AssertionError(f"consulta não modelada: select em {q.tabela!r}")

    @staticmethod
    def _filtro(q: _Consulta, campo: str):
        for nome, valor in q.filtros:
            if nome == campo:
                return valor
        raise AssertionError(
            f"select em {q.tabela!r} sem .eq({campo!r}) — o dublê não modela esta forma"
        )


# ── O dublê do provedor de WhatsApp ─────────────────────────────────────────
class ProvedorFalso:
    """Grava o que seria enviado. Nunca fala com a Meta.

    Mesmos métodos que `tests/test_valeria_runner_2026_09_29.py` dubla, mais
    `send_contact` (o cartão do vendedor no handoff) e `send_template` (o resgate e
    a boas-vindas de LP, que constroem `MetaCloudClient` direto).
    """

    def __init__(self, nome: str):
        self.nome = nome
        self.envios: list[tuple] = []

    def _wamid(self) -> dict:
        return {"messages": [{"id": f"wamid.{self.nome}.{len(self.envios)}"}]}

    async def send_interactive_list(self, to, body, button, rows, header=None):
        self.envios.append(("lista", to, body))
        return self._wamid()

    async def send_interactive_buttons(self, to, body, buttons, image_url=None):
        self.envios.append(("botoes", to, body))
        return self._wamid()

    async def send_text(self, to, text):
        self.envios.append(("texto", to, text))
        return self._wamid()

    async def send_contact(self, to, contact_name, contact_phone):
        self.envios.append(("cartao", to, contact_name))
        return self._wamid()

    async def send_template(self, to, template_name, components=None, language_code="pt_BR"):
        self.envios.append(("template", to, template_name))
        return self._wamid()


# ── Montagem dos jobs, nas colunas exatas do select ─────────────────────────
def _job(job_id: str, job_type: str, *, lead_id: str, phone: str, nome: str,
         conversation_id: str, perfil_da_conversa: str | None,
         ultima_do_cliente: str | None = RECENTE,
         canal: dict | None = None, metadata: dict | None = None) -> dict:
    return {
        "id": job_id,
        "job_type": job_type,
        "lead_id": lead_id,
        "conversation_id": conversation_id,
        "sequence": 1,
        "status": "pending",
        "created_at": (AGORA - timedelta(minutes=30)).isoformat(),
        "metadata": metadata or {},
        "leads": {
            "id": lead_id, "phone": phone, "name": nome,
            "last_customer_message_at": ultima_do_cliente, "wa_id": phone,
        },
        "channels": dict(canal or CANAL_DO_JOB),
        "conversations": {
            "id": conversation_id, "stage": "atacado", "followup_enabled": True,
            "last_customer_message_at": ultima_do_cliente,
            "agent_profile_id": perfil_da_conversa,
        },
    }


def _linha_de_lead(lead_id: str, phone: str, nome: str, **extra) -> dict:
    linha = {
        "id": lead_id, "phone": phone, "name": nome, "wa_id": phone,
        "stage": "atacado", "opt_out": False, "ai_enabled": True,
        "human_control": False, "metadata": {},
        "last_customer_message_at": RECENTE,
    }
    linha.update(extra)
    return linha


# ── Ambiente ────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    """Nenhum fluxo de botões ligado, e nenhum perfil em cache.

    `app/config.py` carrega `.env.local` em `os.environ` no import, então um
    `VALERIA_BOTOES_ENABLED` da máquina do dev vazaria para a suíte. O cache de
    perfis é limpo nas DUAS pontas: um perfil cacheado por outro teste faria o
    cenário 5 (nenhuma consulta a `agent_profiles`) passar pelo motivo errado.
    """
    monkeypatch.delenv("VALERIA_BOTOES_ENABLED", raising=False)
    monkeypatch.delenv("RECUPERACAO_ENABLED", raising=False)
    R.limpar_cache_de_perfis()
    yield
    R.limpar_cache_de_perfis()


class _Tick:
    """O tick do follow-up, dirigido pelo `process_due_followups` REAL."""

    def __init__(self, banco, provedor, metas, agente, llm, rede, rodar):
        self.banco = banco
        self.provedor = provedor
        self.metas = metas
        self.agente = agente
        self.llm = llm
        self.rede = rede
        self.rodar = rodar

    def desfechos(self, job_id: str) -> list[dict]:
        """Os UPDATEs TERMINAIS que o agendador escreveu para este job.

        Reivindicação (`processing`) fica fora de propósito: ela não é desfecho, e
        acontece em todo job.
        """
        return [
            payload
            for tabela, payload, filtros in self.banco.escritas
            if tabela == "follow_up_jobs"
            and ("id", job_id) in filtros
            and payload.get("status") in ("cancelled", "sent")
        ]

    def sem_llm_e_sem_envio(self):
        """O par de asserções que todo cenário de SUPRESSÃO precisa fazer."""
        assert self.agente == [], "o agente (LLM) foi chamado por cima do fluxo de botões"
        assert self.llm == [], "houve chamada de LLM crua no tick"
        assert self.rede == [], "houve request HTTP real no tick"
        assert self.provedor.envios == [], "o follow-up enviou mensagem"
        assert self.metas == [], "o cliente da Meta foi construído"


@pytest.fixture
def tick(monkeypatch):
    banco = BancoFalso()
    provedor = ProvedorFalso("followup")
    metas: list[dict] = []
    agente: list[dict] = []
    llm: list[tuple] = []
    rede: list[tuple] = []
    fila: list[dict] = []

    monkeypatch.setattr(S, "get_supabase", lambda: banco)
    monkeypatch.setattr(S, "get_due_followups", lambda _now, limit=10: list(fila))
    monkeypatch.setattr(S, "is_lead_blacklisted", lambda _lead_id: False)
    monkeypatch.setattr(S, "get_provider", lambda _canal: provedor)

    def _meta_cloud(provider_config):
        metas.append(dict(provider_config or {}))
        return provedor
    monkeypatch.setattr(S, "MetaCloudClient", _meta_cloud)

    monkeypatch.setattr(S, "get_channel_by_provider_config",
                        lambda *_a, **_k: dict(CANAL_DO_JOAO))
    monkeypatch.setattr(S, "get_or_create_conversation",
                        lambda *_a, **_k: {"id": "conversa-ficticia-joao"})
    monkeypatch.setattr(S, "save_message_conv", lambda *_a, **_k: None)
    monkeypatch.setattr(S, "create_deal", lambda *_a, **_k: None)
    monkeypatch.setattr(S, "record_dispatch_note", lambda *_a, **_k: None)

    # Espiões que GRAVAM e LEVANTAM. Ver o limite deles no docstring do módulo.
    def _llm_proibido(*a, **k):
        llm.append((a, k))
        raise AssertionError("chamada REAL de LLM dentro do tick")
    monkeypatch.setattr(S, "generate", _llm_proibido)
    monkeypatch.setattr("app.agent.gemini_client.generate", _llm_proibido)
    monkeypatch.setattr("app.button_flow.classifier.classificar", _llm_proibido)

    async def _rede_proibida(*a, **k):
        rede.append((a, k))
        raise AssertionError("request HTTP real dentro do tick")
    monkeypatch.setattr(httpx.AsyncClient, "send", _rede_proibida)

    # GRAVADOR, não levantador: o cenário 4 exige que o agente rode.
    async def _run_agent(conversation, texto, **kw):
        agente.append({"conversa": (conversation or {}).get("id"), "texto": texto,
                       "perfil": kw.get("agent_profile_id")})
        return "dublê do agente: resposta livre"
    monkeypatch.setattr("app.agent.orchestrator.run_agent", _run_agent)

    async def _rodar(jobs: list[dict]):
        fila[:] = jobs
        await S.process_due_followups(now=AGORA)

    return _Tick(banco, provedor, metas, agente, llm, rede, _rodar)


@pytest.fixture
def botoes_ligado(monkeypatch):
    """Kill switch da ValerIA de botões ligado, com `agent_profiles` espionado.

    Devolve a lista de ids consultados: é ela que o cenário 5 afirma vazia.
    """
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    consultados: list[str] = []

    def _perfil(profile_id):
        consultados.append(profile_id)
        if profile_id == PERFIL_BOTOES:
            return {"id": PERFIL_BOTOES, "kind": "button_flow", "flow_id": FLUXO}
        return {"id": profile_id, "kind": "llm", "flow_id": None}
    monkeypatch.setattr(R, "get_agent_profile", _perfil)
    R.limpar_cache_de_perfis()
    return consultados


class _Fluxo:
    def __init__(self, rodar, provedor, conversa, lead, registro):
        self.turno = rodar
        self.provedor = provedor
        self.conversa = conversa
        self.lead = lead
        self.registro = registro


@pytest.fixture
def fluxo(monkeypatch, tick, botoes_ligado):
    """A ValerIA de botões pelo runner REAL, com as folhas de CRM dubladas.

    `effects` fica real (ver docstring do módulo): `update_lead` escreve na linha
    do lead do `BancoFalso`, que é a MESMA linha que o backstop do follow-up vai
    reler. É o acoplamento de produção, não uma encenação.
    """
    tick.banco.leads[LEAD_FLUXO] = _linha_de_lead(
        LEAD_FLUXO, TELEFONE_FLUXO, "Fulano Ficticio")
    # A cópia em memória que o inbound passaria ao runner. `effects` grava nas
    # COLUNAS (via `update_lead`) e não neste dict — como em produção.
    lead = dict(tick.banco.leads[LEAD_FLUXO])
    conversa = {
        "id": CONV_FLUXO, "lead_id": LEAD_FLUXO, "channel_id": CANAL_ID,
        "stage": "atacado", "status": "active", "followup_enabled": True,
        "agent_profile_id": None, "flow_state": None,
    }
    registro = {"mensagens": [], "score": [], "tags": [], "notas": [], "sistema": []}
    provedor = ProvedorFalso("fluxo")

    def _update_lead(lead_id, **colunas):
        tick.banco.leads[lead_id].update(colunas)

    monkeypatch.setattr(VR, "_reler_estado", lambda c: c.get("flow_state"))
    # `_historico` é fail-soft mas iria ao Supabase real (host de teste → DNS a
    # cada turno). O detector de autoresponder segue REAL, decidindo sobre [].
    monkeypatch.setattr(VR, "_historico", lambda _conv_id: [])
    monkeypatch.setattr(VR, "get_open_deal", lambda _lead_id: None)
    monkeypatch.setattr(
        VR, "update_conversation",
        lambda conv_id, **kw: conversa.update(flow_state=kw["flow_state"]))
    monkeypatch.setattr(
        VR, "save_message",
        lambda *a, **k: registro["mensagens"].append(a[3] if len(a) > 3 else a))
    monkeypatch.setattr(VR, "url_publica_da_foto", lambda _caminho: None)
    monkeypatch.setattr(VR, "preco_do_no", lambda _no: "R$ 28,70")
    monkeypatch.setattr(VR, "save_score_evidence",
                        lambda **kw: registro["score"].append(kw))
    monkeypatch.setattr(valeria_content, "carregar", lambda _flow: {})
    monkeypatch.setattr(R, "is_lead_blacklisted", lambda _lead_id: False)

    monkeypatch.setattr(effects, "update_lead", _update_lead)
    monkeypatch.setattr(effects, "add_tags_to_lead",
                        lambda _lead_id, tags: registro["tags"].extend(tags))
    monkeypatch.setattr(effects, "save_message",
                        lambda *a, **k: registro["sistema"].append(a[2]))
    monkeypatch.setattr(effects, "append_lead_observation",
                        lambda _lead_id, texto: registro["notas"].append(texto))
    monkeypatch.setattr(effects, "get_open_deal", lambda _lead_id: None)

    async def _turno(texto, *, payload=None, titulo=""):
        meta = {"payload": payload, "title": titulo} if payload else None
        await VR.processar_inbound(
            lead=lead, conversation=conversa, channel=CANAL_DO_FLUXO,
            provider=provedor, texto=texto, metadata=meta,
            wamid=f"wamid.in.{len(provedor.envios)}",
        )
        return conversa["flow_state"]

    return _Fluxo(_turno, provedor, conversa, lead, registro)


async def _andar_ate_o_handoff(fluxo) -> dict:
    """N0 -> negocio -> cafeteria -> ate30 -> trocar -> dias15 -> sim -> T_HANDOFF.

    A caminhada é a declarada em `valeria_registry.NOS`: cada passo é o `id` do
    botão que a Meta devolveria no webhook, não um nó escrito à mão.
    """
    await fluxo.turno("oi, queria comprar café")
    passos = (
        ("negocio", "Pro meu negócio"), ("cafeteria", "Cafeteria"),
        ("ate30", "Até 30 kg por mês"), ("trocar", "Quero trocar"),
        ("dias15", "Próximos 15 dias"), ("sim", "Sim, quero falar"),
    )
    estado = None
    for payload, titulo in passos:
        estado = await fluxo.turno(titulo, payload=payload, titulo=titulo)
    return estado


# ── Cenário 1 · o bug, fechado ──────────────────────────────────────────────
async def test_1_lead_parado_no_meio_do_fluxo_nao_recebe_reengage_de_llm(fluxo, tick):
    """O bug inteiro, pelos dois motores reais.

    PROVA: um lead que andou pelo runner real (tela de entrada, toque em "negocio",
    tela N1) e parou é SUPRIMIDO no `process_due_followups` real, com
    `cancel_reason="fluxo_de_botoes"`, zero chamada de agente/LLM e zero envio — e a
    supressão NÃO vem de `ai_enabled`, que segue True na coluna, que é exatamente a
    premissa do bug.

    NÃO PROVA: que o inbound do lead seria roteado para o fluxo (isso é o gate de
    `buffer/processor.py`, coberto em test_valeria_processor_2026_09_30.py), nem o
    nudge que a resposta ao reengage produziria — aqui o reengage nunca sai.
    """
    estado = await fluxo.turno("oi, queria comprar café")
    assert fluxo.provedor.envios[0][0] == "lista", "não recebeu a tela de entrada"
    assert estado["node"] == reg.NO_ENTRADA

    estado = await fluxo.turno("Pro meu negócio", payload="negocio",
                               titulo="Pro meu negócio")
    assert estado["node"] == "N1", "o toque em negocio não avançou para N1"
    assert fluxo.provedor.envios[-1][0] == "botoes", "N1 não saiu como tela de botões"
    envios_do_fluxo = len(fluxo.provedor.envios)

    # E para aqui. Nada o silenciou: é o estado que fazia o `ai_reengage` disparar.
    assert tick.banco.leads[LEAD_FLUXO]["ai_enabled"] is True
    assert tick.banco.leads[LEAD_FLUXO]["opt_out"] is False

    job = _job("job-ficticio-1", "ai_reengage", lead_id=LEAD_FLUXO,
               phone=TELEFONE_FLUXO, nome="Fulano Ficticio",
               conversation_id=CONV_FLUXO, perfil_da_conversa=None)
    tick.banco.mensagens[CONV_FLUXO] = [{"content": "e quanto sai o quilo?",
                                         "role": "user"}]
    await tick.rodar([job])

    assert tick.desfechos("job-ficticio-1") == [
        {"status": "cancelled", "cancel_reason": "fluxo_de_botoes"}
    ]
    tick.sem_llm_e_sem_envio()
    assert len(fluxo.provedor.envios) == envios_do_fluxo, (
        "o tick do follow-up enviou pelo provedor do fluxo")
    assert tick.banco.leads[LEAD_FLUXO]["ai_enabled"] is True, (
        "a supressão veio de ai_disabled, não do fluxo de botões")


# ── Cenário 2 · o anteparo sobrevive ────────────────────────────────────────
async def test_2_handoff_rescue_dispara_para_lead_que_o_fluxo_acabou_de_entregar(
        fluxo, tick):
    """O anteparo do caso Wilson Demuth (>21h no vácuo, scheduler.py:1004).

    PROVA: o lead chega a `T_HANDOFF` pelo runner real; o handoff real de `effects`
    grava `ai_enabled=False` + `human_control=True` na coluna; o backstop do
    follow-up resolve o motivo `fluxo_de_botoes` para esse mesmo lead — e o
    `handoff_rescue` DISPARA de todo jeito (isenção), notificando o vendedor por
    TEMPLATE, sem agente e sem LLM.

    NÃO PROVA: a entrega do template pela Meta, nem a janela de `_rescue_contact_cutoff`
    (este lead não tem conversa no canal do João, que é o caminho em que o resgate é
    necessário). O motivo é afirmado chamando o `_lead_stop_reason` real sobre o que o
    `_fetch_lead_for_backstop` real leu — não sobre dicts montados à mão.
    """
    estado = await _andar_ate_o_handoff(fluxo)
    assert estado["node"] == "T_HANDOFF", "a caminhada não chegou ao handoff"
    assert reg.TAG_QUALIFICADO in fluxo.registro["tags"]
    linha = tick.banco.leads[LEAD_FLUXO]
    assert linha["ai_enabled"] is False, "o handoff real não desligou a IA"
    assert linha["human_control"] is True, "o handoff real não carimbou o controle humano"

    job = _job("job-ficticio-2", "handoff_rescue", lead_id=LEAD_FLUXO,
               phone=TELEFONE_FLUXO, nome="Fulano Ficticio",
               conversation_id=CONV_FLUXO, perfil_da_conversa=None,
               metadata={"lead_phone": TELEFONE_FLUXO,
                         "joao_phone_number_id": PHONE_NUMBER_ID_JOAO,
                         "lead_name": "Fulano Ficticio"})

    # O motivo É `fluxo_de_botoes` (e não `ai_disabled`): é a isenção que deixa o
    # job passar, não a ausência de motivo.
    assert S._lead_stop_reason(
        S._fetch_lead_for_backstop(LEAD_FLUXO),
        job["conversations"], job["channels"],
    ) == "fluxo_de_botoes"

    await tick.rodar([job])

    desfechos = tick.desfechos("job-ficticio-2")
    assert len(desfechos) == 1 and desfechos[0]["status"] == "sent", (
        f"o resgate não foi concluído: {desfechos}")
    assert ("template", TELEFONE_FLUXO, S.JOAO_TEMPLATE_NAME) in tick.provedor.envios
    assert tick.metas == [CANAL_DO_JOAO["provider_config"]], (
        "o template não saiu pelo canal do João")
    assert tick.agente == [], "o resgate chamou o agente"
    assert tick.llm == [] and tick.rede == []


# ── Cenário 3 · a boas-vindas de landing page sobrevive ─────────────────────
async def test_3_lp_welcome_dispara_para_lead_que_nunca_mandou_mensagem(
        tick, botoes_ligado):
    """Bloquear `lp_welcome` faria NENHUM lead de LP ser recebido.

    PROVA: um lead de LP no MESMO canal de botões, sem nenhuma mensagem, resolve para
    o motivo `fluxo_de_botoes` e ainda assim recebe a boas-vindas — por template, sem
    agente e sem LLM.

    NÃO PROVA: o cadastro do card (create_deal é dublado) nem a entrega pela Meta.
    """
    tick.banco.leads[LEAD_LP] = _linha_de_lead(
        LEAD_LP, TELEFONE_LP, "Fulana Ficticia", last_customer_message_at=None)
    job = _job("job-ficticio-3", "lp_welcome", lead_id=LEAD_LP, phone=TELEFONE_LP,
               nome="Fulana Ficticia", conversation_id=CONV_LP,
               perfil_da_conversa=None, ultima_do_cliente=None,
               metadata={"lead_phone": TELEFONE_LP,
                         "template_name": "lp_solicitacao_recebida",
                         "lead_name": "Fulana Ficticia", "origem": "atacado"})

    assert S._lead_stop_reason(
        S._fetch_lead_for_backstop(LEAD_LP),
        job["conversations"], job["channels"],
    ) == "fluxo_de_botoes", "o cenário não está no canal de botões — a isenção não é exercida"

    await tick.rodar([job])

    desfechos = tick.desfechos("job-ficticio-3")
    assert len(desfechos) == 1 and desfechos[0]["status"] == "sent", (
        f"a boas-vindas de LP não foi concluída: {desfechos}")
    assert ("template", TELEFONE_LP, "lp_solicitacao_recebida") in tick.provedor.envios
    assert tick.agente == [], "a boas-vindas chamou o agente"
    assert tick.llm == [] and tick.rede == []


# ── Cenário 3b · a ORDEM contra a blacklist, ponta a ponta ──────────────────
# ACRÉSCIMO aos cinco cenários pedidos, e o motivo é uma mutação: pôr o
# `fluxo_de_botoes` ANTES de `is_lead_blacklisted` (a ordem que a spec desta task
# pedia) deixa os cinco VERDES. Quem pega isso é `test_blacklist_vence_fluxo_de_botoes`
# no arquivo unitário, que afirma o motivo — mas não afirma o DANO: que a boas-vindas
# isenta de fato não sai para quem está na Blacklist. O dano só é observável aqui, no
# tick inteiro, e é exatamente o defeito que o comentário do fix descreve.
async def test_3b_lead_na_blacklist_nao_recebe_a_boas_vindas_isenta(
        tick, botoes_ligado, monkeypatch):
    """`blacklisted` não tem isenção nenhuma — nem a do `lp_welcome`.

    PROVA: o MESMO job do cenário 3, com o lead na Blacklist, é cancelado como
    `blacklisted` e NENHUM template sai. É a ordem (blacklist antes do fluxo) sendo
    verificada pelo efeito, não pelo rótulo.

    NÃO PROVA: a resolução da Blacklist em si (`is_lead_blacklisted` é dublado) — o
    que se prova é o que o agendador faz com a resposta dela.
    """
    monkeypatch.setattr(S, "is_lead_blacklisted", lambda _lead_id: True)
    tick.banco.leads[LEAD_LP] = _linha_de_lead(
        LEAD_LP, TELEFONE_LP, "Fulana Ficticia", last_customer_message_at=None)
    job = _job("job-ficticio-3b", "lp_welcome", lead_id=LEAD_LP, phone=TELEFONE_LP,
               nome="Fulana Ficticia", conversation_id=CONV_LP,
               perfil_da_conversa=None, ultima_do_cliente=None,
               metadata={"lead_phone": TELEFONE_LP,
                         "template_name": "lp_solicitacao_recebida",
                         "lead_name": "Fulana Ficticia", "origem": "atacado"})

    await tick.rodar([job])

    assert tick.desfechos("job-ficticio-3b") == [
        {"status": "cancelled", "cancel_reason": "blacklisted"}
    ]
    tick.sem_llm_e_sem_envio()


# ── Cenário 4 · a conversa vence o canal ────────────────────────────────────
async def test_4_conversa_apontada_para_a_llm_no_canal_de_botoes_segue_recebendo(
        tick, botoes_ligado):
    """O lead que um disparo atribuiu DELIBERADAMENTE à LLM.

    PROVA: no mesmo canal de botões, uma conversa cujo `agent_profile_id` aponta para
    um perfil `kind='llm'` não é suprimida — o `ai_reengage` roda o agente e envia.
    A precedência da conversa sobre o canal é exercida pelo caminho real
    (`runner.fluxo_da_conversa` consultando `agent_profiles` pelo id da conversa).

    NÃO PROVA: o conteúdo que a Valéria escreveria (run_agent é dublado) — prova que
    ele FOI chamado, com o perfil outbound, e que a mensagem saiu pelo provedor.
    """
    tick.banco.leads[LEAD_LLM] = _linha_de_lead(LEAD_LLM, TELEFONE_LLM, "Siclano Ficticio")
    tick.banco.mensagens[CONV_LLM] = [{"content": "ainda tá de pé aquele orçamento?",
                                       "role": "user"}]
    job = _job("job-ficticio-4", "ai_reengage", lead_id=LEAD_LLM, phone=TELEFONE_LLM,
               nome="Siclano Ficticio", conversation_id=CONV_LLM,
               perfil_da_conversa=PERFIL_LLM)

    assert S._lead_stop_reason(
        S._fetch_lead_for_backstop(LEAD_LLM),
        job["conversations"], job["channels"],
    ) is None, "a conversa de LLM foi tratada como fluxo de botões"

    await tick.rodar([job])

    desfechos = tick.desfechos("job-ficticio-4")
    assert len(desfechos) == 1 and desfechos[0]["status"] == "sent", (
        f"o reengage da conversa de LLM não foi concluído: {desfechos}")
    assert [c["cancel_reason"] for c in desfechos if "cancel_reason" in c] == []
    assert len(tick.agente) == 1, "o agente não foi chamado"
    assert tick.agente[0]["perfil"] == S.AI_REENGAGE_PROFILE_ID
    assert [e for e in tick.provedor.envios if e[0] == "texto"], "nada foi enviado"
    # A precedência custou UMA leitura de perfil, a da conversa — não a do canal.
    assert botoes_ligado == [PERFIL_LLM]
    assert tick.llm == [] and tick.rede == []


# ── Cenário 5 · o estado de hoje em produção ────────────────────────────────
async def test_5_com_o_kill_switch_ausente_tudo_dispara_e_agent_profiles_nao_e_lido(
        tick, monkeypatch):
    """Sem `VALERIA_BOTOES_ENABLED` no ambiente, nada muda — e nada é consultado.

    PROVA: dois jobs no MESMO tick disparam normalmente, e `agent_profiles` não é lido
    nenhuma vez, porque `config.algum_fluxo_ligado()` corta antes. Os dois jobs têm as
    DUAS formas de apontar para o fluxo: a de produção (conversa com
    `agent_profile_id=NULL`, o CANAL trazendo o perfil embutido) e a que CUSTARIA a
    consulta (conversa apontando para o perfil de botões).

    NÃO PROVA: que o embed `agent_profiles(kind, flow_id)` sai do select de
    `get_due_followups` com o switch desligado — ele não sai, e nem deveria: aquele
    select é um só. A forma de produção resolve pelo dict embutido e não custaria
    consulta nem com o switch ligado; é por isso que o segundo job existe, e é só nele
    que a asserção de "zero consultas" tem conteúdo. A prova de que o cache estava
    FRIO (e não de que o switch cortou) está no fim do teste.
    """
    consultados: list[str] = []

    def _perfil_proibido(profile_id):
        consultados.append(profile_id)
        raise AssertionError("consultou agent_profiles com todos os fluxos desligados")
    monkeypatch.setattr(R, "get_agent_profile", _perfil_proibido)
    R.limpar_cache_de_perfis()

    tick.banco.leads[LEAD_FLUXO] = _linha_de_lead(
        LEAD_FLUXO, TELEFONE_FLUXO, "Fulano Ficticio")
    tick.banco.leads[LEAD_LLM] = _linha_de_lead(
        LEAD_LLM, TELEFONE_LLM, "Siclano Ficticio")
    tick.banco.mensagens[CONV_FLUXO] = [{"content": "e o preço?", "role": "user"}]
    tick.banco.mensagens[CONV_LLM] = [{"content": "oi, tudo bem?", "role": "user"}]

    como_hoje = _job("job-ficticio-5a", "ai_reengage", lead_id=LEAD_FLUXO,
                     phone=TELEFONE_FLUXO, nome="Fulano Ficticio",
                     conversation_id=CONV_FLUXO, perfil_da_conversa=None)
    conversa_aponta = _job("job-ficticio-5b", "ai_reengage", lead_id=LEAD_LLM,
                           phone=TELEFONE_LLM, nome="Siclano Ficticio",
                           conversation_id=CONV_LLM,
                           perfil_da_conversa=PERFIL_BOTOES)

    await tick.rodar([como_hoje, conversa_aponta])

    for job_id in ("job-ficticio-5a", "job-ficticio-5b"):
        desfechos = tick.desfechos(job_id)
        assert len(desfechos) == 1 and desfechos[0]["status"] == "sent", (
            f"{job_id} não disparou como antes do fix: {desfechos}")
    assert len(tick.agente) == 2, "o agente não rodou nos dois jobs"
    assert consultados == [], "agent_profiles foi consultado com os fluxos desligados"
    assert tick.llm == [] and tick.rede == []

    # O cache estava FRIO: com o switch ligado, a MESMA conversa custa a consulta.
    # Sem esta prova, "zero consultas" também seria o resultado de um cache quente.
    monkeypatch.setenv("VALERIA_BOTOES_ENABLED", "on")
    R.fluxo_da_conversa({"id": CONV_LLM, "agent_profile_id": PERFIL_BOTOES},
                        CANAL_DO_JOB)
    assert consultados == [PERFIL_BOTOES], (
        "a consulta não aconteceu nem com o switch ligado — o cache estava quente e "
        "a asserção de zero consultas não provava nada")
