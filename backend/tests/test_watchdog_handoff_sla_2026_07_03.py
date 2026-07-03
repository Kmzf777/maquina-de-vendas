"""Check 5 `handoff_sla_breach` (caso Juliana) + tiebreaker de paginacao (P3 minor)
— 2026-07-03 (Frente B, Task 2 / B2).

Contexto forense: Juliana (02/07) mandou mensagem no canal humano (pos-handoff, o
Joao ja tinha assumido a conversa) e ficou 1h46 sem resposta — "o Joao visualiza e
nao responde" — e ZERO alertas dispararam. O Check 2 (`orphan_lead_reply`) nao
cobre esse caso por DESIGN: `human_control=true` tira a conversa do escopo (e o
estado ESPERADO pos-handoff, a ponte da Frente B1). Este arquivo cobre o Check 5,
que fecha essa lacuna observando diretamente `conversations.last_customer_message_at`/
`last_seller_response_at` (mantidas por fluxo/trigger ja existentes — ver
migrations/20260525_sla_seller_columns.sql — o check nao precisa ler `messages`).

Tambem cobre o tiebreaker `.order("id")` da paginacao do passo 1 de
`_find_unanswered_conversations` (Minor P3 do review da Etapa 1, empacotado nesta
mesma task por tocar o mesmo arquivo/fake).

Reusa o FakeSupabase/FakeQuery de test_watchdog_checks_2026_07_02.py, estendido la
(aditivamente) com suporte a `.eq("embed.coluna", valor)` (dotted-key, necessario
p/ `.eq("channels.mode", "human")`) e `.order()` encadeado multi-chave (necessario
p/ o tiebreaker) — ambas capacidades genericas do fake, nao gambiarra local.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.watchdog import service as W
from app.watchdog.service import check_ai_unresponsive, check_handoff_sla

from tests.test_watchdog_checks_2026_07_02 import (  # reuso, nao duplicacao (ver docstring)
    FakeSupabase,
    _DedupBoomSupabase,
    _iso,
    _seed_conversation_check1,
    _seed_message,
)

SP_TZ = ZoneInfo("America/Sao_Paulo")


def _fake_db(monkeypatch) -> FakeSupabase:
    """Mesmo padrao da fixture `fake_db` do arquivo original, mas como funcao —
    espelha test_watchdog_pagination_2026_07_03.py (os testes aqui monkeypatcham
    caso a caso, nao usam a fixture pytest diretamente)."""
    fake = FakeSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)
    return fake


def _local(y, m, d, hh, mm=0) -> datetime:
    """Constroi um `now` (UTC) a partir de um horario LOCAL (America/Sao_Paulo) —
    deixa os casos de teste legiveis nos mesmos termos do brief ("17:22 local")."""
    return datetime(y, m, d, hh, mm, tzinfo=SP_TZ).astimezone(timezone.utc)


# --- Helpers de fixture (locais a este arquivo -- ver docstring do modulo) ------

def _seed_conversation_check5(
    fake, conv_id, *,
    mode="human",
    last_customer_message_at=None,
    last_seller_response_at=None,
    name="Lead",
    lead_id=None,
):
    fake.tables["conversations"].append({
        "id": conv_id,
        "lead_id": lead_id or f"lead-{conv_id}",
        "last_customer_message_at": _iso(last_customer_message_at) if last_customer_message_at else None,
        "last_seller_response_at": _iso(last_seller_response_at) if last_seller_response_at else None,
        "channels": {"mode": mode},
        "leads": {"name": name},
    })


def _seed_sla_alert(fake, conversation_ids, created_at, resolved=False):
    fake.tables["system_alerts"].append({
        "type": "handoff_sla_breach",
        "resolved": resolved,
        "created_at": _iso(created_at),
        "metadata": {"conversation_ids": list(conversation_ids)},
    })


# ── Check 5: handoff_sla_breach (caso Juliana) ──────────────────────────────────

def test_check5_juliana_detects_violation_and_inserts_warning_alert(monkeypatch):
    """Caso real: msg do lead ha 30min, ultima resposta do vendedor ha 2h (ou seja,
    ANTES da msg do lead) -> SLA de 20min estourado -> 1 violacao + alerta warning
    com o id da conversa nos metadata."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)  # 14h local, dentro da janela util (8h-20h)
    _seed_conversation_check5(
        fake, "conv-juliana",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=now - timedelta(hours=2),
        name="Juliana",
    )

    result = check_handoff_sla(now)

    assert result == 1
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["type"] == "handoff_sla_breach"
    assert alerts[0]["severity"] == "warning"
    assert alerts[0]["metadata"]["conversation_ids"] == ["conv-juliana"]
    assert "Juliana" in alerts[0]["message"]


