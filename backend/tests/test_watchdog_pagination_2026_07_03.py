"""Watchdog — pendencias pos-review da Etapa 1 (follow-up do E1) — 2026-07-03.

O review final da Etapa 1 (`docs(plan): pendencias pos-review E1/E2`, commit 37394ae)
apontou 3 riscos em `_find_unanswered_conversations` (backend/app/watchdog/service.py):

  1. Passo 1 (candidatas) usava uma UNICA pagina (`.limit(CANDIDATE_MESSAGE_LIMIT)`).
     Sob rajada, se 500+ mensagens MAIS NOVAS que uma conversa fantasma (candidata
     antiga, ainda sem resposta) caem na mesma janela, elas ocupam toda a pagina e a
     fantasma nunca aparece em `last_user_msg` — MISS completo da violacao real.
  2. Passos 2/3 usavam `.in_("id"/"conversation_id", ids)` com a lista INTEIRA de
     candidatas — sob volume alto (500+ UUIDs), risco de URL gigante.
  3. Passo 3 (respostas) nao tinha order/limit — buscava TODAS as respostas desde a
     candidata mais antiga, sem teto.

Este arquivo cobre a correcao: paginacao do passo 1 (`.range()` + teto de seguranca
`CANDIDATE_MAX_PAGES`), chunking de ids nos passos 2/3 (`ID_CHUNK_SIZE`), replies
bounded no passo 3 (`order desc + limit(REPLIES_FETCH_LIMIT)`) e embeds enxutos
(Check 1/2 param de select sem campos nao consumidos por `scope_ok`).

Reusa o FakeSupabase/FakeQuery de test_watchdog_checks_2026_07_02.py (estendido la
com `.range()` + `calls` log, ja que sao capacidades genericas do fake) em vez de
duplicar — importa a classe e os helpers de seed direto do modulo de teste existente.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.watchdog import service as W
from app.watchdog.service import check_ai_unresponsive, check_orphan_lead_reply

from tests.test_watchdog_checks_2026_07_02 import (  # reuso, nao duplicacao (ver docstring)
    FakeSupabase,
    _seed_conversation_check1,
    _seed_conversation_check2,
    _seed_message,
)


def _fake_db(monkeypatch) -> FakeSupabase:
    """Mesmo padrao da fixture `fake_db` do arquivo original, mas como funcao — os
    testes aqui monkeypatcham em cada caso (nao usam a fixture pytest diretamente
    porque `monkeypatch` ja e injetado por parametro nos testes abaixo).
    """
    fake = FakeSupabase()
    monkeypatch.setattr("app.watchdog.service.get_supabase", lambda: fake)
    monkeypatch.setattr("app.alerts.service.get_supabase", lambda: fake)
    return fake


# ── Caso 1: MISS completo corrigido pela paginacao ─────────────────────────────

def test_pagination_finds_ghost_conversation_hidden_behind_single_page(monkeypatch):
    """O finding do review: 1 conversa fantasma (candidata antiga, sem resposta) +
    501 conversas com mensagens MAIS NOVAS na mesma janela. Antes da paginacao, a
    query unica (`order desc + limit(500)`) devolvia so as 500 mais novas — a
    fantasma (a mais antiga de todas) nunca aparecia em `last_user_msg`, e o check
    reportava 0 violacoes (MISS completo). Com paginacao (`.range()` em loop), o
    passo 1 continua buscando ate a fantasma entrar na janela agregada.
    """
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)

    _seed_conversation_check1(fake, "conv-fantasma", mode="ai", ai_enabled=True, name="Fantasma")
    _seed_message(fake, "conv-fantasma", "user", now - timedelta(hours=20))

    # 501 (> CANDIDATE_PAGE_SIZE) mensagens de OUTRAS conversas, mais novas que a
    # fantasma mas ainda fora do grace — nao registradas em `conversations`, entao
    # saem do escopo no passo 2 mesmo se aparecerem como candidatas (o teste so
    # precisa que elas ocupem a "pagina" antiga; nao precisam de resposta/escopo).
    for i in range(501):
        _seed_message(fake, f"conv-flood-{i}", "user", now - timedelta(hours=19, seconds=i))

    result = check_ai_unresponsive(now)

    assert result == 1
    alerts = fake.tables["system_alerts"]
    assert len(alerts) == 1
    assert alerts[0]["metadata"]["conversation_ids"] == ["conv-fantasma"]


# ── Caso 2: teto de paginas ──────────────────────────────────────────────────

def test_pagination_stops_at_max_pages_and_logs_truncation_warning(monkeypatch, caplog):
    """'Paginas infinitas': mais candidatas do que CANDIDATE_MAX_PAGES *
    CANDIDATE_PAGE_SIZE cabem na janela. O passo 1 nao pode paginar sem fim (URL/
    tempo ilimitados) — para no teto de seguranca e loga o truncamento. Falso
    negativo aceito (mensagens mais antigas que o teto ficam de fora) — o teto e uma
    ordem de grandeza acima do volume atual (ver docstring da constante em
    service.py).
    """
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)

    total = W.CANDIDATE_MAX_PAGES * W.CANDIDATE_PAGE_SIZE + 1  # garante a ultima pagina cheia
    base_offset = timedelta(minutes=W.AI_UNRESPONSIVE_GRACE_MINUTES, seconds=1)
    for i in range(total):
        _seed_message(fake, f"conv-flood-{i}", "user", now - base_offset - timedelta(seconds=i))

    with caplog.at_level(logging.WARNING, logger="app.watchdog.service"):
        check_ai_unresponsive(now)

    assert "truncada em 10" in caplog.text

    page_calls = [c for c in fake.calls if c["table"] == "messages" and c["range"] is not None]
    assert len(page_calls) == W.CANDIDATE_MAX_PAGES
    assert [c["range"] for c in page_calls] == [
        (i * W.CANDIDATE_PAGE_SIZE, i * W.CANDIDATE_PAGE_SIZE + W.CANDIDATE_PAGE_SIZE - 1)
        for i in range(W.CANDIDATE_MAX_PAGES)
    ]


# ── Caso 3: chunking de ids nos passos 2/3 ───────────────────────────────────

def test_chunking_splits_over_100_ids_and_aggregates_result_correctly(monkeypatch):
    """>100 (ID_CHUNK_SIZE) conversation_ids no escopo -> passos 2 e 3 chamam `.in_()`
    em multiplos chunks (fake registra cada `execute()` em `fake.calls`). O resultado
    agregado precisa continuar correto — em especial, uma resposta que "limpa" uma
    conversa cujo chunk NAO e o ultimo so fica correta se os chunks forem agregados
    (extend), nao substituidos (overwrite).
    """
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)

    n_convs = 101  # > ID_CHUNK_SIZE (100) -> pelo menos 2 chunks
    for i in range(n_convs):
        conv_id = f"conv-{i:03d}"
        _seed_conversation_check2(fake, conv_id, ai_enabled=False, human_control=False, opt_out=False)
        _seed_message(fake, conv_id, "user", now - timedelta(minutes=40))
        if i % 2 == 0:
            _seed_message(fake, conv_id, "assistant", now - timedelta(minutes=35))  # limpa a violacao

    result = check_orphan_lead_reply(now)

    expected_violated = len([i for i in range(n_convs) if i % 2 != 0])  # 50 impares sem resposta
    assert result == expected_violated

    conv_calls = [c for c in fake.calls if c["table"] == "conversations"]
    assert len(conv_calls) >= 2  # prova que chunkeou (nao 1 unico .in_() gigante)

    id_chunks = [vals for c in conv_calls for key, vals in c["in_"] if key == "id"]
    assert all(len(chunk) <= W.ID_CHUNK_SIZE for chunk in id_chunks)
    seen_ids = {v for chunk in id_chunks for v in chunk}
    assert seen_ids == {f"conv-{i:03d}" for i in range(n_convs)}  # nenhum id perdido/duplicado


# ── Caso 4: replies bounded (order desc + limit) ─────────────────────────────

def test_replies_query_bounded_by_order_desc_and_limit_still_detects_violation(monkeypatch):
    """Passo 3 (respostas) agora pede `order("created_at", desc=True).limit(
    REPLIES_FETCH_LIMIT)` por chunk. Direcao segura por construcao: a resposta mais
    NOVA fica no topo do order desc — e ela que CLAREIA a violacao; truncar as mais
    antigas (fora do limit) so pode gerar falso positivo (alerta a mais), nunca
    esconder uma violacao real. Este teste crava o contrato: a conversa cuja unica
    resposta e a mais nova continua sendo corretamente limpa, e uma segunda conversa
    sem nenhuma resposta continua violada (bounding nao quebra a deteccao real).
    """
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)

    _seed_conversation_check1(fake, "conv-clareada", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-clareada", "user", now - timedelta(hours=10))
    _seed_message(fake, "conv-clareada", "assistant", now - timedelta(hours=9))  # mais nova

    _seed_conversation_check1(fake, "conv-orfa", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-orfa", "user", now - timedelta(hours=8))  # sem resposta

    result = check_ai_unresponsive(now)

    assert result == 1
    assert fake.tables["system_alerts"][0]["metadata"]["conversation_ids"] == ["conv-orfa"]

    replies_calls = [c for c in fake.calls if c["table"] == "messages" and c["limit"] == W.REPLIES_FETCH_LIMIT]
    assert replies_calls, "passo 3 deveria emitir ao menos 1 query de replies com limit(REPLIES_FETCH_LIMIT)"
    assert all(c["order"] == ("created_at", True) for c in replies_calls)


# ── Caso 5: embeds enxutos ────────────────────────────────────────────────────

def test_check1_embed_select_omits_unused_name_and_opt_out(monkeypatch):
    """Check 1 (`scope_ok` so le `channels.mode` e `leads.ai_enabled`) nao deveria
    pedir `name`/`opt_out` no embed de `leads` — campos nunca lidos por `scope_ok`.
    """
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)
    _seed_conversation_check1(fake, "conv-x", mode="ai", ai_enabled=True)
    _seed_message(fake, "conv-x", "user", now - timedelta(hours=6))

    assert check_ai_unresponsive(now) == 1

    conv_calls = [c for c in fake.calls if c["table"] == "conversations"]
    assert conv_calls, "passo 2 deveria ter sido chamado"
    for c in conv_calls:
        assert "name" not in c["select"]
        assert "opt_out" not in c["select"]
        assert "ai_enabled" in c["select"]


def test_check2_embed_select_omits_unused_name(monkeypatch):
    """Check 2 (`scope_ok` le `ai_enabled`/`human_control`/`opt_out`) nao deveria
    pedir `name` no embed de `leads` — nunca lido por `scope_ok`.
    """
    fake = _fake_db(monkeypatch)
    now = datetime.now(timezone.utc)
    _seed_conversation_check2(fake, "conv-y", ai_enabled=False, human_control=False, opt_out=False)
    _seed_message(fake, "conv-y", "user", now - timedelta(minutes=40))

    assert check_orphan_lead_reply(now) == 1

    conv_calls = [c for c in fake.calls if c["table"] == "conversations"]
    assert conv_calls, "passo 2 deveria ter sido chamado"
    for c in conv_calls:
        assert "name" not in c["select"]
        assert "human_control" in c["select"]
        assert "opt_out" in c["select"]
