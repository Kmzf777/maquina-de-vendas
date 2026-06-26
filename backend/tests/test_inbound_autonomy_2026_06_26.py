"""Autonomia GLOBAL da Valéria (inbound incluído) — design 2026-06-26.

Generaliza o que o funil frio já tinha para TODOS os funis da Valéria, agora com vocabulário
de `key` unificado (migration 20260626):
  - Reflexo de reply genérico: card em novo/entrada/disparo_feito → 'respondeu' (nunca regride).
  - Criação adiada: quando a IA classifica o segmento (mudar_stage), nasce o card no funil dele.
  - marcar_interesse vira create-or-move: sem card, cria no funil do segmento já em 'qualificado'.
"""
from unittest.mock import patch
import pytest


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, fake):
        self.table = table
        self.fake = fake
        self.filters = {}
        self.op = "select"
        self.payload = None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, values):
        self.filters[("in", key)] = values
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(self.fake.resolve(self))


class FakeSupabase:
    def __init__(self, resolver, writes):
        self._resolver = resolver
        self.writes = writes

    def table(self, name):
        return _Query(name, self)

    def resolve(self, q):
        if q.op in ("update", "insert"):
            self.writes.append((q.op, q.table, q.payload, q.filters))
            payload = q.payload if isinstance(q.payload, dict) else {}
            return [{**payload, "id": q.filters.get("id", "new-deal")}]
        return self._resolver(q.table, q.filters)


# Funil de segmento pós-migration 20260626 (keys unificadas).
PL_ATACADO = "pl-atacado"
ST_ENTRADA = "st-entrada"
ST_NOVO = "st-novo"
ST_RESPONDEU = "st-respondeu"
ST_QUALIF = "st-qualificado"


def _segment_resolver(table, filters):
    if table == "pipeline_stages" and filters.get("pipeline_id") == PL_ATACADO:
        by_key = {
            "entrada": ST_ENTRADA,
            "novo": ST_NOVO,
            "respondeu": ST_RESPONDEU,
            "qualificado": ST_QUALIF,
        }
        k = filters.get("key")
        if k in by_key:
            return [{"id": by_key[k]}]
    return []


# ── Reflexo de reply generalizado ────────────────────────────────────────────
def test_reply_reflex_moves_novo_to_respondeu_in_segment_funnel():
    """Funil de segmento (não-frio): card em 'novo' → 'respondeu' quando o lead responde."""
    from app.leads.service import advance_deal_on_reply

    deal = {"id": "deal-1", "pipeline_id": PL_ATACADO, "stage_id": ST_NOVO}
    writes = []
    with patch("app.leads.service.get_open_deal", return_value=deal), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(_segment_resolver, writes)):
        assert advance_deal_on_reply("lead-1") is True

    assert len(writes) == 1
    op, table, payload, filters = writes[0]
    assert (op, table) == ("update", "deals")
    assert payload["stage_id"] == ST_RESPONDEU


def test_reply_reflex_moves_entrada_to_respondeu():
    from app.leads.service import advance_deal_on_reply

    deal = {"id": "deal-2", "pipeline_id": PL_ATACADO, "stage_id": ST_ENTRADA}
    writes = []
    with patch("app.leads.service.get_open_deal", return_value=deal), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(_segment_resolver, writes)):
        assert advance_deal_on_reply("lead-2") is True
    assert writes[0][2]["stage_id"] == ST_RESPONDEU


def test_reply_reflex_never_regresses_qualificado():
    """Card já 'qualificado' não regride para 'respondeu' (interesse conquistado é preservado)."""
    from app.leads.service import advance_deal_on_reply

    deal = {"id": "deal-3", "pipeline_id": PL_ATACADO, "stage_id": ST_QUALIF}
    writes = []
    with patch("app.leads.service.get_open_deal", return_value=deal), \
         patch("app.leads.service.get_supabase", return_value=FakeSupabase(_segment_resolver, writes)):
        assert advance_deal_on_reply("lead-3") is False
    assert writes == []


# ── Criação adiada do card no funil do segmento ──────────────────────────────
def test_ensure_segment_deal_creates_when_no_open_deal():
    """Segmento conhecido + sem deal aberto → cria card no funil do segmento."""
    from app.leads.service import ensure_segment_deal

    calls = []
    with patch("app.leads.service.get_open_deal", return_value=None), \
         patch("app.leads.service.get_lead", return_value={"name": "Maria", "phone": "5511"}), \
         patch("app.leads.service.create_deal",
               lambda *a, **k: calls.append((a, k)) or {"id": "d-new"}):
        assert ensure_segment_deal("lead-1", "atacado") is True

    assert len(calls) == 1
    _, kw = calls[0]
    assert kw["category"] == "atacado"
    assert kw["dedupe_open"] is True


