"""Wartime T2 (10/07): alertas de budget + despacho externo de alertas.

Cobre os critérios de aceite 5 e 6 da spec 2026-07-10-wartime-budget-parking-alerts:
  5. Trip do kill-switch → `llm_budget_exceeded` critical (1/dia, dedup in-process E
     banco); ≥80% do teto → `llm_budget_warning` (1/dia); virada do dia UTC com gasto
     abaixo do teto → auto-resolve dos alertas abertos.
  6. `_notify_external` roteia por severidade (critical → Sentry error + WhatsApp admin;
     warning → só Sentry); sem ADMIN_ALERT_PHONE = no-op silencioso; falha do provider
     nunca escala; Sentry ausente = no-op; REHEARSAL_MODE suprime o WhatsApp.

Contexto: o processor (Pacote A) suprime o alerta llm_down quando reason="budget" —
o alerta de budget daqui é a ÚNICA sinalização do estouro, por isso os testes também
verificam que a mensagem é autossuficiente (gasto, teto, e o que acontece com os leads).
"""
import asyncio
import sys
import types

import pytest

from app.agent import budget_guard
from app.alerts import service as alerts_svc


# ── Fakes ────────────────────────────────────────────────────────────────────────

class _FluentQuery:
    """Encadeamento fluente mínimo do supabase-py, gravando as operações executadas."""

    def __init__(self, sb, table):
        self._sb = sb
        self.table_name = table
        self.op = None
        self.payload = None
        self.filters = []

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

    def eq(self, *a):
        self.filters.append(("eq", a))
        return self

    def gte(self, *a):
        self.filters.append(("gte", a))
        return self

    def in_(self, *a):
        self.filters.append(("in", a))
        return self

    def limit(self, *a):
        return self

    def execute(self):
        self._sb.executed.append(self)
        if self.op == "select":
            return types.SimpleNamespace(data=list(self._sb.select_data))
        return types.SimpleNamespace(data=[])


class _FakeSB:
    def __init__(self, select_data=None):
        self.select_data = select_data or []
        self.executed = []

    def table(self, name):
        return _FluentQuery(self, name)

    def updates(self):
        return [q for q in self.executed if q.op == "update"]

    def selects(self):
        return [q for q in self.executed if q.op == "select"]


class _FakeProvider:
    def __init__(self, fail=False, fail_template=False):
        self.sent = []  # legado: guarda envios via send_text (compat com testes antigos)
        self.sent_templates = []
        self.template_attempts = 0  # incrementa em TODA chamada, mesmo que levante
        self._fail = fail
        self._fail_template = fail_template

    async def send_text(self, to, body):
        if self._fail:
            raise RuntimeError("provider boom")
        self.sent.append((to, body))
        return {"status": "ok"}

    async def send_template(self, to, template_name, components=None, language_code="pt_BR"):
        self.template_attempts += 1
        if self._fail_template:
            raise RuntimeError("template boom")
        self.sent_templates.append({
            "to": to,
            "template_name": template_name,
            "components": components or [],
            "language_code": language_code,
        })
        return {"status": "ok"}


@pytest.fixture(autouse=True)
def _reset_budget_alert_state():
    """Flags in-process são módulo-globais — cada teste começa com o dia zerado."""
    budget_guard._alert_state.update(exceeded_day=None, warning_day=None, autoresolve_day=None)
    yield
    budget_guard._alert_state.update(exceeded_day=None, warning_day=None, autoresolve_day=None)


@pytest.fixture
def alert_recorder(monkeypatch):
    """Grava chamadas a create_system_alert sem tocar banco nem despacho externo."""
    calls = []
    monkeypatch.setattr(
        "app.alerts.service.create_system_alert",
        lambda type, title, message, severity="error", metadata=None: calls.append(
            {"type": type, "title": title, "message": message, "severity": severity}
        ),
    )
    return calls


