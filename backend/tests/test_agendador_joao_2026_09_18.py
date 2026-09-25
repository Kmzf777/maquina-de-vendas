"""Agendador das cadências do João — quem CRIA os jobs (Task J3, 2026-09-18).

A Task J1 declarou as cadências (`follow_up/cadence_joao.py`), a J2 escreveu o handler
que consome os jobs (`scheduler._process_joao_touch`). Entre as duas faltava quem varre
o funil e cria o job — é isto, e é o único ponto do motor do João que decide QUEM
recebe.

──────────────────────────────────────────────────────────────────────────────
O ACHADO QUE ESTA TASK RESOLVE: `reposicao` e `em_atencao` VIGIAM A MESMA ETAPA
──────────────────────────────────────────────────────────────────────────────

As duas olham `stage_key='novo'` do funil de Reposição — aos 45 e aos 90 dias. O desenho
antigo (esteira-campanha, apagado na J0) não colidia porque a esteira MOVIA o card ao
terminar; este handler não move card nenhum. Sem uma regra explícita, no dia em que
alguém preencher o template de "Em atenção" pela tela (Task J5) o mesmo card passaria a
casar os DOIS gatilhos, e receberia duas cadências ao mesmo tempo.

A REGRA ESCOLHIDA (ver `follow_up/service.py::motivo_para_pular_joao`) é uma PARTIÇÃO
sobre um único booleano — "a Reposição já se esgotou neste card?":

    reposicao   só pega card com reposicao_concluida == False
    em_atencao  só pega card com reposicao_concluida == True

Por ser partição, e não uma diferença de prazo, ela é airtight: não existe estado do
card em que as duas sejam elegíveis — nem no dia 90, nem em nenhum outro. É o que o
teste `test_os_dois_gatilhos_nunca_disparam_para_o_mesmo_card` prova por enumeração.

O ALTERNATIVO REJEITADO: "em_atencao pega 90+ dias E que não está elegível para
reposicao". Depende do RELÓGIO (cooldown, prazos editáveis pela tela) — e os prazos são
justamente o que a ata manda deixar o João editar (33:28). Bastaria ele subir o gatilho
de Reposição para 120 dias para as duas voltarem a colidir, em silêncio.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.follow_up import service as S
from app.follow_up import cadence_joao as C


# Segunda-feira, 10:00 em São Paulo — dentro da janela comercial, para que os offsets
# de dia inteiro caiam em horários previsíveis sem o clamp mexer neles.
NOW = datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc)

JOAO_CHANNEL = {
    "id": "ch-joao",
    "provider": "meta_cloud",
    "provider_config": {"phone_number_id": S.JOAO_PHONE_NUMBER_ID},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Dublê do Supabase — roteia por TABELA, em vez de encadear MagicMock
# ═══════════════════════════════════════════════════════════════════════════════
class _FakeTable:
    def __init__(self, nome: str, fake: "_FakeSupabase"):
        self.nome = nome
        self.fake = fake
        self.op = "select"
        self.payload = None
        self.filtros: list = []

    # encadeamento — nenhum destes filtra de verdade; o teste controla `rows`
    def select(self, *a, **k):
        self.op = "select"
        return self

    def eq(self, col, val):
        self.filtros.append(("eq", col, val))
        return self

    def in_(self, col, val):
        self.filtros.append(("in", col, list(val)))
        return self

    def gte(self, *a):
        return self

    def lte(self, *a):
        return self

    def lt(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a):
        return self

    def single(self):
        return self

    @property
    def not_(self):
        return self

    def insert(self, rows):
        self.op = "insert"
        self.payload = rows
        self.fake.inserts.append((self.nome, rows))
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def execute(self):
        if self.op == "update":
            self.fake.updates.append((self.nome, self.payload, self.filtros))
            return SimpleNamespace(data=[])
        if self.op == "insert":
            return SimpleNamespace(data=self.payload)
        self.fake.selects.append((self.nome, self.filtros))
        return SimpleNamespace(data=self.fake.rows.get(self.nome, []))


class _FakeSupabase:
    def __init__(self, rows=None, rpc_rows=None, tabelas_quebradas=()):
        self.rows = rows or {}
        self.rpc_rows = rpc_rows if rpc_rows is not None else []
        self.tabelas_quebradas = set(tabelas_quebradas)
        self.inserts: list = []
        self.updates: list = []
        self.selects: list = []
        self.rpcs: list = []

    def table(self, nome):
        if nome in self.tabelas_quebradas:
            raise RuntimeError(f"relation '{nome}' does not exist (PGRST205)")
        return _FakeTable(nome, self)

    def rpc(self, nome, args):
        self.rpcs.append((nome, args))
        linhas = self.rpc_rows
        if callable(linhas):
            linhas = linhas(nome, args)
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=linhas))


def _linha_rpc(n=1, deal=None, lead=None):
    return {
        "lead_id": lead or f"lead-{n}",
        "deal_id": deal or f"deal-{n}",
        "stage_id": "stage-novo",
        "last_speaker": "nos",
        "last_message_at": "2026-08-01T12:00:00+00:00",
    }


def _overrides(**por_codigo):
    """`{"reposicao": {"ativa": True}}` → liga a cadência deste CÓDIGO em TODOS os
    funis-irmãos que a possuem — o equivalente, no eixo funil-primeiro, ao "liga nas
    duas linhas" de antes (ex. `novo` liga em `atacado` E `private_label`; `reposicao`
    liga em `reposicao_atacado` E `reposicao_private_label`). Devolve a forma nova que
    `carregar_overrides_joao` produz: `{funil: {codigo: {...}}}`.

    Para ligar um funil só (provar que eles não vazam um para o outro), monte o dict
    `{funil: {codigo: {...}}}` na mão — ver
    `test_cadencia_ativa_so_num_funil_nao_vaza_para_o_outro`.
    """
    resultado: dict[str, dict] = {}
    for codigo, valores in por_codigo.items():
        for f in C.FUNIS:
            if any(c.codigo == codigo for c in f.cadencias):
                resultado.setdefault(f.codigo, {})[codigo] = valores
    return resultado


def _toques_com_template(codigo: str) -> dict[int, dict]:
    """Sobreposição que preenche um template em CADA toque da cadência `codigo`.

    Desde 23/09/2026 as TRÊS cadências de prospecção (`novo`, `em_conversa`,
    `proposta`) nascem sem template em toque nenhum — decisão explícita do dono do
    funil (spec 2026-09-23 §2), a mesma trava que "Em atenção" já tinha. Com isso, o
    agendador RECUSA criar job (`test_cadencia_ligada_sem_template_nao_cria_job` prova
    a recusa), e todo teste do AGENDAMENTO precisa simular a tela já preenchida — que é
    exatamente o que a Task J5 vai permitir, sem deploy.
    """
    quantos = max(
        (len(c.touches) for f in C.FUNIS for c in f.cadencias if c.codigo == codigo),
        default=0,
    )
    return {i: {"template_name": f"joao_{codigo}_t{i}"} for i in range(1, quantos + 1)}


def _ligada(codigo: str, **extras) -> dict:
    """`_overrides` com os templates preenchidos — a cadência LIGA de verdade.

    `toques` passado em `extras` é mesclado toque a toque (e não substituído): gravar
    `{2: {"dias": 30}}` apagaria o template do toque 2 e a cadência voltaria a ser
    recusada, que é o jeito mais silencioso possível de um teste passar por engano.
    """
    toques = _toques_com_template(codigo)
    for sequence, valores in (extras.pop("toques", None) or {}).items():
        toques[sequence] = {**toques.get(sequence, {}), **valores}
    return _overrides(**{codigo: {"ativa": True, "toques": toques, **extras}})


def _so_toques(jobs: list[dict]) -> list[dict]:
    """Os jobs de TOQUE — sem o job de mover, que fecha a matrícula e não é toque."""
    return [j for j in jobs if j["metadata"].get("acao") != "mover_etapa"]


def _so_moves(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if j["metadata"].get("acao") == "mover_etapa"]


def _do_funil(fake, funil: str) -> list[dict]:
    return [j for j in _jobs_criados(fake) if j["metadata"]["funil"] == funil]


def _rodar(fake, overrides, *, teto=None, now=NOW, canal=JOAO_CHANNEL,
           blacklisted=False):
    """Executa uma passagem do agendador com todo o I/O dublado."""
    with (
        patch("app.follow_up.service.get_supabase", return_value=fake),
        patch("app.follow_up.service.carregar_overrides_joao", return_value=overrides),
        patch("app.follow_up.service.get_channel_by_provider_config", return_value=canal),
        patch("app.follow_up.service.get_or_create_conversation",
              side_effect=lambda lead_id, ch: {"id": f"conv-{lead_id}"}),
        patch("app.leads.service.is_lead_blacklisted", return_value=blacklisted),
        patch("app.follow_up.service.emit_event"),
    ):
        return S.agendar_cadencias_joao(now=now, teto=teto)


def _jobs_criados(fake):
    criados = []
    for tabela, rows in fake.inserts:
        assert tabela == "follow_up_jobs"
        criados.extend(rows if isinstance(rows, list) else [rows])
    return criados


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Cadência desligada
# ═══════════════════════════════════════════════════════════════════════════════
def test_cadencia_desligada_nao_cria_job_nenhum():
    """`ativa=False` é o default das QUATRO cadências no código (spec §7).

    E "não cria job" aqui é mais forte do que "não insere": a varredura nem chega a
    perguntar ao banco. Medido em 16/09: 888 cards ficam elegíveis no instante em que
    uma cadência liga — uma varredura que roda e depois descarta seria 888 linhas lidas
    a cada 30 segundos, para nada.
    """
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    assert _rodar(fake, {}) == 0
    assert fake.rpcs == []
    assert fake.inserts == []


def test_todas_as_cadencias_nascem_desligadas_no_codigo():
    """A trava a montante: sem override no banco, `resolver(...).ativa` é False em toda
    cadência de todo funil — inclusive `recuperacao`, que não tem cadência nenhuma
    (`cadencias == ()`, o laço abaixo não roda para ele)."""
    for f in C.FUNIS:
        for cadencia in f.cadencias:
            assert C.resolver(f.codigo, cadencia.codigo).ativa is False


# ═══════════════════════════════════════════════════════════════════════════════
# 1b. Funil é o eixo — isolamento entre funis-irmãos, e Recuperação vazia
# ═══════════════════════════════════════════════════════════════════════════════
def test_cadencia_ativa_so_num_funil_nao_vaza_para_o_outro():
    """Atacado e Private Label deixaram de estar acoplados (spec 2026-09-21 §2,
    decisão 1): ligar o `novo` só no funil Atacado não liga o irmão Private Label —
    cada `(funil, cadência)` tem seu próprio liga/desliga."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    so_atacado = {"atacado": _ligada("novo")["atacado"]}  # só um dos dois funis
    _rodar(fake, so_atacado)

    pipelines = {a["p_pipeline_id"] for _, a in fake.rpcs}
    assert pipelines == {C.PIPELINE_ATACADO}  # NUNCA C.PIPELINE_PRIVATE_LABEL


