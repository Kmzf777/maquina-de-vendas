"""Trava dupla da higiene de lista fria — diretriz 2026-07-13.

Contexto: o disparo "DSP 13 07 26 06 54" teve 47 de 49 leads retidos pelo
`_hot_lead_guardrail` com o motivo "relacionamento ativo/contato humano <90d".
A auditoria mostrou que o contato humano mais recente de TODO o lote era de
25/06 — ninguém estava em negociação viva. A janela de 90 dias tratava
"trabalhado no mês passado" como se fosse "em conversa agora".

A diretriz nova separa os dois sinais, que a `lead_has_active_relationship`
fundia num booleano só:

  TRAVA A (absoluta, imexível): cliente consolidado — venda em `sales`, deal em
  `fechado_ganho`, ou deal com `closed_at` fora dos estágios de perda. NUNCA
  recebe disparo frio, independente de tempo. É o caso Nayara/Kadi Guth.

  TRAVA B (temporal, 72h): lead SEM venda cujo vendedor humano falou com ele
  dentro da janela. Fora da janela, o lead é reabordável pela Valéria.

`ja_chamado` (tratativa humana em aberto) sai do bloqueio absoluto: é sinal de
contato, não de venda — quem decide sobre ele é a TRAVA B.

REGRESSÃO CRÍTICA: `lead_has_active_relationship` NÃO muda de comportamento —
ela é usada pelo guardrail de descarte em `agent/tools.py` (caso Kadi Guth), que
depende da janela de 90 dias e de `ja_chamado`. Só o worker de broadcast passa a
usar os sinais separados.
"""
import pytest
from unittest.mock import MagicMock

from app.templates.intent import COLD_REACTIVATION, GENERIC


class _TableRouterStub:
    """Stub encadeável do supabase-py que devolve dados POR TABELA.

    O _SbStub opaco da suíte antiga devolve o mesmo `.data` para qualquer tabela,
    então não consegue expressar "tem mensagem de seller mas NÃO tem venda" — que
    é exatamente a distinção que a trava dupla precisa fazer.
    """

    def __init__(self, tables: dict[str, list] | None = None, raise_exc: Exception | None = None):
        self._tables = tables or {}
        self._raise = raise_exc
        self._current: str | None = None
        self.filters: list[tuple] = []

    def table(self, name):
        self._current = name
        return self

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", self._current, col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", self._current, col, list(vals)))
        return self

    def gte(self, col, val):
        self.filters.append(("gte", self._current, col, val))
        return self

    def filter(self, col, op, val):
        self.filters.append(("filter", self._current, col, op, val))
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self._raise:
            raise self._raise
        result = MagicMock()
        result.data = list(self._tables.get(self._current, []))
        return result


# ---------------------------------------------------------------------------
# TRAVA A — lead_is_customer (bloqueio absoluto, sem janela de tempo)
# ---------------------------------------------------------------------------

def test_lead_is_customer_true_com_venda_registrada(monkeypatch):
    from app.leads import service
    stub = _TableRouterStub(tables={"sales": [{"id": "s1"}]})
    monkeypatch.setattr(service, "get_supabase", lambda: stub)
    assert service.lead_is_customer("L1") is True


def test_lead_is_customer_true_com_deal_fechado_ganho(monkeypatch):
    from app.leads import service
    stub = _TableRouterStub(tables={
        "sales": [], "pipeline_stages": [{"id": "st-ganho"}], "deals": [{"id": "d1"}],
    })
    monkeypatch.setattr(service, "get_supabase", lambda: stub)
    assert service.lead_is_customer("L1") is True


def test_lead_is_customer_nao_consulta_messages(monkeypatch):
    """A TRAVA A é sobre VENDA, não sobre conversa. Se ela olhasse `messages`,
    voltaria a fundir os dois sinais e a janela temporal viraria letra morta."""
    from app.leads import service
    stub = _TableRouterStub(tables={"sales": [], "deals": []})
    monkeypatch.setattr(service, "get_supabase", lambda: stub)

    assert service.lead_is_customer("L1") is False
    assert not any(f[1] == "messages" for f in stub.filters)