# ── B1: trip → alerta critical 1x/dia (flag in-process + dedup DB) ───────────────

def test_trip_dispara_alerta_critical_com_mensagem_autossuficiente(monkeypatch, alert_recorder):
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: _FakeSB(select_data=[]))
    budget_guard.fire_budget_alert(12.5, 10.0)
    assert len(alert_recorder) == 1
    alert = alert_recorder[0]
    assert alert["type"] == "llm_budget_exceeded"
    assert alert["severity"] == "critical"
    # Mensagem autossuficiente: gasto, teto, prazo (virada UTC) e destino dos turnos.
    assert "US$12.50" in alert["message"]
    assert "US$10.00" in alert["message"]
    assert "virada do dia UTC" in alert["message"]
    assert "estacionados" in alert["message"]


def test_trip_flag_inprocess_bloqueia_segunda_chamada_sem_tocar_banco(monkeypatch, alert_recorder):
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: _FakeSB(select_data=[]))
    budget_guard.fire_budget_alert(12.5, 10.0)
    assert len(alert_recorder) == 1

    # Segunda chamada no MESMO dia: a flag corta ANTES de qualquer query — o caminho
    # quente (is_exceeded roda em toda chamada de LLM) não pode ganhar custo de banco.
    def _explode():
        raise AssertionError("dedup in-process deveria cortar antes do banco")

    monkeypatch.setattr(budget_guard, "get_supabase", _explode)
    budget_guard.fire_budget_alert(12.5, 10.0)  # não levanta, não insere
    assert len(alert_recorder) == 1


def test_dedup_db_bloqueia_quando_ja_existe_alerta_aberto(monkeypatch, alert_recorder):
    # Camada 2 (multiprocesso): outro processo já criou o alerta → esta réplica não duplica.
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: _FakeSB(select_data=[{"id": "a1"}]))
    budget_guard.fire_budget_alert(12.5, 10.0)
    assert alert_recorder == []


def test_dedup_db_falho_cria_mesmo_assim(monkeypatch, alert_recorder):
    # Fail-soft do dedup: melhor um alerta duplicado do que alerta nenhum.
    def _boom():
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(budget_guard, "get_supabase", _boom)
    budget_guard.fire_budget_alert(12.5, 10.0)
    assert len(alert_recorder) == 1


def test_is_exceeded_no_trip_dispara_critical_e_retorna_true(monkeypatch, alert_recorder):
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 12.5)
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: _FakeSB(select_data=[]))
    assert budget_guard.is_exceeded() is True
    assert [a["type"] for a in alert_recorder] == ["llm_budget_exceeded"]


def test_falha_total_do_alerta_nao_impede_is_exceeded(monkeypatch):
    # NENHUMA falha do alarme pode atrasar/impedir a resposta do guard.
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 12.5)

    def _boom(*a, **k):
        raise RuntimeError("tudo fora")

    monkeypatch.setattr(budget_guard, "get_supabase", _boom)
    monkeypatch.setattr("app.alerts.service.create_system_alert", _boom)
    assert budget_guard.is_exceeded() is True  # não levanta


# ── B1: aviso preventivo a 80% ───────────────────────────────────────────────────

def test_80_por_cento_dispara_warning_uma_vez(monkeypatch, alert_recorder):
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 8.5)
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: _FakeSB(select_data=[]))
    assert budget_guard.is_exceeded() is False  # 85% NÃO é trip
    assert len(alert_recorder) == 1
    alert = alert_recorder[0]
    assert alert["type"] == "llm_budget_warning"
    assert alert["severity"] == "warning"
    assert "85%" in alert["message"]
    # Segunda leitura no mesmo dia: flag in-process segura (1/dia).
    assert budget_guard.is_exceeded() is False
    assert len(alert_recorder) == 1


def test_abaixo_de_80_por_cento_nao_alerta(monkeypatch, alert_recorder):
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 3.0)
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: _FakeSB(select_data=[]))
    assert budget_guard.is_exceeded() is False
    assert alert_recorder == []


