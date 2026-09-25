"""Handler dos toques do João no scheduler de follow-up (Task J2, 2026-09-18).

O lead do João está em SILÊNCIO por definição — a janela de 24h da Meta está fechada —
então o toque dele é SEMPRE template aprovado, NUNCA texto gerado por LLM. É a única
diferença de fundo entre este handler e os da ValerIA, e é o que estes testes provam.

O caminho `standard` da ValerIA é o único follow-up que funciona em produção (8.140 jobs
na história). O ponto de contato do ramo novo é só o despacho por `job_type` — os testes
de regressão aqui existem para que qualquer desvio do caminho dela fique vermelho.

FORMA DO JOB (contrato com a Task F1/F3, spec 2026-09-21):
    job_type: "joao_touch" (ou qualquer "joao_*" — o despacho é por prefixo)
    metadata: {
        "cadencia": "novo"|"em_conversa"|"reposicao"|"em_atencao",
        "funil": "atacado"|"private_label"|"reposicao_atacado"|"reposicao_private_label",
                                                   # opcional — cai p/ o funil do deal
        "toque": 1,                               # 1-based
        "template_name": "joao_novo_atacado_t1",  # OU "template_por_funil"
        "template_por_funil": {"atacado": "...", "private_label": "...", ...},
        "language_code": "pt_BR",                # default
        "template_variables": {...},             # default: {{1}} = primeiro nome
        "lead_phone": "...",                     # opcional — cai p/ leads.phone
        "deal_id": "...",                        # OBRIGATÓRIO desde 2026-09-25: é por
                                                 # ele que a etapa é relida no envio
        "pipeline_id": "...",                    # opcional, p/ resolver o funil
    }

A REGRA QUE GOVERNA A VIDA DA ESTEIRA (spec 2026-09-25 §2): ela vive enquanto o card
estiver na etapa vigiada. Mudança de etapa ENCERRA o toque, e a etapa vigiada vem da
CONFIG (`cadence_joao.cadencia_do_funil`), nunca do `metadata` — ver a seção "a esteira
vive enquanto o card estiver na etapa" no fim deste arquivo.

FORMA DO JOB DE MOVER (contrato E2↔E3, spec 2026-09-23 §3) — o ÚNICO job deste handler
que não manda mensagem nenhuma:
    job_type: o mesmo da cadência ("joao_novo" | "joao_em_conversa" | "joao_proposta")
    metadata: {
        "acao": "mover_etapa",            # A MARCA — ausente = job de toque normal
        "etapa_final_key": "em_atencao",  # a key da etapa de DESTINO
        "cadencia": "novo", "funil": "atacado",   # dizem qual etapa é a VIGIADA
        "matricula_id": "...", "deal_id": "...", "pipeline_id": "...",
        "template_name": None,
    }
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.follow_up import scheduler as S


NOW = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)

JOAO_CHANNEL = {
    "id": "ch-joao",
    "provider": "meta_cloud",
    "provider_config": {"phone_number_id": S.JOAO_PHONE_NUMBER_ID, "access_token": "tok-joao"},
}


def _joao_job(**over):
    """Job de toque do João no formato que `get_due_followups` devolve (joins inclusos).

    O par (funil, cadência) do default é REAL — `atacado`/`novo`, que vigia a etapa
    `novo` — e o `deal_id` está sempre presente, como o agendador grava. Desde a guarda
    de etapa (spec 2026-09-25 §3.1) isso deixou de ser cosmético: um par inexistente
    encerraria o toque fail-closed e um job sem `deal_id` seria cancelado, e todo teste
    de envio daqui viraria um teste de guarda sem que o nome dele dissesse isso.
    """
    metadata = {
        "cadencia": "novo",
        "funil": "atacado",
        "toque": 1,
        "template_name": "joao_novo_atacado_t1",
        "lead_phone": "5534988861441",
        "deal_id": "deal-1",
    }
    metadata.update(over.pop("metadata", {}))
    job = {
        "id": "job-joao-1",
        "job_type": "joao_touch",
        "conversation_id": "conv-joao",
        "lead_id": "lead-1",
        "channel_id": "ch-joao",
        "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5534988861441", "name": "Marcella Souza"},
        "channels": {"id": "ch-joao", "name": "João", "provider": "meta_cloud",
                     "provider_config": {"phone_number_id": S.JOAO_PHONE_NUMBER_ID,
                                         "access_token": "tok-joao"}, "mode": "human"},
        "conversations": {"id": "conv-joao", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": None},
        "metadata": metadata,
    }
    job.update(over)
    return job


def _meta(wamid="wamid.JOAO"):
    client = AsyncMock()
    client.send_template = AsyncMock(return_value={"messages": [{"id": wamid}]})
    return client


def _run_handler(job, *, meta=None, channel=JOAO_CHANNEL, sb=None, now=NOW, rendered="Oi Marcella, é o João"):
    """Executa `_process_joao_touch` com as bordas de I/O mockadas.

    `_generate_followup_message` é mockado com um side_effect que EXPLODE: nenhuma linha
    do caminho do João pode chamar o LLM.

    O banco default é o `_FakeSupabase` de verdade (definido mais abaixo, junto das
    etapas dos dois funis), com o card de `_joao_job` parado na etapa que a cadência
    vigia: desde a guarda de etapa, um MagicMock genérico faria toda leitura de card
    devolver "card sumiu" e nenhum toque sairia.
    """
    import asyncio

    meta = meta or _meta()
    sb = _db() if sb is None else sb
    calls = {}

    def _no_llm(*a, **k):
        raise AssertionError("o caminho do João NUNCA pode chamar o LLM")

    with patch("app.follow_up.scheduler.get_channel_by_provider_config", return_value=channel) as mock_ch, \
         patch("app.follow_up.scheduler.get_supabase", return_value=sb), \
         patch("app.follow_up.scheduler.MetaCloudClient", return_value=meta), \
         patch("app.follow_up.scheduler._generate_followup_message", new=AsyncMock(side_effect=_no_llm)), \
         patch("app.broadcast.worker._render_template_body", new=AsyncMock(return_value=rendered)), \
         patch("app.follow_up.scheduler.get_or_create_conversation", return_value={"id": "conv-joao"}), \
         patch("app.follow_up.scheduler.save_message_conv") as mock_save_msg, \
         patch("app.follow_up.scheduler._save_followup_wamid") as mock_wamid, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent, \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        calls.update(
            channel=mock_ch, save_msg=mock_save_msg, wamid=mock_wamid,
            sent=mock_sent, cancel=mock_cancel, meta=meta,
        )
        asyncio.run(S._process_joao_touch(job, now))
    return calls


# ─── o handler: envio por template aprovado, sem LLM ─────────────────────────

def test_handler_envia_template_do_toque_pelo_canal_do_joao():
    calls = _run_handler(_joao_job())

    calls["meta"].send_template.assert_awaited_once()
    kwargs = calls["meta"].send_template.await_args.kwargs
    args = calls["meta"].send_template.await_args.args
    assert args[0] == "5534988861441"
    assert args[1] == "joao_novo_atacado_t1"
    assert kwargs["language_code"] == "pt_BR"
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()


def test_handler_monta_os_componentes_do_template_com_o_primeiro_nome():
    """Reusa `broadcast/worker.py::_build_template_components` — os 24 templates do João
    têm UM param POSICIONAL ({{1}}), o primeiro nome do lead."""
    calls = _run_handler(_joao_job())

    components = calls["meta"].send_template.await_args.kwargs["components"]
    assert components == [{"type": "body", "parameters": [{"type": "text", "text": "Marcella"}]}]


def test_handler_nao_chama_llm_em_nenhum_ponto():
    """A janela está fechada: free-text seria rejeitado (#131047). O mock do LLM explode
    se for tocado — este teste só existe para nomear a regra."""
    calls = _run_handler(_joao_job())
    calls["sent"].assert_called_once()


def test_handler_resolve_o_canal_do_vendedor_pelo_phone_number_id():
    calls = _run_handler(_joao_job())
    calls["channel"].assert_called_once_with(
        "phone_number_id", S.JOAO_PHONE_NUMBER_ID, "meta_cloud"
    )


def test_handler_persiste_o_wamid_antes_de_marcar_sent():
    calls = _run_handler(_joao_job())
    calls["wamid"].assert_called_once_with("job-joao-1", "wamid.JOAO")
    calls["sent"].assert_called_once_with("job-joao-1")


def test_handler_cancela_quando_o_canal_do_joao_nao_existe():
    calls = _run_handler(_joao_job(), channel=None)
    calls["cancel"].assert_called_once_with("job-joao-1", "joao_channel_not_found")
    calls["sent"].assert_not_called()


def test_handler_cancela_sem_template():
    job = _joao_job()
    job["metadata"].pop("template_name")
    calls = _run_handler(job)
    calls["cancel"].assert_called_once_with("job-joao-1", "missing_template_name")
    calls["meta"].send_template.assert_not_awaited()


def test_handler_cancela_sem_telefone():
    job = _joao_job()
    job["metadata"].pop("lead_phone")
    job["leads"]["phone"] = ""
    calls = _run_handler(job)
    calls["cancel"].assert_called_once_with("job-joao-1", "missing_lead_phone")


def test_handler_respeita_language_code_do_metadata():
    calls = _run_handler(_joao_job(metadata={"language_code": "en"}))
    assert calls["meta"].send_template.await_args.kwargs["language_code"] == "en"


def test_handler_envia_mesmo_em_canal_humano():
    """O canal do João É humano (`mode='human'`) — o guard do caminho `standard` que
    cancela follow-up em canal humano não pode alcançar o toque do vendedor."""
    job = _joao_job()
    assert job["channels"]["mode"] == "human"
    calls = _run_handler(job)
    calls["meta"].send_template.assert_awaited_once()
    calls["cancel"].assert_not_called()


def test_handler_persiste_a_mensagem_do_template_na_conversa_do_joao():
    """Sem isto o CRM mostra só a resposta do lead, como se ele tivesse iniciado do nada
    (mesmo motivo de `_persist_joao_handoff_message`)."""
    calls = _run_handler(_joao_job())
    calls["save_msg"].assert_called_once()
    kwargs = calls["save_msg"].call_args.kwargs
    assert kwargs["content"] == "Oi Marcella, é o João"
    assert kwargs["role"] == "assistant"
    assert kwargs["wamid"] == "wamid.JOAO"


def test_handler_nao_persiste_placeholder_de_template_nao_renderizado():
    """`_render_template_body` devolve "[Template: x]" quando não acha o corpo — gravar
    isso envenenaria o histórico do CRM."""
    calls = _run_handler(_joao_job(), rendered="[Template: joao_novo_atacado_t1]")
    calls["save_msg"].assert_not_called()
    calls["sent"].assert_called_once()


# ─── o funil do card (Atacado / Private Label / Reposição Atacado / Reposição PL) ─────

def test_funil_vem_do_metadata_quando_declarado():
    assert S._resolve_joao_funil(_joao_job()) == "atacado"


def test_funil_aceita_as_grafias_de_private_label():
    for grafia in ("private_label", "privatelabel", "Private Label", "PRIVATE-LABEL"):
        job = _joao_job(metadata={"funil": grafia})
        assert S._resolve_joao_funil(job) == "private_label", grafia


def test_funil_por_pipeline_e_1_para_1_sem_colisao():
    """Bug fix da spec 2026-09-21 §1/§6: o dicionário antigo (`_LINHA_POR_PIPELINE`)
    mapeava o Atacado normal E a Reposição Atacado para a MESMA string "atacado" (e o
    mesmo para Private Label x Reposição Private Label) — os quatro pipelines do João
    colapsavam em só duas linhas. `_FUNIL_POR_PIPELINE` é 1:1, quatro valores distintos."""
    valores = list(S._FUNIL_POR_PIPELINE.values())
    assert len(valores) == len(set(valores)) == 4
    assert S._FUNIL_POR_PIPELINE[S.PIPELINE_JOAO_ATACADO] == "atacado"
    assert S._FUNIL_POR_PIPELINE[S.PIPELINE_JOAO_PRIVATE_LABEL] == "private_label"
    assert S._FUNIL_POR_PIPELINE[S.PIPELINE_JOAO_REPOSICAO_ATACADO] == "reposicao_atacado"
    assert (
        S._FUNIL_POR_PIPELINE[S.PIPELINE_JOAO_REPOSICAO_PRIVATE_LABEL]
        == "reposicao_private_label"
    )


def test_funil_vem_do_pipeline_do_deal_quando_o_metadata_nao_traz():
    """O toque do João é por FUNIL: mandar o texto de Atacado a um lead de Reposição
    Atacado é o mesmo erro que mandar o texto de Atacado a um lead de Private Label —
    e é exatamente o bug que a colisão antiga permitia (deal de Reposição Atacado
    resolvia, incorretamente, para o funil "atacado" normal)."""
    job = _joao_job()
    job["metadata"].pop("funil")
    job["metadata"]["deal_id"] = "deal-1"
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "deal-1", "pipeline_id": S.PIPELINE_JOAO_REPOSICAO_ATACADO}
    ]
    with patch("app.follow_up.scheduler.get_supabase", return_value=sb):
        assert S._resolve_joao_funil(job) == "reposicao_atacado"


def test_funil_do_pipeline_declarado_no_metadata():
    job = _joao_job()
    job["metadata"].pop("funil")
    job["metadata"]["pipeline_id"] = S.PIPELINE_JOAO_REPOSICAO_PRIVATE_LABEL
    assert S._resolve_joao_funil(job) == "reposicao_private_label"


def test_template_por_funil_escolhe_o_texto_do_funil_resolvido():
    job = _joao_job(metadata={
        "funil": "private_label",
        "template_por_funil": {"atacado": "joao_novo_atacado_t1",
                               "private_label": "joao_novo_privatelabel_t1"},
    })
    job["metadata"].pop("template_name")
    calls = _run_handler(job)
    assert calls["meta"].send_template.await_args.args[1] == "joao_novo_privatelabel_t1"


def test_funil_vindo_do_deal_mantem_o_toque_vivo():
    """Sem `metadata.funil`, o funil sai do pipeline do card — e com ele a etapa vigiada.
    O deal default está no funil Atacado, na etapa `novo`, que é a que "Novo" vigia."""
    job = _joao_job()
    job["metadata"].pop("funil")
    calls = _run_handler(job)
    calls["meta"].send_template.assert_awaited_once()


def test_funil_indeterminavel_encerra_o_toque_sem_enviar():
    """MUDOU em 2026-09-25 (spec §3.1). Antes: "sem funil declarado, o template já
    resolvido no metadata vale, e o toque sai". Agora o funil é também quem diz QUAL
    etapa a cadência vigia — sem ele não há como verificar se o card continua lá, e a
    falha segura é o silêncio (fail-closed, igual ao ramo do move).

    Aqui o card está num pipeline que não é de nenhum funil do João, então nem o
    metadata nem o card resolvem o funil."""
    job = _joao_job()
    job["metadata"].pop("funil")
    db = _FakeSupabase(
        deals={"deal-1": {"id": "deal-1", "pipeline_id": "pipe-de-outra-pessoa",
                          "stage_id": "st-x"}})
    calls = _run_handler(job, sb=db)

    calls["meta"].send_template.assert_not_awaited()
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()


# ─── erros da Meta: espelha lp_welcome / handoff_rescue ──────────────────────

def test_erro_permanente_da_meta_cancela_o_job():
    import httpx
    resp = httpx.Response(400, request=httpx.Request("POST", "https://graph.facebook.com/"))
    meta = AsyncMock()
    meta.send_template = AsyncMock(side_effect=httpx.HTTPStatusError("bad", request=resp.request, response=resp))
    calls = _run_handler(_joao_job(), meta=meta)
    calls["cancel"].assert_called_once_with("job-joao-1", "meta_permanent_error_400")
    calls["sent"].assert_not_called()


def test_erro_transitorio_da_meta_nao_cancela_nem_marca_sent():
    import httpx
    resp = httpx.Response(503, request=httpx.Request("POST", "https://graph.facebook.com/"))
    meta = AsyncMock()
    meta.send_template = AsyncMock(side_effect=httpx.HTTPStatusError("boom", request=resp.request, response=resp))
    calls = _run_handler(_joao_job(), meta=meta)
    calls["cancel"].assert_not_called()
    calls["sent"].assert_not_called()


def test_rejeicao_embutida_da_meta_cancela_como_meta_rejected():
    """HTTP 200 COM erro embutido é rejeição PERMANENTE — sem cancelar, o job fica
    pending e é retentado a cada tick para sempre."""
    meta = AsyncMock()
    meta.send_template = AsyncMock(side_effect=RuntimeError("param invalido"))
    calls = _run_handler(_joao_job(), meta=meta)
    calls["cancel"].assert_called_once_with("job-joao-1", "meta_rejected")


# ─── conversa finalizada pelo vendedor em /conversas ─────────────────────────

def test_conversa_finalizada_cancela_o_toque_do_joao():
    job = _joao_job()
    job["conversations"]["followup_enabled"] = False
    calls = _run_handler(job)
    calls["cancel"].assert_called_once_with("job-joao-1", "followup_disabled")
    calls["meta"].send_template.assert_not_awaited()


# ─── o job que MOVE o card no fim da cadência (spec 2026-09-23 §3) ───────────
#
# CONTRATO com o agendador (Task E2): o job de mover é um job normal da cadência,
# marcado com `metadata.acao == "mover_etapa"` — e essa marca é a ÚNICA condição do
# ramo. Inferir pelo template nulo não serve: os 22 toques das três cadências de
# prospecção nascem TODOS sem template, de propósito.

ETAPA_NOVO_ATACADO = "st-novo-atacado"
ETAPA_RESPONDEU_ATACADO = "st-respondeu-atacado"
ETAPA_PROPOSTA_ATACADO = "st-proposta-atacado"
ETAPA_GANHO_ATACADO = "st-ganho-atacado"
ETAPA_ATENCAO_ATACADO = "st-atencao-atacado"
ETAPA_NOVO_PRIVATE_LABEL = "st-novo-privatelabel"
ETAPA_ATENCAO_PRIVATE_LABEL = "st-atencao-privatelabel"

# As etapas dos DOIS funis na mesma tabela, com as MESMAS keys `novo` e `em_atencao` —
# `key` só é única por pipeline (`idx_pipeline_stages_key_unique`). As de Private Label
# vêm PRIMEIRO de propósito: sem o filtro por pipeline_id, o `next()` do código pegaria
# justamente elas — o card do Atacado iria para o funil do outro (move), ou um card
# parado na coluna certa seria lido como card movido (guarda de etapa do toque).
#
# As keys são as de `20260910_contrato_etapas_joao.sql`: "Em conversa" é `respondeu`
# (não `em_conversa`), e quem compra vai para `fechado_ganho`.
ETAPAS_DOS_DOIS_FUNIS = [
    {"id": ETAPA_ATENCAO_PRIVATE_LABEL, "key": "em_atencao",
     "pipeline_id": S.PIPELINE_JOAO_PRIVATE_LABEL},
    {"id": ETAPA_NOVO_PRIVATE_LABEL, "key": "novo",
     "pipeline_id": S.PIPELINE_JOAO_PRIVATE_LABEL},
    {"id": ETAPA_NOVO_ATACADO, "key": "novo", "pipeline_id": S.PIPELINE_JOAO_ATACADO},
    {"id": ETAPA_RESPONDEU_ATACADO, "key": "respondeu",
     "pipeline_id": S.PIPELINE_JOAO_ATACADO},
    {"id": ETAPA_PROPOSTA_ATACADO, "key": "proposta_enviada",
     "pipeline_id": S.PIPELINE_JOAO_ATACADO},
    {"id": ETAPA_GANHO_ATACADO, "key": "fechado_ganho",
     "pipeline_id": S.PIPELINE_JOAO_ATACADO},
    {"id": ETAPA_ATENCAO_ATACADO, "key": "em_atencao",
     "pipeline_id": S.PIPELINE_JOAO_ATACADO},
]


class _FakeTable:
    def __init__(self, db, nome):
        self.db, self.nome, self.op, self.payload = db, nome, "select", None
        self.filtros: dict = {}

    def select(self, *a, **k):
        self.op = "select"
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, coluna, valor):
        self.filtros[coluna] = valor
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self.nome == "deals" and self.op == "update":
            self.db.updates.append((self.filtros.get("id"), self.payload))
            return SimpleNamespace(data=[{"id": self.filtros.get("id")}])
        if self.nome == "deals":
            deal = self.db.deals.get(self.filtros.get("id"))
            return SimpleNamespace(data=[dict(deal)] if deal else [])
        if self.nome == "pipeline_stages":
            pipeline_id = self.filtros.get("pipeline_id")
            # SEM filtro devolve TUDO — é o que transforma "esqueci o .eq(pipeline_id)"
            # em teste vermelho, em vez de um card movido para o funil errado.
            if pipeline_id is None:
                return SimpleNamespace(data=list(self.db.stages))
            return SimpleNamespace(
                data=[e for e in self.db.stages if e["pipeline_id"] == pipeline_id]
            )
        return SimpleNamespace(data=[])


class _FakeSupabase:
    """Supabase de mentira com `deals` e `pipeline_stages`, e o filtro por funil de verdade."""

    def __init__(self, deals: dict, stages: list | None = None):
        self.deals = deals
        self.stages = stages if stages is not None else ETAPAS_DOS_DOIS_FUNIS
        self.updates: list = []

    def table(self, nome):
        return _FakeTable(self, nome)


def _db(stage_id=ETAPA_NOVO_ATACADO, pipeline_id=S.PIPELINE_JOAO_ATACADO, stages=None):
    return _FakeSupabase(
        deals={"deal-1": {"id": "deal-1", "pipeline_id": pipeline_id, "stage_id": stage_id}},
        stages=stages,
    )


def _move_job(**over):
    """O job de mover, no formato EXATO do contrato E2↔E3 (plano de 2026-09-23)."""
    metadata = {
        "acao": "mover_etapa",
        "etapa_final_key": "em_atencao",
        "cadencia": "novo",
        "funil": "atacado",
        "matricula_id": "mat-1",
        "matricula_em": "2026-09-18T09:00:00+00:00",
        "deal_id": "deal-1",
        "stage_id": ETAPA_NOVO_ATACADO,
        "pipeline_id": S.PIPELINE_JOAO_ATACADO,
        "template_name": None,
    }
    metadata.update(over.pop("metadata", {}))
    over.setdefault("job_type", "joao_novo")
    over.setdefault("sequence", 4)
    job = _joao_job(**over)
    job["metadata"] = metadata
    return job


def test_job_de_mover_move_o_card_e_nao_envia_nada():
    """O ramo inteiro: move o card e NÃO toca em template, canal nem provider."""
    db = _db()
    calls = _run_handler(_move_job(), sb=db)

    assert db.updates and db.updates[0][0] == "deal-1"
    assert db.updates[0][1]["stage_id"] == ETAPA_ATENCAO_ATACADO
    calls["meta"].send_template.assert_not_awaited()
    calls["save_msg"].assert_not_called()
    calls["channel"].assert_not_called()   # nem chega a resolver o canal do vendedor
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()


def test_job_de_mover_procura_a_key_dentro_do_pipeline_do_deal():
    """`em_atencao` existe nos quatro funis do João — `key` só é única POR pipeline
    (`idx_pipeline_stages_key_unique`). Sem o filtro, o card do Atacado cairia na etapa
    de Private Label, que é a primeira da lista em `ETAPAS_DOS_DOIS_FUNIS`."""
    db = _db()
    _run_handler(_move_job(), sb=db)

    assert db.updates[0][1]["stage_id"] == ETAPA_ATENCAO_ATACADO
    assert db.updates[0][1]["stage_id"] != ETAPA_ATENCAO_PRIVATE_LABEL


def test_job_de_mover_nao_desfaz_o_move_manual_do_vendedor():
    """Card já FORA da etapa vigiada (`novo`): o fim da cadência não puxa de volta o que
    o João moveu à mão."""
    db = _db(stage_id=ETAPA_PROPOSTA_ATACADO)
    calls = _run_handler(_move_job(), sb=db)

    assert db.updates == []
    calls["meta"].send_template.assert_not_awaited()
    calls["sent"].assert_called_once_with("job-joao-1")


def test_job_de_mover_com_etapa_de_destino_inexistente_nao_move_e_nao_levanta():
    """Funil sem `em_atencao` (migration não aplicada, key renomeada à mão): registra e
    segue — a cadência já acabou, só o card não anda."""
    db = _db(stages=[{"id": ETAPA_NOVO_ATACADO, "key": "novo",
                      "pipeline_id": S.PIPELINE_JOAO_ATACADO}])
    calls = _run_handler(_move_job(), sb=db)

    assert db.updates == []
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()


def test_job_de_mover_de_cadencia_que_vigia_outra_etapa():
    """A etapa VIGIADA vem da cadência declarada no job, não de um chute: `proposta`
    vigia `proposta_enviada`, então um card ali AINDA move."""
    db = _db(stage_id=ETAPA_PROPOSTA_ATACADO)
    calls = _run_handler(
        _move_job(job_type="joao_proposta", metadata={"cadencia": "proposta"}), sb=db)

    assert db.updates[0][1]["stage_id"] == ETAPA_ATENCAO_ATACADO
    calls["sent"].assert_called_once_with("job-joao-1")


def test_job_de_mover_com_deal_inexistente_nao_levanta():
    db = _FakeSupabase(deals={})
    calls = _run_handler(_move_job(), sb=db)

    assert db.updates == []
    calls["sent"].assert_called_once_with("job-joao-1")


def test_job_de_mover_sem_deal_id_e_cancelado_como_malformado():
    job = _move_job()
    job["metadata"].pop("deal_id")
    calls = _run_handler(job, sb=_db())

    calls["cancel"].assert_called_once_with("job-joao-1", "mover_etapa_sem_alvo")
    calls["sent"].assert_not_called()


def test_job_de_mover_nao_marca_terminal_quando_o_banco_falha():
    """Soluço de banco é TRANSITÓRIO: nem `sent` nem `cancelled`, o próximo tick tenta
    de novo. Cancelar por erro de rede seria permanente."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("conexão caiu")
    calls = _run_handler(_move_job(), sb=sb)

    calls["sent"].assert_not_called()
    calls["cancel"].assert_not_called()


def test_toque_sem_template_e_sem_a_marca_continua_sendo_toque():
    """MUTAÇÃO — a condição do ramo é SÓ `metadata.acao`. Se alguém trocar por "template
    nulo → mover", este job (um toque normal das cadências novas, que nascem todas sem
    texto) moveria o card em vez de ser cancelado por falta de template."""
    job = _move_job()
    job["metadata"].pop("acao")
    db = _db()
    calls = _run_handler(job, sb=db)

    assert db.updates == []
    calls["cancel"].assert_called_once_with("job-joao-1", "missing_template_name")


def test_conversa_finalizada_cancela_tambem_o_job_de_mover():
    """Quando o João encerra o atendimento em /conversas a cadência INTEIRA para —
    arrastar o card para "Em atenção" depois disso seria continuar a cadência atrás dele."""
    job = _move_job()
    job["conversations"]["followup_enabled"] = False
    db = _db()
    calls = _run_handler(job, sb=db)

    assert db.updates == []
    calls["cancel"].assert_called_once_with("job-joao-1", "followup_disabled")


# ─── _mover_card_joao direto (sem o handler em volta) ────────────────────────

def test_mover_card_joao_devolve_true_so_quando_o_card_anda():
    db = _db()
    with patch("app.follow_up.scheduler.get_supabase", return_value=db):
        assert S._mover_card_joao("deal-1", "em_atencao", etapa_vigiada="novo") is True
        assert S._mover_card_joao("deal-1", "em_atencao", etapa_vigiada="respondeu") is False
        assert S._mover_card_joao("deal-1", "etapa_que_nao_existe", etapa_vigiada="novo") is False
        assert S._mover_card_joao("deal-fantasma", "em_atencao", etapa_vigiada="novo") is False
    assert len(db.updates) == 1


# ─── a esteira vive enquanto o card estiver na etapa (spec 2026-09-25 §3.1) ──
#
# O DEFEITO que esta seção fecha, reproduzido contra o motor real em 24/09/2026: a
# MATRÍCULA já respeitava a etapa (a RPC filtra pela etapa atual do card e exclui de
# propósito `fechado_ganho`), mas ela agenda TODOS os toques de uma vez e o envio nunca
# relia a etapa. Card movido para "Fechado Ganho" no dia 1 continuava recebendo os
# toques 2 e 3 de "Novo" — até 3 mensagens de marketing, ao longo de 9 dias, para quem
# acabou de comprar.
#
# A guarda é a de `automation/engine.py::_guard_broken` ("True se o card saiu da etapa
# que originou este enrollment") trazida do motor de campanhas, com UMA diferença: lá
# ela é fail-OPEN e aqui NÃO é (ver `test_toque_nao_marca_estado_terminal_...`).

def test_toque_nao_sai_com_o_card_em_fechado_ganho():
    """O DEFEITO, fechado. Card em "Fechado Ganho" e toque 2 de "Novo" na fila: nada sai,
    e o job é encerrado com `card_mudou_de_etapa`.

    MUTAÇÃO OBRIGATÓRIA (plano 2026-09-25, G2): removida a guarda, ESTE teste tem de
    ficar vermelho — ele é a única coisa entre um cliente que acabou de comprar e três
    mensagens de marketing ao longo de nove dias."""
    db = _db(stage_id=ETAPA_GANHO_ATACADO)
    calls = _run_handler(_joao_job(metadata={"toque": 2}), sb=db)

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_called_once_with("job-joao-1", "card_mudou_de_etapa")
    calls["sent"].assert_not_called()
    calls["save_msg"].assert_not_called()
    # A guarda vem ANTES de resolver o canal do vendedor: esteira encerrada não gasta
    # leitura de canal nem monta componentes de template.
    calls["channel"].assert_not_called()


def test_toque_de_novo_nao_sai_depois_que_o_card_vai_para_em_conversa():
    """A consequência declarada no spec §2: em "Novo", responder ENCERRA a esteira — não
    porque a resposta cancela algo, mas porque `advance_deal_on_reply` move o card de
    `novo` para `respondeu` ("Em conversa") sozinho, e a guarda de etapa encerra o que
    sobrou. A esteira de "Em conversa" assume depois."""
    db = _db(stage_id=ETAPA_RESPONDEU_ATACADO)
    calls = _run_handler(_joao_job(metadata={"toque": 3}), sb=db)

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_called_once_with("job-joao-1", "card_mudou_de_etapa")


def test_toque_sai_normalmente_com_o_card_ainda_na_etapa_vigiada():
    """O caminho feliz, com a leitura extra no meio: o toque sai igual, e a guarda LÊ a
    etapa — nunca escreve."""
    db = _db(stage_id=ETAPA_NOVO_ATACADO)
    calls = _run_handler(_joao_job(metadata={"toque": 2}), sb=db)

    calls["meta"].send_template.assert_awaited_once()
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()
    assert db.updates == []


def test_a_guarda_procura_a_etapa_dentro_do_funil_do_card():
    """`novo` existe nos quatro funis do João e `key` só é única POR pipeline. A etapa
    `novo` de Private Label vem ANTES da de Atacado em `ETAPAS_DOS_DOIS_FUNIS`: uma
    guarda que procurasse a key sem filtrar pelo funil do card acharia a do outro funil
    e trataria este card parado na coluna certa como card movido."""
    db = _db(stage_id=ETAPA_NOVO_ATACADO, pipeline_id=S.PIPELINE_JOAO_ATACADO)
    calls = _run_handler(_joao_job(), sb=db)

    calls["meta"].send_template.assert_awaited_once()
    calls["cancel"].assert_not_called()


def test_toque_com_o_card_apagado_e_cancelado():
    """Sem card não há trabalho — a mesma leitura que `_guard_broken` faz do deal
    inexistente. O motivo é o mesmo `card_mudou_de_etapa` (spec §3.1)."""
    db = _FakeSupabase(deals={})
    calls = _run_handler(_joao_job(), sb=db)

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_called_once_with("job-joao-1", "card_mudou_de_etapa")
    calls["sent"].assert_not_called()


def test_toque_nao_marca_estado_terminal_quando_o_banco_falha():
    """A diferença DELIBERADA para `_guard_broken`, que é fail-OPEN: aqui erro de banco
    não envia E não encerra. Lá o custo de errar é um toque a mais numa campanha; aqui é
    mensagem de marketing para quem acabou de comprar — o botão "Bloquear" e a reputação
    do número na Meta. Adiar a decisão até dar para tomá-la é melhor que os dois
    extremos, e é o mesmo tratamento que o ramo do move dá a erro transitório."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("conexão caiu")
    calls = _run_handler(_joao_job(), sb=sb)

    calls["meta"].send_template.assert_not_awaited()
    calls["sent"].assert_not_called()
    calls["cancel"].assert_not_called()


def test_a_etapa_vigiada_vem_da_config_e_nao_do_metadata():
    """MUTAÇÃO: o job leva um `metadata.stage_id` MENTIROSO, apontando para a etapa onde
    o card está AGORA (Fechado Ganho). Uma guarda que comparasse `deals.stage_id` com
    `metadata.stage_id` acharia tudo em ordem e mandaria a mensagem.

    A etapa vigiada vem de `cadencia_do_funil(funil, cadencia)` — a config é a fonte, e
    duas fontes divergiriam no dia em que alguém mudasse o gatilho pela tela. É o mesmo
    caminho que o ramo do move já usa."""
    db = _db(stage_id=ETAPA_GANHO_ATACADO)
    calls = _run_handler(_joao_job(metadata={"stage_id": ETAPA_GANHO_ATACADO}), sb=db)

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_called_once_with("job-joao-1", "card_mudou_de_etapa")


def test_metadata_stage_id_desatualizado_nao_derruba_o_toque_legitimo():
    """O outro lado da mesma moeda: card parado na etapa vigiada e um `metadata.stage_id`
    apontando para outra coluna. A config manda, e o toque sai."""
    db = _db(stage_id=ETAPA_NOVO_ATACADO)
    calls = _run_handler(_joao_job(metadata={"stage_id": ETAPA_PROPOSTA_ATACADO}), sb=db)

    calls["meta"].send_template.assert_awaited_once()
    calls["cancel"].assert_not_called()


def test_a_etapa_vigiada_e_a_da_CADENCIA_declarada_no_job():
    """O MESMO card, em `proposta_enviada`, encerra a esteira "Novo" e mantém viva a de
    "Proposta Enviada" — cada cadência vigia a sua etapa."""
    calls_novo = _run_handler(
        _joao_job(), sb=_db(stage_id=ETAPA_PROPOSTA_ATACADO))
    calls_novo["cancel"].assert_called_once_with("job-joao-1", "card_mudou_de_etapa")

    calls_proposta = _run_handler(
        _joao_job(job_type="joao_proposta", metadata={"cadencia": "proposta"}),
        sb=_db(stage_id=ETAPA_PROPOSTA_ATACADO))
    calls_proposta["meta"].send_template.assert_awaited_once()
    calls_proposta["cancel"].assert_not_called()


def test_a_esteira_de_reposicao_vigia_a_coluna_cliente_ativo():
    """A única cadência que pode ser ligada hoje (é a única com template em todo toque).
    Ela vive nos funis de Reposição e vigia a key `novo` — a coluna "Cliente Ativo"
    (decisão 2 de `cadence_joao`). O rótulo muda, a key não."""
    db = _FakeSupabase(
        deals={"deal-1": {"id": "deal-1",
                          "pipeline_id": S.PIPELINE_JOAO_REPOSICAO_ATACADO,
                          "stage_id": "st-cliente-ativo"}},
        stages=[{"id": "st-cliente-ativo", "key": "novo",
                 "pipeline_id": S.PIPELINE_JOAO_REPOSICAO_ATACADO}],
    )
    job = _joao_job(metadata={"funil": "reposicao_atacado", "cadencia": "reposicao",
                              "template_name": "joao_reposicao_atacado_t1"})
    calls = _run_handler(job, sb=db)

    assert calls["meta"].send_template.await_args.args[1] == "joao_reposicao_atacado_t1"
    calls["sent"].assert_called_once_with("job-joao-1")


def test_toque_sem_deal_id_nao_envia_e_e_cancelado():
    """O agendador grava `deal_id` em todo job da cadência — ausência é BUG. E job que
    não dá para verificar não manda mensagem: `cancel_reason` é onde o bug fica visível
    numa consulta, em vez de virar um `sent` silencioso."""
    job = _joao_job()
    job["metadata"].pop("deal_id")
    calls = _run_handler(job)

    calls["meta"].send_template.assert_not_awaited()
    calls["cancel"].assert_called_once_with("job-joao-1", "toque_sem_deal_para_verificar")
    calls["sent"].assert_not_called()


def test_toque_de_cadencia_nao_resolvida_encerra_sem_enviar():
    """Fail-closed, igual ao ramo do move: `reposicao` NÃO é cadência do funil Atacado
    (ela vive nos dois funis de Reposição), então o par não resolve. Sem saber que etapa
    vigiar não dá para afirmar que o card continua nela — e o silêncio é a falha segura.

    `_mark_sent` e não `_cancel_job`: job cancelado é lido pelo cooldown por matrícula do
    agendador como "o lead respondeu no meio", e LIBERARIA a reentrada."""
    calls = _run_handler(_joao_job(metadata={"cadencia": "reposicao"}))

    calls["meta"].send_template.assert_not_awaited()
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()


def test_a_guarda_de_etapa_nao_alcanca_o_job_de_mover():
    """O ramo do move tem a SUA guarda (`_mover_card_joao`) e sai antes desta — senão um
    card que saiu da etapa seria `cancelled` em vez de `sent`, e job cancelado mente para
    o cooldown por matrícula do agendador (ele lê isso como "o lead respondeu")."""
    db = _db(stage_id=ETAPA_PROPOSTA_ATACADO)
    calls = _run_handler(_move_job(), sb=db)

    assert db.updates == []
    calls["sent"].assert_called_once_with("job-joao-1")
    calls["cancel"].assert_not_called()


# ─── _stop_reason_applies: as mesmas paradas da ValerIA ──────────────────────

@pytest.mark.parametrize("job_type", ["joao_touch", "joao_novo", "joao_em_conversa",
                                      "joao_proposta", "joao_reposicao", "joao_em_atencao"])
@pytest.mark.parametrize("reason", ["blacklisted", "wrong_number", "opt_out"])
def test_joao_para_nas_mesmas_condicoes_da_valeria(reason, job_type):
    assert S._stop_reason_applies(reason, job_type) is True


# ─── a cadência nova: `joao_proposta` (spec 2026-09-23) ──────────────────────

def test_joao_proposta_esta_na_lista_hardcoded_do_handler():
    """`JOB_TYPES` de `cadence_joao` é derivado de `FUNIS` e ganha `joao_proposta`
    sozinho; `JOAO_JOB_TYPES` daqui é hardcoded e precisa dele à mão."""
    from app.follow_up import cadence_joao as cj

    assert "joao_proposta" in S.JOAO_JOB_TYPES
    assert cj.JOB_TYPES <= S.JOAO_JOB_TYPES


def test_joao_proposta_nasce_isento_de_ai_disabled():
    """O teste que o spec 2026-09-23 §6 manda escrever ANTES de confiar na cadência nova.

    A isenção do João é por PREFIXO (`_is_joao_job_type`), não pela tabela
    `_STOP_REASON_EXEMPT_JOB_TYPES` — então `joao_proposta` já nasce isento sem que
    ninguém a atualize. Se este teste ficar vermelho, a cadência nova nasce CONDENADA:
    é o bug do `handoff_rescue` de 27/07 (144 jobs criados, 144 cancelados com
    `ai_disabled`, ZERO enviados), e o lead do vendedor tem `ai_enabled=False` por
    definição."""
    assert S._is_joao_job_type("joao_proposta") is True
    assert S._stop_reason_applies("ai_disabled", "joao_proposta") is False
    assert "joao_proposta" not in S._STOP_REASON_EXEMPT_JOB_TYPES.get(
        "ai_disabled", frozenset()
    ), "a isenção do João é por prefixo — não por lista fechada"


@pytest.mark.parametrize("job_type", ["joao_touch", "joao_reposicao", "joao_proposta"])
def test_ai_disabled_nao_para_o_toque_do_joao(job_type):
    """O lead do João tem ai_enabled=False POR DEFINIÇÃO (foi entregue ao humano). Sem
    esta isenção todo job do João nasceria condenado — exatamente o bug do handoff_rescue
    (144 jobs criados entre 22 e 27/07, 144 cancelados com `ai_disabled`, ZERO enviados)."""
    assert S._stop_reason_applies("ai_disabled", job_type) is False


def test_ai_disabled_continua_parando_o_caminho_da_valeria():
    """REGRESSÃO: a isenção é SÓ do João. Nada muda para `standard`."""
    assert S._stop_reason_applies("ai_disabled", "standard") is True
    assert S._stop_reason_applies("ai_disabled", None) is True
    assert S._stop_reason_applies("ai_disabled", "ai_reengage") is True
    assert S._stop_reason_applies("ai_disabled", "handoff_rescue") is False


def test_sem_motivo_nada_para():
    assert S._stop_reason_applies(None, "joao_touch") is False
    assert S._stop_reason_applies("", "joao_touch") is False


# ─── despacho em process_due_followups (alvo da mutação) ─────────────────────

def _drive_tick(job, **extra_patches):
    """Roda `process_due_followups` com UM job, sem tocar em I/O real."""
    import asyncio

    def _no_llm(*a, **k):
        raise AssertionError("o caminho do João NUNCA pode chamar o LLM")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._generate_followup_message", new=AsyncMock(side_effect=_no_llm)), \
         patch("app.follow_up.scheduler._process_joao_touch", new=AsyncMock()) as mock_joao, \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=extra_patches.get("lead")):
        asyncio.run(S.process_due_followups(now=NOW))
    return mock_joao


def test_despacho_roteia_o_job_do_joao_para_o_handler_dedicado():
    """MUTAÇÃO: se o `job_type` do João não bater no despacho, o job cai no caminho
    `standard` — que chama o LLM e explode no mock acima."""
    mock_joao = _drive_tick(_joao_job())
    mock_joao.assert_awaited_once()
    assert mock_joao.await_args.args[0]["id"] == "job-joao-1"


@pytest.mark.parametrize("job_type", ["joao_novo", "joao_em_conversa", "joao_proposta",
                                      "joao_reposicao", "joao_em_atencao"])
def test_despacho_aceita_qualquer_job_type_do_joao(job_type):
    mock_joao = _drive_tick(_joao_job(job_type=job_type))
    mock_joao.assert_awaited_once()


def test_lead_blacklisted_suprime_o_job_do_joao_antes_do_handler():
    job = _joao_job()
    with patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        mock_joao = _drive_tick(job, lead={"id": "lead-1", "metadata": {"blacklisted_at": "2026-09-01"}})
    mock_joao.assert_not_awaited()
    mock_cancel.assert_called_once_with("job-joao-1", "blacklisted")


def test_lead_wrong_number_suprime_o_job_do_joao_antes_do_handler():
    job = _joao_job()
    with patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        mock_joao = _drive_tick(job, lead={"id": "lead-1", "metadata": {"wrong_number_at": "2026-09-01"}})
    mock_joao.assert_not_awaited()
    mock_cancel.assert_called_once_with("job-joao-1", "wrong_number")


def test_lead_com_ia_desligada_segue_para_o_handler_do_joao():
    """O caso NORMAL do João: lead entregue ao humano, ai_enabled=False."""
    job = _joao_job()
    with patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        mock_joao = _drive_tick(job, lead={"id": "lead-1", "ai_enabled": False, "metadata": {}})
    mock_joao.assert_awaited_once()
    mock_cancel.assert_not_called()


# ─── REGRESSÃO: o caminho `standard` da ValerIA, intocado ────────────────────

@pytest.mark.asyncio
async def test_standard_continua_gerando_por_llm_e_enviando_texto():
    """O único follow-up que funciona em produção. Se este teste mudar de resultado, o
    ramo novo quebrou o caminho que não podia quebrar."""
    job = {
        "id": "job-std-1", "job_type": "standard", "conversation_id": "conv-1",
        "lead_id": "lead-1", "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5511999999999"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": True,
                          "last_customer_message_at": datetime.now(timezone.utc).isoformat()},
        "metadata": {},
    }
    provider = AsyncMock()
    provider.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.STD"}]})

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler.get_provider", return_value=provider), \
         patch("app.follow_up.scheduler._generate_followup_message",
               new=AsyncMock(return_value=("Oi, tudo bem?", "stop"))) as mock_llm, \
         patch("app.follow_up.scheduler.save_message_conv"), \
         patch("app.follow_up.scheduler._process_joao_touch", new=AsyncMock()) as mock_joao, \
         patch("app.follow_up.scheduler._save_followup_wamid") as mock_wamid, \
         patch("app.follow_up.scheduler._mark_sent") as mock_sent:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_llm.assert_awaited_once()
    provider.send_text.assert_awaited_once_with("5511999999999", "Oi, tudo bem?")
    mock_wamid.assert_called_once_with("job-std-1", "wamid.STD")
    mock_sent.assert_called_once_with("job-std-1")
    mock_joao.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", ["standard", None, "ai_reengage", "lp_welcome",
                                      "handoff_rescue", "ai_scheduled_return"])
async def test_nenhum_job_type_existente_cai_no_handler_do_joao(job_type):
    """REGRESSÃO de despacho: os cinco tipos que já existiam não podem ser capturados
    pelo ramo novo."""
    job = {
        "id": "job-x", "job_type": job_type, "conversation_id": "conv-1",
        "lead_id": "lead-1", "sequence": 1,
        "leads": {"id": "lead-1", "phone": "5511999999999"},
        "channels": {"id": "ch-1", "mode": "human", "provider_config": {}},
        "conversations": {"id": "conv-1", "stage": "atacado", "followup_enabled": False},
        "metadata": {},
    }
    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._process_handoff_rescue", new=AsyncMock()), \
         patch("app.follow_up.scheduler._process_lp_welcome", new=AsyncMock()), \
         patch("app.follow_up.scheduler._process_ai_reengage", new=AsyncMock()), \
         patch("app.follow_up.scheduler._process_ai_scheduled_return", new=AsyncMock()), \
         patch("app.follow_up.scheduler._cancel_job"), \
         patch("app.follow_up.scheduler._process_joao_touch", new=AsyncMock()) as mock_joao:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_joao.assert_not_awaited()
