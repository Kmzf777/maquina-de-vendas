"""Pre-flight de template no broadcast (wartime T3, 10/07).

O /start validava billing e pendências, mas ZERO validação de template: nome
inexistente, locale divergente do aprovado (automacao_valeria_to_joao só existe
em `en` → pedir pt_BR dava 404) e contagem de params errada (reativacao_*: 5
aprovados vs 1 enviado → #132000) só explodiam NO MEIO da campanha, lead a lead.

Contratos fixados aqui (critério de aceite 1 da spec):
  - as 4 checagens (existência/aprovação, locale, params do BODY, header);
  - TODOS os erros retornados de uma vez, legíveis em PT-BR;
  - fail-closed quando o template não pode ser verificado (banco E Meta fora);
  - kill-switch PREFLIGHT_TEMPLATE=off pula o gate inteiro;
  - /start bloqueia com 400 e o status do broadcast fica INTOCADO.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.templates.preflight import validate_template_for_broadcast


# ─── helpers ──────────────────────────────────────────────────────────────────

def _sb_with_rows(rows):
    """Mock de Supabase: message_templates.select(...).eq(name).execute().data = rows."""
    sb = MagicMock()
    (
        sb.table.return_value.select.return_value
        .eq.return_value.execute.return_value.data
    ) = rows
    return sb


def _row(language="pt_BR", status="approved", body_text="Olá {{primeiro_nome}}, tudo bem?", header=None):
    components = []
    if header:
        components.append(header)
    components.append({"type": "BODY", "text": body_text})
    return {"name": "tpl_teste", "language": language, "status": status, "components": components}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def preflight_on(monkeypatch):
    """Liga o gate (a suíte roda com PREFLIGHT_TEMPLATE=off por hermeticidade)."""
    monkeypatch.setenv("PREFLIGHT_TEMPLATE", "on")


# ─── kill-switch ──────────────────────────────────────────────────────────────

def test_kill_switch_off_pula_o_gate_sem_tocar_o_banco(monkeypatch):
    """PREFLIGHT_TEMPLATE=off → [] imediato, sem lookup nenhum (reversão sem deploy)."""
    monkeypatch.setenv("PREFLIGHT_TEMPLATE", "off")
    boom = MagicMock(side_effect=AssertionError("não deveria tocar o banco"))
    with patch("app.templates.preflight.get_supabase", boom):
        errors = _run(validate_template_for_broadcast("qualquer", "pt_BR", {}, None))
    assert errors == []
    boom.assert_not_called()


# ─── checagem 1: existência/aprovação ─────────────────────────────────────────

def test_template_aprovado_com_params_corretos_passa(preflight_on):
    sb = _sb_with_rows([_row()])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast(
            "tpl_teste", "pt_BR", {"__params_type__": "named", "primeiro_nome": "{{primeiro_nome}}"}, None,
        ))
    assert errors == []


def test_template_inexistente_bloqueia(preflight_on):
    """Banco respondeu (template ausente) e Meta inacessível (sem canal) → bloqueado."""
    sb = _sb_with_rows([])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_fantasma", "pt_BR", {}, None))
    assert len(errors) == 1
    assert "tpl_fantasma" in errors[0]
    assert "não existe" in errors[0] or "não encontrado" in errors[0]


def test_template_existente_mas_nao_aprovado_bloqueia(preflight_on):
    sb = _sb_with_rows([_row(status="pending")])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", {}, None))
    assert len(errors) == 1
    assert "NÃO está aprovado" in errors[0]
    assert "pending" in errors[0]


def test_fail_closed_banco_e_meta_indisponiveis(preflight_on):
    """Sem NENHUMA fonte verificável, o disparo em massa às cegas é bloqueado."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.side_effect = RuntimeError("db down")
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", {}, None))
    assert len(errors) == 1
    assert "não foi possível verificar" in errors[0]
    assert "PREFLIGHT_TEMPLATE=off" in errors[0]  # escape hatch documentado no erro


# ─── checagem 2: locale ───────────────────────────────────────────────────────

def test_locale_divergente_cita_os_dois_valores(preflight_on):
    """Armadilha automacao_valeria_to_joao: aprovado só em `en`, broadcast pede pt_BR."""
    sb = _sb_with_rows([_row(language="en", body_text="Hello, how are you?")])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", {}, None))
    assert len(errors) == 1
    assert "pt_BR" in errors[0] and "en" in errors[0]


# ─── checagem 3: params do BODY ───────────────────────────────────────────────

def test_posicional_contagem_errada_bloqueia(preflight_on):
    """Armadilha reativacao_*: BODY aprovado pede 3 params, o disparo manda 1."""
    sb = _sb_with_rows([_row(body_text="Olá {{1}}, sou {{2}} da {{3}}.")])
    variables = {"__params_type__": "positional", "1": "{{primeiro_nome}}"}
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", variables, None))
    assert any("3 parâmetro" in e and "132000" in e for e in errors)


def test_params_type_incoerente_com_placeholders_bloqueia(preflight_on):
    """BODY posicional com __params_type__ named (default) → formato de envio errado."""
    sb = _sb_with_rows([_row(body_text="Olá {{1}}!")])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast(
            "tpl_teste", "pt_BR", {"1": "{{primeiro_nome}}"}, None,  # sem __params_type__ → named
        ))
    assert any("POSICIONAIS" in e and "__params_type__" in e for e in errors)