def test_lead_is_customer_ignora_ja_chamado(monkeypatch):
    """`ja_chamado` = tratativa humana em aberto, NÃO é venda. Quem decide sobre
    esse lead é a janela de 72h, não o bloqueio absoluto."""
    from app.leads import service
    stub = _TableRouterStub(tables={
        "sales": [], "pipeline_stages": [{"id": "st-ganho"}], "deals": [],
    })
    monkeypatch.setattr(service, "get_supabase", lambda: stub)

    assert service.lead_is_customer("L1") is False

    # A TRAVA A só resolve estágio de GANHO — 'ja_chamado' não aparece em lugar nenhum.
    assert not any("ja_chamado" in str(f) for f in stub.filters)


def test_lead_is_customer_fail_open_em_erro(monkeypatch):
    from app.leads import service
    monkeypatch.setattr(
        service, "get_supabase", lambda: _TableRouterStub(raise_exc=RuntimeError("db down"))
    )
    assert service.lead_is_customer("L1") is False


def test_lead_is_customer_le_o_estagio_verdadeiro_e_nao_a_coluna_legada(monkeypatch):
    """AUDITORIA 13/07: `deals.stage` (coluna legada) está congelada — NENHUMA linha
    do banco tem stage='fechado_ganho'. O ganho real vive em `stage_id`, apontando
    para um `pipeline_stages` de key='fechado_ganho'.

    Consequência do bug: a heurística de closed_at filtrava perda pela coluna legada
    e classificava 10 deals do estágio REAL "Perdido" como closed-won. A trava de
    cliente precisa ler `stage_id`, senão protege quem não é cliente e um dia deixa
    passar quem é."""
    from app.leads import service
    stub = _TableRouterStub(tables={
        "sales": [],
        "pipeline_stages": [{"id": "st-ganho"}],
        "deals": [{"id": "d1"}],
    })
    monkeypatch.setattr(service, "get_supabase", lambda: stub)

    assert service.lead_is_customer("L1") is True

    # A trava tem de resolver os estágios de ganho pela KEY...
    assert ("eq", "pipeline_stages", "key", "fechado_ganho") in stub.filters
    # ...e casar os deals por stage_id, nunca pela coluna legada `stage`.
    assert ("in", "deals", "stage_id", ["st-ganho"]) in stub.filters
    assert not any(f[1] == "deals" and f[2] == "stage" for f in stub.filters)


def test_lead_is_customer_nao_confunde_perdido_com_ganho(monkeypatch):
    """Os 10 leads do lote de 13/07: deal em "Perdido" com closed_at preenchido e
    stage legado 'novo'. Não são clientes — não podem ser retidos como se fossem."""
    from app.leads import service
    stub = _TableRouterStub(tables={
        "sales": [],
        "pipeline_stages": [{"id": "st-ganho"}],
        "deals": [],  # nenhum deal em estágio de ganho
    })
    monkeypatch.setattr(service, "get_supabase", lambda: stub)

    assert service.lead_is_customer("L1") is False


# ---------------------------------------------------------------------------
# TRAVA B — lead_recently_engaged com janela em HORAS
# ---------------------------------------------------------------------------

def test_lead_recently_engaged_aceita_janela_em_horas(monkeypatch):
    from app.leads import service
    from datetime import datetime, timedelta, timezone

    stub = _TableRouterStub(tables={"messages": []})
    monkeypatch.setattr(service, "get_supabase", lambda: stub)

    assert service.lead_recently_engaged("L1", hours=72) is False

    cutoffs = [f for f in stub.filters if f[0] == "gte" and f[2] == "created_at"]
    assert len(cutoffs) == 1
    cutoff = datetime.fromisoformat(cutoffs[0][3])
    esperado = datetime.now(timezone.utc) - timedelta(hours=72)
    assert abs((cutoff - esperado).total_seconds()) < 60