# ── B2: virada do dia UTC → auto-resolve ─────────────────────────────────────────

def test_virada_de_dia_auto_resolve_alertas_abertos(monkeypatch, alert_recorder):
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 1.0)
    sb = _FakeSB()
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: sb)
    # Simula alerta disparado ONTEM (flag de um dia anterior = budget já resetou).
    budget_guard._alert_state["exceeded_day"] = "1999-01-01"

    assert budget_guard.is_exceeded() is False
    updates = sb.updates()
    assert len(updates) == 1
    upd = updates[0]
    assert upd.table_name == "system_alerts"
    assert upd.payload["resolved"] is True
    # Resolve os dois tipos de alerta de budget, só os ainda abertos.
    in_filters = [f for f in upd.filters if f[0] == "in"]
    assert in_filters and set(in_filters[0][1][1]) == {"llm_budget_exceeded", "llm_budget_warning"}
    assert ("eq", ("resolved", False)) in upd.filters
    # Flags do dia anterior foram limpas — um novo estouro HOJE alerta de novo.
    assert budget_guard._alert_state["exceeded_day"] is None

    # 1x/dia: segunda leitura no mesmo dia não repete o update.
    assert budget_guard.is_exceeded() is False
    assert len(sb.updates()) == 1


def test_auto_resolve_nao_roda_se_incidente_e_do_dia_corrente(monkeypatch, alert_recorder):
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 1.0)
    sb = _FakeSB()
    monkeypatch.setattr(budget_guard, "get_supabase", lambda: sb)
    day, _ = budget_guard._today_utc()
    budget_guard._alert_state["exceeded_day"] = day  # alerta de HOJE — incidente vale
    assert budget_guard.is_exceeded() is False
    assert sb.updates() == []


def test_auto_resolve_fail_soft(monkeypatch, alert_recorder):
    monkeypatch.setenv("LLM_DAILY_COST_LIMIT_USD", "10")
    monkeypatch.setattr(budget_guard, "today_spend_usd", lambda force=False: 1.0)

    def _boom():
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(budget_guard, "get_supabase", _boom)
    budget_guard._alert_state["exceeded_day"] = "1999-01-01"
    assert budget_guard.is_exceeded() is False  # não levanta


# ── B3: _notify_external roteia por severidade ───────────────────────────────────

def _install_fake_sentry(monkeypatch):
    captured = []
    fake = types.ModuleType("sentry_sdk")
    fake.capture_message = lambda msg, level=None: captured.append((msg, level))
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    return captured


def test_notify_external_critical_vai_para_sentry_e_whatsapp(monkeypatch):
    captured = _install_fake_sentry(monkeypatch)
    wa_calls = []
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: wa_calls.append((t, m)))
    alerts_svc._notify_external("llm_budget_exceeded", "Teto estourado", "detalhe", "critical")
    assert captured == [("[ALERT][llm_budget_exceeded] Teto estourado: detalhe", "error")]
    assert wa_calls == [("Teto estourado", "detalhe")]


def test_notify_external_warning_so_sentry(monkeypatch):
    captured = _install_fake_sentry(monkeypatch)
    wa_calls = []
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: wa_calls.append((t, m)))
    alerts_svc._notify_external("llm_budget_warning", "80% do teto", "detalhe", "warning")
    assert captured == [("[ALERT][llm_budget_warning] 80% do teto: detalhe", "warning")]
    assert wa_calls == []


def test_notify_external_outras_severities_nao_despacham(monkeypatch):
    captured = _install_fake_sentry(monkeypatch)
    wa_calls = []
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: wa_calls.append((t, m)))
    for severity in ("info", "error"):
        alerts_svc._notify_external("x", "t", "m", severity)
    assert captured == []
    assert wa_calls == []