def test_recuperacao_nunca_gera_job_mesmo_que_o_banco_tente_ligar():
    """`João - Recuperação` não tem cadência (spec 2026-09-21 §1, `Funil.cadencias ==
    ()`). Provado pelo COMPORTAMENTO, não por um `if` especial no agendador: mesmo que
    a tabela de overrides traga uma linha teimosa para `funil="recuperacao"` com
    códigos de cadência que nem existem nela, o laço `for cadencia in funil.cadencias`
    do agendador não roda nenhuma vez para este funil — zero RPC, zero job.
    """
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    overrides = {"recuperacao": {
        "novo": {"ativa": True}, "reposicao": {"ativa": True},
        "em_conversa": {"ativa": True}, "em_atencao": {"ativa": True},
    }}
    assert _rodar(fake, overrides) == 0
    assert fake.rpcs == []
    assert fake.inserts == []


def test_teto_e_por_par_funil_cadencia_nao_um_teto_global():
    """O teto é aplicado a CADA passagem de `(funil, cadência)`, não a uma varredura
    global: duas cadências "novo" (uma por funil-irmão) com POOLS DIFERENTES de cards
    cada uma respeita o SEU teto — uma não rouba cota da outra."""
    def rpc_rows(_nome, args):
        prefixo = "atacado" if args["p_pipeline_id"] == C.PIPELINE_ATACADO else "pl"
        return [_linha_rpc(i, lead=f"{prefixo}-lead-{i}") for i in range(1, 6)]

    fake = _FakeSupabase(rpc_rows=rpc_rows)
    _rodar(fake, _ligada("novo"), teto=2)

    leads = {j["lead_id"] for j in _jobs_criados(fake)}
    # 2 do funil Atacado + 2 do funil Private Label — cada passagem respeitou o SEU teto
    assert leads == {"atacado-lead-1", "atacado-lead-2", "pl-lead-1", "pl-lead-2"}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. A varredura reusa a RPC que já tem as guardas
# ═══════════════════════════════════════════════════════════════════════════════
def test_varredura_usa_a_rpc_get_deals_stage_stagnant():
    """Nenhuma consulta nova: a RPC já traz blacklist, número errado e conversa
    finalizada no próprio WHERE (20260904_esteiras_vendedor.sql)."""
    fake = _FakeSupabase(rpc_rows=[])
    _rodar(fake, _ligada("novo"))

    assert fake.rpcs, "a cadência ligada tem de varrer"
    nomes = {nome for nome, _ in fake.rpcs}
    assert nomes == {"get_deals_stage_stagnant"}


def test_parametros_da_rpc_saem_da_cadencia_resolvida():
    fake = _FakeSupabase(rpc_rows=[])
    _rodar(fake, _ligada("novo"), teto=7)

    args_por_pipeline = {a["p_pipeline_id"]: a for _, a in fake.rpcs}
    assert set(args_por_pipeline) == {C.PIPELINE_ATACADO, C.PIPELINE_PRIVATE_LABEL}
    args = args_por_pipeline[C.PIPELINE_ATACADO]
    assert args["p_stage_key"] == "novo"
    assert args["p_stage_id"] is None
    assert args["p_stage_days"] == 2          # gatilho da ata (01:07:10)
    assert args["p_silence_days"] == 2        # o SEGUNDO relógio (spec 2026-09-23 §5)
    assert args["p_last_speaker"] == "qualquer"
    assert args["p_limit"] == 7               # o teto vai JUNTO para o banco
    assert args["p_channel_id"] == JOAO_CHANNEL["id"]
    assert args["p_audience"] == S.JOAO_CADENCIA_AUDIENCIA


# ── O SEGUNDO relógio do gatilho: `p_silence_days` (spec 2026-09-23 §5) ───────
@pytest.mark.parametrize("codigo,silencio", [
    ("novo", 2),          # "2 dias sem conversar" — o dono, 23/09
    ("em_conversa", 2),   # idem
    ("proposta", 0),      # "24h DEPOIS da proposta": o relógio é o da ETAPA
    ("reposicao", 0),     # "45 dias em Cliente Ativo": idem
    ("em_atencao", 0),    # "90 dias sem comprar": idem
])
def test_p_silence_days_vem_da_cadencia_e_nao_e_mais_fixo_em_zero(codigo, silencio):
    """Era `"p_silence_days": 0` hardcoded, com a justificativa de que "o relógio da
    ata é o da ETAPA". Vale para quatro das cinco cadências — e não vale para as duas
    que o dono descreveu em 23/09 como "2 dias SEM CONVERSAR".

    Os dois parâmetros combinam por AND dentro da RPC, e 0 desliga o respectivo filtro.
    Trocar um pelo outro em `novo` não quebraria nada visível: a esteira só pegaria
    menos (ou mais) gente, em silêncio. Por isso o número é conferido aqui, na fronteira
    com o banco, e não só na declaração.
    """
    fake = _FakeSupabase(rpc_rows=[])
    _rodar(fake, _ligada(codigo))

    assert fake.rpcs, "a cadência ligada tem de varrer"
    assert {a["p_silence_days"] for _, a in fake.rpcs} == {silencio}
    # Nunca muda: um lead calado há 2 dias merece follow-up tanto se a última palavra
    # foi dele quanto se foi nossa.
    assert {a["p_last_speaker"] for _, a in fake.rpcs} == {"qualquer"}


def test_gatilho_dias_do_banco_sobrepoe_o_do_codigo():
    """Ata 33:28 — "45 dias, mas opção do João editar o número de dias"."""
    fake = _FakeSupabase(rpc_rows=[])
    _rodar(fake, _overrides(reposicao={"ativa": True, "gatilho_dias": 60}))

    assert {a["p_stage_days"] for _, a in fake.rpcs} == {60}


def test_sem_canal_do_joao_nao_cria_job():
    """O toque TEM de sair do número do vendedor. Sem canal, nada é criado —
    em vez de criar job com o canal da ValerIA e assinar "João" no número errado."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    assert _rodar(fake, _overrides(novo={"ativa": True}), canal=None) == 0
    assert fake.inserts == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Os jobs criados — a forma que a Task J2 espera
# ═══════════════════════════════════════════════════════════════════════════════
def test_cria_um_job_por_toque_de_uma_vez():
    """Decisão documentada: a cadência inteira é agendada na matrícula.

    O alternativo (criar só o próximo toque, e o seguinte quando este sair) exigiria
    que o handler reagendasse — acoplando o caminho de ENVIO ao de AGENDAMENTO, que é
    exatamente o que separa este motor do builder que foi abandonado.
    """
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _ligada("em_conversa"))

    # 4 toques (eram 7 até 22/09; spec 2026-09-23 §1) × 2 funis-irmãos — mas o mesmo
    # card volta em cada varredura de funil porque o dublê devolve a mesma linha de RPC
    # para os dois.
    toques = _so_toques(_do_funil(fake, "atacado"))
    assert len(toques) == 4
    assert [j["metadata"]["toque"] for j in toques] == [1, 2, 3, 4]


def test_metadata_do_job_cumpre_o_contrato_do_handler():
    """A forma documentada no topo de `scheduler._process_joao_touch`."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _overrides(reposicao={"ativa": True}))

    job = _jobs_criados(fake)[0]
    md = job["metadata"]
    assert job["job_type"] == "joao_reposicao"
    assert job["status"] == "pending"
    assert job["conversation_id"] == "conv-lead-1"
    assert job["channel_id"] == JOAO_CHANNEL["id"]
    assert job["lead_id"] == "lead-1"
    assert job["sequence"] == md["toque"] == 1
    assert md["cadencia"] == "reposicao"
    # "reposicao_atacado" é o primeiro funil-irmão em `cj.FUNIS` a ter a cadência
    # "reposicao" — é dele que sai o job[0] desta passagem.
    assert md["funil"] == "reposicao_atacado"
    assert md["template_name"] == "joao_reposicao_atacado_t1"
    assert md["deal_id"] == "deal-1"
    assert md["phone_number_id"] == S.JOAO_PHONE_NUMBER_ID
    assert md["matricula_id"] and md["matricula_em"]


