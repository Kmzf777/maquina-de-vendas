"""TDD Onda 2: cadência outbound com nudge D+1 "Sim-e-sumiu" (auditoria 08/07).

Contexto: 4 leads do run de 08/07 responderam "Sim" ao template, ouviram o pitch e
sumiram — e NENHUM follow-up nasceu. Causa 1 (corrigida por migração 20260709): o
check constraint de `sequence` só aceitava (1,2) e TODO insert da cadência de 4
toques falhava com 23514 desde 26/06. Causa 2 (este teste): a cadência fria
(warm=False) começava no T2 (D+1 clampado à janela comercial), que para uma resposta
noturna cai FORA da janela de 24h da Meta — o toque virava template de reabertura em
vez de mensagem livre no calor da conversa.

O nudge outbound: primeiro toque a +18h (clampado), objetivo "retomar_pos_sim",
dentro da janela de 24h para qualquer resposta entre ~9h e ~22h.
"""
from datetime import datetime, timedelta, timezone

from app.follow_up.cadence import build_touch_jobs, CADENCE, MIN_GAP


_TZ_UTC = timezone.utc


def _mk(now, **kw):
    defaults = dict(
        conversation_id="conv-1", lead_id="lead-1", channel_id="ch-1", env_tag="production",
    )
    defaults.update(kw)
    return build_touch_jobs(now, **defaults)


def test_outbound_frio_comeca_com_nudge_18h():
    """warm=False + outbound=True → 1º job é o nudge retomar_pos_sim ~+18h."""
    # 21:36 BRT (00:36 UTC do dia seguinte) — o horário real do "Sim" do run de 08/07.
    now = datetime(2026, 7, 9, 0, 36, tzinfo=_TZ_UTC)
    jobs = _mk(now, warm=False, outbound=True)

    first = jobs[0]
    assert first["metadata"]["objetivo"] == "retomar_pos_sim"
    assert first["sequence"] == 1
    fire_at = datetime.fromisoformat(first["fire_at"])
    # +18h cai às 18:36 UTC (15:36 BRT) — dentro da janela comercial, sem clamp.
    assert fire_at == now + timedelta(hours=18)
    # E dentro da janela de 24h da Meta (o ponto inteiro do nudge).
    assert fire_at < now + timedelta(hours=24)


def test_outbound_frio_mantem_cadencia_seguinte():
    """Depois do nudge vêm os toques T2..T4 da cadência padrão, monotônicos."""
    now = datetime(2026, 7, 9, 0, 36, tzinfo=_TZ_UTC)
    jobs = _mk(now, warm=False, outbound=True)

    assert len(jobs) == 1 + len(CADENCE[1:])
    objetivos = [j["metadata"]["objetivo"] for j in jobs]
    assert objetivos == ["retomar_pos_sim", "reforco_valor", "prova_social", "ultima_chamada"]
    fires = [datetime.fromisoformat(j["fire_at"]) for j in jobs]
    for a, b in zip(fires, fires[1:]):
        assert b >= a + MIN_GAP


def test_outbound_quente_nao_troca_o_t1():
    """warm=True (interesse marcado) mantém a cadência padrão mesmo em outbound."""
    now = datetime(2026, 7, 9, 14, 0, tzinfo=_TZ_UTC)
    jobs = _mk(now, warm=True, outbound=True)
    assert jobs[0]["metadata"]["objetivo"] == "reengajar"
    assert len(jobs) == len(CADENCE)


def test_inbound_frio_sem_nudge():
    """outbound=False preserva o comportamento atual (T1 suprimido, começa no T2)."""
    now = datetime(2026, 7, 9, 14, 0, tzinfo=_TZ_UTC)
    jobs = _mk(now, warm=False, outbound=False)
    assert jobs[0]["metadata"]["objetivo"] == "reforco_valor"
    assert len(jobs) == len(CADENCE) - 1


def test_sequences_dentro_do_constraint():
    """Todas as sequences ficam em 1..9 (constraint 20260709) em todas as variantes."""
    now = datetime(2026, 7, 9, 14, 0, tzinfo=_TZ_UTC)
    for kw in (dict(warm=True), dict(warm=False), dict(warm=False, outbound=True),
               dict(warm=True, outbound=True)):
        for j in _mk(now, **kw):
            assert 1 <= j["sequence"] <= 9