def test_notify_external_sentry_ausente_e_noop(monkeypatch):
    # sys.modules[name] = None faz `import sentry_sdk` levantar ImportError — simula
    # ambiente sem o pacote. O despacho segue fail-open (padrão observability.py).
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: None)
    alerts_svc._notify_external("x", "t", "m", "critical")  # não levanta


def test_notify_external_engole_falha_do_whatsapp(monkeypatch):
    _install_fake_sentry(monkeypatch)

    def _boom(t, m):
        raise RuntimeError("whatsapp boom")

    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", _boom)
    # llm_down está no allowlist default de _whatsapp_admin_allowed_types → a chamada é
    # tentada e o _boom levanta; o teste garante que _notify_external engole.
    alerts_svc._notify_external("llm_down", "t", "m", "critical")  # não levanta


# ── B6: Allowlist de tipos que disparam WhatsApp admin (audit 11/08) ─────────────
# Antes: TODO alerta severity=critical disparava WhatsApp (llm_down, ai_unresponsive,
# handoff_sla_escalation, billing_payment_issue, etc.). Isso acordava o admin fora do
# horário comercial para incidentes que ele não pode acionar sozinho — a fila humana
# não é problema do admin às 3h da manhã. Agora só tipos ligados ao LLM ("token
# acabou": llm_down + llm_budget_exceeded) disparam WhatsApp por default. Restante
# segue em system_alerts + Sentry (auditoria/e-mail). Override via
# WHATSAPP_ADMIN_ALERT_TYPES=csv.

def test_notify_external_critical_handoff_escalation_nao_dispara_whatsapp_por_default(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ADMIN_ALERT_TYPES", raising=False)
    _install_fake_sentry(monkeypatch)
    wa_calls = []
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: wa_calls.append((t, m)))
    alerts_svc._notify_external(
        "handoff_sla_escalation",
        "Fila humana acumulando: 3 lead(s)",
        "detalhe",
        "critical",
    )
    assert wa_calls == []  # NÃO acorda o admin — fila humana é responsabilidade do time


def test_notify_external_critical_llm_down_dispara_whatsapp_por_default(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ADMIN_ALERT_TYPES", raising=False)
    _install_fake_sentry(monkeypatch)
    wa_calls = []
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: wa_calls.append((t, m)))
    alerts_svc._notify_external("llm_down", "IA fora", "detalhe", "critical")
    assert wa_calls == [("IA fora", "detalhe")]


def test_notify_external_respeita_allowlist_env(monkeypatch):
    """WHATSAPP_ADMIN_ALERT_TYPES sobrepõe o default (CSV, whitespace tolerado)."""
    monkeypatch.setenv("WHATSAPP_ADMIN_ALERT_TYPES", "handoff_sla_escalation, billing_payment_issue")
    _install_fake_sentry(monkeypatch)
    wa_calls = []
    monkeypatch.setattr(alerts_svc, "_notify_whatsapp_admin", lambda t, m: wa_calls.append((t, m)))
    # dentro do allowlist explícito
    alerts_svc._notify_external("handoff_sla_escalation", "Fila", "detalhe", "critical")
    # fora do allowlist explícito (mesmo sendo default)
    alerts_svc._notify_external("llm_down", "IA fora", "detalhe", "critical")
    assert wa_calls == [("Fila", "detalhe")]


def test_create_system_alert_notifica_mesmo_com_insert_falhando(monkeypatch):
    # Notificação externa NÃO depende de persistência: se o banco caiu, avisar fora
    # do banco é ainda mais importante.
    def _boom():
        raise RuntimeError("supabase fora")

    monkeypatch.setattr(alerts_svc, "get_supabase", _boom)
    notified = []
    monkeypatch.setattr(
        alerts_svc, "_notify_external", lambda *a: notified.append(a)
    )
    alerts_svc.create_system_alert("x", "t", "m", severity="critical")
    assert notified == [("x", "t", "m", "critical")]


