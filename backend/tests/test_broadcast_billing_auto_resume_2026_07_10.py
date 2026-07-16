"""Auto-resume de broadcast pausado por billing (wartime T4, 10/07).

`pause_broadcast_for_billing` pausava, mas NÃO existia resume: quando a Meta
normalizava o billing (health check horário auto-resolve o alerta), os broadcasts
ficavam pausados até alguém lembrar — janela de disparo perdida + toil.

Contratos fixados aqui (critério de aceite 3 da spec):
  - ao pausar por billing, grava marcador Redis `billing:paused_broadcast:{id}`
    TTL 7d, best-effort (Redis fora → resume manual, status quo, sem regressão);
  - `resume_broadcasts_after_billing` retoma SÓ broadcasts ainda 'paused' com
    marcador (update guardado), com wake-up + alerta warning `broadcast_auto_resumed`;
  - broadcast mexido pelo operador (status != paused) → só consome o marcador,
    a decisão humana vence;
  - fail-soft total: Redis/banco fora nunca derrubam o health check chamador.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import app.broadcast.service as svc


# ─── marcador no pause ────────────────────────────────────────────────────────

def test_pause_por_billing_grava_marcador_redis_ttl_7d():
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.in_.return_value.execute.return_value.data = [{"id": "bc-1"}]
    fake_redis = MagicMock()

    with patch.object(svc, "get_supabase", return_value=mock_sb), \
         patch.object(svc, "_get_redis", return_value=fake_redis):
        assert svc.pause_broadcast_for_billing("bc-1") is True

    fake_redis.set.assert_called_once_with(
        "billing:paused_broadcast:bc-1", "1", ex=7 * 24 * 3600,
    )


def test_pause_sem_linha_afetada_nao_grava_marcador():
    """Idempotência: broadcast já paused/completed → nada pausado → sem marcador."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.in_.return_value.execute.return_value.data = []
    fake_redis = MagicMock()

    with patch.object(svc, "get_supabase", return_value=mock_sb), \
         patch.object(svc, "_get_redis", return_value=fake_redis):
        assert svc.pause_broadcast_for_billing("bc-1") is False

    fake_redis.set.assert_not_called()


def test_redis_fora_no_pause_nao_quebra_o_pause():
    """Best-effort: marcador perdido = resume manual (status quo), nunca exceção."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.in_.return_value.execute.return_value.data = [{"id": "bc-1"}]

    with patch.object(svc, "get_supabase", return_value=mock_sb), \
         patch.object(svc, "_get_redis", side_effect=ConnectionError("redis down")):
        assert svc.pause_broadcast_for_billing("bc-1") is True  # o pause em si venceu


# ─── resume ───────────────────────────────────────────────────────────────────

def _resume_sb(status_by_id):
    """Supabase fake: UPDATE guardado por eq(status='paused') devolve linha só se
    o broadcast ainda estiver paused (espelha o guard real)."""
    sb = MagicMock()

    def _eq_id(field, broadcast_id):
        assert field == "id"
        second = MagicMock()

        def _eq_status(field2, value2):
            assert (field2, value2) == ("status", "paused")
            final = MagicMock()
            final.execute.return_value.data = (
                [{"id": broadcast_id}] if status_by_id.get(broadcast_id) == "paused" else []
            )
            return final

        second.eq.side_effect = _eq_status
        return second

    sb.table.return_value.update.return_value.eq.side_effect = _eq_id
    return sb


def test_resume_retoma_so_paused_consome_marcadores_e_alerta():
    """b1 ainda paused → running + wake-up + alerta warning; b2 mexido pelo operador
    (running de novo) → só DEL do marcador."""
    fake_redis = MagicMock()
    fake_redis.scan_iter.return_value = [
        "billing:paused_broadcast:b1",
        "billing:paused_broadcast:b2",
    ]
    sb = _resume_sb({"b1": "paused", "b2": "running"})
    emitted = []

    with patch.object(svc, "_get_redis", return_value=fake_redis), \
         patch.object(svc, "get_supabase", return_value=sb), \
         patch("app.events.bus.emit_event", side_effect=lambda d, p=None: emitted.append(d)), \
         patch("app.alerts.service.create_system_alert") as mock_alert:
        resumed = svc.resume_broadcasts_after_billing()

    assert resumed == 1
    assert emitted == ["broadcasts"]  # wake-up só para quem foi retomado
    mock_alert.assert_called_once()
    args, kwargs = mock_alert.call_args
    assert args[0] == "broadcast_auto_resumed"
    assert kwargs.get("severity") == "warning"
    assert kwargs.get("metadata", {}).get("broadcast_id") == "b1"
    # AMBOS os marcadores consumidos (decisão humana vence, mas o marcador morre)
    deleted = {c[0][0] for c in fake_redis.delete.call_args_list}
    assert deleted == {"billing:paused_broadcast:b1", "billing:paused_broadcast:b2"}


def test_resume_redis_fora_e_fail_soft():
    with patch.object(svc, "_get_redis", side_effect=ConnectionError("redis down")):
        assert svc.resume_broadcasts_after_billing() == 0


def test_resume_erro_de_banco_preserva_o_marcador_para_a_proxima_passada():
    """Update falhou p/ o id → NÃO deleta o marcador (o próximo health check retenta)."""
    fake_redis = MagicMock()
    fake_redis.scan_iter.return_value = ["billing:paused_broadcast:b1"]
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.side_effect = RuntimeError("db down")

    with patch.object(svc, "_get_redis", return_value=fake_redis), \
         patch.object(svc, "get_supabase", return_value=sb):
        assert svc.resume_broadcasts_after_billing() == 0

    fake_redis.delete.assert_not_called()


# ─── hook no health check horário ─────────────────────────────────────────────

def test_health_check_sem_billing_chama_o_resume_fail_soft():
    """O ramo que auto-resolve alertas de billing dispara o auto-resume (1 chamada)."""
    from datetime import datetime, timezone
    import app.follow_up.scheduler as sched

    logs_t = MagicMock()
    logs_t.select.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    alerts_t = MagicMock()
    alerts_t.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    sb = MagicMock()
    sb.table.side_effect = lambda name: logs_t if name == "meta_webhook_logs" else alerts_t

    with patch.object(sched, "get_supabase", return_value=sb), \
         patch("app.broadcast.service.resume_broadcasts_after_billing") as mock_resume:
        asyncio.run(sched._health_check_via_logs(datetime.now(timezone.utc)))

    mock_resume.assert_called_once()


def test_health_check_com_billing_ativo_nao_chama_o_resume():
    """Com erro 131042 nos logs da última hora, NADA de resume (billing ainda quebrado)."""
    from datetime import datetime, timezone
    import app.follow_up.scheduler as sched

    logs_t = MagicMock()
    logs_t.select.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": "log-1", "payload": {"errors": [{"code": 131042}]}},
    ]
    sb = MagicMock()
    sb.table.side_effect = lambda name: logs_t if name == "meta_webhook_logs" else MagicMock()

    with patch.object(sched, "get_supabase", return_value=sb), \
         patch("app.alerts.service.fire_billing_alert", new_callable=AsyncMock) as mock_fire, \
         patch("app.broadcast.service.resume_broadcasts_after_billing") as mock_resume:
        asyncio.run(sched._health_check_via_logs(datetime.now(timezone.utc)))

    mock_resume.assert_not_called()
    mock_fire.assert_called_once()
