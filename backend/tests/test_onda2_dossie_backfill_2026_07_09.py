"""TDD Onda 2: dossiê consome histórico COMPLETO quando não há dossiê prévio.

Bug de arrasto do burn de 08/07: as 1.366 gerações que falharam no parse AVANÇARAM a
marca d'água (rolling_summary_updated_at) sem persistir dossiê nenhum. Resultado: o
lead tem rolling_summary NULL mas watermark recente — o delta seguinte vem vazio ou
minúsculo e a história anterior fica PERDIDA para a memória de longo prazo (Wander:
33 mensagens, dossiê em branco, watermark de ontem).

Correção: quando o lead NÃO tem dossiê, `refresh_lead_memory` ignora a marca d'água e
lê o histórico completo (since=None), capado nas últimas MEMORY_BACKFILL_MAX_MSGS
mensagens (prompt bounded). Com dossiê existente, o delta incremental continua igual.
O script scripts/backfill_dossies.py usa esse mesmo caminho para a base histórica.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.agent.memory_manager as MM


def _base_patches(lead, history):
    return [
        patch.object(MM, "get_supabase", return_value=MagicMock()),
        patch.object(MM, "_claim_lock", return_value=True),
        patch.object(MM, "_release_lock"),
        patch.object(MM, "get_lead", return_value=lead),
        # Emula a semântica real de get_history: latest=True devolve a janela das
        # `limit` mensagens mais recentes em ordem cronológica (o cap do backfill
        # passou do slice em memória para a query — fix P3 de 09/07).
        patch.object(
            MM, "get_history",
            side_effect=lambda lead_id, limit=30, since=None, latest=False: (
                history[-limit:] if latest else history[:limit]
            ),
        ),
        patch.object(MM, "update_lead"),
        patch.object(
            MM, "generate_rolling_summary",
            new=AsyncMock(return_value="## DOSSIÊ DO LEAD\n* **Perfil / Empresa:** X"),
        ),
    ]


@pytest.mark.asyncio
async def test_sem_dossie_ignora_watermark_e_le_historico_completo():
    lead = {
        "id": "lead-1", "stage": "private_label",
        "rolling_summary": None,
        # watermark avançada pelas gerações que falharam no parse (burn 08/07)
        "rolling_summary_updated_at": "2026-07-09T02:14:12+00:00",
    }
    history = [{"role": "user", "content": f"m{i}", "created_at": f"2026-07-08T2{i%4}:00:00+00:00"}
               for i in range(6)]
    patches = _base_patches(lead, history)
    with patches[0], patches[1], patches[2], patches[3], patches[4] as m_hist, \
         patches[5], patches[6]:
        ok = await MM.refresh_lead_memory("lead-1", model="m")

    assert ok is True
    # since=None → histórico completo, não o delta pós-watermark
    assert m_hist.call_args.kwargs.get("since") is None


@pytest.mark.asyncio
async def test_com_dossie_mantem_delta_incremental():
    lead = {
        "id": "lead-2", "stage": "atacado",
        "rolling_summary": "## DOSSIÊ DO LEAD\n* **Perfil / Empresa:** cafeteria",
        "rolling_summary_updated_at": "2026-07-08T10:00:00+00:00",
    }
    history = [{"role": "user", "content": "novidade", "created_at": "2026-07-09T09:00:00+00:00"}]
    patches = _base_patches(lead, history)
    with patches[0], patches[1], patches[2], patches[3], patches[4] as m_hist, \
         patches[5], patches[6]:
        await MM.refresh_lead_memory("lead-2", model="m")

    assert m_hist.call_args.kwargs.get("since") == "2026-07-08T10:00:00+00:00"


@pytest.mark.asyncio
async def test_historico_gigante_e_capado():
    """Prompt bounded: no caminho sem dossiê, só as últimas MEMORY_BACKFILL_MAX_MSGS
    mensagens entram no delta enviado ao LLM."""
    lead = {"id": "lead-3", "stage": "consumo", "rolling_summary": "",
            "rolling_summary_updated_at": None}
    history = [{"role": "user", "content": f"m{i}", "created_at": f"2026-07-0{1 + i % 8}T10:00:00+00:00"}
               for i in range(MM.MEMORY_BACKFILL_MAX_MSGS + 150)]
    patches = _base_patches(lead, history)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6] as m_gen:
        await MM.refresh_lead_memory("lead-3", model="m")

    delta = m_gen.await_args.args[1]
    assert len(delta) == MM.MEMORY_BACKFILL_MAX_MSGS
    # cap pega o FIM do histórico (mensagens mais recentes), não o começo
    assert delta[-1]["content"] == history[-1]["content"]
