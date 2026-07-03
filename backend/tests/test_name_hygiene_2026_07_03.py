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


# ─── fire_reopen_template: mesma higiene (achado por grep, mesma família de bug) ────

@pytest.mark.asyncio
async def test_fire_reopen_template_nome_so_saudacao_usa_fallback(monkeypatch):
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
    assert captured["components"] == [{
        "type": "body",
        "parameters": [{"type": "text", "parameter_name": "primeiro_nome", "text": _NAME_FALLBACK}],
    }]
