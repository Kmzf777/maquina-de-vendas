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
        "template_name": "joao_reposicao_atacado_t1",   # OU "template_por_funil"
        "template_por_funil": {"atacado": "...", "private_label": "...", ...},
        "language_code": "pt_BR",                # default
        "template_variables": {...},             # default: {{1}} = primeiro nome
        "lead_phone": "...",                     # opcional — cai p/ leads.phone
        "deal_id": "...", "pipeline_id": "...",  # opcionais, p/ resolver o funil
    }
"""
from datetime import datetime, timezone
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
    """Job de toque do João no formato que `get_due_followups` devolve (joins inclusos)."""
    metadata = {
        "cadencia": "reposicao",
        "funil": "atacado",
        "toque": 1,
        "template_name": "joao_reposicao_atacado_t1",
        "lead_phone": "5534988861441",
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
    """
    import asyncio

    meta = meta or _meta()
    sb = sb or MagicMock()
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
    assert args[1] == "joao_reposicao_atacado_t1"
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
    calls = _run_handler(_joao_job(), rendered="[Template: joao_reposicao_atacado_t1]")
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


def test_funil_indefinido_nao_derruba_o_toque_com_template_explicito():
    """Sem deal e sem funil declarado, o template já resolvido no metadata vale."""
    job = _joao_job()
    job["metadata"].pop("funil")
    calls = _run_handler(job)
    calls["meta"].send_template.assert_awaited_once()


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


# ─── _stop_reason_applies: as mesmas paradas da ValerIA ──────────────────────

@pytest.mark.parametrize("job_type", ["joao_touch", "joao_novo", "joao_em_conversa",
                                      "joao_reposicao", "joao_em_atencao"])
@pytest.mark.parametrize("reason", ["blacklisted", "wrong_number", "opt_out"])
def test_joao_para_nas_mesmas_condicoes_da_valeria(reason, job_type):
    assert S._stop_reason_applies(reason, job_type) is True


@pytest.mark.parametrize("job_type", ["joao_touch", "joao_reposicao"])
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


@pytest.mark.parametrize("job_type", ["joao_novo", "joao_em_conversa", "joao_reposicao",
                                      "joao_em_atencao"])
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
