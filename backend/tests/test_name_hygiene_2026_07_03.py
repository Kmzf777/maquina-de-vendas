"""Testes de higiene de nome (LP -> CRM -> templates) — Task 4 (C-4).

Casos reais (auditoria 01-02/07): leads gravados como "Olá, boa tarde", "Boa
tarde.... Luiz", "Boa tarde." cascatearam para os templates — o disparo de LP saudou
"olá Olá," e o resgate do João abriu "Olá, Olá,!" porque `lead_name.split()[0]` pegava
a palavra da saudação como se fosse o nome do lead. A Valéria descobriu o nome real
("Luiz") no resumo de handoff, mas `leads.name` nunca foi corrigido.

`strip_greeting_prefix` (leads/service.py) resolve na origem: remove a saudação (e
recupera um nome real colado depois dela, "Boa tarde.... Luiz" -> "Luiz"), integrado em
`_sanitize_lead_name` (lp_webhook) e `sanitize_display_name` (leads/service, usado pelo
prompt via build_base_prompt). Quando não sobra nome nenhum, os renderizadores de
template (João, lp_welcome, reopen) caem no fallback neutro "tudo bem" em vez de vazar a
saudação pro cliente ("olá Olá," / "Olá, Olá,!").
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pytest

from app.leads.service import strip_greeting_prefix, sanitize_display_name
from app.lp_webhook.service import _sanitize_lead_name
from app.follow_up.scheduler import (
    _build_joao_handoff_components,
    _render_joao_handoff_text,
    _process_lp_welcome,
    _NAME_FALLBACK,
)


# ─── strip_greeting_prefix (helper compartilhado, leads/service.py) ─────────

@pytest.mark.parametrize("raw,expected", [
    # Casos reais (auditoria 01-02/07)
    ("Boa tarde.... Luiz", "Luiz"),
    ("Olá, boa tarde", None),
    ("Boa tarde.", None),
    ("Maycon", "Maycon"),  # nome limpo, sem saudacao -> intocado
    # Acentos / caixa
    ("OLÁ, TUDO BEM", None),
    ("ola, tudo bem", None),          # sem acento
    ("Oi! Marcos", "Marcos"),
    ("BOM DIA, joão", "joão"),        # preserva a caixa/acento do restante (nao vira "João")
    ("e aí, tudo bem", None),         # saudacao composta dupla
    ("E AI", None),                   # maiuscula, sem acento
    ("Bom dia", None),
    ("Tudo bem", None),
    ("boa tarde... josé", "josé"),    # nao forca title-case no restante
    ("", None),
    (None, None),
    ("   ", None),                    # so espaco
    # Sem saudacao nenhuma -> intocado
    ("Elisangele Accordi", "Elisangele Accordi"),
    ("Ana Paula", "Ana Paula"),
])
def test_strip_greeting_prefix(raw, expected):
    assert strip_greeting_prefix(raw) == expected


def test_strip_greeting_prefix_nao_trunca_nome_que_comeca_parecido_com_saudacao():
    """'Olavo'/'Oiane' começam com as mesmas letras de saudações mas NÃO são saudação —
    a fronteira de palavra (\\b) no matcher impede o corte incorreto."""
    assert strip_greeting_prefix("Olavo") == "Olavo"
    assert strip_greeting_prefix("Oiane Ferreira") == "Oiane Ferreira"


# ─── _sanitize_lead_name (lp_webhook/service.py) integra o strip ───────────

@pytest.mark.parametrize("raw,exp_name,exp_msg,exp_email", [
    # Casos reais: nome recuperado após a saudação
    ("Boa tarde.... Luiz", "Luiz", None, None),
    # Casos reais: SÓ saudação -> sem nome, texto cru preservado em lp_message
    ("Olá, boa tarde", None, "Olá, boa tarde", None),
    ("Boa tarde.", None, "Boa tarde.", None),
    # Nome limpo, sem saudação -> intocado (regressão)
    ("Maycon", "Maycon", None, None),
    ("Maria Silva", "Maria Silva", None, None),
    # Saudação + e-mail colado -> ainda extrai o e-mail do texto ORIGINAL
    ("Bom dia, fulano@gmail.com", None, "Bom dia, fulano@gmail.com", "fulano@gmail.com"),
])
def test_sanitize_lead_name_integra_strip_greeting_prefix(raw, exp_name, exp_msg, exp_email):
    name, msg, email = _sanitize_lead_name(raw)
    assert name == exp_name
    assert msg == exp_msg
    assert email == exp_email


def test_sanitize_lead_name_saudacao_seguida_de_pergunta_continua_dirty():
    """Depois de remover a saudação, o RESTANTE ainda pode ser "sujo" (pergunta) — o
    texto cru ORIGINAL (não o fragmento pós-strip) é preservado em lp_message, igual ao
    comportamento pré-existente para valores que não são nome."""
    name, msg, email = _sanitize_lead_name("Bom dia, qual o valor mínimo?")
    assert name is None
    assert msg == "Bom dia, qual o valor mínimo?"
    assert email is None


# ─── sanitize_display_name (leads/service.py, usado pelo build_base_prompt) ─

@pytest.mark.parametrize("raw,expected", [
    ("Boa tarde.... Luiz", "Luiz"),
    ("Olá, boa tarde", None),
    ("Boa tarde.", None),
    ("Maycon", "Maycon"),
    # Regressão: handle/import continuam rejeitados
    ("Brunor_barista", None),
    ("João - Import - Leads Frios", None),
    # Regressão: nomes legítimos continuam intocados
    ("João Silva", "João Silva"),
    (" Maria ", "Maria"),
])
def test_sanitize_display_name_com_saudacao(raw, expected):
    assert sanitize_display_name(raw) == expected


# ─── pushname-apelido não é nome (QA 10/07 — lead "querido") ─────────────────
# Caso real: pushname "querido" passou o filtro conservador, virou leads.name e a
# Valéria abriu bolha com "boa, querido" num lead B2B. Apelidos afetivos genéricos
# usados como pushname NÃO são nomes — match exato do nome inteiro normalizado,
# para nunca derrubar nomes legítimos.

@pytest.mark.parametrize("raw", [
    "querido", "Querida", "AMOR", "meu amor", "mozão", "Mozao",
    "bebê", "bebe", "vida", "eu", "Eu mesmo", "eu mesma",
])
def test_sanitize_display_name_descarta_apelido_de_pushname(raw):
    assert sanitize_display_name(raw) is None, (
        f"apelido de pushname {raw!r} virou nome de lead — a Valéria chamaria o lead assim"
    )


@pytest.mark.parametrize("raw", [
    # Nomes reais que CONTÊM (mas não SÃO) termos da blocklist — jamais descartar.
    # "Vida Nova Cafés" saiu desta lista na varredura 12/07: nome de EMPRESA como
    # vocativo é a falha (caso "fechado, Empório Da Canastra") — agora cai em sem-nome.
    "Amora", "Vidal", "Eugênio", "Eunice",
])
def test_sanitize_display_name_preserva_nomes_parecidos_com_apelido(raw):
    assert sanitize_display_name(raw) == raw


# ─── _build_joao_handoff_components: nome-lixo -> fallback "tudo bem" ───────

def test_build_joao_handoff_components_nome_so_saudacao_cai_no_fallback():
    """Caso real: "Olá, boa tarde" não pode virar o param nome_do_lead="Olá," (que
    produzia "Olá, Olá,!" na mensagem enviada)."""
    components = _build_joao_handoff_components("Olá, boa tarde")
    params = components[0]["parameters"]
    assert params[0] == {"type": "text", "parameter_name": "nome_do_lead", "text": _NAME_FALLBACK}


def test_build_joao_handoff_components_nome_vazio_cai_no_fallback():
    """ATENÇÃO (Task C-4): antes mandava "" quando lead_name vazio — agora usa o
    fallback, já que a Meta rejeita parâmetro de template vazio."""
    components = _build_joao_handoff_components("")
    params = components[0]["parameters"]
    assert params[0] == {"type": "text", "parameter_name": "nome_do_lead", "text": _NAME_FALLBACK}


def test_build_joao_handoff_components_recupera_nome_real_apos_saudacao():
    components = _build_joao_handoff_components("Boa tarde.... Luiz")
    params = components[0]["parameters"]
    assert params[0] == {"type": "text", "parameter_name": "nome_do_lead", "text": "Luiz"}


def test_build_joao_handoff_components_nome_limpo_nao_afetado():
    """Regressão: nome legítimo continua funcionando como antes (mesmo caso do
    test_handoff_rescue.py::test_build_joao_handoff_components_uses_two_named_params)."""
    components = _build_joao_handoff_components("Elisangele Accordi")
    params = components[0]["parameters"]
    assert params[0] == {"type": "text", "parameter_name": "nome_do_lead", "text": "Elisangele"}


# ─── _render_joao_handoff_text: persistido == enviado ────────────────────────

def test_render_joao_handoff_text_nome_so_saudacao_usa_fallback():
    txt = _render_joao_handoff_text("Olá, boa tarde")
    assert txt.startswith(f"Olá, {_NAME_FALLBACK}!")


def test_render_joao_handoff_text_nome_vazio_usa_fallback():
    txt = _render_joao_handoff_text("")
    assert txt.startswith(f"Olá, {_NAME_FALLBACK}!")


def test_render_joao_handoff_text_recupera_nome_real_apos_saudacao():
    txt = _render_joao_handoff_text("Boa tarde.... Luiz")
    assert txt.startswith("Olá, Luiz!")


def test_render_joao_handoff_text_coerente_com_componentes_enviados():
    """O texto PERSISTIDO deve renderizar o MESMO nome/fallback que
    _build_joao_handoff_components manda pra Meta — senão o histórico no CRM diverge do
    que o lead de fato recebeu no WhatsApp."""
    for lead_name in ("Olá, boa tarde", "", "Boa tarde.... Luiz", "Maria Silva"):
        components = _build_joao_handoff_components(lead_name)
        sent_name = components[0]["parameters"][0]["text"]
        rendered = _render_joao_handoff_text(lead_name)
        assert rendered.startswith(f"Olá, {sent_name}!")


# ─── _process_lp_welcome (scheduler): nome-lixo -> fallback "tudo bem" ──────

def _make_lp_job(lead_name: str, **overrides) -> dict:
    job = {
        "id": "job-lp-hygiene-1",
        "lead_id": "lead-1",
        "conversation_id": "conv-1",
        "channel_id": "ch-1",
        "channels": {"id": "ch-1", "provider": "meta_cloud", "provider_config": {"access_token": "tok"}},
        "leads": {"id": "lead-1", "phone": "5534999999999", "last_customer_message_at": None},
        "conversations": {"id": "conv-1", "last_customer_message_at": None},
        "metadata": {
            "lead_phone": "5534999999999",
            "lead_name": lead_name,
            "template_name": "lp_solicitacao_recebida",
            "language_code": "pt_BR",
        },
    }
    job.update(overrides)
    return job


@pytest.mark.asyncio
async def test_process_lp_welcome_nome_so_saudacao_envia_fallback():
    """Caso real: lead gravado como "Olá, boa tarde" não pode saudar "olá Olá," — o
    template recebe o fallback neutro "tudo bem"."""
    job = _make_lp_job("Olá, boa tarde")
    now = datetime(2026, 7, 3, 10, 15, 0, tzinfo=timezone.utc)

    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.x"}]})

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider), \
         patch("app.follow_up.scheduler.create_deal"), \
         patch("app.follow_up.scheduler.record_dispatch_note"), \
         patch("app.follow_up.scheduler._mark_sent"):
        await _process_lp_welcome(job, now)

    mock_provider.send_template.assert_awaited_once_with(
        "5534999999999", "lp_solicitacao_recebida",
        components=[{
            "type": "body",
            "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": _NAME_FALLBACK}],
        }],
        language_code="pt_BR",
    )


@pytest.mark.asyncio
async def test_process_lp_welcome_recupera_nome_real_apos_saudacao():
    """Caso real: "Boa tarde.... Luiz" deve disparar com primeiro_nome="Luiz", não "Boa"."""
    job = _make_lp_job("Boa tarde.... Luiz")
    now = datetime(2026, 7, 3, 10, 15, 0, tzinfo=timezone.utc)

    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.y"}]})

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider), \
         patch("app.follow_up.scheduler.create_deal"), \
         patch("app.follow_up.scheduler.record_dispatch_note"), \
         patch("app.follow_up.scheduler._mark_sent"):
        await _process_lp_welcome(job, now)

    mock_provider.send_template.assert_awaited_once_with(
        "5534999999999", "lp_solicitacao_recebida",
        components=[{
            "type": "body",
            "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": "Luiz"}],
        }],
        language_code="pt_BR",
    )


@pytest.mark.asyncio
async def test_process_lp_welcome_sem_nome_nenhum_envia_fallback():
    """Sem lead_name nenhum (nem metadata, nem leads.name) — o param NOMEADO é
    OBRIGATÓRIO no template, então SEMPRE vai com o fallback (nunca components=None,
    que arriscava rejeição da Meta por parâmetro ausente)."""
    job = _make_lp_job("")
    now = datetime(2026, 7, 3, 10, 15, 0, tzinfo=timezone.utc)

    mock_provider = AsyncMock()
    mock_provider.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.z"}]})

    with patch("app.follow_up.scheduler.MetaCloudClient", return_value=mock_provider), \
         patch("app.follow_up.scheduler.create_deal"), \
         patch("app.follow_up.scheduler.record_dispatch_note"), \
         patch("app.follow_up.scheduler._mark_sent"):
        await _process_lp_welcome(job, now)

    _, kwargs = mock_provider.send_template.call_args
    assert kwargs["components"] == [{
        "type": "body",
        "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": _NAME_FALLBACK}],
    }]


# ─── fire_reopen_template: template coerente com silêncio DO LEAD (Rodada 5) ────
# O antigo continuar_conversa pedia desculpas por atraso NOSSO ("não consegui te
# responder a tempo") num gatilho onde quem silenciou foi o LEAD — incoerência
# comercial vista ao vivo em 10/07 (5 leads). Novo: utilidade_geral_confirmacao_v1
# (utility aprovado, en_US, corpo pt): "O Cafe Canastra esta aguardando sua
# confirmacao sobre {{2}} desde {{3}}" — 3 params posicionais determinísticos.

import re as _re


@pytest.mark.asyncio
async def test_fire_reopen_template_envia_3_params_e_locale_aprovado(monkeypatch):
    """Nome sanitizado (recupera 'Luiz' da saudação), assunto fixo honesto e data da
    última msg do lead — enviados como params POSICIONAIS com o locale da aprovação."""
    from app.follow_up import scheduler

    captured = {}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            captured.update(name=name, components=components, language_code=language_code)
            return {"messages": [{"id": "wamid-hygiene"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "save_message_conv", lambda **kw: None)
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: None)
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda *a: None)
    monkeypatch.setattr(scheduler, "extract_wamid", lambda r: "wamid-hygiene")

    lead = {"id": "lead-1", "name": "Boa tarde.... Luiz", "phone": "5511999999999"}
    job = {
        "id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1", "metadata": {},
        "conversations": {"last_customer_message_at": "2026-07-09T17:58:38+00:00"},
    }
    ok = await scheduler.fire_reopen_template(
        job, lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x",
    )
    assert ok is True
    assert captured["name"] == "utilidade_geral_confirmacao_v1"
    assert captured["language_code"] == "en_US", "locale deve ser o da APROVAÇÃO na Meta"
    params = captured["components"][0]["parameters"]
    assert [p["type"] for p in params] == ["text", "text", "text"]
    assert all("parameter_name" not in p for p in params), "params são POSICIONAIS"
    assert params[0]["text"] == "Luiz"
    assert params[1]["text"] == "a continuidade do atendimento"
    assert params[2]["text"] == "09/07/2026"  # 17:58 UTC = 14:58 BRT, mesmo dia


@pytest.mark.asyncio
async def test_fire_reopen_template_nome_lixo_cai_no_fallback(monkeypatch):
    """Nome-saudação puro → param 1 vira o fallback neutro ('tudo bem')."""
    from app.follow_up import scheduler

    captured = {}

    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            captured["components"] = components
            return {"messages": [{"id": "wamid-hygiene"}]}

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "save_message_conv", lambda **kw: None)
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: None)
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda *a: None)
    monkeypatch.setattr(scheduler, "extract_wamid", lambda r: "wamid-hygiene")

    lead = {"id": "lead-1", "name": "Boa tarde.", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(
        {"id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1", "metadata": {}},
        lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x",
    )
    assert ok is True
    assert captured["components"][0]["parameters"][0]["text"] == scheduler._NAME_FALLBACK


# ─── fire_reopen_template: persistido == enviado (QA 10/07, Rodada 4) ───────────
# O lead recebia o template aprovado ("Olá \nInfelizmente não consegui te responder
# a tempo..."), mas a conversa gravava o PLACEHOLDER "continuar a conversa de onde
# paramos" como fala da Valéria — poluindo o CRM (parece mensagem errática enviada)
# e o histórico que o LLM relê nos turnos seguintes. 5 casos reais em 10/07
# (Tainara, Luciana, Maria, Lucas, Yandra — toques seq=2 com janela fechada).

def _reopen_scheduler_patched(monkeypatch, scheduler, captured):
    class _Meta:
        def __init__(self, cfg): pass
        async def send_template(self, to, name, components=None, language_code="pt_BR"):
            return {"messages": [{"id": "wamid-body"}]}

    def _capture_save(**kw):
        captured.update(kw)

    monkeypatch.setattr(scheduler, "MetaCloudClient", _Meta)
    monkeypatch.setattr(scheduler, "_reopen_template_category", lambda: "utility")
    monkeypatch.setattr(scheduler, "save_message_conv", _capture_save)
    monkeypatch.setattr(scheduler, "_mark_awaiting_reopen", lambda jid: None)
    monkeypatch.setattr(scheduler, "_store_reopen_context", lambda *a: None)
    monkeypatch.setattr(scheduler, "extract_wamid", lambda r: "wamid-body")


@pytest.mark.asyncio
async def test_fire_reopen_template_persiste_o_corpo_real_do_template(monkeypatch):
    """O content persistido deve ser o BODY real do template (message_templates),
    nunca o placeholder interno."""
    from unittest.mock import MagicMock
    from app.follow_up import scheduler

    captured = {}
    _reopen_scheduler_patched(monkeypatch, scheduler, captured)

    corpo_real = "Ola, {{1}}! Aguardando sua confirmacao sobre {{2}} desde {{3}}."
    sb = MagicMock()
    (sb.table.return_value.select.return_value
        .eq.return_value.limit.return_value
        .execute.return_value) = MagicMock(
        data=[{"components": [{"type": "BODY", "text": corpo_real}]}]
    )
    monkeypatch.setattr(scheduler, "get_supabase", lambda: sb)

    lead = {"id": "lead-1", "name": "Tainara", "phone": "5511999999999"}
    job = {
        "id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1", "metadata": {},
        "conversations": {"last_customer_message_at": "2026-07-09T17:58:38+00:00"},
    }
    ok = await scheduler.fire_reopen_template(
        job, lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x",
    )
    assert ok is True
    assert captured["content"] == (
        "Ola, Tainara! Aguardando sua confirmacao sobre a continuidade do atendimento "
        "desde 09/07/2026."
    ), f"persistido != enviado (renderizado): {captured['content']!r}"


@pytest.mark.asyncio
async def test_fire_reopen_template_fallback_persiste_corpo_estatico_completo(monkeypatch):
    """message_templates indisponível → persiste a cópia fiel do corpo aprovado
    (o template é estático, ZERO params), jamais o fragmento-placeholder."""
    from app.follow_up import scheduler

    captured = {}
    _reopen_scheduler_patched(monkeypatch, scheduler, captured)

    def _boom():
        raise RuntimeError("db indisponível")

    monkeypatch.setattr(scheduler, "get_supabase", _boom)

    lead = {"id": "lead-1", "name": "Tainara", "phone": "5511999999999"}
    ok = await scheduler.fire_reopen_template(
        {"id": "job-1", "lead_id": "lead-1", "conversation_id": "conv-1", "metadata": {}},
        lead, {"provider_config": {}}, "conv-1", motivo="x", contexto="x",
    )
    assert ok is True
    content = captured["content"]
    assert content != "continuar a conversa de onde paramos"
    assert "{{" not in content, "placeholders devem estar renderizados"
    assert "aguardando sua confirmacao" in content
    assert "Tainara" in content
    # Rodada 5: o corpo NÃO pode mais ser o pedido de desculpas por atraso nosso
    assert "não consegui te responder" not in content
    assert "Peço desculpas" not in content
