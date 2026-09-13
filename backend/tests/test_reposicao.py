# backend/tests/test_reposicao.py
import app.leads.reposicao as rep


# Task 6 (10/09/2026): o funil mudou de nome de novo ("João - Reposição" →
# "João - Reposição Atacado") e passou a existir um segundo funil de reposição
# (Private Label) — REPOSICAO_PIPELINE_NAME foi REMOVIDA porque nome já quebrou em
# silêncio duas vezes (09/09 e 10/09/2026). O que este teste protegia — "o card de
# reposição vai para o funil de reposição certo, não para qualquer um" — continua
# valendo; só o mecanismo mudou, de nome para UUID resolvido a partir do funil de
# ORIGEM (reposicao.reposicao_pipeline_para). Confirmado por SELECT em 10/09/2026.
ATACADO_ORIGEM = "9706a14a-3d9a-413b-bceb-26838fc2cc45"      # João - Atacado
ATACADO_REPOSICAO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"   # João - Reposição Atacado


def test_ensure_reposicao_deal_creates_in_reposicao_pipeline(monkeypatch):
    calls = {}
    def fake_create_deal(lead_id, title, category=None, *, pipeline_name=None,
                          pipeline_id=None, stage_label=None, stage_key=None,
                          dedupe_open=False, dedupe_pipeline_id=None):
        calls.update(lead_id=lead_id, pipeline_id=pipeline_id, stage_key=stage_key,
                      dedupe_open=dedupe_open, dedupe_pipeline_id=dedupe_pipeline_id)
        return {"id": "d1"}
    monkeypatch.setattr(rep, "create_deal", fake_create_deal)
    monkeypatch.setattr(rep, "_pipeline_de_origem", lambda deal_id: ATACADO_ORIGEM)

    # A função pura que substitui a constante de nome: origem Atacado → destino
    # Reposição Atacado, pelo MESMO id que a constante antiga apontava.
    assert rep.reposicao_pipeline_para(ATACADO_ORIGEM) == ATACADO_REPOSICAO

    rep.ensure_reposicao_deal("lead-1", deal_id="deal-atacado")
    assert calls["lead_id"] == "lead-1"
    assert calls["pipeline_id"] == ATACADO_REPOSICAO
    assert calls["stage_key"] == "novo"
    assert calls["dedupe_open"] is True
    assert calls["dedupe_pipeline_id"] == ATACADO_REPOSICAO


def test_ensure_reposicao_deal_failsoft(monkeypatch):
    def boom(*a, **k): raise RuntimeError("db down")
    monkeypatch.setattr(rep, "create_deal", boom)
    # não deve levantar
    rep.ensure_reposicao_deal("lead-1")


class _FakeQ:
    def __init__(self, rows): self._rows = rows
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def execute(self):
        class R: pass
        r = R(); r.data = self._rows; return r


class _FakeSB:
    def __init__(self, deals, stages): self._d = deals; self._s = stages
    def table(self, name): return _FakeQ(self._d if name == "deals" else self._s)


def test_deal_is_won_true_when_stage_key_fechado_ganho(monkeypatch):
    sb = _FakeSB(deals=[{"stage_id": "s1"}], stages=[{"key": "fechado_ganho"}])
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert rep.deal_is_won("d1") is True


def test_deal_is_won_false_other_stage(monkeypatch):
    sb = _FakeSB(deals=[{"stage_id": "s1"}], stages=[{"key": "qualificado"}])
    monkeypatch.setattr(rep, "get_supabase", lambda: sb)
    assert rep.deal_is_won("d1") is False


# ── Task 4 tests ──────────────────────────────────────────────────────────────
import asyncio
import app.automation.triggers as trg


def test_fire_trigger_deal_won_calls_ensure(monkeypatch):
    # Task 6 (10/09/2026): ensure_reposicao_deal passou a receber deal_id (o destino
    # do card de reposição depende do funil de ORIGEM desse deal). O mock antigo
    # (lambda lid: ...) não aceitava o kwarg novo — a chamada real levantava TypeError,
    # engolida pelo try/except amplo de fire_trigger, e o teste falhava em silêncio
    # (called nunca era setado, mas sem crash à vista). Ajustado para aceitar deal_id
    # e, já que dá para ver agora, reforçado: confere também que o deal_id certo foi
    # repassado — antes essa checagem não existia porque o parâmetro não existia.
    called = {}
    def fake_ensure(lid, deal_id=None):
        called["lead"] = lid
        called["deal_id"] = deal_id
    monkeypatch.setattr(trg, "ensure_reposicao_deal", fake_ensure)
    monkeypatch.setattr(trg, "deal_is_won", lambda did: True)
    monkeypatch.setattr(trg, "_maybe_fire_stage_conversion", lambda lid, data: None)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("deal_stage_enter", "lead-9", {"deal_id": "d1"}))
    assert called.get("lead") == "lead-9"
    assert called.get("deal_id") == "d1"


def test_fire_trigger_sale_created_calls_ensure(monkeypatch):
    # Mesmo motivo da tradução acima (mock precisa aceitar deal_id) — e mesmo
    # reforço: confere que o deal_id do payload do evento chega intacto em
    # ensure_reposicao_deal.
    called = {}
    def fake_ensure(lid, deal_id=None):
        called["lead"] = lid
        called["deal_id"] = deal_id
    monkeypatch.setattr(trg, "ensure_reposicao_deal", fake_ensure)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("sale_created", "lead-7", {"value": 100, "deal_id": "d7"}))
    assert called.get("lead") == "lead-7"
    assert called.get("deal_id") == "d7"


def test_fire_trigger_non_won_stage_does_not_call_ensure(monkeypatch):
    called = {}
    monkeypatch.setattr(trg, "ensure_reposicao_deal", lambda lid: called.setdefault("lead", lid))
    monkeypatch.setattr(trg, "deal_is_won", lambda did: False)
    monkeypatch.setattr(trg, "_maybe_fire_stage_conversion", lambda lid, data: None)
    monkeypatch.setattr(trg, "get_campaigns_with_trigger_type", lambda t: [])
    asyncio.run(trg.fire_trigger("deal_stage_enter", "lead-1", {"deal_id": "d1"}))
    assert "lead" not in called
