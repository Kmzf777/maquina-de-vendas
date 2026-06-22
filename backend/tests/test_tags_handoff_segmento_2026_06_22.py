"""P1 (tags autônomas) + P2 (handoff por segmento) — auditoria 2026-06-22."""
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock
import app.agent.tools as tools


# --- P1: tool adicionar_tag_lead ----------------------------------------

def test_tag_tool_registrada_em_todos_os_stages():
    for stage in ("secretaria", "atacado", "private_label", "exportacao", "consumo"):
        names = [t["function"]["name"] for t in tools.get_tools_for_stage(stage)]
        assert "adicionar_tag_lead" in names, f"ausente no stage {stage}"


def test_tag_schema_enum_bate_com_allowlist():
    schema = next(t for t in tools.TOOLS_SCHEMA if t["function"]["name"] == "adicionar_tag_lead")
    enum = set(schema["function"]["parameters"]["properties"]["tags"]["items"]["enum"])
    assert enum == set(tools._TAG_ALLOWLIST)


@pytest.mark.asyncio
async def test_tag_invalida_e_descartada():
    """IA não consegue aplicar tag fora da allowlist (nem chega no add_tags_to_lead)."""
    with patch.object(tools, "add_tags_to_lead") as mock_add:
        out = await tools.execute_tool(
            "adicionar_tag_lead", {"tags": ["b2b", "Cliente_Novo", "lixo"]},
            "L1", "5511999", "conv-1",
        )
    mock_add.assert_not_called()
    assert "Nenhuma tag válida" in out


@pytest.mark.asyncio
async def test_tag_valida_aplicada():
    with patch.object(tools, "add_tags_to_lead", return_value=["B2B", "Urgente"]) as mock_add:
        out = await tools.execute_tool(
            "adicionar_tag_lead", {"tags": ["B2B", "Urgente"]},
            "L1", "5511999", "conv-1",
        )
    mock_add.assert_called_once_with("L1", ["B2B", "Urgente"])
    assert "Tags aplicadas: B2B, Urgente" in out


@pytest.mark.asyncio
async def test_tag_mix_valida_e_invalida_so_aplica_valida():
    with patch.object(tools, "add_tags_to_lead", return_value=["Marca Própria"]) as mock_add:
        out = await tools.execute_tool(
            "adicionar_tag_lead", {"tags": ["Marca Própria", "b2b"]},
            "L1", "5511999", "conv-1",
        )
    mock_add.assert_called_once_with("L1", ["Marca Própria"])  # 'b2b' descartada
    assert "Marca Própria" in out


# --- P1: add_tags_to_lead (busca segura por nome + dedupe) ---------------

class _Resp:
    def __init__(self, data): self.data = data

class _Q:
    def __init__(self, sink): self.sink = sink; self._table = None; self._inserted = None
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def insert(self, rows): self._inserted = rows; self.sink["inserted"] = rows; return self
    def execute(self):
        if self._inserted is not None:
            return _Resp(self._inserted)
        return _Resp(self.sink["responses"].get(self._table, []))

class _SB:
    def __init__(self, sink): self.sink = sink
    def table(self, name):
        q = _Q(self.sink); q._table = name; return q


def test_add_tags_to_lead_resolve_por_nome_e_dedupe():
    import app.leads.service as svc
    sink = {
        "responses": {
            "tags": [{"id": "t-b2b", "name": "B2B"}, {"id": "t-urg", "name": "Urgente"}],
            "lead_tags": [{"tag_id": "t-b2b"}],  # B2B já aplicada
        },
        "inserted": None,
    }
    with patch.object(svc, "get_supabase", return_value=_SB(sink)):
        applied = svc.add_tags_to_lead("L1", ["B2B", "Urgente"])
    assert applied == ["Urgente"]  # B2B deduplicada
    assert sink["inserted"] == [{"lead_id": "L1", "tag_id": "t-urg"}]


def test_add_tags_to_lead_ignora_nome_inexistente():
    import app.leads.service as svc
    sink = {"responses": {"tags": [], "lead_tags": []}, "inserted": None}
    with patch.object(svc, "get_supabase", return_value=_SB(sink)):
        applied = svc.add_tags_to_lead("L1", ["Inexistente"])
    assert applied == []


# --- P2: move_deal_to_vendor_pipeline por segmento ----------------------

def test_segment_handoff_map_exclui_consumo():
    import app.leads.service as svc
    assert svc.SEGMENT_HANDOFF_PIPELINE["atacado"] == "João - Atacado"
    assert svc.SEGMENT_HANDOFF_PIPELINE["private_label"] == "João - Private Label"
    assert svc.SEGMENT_HANDOFF_PIPELINE["exportacao"] == "Arthur - Exportação"
    assert "consumo" not in svc.SEGMENT_HANDOFF_PIPELINE


def test_move_deal_vendor_segmento_sem_pipeline_retorna_none():
    import app.leads.service as svc
    # consumo/secretaria não mapeados → None (sem tocar no banco)
    assert svc.move_deal_to_vendor_pipeline("L1", "consumo", title="x") is None
    assert svc.move_deal_to_vendor_pipeline("L1", None, title="x") is None


@pytest.mark.asyncio
async def test_handoff_roteia_por_segmento_atacado():
    """encaminhar_humano deve priorizar move_deal_to_vendor_pipeline (segmento)."""
    with patch.object(tools, "update_lead"), \
         patch.object(tools, "get_lead", return_value={"id": "L1", "stage": "atacado", "name": "Ana"}), \
         patch.object(tools, "move_deal_to_vendor_pipeline", return_value={"id": "d1"}) as mock_seg, \
         patch.object(tools, "move_open_deal_for_handoff") as mock_lp, \
         patch.object(tools, "create_deal") as mock_create, \
         patch.object(tools, "save_message"), \
         patch.object(tools, "get_channel_for_lead", return_value=None):
        await tools.execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "atacado qualificado"},
            "L1", "5511999", "conv-1",
        )
    mock_seg.assert_called_once()
    assert mock_seg.call_args.args[1] == "atacado"   # segmento = lead.stage
    mock_lp.assert_not_called()      # não cai no fallback LP
    mock_create.assert_not_called()  # nem no create


@pytest.mark.asyncio
async def test_handoff_consumo_cai_no_fallback():
    """Sem pipeline de vendedor (consumo) → usa o fallback (LP/create)."""
    with patch.object(tools, "update_lead"), \
         patch.object(tools, "get_lead", return_value={"id": "L2", "stage": "consumo", "name": "Bia"}), \
         patch.object(tools, "move_deal_to_vendor_pipeline", return_value=None) as mock_seg, \
         patch.object(tools, "move_open_deal_for_handoff", return_value=None) as mock_lp, \
         patch.object(tools, "create_deal") as mock_create, \
         patch.object(tools, "save_message"), \
         patch.object(tools, "get_channel_for_lead", return_value=None):
        await tools.execute_tool(
            "encaminhar_humano",
            {"vendedor": "Joao Bras", "motivo": "consumo"},
            "L2", "5511888", "conv-2",
        )
    mock_seg.assert_called_once()
    mock_lp.assert_called_once()       # fallback acionado
    mock_create.assert_called_once()   # e o create final


# --- prompt ---------------------------------------------------------------

def test_base_prompt_tem_regra_28_tags():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt("Ana", None, datetime(2026, 6, 22, 14, 0))
    assert "ETIQUETAR O LEAD (TAGS)" in s
    assert "adicionar_tag_lead" in s