# ── B4: WhatsApp ao admin ────────────────────────────────────────────────────────

def test_whatsapp_noop_sem_admin_alert_phone(monkeypatch):
    monkeypatch.delenv("ADMIN_ALERT_PHONE", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")

    def _explode(*a, **k):
        raise AssertionError("sem ADMIN_ALERT_PHONE nada deveria ser resolvido/enviado")

    monkeypatch.setattr("app.channels.service.get_active_channel", _explode)
    monkeypatch.setattr("app.whatsapp.registry.get_provider", _explode)
    alerts_svc._notify_whatsapp_admin("t", "m")  # skip silencioso


def test_whatsapp_envia_para_admin_via_canal_ativo(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("ADMIN_ALERT_TEMPLATE_NAME", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"id": "chan-ativo", "provider": "meta_cloud", "provider_config": {}}
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: channel)
    provider = _FakeProvider()
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: provider)

    # Teste sync = sem event loop ativo → cai no ramo asyncio.run (envio resolvido já).
    alerts_svc._notify_whatsapp_admin("Teto estourado", "US$12.50 >= US$10.00")
    assert provider.sent == [("5511999999999", "🚨 Teto estourado\n\nUS$12.50 >= US$10.00")]


def test_whatsapp_prefere_alert_channel_id(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.setenv("ALERT_CHANNEL_ID", "chan-alerta")
    monkeypatch.delenv("ADMIN_ALERT_TEMPLATE_NAME", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    looked_up = []
    channel = {"id": "chan-alerta", "provider": "meta_cloud", "provider_config": {}}

    def _by_id(cid):
        looked_up.append(cid)
        return channel

    def _explode():
        raise AssertionError("com ALERT_CHANNEL_ID resolvido, não usa canal ativo")

    monkeypatch.setattr("app.channels.service.get_channel_by_id", _by_id)
    monkeypatch.setattr("app.channels.service.get_active_channel", _explode)
    provider = _FakeProvider()
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: provider)

    alerts_svc._notify_whatsapp_admin("t", "m")
    assert looked_up == ["chan-alerta"]
    assert len(provider.sent) == 1


def test_whatsapp_falha_do_provider_nao_escala(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"id": "c1", "provider": "meta_cloud", "provider_config": {}}
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: channel)
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: _FakeProvider(fail=True))
    alerts_svc._notify_whatsapp_admin("t", "m")  # não levanta


def test_whatsapp_sem_canal_disponivel_nao_escala(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: None)
    alerts_svc._notify_whatsapp_admin("t", "m")  # não levanta


def test_whatsapp_skip_em_rehearsal(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.setenv("REHEARSAL_MODE", "true")

    def _explode(*a, **k):
        raise AssertionError("rehearsal não deveria resolver canal nem enviar")

    monkeypatch.setattr("app.channels.service.get_active_channel", _explode)
    monkeypatch.setattr("app.whatsapp.registry.get_provider", _explode)
    alerts_svc._notify_whatsapp_admin("t", "m")  # skip total


async def test_whatsapp_com_loop_ativo_agenda_task(monkeypatch):
    # Dentro de um event loop (worker/webhook), o envio vira task — não bloqueia o
    # caminho do incidente. Cede o loop e verifica que a task rodou.
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.delenv("ADMIN_ALERT_TEMPLATE_NAME", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"id": "c1", "provider": "meta_cloud", "provider_config": {}}
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: channel)
    provider = _FakeProvider()
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: provider)

    alerts_svc._notify_whatsapp_admin("t", "m")
    assert provider.sent == []  # agendado, ainda não executado
    await asyncio.sleep(0)
    assert provider.sent == [("5511999999999", "🚨 t\n\nm")]