def test_ultimo_toque_e_marcado_e_so_ele():
    """`ultimo_toque` é o que prova, mais tarde, que a cadência se ESGOTOU no card —
    e é sobre isso que a exclusão mútua decide. Contar toques enviados não serve: a
    tela pode mudar os dias, e o código pode mudar a forma da cadência."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _overrides(reposicao={"ativa": True}))

    do_funil = [j for j in _jobs_criados(fake)
                if j["metadata"]["funil"] == "reposicao_atacado"]
    assert [j["metadata"]["ultimo_toque"] for j in do_funil] == [False, False, False, True]


def test_fire_at_sai_dos_offsets_e_respeita_a_janela_comercial():
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _ligada("em_conversa"))

    toques = _so_toques(_do_funil(fake, "atacado"))
    fire = [datetime.fromisoformat(j["fire_at"]) for j in toques]
    offsets = C._EM_CONVERSA_OFFSETS

    assert fire[0] == NOW                       # offset 0, já dentro da janela
    assert fire[1] == NOW + timedelta(days=2)   # quarta-feira, 10h BRT
    for alvo, dias in zip(fire, offsets):
        assert alvo >= NOW + timedelta(days=dias)   # o clamp só empurra p/ frente
        assert S.is_within_business_window(alvo)


def test_dias_do_banco_sobrepoem_os_offsets_do_codigo():
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _overrides(reposicao={
        "ativa": True, "toques": {2: {"dias": 30}},
    }))

    do_funil = [j for j in _jobs_criados(fake)
                if j["metadata"]["funil"] == "reposicao_atacado"]
    assert datetime.fromisoformat(do_funil[1]["fire_at"]) == NOW + timedelta(days=30)


# ═══════════════════════════════════════════════════════════════════════════════
# 3b. O JOB DE MOVER — a matrícula termina empurrando o card para "Em atenção"
# ═══════════════════════════════════════════════════════════════════════════════
#
# Spec 2026-09-23 §3, e é a ÚNICA exceção ao "o motor nunca move card" do spec de 18/09.
# O contrato com o handler (`scheduler._process_joao_touch`) é uma marca só:
#
#     metadata["acao"] == "mover_etapa"
#
# Nada de inferir pelo template nulo — job de TOQUE sem template também existe, e hoje
# é o estado das três cadências de prospecção inteiras.
@pytest.mark.parametrize("codigo,offsets", [
    ("novo", C._NOVO_OFFSETS),
    ("em_conversa", C._EM_CONVERSA_OFFSETS),
    ("proposta", C._PROPOSTA_OFFSETS),
])
def test_o_job_de_mover_fecha_a_matricula_das_tres_cadencias(codigo, offsets):
    """Um job a mais, no fim, com a marca — nos dois funis e nas três cadências."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _ligada(codigo))

    for funil, pipeline in (("atacado", C.PIPELINE_ATACADO),
                            ("private_label", C.PIPELINE_PRIVATE_LABEL)):
        do_funil = _do_funil(fake, funil)
        toques, moves = _so_toques(do_funil), _so_moves(do_funil)
        assert len(toques) == len(offsets)
        assert len(moves) == 1, "um move por matrícula, nem zero nem dois"

        mover, ultimo = moves[0], toques[-1]
        md = mover["metadata"]
        assert mover["job_type"] == f"joao_{codigo}" == ultimo["job_type"]
        assert mover["status"] == "pending"
        # `sequence` é NOT NULL na tabela, e reusar a do último toque daria dois jobs
        # com a mesma sequence dentro da mesma matrícula.
        assert mover["sequence"] == ultimo["sequence"] + 1 == len(offsets) + 1
        assert md["acao"] == "mover_etapa"
        assert md["etapa_final_key"] == "em_atencao"
        assert md["template_name"] is None
        assert md["cadencia"] == codigo and md["funil"] == funil
        assert md["pipeline_id"] == pipeline
        assert md["deal_id"] == "deal-1"
        # MESMO `matricula_id` dos toques: é por ele que a resposta do lead cancela (e
        # o adiamento de 60 dias desliza) o bloco INTEIRO, o move incluído.
        assert md["matricula_id"] == ultimo["metadata"]["matricula_id"]


@pytest.mark.parametrize("codigo,offsets", [
    ("novo", C._NOVO_OFFSETS),
    ("em_conversa", C._EM_CONVERSA_OFFSETS),
    ("proposta", C._PROPOSTA_OFFSETS),
])
def test_o_move_e_agendado_um_dia_depois_do_ultimo_toque(codigo, offsets):
    """`dias_ate_mover=1` — 24h depois do último toque, e dentro da janela comercial.

    O clamp é o MESMO dos toques (spec §3): um move empurrado das 2h para as 8h é
    invisível para o lead, e a alternativa seria um ramo a mais no laço. Em `novo` o
    alvo cai num SÁBADO (dia 5 a partir de uma segunda) — é justamente o caso que
    prova que o move não escapa da janela.
    """
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _ligada(codigo))

    do_funil = _do_funil(fake, "atacado")
    ultimo = datetime.fromisoformat(_so_toques(do_funil)[-1]["fire_at"])
    quando = datetime.fromisoformat(_so_moves(do_funil)[0]["fire_at"])

    assert quando >= ultimo + timedelta(days=1)   # o clamp só empurra para a frente
    assert quando > ultimo                        # nunca antes do último toque
    assert S.is_within_business_window(quando)


def test_o_move_da_proposta_cai_no_dia_9_da_matricula():
    """O número da reunião, sem o clamp no meio: toques em 0/1/4/8, move no dia 9."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _ligada("proposta"))

    mover = _so_moves(_do_funil(fake, "atacado"))[0]
    assert datetime.fromisoformat(mover["fire_at"]) == NOW + timedelta(days=9)


def test_a_cadencia_que_se_repete_nunca_ganha_job_de_mover():
    """"Em atenção" é `repete_ultimo`: "uma mensagem a cada três dias ATÉ ele falar que
    não quer" (ata 38:08) — uma cadência SEM FIM declarado."""
    fake = _FakeSupabase(
        rpc_rows=[_linha_rpc()],
        rows={"follow_up_jobs": list(_REPOSICAO_CONCLUIDA_ONTEM)},
    )
    _rodar(fake, _ligada("em_atencao"))

    jobs = _jobs_criados(fake)
    assert jobs, "a cadência ligada tem de matricular"
    assert _so_moves(jobs) == []


def test_repete_ultimo_barra_o_move_mesmo_com_etapa_final_declarada():
    """A guarda `repete_ultimo` é a SEGUNDA, e hoje nenhuma cadência real a exercita:
    "Em atenção" já é barrada pela primeira (`etapa_final_key is None`). Ela existe
    para o dia em que alguém declarar um destino numa cadência que se repete — a
    tentação é grande, porque "Em atenção" é ao mesmo tempo o código de uma CADÊNCIA e
    a key de uma ETAPA.

    Sem ela, o move nasceria a CADA passagem (a cadência que se repete cria um job por
    vez, para sempre): o card seria empurrado para a etapa final no primeiro
    vencimento, e a esteira continuaria criando moves de um card que já saiu.

    Montada à mão de propósito — um cenário que o código não produz hoje é exatamente
    o que uma guarda defensiva protege, e testá-lo pelo agendador seria impossível.
    """
    ate = S.resolver_para_agendar("reposicao_atacado", "em_atencao", {"ativa": True})
    assert ate.repete_ultimo and ate.etapa_final_key is None
    hibrida = replace(ate, etapa_final_key="em_atencao", etapa_final_rotulo="Em atenção")

    rows = S._montar_jobs_da_matricula(
        hibrida, _linha_rpc(), canal=JOAO_CHANNEL, conversation_id="conv-1",
        now=NOW, jobs_do_card=[])

    assert len(rows) == 1, "a cadência que se repete cria UM job por passagem"
    assert _so_moves(rows) == []


