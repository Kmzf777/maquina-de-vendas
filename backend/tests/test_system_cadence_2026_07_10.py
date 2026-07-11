"""Espelho visual do motor de follow-up no builder de Cadências (10/07).

Fixa três contratos:
1. FIDELIDADE — o grafo é construído A PARTIR de cadence.py/scheduler (objective_prompt
   reais, template de reabertura e locale da Rodada 5), nunca de cópias.
2. VALIDADE p/ o builder — tipos de nó suportados, exatamente 1 trigger conectado,
   todo nó alcança um end, ids determinísticos (sync idempotente por construção).
3. SEGURANÇA DE EXECUÇÃO — campanha nasce draft e o router recusa activate/enroll/
   delete para o UUID de sistema (ativar duplicaria os toques do worker real).
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.campaigns.system_cadence import (
    VALERIA_CADENCE_CAMPAIGN_ID,
    build_valeria_cadence_graph,
    sync_valeria_cadence_campaign,
)
from app.follow_up.cadence import CADENCE, OUTBOUND_NUDGE

# Tipos que o builder React Flow renderiza (frontend/src/lib/types.ts CampaignNodeType)
_BUILDER_NODE_TYPES = {"trigger", "send", "send_text", "wait", "condition", "action", "end"}


def _graph():
    return build_valeria_cadence_graph()


def test_campaign_identity_and_never_active():
    campaign, _ = _graph()
    assert campaign["id"] == VALERIA_CADENCE_CAMPAIGN_ID
    assert campaign["id"] == "d4a7ffa3-62c2-51c4-91fc-5fcc06ec9055"  # literal duplicado no frontend
    assert campaign["status"] == "draft"
    assert "[SISTEMA]" in campaign["description"]


def test_nodes_are_valid_for_the_builder():
    _, nodes = _graph()
    assert all(n["type"] in _BUILDER_NODE_TYPES for n in nodes)
    triggers = [n for n in nodes if n["type"] == "trigger"]
    assert len(triggers) == 1
    assert triggers[0]["next_node_id"], "activate/enroll exigem trigger conectado; o espelho também"
    ids = {n["id"] for n in nodes}
    for n in nodes:
        for link in ("next_node_id", "yes_node_id", "no_node_id"):
            if n[link] is not None:
                assert n[link] in ids, f"{n['type']}.{link} aponta para nó inexistente"


def test_every_path_reaches_an_end():
    _, nodes = _graph()
    by_id = {n["id"]: n for n in nodes}
    trigger = next(n for n in nodes if n["type"] == "trigger")

    def reaches_end(node_id: str, seen: frozenset = frozenset()) -> bool:
        if node_id in seen:
            return False  # ciclo
        node = by_id[node_id]
        if node["type"] == "end":
            return True
        nxt = [node[k] for k in ("next_node_id", "yes_node_id", "no_node_id") if node[k]]
        if not nxt:
            return False
        return all(reaches_end(i, seen | {node_id}) for i in nxt)

    assert reaches_end(trigger["id"]), "todo caminho do fluxo deve terminar num nó end"


def test_deterministic_ids_make_sync_idempotent_by_construction():
    _, a = _graph()
    _, b = _graph()
    assert [n["id"] for n in a] == [n["id"] for n in b]


def test_fidelity_touch_texts_use_real_objective_prompts():
    _, nodes = _graph()
    texts = [n["config"].get("message_text", "") for n in nodes if n["type"] == "send_text"]
    assert len(texts) == 4  # T1..T4
    for touch, text in zip(CADENCE, texts):
        assert touch.objective_prompt.strip() in text, (
            f"toque seq={touch.sequence} não embute o objective_prompt real de cadence.py"
        )
    # T1 documenta jitter e nudge outbound reais
    assert f"+{CADENCE[0].jitter_minutes[0]}–{CADENCE[0].jitter_minutes[1]}min" in texts[0]
    assert f"+{int(OUTBOUND_NUDGE.offset.total_seconds() // 3600)}h" in texts[0]


def test_fidelity_reply_cancels_and_window_condition():
    _, nodes = _graph()
    for n in nodes:
        if n["type"] == "send_text":
            assert n["config"]["on_reply"] == "cancel", (
                "resposta do lead cancela/re-arma a cadência (schedule_followup)"
            )
    condition = next(n for n in nodes if n["type"] == "condition")
    assert condition["config"] == {"condition_type": "replied_recently", "days": 1}
    assert condition["yes_node_id"] and condition["no_node_id"]


def test_fidelity_reopen_node_matches_scheduler_constants():
    from app.follow_up.scheduler import _REOPEN_TEMPLATE_LANGUAGE, _REOPEN_TEMPLATE_NAME, _REOPEN_TOPIC
    _, nodes = _graph()
    reopen = next(n for n in nodes if n["type"] == "send")
    cfg = reopen["config"]
    assert cfg["template_name"] == _REOPEN_TEMPLATE_NAME
    assert cfg["template_language"] == _REOPEN_TEMPLATE_LANGUAGE
    assert cfg["template_variables"]["2"] == _REOPEN_TOPIC
    assert cfg["template_variables"]["__params_type__"] == "positional"
    assert cfg["on_reply"] == "pause"


def test_fidelity_wait_offsets():
    _, nodes = _graph()
    waits = [n["config"]["days"] for n in nodes if n["type"] == "wait"]
    assert waits == [1, 2, 4]  # D+1; +2 (→D+3); +4 (≈D+6h20)
    for n in nodes:
        if n["type"] == "wait":
            assert (n["config"]["send_start_hour"], n["config"]["send_end_hour"]) == (9, 16)


def test_sync_upserts_campaign_and_replaces_nodes_in_fk_safe_order():
    sb = MagicMock()
    with patch("app.campaigns.system_cadence.get_supabase", return_value=sb):
        assert sync_valeria_cadence_campaign() is True

    upsert_payload = sb.table.return_value.upsert.call_args[0][0]
    assert upsert_payload["id"] == VALERIA_CADENCE_CAMPAIGN_ID
    assert sb.table.return_value.delete.called
    rows = sb.table.return_value.insert.call_args[0][0]
    assert all(r["campaign_id"] == VALERIA_CADENCE_CAMPAIGN_ID for r in rows)
    # Ordem topológica reversa: cada link referencia um nó já inserido antes dele.
    seen: set = set()
    for r in rows:
        for link in ("next_node_id", "yes_node_id", "no_node_id"):
            if r[link] is not None:
                assert r[link] in seen, "insert deve vir em ordem topológica reversa (FK-safe)"
        seen.add(r["id"])


def test_sync_fails_open():
    with patch("app.campaigns.system_cadence.get_supabase", side_effect=RuntimeError("db down")):
        assert sync_valeria_cadence_campaign() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["activate", "enroll", "delete"])
async def test_router_rejects_system_campaign(endpoint):
    from app.campaigns import router as r

    with patch.object(r, "get_campaign", return_value={"id": VALERIA_CADENCE_CAMPAIGN_ID, "status": "draft"}), \
         patch.object(r, "list_nodes", return_value=[]), \
         patch.object(r, "is_already_enrolled", return_value=False), \
         patch.object(r, "update_campaign") as upd, \
         patch.object(r, "delete_campaign") as dele, \
         patch.object(r, "create_enrollment") as enr:
        with pytest.raises(HTTPException) as exc:
            if endpoint == "activate":
                await r.api_activate_campaign(VALERIA_CADENCE_CAMPAIGN_ID)
            elif endpoint == "enroll":
                await r.api_enroll_lead(VALERIA_CADENCE_CAMPAIGN_ID, r.EnrollRequest(lead_id="L1"))
            else:
                await r.api_delete_campaign(VALERIA_CADENCE_CAMPAIGN_ID)
        assert exc.value.status_code == 409
    assert not upd.called and not dele.called and not enr.called
