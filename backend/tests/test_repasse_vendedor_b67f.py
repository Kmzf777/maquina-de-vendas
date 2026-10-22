"""Caminho do repasse (Task E, cartão b67f1c6b).

Segmento em `leads.segmento` (separado da fase), vendedor pelo cadastro único
`vendedores`, exportação para o Arthur pelo fixo, carimbo `metadata.handoff.vendedor_id`
e as travas de `[qualificar_lead]` / `marcar_interesse`.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import tools
from app.agent.tools import EXPORTACAO_NAME, EXPORTACAO_PHONE, SUPERVISOR_NAME, SUPERVISOR_PHONE
from app.vendedores import service as vendedores

JOAO = {"id": "u-joao", "email": "joao@cafecanastra.com", "nome": "João Brás",
        "apelidos": ["Joao Bras", "João - Café Canastra"], "segmentos": ["atacado", "private_label"],
        "atende_no_crm": True, "ativo": True}
ARTHUR = {"id": "u-arthur", "email": "arthur@cafecanastra.com", "nome": "Arthur",
          "apelidos": ["Arthur - Café Canastra"], "segmentos": ["exportacao"],
          "atende_no_crm": False, "ativo": True}
RAFAEL = {"id": "u-rafael", "email": "rafael@cafecanastra.com", "nome": "Rafael", "apelidos": [],
          "segmentos": [], "atende_no_crm": True, "ativo": False}


@pytest.fixture
def tabela(monkeypatch):
    vendedores.limpar_cache()
    monkeypatch.setattr(vendedores, "_carregar", lambda: [dict(r) for r in (JOAO, ARTHUR, RAFAEL)])
    yield
    vendedores.limpar_cache()


@pytest.fixture
def tabela_vazia(monkeypatch):
    vendedores.limpar_cache()
    monkeypatch.setattr(vendedores, "_carregar", lambda: [])
    yield
    vendedores.limpar_cache()


# ─────────────────────────────────────────────── apply_stage_transition

def _ast(lead, conv_stage, novo):
    with patch.object(tools, "get_lead", return_value=lead), \
         patch.object(tools, "get_conversation", return_value={"stage": conv_stage}), \
         patch.object(tools, "update_conversation") as uc, \
         patch.object(tools, "update_lead") as ul, \
         patch.object(tools, "ensure_segment_deal") as esd, \
         patch.object(tools, "save_message") as sm:
        ok = tools.apply_stage_transition("L1", "C1", novo)
    return ok, uc, ul, esd, sm


def test_segmento_grava_leads_segmento_e_fase_qualificando():
    ok, uc, ul, esd, sm = _ast({"id": "L1", "stage": "triagem", "segmento": None}, "secretaria",
                               "private_label")
    assert ok is True
    ul.assert_called_once_with("L1", segmento="private_label", stage="qualificando")
    # conversations.stage continua recebendo o valor de hoje (escolhe o prompt).
    uc.assert_called_once_with("C1", stage="private_label")
    esd.assert_called_once_with("L1", "private_label")
    assert sm.call_args.args[2] == "stage alterado para: private_label"


def test_secretaria_vira_fase_triagem_sem_segmento():
    ok, uc, ul, esd, sm = _ast({"id": "L1", "stage": "pending", "segmento": None}, "pending",
                               "secretaria")
    assert ok is True
    ul.assert_called_once_with("L1", stage="triagem", segmento=None)
    uc.assert_called_once_with("C1", stage="secretaria")


def test_noop_quando_lead_e_conversa_ja_estao_no_destino():
    ok, uc, ul, esd, sm = _ast({"id": "L1", "stage": "qualificando", "segmento": "atacado"},
                               "atacado", "atacado")
    assert ok is False
    ul.assert_not_called()
    uc.assert_not_called()
    sm.assert_not_called()


def test_lead_legado_com_segmento_no_stage_ressincroniza():
    """Lead antigo (segmento só em `stage`) ganha `segmento` na primeira transição. Com a
    conversa já no destino é migração silenciosa: grava o lead, sem marcador nem card."""
    ok, uc, ul, esd, sm = _ast({"id": "L1", "stage": "atacado"}, "atacado", "atacado")
    assert ok is False
    ul.assert_called_once_with("L1", segmento="atacado", stage="qualificando")
    uc.assert_not_called()
    esd.assert_not_called()
    sm.assert_not_called()


def test_lead_legado_com_conversa_em_outro_stage_aplica_normal():
    ok, uc, ul, esd, sm = _ast({"id": "L1", "stage": "atacado"}, "pending", "atacado")
    assert ok is True
    ul.assert_called_once_with("L1", segmento="atacado", stage="qualificando")
    uc.assert_called_once_with("C1", stage="atacado")
    sm.assert_called_once()


def test_noop_secretaria_ja_em_triagem():
    ok, *_ = _ast({"id": "L1", "stage": "triagem", "segmento": None}, "secretaria", "secretaria")
    assert ok is False


# ─────────────────────────────────────────────── vendor_user_id_for_segment

def test_vendor_user_id_for_segment_le_vendedores(tabela):
    from app.leads.service import vendor_user_id_for_segment
    assert vendor_user_id_for_segment("atacado") == "u-joao"
    assert vendor_user_id_for_segment("Private Label") == "u-joao"
    assert vendor_user_id_for_segment("exportacao") == "u-arthur"
    assert vendor_user_id_for_segment("consumo") is None
    assert vendor_user_id_for_segment("secretaria") is None
    assert vendor_user_id_for_segment(None) is None


def test_vendor_user_id_for_segment_tabela_vazia_devolve_none(tabela_vazia):
    from app.leads.service import vendor_user_id_for_segment
    assert vendor_user_id_for_segment("atacado") is None


# ─────────────────────────────────────────────── encaminhar_humano

class _Provider:
    def __init__(self):
        self.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.1"}]})
        self.send_contact = AsyncMock(return_value={})


def _mocks_handoff(monkeypatch, lead, *, canal=True):
    reg = {"updates": [], "msgs": [], "creates": [], "moves": [], "lp_moves": [],
           "rescue": [], "provider": _Provider()}
    monkeypatch.setattr(tools, "get_lead", lambda lead_id: dict(lead))
    monkeypatch.setattr(tools, "update_lead", lambda lead_id, **kw: reg["updates"].append(kw))
    monkeypatch.setattr(tools, "create_deal",
                        lambda lead_id, title, **kw: reg["creates"].append(kw) or {"id": "d"})
    monkeypatch.setattr(tools, "move_deal_to_vendor_pipeline",
                        lambda lead_id, seg, title=None: reg["moves"].append(seg) or {"id": "d"})
    monkeypatch.setattr(tools, "move_open_deal_for_handoff",
                        lambda *a, **k: reg["lp_moves"].append(a) or None)
    monkeypatch.setattr(tools, "cancel_followups_by_phone", lambda *a, **k: None)
    monkeypatch.setattr(tools, "schedule_handoff_rescue", lambda **kw: reg["rescue"].append(kw))
    monkeypatch.setattr(tools, "get_conversation_history",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sem resumo")))
    monkeypatch.setattr(tools, "append_lead_observation", lambda *a, **k: None)
    monkeypatch.setattr(tools, "_despedida_ja_enviada", lambda *a, **k: False)
    monkeypatch.setattr(tools, "get_channel_for_lead",
                        lambda lead_id: {"id": "ch-1"} if canal else None)
    monkeypatch.setattr(tools, "get_provider", lambda ch: reg["provider"])
    monkeypatch.setattr(tools, "save_message",
                        lambda lead_id, role, content, *a, **k: reg["msgs"].append((role, content)) or {})
    return reg


def _carimbo(reg):
    hs = [u["metadata"]["handoff"] for u in reg["updates"]
          if "metadata" in u and "handoff" in (u["metadata"] or {})]
    assert hs, "esperava carimbo metadata.handoff"
    return hs[0]


def _desligou(reg):
    d = [u for u in reg["updates"] if u.get("ai_enabled") is False]
    assert d
    return d[0]


async def _encaminhar(args=None):
    return await tools.execute_tool(
        "encaminhar_humano", args or {"vendedor": "Joao Bras", "motivo": "qualificado"},
        lead_id="L1", phone="5511999999999", conversation_id="C1")


LEAD_EXPORT = {"id": "L1", "phone": "5511999999999", "stage": "qualificando",
               "segmento": "exportacao", "metadata": {}, "name": "Ana"}
LEAD_ATACADO = {"id": "L1", "phone": "5511999999999", "stage": "qualificando",
                "segmento": "atacado", "metadata": {}, "name": "Ana"}
LEAD_SEM_SEG = {"id": "L1", "phone": "5511999999999", "stage": "triagem", "segmento": None,
                "metadata": {}, "name": "Ana"}


@pytest.mark.asyncio
async def test_exportacao_manda_cartao_do_arthur_e_grava_vendedor_id(monkeypatch, tabela):
    reg = _mocks_handoff(monkeypatch, LEAD_EXPORT)
    res = await _encaminhar()
    contato = reg["provider"].send_contact.call_args.kwargs
    assert contato == {"contact_name": EXPORTACAO_NAME, "contact_phone": EXPORTACAO_PHONE}
    assert ("system", f"[encaminhar_humano] cartão de contato de {EXPORTACAO_NAME} enviado") in reg["msgs"]
    assert _desligou(reg)["assigned_to"] == "u-arthur"
    carimbo = _carimbo(reg)
    assert carimbo["vendedor_id"] == "u-arthur"
    assert carimbo["vendedor"] == "Arthur"
    assert carimbo["segmento"] == "exportacao"
    assert reg["moves"] == ["exportacao"]
    despedida = reg["provider"].send_text.call_args.args[1]
    assert "Arthur" in despedida and "João" not in despedida and "wa.me" not in despedida
    # Arthur atende fora do CRM, pelo fixo: o resgate (template do canal do João) não sai.
    assert reg["rescue"] == []
    assert res == "Lead encaminhado para Arthur"


@pytest.mark.asyncio
async def test_exportacao_troca_despedida_do_llm_que_cita_o_joao(monkeypatch, tabela):
    reg = _mocks_handoff(monkeypatch, LEAD_EXPORT)
    await _encaminhar({"vendedor": "Joao Bras", "motivo": "q",
                       "mensagem_despedida": "vou deixar o contato do João aqui embaixo"})
    despedida = reg["provider"].send_text.call_args.args[1]
    assert "Arthur" in despedida and "João" not in despedida


@pytest.mark.asyncio
async def test_exportacao_mantem_despedida_do_llm_sem_joao(monkeypatch, tabela):
    reg = _mocks_handoff(monkeypatch, LEAD_EXPORT)
    await _encaminhar({"vendedor": "Arthur", "motivo": "q",
                       "mensagem_despedida": "o Arthur te chama pelo fixo"})
    assert reg["provider"].send_text.call_args.args[1] == "o Arthur te chama pelo fixo"


@pytest.mark.asyncio
async def test_exportacao_com_tabela_vazia_nao_derruba_e_manda_arthur(monkeypatch, tabela_vazia):
    reg = _mocks_handoff(monkeypatch, LEAD_EXPORT)
    res = await _encaminhar()
    assert reg["provider"].send_contact.call_args.kwargs["contact_name"] == EXPORTACAO_NAME
    carimbo = _carimbo(reg)
    assert carimbo["vendedor_id"] is None
    assert carimbo["vendedor"] == "Arthur"
    assert res == "Lead encaminhado para Arthur"


@pytest.mark.asyncio
async def test_atacado_continua_mandando_o_joao(monkeypatch, tabela):
    reg = _mocks_handoff(monkeypatch, LEAD_ATACADO)
    res = await _encaminhar()
    contato = reg["provider"].send_contact.call_args.kwargs
    assert contato == {"contact_name": SUPERVISOR_NAME, "contact_phone": SUPERVISOR_PHONE}
    assert _desligou(reg)["assigned_to"] == "u-joao"
    carimbo = _carimbo(reg)
    assert carimbo["vendedor_id"] == "u-joao"
    assert carimbo["vendedor"] == "João Brás"
    assert reg["moves"] == ["atacado"]
    assert len(reg["rescue"]) == 1
    assert res == "Lead encaminhado para João Brás"
    assert ("system", "[encaminhar_humano] Lead encaminhado para João Brás: qualificado") in reg["msgs"]


@pytest.mark.asyncio
async def test_atacado_tabela_vazia_mantem_rotulo_do_llm(monkeypatch, tabela_vazia):
    reg = _mocks_handoff(monkeypatch, LEAD_ATACADO)
    res = await _encaminhar()
    carimbo = _carimbo(reg)
    assert carimbo["vendedor_id"] is None
    assert carimbo["vendedor"] == "Joao Bras"
    assert res == "Lead encaminhado para Joao Bras"


@pytest.mark.asyncio
async def test_segmento_legado_no_stage_ainda_roteia(monkeypatch, tabela):
    lead = dict(LEAD_ATACADO, stage="private_label", segmento=None)
    reg = _mocks_handoff(monkeypatch, lead)
    await _encaminhar()
    assert reg["moves"] == ["private_label"]
    assert _carimbo(reg)["segmento"] == "private_label"


@pytest.mark.asyncio
async def test_sem_segmento_nao_move_o_card_e_resolve_vendedor_do_llm(monkeypatch, tabela):
    reg = _mocks_handoff(monkeypatch, LEAD_SEM_SEG)
    await _encaminhar({"vendedor": "Rafael", "motivo": "q"})
    assert reg["moves"] == [] and reg["lp_moves"] == []
    assert reg["creates"] == [{"category": None, "dedupe_open": True}]
    assert _desligou(reg)["assigned_to"] == "u-rafael"
    carimbo = _carimbo(reg)
    assert carimbo["vendedor_id"] == "u-rafael"
    assert carimbo["vendedor"] == "Rafael"
    assert carimbo["segmento"] is None


@pytest.mark.asyncio
async def test_sem_segmento_e_vendedor_irresolvivel_cai_no_joao(monkeypatch, tabela):
    reg = _mocks_handoff(monkeypatch, LEAD_SEM_SEG)
    await _encaminhar({"motivo": "q"})  # sem vendedor -> "Vendedor"
    assert _desligou(reg)["assigned_to"] == "u-joao"
    assert _carimbo(reg)["vendedor"] == "João Brás"


@pytest.mark.asyncio
async def test_consumo_nao_vai_para_vendedor_nem_muda_de_funil(monkeypatch, tabela):
    lead = dict(LEAD_ATACADO, segmento="consumo")
    reg = _mocks_handoff(monkeypatch, lead)
    await _encaminhar()
    assert "assigned_to" not in _desligou(reg)
    assert reg["moves"] == [] and reg["lp_moves"] == []
    assert reg["creates"] == [{"category": "consumo", "dedupe_open": True}]
    # quem recebe o cartão é o João: o carimbo diz isso.
    assert _carimbo(reg)["vendedor_id"] == "u-joao"


@pytest.mark.asyncio
@pytest.mark.parametrize("fixo", ["Joao Bras", "João Brás"])
async def test_repasses_com_nome_fixo_carimbam_o_id(monkeypatch, tabela, fixo):
    """Os repasses com o nome fixo (guardas do processor, parking, scheduler, orchestrator,
    cascatas de qualificar_lead/reclamação/retomada) passam todos por encaminhar_humano."""
    reg = _mocks_handoff(monkeypatch, LEAD_SEM_SEG)
    await _encaminhar({"vendedor": fixo, "motivo": "IA temporariamente indisponível"})
    carimbo = _carimbo(reg)
    assert carimbo["vendedor_id"] == "u-joao"
    assert carimbo["vendedor"] == "João Brás"


@pytest.mark.asyncio
async def test_registrar_repasse_recebe_vendedor_id(monkeypatch, tabela):
    _mocks_handoff(monkeypatch, LEAD_EXPORT)
    with patch("app.leads.repasse.registrar_repasse", return_value=True) as rr:
        await _encaminhar()
    kw = rr.call_args.kwargs
    assert kw["vendedor_id"] == "u-arthur"
    assert kw["vendedor"] == "Arthur"
    assert kw["segmento"] == "exportacao"


# ─────────────────────────────────────────────── button_flow/effects._aplicar_handoff

def _aplicar(lead, vendedor):
    from app.button_flow import effects
    carimbos = []
    with patch.object(effects, "update_lead"), \
         patch.object(effects, "save_message", return_value={"id": "m1", "created_at": "t"}), \
         patch.object(effects, "atualizar_metadata",
                      side_effect=lambda lead, campos, rotulo: carimbos.append(campos) or True), \
         patch.object(effects, "_mover_deal"), patch.object(effects, "anotar"), \
         patch("app.leads.repasse.registrar_repasse", return_value=True) as rr:
        effects._aplicar_handoff(lead, "C1", vendedor=vendedor)
    return carimbos[0]["handoff"], rr.call_args.kwargs


def test_botoes_arthur_carimba_id_do_arthur(tabela):
    h, kw = _aplicar({"id": "L1", "stage": "qualificando", "segmento": "exportacao"}, "Arthur")
    assert h["vendedor_id"] == "u-arthur" and h["vendedor"] == "Arthur"
    assert kw["vendedor_id"] == "u-arthur" and kw["segmento"] == "exportacao"


def test_botoes_default_supervisor_resolve_o_joao(tabela):
    h, kw = _aplicar({"id": "L1", "stage": "atacado"}, None)
    assert h["vendedor_id"] == "u-joao" and h["vendedor"] == "João Brás"
    assert kw["vendedor_id"] == "u-joao" and kw["segmento"] == "atacado"


def test_botoes_tabela_vazia_mantem_nome(tabela_vazia):
    h, kw = _aplicar({"id": "L1", "stage": "triagem"}, "Joao Bras")
    assert h["vendedor_id"] is None and h["vendedor"] == "Joao Bras"
    assert kw["segmento"] is None


# ─────────────────────────────────────────────── ponte pós-handoff

def test_ponte_resolve_pelo_id_primeiro(tabela):
    from app.buffer.processor import _vendedor_da_ponte
    lead = {"metadata": {"handoff": {"vendedor_id": "u-arthur", "vendedor": "Joao Bras"}}}
    assert _vendedor_da_ponte(lead)[:2] == (EXPORTACAO_NAME, EXPORTACAO_PHONE)
    lead = {"metadata": {"handoff": {"vendedor_id": "u-joao", "vendedor": "Arthur"}}}
    assert _vendedor_da_ponte(lead)[:2] == (SUPERVISOR_NAME, SUPERVISOR_PHONE)


def test_ponte_sem_id_usa_o_nome(tabela):
    from app.buffer.processor import _vendedor_da_ponte
    lead = {"metadata": {"handoff": {"vendedor": "Arthur"}}}
    assert _vendedor_da_ponte(lead)[:2] == (EXPORTACAO_NAME, EXPORTACAO_PHONE)
    lead = {"metadata": {"handoff": {"vendedor_id": "u-desconhecido", "vendedor": "Arthur"}}}
    assert _vendedor_da_ponte(lead)[:2] == (EXPORTACAO_NAME, EXPORTACAO_PHONE)


# ─────────────────────────────────────────────── qualificar_lead

def _qualificar_mocks(monkeypatch, lead):
    reg = {"msgs": [], "score": []}
    monkeypatch.setattr(tools, "get_lead", lambda lead_id: dict(lead))
    monkeypatch.setattr(tools, "update_lead", lambda lead_id, **kw: None)
    monkeypatch.setattr(tools, "save_message",
                        lambda lead_id, role, content, *a, **k: reg["msgs"].append(content) or {})
    monkeypatch.setattr(tools, "save_score_evidence", lambda *a, **k: reg["score"].append(k))
    monkeypatch.setattr(tools, "_validated_score_evidence", lambda *a, **k: {})
    return reg


async def _qualificar(args):
    return await tools.execute_tool("qualificar_lead", args, lead_id="L1",
                                    phone="5511999999999", conversation_id="C1")


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {},
    {"finalidade": "revenda"},          # igual à âncora já gravada
    {"finalidade": "  revenda "},
    {"volume": "", "urgencia": None},
])
async def test_qualificar_sem_ancora_nova_nao_grava_marcador(monkeypatch, args):
    lead = {"id": "L1", "stage": "qualificando", "segmento": "atacado",
            "metadata": {"qualificacao": {"finalidade": "revenda"}}}
    reg = _qualificar_mocks(monkeypatch, lead)
    await _qualificar(args)
    assert not [m for m in reg["msgs"] if m.startswith("[qualificar_lead]")]


@pytest.mark.asyncio
async def test_qualificar_com_ancora_nova_grava_marcador(monkeypatch):
    lead = {"id": "L1", "stage": "qualificando", "segmento": "atacado",
            "metadata": {"qualificacao": {"finalidade": "revenda"}}}
    reg = _qualificar_mocks(monkeypatch, lead)
    await _qualificar({"urgencia": "esta semana"})
    marcadores = [m for m in reg["msgs"] if m.startswith("[qualificar_lead]")]
    assert marcadores == ["[qualificar_lead] finalidade=revenda volume=None urgencia=esta semana"]


SCORE = {"segment": "cafeteria", "monthly_volume_kg": 30}


@pytest.mark.asyncio
async def test_score_grava_para_segmento_b2b_em_leads_segmento(monkeypatch):
    reg = _qualificar_mocks(monkeypatch, {"id": "L1", "stage": "qualificando",
                                          "segmento": "private_label", "metadata": {}})
    with patch.object(tools, "lead_e_b2b", return_value=False) as b2b:
        await _qualificar(dict(SCORE))
    assert len(reg["score"]) == 1
    b2b.assert_not_called()


@pytest.mark.asyncio
async def test_score_grava_para_lead_b2b_sem_segmento(monkeypatch):
    reg = _qualificar_mocks(monkeypatch, {"id": "L1", "stage": "triagem", "metadata": {}})
    with patch.object(tools, "lead_e_b2b", return_value=True) as b2b:
        await _qualificar(dict(SCORE))
    assert len(reg["score"]) == 1
    b2b.assert_called_once_with("L1")


@pytest.mark.asyncio
async def test_score_nao_grava_para_nao_b2b(monkeypatch):
    reg = _qualificar_mocks(monkeypatch, {"id": "L1", "stage": "qualificando",
                                          "segmento": "consumo", "metadata": {}})
    with patch.object(tools, "lead_e_b2b", return_value=False):
        await _qualificar(dict(SCORE))
    assert reg["score"] == []


# ─────────────────────────────────────────────── marcar_interesse

@pytest.mark.asyncio
@pytest.mark.parametrize("nivel,move", [("quente", True), ("morno", False), ("frio", False)])
async def test_marcar_interesse_so_move_com_quente(monkeypatch, nivel, move):
    monkeypatch.setattr(tools, "get_lead",
                        lambda lead_id: {"id": "L1", "stage": "qualificando", "segmento": "atacado"})
    with patch.object(tools, "mark_deal_qualificado") as mdq:
        res = await tools.execute_tool("marcar_interesse", {"nivel": nivel, "motivo": "x"},
                                       lead_id="L1", phone="5511", conversation_id="C-mi-" + nivel)
    tools.pop_interest_marked("C-mi-" + nivel)
    assert nivel in res
    if move:
        mdq.assert_called_once_with("L1", "atacado")
    else:
        mdq.assert_not_called()


# ─────────────────────────────────────────────── retomar_contato_vendedor

@pytest.mark.asyncio
async def test_retomada_cria_card_pelo_segmento(monkeypatch):
    lead = {"id": "L1", "stage": "qualificando", "segmento": "private_label",
            "metadata": {"handoff_summary": "x"}, "name": "Ana"}
    creates = []
    monkeypatch.setattr(tools, "get_lead", lambda lead_id: dict(lead))
    monkeypatch.setattr(tools, "update_lead", lambda *a, **k: None)
    monkeypatch.setattr(tools, "move_open_deal_for_handoff", lambda *a, **k: None)
    monkeypatch.setattr(tools, "create_deal", lambda lead_id, title, **kw: creates.append(kw))
    monkeypatch.setattr(tools, "save_message", lambda *a, **k: {})
    monkeypatch.setattr(tools, "_safe_schedule_reengage", lambda *a, **k: None)
    with patch("app.follow_up.service.is_within_business_window", return_value=False):
        await tools.execute_tool("retomar_contato_vendedor", {"motivo": "voltou"},
                                 lead_id="L1", phone="5511", conversation_id="C1")
    assert creates == [{"category": "private_label", "dedupe_open": True}]


# ─────────────────────────────────────────────── summary

def test_briefing_de_fallback_usa_segmento():
    from app.agent.summary import _fallback_briefing
    txt = _fallback_briefing([], {"name": "Ana", "stage": "qualificando", "segmento": "atacado"},
                             "m", None)
    assert "**Interesse Principal:** atacado" in txt
    txt = _fallback_briefing([], {"name": "Ana", "stage": "triagem"}, "m", None)
    assert "**Interesse Principal:** Não informado" in txt


@pytest.mark.asyncio
async def test_resumo_informa_segmento_ao_modelo():
    from app.agent import summary
    capt = {}

    async def fake_generate(model, contents, **kw):
        capt["ctx"] = str(contents)
        return MagicMock(text="ok", usage_metadata=None)

    with patch.object(summary, "generate", fake_generate), \
         patch.object(summary, "user_content", lambda t: t):
        await summary.generate_qualification_summary(
            [{"role": "user", "content": "oi"}],
            {"name": "Ana", "stage": "qualificando", "segmento": "private_label"}, "m")
    assert "Segmento identificado: private_label" in capt["ctx"]