def test_as_cadencias_de_reposicao_continuam_sem_mover_card():
    """`etapa_final_key is None` nas duas (spec 2026-09-23 §7, "o que NÃO muda"): o
    card de Reposição não tem para onde ir — o funil dele é de cliente ativo."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _overrides(reposicao={"ativa": True}))

    jobs = _jobs_criados(fake)
    assert len(jobs) == 8          # 4 toques × 2 funis-irmãos, e nada além
    assert _so_moves(jobs) == []


def test_o_move_nao_conta_para_a_trava_de_ativacao():
    """`toques_sem_template` olha `touches`, e o move não é um `Touch` — é uma
    propriedade da cadência. Se contasse, nenhuma das três poderia ser ligada nem com
    todos os textos preenchidos (spec 2026-09-23 §3)."""
    for funil in ("atacado", "private_label"):
        for codigo in ("novo", "em_conversa", "proposta"):
            cadencia = C.cadencia_do_funil(funil, codigo)
            assert cadencia.etapa_final_key == "em_atencao"
            ov = {"toques": _toques_com_template(codigo)}
            assert C.toques_sem_template(funil, codigo, ov) == ()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Idempotência e reentrada
# ═══════════════════════════════════════════════════════════════════════════════
def _job_existente(cadencia, toque, status, *, deal="deal-1", lead="lead-1",
                   ultimo=False, sent_at=None, created_at=None, matricula="m-1"):
    return {
        "id": f"job-{cadencia}-{toque}-{status}",
        "lead_id": lead,
        "job_type": f"joao_{cadencia}",
        "status": status,
        "sequence": toque,
        "sent_at": sent_at,
        "fire_at": (created_at or NOW).isoformat(),
        "created_at": (created_at or NOW).isoformat(),
        "metadata": {
            "cadencia": cadencia, "toque": toque, "deal_id": deal,
            "ultimo_toque": ultimo, "matricula_id": matricula,
            "matricula_em": (created_at or NOW).isoformat(),
        },
    }


def test_idempotente_card_com_job_aberto_nao_ganha_outro():
    fake = _FakeSupabase(
        rpc_rows=[_linha_rpc()],
        rows={"follow_up_jobs": [_job_existente("reposicao", 2, "pending")]},
    )
    assert _rodar(fake, _overrides(reposicao={"ativa": True})) == 0
    assert fake.inserts == []


def test_job_aberto_de_OUTRA_cadencia_tambem_barra():
    """Um card, uma cadência por vez. Duas cadências abertas no mesmo card mandariam
    dois templates diferentes, do mesmo vendedor, no mesmo dia."""
    fake = _FakeSupabase(
        rpc_rows=[_linha_rpc()],
        rows={"follow_up_jobs": [_job_existente("em_conversa", 3, "pending")]},
    )
    assert _rodar(fake, _overrides(novo={"ativa": True})) == 0


def test_job_cancelado_nao_barra_a_reentrada():
    """`cancelled` não é cadência em andamento — é cadência que MORREU."""
    antigo = _job_existente(
        "novo", 1, "cancelled", created_at=NOW - timedelta(days=200))
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()], rows={"follow_up_jobs": [antigo]})
    assert _rodar(fake, _ligada("novo")) > 0


def test_cooldown_impede_a_cadencia_de_recomecar_sozinha():
    """O defeito que a RPC documenta em 20260904: o card não sai da etapa quando a
    cadência acaba, então na varredura seguinte ele é elegível de novo — um template a
    cada poucos dias, para sempre."""
    concluido = _job_existente(
        "novo", 1, "sent", ultimo=True,
        sent_at=(NOW - timedelta(days=3)).isoformat(),
        created_at=NOW - timedelta(days=3))
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()], rows={"follow_up_jobs": [concluido]})
    assert _rodar(fake, _ligada("novo")) == 0


def test_passado_o_cooldown_o_card_pode_reentrar():
    """Card que sai da etapa e volta meses depois é oportunidade legítima — mesma
    doutrina do `p_cooldown_days` da RPC (exclusão temporária, não permanente)."""
    antigo = _job_existente(
        "novo", 1, "sent", ultimo=True,
        sent_at=(NOW - timedelta(days=200)).isoformat(),
        created_at=NOW - timedelta(days=200))
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()], rows={"follow_up_jobs": [antigo]})
    assert _rodar(fake, _ligada("novo")) > 0


# ── O trinco de 90 dias conta MATRÍCULA, não job (spec 2026-09-23 §4) ─────────
#
# A regra antiga já ignorava job `cancelled` — a intenção sempre foi "cadência que
# morreu não segura reentrada". Mas ela olhava UM JOB POR VEZ, e quando o lead responde
# no meio só os PENDENTES são cancelados (`cancel_followups_by_phone`, motivo
# `client_replied`): os toques que JÁ SAÍRAM ficam `sent`, e eram ELES que disparavam o
# cooldown. Resultado em produção: o lead que responde no T2 e volta a sumir fica 90
# dias sem esteira nenhuma — o oposto exato de "se responder, reinicia".
def _matricula_interrompida(dias_atras=3, matricula="m-respondeu"):
    """O lead respondeu no T2: dois toques SAÍRAM, os dois restantes foram cancelados.

    É o estado mais comum da esteira em produção, e o que a regra antiga lia como
    "cadência completa".
    """
    nasceu = NOW - timedelta(days=dias_atras)
    return [
        _job_existente("novo", 1, "sent", sent_at=nasceu.isoformat(),
                       created_at=nasceu, matricula=matricula),
        _job_existente("novo", 2, "sent",
                       sent_at=(nasceu + timedelta(days=2)).isoformat(),
                       created_at=nasceu, matricula=matricula),
        _job_existente("novo", 3, "cancelled", created_at=nasceu, matricula=matricula),
        _job_existente("novo", 4, "cancelled", created_at=nasceu, ultimo=True,
                       matricula=matricula),
    ]


def _matricula_completa(dias_atras=3, matricula="m-completa"):
    """A esteira terminou o trabalho dela: todos os toques saíram, nada foi cancelado."""
    nasceu = NOW - timedelta(days=dias_atras)
    return [
        _job_existente("novo", n, "sent",
                       sent_at=(nasceu + timedelta(days=n)).isoformat(),
                       created_at=nasceu, ultimo=(n == 3), matricula=matricula)
        for n in (1, 2, 3)
    ]


def _cadencia_novo():
    return S.resolver_para_agendar("atacado", "novo", {"ativa": True})


def test_lead_que_respondeu_no_meio_reentra_na_esteira():
    """O TESTE DESTE LOTE. Matrícula INTERROMPIDA (tem job `cancelled`) não segura
    reentrada, por mais recente que seja — "se responder, reinicia"."""
    assert S.motivo_para_pular_joao(
        _cadencia_novo(), _matricula_interrompida(), NOW) is None


def test_matricula_completa_segura_a_reentrada_por_90_dias():
    """O contrapeso, e é o defeito original que o cooldown existe para tampar (a RPC o
    documenta em 20260904): o card NÃO sai da etapa quando a cadência acaba, então na
    varredura seguinte ele é elegível de novo — um template a cada poucos dias, para
    sempre."""
    assert S.motivo_para_pular_joao(
        _cadencia_novo(), _matricula_completa(), NOW) == "cooldown"


def test_uma_matricula_interrompida_nao_apaga_outra_que_rodou_inteira():
    """As duas coisas ao mesmo tempo: o card já teve uma esteira COMPLETA há 3 dias e
    outra interrompida. A completa continua segurando — a interrupção de uma matrícula
    não é um perdão geral."""
    jobs = _matricula_completa() + _matricula_interrompida()
    assert S.motivo_para_pular_joao(_cadencia_novo(), jobs, NOW) == "cooldown"


def test_matricula_completa_ha_mais_de_90_dias_libera():
    """`JOAO_COOLDOWN_DIAS` continua 90: muda O QUE conta, não por quanto tempo."""
    assert S.JOAO_COOLDOWN_DIAS == 90
    assert S.motivo_para_pular_joao(
        _cadencia_novo(), _matricula_completa(dias_atras=91), NOW) is None


def test_job_sem_matricula_id_conta_como_matricula_propria():
    """Nenhum job criado por este agendador é assim — mas um criado à mão seria, e o
    campo é lido de `metadata`. O lado conservador é ele contar SOZINHO, em vez de ser
    absorvido por um bloco cancelado que não é dele."""
    orfao = _job_existente("novo", 1, "sent", created_at=NOW - timedelta(days=3))
    del orfao["metadata"]["matricula_id"]
    de_outra = _job_existente("novo", 1, "cancelled", created_at=NOW - timedelta(days=3),
                              matricula="m-outra")

    assert S.motivo_para_pular_joao(
        _cadencia_novo(), [orfao, de_outra], NOW) == "cooldown"


def test_cooldown_de_outra_cadencia_nao_conta():
    """O cooldown é por `job_type`: uma matrícula completa de "Em conversa" não segura
    a entrada em "Novo" (o que segura entre cadências diferentes é a regra 1, "um card,
    uma cadência por vez", e ela só olha `pending`)."""
    de_em_conversa = [
        _job_existente("em_conversa", n, "sent", created_at=NOW - timedelta(days=3),
                       sent_at=(NOW - timedelta(days=3)).isoformat(),
                       matricula="m-conversa")
        for n in (1, 2, 3, 4)
    ]
    assert S.motivo_para_pular_joao(_cadencia_novo(), de_em_conversa, NOW) is None


def test_reentrada_depois_da_resposta_cria_jobs_de_verdade():
    """O mesmo cenário, agora ponta a ponta pelo agendador: o card volta a ser
    matriculado, com a cadência inteira e o job de mover."""
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()],
                         rows={"follow_up_jobs": _matricula_interrompida()})
    assert _rodar(fake, _ligada("novo")) > 0

    do_atacado = _do_funil(fake, "atacado")
    assert len(_so_toques(do_atacado)) == 3
    assert len(_so_moves(do_atacado)) == 1


def test_matricula_completa_recente_nao_reentra_pelo_agendador():
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()],
                         rows={"follow_up_jobs": _matricula_completa()})
    assert _rodar(fake, _ligada("novo")) == 0
    assert fake.inserts == []


def test_jobs_de_outro_card_do_mesmo_lead_nao_barram():
    """A cadência é do CARD, não do lead: o mesmo lead tem card em Atacado e card em
    Reposição, e eles caminham em paralelo."""
    de_outro_card = _job_existente("reposicao", 1, "pending", deal="deal-OUTRO")
    fake = _FakeSupabase(
        rpc_rows=[_linha_rpc()], rows={"follow_up_jobs": [de_outro_card]})
    assert _rodar(fake, _overrides(reposicao={"ativa": True})) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Teto por passagem
# ═══════════════════════════════════════════════════════════════════════════════
def test_teto_por_passagem_limita_os_cards():
    """Medido em 16/09: 888 cards ficam elegíveis no instante em que uma cadência liga.

    O `p_limit` vai para a RPC, mas o corte também é feito AQUI: o dublê (como um banco
    que ignorasse o LIMIT, ou uma RPC substituída) devolve cinco linhas, e ainda assim
    só duas viram matrícula.
    """
    fake = _FakeSupabase(rpc_rows=[_linha_rpc(n) for n in range(1, 6)])
    _rodar(fake, _ligada("novo"), teto=2)

    leads = {j["lead_id"] for j in _jobs_criados(fake)}
    assert len(leads) == 2


def test_teto_tem_default_seguro():
    assert S.JOAO_TETO_PADRAO == 20