def test_check5_seller_replied_after_customer_message_is_ok(monkeypatch):
    """`last_seller_response_at` > `last_customer_message_at` (Joao respondeu DEPOIS
    da ultima msg do lead) -> 0 violacoes."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)
    _seed_conversation_check5(
        fake, "conv-respondida",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=now - timedelta(minutes=5),
        name="Cliente",
    )

    assert check_handoff_sla(now) == 0
    assert fake.tables["system_alerts"] == []


def test_check5_within_sla_grace_is_ok(monkeypatch):
    """Msg do lead ha 10min (< HANDOFF_SLA_MINUTES=20) -> ainda dentro do SLA -> 0."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)
    _seed_conversation_check5(
        fake, "conv-fresca",
        last_customer_message_at=now - timedelta(minutes=10),
        last_seller_response_at=None,
        name="Cliente",
    )

    assert check_handoff_sla(now) == 0
    assert fake.tables["system_alerts"] == []


def test_check5_ai_channel_out_of_scope(monkeypatch):
    """Canal `mode='ai'` fica fora do escopo do Check 5 (so cobre canal humano)."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)
    _seed_conversation_check5(
        fake, "conv-ia", mode="ai",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=None,
        name="Cliente",
    )

    assert check_handoff_sla(now) == 0
    assert fake.tables["system_alerts"] == []


def test_check5_beyond_lookback_window_is_ignored(monkeypatch):
    """Msg do lead ha 30h (> HANDOFF_SLA_LOOKBACK_HOURS=24h) -> violacao antiga
    demais, fora da janela de deteccao (mesma logica do lookback dos Checks 1/2)."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)
    _seed_conversation_check5(
        fake, "conv-antiquissima",
        last_customer_message_at=now - timedelta(hours=30),
        last_seller_response_at=None,
        name="Antiga",
    )

    assert check_handoff_sla(now) == 0
    assert fake.tables["system_alerts"] == []


def test_check5_outside_useful_window_returns_zero_without_query(monkeypatch):
    """Fora da janela util (8h-20h local): retorna 0 SEM sequer consultar o banco —
    `fake.calls` fica vazio (nem `get_supabase()` chegaria a ser usado por uma
    query real)."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 23, 0)  # 23h local
    _seed_conversation_check5(
        fake, "conv-noite",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=None,
        name="Cliente",
    )

    result = check_handoff_sla(now)

    assert result == 0
    assert fake.calls == []
    assert fake.tables["system_alerts"] == []


def test_check5_dedup_by_conversation_excludes_only_already_alerted(monkeypatch):
    """Dedup POR CONVERSA: uma conversa ja coberta por um alerta recente (mesmo
    conversation_id nos metadata) nao re-alerta; uma conversa NOVA violada no mesmo
    tick gera alerta contendo SO a nova — nao duplica nem silencia a nova por causa
    da antiga (foi esse silencio que escondeu o caso Juliana)."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)

    _seed_sla_alert(fake, ["conv-antiga"], now - timedelta(minutes=30))  # dentro do dedup window (2h)

    _seed_conversation_check5(
        fake, "conv-antiga",
        last_customer_message_at=now - timedelta(minutes=40),
        last_seller_response_at=None,
        name="Antiga",
    )
    _seed_conversation_check5(
        fake, "conv-nova",
        last_customer_message_at=now - timedelta(minutes=25),
        last_seller_response_at=None,
        name="Nova",
    )

    result = check_handoff_sla(now)

    assert result == 2  # as duas SAO violacoes reais (dedup so filtra o ALERTA)
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 2  # 1 seed (dedup) + 1 novo -- nao duplicou a antiga
    new_alert = alerts[-1]
    assert new_alert["metadata"]["conversation_ids"] == ["conv-nova"]


