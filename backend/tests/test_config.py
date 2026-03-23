import os

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.setenv("META_VERIFY_TOKEN", "verify")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    from importlib import reload
    import app.config
    reload(app.config)
    s = app.config.Settings()

    assert s.meta_phone_number_id == "123"
    assert s.buffer_base_timeout == 15
    assert s.buffer_max_timeout == 45
