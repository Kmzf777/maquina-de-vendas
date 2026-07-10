"""P3 — persistência do dossiê para leads sem rolling_summary (vítimas do burn 08/07
e conversas curtas) + histórico completo real no caminho sem dossiê prévio.

Bug 1: o worker pulava lead com rolling_summary NULL se o watermark estivesse
avançado (_summary_is_current não checava NULL) → o lead nunca era curado pela
via de produção.
Bug 2: get_history tem limit=30 default com ordem asc; o caminho "histórico
completo" (Onda 2) lia só as 30 mensagens MAIS ANTIGAS — o cap de 200 nunca agia.
"""
from unittest.mock import patch

from tests.test_memory_manager import _FakeSelSupabase


async def test_process_stale_nao_pula_lead_sem_dossie_com_watermark_avancado():
    """Vítima do burn: rolling_summary NULL + watermark >= last_msg → DEVE processar."""
    from app.agent import memory_manager as mm

    rows = [
        # watermark "em dia" mas SEM dossiê gravado (as gerações falharam no parse)
        {"id": "vitima_burn", "last_customer_message_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary_updated_at": "2026-07-08T19:00:00+00:00",
         "rolling_summary": None},
        # dossiê real e em dia → continua pulando
        {"id": "em_dia", "last_customer_message_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary_updated_at": "2026-07-08T18:00:00+00:00",
         "rolling_summary": "## DOSSIÊ DO LEAD\n- ..."},
    ]
    store = {"rows": rows, "filters": [], "limit": None}
    refreshed = []

    async def fake_refresh(lead_id, **k):
        refreshed.append(lead_id)
        return True

    with patch.object(mm, "get_supabase", return_value=_FakeSelSupabase(store)), \
         patch.object(mm, "refresh_lead_memory", new=fake_refresh):
        count = await mm.process_stale_lead_memories()

    assert refreshed == ["vitima_burn"]
    assert count == 1


async def test_refresh_sem_dossie_busca_mensagens_mais_recentes_com_cap():
    """Sem dossiê prévio: get_history recebe limit=MEMORY_BACKFILL_MAX_MSGS e
    latest=True (as MAIS RECENTES, não as 30 mais antigas do default)."""
    from app.agent import memory_manager as mm

    calls = {}

    def fake_get_history(lead_id, limit=30, since=None, latest=False):
        calls["limit"] = limit
        calls["since"] = since
        calls["latest"] = latest
        return [{"role": "user", "content": "oi", "created_at": "2026-07-08T18:00:00+00:00"}]

    async def fake_generate(prior, delta, client, model, **k):
        return "## DOSSIÊ DO LEAD\n- novo"

    with patch.object(mm, "get_supabase"), \
         patch.object(mm, "_claim_lock", return_value=True), \
         patch.object(mm, "_release_lock"), \
         patch.object(mm, "get_lead", return_value={"rolling_summary": None,
                                                    "rolling_summary_updated_at": "2026-07-08T19:00:00+00:00"}), \
         patch.object(mm, "get_history", new=fake_get_history), \
         patch.object(mm, "generate_rolling_summary", new=fake_generate), \
         patch.object(mm, "update_lead") as upd:
        ok = await mm.refresh_lead_memory("lead-1", client=object())

    assert ok is True
    assert calls["since"] is None  # watermark ignorado sem dossiê (Onda 2)
    assert calls["limit"] == mm.MEMORY_BACKFILL_MAX_MSGS  # cap efetivo, não 30
    assert calls["latest"] is True  # janela das mais recentes
    assert upd.called


def test_get_history_latest_retorna_janela_mais_recente_em_ordem_cronologica():
    """latest=True: consulta desc + limit e devolve em ordem asc (mais antiga→recente)."""
    from app.leads import service as leads_service

    class _Result:
        data = [
            {"content": "m3", "created_at": "2026-07-08T18:03:00+00:00"},
            {"content": "m2", "created_at": "2026-07-08T18:02:00+00:00"},
        ]

    class _Query:
        def __init__(self):
            self.order_kwargs = None
            self.limit_val = None

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def gt(self, *a, **k):
            return self

        def order(self, col, desc=False):
            self.order_kwargs = {"col": col, "desc": desc}
            return self

        def limit(self, n):
            self.limit_val = n
            return self

        def execute(self):
            return _Result()

    q = _Query()

    class _Supa:
        def table(self, name):
            return q

    with patch.object(leads_service, "get_supabase", return_value=_Supa()):
        out = leads_service.get_history("lead-1", limit=2, latest=True)

    assert q.order_kwargs == {"col": "created_at", "desc": True}
    assert q.limit_val == 2
    assert [m["content"] for m in out] == ["m2", "m3"]  # devolvido cronológico
