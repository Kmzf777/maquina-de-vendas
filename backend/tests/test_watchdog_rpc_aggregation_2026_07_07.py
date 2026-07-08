"""Watchdog — agregacao server-side do passo 1 (RPC) — 2026-07-07.

`_find_unanswered_conversations` passou a preferir a RPC
`get_last_user_msg_per_conversation` (1 linha por conversa, GROUP BY no Postgres)
em vez de paginar ate 5.000 linhas cruas de `messages` por tick. Estes testes
cravam duas garantias:

  1. PARIDADE: com a RPC disponivel, o Check 1 detecta EXATAMENTE a mesma violacao
     que o caminho paginado detectaria (fantasma sem resposta viola; conversa
     clareada por resposta nao). A RPC nao pode mudar o veredito da rede de
     seguranca — so a forma de obter as candidatas.
  2. CORTE DE EGRESS: quando a RPC responde, o passo 1 NAO emite nenhuma leitura
     paginada de `messages` (`.range()`), que era o maior leitor recorrente do
     backend.
  3. FALLBACK: se a RPC falha/nao existe, cai no caminho paginado sem levantar —
     coberto indiretamente por todos os testes de watchdog existentes (FakeSupabase
     nao tem `.rpc`), e explicitamente aqui.

Reusa o FakeSupabase/seeds do arquivo base; adiciona um `.rpc()` que computa a
mesma agregacao sobre as mensagens semeadas (paridade com o SQL da migration).
"""
from types import SimpleNamespace

from app.watchdog import service as W
from app.watchdog.service import check_ai_unresponsive

from tests.test_watchdog_checks_2026_07_02 import (
    FakeSupabase,
    _seed_conversation_check1,
    _seed_message,
    _ts,
)

from datetime import datetime, timedelta, timezone


class _RpcFakeSupabase(FakeSupabase):
    """FakeSupabase + `.rpc("get_last_user_msg_per_conversation", ...)` que computa a
    MESMA agregacao do SQL da migration sobre `self.tables["messages"]`: ultima
    mensagem role=user por conversation_id na janela [p_since, p_until]."""

    def __init__(self):
        super().__init__()
        self.rpc_calls: list = []

    def rpc(self, name, params):
        self.rpc_calls.append({"name": name, "params": params})
        assert name == "get_last_user_msg_per_conversation"
        since, until = _ts(params["p_since"]), _ts(params["p_until"])
        latest: dict = {}
        for m in self.tables["messages"]:
            if m.get("role") != "user" or m.get("conversation_id") is None:
                continue
            if not (since <= _ts(m["created_at"]) <= until):
                continue
            cid, ts = m["conversation_id"], m["created_at"]
            if cid not in latest or _ts(ts) > _ts(latest[cid]):
                latest[cid] = ts
        rows = [{"conversation_id": cid, "last_user_at": ts} for cid, ts in latest.items()]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=rows))


def _fake_rpc_db(monkeypatch) -> _RpcFakeSupabase:
    W._RPC_AGG_DISABLED = False  # reset do flag global (pode ter sido desligado por outro teste)
    fake = _RpcFakeSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)
    return fake


def test_rpc_path_detects_same_violation_as_pagination(monkeypatch):
    """Paridade: fantasma (user sem resposta) viola; clareada (user + assistant mais
    nova) nao. Mesmo veredito que o caminho paginado (cf. test de paginacao)."""
    fake = _fake_rpc_db(monkeypatch)
    now = datetime.now(timezone.utc)

    _seed_conversation_check1(fake, "conv-clareada", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-clareada", "user", now - timedelta(hours=10))
    _seed_message(fake, "conv-clareada", "assistant", now - timedelta(hours=9))  # limpa

    _seed_conversation_check1(fake, "conv-fantasma", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-fantasma", "user", now - timedelta(hours=8))  # sem resposta

    result = check_ai_unresponsive(now)

    assert result == 1
    assert fake.tables["system_alerts"][0]["metadata"]["conversation_ids"] == ["conv-fantasma"]


def test_rpc_path_skips_paginated_message_reads(monkeypatch):
    """Corte de egress: com a RPC respondendo, o passo 1 nao emite leitura paginada
    de `messages` (`.range()`). A RPC e chamada exatamente uma vez."""
    fake = _fake_rpc_db(monkeypatch)
    now = datetime.now(timezone.utc)

    _seed_conversation_check1(fake, "conv-fantasma", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-fantasma", "user", now - timedelta(hours=8))

    check_ai_unresponsive(now)

    assert len(fake.rpc_calls) == 1
    paginated_msg_reads = [c for c in fake.calls if c["table"] == "messages" and c["range"] is not None]
    assert paginated_msg_reads == [], "passo 1 nao deveria paginar `messages` quando a RPC responde"


def test_falls_back_to_pagination_when_rpc_missing(monkeypatch):
    """Fallback: sem `.rpc` (FakeSupabase puro), o passo 1 volta a paginar `messages`
    sem levantar, e a deteccao continua correta."""
    W._RPC_AGG_DISABLED = False
    fake = FakeSupabase()  # sem .rpc -> AttributeError -> fallback
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)
    now = datetime.now(timezone.utc)

    _seed_conversation_check1(fake, "conv-fantasma", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-fantasma", "user", now - timedelta(hours=8))

    result = check_ai_unresponsive(now)

    assert result == 1
    paginated_msg_reads = [c for c in fake.calls if c["table"] == "messages" and c["range"] is not None]
    assert paginated_msg_reads, "sem RPC, o passo 1 deveria paginar `messages` (fallback)"
