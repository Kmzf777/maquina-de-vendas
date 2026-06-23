def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    from app.config import Settings
    s = Settings()

    assert s.gemini_api_key == "test-gemini"
    # Debounce de mensagens do lead: janela base 15s que RESETA a cada nova mensagem
    # (CA#2 — "espero o lead parar de digitar"), ate o teto absoluto de 60s para nao
    # travar o bot quando o lead metralha mensagens. buffer_extend_timeout ficou legado
    # (nao mais usado apos a mudanca de "extend +5s" para "reset ao base").
    assert s.buffer_base_timeout == 15
    assert s.buffer_max_timeout == 60


def test_gemini_api_key_configured():
    from app.config import Settings
    s = Settings(
        gemini_api_key="test-gemini",
        supabase_url="http://test",
        supabase_service_key="test",
    )
    assert s.gemini_api_key == "test-gemini"