def test_ensure_segment_deal_noop_when_open_deal_exists():
    """Já existe card aberto → não duplica."""
    from app.leads.service import ensure_segment_deal

    calls = []
    with patch("app.leads.service.get_open_deal", return_value={"id": "d-open"}), \
         patch("app.leads.service.create_deal", lambda *a, **k: calls.append(1)):
        assert ensure_segment_deal("lead-2", "atacado") is False
    assert calls == []


def test_ensure_segment_deal_noop_for_unknown_segment():
    """Segmento desconhecido (ex.: 'pending'/'secretaria') → não cria card (funil indefinido)."""
    from app.leads.service import ensure_segment_deal

    calls = []
    with patch("app.leads.service.get_open_deal", return_value=None), \
         patch("app.leads.service.create_deal", lambda *a, **k: calls.append(1)):
        assert ensure_segment_deal("lead-3", "pending") is False
    assert calls == []


# ── mudar_stage dispara a criação do card ────────────────────────────────────
@pytest.mark.asyncio
async def test_mudar_stage_creates_segment_deal(monkeypatch):
    """Ao classificar o segmento, mudar_stage cria o card no funil correspondente."""
    from app.agent.tools import execute_tool

    monkeypatch.setattr("app.agent.tools.update_lead", lambda *a, **k: {"id": "lead-1"})
    monkeypatch.setattr("app.agent.tools.update_conversation", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.tools.save_message", lambda *a, **k: None)
    seg_calls = []
    monkeypatch.setattr(
        "app.agent.tools.ensure_segment_deal",
        lambda lead_id, segment, **k: seg_calls.append((lead_id, segment)) or True,
    )

    await execute_tool(
        "mudar_stage", {"stage": "atacado"},
        lead_id="lead-1", phone="5511", conversation_id="conv-1",
    )
    assert seg_calls == [("lead-1", "atacado")]


# ── marcar_interesse vira create-or-move ─────────────────────────────────────
@pytest.mark.asyncio
async def test_marcar_interesse_create_or_move_uses_segment(monkeypatch):
    """marcar_interesse encaminha lead+segmento para a rotina create-or-move de qualificação."""
    from app.agent.tools import execute_tool, pop_interest_marked

    monkeypatch.setattr("app.agent.tools.get_lead", lambda lid: {"id": lid, "stage": "atacado"})
    calls = []
    monkeypatch.setattr(
        "app.agent.tools.mark_deal_qualificado",
        lambda lead_id, segment=None: calls.append((lead_id, segment)) or True,
    )

    result = await execute_tool(
        "marcar_interesse", {"nivel": "quente", "motivo": "pediu preço"},
        lead_id="lead-1", phone="5511", conversation_id="conv-1",
    )
    assert calls == [("lead-1", "atacado")]
    assert pop_interest_marked("conv-1") == {"nivel": "quente", "motivo": "pediu preço"}
    assert "quente" in result.lower()


def test_mark_deal_qualificado_creates_then_moves(monkeypatch):
    """Sem card: cria no funil do segmento e move para 'qualificado'."""
    from app.leads import service

    order = []
    monkeypatch.setattr(service, "get_open_deal", lambda lid: None)
    monkeypatch.setattr(
        service, "ensure_segment_deal",
        lambda lead_id, segment, **k: order.append(("ensure", segment)) or True,
    )
    monkeypatch.setattr(
        service, "move_deal_to_stage_key",
        lambda lead_id, key, label_fallback=None: order.append(("move", key)) or True,
    )

    assert service.mark_deal_qualificado("lead-1", "atacado") is True
    assert order == [("ensure", "atacado"), ("move", "qualificado")]


def test_mark_deal_qualificado_existing_deal_only_moves(monkeypatch):
    """Com card aberto: não cria, só move para 'qualificado'."""
    from app.leads import service

    order = []
    monkeypatch.setattr(service, "get_open_deal", lambda lid: {"id": "d-open"})
    monkeypatch.setattr(
        service, "ensure_segment_deal",
        lambda *a, **k: order.append("ensure") or True,
    )
    monkeypatch.setattr(
        service, "move_deal_to_stage_key",
        lambda lead_id, key, label_fallback=None: order.append(("move", key)) or True,
    )

    assert service.mark_deal_qualificado("lead-2", "atacado") is True
    assert order == [("move", "qualificado")]  # ensure NÃO foi chamado
