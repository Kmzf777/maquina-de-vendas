def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    from app.config import Settings
    s = Settings()

    assert s.gemini_api_key == "test-gemini"
    # Debounce de mensagens do lead: janela base 15s (estende +5s a cada nova
    # mensagem, ate o teto de 45s) para agrupar bursts e evitar surto de bolhas.
    # Cadencia real observada em prod: mediana ~43s entre mensagens, com pares
    # legitimos de 8-15s que a janela antiga (8s) fragmentava (ex.: lead 5549933008455).
    assert s.buffer_base_timeout == 15
    assert s.buffer_extend_timeout == 5
    assert s.buffer_max_timeout == 45


def test_gemini_api_key_configured():
    from app.config import Settings
    s = Settings(
        gemini_api_key="test-gemini",
        supabase_url="http://test",
        supabase_service_key="test",
    )
    assert s.gemini_api_key == "test-gemini"
