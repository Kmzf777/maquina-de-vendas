def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    from app.config import Settings
    s = Settings()

    assert s.gemini_api_key == "test-gemini"
    assert s.buffer_base_timeout == 3
    assert s.buffer_max_timeout == 30


def test_gemini_api_key_configured():
    from app.config import Settings
    s = Settings(
        gemini_api_key="test-gemini",
        supabase_url="http://test",
        supabase_service_key="test",
    )
    assert s.gemini_api_key == "test-gemini"