def test_check5_dedup_counts_resolved_alerts_too(monkeypatch):
    """Diferente do dedup GLOBAL dos outros checks (`_alert_recently_fired`, que so
    olha `resolved=False`): aqui um alerta JA RESOLVIDO ainda conta pro dedup por
    conversa — resolver manualmente nao deveria reabrir a mesma conversa no
    proximo tick, so porque `resolved=True`."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)

    _seed_sla_alert(fake, ["conv-resolvida"], now - timedelta(minutes=10), resolved=True)
    _seed_conversation_check5(
        fake, "conv-resolvida",
        last_customer_message_at=now - timedelta(minutes=40),
        last_seller_response_at=None,
        name="Resolvida",
    )

    result = check_handoff_sla(now)

    assert result == 1
    assert len(fake.tables["system_alerts"]) == 1  # nenhum alerta NOVO inserido


def test_check5_dedup_read_failure_fails_open_and_still_alerts(monkeypatch):
    """Fail-open: se a QUERY de dedup por conversa falhar (`system_alerts`
    indisponivel), o check NAO pode engolir a violacao em silencio — insere o
    alerta mesmo assim. Mesmo contrato de `_alert_recently_fired`/Check 1
    (`test_check1_dedup_read_falha_ainda_assim_insere_alerta_fail_open`): foi
    justamente o silencio, nao um alerta duplicado, que escondeu o caso Juliana."""
    fake = _DedupBoomSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)

    now = _local(2026, 7, 2, 14, 0)
    _seed_conversation_check5(
        fake, "conv-juliana",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=None,
        name="Juliana",
    )

    result = check_handoff_sla(now)

    assert result == 1
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 1  # fail-open: insere mesmo com a leitura de dedup quebrada
    assert alerts[0]["type"] == "handoff_sla_breach"
    assert alerts[0]["metadata"]["conversation_ids"] == ["conv-juliana"]


def test_check5_dedup_sobra_zero_sem_alerta(monkeypatch):
    """Se, apos excluir as ja alertadas, nao sobrar nenhuma conversa NOVA -> sem
    alerta algum (mas a contagem de violacoes reais continua sendo reportada)."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)

    _seed_sla_alert(fake, ["conv-unica"], now - timedelta(minutes=5))
    _seed_conversation_check5(
        fake, "conv-unica",
        last_customer_message_at=now - timedelta(minutes=40),
        last_seller_response_at=None,
        name="Unica",
    )

    result = check_handoff_sla(now)

    assert result == 1
    assert len(fake.tables["system_alerts"]) == 1  # so o seed -- nenhum alerta novo


