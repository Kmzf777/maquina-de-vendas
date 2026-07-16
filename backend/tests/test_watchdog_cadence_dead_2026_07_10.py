"""Wartime T5 (Pacote C2) — Check 6 `cadence_dead` + histograma de jobs no QA diário.

Contexto forense: a cadência 4-touch ficou MORTA por 13 dias (26/06→09/07) porque a
constraint 23514 fazia o INSERT em follow_up_jobs falhar como warning engolido — os
jobs nunca eram CRIADOS, então o `check_stuck_followup_jobs` (que olha jobs
EXISTENTES presos há 2h) nunca teve o que olhar. O detector correto é a combinação
"operação viva + zero criação de jobs", coberto aqui:

  - dispara nas condições exatas (assistant nas 24h + zero follow_up_jobs + janela
    08h-20h BRT) com alerta critical citando o precedente de 26/06;
  - NÃO dispara num dia sem tráfego (sem mensagens assistant novas);
  - NÃO dispara fora da janela 08h-20h BRT (e sem tocar o banco);
  - dedup de 24h (1 alerta não-resolvido por dia; resolvido não deduplica);
  - fail-open em erro de query (loga warning, NÃO alerta — falso critical acordaria
    o operador via WhatsApp/Sentry do T2);
  - QA diário com breakdown criados/executados por job_type e -1 em falha.

Fakes de supabase dict-backed no estilo de test_watchdog_checks_2026_07_02.py.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import app.watchdog.service as W
from app.watchdog.service import check_cadence_dead

# 12:00 BRT (America/Sao_Paulo = UTC-3, sem DST desde 2019) — dentro da janela útil.
NOW_IN_WINDOW = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)
# 03:00 BRT — fora da janela útil (madrugada).
NOW_OUT_OF_WINDOW = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ts(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data or [])


class _FakeNotAccessor:
    """`.not_.is_(key, "null")` → filtra IS NOT NULL e volta ao encadeamento (mesmo
    padrão do fake de test_watchdog_checks_2026_07_02.py; usado pela métrica de
    dossiês do QA)."""

    def __init__(self, query: "FakeQuery"):
        self._query = query

    def is_(self, key, value):
        if value == "null":
            self._query._filtered = [
                r for r in self._query._filtered if r.get(key) is not None
            ]
        return self._query


class FakeQuery:
    """Subconjunto do supabase-py usado pelo check_cadence_dead e pelo QA diário:
    select(count=)/eq/gte/lt/lte/like/in_/not_.is_/order/limit/insert/execute.

    gte/lt/lte comparam timestamps PARSEADOS (nunca string) e tratam valor ausente/
    None como "não passa no filtro" — importante porque jobs criados-mas-não-enviados
    têm sent_at=None e o filtro de executados (gte em sent_at) não pode estourar.
    """

    def __init__(self, rows: list):
        self._rows = rows  # referência viva à tabela (insert muta)
        self._filtered = list(rows)
        self._limit_n = None
        self._insert_payload = None

    def select(self, *cols, **_k):
        return self

    def eq(self, key, value):
        self._filtered = [r for r in self._filtered if r.get(key) == value]
        return self

    def _cmp(self, key, value, op):
        bound = _ts(value)
        self._filtered = [
            r for r in self._filtered
            if r.get(key) is not None and op(_ts(r[key]), bound)
        ]
        return self

    def gte(self, key, value):
        return self._cmp(key, value, lambda a, b: a >= b)

    def lt(self, key, value):
        return self._cmp(key, value, lambda a, b: a < b)

    def lte(self, key, value):
        return self._cmp(key, value, lambda a, b: a <= b)

    def like(self, key, pattern):
        import fnmatch
        translated = pattern.replace("%", "*")
        self._filtered = [
            r for r in self._filtered
            if fnmatch.fnmatchcase(str(r.get(key) or ""), translated)
        ]
        return self

    def in_(self, key, values):
        values_set = set(values)
        self._filtered = [r for r in self._filtered if r.get(key) in values_set]
        return self

    @property
    def not_(self):
        return _FakeNotAccessor(self)

    def order(self, key, desc=False):
        self._filtered = sorted(
            self._filtered, key=lambda r: _ts(r.get(key)), reverse=desc
        )
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def execute(self):
        if self._insert_payload is not None:
            rows = (
                self._insert_payload
                if isinstance(self._insert_payload, list)
                else [self._insert_payload]
            )
            self._rows.extend(rows)
            return _Resp(list(rows))
        rows = list(self._filtered)
        if self._limit_n is not None:
            rows = rows[: self._limit_n]
        return _Resp(rows)


class FakeSupabase:
    def __init__(self):
        self.tables: dict = {
            "messages": [],
            "follow_up_jobs": [],
            "system_alerts": [],
        }

    def table(self, name):
        return FakeQuery(self.tables.setdefault(name, []))


@pytest.fixture
def fake_db(monkeypatch):
    """Mesmo backing store para o watchdog E para create_system_alert — o insert do
    alerta aparece de verdade em fake.tables["system_alerts"] (padrão de
    test_watchdog_checks_2026_07_02.py). ADMIN_ALERT_PHONE removido: alerta critical
    dispararia o despacho WhatsApp do T2 se o dev tiver o env setado localmente.
    """
    fake = FakeSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)
    monkeypatch.delenv("ADMIN_ALERT_PHONE", raising=False)
    return fake


def _freeze_watchdog_clock(monkeypatch, fixed: datetime):
    """Congela `datetime.now` DENTRO do módulo do watchdog (o dedup
    `_alert_recently_fired` usa o relógio real, não o `now` do check — sem congelar,
    seeds relativos ao NOW_IN_WINDOW fixo divergiriam do relógio da máquina).
    Subclasse de datetime: fromisoformat/aritmética continuam funcionando.
    """
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(W, "datetime", _Frozen)


def _seed_assistant_msg(fake, created_at):
    fake.tables["messages"].append({
        "id": f"msg-{len(fake.tables['messages'])}",
        "role": "assistant",
        "created_at": _iso(created_at),
    })


def _seed_job(fake, created_at, *, job_type="standard", status="pending",
              sent_at=None, env_tag=None):
    fake.tables["follow_up_jobs"].append({
        "id": f"job-{len(fake.tables['follow_up_jobs'])}",
        "job_type": job_type,
        "status": status,
        "env_tag": env_tag if env_tag is not None else W._ENV_TAG,
        "created_at": _iso(created_at),
        "sent_at": _iso(sent_at) if sent_at else None,
    })


def _seed_alert(fake, alert_type, created_at, resolved=False):
    fake.tables["system_alerts"].append({
        "type": alert_type,
        "resolved": resolved,
        "created_at": _iso(created_at),
    })


# ── Check 6: dispara nas condições exatas ──────────────────────────────────────

def test_dispara_operacao_viva_e_zero_jobs(fake_db):
    """Assinatura do incidente 26/06→09/07: a Valéria conversou nas últimas 24h mas
    ZERO follow_up_jobs foram criados → alerta cadence_dead critical."""
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=5))

    assert check_cadence_dead(NOW_IN_WINDOW) == 1

    alerts = fake_db.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "cadence_dead"
    assert alerts[0]["severity"] == "critical"
    # A mensagem cita o precedente que motivou o check.
    assert "26/06" in alerts[0]["message"]
    assert alerts[0]["metadata"]["lookback_hours"] == W.CADENCE_DEAD_LOOKBACK_HOURS


def test_nao_dispara_sem_mensagens_assistant(fake_db):
    """Dia sem tráfego: sem operação viva, zero jobs é o estado NORMAL (madrugada de
    domingo, feriado) — silêncio, não alerta."""
    # Só mensagem de lead (role=user) e uma assistant VELHA (fora das 24h).
    fake_db.tables["messages"].append({
        "id": "msg-user", "role": "user",
        "created_at": _iso(NOW_IN_WINDOW - timedelta(hours=3)),
    })
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=30))

    assert check_cadence_dead(NOW_IN_WINDOW) == 0
    assert fake_db.tables["system_alerts"] == []


def test_nao_dispara_com_job_criado_na_janela(fake_db):
    """1 job criado nas 24h prova que a criação está viva → silêncio."""
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=5))
    _seed_job(fake_db, NOW_IN_WINDOW - timedelta(hours=3))

    assert check_cadence_dead(NOW_IN_WINDOW) == 0
    assert fake_db.tables["system_alerts"] == []


def test_job_de_outro_env_nao_mascara_cadencia_morta(fake_db):
    """Job com env_tag de OUTRO ambiente (ex.: teste em dev) não pode mascarar a
    cadência morta do ambiente atual — mesmo escopo por env do Check 3."""
    other_env = "production" if W._ENV_TAG == "dev" else "dev"
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=5))
    _seed_job(fake_db, NOW_IN_WINDOW - timedelta(hours=3), env_tag=other_env)

    assert check_cadence_dead(NOW_IN_WINDOW) == 1
    assert len(fake_db.tables["system_alerts"]) == 1


def test_nao_dispara_fora_da_janela_08_20_brt(monkeypatch):
    """03:00 BRT: retorna 0 SEM consultar o banco (de madrugada é normal não criar
    job; critical do T2 acordaria o operador à toa)."""
    sb_mock = MagicMock()
    monkeypatch.setattr(W, "get_supabase", lambda: sb_mock)
    alert_mock = MagicMock()
    monkeypatch.setattr(W, "create_system_alert", alert_mock)

    assert check_cadence_dead(NOW_OUT_OF_WINDOW) == 0
    sb_mock.table.assert_not_called()
    alert_mock.assert_not_called()


# ── Dedup 24h ──────────────────────────────────────────────────────────────────

def test_dedup_24h_nao_duplica_alerta_nao_resolvido(fake_db, monkeypatch):
    """Alerta cadence_dead não-resolvido de 10h atrás → condição ainda detectada,
    mas nenhum segundo insert (1 critical/dia, não 1 por tick)."""
    _freeze_watchdog_clock(monkeypatch, NOW_IN_WINDOW)
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=5))
    _seed_alert(fake_db, "cadence_dead", NOW_IN_WINDOW - timedelta(hours=10))

    assert check_cadence_dead(NOW_IN_WINDOW) == 0
    assert len(fake_db.tables["system_alerts"]) == 1  # só o seed


def test_dedup_expira_apos_24h(fake_db, monkeypatch):
    """Alerta antigo (30h) já saiu da janela de dedup → alerta de novo (a cadência
    do incidente real ficou morta 13 DIAS; 1 lembrete por dia é o contrato)."""
    _freeze_watchdog_clock(monkeypatch, NOW_IN_WINDOW)
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=5))
    _seed_alert(fake_db, "cadence_dead", NOW_IN_WINDOW - timedelta(hours=30))

    assert check_cadence_dead(NOW_IN_WINDOW) == 1
    assert len(fake_db.tables["system_alerts"]) == 2


def test_dedup_ignora_alerta_resolvido(fake_db, monkeypatch):
    """Alerta recente mas RESOLVIDO não deduplica: se o operador resolveu e a
    cadência continua morta, precisa alertar de novo."""
    _freeze_watchdog_clock(monkeypatch, NOW_IN_WINDOW)
    _seed_assistant_msg(fake_db, NOW_IN_WINDOW - timedelta(hours=5))
    _seed_alert(fake_db, "cadence_dead", NOW_IN_WINDOW - timedelta(hours=2), resolved=True)

    assert check_cadence_dead(NOW_IN_WINDOW) == 1
    assert len(fake_db.tables["system_alerts"]) == 2


# ── Fail-open em erro de query ─────────────────────────────────────────────────

def test_fail_open_erro_de_query_nao_alerta(monkeypatch):
    """Falha transitória de leitura NÃO é evidência de cadência morta — alertar
    critical em cima de erro de query seria falso positivo (WhatsApp+Sentry via T2).
    Loga warning, retorna 0, nunca levanta."""
    sb_mock = MagicMock()
    sb_mock.table.side_effect = RuntimeError("supabase indisponível")
    monkeypatch.setattr(W, "get_supabase", lambda: sb_mock)
    alert_mock = MagicMock()
    monkeypatch.setattr(W, "create_system_alert", alert_mock)

    assert check_cadence_dead(NOW_IN_WINDOW) == 0
    alert_mock.assert_not_called()


# ── QA diário: breakdown criados/executados por job_type ──────────────────────

# 07:15 BRT de 10/07 — dentro da janela do QA; D-1 = 09/07 BRT (03:00 UTC 09/07 →
# 03:00 UTC 10/07).
QA_NOW = datetime(2026, 7, 10, 10, 15, tzinfo=timezone.utc)
D1 = datetime(2026, 7, 9, tzinfo=timezone.utc)


def test_qa_breakdown_criados_e_executados_por_tipo(fake_db):
    """Histograma D-1: criados = created_at na janela; executados = status='sent'
    com sent_at na janela. É o detector humano de "um job_type sumiu" — no incidente
    de 26/06→09/07, o followups_enviados agregado nunca denunciou a cadência morta."""
    # standard criado E executado em D-1.
    _seed_job(fake_db, D1 + timedelta(hours=12), status="sent",
              sent_at=D1 + timedelta(hours=13))
    # criado em D-1, ainda pendente; sem job_type explícito → default 'standard'
    # (mesmo default da coluna no schema 20260527_follow_up_jobs_schema.sql).
    fake_db.tables["follow_up_jobs"].append({
        "id": "job-sem-tipo", "status": "pending", "env_tag": W._ENV_TAG,
        "created_at": _iso(D1 + timedelta(hours=14)), "sent_at": None,
    })
    # handoff_rescue criado ANTES de D-1 mas executado em D-1 → só executados.
    _seed_job(fake_db, D1 - timedelta(hours=20), job_type="handoff_rescue",
              status="sent", sent_at=D1 + timedelta(hours=15))
    # lp_welcome criado DEPOIS da janela (dia do relatório) → fora.
    _seed_job(fake_db, D1 + timedelta(hours=30), job_type="lp_welcome")
    # job de outro ambiente → fora.
    other_env = "production" if W._ENV_TAG == "dev" else "dev"
    _seed_job(fake_db, D1 + timedelta(hours=12), env_tag=other_env)

    metrics = W._qa_collect_metrics(QA_NOW)

    assert metrics["jobs_por_tipo"] == {
        "standard": {"criados": 2, "executados": 1},
        "handoff_rescue": {"criados": 0, "executados": 1},
    }


def test_qa_mensagem_inclui_breakdown_compacto(monkeypatch):
    """A mensagem do daily_qa_report carrega o histograma compacto
    (tipo criados/executados), legível no banner do CRM."""
    metrics = {
        "respostas_ia": 42, "followups_enviados": 4, "inbounds": 30, "handoffs": 3,
        "optouts": 1, "perguntas_repetidas_corrigidas": 2, "dossies_atualizados": 12,
        "disparos_enviados": 50, "numero_errado_marcados": 1, "indicacoes": 1,
        "jobs_por_tipo": {
            "standard": {"criados": 12, "executados": 10},
            "handoff_rescue": {"criados": 3, "executados": 3},
        },
    }
    alert_mock = MagicMock()
    monkeypatch.setattr(W, "_qa_already_published_today", lambda now: False)
    monkeypatch.setattr(W, "_qa_collect_metrics", lambda now: metrics)
    monkeypatch.setattr(W, "create_system_alert", alert_mock)

    assert W.check_daily_qa(QA_NOW) is True

    args, kwargs = alert_mock.call_args
    assert "standard 12/10" in args[2]
    assert "handoff_rescue 3/3" in args[2]
    assert kwargs["metadata"]["metrics"]["jobs_por_tipo"] == metrics["jobs_por_tipo"]


def test_qa_breakdown_indisponivel_vira_menos_1(monkeypatch):
    """Query de jobs quebrada → -1 (indicador indisponível), sem derrubar o
    relatório; a mensagem sinaliza 'indisponível (-1)'."""
    sb_mock = MagicMock()
    sb_mock.table.side_effect = RuntimeError("db down")
    monkeypatch.setattr(W, "get_supabase", lambda: sb_mock)

    assert W._qa_jobs_breakdown("2026-07-09T03:00:00+00:00",
                                "2026-07-10T03:00:00+00:00") == -1

    # E o formatador da mensagem tolera o -1 (e também a chave ausente).
    assert W._fmt_jobs_breakdown(-1) == "indisponível (-1)"
    assert W._fmt_jobs_breakdown({}) == "nenhum"
