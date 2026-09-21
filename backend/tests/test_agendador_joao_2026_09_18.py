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


def _overrides(**por_cadencia):
    """`{"reposicao": {"ativa": True}}` → o formato que o agendador consome."""
    return dict(por_cadencia)


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
    """A trava a montante: sem linha no banco, `resolver(...).ativa` é False em todas."""
    for codigo in C.CODIGOS:
        for linha in C.LINHAS:
            assert C.resolver(codigo, linha).ativa is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. A varredura reusa a RPC que já tem as guardas
# ═══════════════════════════════════════════════════════════════════════════════
def test_varredura_usa_a_rpc_get_deals_stage_stagnant():
    """Nenhuma consulta nova: a RPC já traz blacklist, número errado e conversa
    finalizada no próprio WHERE (20260904_esteiras_vendedor.sql)."""
    fake = _FakeSupabase(rpc_rows=[])
    _rodar(fake, _overrides(novo={"ativa": True}))

    assert fake.rpcs, "a cadência ligada tem de varrer"
    nomes = {nome for nome, _ in fake.rpcs}
    assert nomes == {"get_deals_stage_stagnant"}


def test_parametros_da_rpc_saem_da_cadencia_resolvida():
    fake = _FakeSupabase(rpc_rows=[])
    _rodar(fake, _overrides(novo={"ativa": True}), teto=7)

    args_por_pipeline = {a["p_pipeline_id"]: a for _, a in fake.rpcs}
    assert set(args_por_pipeline) == {C.PIPELINE_ATACADO, C.PIPELINE_PRIVATE_LABEL}
    args = args_por_pipeline[C.PIPELINE_ATACADO]
    assert args["p_stage_key"] == "novo"
    assert args["p_stage_id"] is None
    assert args["p_stage_days"] == 2          # gatilho da ata (01:07:10)
    assert args["p_limit"] == 7               # o teto vai JUNTO para o banco
    assert args["p_channel_id"] == JOAO_CHANNEL["id"]
    assert args["p_audience"] == S.JOAO_CADENCIA_AUDIENCIA


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
    _rodar(fake, _overrides(em_conversa={"ativa": True}))

    jobs = _jobs_criados(fake)
    # 7 toques (ata 41:02) × 2 linhas — mas o mesmo card volta em cada varredura de
    # linha porque o dublê devolve a mesma linha para os dois funis.
    da_linha = [j for j in jobs if j["metadata"]["linha"] == C.LINHA_ATACADO]
    assert len(da_linha) == 7
    assert [j["metadata"]["toque"] for j in da_linha] == [1, 2, 3, 4, 5, 6, 7]


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
    assert md["linha"] in C.LINHAS
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

    da_linha = [j for j in _jobs_criados(fake)
                if j["metadata"]["linha"] == C.LINHA_ATACADO]
    assert [j["metadata"]["ultimo_toque"] for j in da_linha] == [False, False, False, True]


def test_fire_at_sai_dos_offsets_e_respeita_a_janela_comercial():
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()])
    _rodar(fake, _overrides(em_conversa={"ativa": True}))

    da_linha = [j for j in _jobs_criados(fake)
                if j["metadata"]["linha"] == C.LINHA_ATACADO]
    fire = [datetime.fromisoformat(j["fire_at"]) for j in da_linha]
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

    da_linha = [j for j in _jobs_criados(fake)
                if j["metadata"]["linha"] == C.LINHA_ATACADO]
    assert datetime.fromisoformat(da_linha[1]["fire_at"]) == NOW + timedelta(days=30)


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
    assert _rodar(fake, _overrides(novo={"ativa": True})) > 0


def test_cooldown_impede_a_cadencia_de_recomecar_sozinha():
    """O defeito que a RPC documenta em 20260904: o card não sai da etapa quando a
    cadência acaba, então na varredura seguinte ele é elegível de novo — um template a
    cada poucos dias, para sempre."""
    concluido = _job_existente(
        "novo", 1, "sent", ultimo=True,
        sent_at=(NOW - timedelta(days=3)).isoformat(),
        created_at=NOW - timedelta(days=3))
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()], rows={"follow_up_jobs": [concluido]})
    assert _rodar(fake, _overrides(novo={"ativa": True})) == 0