def test_cadencia_ligada_sem_template_nao_cria_job():
    """Defesa em profundidade da trava da Task J4 ("ligar exige template aprovado em
    todo toque"). "Em atenção" nasce sem template — os 24 aprovados na Meta cobrem só
    Novo, Em conversa e Reposição. Um job sem template chega ao handler e morre em
    `missing_template_name`: cadência que matricula, não envia, e caminha até o fim."""
    fake = _FakeSupabase(
        rpc_rows=[_linha_rpc()],
        rows={"follow_up_jobs": list(_REPOSICAO_CONCLUIDA_ONTEM)},
    )
    assert _rodar(fake, _overrides(em_atencao={"ativa": True})) == 0
    assert fake.inserts == []


# ═══════════════════════════════════════════════════════════════════════════════
# 6. A EXCLUSÃO MÚTUA — o achado desta task
# ═══════════════════════════════════════════════════════════════════════════════
#
# `reposicao` (45 dias) e `em_atencao` (90 dias) vigiam `stage_key='novo'` do MESMO funil
# de Reposição. A regra é uma partição sobre "a Reposição já se esgotou neste card?".
def _estado(nome, jobs):
    return pytest.param(jobs, id=nome)


_NUNCA_RODOU: list = []
_REPOSICAO_EM_ANDAMENTO = [
    _job_existente("reposicao", 1, "sent", sent_at=(NOW - timedelta(days=15)).isoformat(),
                   created_at=NOW - timedelta(days=15)),
    _job_existente("reposicao", 2, "pending", created_at=NOW - timedelta(days=15)),
]
_REPOSICAO_CONCLUIDA_ONTEM = [
    _job_existente("reposicao", 4, "sent", ultimo=True,
                   sent_at=(NOW - timedelta(days=1)).isoformat(),
                   created_at=NOW - timedelta(days=46)),
]
# O estado que desmonta a regra baseada em PRAZO: a Reposição acabou há tanto tempo que
# nenhum cooldown a segura mais. Só a partição explícita impede as duas de coexistirem.
_REPOSICAO_CONCLUIDA_HA_MUITO = [
    _job_existente("reposicao", 4, "sent", ultimo=True,
                   sent_at=(NOW - timedelta(days=200)).isoformat(),
                   created_at=NOW - timedelta(days=245)),
]


@pytest.mark.parametrize("jobs", [
    _estado("nunca_rodou", _NUNCA_RODOU),
    _estado("reposicao_em_andamento", _REPOSICAO_EM_ANDAMENTO),
    _estado("reposicao_concluida_ontem", _REPOSICAO_CONCLUIDA_ONTEM),
    _estado("reposicao_concluida_ha_200_dias", _REPOSICAO_CONCLUIDA_HA_MUITO),
])
def test_os_dois_gatilhos_nunca_disparam_para_o_mesmo_card(jobs):
    """A PROVA. Em nenhum estado do card as duas cadências são elegíveis juntas.

    Mutação obrigatória desta task: troque a regra de exclusão por "nenhuma" (apague a
    partição de `motivo_para_pular_joao`) e o estado `reposicao_concluida_ha_200_dias`
    fica vermelho — é o estado em que o cooldown já expirou e SÓ a partição separa as
    duas.
    """
    rep = S.resolver_para_agendar("reposicao_atacado", "reposicao",
                                  {"ativa": True})
    ate = S.resolver_para_agendar("reposicao_atacado", "em_atencao",
                                  {"ativa": True})
    motivo_rep = S.motivo_para_pular_joao(rep, jobs, NOW)
    motivo_ate = S.motivo_para_pular_joao(ate, jobs, NOW)

    assert not (motivo_rep is None and motivo_ate is None), (
        f"os dois gatilhos elegíveis no mesmo card: rep={motivo_rep} ate={motivo_ate}"
    )


def test_em_atencao_ignora_card_que_nunca_passou_pela_reposicao():
    """"90 dias parado" isolado NÃO é "Em atenção": a ata (38:08) descreve o estado
    de quem já esgotou a régua de Reposição, não de quem nunca entrou nela."""
    ate = S.resolver_para_agendar("reposicao_atacado", "em_atencao", {"ativa": True})
    assert S.motivo_para_pular_joao(ate, [], NOW) == "reposicao_nao_concluida"


def test_em_atencao_pega_o_card_que_esgotou_a_reposicao():
    ate = S.resolver_para_agendar("reposicao_atacado", "em_atencao", {"ativa": True})
    assert S.motivo_para_pular_joao(ate, _REPOSICAO_CONCLUIDA_ONTEM, NOW) is None


def test_reposicao_nao_volta_ao_card_que_ja_a_esgotou():
    rep = S.resolver_para_agendar("reposicao_atacado", "reposicao", {"ativa": True})
    assert (S.motivo_para_pular_joao(rep, _REPOSICAO_CONCLUIDA_HA_MUITO, NOW)
            == "reposicao_ja_concluida")


def test_em_atencao_repete_respeitando_o_intervalo():
    """Ata 38:08: "uma mensagem a cada três dias até ele falar que não quer"."""
    base = list(_REPOSICAO_CONCLUIDA_ONTEM)
    ate = S.resolver_para_agendar("reposicao_atacado", "em_atencao", {"ativa": True})

    recente = base + [_job_existente(
        "em_atencao", 1, "sent", sent_at=(NOW - timedelta(days=1)).isoformat(),
        created_at=NOW - timedelta(days=1), matricula="m-at-1")]
    assert S.motivo_para_pular_joao(ate, recente, NOW) == "intervalo_da_repeticao"

    vencido = base + [_job_existente(
        "em_atencao", 1, "sent", sent_at=(NOW - timedelta(days=4)).isoformat(),
        created_at=NOW - timedelta(days=4), matricula="m-at-1")]
    assert S.motivo_para_pular_joao(ate, vencido, NOW) is None


def test_em_atencao_cria_um_job_por_vez():
    """A cadência que se repete não tem fim declarado — "todos os toques de uma vez"
    é literalmente impossível nela."""
    fake = _FakeSupabase(
        rpc_rows=[_linha_rpc()],
        rows={"follow_up_jobs": list(_REPOSICAO_CONCLUIDA_ONTEM)},
    )
    # `em_atencao` nasce SEM template (os 24 aprovados não a cobrem); para exercitar o
    # agendamento, a sobreposição preenche o template — que é exatamente o que a tela
    # da Task J5 vai permitir, e o cenário que torna a exclusão mútua urgente.
    _rodar(fake, _overrides(em_atencao={
        "ativa": True, "toques": {1: {"template_name": "joao_em_atencao_atacado_t1"}},
    }))
    do_funil = [j for j in _jobs_criados(fake)
                if j["metadata"]["funil"] == "reposicao_atacado"]
    assert len(do_funil) == 1
    assert do_funil[0]["metadata"]["ultimo_toque"] is False  # nunca termina


# ═══════════════════════════════════════════════════════════════════════════════
# 7. A resposta do lead (ata 41:40)
# ═══════════════════════════════════════════════════════════════════════════════
def _pendentes_e_enviados():
    return [
        _job_existente("reposicao", 1, "sent",
                       sent_at=(NOW - timedelta(days=15)).isoformat(),
                       created_at=NOW - timedelta(days=15)),
        _job_existente("reposicao", 2, "pending", created_at=NOW - timedelta(days=15)),
        _job_existente("reposicao", 3, "pending", created_at=NOW - timedelta(days=15)),
    ]


def _responder(texto, jobs, *, optout=None):
    # `optout=None` e não `optout=MagicMock(...)` no default: default mutável é
    # avaliado UMA vez, na definição da função — o mesmo mock era compartilhado por
    # todos os testes que não passam o seu, e `assert_not_called` de um passava a
    # depender da ORDEM em que os outros rodaram.
    optout = optout if optout is not None else MagicMock(return_value=True)
    fake = _FakeSupabase(rows={"follow_up_jobs": jobs})
    with (
        patch("app.follow_up.service.get_supabase", return_value=fake),
        patch("app.campaigns.worker.handle_optout_reply", optout),
        patch("app.leads.service.get_lead", return_value={"id": "lead-1", "phone": "55…"}),
        patch("app.follow_up.service.emit_event"),
    ):
        resultado = S.processar_resposta_joao(
            "lead-1", texto, conversation_id="conv-1", now=NOW)
    return resultado, fake, optout


def test_ainda_tenho_estoque_adia_60_dias_sem_recomecar():
    """Ata 41:40 — adia 60 dias, e NÃO recomeça a contagem.

    Recomeçar devolveria a cadência ao toque 1, e o lead que disse "ainda tenho
    estoque" releria o texto que já leu.
    """
    jobs = _pendentes_e_enviados()
    # os dois pendentes estão espaçados em 15 dias na matrícula
    jobs[1]["fire_at"] = (NOW + timedelta(days=1)).isoformat()
    jobs[2]["fire_at"] = (NOW + timedelta(days=16)).isoformat()

    antigos = {j["id"]: datetime.fromisoformat(j["fire_at"]) for j in jobs}

    resultado, fake, _ = _responder("Ainda tenho estoque", jobs)

    assert resultado == C.RESPOSTA_ADIAR
    atualizados = {filtros[0][2]: payload for _, payload, filtros in fake.updates}
    assert set(atualizados) == {"job-reposicao-2-pending", "job-reposicao-3-pending"}, \
        "só os toques que AINDA NÃO saíram são adiados — o toque 1 já foi lido"
    for job_id, payload in atualizados.items():
        novo = datetime.fromisoformat(payload["fire_at"])
        assert novo >= antigos[job_id] + C.ADIAMENTO_ESTOQUE
        assert S.is_within_business_window(novo)
    # o bloco inteiro DESLIZA — a ordem (e portanto a contagem) não recomeça
    assert (datetime.fromisoformat(atualizados["job-reposicao-3-pending"]["fire_at"])
            > datetime.fromisoformat(atualizados["job-reposicao-2-pending"]["fire_at"]))
    assert not fake.inserts, "adiar nunca cria toque novo"


