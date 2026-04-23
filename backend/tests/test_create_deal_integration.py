"""Integration tests: create_deal deve rotear deal para pipeline correto, coluna Novo.

Requisitos: .env.local com SUPABASE_URL e SUPABASE_SERVICE_KEY reais.
Executar: cd backend && python -m pytest tests/test_create_deal_integration.py -v -m integration
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND / ".env", override=True)

_REAL_SUPABASE = "tshmvxxxyxgctrdkqvam" in os.environ.get("SUPABASE_URL", "")
pytestmark = pytest.mark.skipif(not _REAL_SUPABASE, reason="Requer Supabase real (.env.local)")

# Lead de teste que existe no banco (seed)
_TEST_LEAD_ID = "11111111-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def cleanup_test_deals():
    yield
    from app.db.supabase import get_supabase
    get_supabase().table("deals").delete().like("title", "[TEST-PIPELINE]%").execute()


def _get_expected_pipeline(sb, pipeline_name: str) -> tuple[str, str, str]:
    """Retorna (pipeline_id, first_stage_id, first_stage_label) para o pipeline dado."""
    p = sb.table("pipelines").select("id").eq("name", pipeline_name).limit(1).execute()
    assert p.data, f"Pipeline '{pipeline_name}' não encontrado no banco"
    pipeline_id = p.data[0]["id"]

    s = (
        sb.table("pipeline_stages")
        .select("id, label")
        .eq("pipeline_id", pipeline_id)
        .eq("is_protected", False)
        .order("order_index", desc=False)
        .limit(1)
        .execute()
    )
    assert s.data, f"Nenhum stage não-protegido em '{pipeline_name}'"
    return pipeline_id, s.data[0]["id"], s.data[0]["label"]


@pytest.mark.integration
@pytest.mark.parametrize("category,pipeline_name", [
    ("atacado", "Atacado"),
    ("private_label", "Private Label"),
    ("exportacao", "Exportação"),
])
def test_deal_aparece_em_pipeline_correto_coluna_novo(category, pipeline_name):
    """create_deal(category=X) deve criar deal no pipeline X, primeira coluna 'Novo'."""
    from app.db.supabase import get_supabase
    from app.leads.service import create_deal

    sb = get_supabase()
    expected_pipeline_id, expected_stage_id, expected_stage_label = _get_expected_pipeline(sb, pipeline_name)

    deal = create_deal(_TEST_LEAD_ID, title=f"[TEST-PIPELINE] {category}", category=category)

    assert deal["pipeline_id"] == expected_pipeline_id, (
        f"[{category}] pipeline_id errado: esperado '{pipeline_name}' ({expected_pipeline_id}), got {deal['pipeline_id']}"
    )
    assert deal["stage_id"] == expected_stage_id, (
        f"[{category}] stage_id errado: esperado '{expected_stage_label}' ({expected_stage_id}), got {deal['stage_id']}"
    )
    assert expected_stage_label.lower() == "novo", (
        f"Primeiro stage de '{pipeline_name}' deveria ser 'Novo', mas é '{expected_stage_label}'"
    )

    # Verificação independente: buscar deal no banco e confirmar via query separada
    persisted = (
        sb.table("deals")
        .select("id, pipeline_id, stage_id")
        .eq("id", deal["id"])
        .limit(1)
        .execute()
    ).data[0]

    assert persisted["pipeline_id"] == expected_pipeline_id, (
        f"[{category}] No banco: pipeline_id incorreto após INSERT"
    )
    assert persisted["stage_id"] == expected_stage_id, (
        f"[{category}] No banco: stage_id incorreto após INSERT — deal não está em 'Novo'"
    )