def test_check5_query_pushes_down_not_null_lookback_and_limit(monkeypatch):
    """Item 3 (review final B): sem predicado server-side em
    last_customer_message_at, o max-rows do PostgREST (~1000) truncaria
    silenciosamente sob volume alto. A query emitida pro fake precisa carregar
    `.not_.is_("last_customer_message_at", "null")`, `.gte()` com o MESMO piso de
    lookback usado no filtro Python e `.limit(HANDOFF_SLA_FETCH_LIMIT)` explicito —
    os filtros Python (lookback/SLA/dedup) continuam intactos como defesa em
    profundidade."""
    fake = _fake_db(monkeypatch)
    now = _local(2026, 7, 2, 14, 0)
    _seed_conversation_check5(
        fake, "conv-juliana",
        last_customer_message_at=now - timedelta(minutes=30),
        last_seller_response_at=None,
        name="Juliana",
    )

    result = check_handoff_sla(now)

    assert result == 1  # nao-regressao: a violacao real continua sendo detectada
    conv_calls = [c for c in fake.calls if c["table"] == "conversations"]
    assert len(conv_calls) == 1
    call = conv_calls[0]

    assert call["not_is_null"] == ["last_customer_message_at"]
    assert call["limit"] == W.HANDOFF_SLA_FETCH_LIMIT

    gte_by_key = dict(call["gte"])
    assert "last_customer_message_at" in gte_by_key
    expected_floor = now - timedelta(hours=W.HANDOFF_SLA_LOOKBACK_HOURS)
    actual_floor = datetime.fromisoformat(
        str(gte_by_key["last_customer_message_at"]).replace("Z", "+00:00")
    )
    assert abs((actual_floor - expected_floor).total_seconds()) < 1


# ── Tiebreaker (P3 minor): .order("id") na paginacao do passo 1 ────────────────

def test_pagination_tiebreaker_orders_by_id_after_created_at(monkeypatch):
    """A query paginada do passo 1 (mensagens candidatas) deve emitir
    `.order("created_at", desc=True).order("id", desc=True)` — a chave `id`
    (unica) desempata mensagens com o MESMO `created_at`, o que `.range()`
    sozinho nao garante de forma estavel entre paginas."""
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake, "conv-x", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-x", "user", now - timedelta(hours=6))

    assert check_ai_unresponsive(now) == 1

    page_calls = [c for c in fake.calls if c["table"] == "messages" and c["range"] is not None]
    assert page_calls, "passo 1 (paginado) deveria ter sido chamado"
    for c in page_calls:
        assert c["order_calls"] == [("created_at", True), ("id", True)]


def test_pagination_tiebreaker_keeps_both_tied_messages(monkeypatch):
    """Duas mensagens de conversas DIFERENTES com o MESMO `created_at` (empate) —
    ambas precisam sobreviver a paginacao/reducao "ultima msg por conversation_id"
    e ser detectadas como violacao; o tiebreaker por `id` garante ordem
    deterministica entre elas (sem o `id`, um sort instavel poderia, em tese,
    tratar o empate de forma inconsistente entre execucoes)."""
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)
    tied_ts = now - timedelta(hours=6)

    _seed_conversation_check1(fake, "conv-tie-a", mode="ai", ai_enabled=True)
    _seed_conversation_check1(fake, "conv-tie-b", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-tie-a", "user", tied_ts, msg_id="msg-tie-a")
    _seed_message(fake, "conv-tie-b", "user", tied_ts, msg_id="msg-tie-b")

    result = check_ai_unresponsive(now)

    assert result == 2
    alert_ids = set(fake.tables["system_alerts"][0]["metadata"]["conversation_ids"])
    assert alert_ids == {"conv-tie-a", "conv-tie-b"}


def test_pagination_tiebreaker_does_not_affect_replies_step_single_order(monkeypatch):
    """Nao-regressao: o passo 3 (respostas) continua com UMA unica chamada
    `.order("created_at", desc=True)` — o tiebreaker e exclusivo do passo 1
    (candidatas). `order_calls` com 1 elemento so confirma que o passo 3 nao foi
    alterado por engano."""
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake, "conv-clareada", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-clareada", "user", now - timedelta(hours=10))
    _seed_message(fake, "conv-clareada", "assistant", now - timedelta(hours=9))

    assert check_ai_unresponsive(now) == 0

    replies_calls = [c for c in fake.calls if c["table"] == "messages" and c["limit"] == W.REPLIES_FETCH_LIMIT]
    assert replies_calls, "passo 3 deveria ter emitido ao menos 1 query de replies"
    for c in replies_calls:
        assert c["order_calls"] == [("created_at", True)]