def _job_de_mover_existente(cadencia, sequence, status, **kw):
    """Um job de MOVER já gravado, na forma que o agendador cria."""
    job = _job_existente(cadencia, sequence, status, **kw)
    job["id"] = f"job-{cadencia}-mover-{status}"
    del job["metadata"]["toque"]          # o move não é toque
    job["metadata"].update({
        "acao": "mover_etapa", "etapa_final_key": "em_atencao", "template_name": None,
    })
    return job


def test_o_job_de_mover_desliza_junto_com_a_matricula_adiada():
    """"Ainda tenho estoque" adia os toques — e o move TEM de ir junto.

    Se ficasse parado, o card seria empurrado para "Em atenção" no meio de uma cadência
    adiada em 60 dias: a esteira voltaria a falar com um lead que o CRM já tinha
    marcado como abandonado. Não custa regra nenhuma porque o move carrega o mesmo
    `matricula_id` e uma `sequence` maior que a do último toque — `adiar_toques` o trata
    como mais um item do bloco que desliza.
    """
    nasceu = NOW
    jobs = [
        _job_existente("novo", 1, "sent", sent_at=nasceu.isoformat(), created_at=nasceu),
        _job_existente("novo", 2, "pending", created_at=nasceu),
        _job_existente("novo", 3, "pending", created_at=nasceu),
        _job_de_mover_existente("novo", 4, "pending", created_at=nasceu),
    ]
    jobs[1]["fire_at"] = (NOW + timedelta(days=2)).isoformat()
    jobs[2]["fire_at"] = (NOW + timedelta(days=4)).isoformat()
    jobs[3]["fire_at"] = (NOW + timedelta(days=5)).isoformat()

    resultado, fake, _ = _responder("Ainda tenho estoque", jobs)

    assert resultado == C.RESPOSTA_ADIAR
    atualizados = {filtros[0][2]: payload for _, payload, filtros in fake.updates}
    assert "job-novo-mover-pending" in atualizados, "o move ficou para trás"
    movido = datetime.fromisoformat(atualizados["job-novo-mover-pending"]["fire_at"])
    assert movido >= NOW + timedelta(days=5) + C.ADIAMENTO_ESTOQUE
    # e continua DEPOIS do último toque, que é o que o "mover no fim" significa
    assert movido > datetime.fromisoformat(atualizados["job-novo-3-pending"]["fire_at"])


def test_o_job_de_mover_e_cancelado_com_o_resto_no_optout():
    """Quem pediu para sair não recebe mais nada E não tem o card mexido.

    É o motivo de o move ser um JOB e não uma varredura à parte (spec 2026-09-23 §3):
    todo caminho que já cancela os `pending` da matrícula — o opt-out daqui e o
    `client_replied` do `webhook/meta_router.py` — cancela o move de graça.
    """
    mover = _job_de_mover_existente("novo", 4, "pending")
    jobs = [_job_existente("novo", 1, "sent", sent_at=NOW.isoformat()), mover]

    resultado, fake, _ = _responder("Parar mensagens", jobs)

    assert resultado == C.RESPOSTA_OPTOUT
    cancelados = [
        valor
        for _, payload, filtros in fake.updates if payload.get("status") == "cancelled"
        for _op, coluna, valor in filtros if coluna == "id"
    ]
    assert cancelados and mover["id"] in cancelados[0]


def test_botao_de_saida_reusa_handle_optout_reply():
    """Opt-out REAL — blacklist, não só "para de tocar". A autoridade é uma só."""
    optout = MagicMock(return_value=True)
    resultado, fake, _ = _responder("Parar mensagens", _pendentes_e_enviados(),
                                    optout=optout)

    assert resultado == C.RESPOSTA_OPTOUT
    optout.assert_called_once()
    cancelados = [p for _, p, _ in fake.updates if p.get("status") == "cancelled"]
    assert cancelados and cancelados[0]["cancel_reason"] == C.RESPOSTA_OPTOUT


def test_texto_comum_adia_3_dias_em_vez_de_60():
    """O TERCEIRO ramo (spec 2026-09-25 §3.3). Este teste AFIRMAVA o contrário.

    Até 24/09 ele se chamava `test_texto_comum_nao_mexe_em_nada` e exigia
    `resultado is None` com zero updates — e estava certo para o desenho de então, em
    que quem reagia à resposta comum era o `cancel_followups_by_phone` do webhook,
    MATANDO a esteira. Com a morte fora do caminho, "não fazer nada aqui" viraria "não
    fazer nada em lugar nenhum": o toque seguinte sairia por cima da conversa em
    andamento. Por isso a asserção virou do avesso.

    A IGUALDADE normalizada que o teste antigo protegia continua valendo, e é o que
    este aqui prova de forma mais forte: "ainda tenho estoque mas me manda a tabela" é
    um lead QUENTE, então ele leva os 3 dias da resposta comum e NÃO os 60 do botão.
    Se a comparação virasse substring um dia, este lead sumiria por 60 dias — e a
    asserção de distância abaixo fica vermelha.
    """
    jobs = _pendentes_e_enviados()
    jobs[1]["fire_at"] = (NOW + timedelta(days=1)).isoformat()
    jobs[2]["fire_at"] = (NOW + timedelta(days=16)).isoformat()
    antigos = {j["id"]: datetime.fromisoformat(j["fire_at"]) for j in jobs}

    resultado, fake, optout = _responder(
        "ainda tenho estoque mas me manda a tabela", jobs)

    assert resultado == C.RESPOSTA_ADIAR
    optout.assert_not_called()  # texto comum NUNCA vira blacklist
    assert not fake.inserts, "adiar nunca cria toque novo"

    atualizados = {filtros[0][2]: payload for _, payload, filtros in fake.updates}
    assert set(atualizados) == {"job-reposicao-2-pending", "job-reposicao-3-pending"},         "só os toques que AINDA NÃO saíram deslizam — o toque 1 já foi lido"
    for job_id, payload in atualizados.items():
        novo = datetime.fromisoformat(payload["fire_at"])
        assert novo >= antigos[job_id] + C.ADIAMENTO_RESPOSTA
        # a distância do BOTÃO não pode ser aplicada aqui: sobra a folga da janela
        # comercial (fim de semana), nunca 57 dias a mais.
        assert novo < antigos[job_id] + C.ADIAMENTO_ESTOQUE
        assert S.is_within_business_window(novo)


def test_lead_sem_matricula_aberta_e_noop():
    """O escopo é a cadência do João. O público da ValerIA continua arbitrado pelo LLM
    (escada Anchor-Disrupt-Ask) e pelo caminho determinístico já existente no
    `buffer/processor.py` — este gancho não pode blacklistar por cima deles."""
    optout = MagicMock(return_value=True)
    resultado, fake, _ = _responder("Parar mensagens", [], optout=optout)
    assert resultado is None
    optout.assert_not_called()
    assert fake.updates == []


# ═══════════════════════════════════════════════════════════════════════════════
# 7.1 O RECORTE DO `client_replied` — e o fim da corrida (spec 2026-09-25 §3.2)
# ═══════════════════════════════════════════════════════════════════════════════
#
# A seção 7 pergunta "o que `processar_resposta_joao` faz". Esta pergunta outra coisa:
# **ele chega a ser chamado com alguma coisa na mão?**
#
# Até 24/09 a resposta era não, e esse era o defeito C. Dois caminhos reagiam à mesma
# resposta do lead, e um corria contra o outro:
#
#   `cancel_followups_by_phone(reason="client_replied")` — background task registrada
#       na INGESTÃO do webhook (`meta_router.py`), milissegundos após a resposta HTTP;
#   `processar_resposta_joao` — alcançado por `fire_trigger("message_received")`
#       (`buffer/processor.py`), DEPOIS do debounce do buffer e como `create_task`
#       não aguardado.
#
# O primeiro sempre chegava antes. Quando o segundo rodava, todos os jobs já estavam
# `cancelled`, ele saía no `if not pendentes: return None` e não fazia nada — e foi por
# isso que o botão "ainda tenho estoque" NUNCA adiou 60 dias em produção. Botão vivo na
# tela, morto no efeito, a mesma classe de defeito do rótulo que não casa.
#
# O recorte não faz o segundo ganhar a corrida. Ele tira o primeiro da pista.


class _TabelaDeVerdade:
    """Uma tabela que APLICA os filtros, em vez de só registrá-los.

    O `_FakeTable` do topo deste arquivo devolve `rows` fixas e guarda o que foi pedido
    — perfeito para afirmar "o código pediu X", inútil para a pergunta desta seção, que
    é **o que SOBRA na tabela depois**. Aqui o `not_.in_("job_type", ...)` tem de
    EXECUTAR: ele é o recorte inteiro, e um dublê que o ignorasse aprovaria alegremente
    a mutação que preserva em todos os motivos.
    """

    def __init__(self, banco, nome):
        self.banco = banco
        self.nome = nome
        self.op = "select"
        self.payload = None
        self.dentro: list = []   # o que `eq`/`in_` exigem
        self.fora: list = []     # o que o `not_.in_` exclui
        self._negando = False

    def select(self, *a, **k):
        self.op = "select"
        return self

    def eq(self, col, val):
        self.dentro.append((col, [val]))
        self._negando = False
        return self

    def in_(self, col, vals):
        (self.fora if self._negando else self.dentro).append((col, list(vals)))
        self._negando = False
        return self

    @property
    def not_(self):
        self._negando = True
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def gte(self, *a):
        return self

    def lte(self, *a):
        return self

    def lt(self, *a):
        return self

    def single(self):
        return self

    def insert(self, rows):
        self.op = "insert"
        self.payload = rows
        self.banco.inserts.append((self.nome, rows))
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def _casa(self, linha):
        for col, vals in self.dentro:
            if linha.get(col) not in vals:
                return False
        for col, vals in self.fora:
            if linha.get(col) in vals:
                return False
        return True

    def execute(self):
        if self.op == "insert":
            return SimpleNamespace(data=self.payload)
        linhas = self.banco.tabelas.get(self.nome, [])
        casam = [linha for linha in linhas if self._casa(linha)]
        if self.op == "update":
            for linha in casam:
                linha.update(self.payload)
        return SimpleNamespace(data=[dict(linha) for linha in casam])