def test_passado_o_cooldown_o_card_pode_reentrar():
    """Card que sai da etapa e volta meses depois é oportunidade legítima — mesma
    doutrina do `p_cooldown_days` da RPC (exclusão temporária, não permanente)."""
    antigo = _job_existente(
        "novo", 1, "sent", ultimo=True,
        sent_at=(NOW - timedelta(days=200)).isoformat(),
        created_at=NOW - timedelta(days=200))
    fake = _FakeSupabase(rpc_rows=[_linha_rpc()], rows={"follow_up_jobs": [antigo]})
    assert _rodar(fake, _overrides(novo={"ativa": True})) > 0


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
    _rodar(fake, _overrides(novo={"ativa": True}), teto=2)

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
    rep = S.resolver_para_agendar("reposicao", C.LINHA_ATACADO,
                                  {"ativa": True})
    ate = S.resolver_para_agendar("em_atencao", C.LINHA_ATACADO,
                                  {"ativa": True})
    motivo_rep = S.motivo_para_pular_joao(rep, jobs, NOW)
    motivo_ate = S.motivo_para_pular_joao(ate, jobs, NOW)

    assert not (motivo_rep is None and motivo_ate is None), (
        f"os dois gatilhos elegíveis no mesmo card: rep={motivo_rep} ate={motivo_ate}"
    )


def test_em_atencao_ignora_card_que_nunca_passou_pela_reposicao():
    """"90 dias parado" isolado NÃO é "Em atenção": a ata (38:08) descreve o estado
    de quem já esgotou a régua de Reposição, não de quem nunca entrou nela."""
    ate = S.resolver_para_agendar("em_atencao", C.LINHA_ATACADO, {"ativa": True})
    assert S.motivo_para_pular_joao(ate, [], NOW) == "reposicao_nao_concluida"


def test_em_atencao_pega_o_card_que_esgotou_a_reposicao():
    ate = S.resolver_para_agendar("em_atencao", C.LINHA_ATACADO, {"ativa": True})
    assert S.motivo_para_pular_joao(ate, _REPOSICAO_CONCLUIDA_ONTEM, NOW) is None


def test_reposicao_nao_volta_ao_card_que_ja_a_esgotou():
    rep = S.resolver_para_agendar("reposicao", C.LINHA_ATACADO, {"ativa": True})
    assert (S.motivo_para_pular_joao(rep, _REPOSICAO_CONCLUIDA_HA_MUITO, NOW)
            == "reposicao_ja_concluida")


def test_em_atencao_repete_respeitando_o_intervalo():
    """Ata 38:08: "uma mensagem a cada três dias até ele falar que não quer"."""
    base = list(_REPOSICAO_CONCLUIDA_ONTEM)
    ate = S.resolver_para_agendar("em_atencao", C.LINHA_ATACADO, {"ativa": True})

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
    da_linha = [j for j in _jobs_criados(fake)
                if j["metadata"]["linha"] == C.LINHA_ATACADO]
    assert len(da_linha) == 1
    assert da_linha[0]["metadata"]["ultimo_toque"] is False  # nunca termina


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


def _responder(texto, jobs, *, optout=MagicMock(return_value=True)):
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


def test_botao_de_saida_reusa_handle_optout_reply():
    """Opt-out REAL — blacklist, não só "para de tocar". A autoridade é uma só."""
    optout = MagicMock(return_value=True)
    resultado, fake, _ = _responder("Parar mensagens", _pendentes_e_enviados(),
                                    optout=optout)

    assert resultado == C.RESPOSTA_OPTOUT
    optout.assert_called_once()
    cancelados = [p for _, p, _ in fake.updates if p.get("status") == "cancelled"]
    assert cancelados and cancelados[0]["cancel_reason"] == C.RESPOSTA_OPTOUT


def test_texto_comum_nao_mexe_em_nada():
    """IGUALDADE normalizada, nunca substring: "ainda tenho estoque mas quero ver a
    tabela" é um lead QUENTE, e adiar 60 dias seria perdê-lo."""
    resultado, fake, optout = _responder(
        "ainda tenho estoque mas me manda a tabela", _pendentes_e_enviados())
    assert resultado is None
    assert fake.updates == [] and fake.inserts == []
    optout.assert_not_called()


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
    fake = _FakeSupabase(rows={
        "followup_joao_cadencia": [
            {"cadencia": "reposicao", "gatilho_dias": 60, "ativa": True}],
        "followup_joao_toque": [
            {"cadencia": "reposicao", "linha": "atacado", "toque": 2,
             "dias": 20, "template_name": None}],
    })
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        overrides = S.carregar_overrides_joao()

    assert overrides["reposicao"]["gatilho_dias"] == 60
    assert overrides["reposicao"]["ativa"] is True
    assert overrides["reposicao"]["linhas"]["atacado"]["toques"][2]["dias"] == 20


def test_tabela_ausente_desliga_tudo_em_vez_de_ligar():
    """A migration NÃO é aplicada pelo deploy (é a decisão da Task J1). Até que um
    humano a rode, a leitura falha — e falhar para o lado de "desligado" é a única
    falha segura: o outro lado seriam 888 templates."""
    fake = _FakeSupabase(tabelas_quebradas={"followup_joao_cadencia"})
    with patch("app.follow_up.service.get_supabase", return_value=fake):
        assert S.carregar_overrides_joao() == {}