# ---------------------------------------------------------------------------
# Guardrail do worker — composição das duas travas
# ---------------------------------------------------------------------------

def test_hot_guardrail_bloqueia_cliente_mesmo_com_contato_antigo(monkeypatch):
    """TRAVA A é absoluta: venda registrada não sai no disparo frio nem que o
    último contato humano tenha sido há um ano."""
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_is_customer", lambda _id: True)
    monkeypatch.setattr(worker, "lead_recently_engaged", lambda *a, **k: False)

    reason = worker._hot_lead_guardrail({"id": "L1", "phone": "55349"}, COLD_REACTIVATION)

    assert reason and "cliente" in reason.lower()


def test_hot_guardrail_bloqueia_contato_humano_dentro_de_72h(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_is_customer", lambda _id: False)
    monkeypatch.setattr(worker, "lead_recently_engaged", lambda *a, **k: True)

    reason = worker._hot_lead_guardrail({"id": "L1"}, COLD_REACTIVATION)

    assert reason and "72h" in reason


def test_hot_guardrail_libera_nao_cliente_com_contato_humano_fora_da_janela(monkeypatch):
    """O caso do lote de 13/07: sem venda, último contato humano em 25/06 (18
    dias). A janela de 90d bloqueava; a de 72h libera."""
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_is_customer", lambda _id: False)
    monkeypatch.setattr(worker, "lead_recently_engaged", lambda *a, **k: False)

    assert worker._hot_lead_guardrail({"id": "L1"}, COLD_REACTIVATION) is None


def test_hot_guardrail_usa_janela_de_72_horas(monkeypatch):
    """A janela consultada tem de ser 72 HORAS — não 72 dias, não 90 dias."""
    from app.broadcast import worker
    capturado: dict = {}

    def _fake_engaged(lead_id, **kwargs):
        capturado.update(kwargs)
        return False

    monkeypatch.setattr(worker, "lead_is_customer", lambda _id: False)
    monkeypatch.setattr(worker, "lead_recently_engaged", _fake_engaged)

    worker._hot_lead_guardrail({"id": "L1"}, COLD_REACTIVATION)

    assert capturado.get("hours") == 72


def test_hot_guardrail_nao_bloqueia_intent_generico(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_is_customer", lambda _id: True)
    monkeypatch.setattr(worker, "lead_recently_engaged", lambda *a, **k: True)
    assert worker._hot_lead_guardrail({"id": "L1"}, GENERIC) is None


def test_hot_guardrail_fail_open_em_erro(monkeypatch):
    from app.broadcast import worker

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "lead_is_customer", _boom)
    assert worker._hot_lead_guardrail({"id": "L1"}, COLD_REACTIVATION) is None


# ---------------------------------------------------------------------------
# REGRESSÃO — o guardrail de DESCARTE (agent/tools.py) não pode ser afetado
# ---------------------------------------------------------------------------

def test_has_active_relationship_preserva_ja_chamado_e_90d(monkeypatch):
    """`lead_has_active_relationship` continua sendo o sinal LARGO usado pelo
    guardrail de descarte (caso Kadi Guth): inclui `ja_chamado` e a janela de
    90 dias. Afrouxá-la aqui reabriria o bug de descartar cliente ativo."""
    from app.leads import service

    assert "ja_chamado" in service._ACTIVE_DEAL_STAGES
    assert service._RECENT_ENGAGEMENT_DAYS == 90

    stub = _TableRouterStub(tables={"sales": [], "deals": [{"id": "d-ja-chamado"}]})
    monkeypatch.setattr(service, "get_supabase", lambda: stub)
    assert service.lead_has_active_relationship("L1") is True