# ── B5: Envio via template UTILITY (fora da janela de 24h) ───────────────────────
# Free-form (send_text) só entrega DENTRO da janela de 24h do admin. Alertas
# operacionais precisam chegar fora dela (madrugada, fds, incidente após dias sem
# msg do admin) → template utility aprovado é o único canal garantido. Se
# ADMIN_ALERT_TEMPLATE_NAME não estiver setado, mantém o comportamento antigo
# (send_text). Se estiver e falhar (não aprovado/rejeitado), cai no send_text
# como cinto de segurança (pelo menos entrega se a janela estiver aberta).

def test_whatsapp_usa_template_quando_configurado(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.setenv("ADMIN_ALERT_TEMPLATE_NAME", "alerta_admin_sistema_v1")
    monkeypatch.setenv("ADMIN_ALERT_TEMPLATE_LANGUAGE", "pt_BR")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"id": "chan-ativo", "provider": "meta_cloud", "provider_config": {}}
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: channel)
    provider = _FakeProvider()
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: provider)

    alerts_svc._notify_whatsapp_admin("Teto estourado", "US$12.50 >= US$10.00")

    assert provider.sent == []  # template preferido; send_text NÃO é chamado
    assert len(provider.sent_templates) == 1
    call = provider.sent_templates[0]
    assert call["to"] == "5511999999999"
    assert call["template_name"] == "alerta_admin_sistema_v1"
    assert call["language_code"] == "pt_BR"
    body = next(c for c in call["components"] if c["type"] == "body")
    params = body["parameters"]
    assert params[0] == {"type": "text", "text": "Teto estourado"}
    assert params[1] == {"type": "text", "text": "US$12.50 >= US$10.00"}


def test_whatsapp_template_falha_faz_fallback_para_text(monkeypatch):
    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.setenv("ADMIN_ALERT_TEMPLATE_NAME", "alerta_admin_sistema_v1")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"id": "chan-ativo", "provider": "meta_cloud", "provider_config": {}}
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: channel)
    provider = _FakeProvider(fail_template=True)
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: provider)

    alerts_svc._notify_whatsapp_admin("t", "m")

    # tentou template E falhou (não appenda em sent_templates ao levantar) → send_text é o fallback
    assert provider.template_attempts == 1
    assert provider.sent_templates == []
    assert provider.sent == [("5511999999999", "🚨 t\n\nm")]


def test_whatsapp_sanitiza_newlines_e_espacos_em_variavel_do_template(monkeypatch):
    """Meta rejeita \\n, \\r, \\t e 4+ espaços consecutivos em body_parameters.
    Sanitiza para 1 espaço (bem abaixo do limite de 3)."""
    import re

    monkeypatch.setenv("ADMIN_ALERT_PHONE", "5511999999999")
    monkeypatch.setenv("ADMIN_ALERT_TEMPLATE_NAME", "alerta_admin_sistema_v1")
    monkeypatch.delenv("ALERT_CHANNEL_ID", raising=False)
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    channel = {"id": "chan-ativo", "provider": "meta_cloud", "provider_config": {}}
    monkeypatch.setattr("app.channels.service.get_active_channel", lambda: channel)
    provider = _FakeProvider()
    monkeypatch.setattr("app.whatsapp.registry.get_provider", lambda ch: provider)

    alerts_svc._notify_whatsapp_admin(
        "IA (Valeria)\nindisponivel\r\n— LLM fora",
        "5 turnos\n\n\nfalharam\t\t.    Verifique   quota.",
    )
    body = next(c for c in provider.sent_templates[0]["components"] if c["type"] == "body")
    p0, p1 = body["parameters"][0]["text"], body["parameters"][1]["text"]
    for txt in (p0, p1):
        assert "\n" not in txt and "\r" not in txt and "\t" not in txt
        assert re.search(r"\s{2,}", txt) is None
        assert txt == txt.strip() and txt != ""
    assert "indisponivel" in p0 and "LLM fora" in p0
    assert "falharam" in p1 and "Verifique quota" in p1
