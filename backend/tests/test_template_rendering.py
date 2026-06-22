"""
Tests for template body rendering in the broadcast worker.

How _apply_variables works:
  template_variables maps BODY PARAMETER NAMES to VALUES (literal or token).
  Tokens like "{{primeiro_nome}}" in values are resolved via _LEAD_FIELD_TOKENS.

  Example:
    body = "Olá {{nome}}!"
    template_variables = {"nome": "{{primeiro_nome}}"}
    → replaces {{nome}} with _resolve_value("{{primeiro_nome}}", lead)
    → _resolve_value sees token "{{primeiro_nome}}" → returns lead["name"].split()[0]
    → "Olá Rafael!"

  Shorthand (key name matches token name):
    body = "Olá {{primeiro_nome}}!"
    template_variables = {"primeiro_nome": "{{primeiro_nome}}"}
    → same mechanism, key and value happen to share the same name

Uses the user's real number (5534988861441) for realistic assertions.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


REAL_LEAD = {
    "id": "lead-uuid-real",
    "phone": "5534988861441",
    "name": "Rafael Canastra",
    "company": "Canastra Inteligencia",
    "stage": "pending",
}


# ═══════════════════════════════════════════════════════════════
# _apply_variables — named token resolution
# ═══════════════════════════════════════════════════════════════

def test_apply_variables_primeiro_nome_via_token_value():
    """{{primeiro_nome}} in body resolved when template_variables maps it to the token."""
    from app.broadcast.worker import _apply_variables
    vars_ = {"primeiro_nome": "{{primeiro_nome}}"}
    result = _apply_variables("Olá {{primeiro_nome}}!", vars_, REAL_LEAD)
    assert result == "Olá Rafael!"


def test_apply_variables_nome_completo_via_token_value():
    from app.broadcast.worker import _apply_variables
    result = _apply_variables("Nome: {{nome_completo}}", {"nome_completo": "{{nome_completo}}"}, REAL_LEAD)
    assert result == "Nome: Rafael Canastra"


def test_apply_variables_telefone_via_token_value():
    from app.broadcast.worker import _apply_variables
    result = _apply_variables("WhatsApp: {{telefone}}", {"telefone": "{{telefone}}"}, REAL_LEAD)
    assert result == "WhatsApp: 5534988861441"


def test_apply_variables_empresa_via_token_value():
    from app.broadcast.worker import _apply_variables
    result = _apply_variables("Empresa: {{empresa}}", {"empresa": "{{empresa}}"}, REAL_LEAD)
    assert result == "Empresa: Canastra Inteligencia"


def test_apply_variables_first_name_english_token():
    from app.broadcast.worker import _apply_variables
    result = _apply_variables("Hi {{first_name}}!", {"first_name": "{{first_name}}"}, REAL_LEAD)
    assert result == "Hi Rafael!"


def test_apply_variables_phone_english_token():
    from app.broadcast.worker import _apply_variables
    result = _apply_variables("Contato: {{phone}}", {"phone": "{{phone}}"}, REAL_LEAD)
    assert result == "Contato: 5534988861441"


def test_apply_variables_indirection_different_key_name():
    """Template body uses {{nome}} but template_variables maps it to {{primeiro_nome}} token."""
    from app.broadcast.worker import _apply_variables
    vars_ = {"nome": "{{primeiro_nome}}"}
    result = _apply_variables("Olá {{nome}}!", vars_, REAL_LEAD)
    assert result == "Olá Rafael!"


def test_apply_variables_explicit_literal_value():
    """Non-token literal values in template_variables are used as-is."""
    from app.broadcast.worker import _apply_variables
    vars_ = {"produto": "Queijo Meia-Cura 500g"}
    result = _apply_variables("Oferta: {{produto}}", vars_, REAL_LEAD)
    assert result == "Oferta: Queijo Meia-Cura 500g"


def test_apply_variables_multiple_tokens_resolved():
    """All mapped tokens in the body are replaced in a single call."""
    from app.broadcast.worker import _apply_variables
    vars_ = {
        "primeiro_nome": "{{primeiro_nome}}",
        "telefone": "{{telefone}}",
        "empresa": "{{empresa}}",
    }
    body = "Olá {{primeiro_nome}}, o número {{telefone}} está cadastrado na {{empresa}}."
    result = _apply_variables(body, vars_, REAL_LEAD)
    assert result == "Olá Rafael, o número 5534988861441 está cadastrado na Canastra Inteligencia."


def test_apply_variables_empty_template_variables_leaves_body_unchanged():
    """With no template_variables, nothing is replaced — body returned verbatim."""
    from app.broadcast.worker import _apply_variables
    body = "Olá {{primeiro_nome}}, bem-vindo!"
    result = _apply_variables(body, {}, REAL_LEAD)
    assert result == body  # no substitution — tokens stay as-is


def test_apply_variables_lead_with_only_first_name():
    """Lead with single-word name: primeiro_nome == nome_completo."""
    from app.broadcast.worker import _apply_variables
    lead = {**REAL_LEAD, "name": "Rafael"}
    v1 = _apply_variables("{{primeiro_nome}}", {"primeiro_nome": "{{primeiro_nome}}"}, lead)
    v2 = _apply_variables("{{nome_completo}}", {"nome_completo": "{{nome_completo}}"}, lead)
    assert v1 == "Rafael"
    assert v2 == "Rafael"


def test_apply_variables_lead_with_no_name_falls_back_to_voce():
    """Sem nome (ou handle), tokens de nome caem em "você" — evita "Olá !"/param vazio
    (que o Meta pode rejeitar) e mantém a leitura natural (auditoria 2026-06-22, Falha 10)."""
    from app.broadcast.worker import _apply_variables
    lead = {**REAL_LEAD, "name": None}
    result = _apply_variables("Olá {{primeiro_nome}}!", {"primeiro_nome": "{{primeiro_nome}}"}, lead)
    assert result == "Olá você!"


def test_apply_variables_lead_with_handle_name_falls_back_to_voce():
    """push_name handle (com dígito/underscore) não vira nome próprio no template."""
    from app.broadcast.worker import _apply_variables
    lead = {**REAL_LEAD, "name": "Brunor_barista"}
    result = _apply_variables("Falo com {{primeiro_nome}} neste número?", {"primeiro_nome": "{{primeiro_nome}}"}, lead)
    assert result == "Falo com você neste número?"


# ═══════════════════════════════════════════════════════════════
# _render_template_body — local DB path (fast path)
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_render_template_body_local_db_resolves_tokens_via_template_variables():
    """Template found in local DB with token-mapped variables → body rendered with lead data."""
    from app.broadcast.worker import _render_template_body

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"components": [{"type": "BODY", "text": "Olá {{primeiro_nome}}, temos uma oferta especial!"}]}
    ]

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        result = await _render_template_body(
            "mkt_oferta_especial",
            {"primeiro_nome": "{{primeiro_nome}}"},
            REAL_LEAD,
        )

    assert result == "Olá Rafael, temos uma oferta especial!"


@pytest.mark.asyncio
async def test_render_template_body_local_db_static_template_no_variables():
    """Static template (no variables) returns body text unchanged."""
    from app.broadcast.worker import _render_template_body

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"components": [{"type": "BODY", "text": "Confira nosso catálogo em canastra.com.br!"}]}
    ]

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        result = await _render_template_body("mkt_catalogo", {}, REAL_LEAD)

    assert result == "Confira nosso catálogo em canastra.com.br!"


# ═══════════════════════════════════════════════════════════════
# _render_template_body — Meta API fallback path
# ═══════════════════════════════════════════════════════════════

def _meta_channel():
    return {
        "id": "ch-uuid",
        "provider_config": {
            "waba_id": "waba-test-123",
            "access_token": "Bearer-test-token",
        },
    }


def _meta_resp_with_body(body_text: str):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [{
            "id": "tpl-meta-id-999",
            "language": "pt_BR",
            "category": "MARKETING",
            "components": [
                {"type": "BODY", "text": body_text},
            ],
        }]
    }
    return mock_resp


def _httpx_client_mock(resp):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_cls = MagicMock()
    mock_cls.return_value = mock_client
    return mock_cls


@pytest.mark.asyncio
async def test_render_template_body_meta_api_fallback_resolves_tokens():
    """Template not in local DB: fetches from Meta API and renders with lead data."""
    from app.broadcast.worker import _render_template_body

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock()

    resp = _meta_resp_with_body("Olá {{primeiro_nome}}, bem-vindo à Canastra!")
    http_cls = _httpx_client_mock(resp)

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.worker.httpx.AsyncClient", http_cls):
        result = await _render_template_body(
            "mkt_boas_vindas",
            {"primeiro_nome": "{{primeiro_nome}}"},
            REAL_LEAD,
            _meta_channel(),
        )

    assert result == "Olá Rafael, bem-vindo à Canastra!"


@pytest.mark.asyncio
async def test_render_template_body_meta_api_fallback_auto_syncs_to_local_db():
    """After fetching from Meta API, template components must be inserted into local DB."""
    from app.broadcast.worker import _render_template_body

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock()

    resp = _meta_resp_with_body("Conheça nossos queijos artesanais!")
    http_cls = _httpx_client_mock(resp)

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb), \
         patch("app.broadcast.worker.httpx.AsyncClient", http_cls):
        await _render_template_body("mkt_queijos", {}, REAL_LEAD, _meta_channel())

    mock_sb.table.return_value.insert.assert_called_once()
    payload = mock_sb.table.return_value.insert.call_args[0][0]
    assert payload["name"] == "mkt_queijos"
    assert payload["channel_id"] == "ch-uuid"


@pytest.mark.asyncio
async def test_render_template_body_returns_placeholder_when_db_and_meta_both_fail():
    """If local DB and Meta API both fail, returns [Template: name] placeholder."""
    from app.broadcast.worker import _render_template_body

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.side_effect = Exception("DB offline")

    result = await _render_template_body("mkt_template_xyz", {}, REAL_LEAD)
    assert result == "[Template: mkt_template_xyz]"


@pytest.mark.asyncio
async def test_render_template_body_returns_placeholder_when_no_channel_for_meta_fallback():
    """Without a channel (no credentials), Meta API fallback cannot fire."""
    from app.broadcast.worker import _render_template_body

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    with patch("app.broadcast.worker.get_supabase", return_value=mock_sb):
        result = await _render_template_body("mkt_sem_canal", {}, REAL_LEAD, channel=None)

    assert result == "[Template: mkt_sem_canal]"
