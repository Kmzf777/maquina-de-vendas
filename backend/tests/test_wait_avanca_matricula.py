"""O no `wait` tem de AGENDAR O PROXIMO no, nao estacionar em si mesmo.

Havia um teste da funcao pura `_wait_target` (test_wait_node_hours_2026_07_11.py), que
confere a ARITMETICA do instante. Ninguem testava o CONTROLE DE FLUXO. O resultado:
existe um unico ponto que muda `current_node_id` (engine.py:367) e o ramo do `wait` dava
`return` antes dele — a matricula reagendava o mesmo `wait` a cada tick, para sempre, e
nenhuma cadencia de dois ou mais toques podia funcionar.

MEDICAO (11/09/2026): campaign_enrollments = 0 linhas em toda a historia. O motor nunca
rodou, e por isso ninguem descobriu.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.automation import engine

NOW = datetime(2026, 9, 11, 13, 0, tzinfo=timezone.utc)  # 10:00 BRT, dentro da janela

WAIT_NODE = {
    "id": "no-wait",
    "type": "wait",
    "config": {"days": 1, "hours": 0},
    "next_node_id": "no-envio-2",
    "yes_node_id": None,
    "no_node_id": None,
}

ENROLLMENT = {
    "id": "matricula-1",
    "lead_id": "lead-1",
    "campaign_id": "camp-1",
    "current_node_id": "no-wait",
    "step_count": 3,
    "last_sent_node_id": "no-envio-1",
    "campaign_nodes": WAIT_NODE,
    "leads": {"id": "lead-1", "phone": "5534988861441", "ai_enabled": False},
    "campaigns": {"id": "camp-1", "status": "active", "audience": "humano"},
    "metadata": {},
}


def _rodar_wait():
    """Executa _process_one num no `wait` e devolve os kwargs de cada _update."""
    chamadas = []
    with patch.object(engine, "_update", side_effect=lambda eid, **kw: chamadas.append(kw)), \
         patch.object(engine, "_log_exec"), \
         patch.object(engine, "_guard_broken", return_value=False), \
         patch.object(engine, "_conversation_followup_disabled", return_value=False), \
         patch.object(engine, "_audience_allows", return_value=True), \
         patch.object(engine, "get_supabase", MagicMock()):
        import asyncio
        asyncio.run(engine._process_one(dict(ENROLLMENT), NOW))
    return chamadas


def test_wait_avanca_para_o_proximo_no():
    """O CRITERIO DE APROVACAO do ensaio: current_node_id MUDA ao passar por um wait."""
    chamadas = _rodar_wait()
    assert chamadas, "_process_one nao escreveu nada — o no wait foi ignorado"
    avanco = [c for c in chamadas if "current_node_id" in c]
    assert avanco, (
        "o no wait nao mudou current_node_id — a matricula estaciona nele para sempre"
    )
    assert avanco[-1]["current_node_id"] == "no-envio-2"


def test_wait_agenda_o_proximo_no_para_o_futuro():
    """Avancar sem adiar transformaria o wait em no-op: o proximo toque sairia no mesmo tick."""
    chamadas = _rodar_wait()
    agendamento = [c for c in chamadas if "next_execute_at" in c]
    assert agendamento, "o no wait nao agendou nada"
    alvo = datetime.fromisoformat(agendamento[-1]["next_execute_at"])
    assert alvo > NOW, f"o wait agendou para {alvo}, que nao e depois de {NOW}"


def test_wait_incrementa_step_count():
    """Sem isso o anti-loop MAX_STEPS nunca ve os ciclos que passam por wait."""
    chamadas = _rodar_wait()
    passo = [c for c in chamadas if "step_count" in c]
    assert passo, "o no wait nao incrementou step_count"
    assert passo[-1]["step_count"] == ENROLLMENT["step_count"] + 1


def test_wait_limpa_last_sent_node_id():
    """`last_sent_node_id` e a idempotencia do envio. Carregado para o proximo no, ele
    faria o envio seguinte ser pulado como se ja tivesse acontecido."""
    chamadas = _rodar_wait()
    limpeza = [c for c in chamadas if "last_sent_node_id" in c]
    assert limpeza, "o no wait nao limpou last_sent_node_id"
    assert limpeza[-1]["last_sent_node_id"] is None


def test_wait_sem_proximo_no_encerra_em_vez_de_estacionar():
    """Wait que e o ultimo no do grafo: o fluxo acabou. Estacionar criaria zumbi."""
    enrollment = dict(ENROLLMENT)
    enrollment["campaign_nodes"] = {**WAIT_NODE, "next_node_id": None}
    completados = []
    with patch.object(engine, "_update", side_effect=lambda eid, **kw: None), \
         patch.object(engine, "_complete", side_effect=lambda eid: completados.append(eid)), \
         patch.object(engine, "_log_exec"), \
         patch.object(engine, "_guard_broken", return_value=False), \
         patch.object(engine, "_conversation_followup_disabled", return_value=False), \
         patch.object(engine, "_audience_allows", return_value=True), \
         patch.object(engine, "get_supabase", MagicMock()):
        import asyncio
        asyncio.run(engine._process_one(enrollment, NOW))
    assert completados == ["matricula-1"], "wait sem proximo no deveria completar a matricula"