def test_nomeado_faltando_e_sobrando_reporta_ambos(preflight_on):
    sb = _sb_with_rows([_row(body_text="Olá {{primeiro_nome}}, aqui é {{vendedor}}.")])
    variables = {"__params_type__": "named", "primeiro_nome": "x", "empresa": "y"}
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", variables, None))
    assert any("vendedor" in e and "faltam" in e for e in errors)
    assert any("empresa" in e and "não existente" in e for e in errors)


def test_body_sem_placeholder_com_params_extras_bloqueia(preflight_on):
    """Armadilha continuar_conversa: BODY estático — enviar param dá Meta #132000."""
    sb = _sb_with_rows([_row(body_text="Podemos continuar nossa conversa?")])
    variables = {"__params_type__": "named", "primeiro_nome": "x"}
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", variables, None))
    assert len(errors) == 1
    assert "não tem placeholders" in errors[0]


# ─── checagem 4: header ───────────────────────────────────────────────────────

def test_header_de_midia_sem_url_bloqueia(preflight_on):
    sb = _sb_with_rows([_row(header={"type": "HEADER", "format": "IMAGE"})])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast(
            "tpl_teste", "pt_BR", {"__params_type__": "named", "primeiro_nome": "x"}, None,
        ))
    assert any("__header_url__" in e for e in errors)


def test_midia_fornecida_sem_header_no_template_bloqueia(preflight_on):
    sb = _sb_with_rows([_row()])
    variables = {
        "__params_type__": "named", "primeiro_nome": "x",
        "__header_type__": "IMAGE", "__header_url__": "https://ex.com/i.jpg",
    }
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast("tpl_teste", "pt_BR", variables, None))
    assert any("NÃO tem header" in e for e in errors)


# ─── todos os erros de uma vez ────────────────────────────────────────────────

def test_erros_multiplos_sao_todos_retornados(preflight_on):
    """Locale errado + params errados + header incoerente → o operador vê TUDO."""
    sb = _sb_with_rows([_row(
        language="en", body_text="Hi {{1}} from {{2}}",
        header={"type": "HEADER", "format": "IMAGE"},
    )])
    with patch("app.templates.preflight.get_supabase", return_value=sb):
        errors = _run(validate_template_for_broadcast(
            "tpl_teste", "pt_BR", {"__params_type__": "named", "nome": "x"}, None,
        ))
    assert len(errors) >= 3  # locale + params + header, numa passada só


# ─── fallback Meta API + auto-sync ────────────────────────────────────────────

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


class _FakeAsyncClient:
    def __init__(self, data):
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        return _FakeResp(self._data)


def test_fallback_meta_valida_e_faz_auto_sync(preflight_on):
    """Local vazio + Meta com aprovação em `en` → valida contra a Meta e semeia o banco."""
    sb = _sb_with_rows([])
    meta_data = [{
        "name": "tpl_teste", "language": "en", "status": "APPROVED",
        "category": "UTILITY", "id": "meta-123",
        "components": [{"type": "BODY", "text": "Hello {{primeiro_nome}}!"}],
    }]
    channel = {"id": "ch-1", "provider_config": {"waba_id": "waba", "access_token": "tok"}}
    with patch("app.templates.preflight.get_supabase", return_value=sb), \
         patch("app.templates.preflight.httpx.AsyncClient",
               lambda **kw: _FakeAsyncClient(meta_data)):
        errors = _run(validate_template_for_broadcast(
            "tpl_teste", "en", {"__params_type__": "named", "primeiro_nome": "x"}, channel,
        ))
    assert errors == []
    # auto-sync: o aprovado da Meta foi inserido em message_templates (best-effort)
    insert_payload = sb.table.return_value.insert.call_args[0][0]
    assert insert_payload["name"] == "tpl_teste"
    assert insert_payload["status"] == "approved"


# ─── integração com o /start ──────────────────────────────────────────────────

def _start_sb():
    """Supabase do router: sem billing aberto, broadcast draft, 3 leads pendentes."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "status": "draft", "template_name": "tpl_teste",
        "template_language_code": "pt_BR", "template_variables": {},
    }
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.count = 3
    return sb


def test_start_bloqueado_pelo_preflight_com_todos_os_erros_e_status_intocado(monkeypatch):
    import app.broadcast.router as router_mod

    sb = _start_sb()
    monkeypatch.setattr(
        router_mod, "validate_template_for_broadcast",
        AsyncMock(return_value=["erro A", "erro B"]),
    )
    with patch.object(router_mod, "get_supabase", return_value=sb):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(router_mod.start_broadcast("b-1"))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Disparo bloqueado pelo pre-flight: erro A; erro B"
    # status INTOCADO: nenhum update (o único update do /start é status=running)
    sb.table.return_value.update.assert_not_called()


def test_start_liberado_quando_preflight_passa(monkeypatch):
    import app.broadcast.router as router_mod

    sb = _start_sb()
    emitted = []
    monkeypatch.setattr(router_mod, "emit_event", lambda d, p=None: emitted.append(d))
    monkeypatch.setattr(
        router_mod, "validate_template_for_broadcast", AsyncMock(return_value=[]),
    )
    with patch.object(router_mod, "get_supabase", return_value=sb):
        result = asyncio.run(router_mod.start_broadcast("b-1"))

    assert result["status"] == "started"
    assert emitted == ["broadcasts"]
    update_payload = sb.table.return_value.update.call_args[0][0]
    assert update_payload == {"status": "running"}