class _Banco:
    """`follow_up_jobs` + `leads` + `conversations` em memória, com estado de verdade."""

    LEAD = "lead-1"
    PHONE = "5534988861441"
    CONVERSA = "conv-1"

    def __init__(self, jobs):
        self.tabelas = {
            "leads": [{"id": self.LEAD, "phone": self.PHONE, "bsuid": None}],
            "conversations": [{"id": self.CONVERSA, "lead_id": self.LEAD}],
            "follow_up_jobs": [dict(j) for j in jobs],
        }
        self.inserts: list = []

    def table(self, nome):
        return _TabelaDeVerdade(self, nome)

    def rpc(self, nome, args):  # pragma: no cover - esta seção não varre funil
        raise AssertionError(f"esta seção não deveria chamar a RPC {nome}")

    # ── leitura, para as asserções ──────────────────────────────────────
    def jobs(self):
        return self.tabelas["follow_up_jobs"]

    def por_id(self, job_id):
        return next(j for j in self.jobs() if j["id"] == job_id)

    def pendentes(self):
        return [j for j in self.jobs() if j["status"] == "pending"]

    def pendentes_do_joao(self):
        return [j for j in self.pendentes() if j["job_type"] in C.JOB_TYPES]


def _job_na_conversa(*args, **kwargs):
    """`_job_existente` + a `conversation_id` — que é por onde o cancelamento por
    TELEFONE encontra o job (ele vai de leads → conversations → follow_up_jobs)."""
    job = _job_existente(*args, **kwargs)
    job["conversation_id"] = _Banco.CONVERSA
    job["cancel_reason"] = None
    return job


def _job_da_valeria(job_id="job-standard"):
    """Um toque do caminho `standard` da ValerIA. Não é decoração: metade do recorte é
    o que ele CONTINUA sofrendo — lá responder cancela mesmo, porque aquela cadência
    existe justamente porque o lead sumiu."""
    return {
        "id": job_id, "lead_id": _Banco.LEAD, "conversation_id": _Banco.CONVERSA,
        "job_type": "standard", "status": "pending", "sequence": 1,
        "sent_at": None, "fire_at": (NOW + timedelta(hours=2)).isoformat(),
        "created_at": NOW.isoformat(), "metadata": {}, "cancel_reason": None,
    }


def _cancelar_por_telefone(banco, reason, *, preserve_scheduled_return=True):
    with patch("app.follow_up.service.get_supabase", return_value=banco):
        S.cancel_followups_by_phone(
            _Banco.PHONE, reason=reason,
            preserve_scheduled_return=preserve_scheduled_return)


def _processar_resposta(banco, texto, *, optout=None):
    optout = optout if optout is not None else MagicMock(return_value=True)
    with (
        patch("app.follow_up.service.get_supabase", return_value=banco),
        patch("app.campaigns.worker.handle_optout_reply", optout),
        patch("app.leads.service.get_lead",
              return_value={"id": _Banco.LEAD, "phone": _Banco.PHONE}),
        patch("app.follow_up.service.emit_event"),
    ):
        return S.processar_resposta_joao(
            _Banco.LEAD, texto, conversation_id=_Banco.CONVERSA, now=NOW)


# ── O teste da corrida ──────────────────────────────────────────────────
def test_depois_do_client_replied_ainda_HA_pendentes_do_joao():
    """O defeito C, em uma linha: ontem isto seria ZERO.

    Nenhum mock de ordem, nenhum `assert_called_with` — a pergunta é factual e o banco
    responde: depois do cancelamento que o webhook registra na ingestão, ainda existe
    trabalho `pending` para `processar_resposta_joao` encontrar?
    """
    banco = _Banco([
        _job_na_conversa("novo", 1, "sent", sent_at=NOW.isoformat()),
        _job_na_conversa("novo", 2, "pending"),
        _job_na_conversa("novo", 3, "pending"),
    ])

    _cancelar_por_telefone(banco, "client_replied")

    assert len(banco.pendentes_do_joao()) == 2, (
        "o cancelamento da ingestão esvaziou a esteira do João de novo — "
        "`processar_resposta_joao` vai chegar e não achar nada para adiar, "
        "que é exatamente o defeito C")


def test_o_botao_ainda_tenho_estoque_volta_a_existir_de_ponta_a_ponta():
    """Os DOIS caminhos, na ORDEM REAL em que a produção os executa, no mesmo banco.

    É a demonstração de que o botão deixou de ser morto: o cancelamento da ingestão roda
    primeiro (como sempre rodou) e o handler ainda assim consegue aplicar os 60 dias.
    Antes do recorte, este teste falharia já no `resultado`, que seria `None`.
    """
    fire_2 = NOW + timedelta(days=2)
    fire_3 = NOW + timedelta(days=4)
    jobs = [
        _job_na_conversa("novo", 1, "sent", sent_at=NOW.isoformat()),
        _job_na_conversa("novo", 2, "pending"),
        _job_na_conversa("novo", 3, "pending"),
    ]
    jobs[1]["fire_at"] = fire_2.isoformat()
    jobs[2]["fire_at"] = fire_3.isoformat()
    banco = _Banco(jobs)

    # 1) o que o webhook faz na ingestão, milissegundos depois da resposta HTTP
    _cancelar_por_telefone(banco, "client_replied")
    # 2) o que o buffer faz depois do debounce
    resultado = _processar_resposta(banco, "Ainda tenho estoque")

    assert resultado == C.RESPOSTA_ADIAR
    assert banco.por_id("job-novo-2-pending")["status"] == "pending"
    for job_id, antes in (("job-novo-2-pending", fire_2),
                          ("job-novo-3-pending", fire_3)):
        novo = datetime.fromisoformat(banco.por_id(job_id)["fire_at"])
        assert novo >= antes + C.ADIAMENTO_ESTOQUE, (
            f"{job_id} não foi adiado em 60 dias — o botão continua morto")


# ── O teste do recorte ─────────────────────────────────────────────────
def test_client_replied_preserva_o_joao_e_cancela_o_standard_da_valeria():
    """As duas metades do recorte na MESMA chamada — porque é junto que elas se provam.

    Um teste que olhasse só o João passaria com um `return` no início da função; um que
    olhasse só o `standard` passaria sem recorte nenhum.
    """
    banco = _Banco([
        _job_na_conversa("em_conversa", 2, "pending"),
        _job_da_valeria(),
    ])

    _cancelar_por_telefone(banco, "client_replied")

    joao = banco.por_id("job-em_conversa-2-pending")
    valeria = banco.por_id("job-standard")
    assert joao["status"] == "pending", (
        "responder deixou de MATAR a esteira do João — quem decide o que uma resposta "
        "faz com ela é `processar_resposta_joao`, e ele ADIA")
    assert valeria["status"] == "cancelled", (
        "o caminho `standard` da ValerIA não muda em linha nenhuma: lá responder "
        "continua cancelando, porque aquela cadência existe porque o lead sumiu")
    assert valeria["cancel_reason"] == "client_replied"


@pytest.mark.parametrize("reason,preserve", [
    ("handoff", False),                    # agent/tools.py::encaminhar_humano
    ("sem_interesse_atual", False),        # agent/tools.py
    ("cliente_ativo_sem_demanda", False),  # agent/tools.py
    ("lead_already_served", True),         # agent/tools.py
    ("optout", False),                     # leads/service.py::apply_optout_side_effects
    ("optout_botao", False),               # idem, pelo botão do template
    ("block_manual", False),               # idem, pelo botão "Bloquear" do CRM
])
def test_motivo_terminal_continua_cancelando_o_joao(reason, preserve):
    """O recorte é do `client_replied`, e de mais NENHUM motivo.

    Este é o backstop de 15/07: o cliente pediu ao HUMANO para a IA parar, e os toques
    seguiram saindo. Transformar o recorte em "preserva sempre" reabriria aquele
    incidente pela porta dos fundos — e o custo não é um toque a mais, é mensagem de
    marketing para quem já pediu para sair, com o botão "Bloquear" e a reputação do
    número na Meta do outro lado.
    """
    banco = _Banco([
        _job_na_conversa("em_conversa", 2, "pending"),
        _job_na_conversa("em_conversa", 3, "pending"),
    ])

    _cancelar_por_telefone(banco, reason, preserve_scheduled_return=preserve)

    assert banco.pendentes_do_joao() == [], (
        f"motivo {reason!r} é uma parada TERMINAL e deixou toque do João vivo")
    assert all(j["cancel_reason"] == reason for j in banco.jobs())


