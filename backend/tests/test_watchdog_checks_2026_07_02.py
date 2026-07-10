"""Watchdog fim-a-fim (Etapa 1 / A1) — 2026-07-02.

Contexto forense: o apagao de producao (01-02/07) deixou leads ate 21h sem resposta
com mensagens salvas no banco e ZERO alertas — os alertas existentes (llm_down,
billing) observam EXCECOES no caminho de execucao, nao o resultado fim-a-fim. Este
arquivo cobre os checks que leem o banco direto (verdade fim-a-fim, independente
de qual bug matou o turno) e o loop `run_watchdog` que os orquestra:

  - Check 1 `ai_unresponsive` (caso Welita): lead mandou mensagem num canal de IA
    com IA ligada e ninguem respondeu.
  - Check 3 `followup_jobs_stuck`: jobs de follow-up pendentes com fire_at muito no
    passado — o scheduler parou de rodar.

Fakes de supabase por tabela (dict-backed, encadeavel), espelhando o estilo de
test_processor_llm_down_handoff_2026_07_01.py e test_inbound_autonomy_2026_06_26.py.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.watchdog import service as W
from app.watchdog.service import (
    check_ai_unresponsive,
    check_stuck_followup_jobs,
    run_watchdog,
)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ts(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _order_sort_key(value):
    """Chave de ordenacao generica p/ `FakeQuery.order()`/`execute()`: tenta parsear
    `value` como timestamp (colunas created_at/fire_at, a maioria dos `.order()` do
    watchdog); se nao for parseavel (ex.: coluna `id`, usada so como tiebreaker
    secundario na paginacao — ver `test_watchdog_handoff_sla_2026_07_03.py`), cai
    pro valor bruto. O wrapper em tupla `(0, ...)`/`(1, ...)` evita comparar
    datetime com string diretamente quando um `.sort()` mistura linhas com e sem o
    campo (ex.: linha sem `id`) — timestamps sempre ordenam antes de nao-timestamps.
    """
    try:
        return (0, _ts(value))
    except (ValueError, TypeError):
        return (1, str(value))


def _dotted_get(row: dict, dotted_key: str):
    """Le uma chave `"a.b"` (ex.: `"channels.mode"`) em um dict com embeds
    aninhados — suporta o padrao PostgREST `.eq("embed.coluna", valor)` (filtra pela
    tabela embedada via `!inner`, usado pelo Check 5). Chaves sem ponto continuam
    identicas a `row.get(key)` (comportamento anterior, retrocompativel).
    """
    node = row
    for part in dotted_key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeNotAccessor:
    """Devolvido pela property `FakeQuery.not_` — captura `.is_(key, "null")`
    (equivalente a `IS NOT NULL`) e retorna o FakeQuery original pra manter o
    encadeamento (`.not_.is_(...).gte(...)`), mesmo padrao de `_NotAccessor` em
    test_scheduler_preserves_ai_scheduled_return_2026_06_30.py (que cobre `.in_()`
    em vez de `.is_()`).
    """

    def __init__(self, query: "FakeQuery"):
        self._query = query

    def is_(self, key, value):
        if value == "null":
            self._query._not_is_null_keys.append(key)
            self._query._filtered = [r for r in self._query._filtered if r.get(key) is not None]
        return self._query


class FakeQuery:
    """Query encadeavel sobre uma lista de dicts (uma tabela fake), no estilo do repo.

    Suporta exatamente o subconjunto usado pelo watchdog: select/eq/gte/lte/in_/
    not_.is_/order/limit/range/insert/execute. gte/lte comparam por timestamp
    parseado (nunca por string) — mesma disciplina exigida da implementacao real.

    `table_name`/`call_log` sao opcionais (retrocompativeis com instanciacao antiga
    `FakeQuery(rows)`): quando um `call_log` e passado, cada `execute()` de LEITURA
    (nao-insert) registra nele um snapshot da query (tabela, select, filtros in_,
    order, range, limit) — usado pelos testes de paginacao/chunking/embeds enxutos
    (test_watchdog_pagination_2026_07_03.py) para inspecionar COMO o passo foi
    construido, nao so o resultado.

    `eq()` aceita chaves com ponto (`"channels.mode"`) para filtrar por um embed
    `!inner` (Check 5). `order()` aceita chamadas encadeadas (`.order(a).order(b)`)
    — cada uma empilha em `_order_calls` e `execute()` aplica um sort estavel
    multi-chave (primaria primeiro, seguintes so desempatam) — usado pelo tiebreaker
    `.order("id")` da paginacao (ver test_watchdog_handoff_sla_2026_07_03.py).

    `.not_.is_(key, "null")` (property `not_` devolvendo um accessor com `.is_()`)
    filtra `IS NOT NULL` e volta a encadear no proprio FakeQuery — mesmo padrao real
    do supabase-py usado em app/automation/triggers.py e app/campaigns/google_export.py.
    `gte()`/`not_.is_()` tambem registram suas chamadas (`_gte_calls`/
    `_not_is_null_keys`) no `call_log`, usado pelo pushdown server-side do Check 5
    (ver test_watchdog_handoff_sla_2026_07_03.py::test_check5_query_pushes_down_not_null_lookback_and_limit).
    """

    def __init__(self, rows: list, table_name: str = "", call_log: list | None = None):
        self._rows = rows  # referencia direta a lista da tabela (insert deve mutar)
        self._filtered = list(rows)
        self._table_name = table_name
        self._call_log = call_log
        self._order_key = None
        self._order_desc = False
        self._order_calls: list = []  # [(key, desc), ...] na ordem das chamadas .order() encadeadas
        self._limit_n = None
        self._range = None  # (start, end) inclusive, no estilo supabase-py
        self._select_cols = None
        self._in_calls: list = []  # [(key, values_list), ...] na ordem de chamada
        self._gte_calls: list = []  # [(key, value_bruto), ...] na ordem de chamada
        self._not_is_null_keys: list = []  # keys filtradas via .not_.is_(key, "null")
        self._insert_payload = None

    def select(self, *cols, **_k):
        if cols:
            self._select_cols = cols[0]
        return self

    def eq(self, key, value):
        self._filtered = [r for r in self._filtered if _dotted_get(r, key) == value]
        return self

    def gte(self, key, value):
        self._gte_calls.append((key, value))
        bound = _ts(value)
        self._filtered = [r for r in self._filtered if key in r and _ts(r[key]) >= bound]
        return self

    @property
    def not_(self):
        return _FakeNotAccessor(self)

    def lte(self, key, value):
        bound = _ts(value)
        self._filtered = [r for r in self._filtered if key in r and _ts(r[key]) <= bound]
        return self

    def in_(self, key, values):
        values_list = list(values)
        self._in_calls.append((key, values_list))
        values_set = set(values_list)
        self._filtered = [r for r in self._filtered if r.get(key) in values_set]
        return self

    def order(self, key, desc=False):
        """Encadeavel: `.order("created_at", desc=True).order("id", desc=True)`
        empilha AMBAS as chamadas em `_order_calls` (aplicadas em `execute()` como
        sort estavel multi-chave). `_order_key`/`_order_desc` continuam refletindo
        so a ULTIMA chamada — mantem `call_log["order"]` retrocompativel para quem
        so faz uma chamada (ex.: o `order desc + limit` do passo 3 de
        `_find_unanswered_conversations`, inspecionado por
        test_watchdog_pagination_2026_07_03.py).
        """
        self._order_key = key
        self._order_desc = desc
        self._order_calls.append((key, desc))
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def range(self, start, end):
        """`.range(start, end)` inclusive — mesma semantica do supabase-py
        (offset=start, limit=end-start+1). Usado pela paginacao do passo 1.
        """
        self._range = (start, end)
        return self

    def insert(self, payload):
        self._insert_payload = payload
        return self

    def execute(self):
        if self._insert_payload is not None:
            rows = self._insert_payload if isinstance(self._insert_payload, list) else [self._insert_payload]
            self._rows.extend(rows)
            return _Resp(list(rows))

        rows = list(self._filtered)
        # Sort estavel multi-chave: aplica as chamadas em ordem REVERSA (da ultima
        # p/ a primeira) — o sort do Python e estavel, entao a chave aplicada por
        # ULTIMO (a PRIMEIRA pedida) domina o resultado final; as anteriores
        # (aplicadas antes, ou seja pedidas DEPOIS) so sobrevivem como desempate.
        # Mesma semantica de `.order(a).order(b)` do PostgREST -> `ORDER BY a, b`.
        for key, desc in reversed(self._order_calls):
            rows.sort(key=lambda r, k=key: _order_sort_key(r.get(k)), reverse=desc)
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        elif self._limit_n is not None:
            rows = rows[: self._limit_n]

        if self._call_log is not None:
            self._call_log.append({
                "table": self._table_name,
                "select": self._select_cols,
                "in_": list(self._in_calls),
                "gte": list(self._gte_calls),
                "not_is_null": list(self._not_is_null_keys),
                "order": (self._order_key, self._order_desc),
                "order_calls": list(self._order_calls),
                "range": self._range,
                "limit": self._limit_n,
                "result_count": len(rows),
            })
        return _Resp(rows)


class FakeSupabase:
    """Fake por tabela. `tables` fica acessivel para seed/assert nos testes.

    `calls` registra cada `execute()` de leitura feito por QUALQUER FakeQuery emitido
    por esta instancia (ver `FakeQuery.execute`) — usado pelos testes de paginacao/
    chunking/embeds para inspecionar as queries reais emitidas pelo watchdog.
    """

    def __init__(self):
        self.tables: dict = {
            "messages": [],
            "conversations": [],
            "follow_up_jobs": [],
            "system_alerts": [],
        }
        self.calls: list = []

    def table(self, name):
        rows = self.tables.setdefault(name, [])
        return FakeQuery(rows, table_name=name, call_log=self.calls)


class _DedupBoomQuery(FakeQuery):
    """FakeQuery que lança SOMENTE na leitura (select ... execute) — simula uma falha
    transiente na query de dedup do watchdog (`_alert_recently_fired`) sem impedir o
    insert do alerta feito logo em seguida por `create_system_alert`. As duas funções
    batem na MESMA tabela `system_alerts` mas são interações distintas (1 select + 1
    insert) — por isso o fake precisa diferenciar: `_insert_payload is None` identifica
    uma query de leitura (select nunca seta `_insert_payload`).
    """

    def execute(self):
        if self._insert_payload is None:
            raise RuntimeError("system_alerts indisponível (falha simulada na leitura de dedup)")
        return super().execute()


class _DedupBoomSupabase(FakeSupabase):
    """FakeSupabase cujo `table("system_alerts")` devolve `_DedupBoomQuery` — as demais
    tabelas mantêm o comportamento normal do `FakeQuery`."""

    def table(self, name):
        if name == "system_alerts":
            rows = self.tables.setdefault(name, [])
            return _DedupBoomQuery(rows)
        return super().table(name)


@pytest.fixture
def fake_db(monkeypatch):
    """FakeSupabase compartilhado pelo watchdog E por create_system_alert (mesmo backing
    store) — assim o insert do alerta feito por app.alerts.service realmente aparece em
    fake.tables["system_alerts"], em vez de mockar create_system_alert diretamente.
    """
    fake = FakeSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)
    return fake


# --- Helpers de fixture --------------------------------------------------------

def _seed_message(fake, conversation_id, role, created_at, msg_id=None):
    """`msg_id` (opcional): id unico da mensagem, usado como tiebreaker secundario
    na paginacao real (`.order("id", desc=True)` — P3 minor do review de paginacao,
    ver test_watchdog_handoff_sla_2026_07_03.py). Default auto-incremental
    deterministico (baseado no tamanho atual da tabela) quando o chamador nao
    precisa controlar o valor explicitamente — retrocompativel com todo call site
    existente (nenhum passava um 5o argumento).
    """
    fake.tables["messages"].append({
        "id": msg_id if msg_id is not None else f"msg-{len(fake.tables['messages'])}",
        "conversation_id": conversation_id,
        "role": role,
        "created_at": _iso(created_at),
    })


def _seed_conversation_check1(fake, conv_id, *, mode, ai_enabled, opt_out=False, name="Lead"):
    fake.tables["conversations"].append({
        "id": conv_id,
        "channels": {"mode": mode},
        "leads": {"ai_enabled": ai_enabled, "opt_out": opt_out, "name": name},
    })


def _seed_alert(fake, alert_type, created_at, resolved=False):
    fake.tables["system_alerts"].append({
        "type": alert_type,
        "resolved": resolved,
        "created_at": _iso(created_at),
    })


# ── Check 1: ai_unresponsive (caso Welita) ─────────────────────────────────────

def test_check1_welita_detects_violation_and_inserts_alert(fake_db):
    """Msg de lead 21h atras, canal IA, ai_enabled=true, sem resposta -> 1 violacao + alerta."""
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake_db, "conv-welita", mode="ai", ai_enabled=True, name="Welita")
    _seed_message(fake_db, "conv-welita", "user", now - timedelta(hours=21))

    result = check_ai_unresponsive(now)

    assert result == 1
    alerts = fake_db.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "ai_unresponsive"
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["metadata"]["conversation_ids"] == ["conv-welita"]


def test_check1_assistant_reply_clears_violation(fake_db):
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake_db, "conv-welita", mode="ai", ai_enabled=True)
    _seed_message(fake_db, "conv-welita", "user", now - timedelta(hours=21))
    _seed_message(fake_db, "conv-welita", "assistant", now - timedelta(hours=20))

    assert check_ai_unresponsive(now) == 0
    assert fake_db.tables["system_alerts"] == []


def test_check1_system_reply_clears_violation(fake_db):
    """Resposta role=system (ex.: descarte automatico) tambem conta como resposta valida."""
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake_db, "conv-welita", mode="ai", ai_enabled=True)
    _seed_message(fake_db, "conv-welita", "user", now - timedelta(hours=21))
    _seed_message(fake_db, "conv-welita", "system", now - timedelta(hours=20))

    assert check_ai_unresponsive(now) == 0
    assert fake_db.tables["system_alerts"] == []


def test_check1_within_grace_period_is_ok(fake_db):
    """Msg de 2min atras (< 5min de grace) pode ainda estar em processamento -> nao e violacao."""
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake_db, "conv-fresh", mode="ai", ai_enabled=True)
    _seed_message(fake_db, "conv-fresh", "user", now - timedelta(minutes=2))

    assert check_ai_unresponsive(now) == 0
    assert fake_db.tables["system_alerts"] == []


def test_check1_dedup_skips_second_insert_but_still_reports_violation(fake_db):
    now = datetime.now(timezone.utc)
    _seed_alert(fake_db, "ai_unresponsive", now - timedelta(minutes=10))
    _seed_conversation_check1(fake_db, "conv-welita", mode="ai", ai_enabled=True)
    _seed_message(fake_db, "conv-welita", "user", now - timedelta(hours=21))

    result = check_ai_unresponsive(now)

    assert result == 1  # ainda detecta a violacao
    assert len(fake_db.tables["system_alerts"]) == 1  # mas nao duplica o alerta (so o seed)


def test_check1_dedup_read_falha_ainda_assim_insere_alerta_fail_open(monkeypatch):
    """Fail-open do plano ("falha no check de dedup → loga e cria o alerta mesmo
    assim"): se a QUERY de dedup (`_alert_recently_fired` lendo `system_alerts`) lança,
    o check não pode engolir a violação em silêncio — foi justamente o silêncio, não um
    alerta duplicado, que deixou o apagão de 01-02/07 invisível. O fake diferencia a
    leitura (lança) do insert (aceita), já que ambos batem na mesma tabela.
    """
    fake = _DedupBoomSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)

    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake, "conv-welita", mode="ai", ai_enabled=True, name="Welita")
    _seed_message(fake, "conv-welita", "user", now - timedelta(hours=21))

    result = check_ai_unresponsive(now)

    assert result == 1  # violacao detectada normalmente (candidatas/escopo/respostas nao mexem em system_alerts)
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 1  # fail-open: insere mesmo com a leitura de dedup quebrada
    assert alerts[0]["type"] == "ai_unresponsive"


def test_check1_detects_violation_when_embed_returns_list_shape(fake_db):
    """REGRESSÃO (auditoria 04/07): o Check 1 nunca disparou em produção (0 alertas)
    apesar de violações reais (Alessandro, IA ligada, 4h sem resposta). Causa provável:
    o PostgREST devolve um embed to-one (`channels!inner(mode)`) ora como objeto, ora
    como LISTA de 1 elemento; o `scope_ok` fazia `(row.get('channels') or {}).get('mode')`
    — que estoura AttributeError num shape de lista, derrubando o check inteiro a cada
    tick (engolido pelo try/except do loop). O teste existente só semeava DICT, então
    nunca pegava isso. Aqui os embeds vêm como LISTA — o check deve detectar a violação
    e alertar mesmo assim."""
    now = datetime.now(timezone.utc)
    # Embeds como lista de 1 elemento (shape alternativo do PostgREST).
    fake_db.tables["conversations"].append({
        "id": "conv-alessandro",
        "channels": [{"mode": "ai"}],
        "leads": [{"ai_enabled": True, "opt_out": False, "name": "Alessandro"}],
    })
    _seed_message(fake_db, "conv-alessandro", "user", now - timedelta(hours=4))

    result = check_ai_unresponsive(now)

    assert result == 1
    alerts = fake_db.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "ai_unresponsive"


def test_check1_human_channel_out_of_scope(fake_db):
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake_db, "conv-human", mode="human", ai_enabled=True)
    _seed_message(fake_db, "conv-human", "user", now - timedelta(hours=21))

    assert check_ai_unresponsive(now) == 0
    assert fake_db.tables["system_alerts"] == []


def test_check1_ai_disabled_lead_out_of_scope(fake_db):
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake_db, "conv-off", mode="ai", ai_enabled=False)
    _seed_message(fake_db, "conv-off", "user", now - timedelta(hours=21))

    assert check_ai_unresponsive(now) == 0
    assert fake_db.tables["system_alerts"] == []


# ── Check 3: followup_jobs_stuck ───────────────────────────────────────────────

def test_check3_stuck_jobs_detects_and_inserts_alert(fake_db):
    now = datetime.now(timezone.utc)
    fake_db.tables["follow_up_jobs"].extend([
        {
            "id": "job-1", "job_type": "standard", "status": "pending",
            "env_tag": W._ENV_TAG, "fire_at": _iso(now - timedelta(hours=3)),
        },
        {
            "id": "job-2", "job_type": "handoff_rescue", "status": "pending",
            "env_tag": W._ENV_TAG, "fire_at": _iso(now - timedelta(hours=4)),
        },
    ])

    result = check_stuck_followup_jobs(now)

    assert result == 2
    alerts = fake_db.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "followup_jobs_stuck"
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["metadata"]["count"] == 2
    assert alerts[0]["metadata"]["job_types"] == ["handoff_rescue", "standard"]


def test_check3_different_env_tag_out_of_scope(fake_db):
    now = datetime.now(timezone.utc)
    other_env = "production" if W._ENV_TAG == "dev" else "dev"
    fake_db.tables["follow_up_jobs"].append({
        "id": "job-x", "job_type": "standard", "status": "pending",
        "env_tag": other_env, "fire_at": _iso(now - timedelta(hours=3)),
    })

    assert check_stuck_followup_jobs(now) == 0
    assert fake_db.tables["system_alerts"] == []


# ── run_watchdog: REHEARSAL_MODE e isolamento de falha ─────────────────────────

@pytest.mark.asyncio
async def test_run_watchdog_rehearsal_mode_skips_all_checks(monkeypatch):
    """REHEARSAL_MODE=true -> o tick so dorme; nenhum check e chamado."""
    monkeypatch.setenv("REHEARSAL_MODE", "true")
    calls = []
    monkeypatch.setattr(W, "check_ai_unresponsive", lambda now: calls.append("check1") or 0)
    monkeypatch.setattr(W, "check_stuck_followup_jobs", lambda now: calls.append("check3") or 0)

    app_mock = MagicMock()
    with patch("app.watchdog.service.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await run_watchdog(app_mock)

    assert calls == []


@pytest.mark.asyncio
async def test_run_watchdog_normal_tick_calls_checks_and_recovery_despite_first_failure(monkeypatch):
    """Tick normal: chama os 3 checks + recover_orphaned_buffers mesmo se o 1o check lancar.

    Os 3 checks (incluindo o Check 5 `check_handoff_sla`) sao monkeypatchados — sem
    isso, `check_handoff_sla` real bateria no Supabase de verdade (URL fake do
    conftest, `https://test.supabase.co`) sempre que o horario real da maquina de
    teste cair dentro da janela util (8h-20h America/Sao_Paulo), tornando o teste
    dependente de hora do dia (flaky).
    """
    monkeypatch.setenv("REHEARSAL_MODE", "false")
    calls = []

    def _boom(now):
        calls.append("check1")
        raise RuntimeError("boom")

    monkeypatch.setattr(W, "check_ai_unresponsive", _boom)
    monkeypatch.setattr(W, "check_stuck_followup_jobs", lambda now: calls.append("check3") or 0)
    monkeypatch.setattr(W, "check_handoff_sla", lambda now: calls.append("check5") or 0)
    # Check 6 (cadence_dead) tem janela util 08h-20h BRT — sem o monkeypatch, o check
    # real bateria no Supabase fake do conftest na maior parte do dia (mesma
    # justificativa do check5 acima). Tambem VERIFICA o registro no ciclo (C2.2).
    monkeypatch.setattr(W, "check_cadence_dead", lambda now: calls.append("check6") or 0)

    recovery_calls = []

    async def _fake_recover(redis, **kwargs):
        recovery_calls.append((redis, kwargs))
        return 0

    monkeypatch.setattr(W, "recover_orphaned_buffers", _fake_recover)

    app_mock = MagicMock()
    app_mock.state.redis = "fake-redis-marker"

    with patch("app.watchdog.service.asyncio.sleep", new=AsyncMock(side_effect=asyncio.CancelledError)):
        with pytest.raises(asyncio.CancelledError):
            await run_watchdog(app_mock)

    assert calls == ["check1", "check3", "check5", "check6"]
    assert recovery_calls == [("fake-redis-marker", {"require_no_deadline": True, "source": "watchdog"})]
