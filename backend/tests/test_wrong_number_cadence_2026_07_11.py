"""Supressão de cadência/reopen para leads `wrong_number` — 11/07/2026.

Caso real (go/no-go do disparo em massa frios): Maria respondeu "Não" ao template
frio em 09/07, `registrar_numero_errado` marcou `metadata.wrong_number_at` — e em
10/07 ela recebeu o reopen D+1 ("não consegui te responder a tempo…") mesmo tendo
negado ser a dona do número. O job de 72h (process_wrong_number_deadends) ainda
não tinha vencido, e nada entre a marcação e o deadend suprimia os toques.

Cobertura:
1. `lead_marked_wrong_number` (função pura de decisão) — todos os ramos.
2. Agendamento: `schedule_followup` de lead marcado cancela os pending (reason
   `wrong_number`) e NÃO insere cadência nova; fail-open em erro de leitura.
3. Disparo: `process_due_followups` cancela o job `standard` de lead marcado ANTES
   do backstop/janela — nem toque LLM nem reopen saem (o guard único cobre os dois,
   porque o reopen é disparado pelo mesmo caminho padrão).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.follow_up import scheduler as S
from app.follow_up import service as FS
from app.follow_up.service import lead_marked_wrong_number


# ─── lead_marked_wrong_number: função pura ────────────────────────────────────

def test_flag_presente_e_wrong_number():
    lead = {"metadata": {"wrong_number_at": "2026-07-09T17:43:16+00:00"}}
    assert lead_marked_wrong_number(lead) is True


def test_sem_flag_nao_e_wrong_number():
    assert lead_marked_wrong_number({"metadata": {}}) is False


def test_metadata_ausente_nao_e_wrong_number():
    assert lead_marked_wrong_number({"id": "L1"}) is False


def test_lead_none_fail_safe():
    assert lead_marked_wrong_number(None) is False


def test_flag_vazia_nao_e_wrong_number():
    """Flag removida via pop/None (dono real respondeu) → volta a receber cadência."""
    assert lead_marked_wrong_number({"metadata": {"wrong_number_at": None}}) is False


# ─── schedule_followup: guard no AGENDAMENTO ──────────────────────────────────

class _FakeSb:
    """Fake encadeável table-aware: registra updates/inserts e responde
    conversations/leads com dados semeados. `raise_on_leads` simula falha SÓ na
    releitura do lead (fail-open do guard)."""

    def __init__(self, lead_metadata=None, raise_on_leads=False):
        self._lead_metadata = lead_metadata or {}
        self._raise_on_leads = raise_on_leads
        self._table = None
        self._op = None
        self._payload = None
        self.updates: list[tuple[str, dict]] = []
        self.inserts: list[tuple[str, object]] = []

    def table(self, name):
        self._table = name
        self._op = "select"
        self._payload = None
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def insert(self, rows):
        self._op = "insert"
        self._payload = rows
        return self

    def __getattr__(self, name):
        # `.not_` é ATRIBUTO (não chamada) na API do supabase-py — devolve self
        # direto; o resto (eq / in_ / limit / single / select / order...) encadeia.
        if name == "not_":
            return self
        return lambda *a, **k: self

    def execute(self):
        result = MagicMock()
        if self._op == "update":
            self.updates.append((self._table, self._payload))
            result.data = []
        elif self._op == "insert":
            self.inserts.append((self._table, self._payload))
            result.data = []
        elif self._table == "conversations":
            result.data = [{"id": "conv-1"}]
        elif self._table == "leads":
            if self._raise_on_leads:
                raise RuntimeError("db down")
            result.data = {"id": "lead-1", "metadata": self._lead_metadata}
        else:
            result.data = []
        return result


def _run_schedule(fake, monkeypatch):
    monkeypatch.setattr(FS, "get_supabase", lambda: fake)
    monkeypatch.setattr(FS, "_already_touched_today", lambda *a, **k: False)
    monkeypatch.setattr(FS, "emit_event", lambda *a, **k: None)
    FS.schedule_followup("conv-1", "lead-1", "ch-1", warm=False, outbound=True)


def test_agendamento_suprimido_para_wrong_number(monkeypatch):
    fake = _FakeSb(lead_metadata={"wrong_number_at": "2026-07-09T17:43:16+00:00"})

    _run_schedule(fake, monkeypatch)

    assert fake.inserts == []  # nenhuma cadência nova
    cancel_updates = [p for t, p in fake.updates if t == "follow_up_jobs"]
    assert cancel_updates and cancel_updates[0]["cancel_reason"] == "wrong_number"


def test_agendamento_normal_sem_flag(monkeypatch):
    fake = _FakeSb(lead_metadata={})

    _run_schedule(fake, monkeypatch)

    assert fake.inserts and fake.inserts[0][0] == "follow_up_jobs"
    cancel_updates = [p for t, p in fake.updates if t == "follow_up_jobs"]
    assert cancel_updates and cancel_updates[0]["cancel_reason"] == "rescheduled"


def test_agendamento_fail_open_em_erro_de_leitura(monkeypatch):
    """Erro ao reler o lead NUNCA bloqueia o agendamento (mesmo contrato fail-open
    das outras guardas de leitura do follow-up)."""
    fake = _FakeSb(raise_on_leads=True)

    _run_schedule(fake, monkeypatch)

    assert fake.inserts and fake.inserts[0][0] == "follow_up_jobs"


# ─── process_due_followups: guard no DISPARO ──────────────────────────────────

def _make_job(**overrides) -> dict:
    job = {
        "id": "job-1",
        "job_type": "standard",
        "conversation_id": "conv-1",
        "lead_id": "lead-1",
        "sequence": 2,
        "leads": {"id": "lead-1", "phone": "5511999999999", "name": "Maria"},
        "channels": {"id": "ch-1", "mode": "ai", "provider_config": {}},
        "conversations": {
            "id": "conv-1",
            "stage": "secretaria",
            "followup_enabled": True,
            # Sem last_customer_message_at: se o guard wrong_number NÃO agir, o guard
            # padrão seguinte cancela como "window_expired" — usamos isso para provar
            # qual caminho foi tomado (mesmo truque de test_backstop_pos_catalogo).
            "last_customer_message_at": None,
        },
        "metadata": {},
    }
    job.update(overrides)
    return job


@pytest.mark.asyncio
async def test_job_de_lead_wrong_number_cancela_sem_toque_nem_reopen():
    job = _make_job()
    fresh_lead = {
        "id": "lead-1",
        "phone": "5511999999999",
        "stage": "secretaria",
        "metadata": {"wrong_number_at": "2026-07-09T17:43:16+00:00"},
    }
    mock_execute_tool = AsyncMock(return_value="ok")

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.agent.tools.execute_tool", mock_execute_tool), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel, \
         patch("app.follow_up.scheduler.fire_reopen_template", new_callable=AsyncMock) as mock_reopen, \
         patch("app.follow_up.scheduler._generate_followup_message") as mock_generate:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_cancel.assert_called_once_with("job-1", "wrong_number")
    mock_reopen.assert_not_awaited()
    mock_generate.assert_not_called()
    mock_execute_tool.assert_not_awaited()  # nem handoff proativo


@pytest.mark.asyncio
async def test_lead_sem_flag_segue_para_o_fluxo_padrao():
    """Sem a flag, o job passa pelo guard e cai no caminho padrão (window_expired,
    dado o cenário sem last_customer_message_at) — não-regressão do fluxo."""
    job = _make_job()
    fresh_lead = {
        "id": "lead-1",
        "phone": "5511999999999",
        "stage": "secretaria",
        "metadata": {},
    }

    with patch("app.follow_up.scheduler.get_due_followups", return_value=[job]), \
         patch("app.follow_up.scheduler._recover_stale_followup_jobs", return_value=0), \
         patch("app.follow_up.scheduler._claim_followup_job", return_value=True), \
         patch("app.follow_up.scheduler._fetch_lead_for_backstop", return_value=fresh_lead), \
         patch("app.follow_up.scheduler._cancel_job") as mock_cancel:
        await S.process_due_followups(now=datetime.now(timezone.utc))

    mock_cancel.assert_called_once_with("job-1", "window_expired")