def test_o_handoff_rescue_continua_preservado_no_client_replied():
    """O recorte ACRESCENTA ao que já era preservado, nunca substitui.

    `handoff_rescue` (aviso ao vendedor) e `ai_scheduled_return` (retorno que a própria
    IA prometeu) sobreviviam ao `client_replied` desde 30/06. Uma implementação que
    trocasse a lista em vez de estendê-la passaria em todos os testes acima e quebraria
    aqueles dois em silêncio.
    """
    banco = _Banco([
        _job_da_valeria("job-rescue"), _job_da_valeria("job-retorno"),
        _job_na_conversa("novo", 2, "pending"),
    ])
    banco.por_id("job-rescue")["job_type"] = "handoff_rescue"
    banco.por_id("job-retorno")["job_type"] = "ai_scheduled_return"

    _cancelar_por_telefone(banco, "client_replied")

    assert banco.por_id("job-rescue")["status"] == "pending"
    assert banco.por_id("job-retorno")["status"] == "pending"
    assert banco.por_id("job-novo-2-pending")["status"] == "pending"


def test_o_recorte_cobre_TODAS_as_cadencias_do_joao():
    """A lista de preservados sai de `cadence_joao.JOB_TYPES`, que é DERIVADA de `FUNIS`.

    Uma lista escrita à mão envelheceria calada: `joao_proposta` nasceu em 23/09 e uma
    cópia de 18/09 o teria deixado de fora — a esteira de Proposta Enviada seria a única
    a continuar morrendo quando o lead responde, e ninguém notaria.
    """
    preservados = set(S._preserved_job_types(True, "client_replied"))
    assert C.JOB_TYPES <= preservados, C.JOB_TYPES - preservados
    assert "standard" not in preservados


def test_sem_motivo_declarado_o_joao_NAO_e_preservado():
    """`reason` ganhou default — e o default cai no lado seguro.

    O único chamador de produção sempre passa o motivo; o default existe para quem
    chama a função direto (a suíte do backstop de 15/07 é quem faz isso). Se ele
    preservasse, a mutação proibida — "preserva sempre" — estaria escrita na
    ASSINATURA, onde nenhum dos testes de motivo terminal acima a pegaria.
    """
    assert S._preserved_job_types(True) == ["handoff_rescue", "ai_scheduled_return"]
    assert not (C.JOB_TYPES & set(S._preserved_job_types(False)))


# ── Continuidade: a esteira CONTINUA, não recomeça ────────────────────────────
def test_lead_que_responde_no_toque_2_mantem_os_toques_3_e_4_da_MESMA_matricula():
    """O defeito B, medido de ponta a ponta: continuar de onde parou é o que dá TETO.

    O desenho antigo cancelava tudo, e o cooldown por matrícula de 23/09 liberava a
    reentrada ~2 dias depois — DO TOQUE 1. O lead relia as mesmas mensagens e cada volta
    reiniciava a contagem, então não havia teto: quem responde a cada 3 dias ficava em
    laço permanente e nunca chegava a "Em Atenção".

    A asserção que carrega esse peso é a do `matricula_id`: o toque 3 e o toque 4 têm de
    ser OS MESMOS jobs, da MESMA matrícula. Uma implementação que cancelasse e
    rematriculasse também deixaria dois `pending` na tabela — e seria o laço de volta.
    """
    fire_3 = NOW + timedelta(days=30)
    fire_4 = NOW + timedelta(days=45)
    nasceu = NOW - timedelta(days=45)
    jobs = [
        _job_na_conversa("reposicao", 1, "sent", matricula="m-unica", created_at=nasceu,
                         sent_at=(NOW - timedelta(days=30)).isoformat()),
        _job_na_conversa("reposicao", 2, "sent", matricula="m-unica", created_at=nasceu,
                         sent_at=NOW.isoformat()),
        _job_na_conversa("reposicao", 3, "pending", matricula="m-unica",
                         created_at=nasceu),
        _job_na_conversa("reposicao", 4, "pending", matricula="m-unica",
                         created_at=nasceu, ultimo=True),
    ]
    jobs[2]["fire_at"] = fire_3.isoformat()
    jobs[3]["fire_at"] = fire_4.isoformat()
    banco = _Banco(jobs)

    _cancelar_por_telefone(banco, "client_replied")
    resultado = _processar_resposta(banco, "opa, me manda a tabela de preços")

    assert resultado == C.RESPOSTA_ADIAR
    assert not banco.inserts, "matrícula NOVA é o laço de volta — esta CONTINUA"

    sobreviventes = {j["id"]: j for j in banco.pendentes_do_joao()}
    assert set(sobreviventes) == {"job-reposicao-3-pending", "job-reposicao-4-pending"}
    assert {j["metadata"]["matricula_id"] for j in sobreviventes.values()} == {"m-unica"}

    for job_id, antes in (("job-reposicao-3-pending", fire_3),
                          ("job-reposicao-4-pending", fire_4)):
        novo = datetime.fromisoformat(sobreviventes[job_id]["fire_at"])
        assert novo >= antes + C.ADIAMENTO_RESPOSTA, f"{job_id} não esperou os 3 dias"
        assert novo < antes + C.ADIAMENTO_ESTOQUE, (
            f"{job_id} levou o adiamento do BOTÃO — texto comum não some por 60 dias")

    # e a ordem entre eles — o bloco DESLIZA, ele não é reescrito
    assert (datetime.fromisoformat(sobreviventes["job-reposicao-4-pending"]["fire_at"])
            > datetime.fromisoformat(sobreviventes["job-reposicao-3-pending"]["fire_at"]))
    # e os dois que já saíram não voltam: o lead não relê o que já leu
    assert banco.por_id("job-reposicao-1-sent")["status"] == "sent"
    assert banco.por_id("job-reposicao-2-sent")["status"] == "sent"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Onde isto se liga ao que já roda
# ═══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_o_tick_de_automacao_chama_o_agendador():
    from app.automation import triggers as T

    with (
        patch("app.automation.triggers.get_supabase", return_value=MagicMock()),
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]),
        patch("app.automation.triggers.agendar_cadencias_joao") as mock_agendar,
    ):
        await T.check_polling_triggers(NOW)
    mock_agendar.assert_called_once()


@pytest.mark.asyncio
async def test_falha_do_agendador_nao_derruba_o_tick():
    from app.automation import triggers as T

    with (
        patch("app.automation.triggers.get_supabase", return_value=MagicMock()),
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]),
        patch("app.automation.triggers.agendar_cadencias_joao",
              side_effect=RuntimeError("boom")),
    ):
        await T.check_polling_triggers(NOW)  # não levanta


@pytest.mark.asyncio
async def test_inbound_do_lead_chega_na_cadencia_do_joao():
    """O gancho REUSADO: `fire_trigger('message_received')` já recebe o texto do lead
    (`buffer/processor.py` o dispara em todo inbound, ANTES do gate de canal humano —
    e o público do João está justamente atrás desse gate)."""
    from app.automation import triggers as T

    with (
        patch("app.automation.triggers.get_campaigns_with_trigger_type", return_value=[]),
        patch("app.automation.triggers.processar_resposta_joao") as mock_resposta,
    ):
        await T.fire_trigger("message_received", "lead-1",
                             {"body": "Ainda tenho estoque"})
    mock_resposta.assert_called_once()
    assert mock_resposta.call_args[0][0] == "lead-1"
    assert mock_resposta.call_args[0][1] == "Ainda tenho estoque"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. A sobreposição do banco, lida pelo agendador
# ═══════════════════════════════════════════════════════════════════════════════
def test_overrides_ausentes_valem_o_codigo():
    fake = _FakeSupabase(rows={"followup_joao_cadencia": [], "followup_joao_toque": []})
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        assert S.carregar_overrides_joao() == {}


def test_overrides_montam_a_forma_que_resolver_consome():
    """A PK das duas tabelas mudou no Lote 1: `(funil, cadencia)` e
    `(funil, cadencia, toque)` — sem coluna `linha`. A forma devolvida acompanha:
    `{funil: {codigo: {gatilho_dias, ativa, toques}}}`."""
    fake = _FakeSupabase(rows={
        "followup_joao_cadencia": [
            {"funil": "reposicao_atacado", "cadencia": "reposicao",
             "gatilho_dias": 60, "ativa": True}],
        "followup_joao_toque": [
            {"funil": "reposicao_atacado", "cadencia": "reposicao", "toque": 2,
             "dias": 20, "template_name": None}],
    })
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        overrides = S.carregar_overrides_joao()

    assert overrides["reposicao_atacado"]["reposicao"]["gatilho_dias"] == 60
    assert overrides["reposicao_atacado"]["reposicao"]["ativa"] is True
    assert overrides["reposicao_atacado"]["reposicao"]["toques"][2]["dias"] == 20


def test_overrides_de_par_invalido_sao_ignorados():
    """`(funil, cadencia)` que não existe em `cj.FUNIS` (ex. `atacado`/`reposicao`, ou
    qualquer par com `funil="recuperacao"`) é descartado — mesma trava que o CHECK do
    banco impõe, replicada aqui para o caso de a tabela ser editada por fora do CRM."""
    fake = _FakeSupabase(rows={
        "followup_joao_cadencia": [
            {"funil": "atacado", "cadencia": "reposicao",  # par inválido
             "gatilho_dias": 10, "ativa": True},
            {"funil": "recuperacao", "cadencia": "novo",  # recuperacao não tem par
             "gatilho_dias": 5, "ativa": True},
        ],
        "followup_joao_toque": [
            {"funil": "atacado", "cadencia": "reposicao", "toque": 1,
             "dias": 1, "template_name": "x"},
        ],
    })
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        overrides = S.carregar_overrides_joao()

    assert overrides == {}


def test_tabela_ausente_desliga_tudo_em_vez_de_ligar():
    """A migration NÃO é aplicada pelo deploy (é a decisão da Task J1). Até que um
    humano a rode, a leitura falha — e falhar para o lado de "desligado" é a única
    falha segura: o outro lado seriam 888 templates."""
    fake = _FakeSupabase(tabelas_quebradas={"followup_joao_cadencia"})
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        assert S.carregar_overrides_joao() == {}
