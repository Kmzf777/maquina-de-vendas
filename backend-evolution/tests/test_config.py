def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("EVOLUTION_API_URL", "https://evo.test.com")
    monkeypatch.setenv("EVOLUTION_API_KEY", "test-key")
    monkeypatch.setenv("EVOLUTION_INSTANCE", "test-instance")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "key")

    import app.config
    app.config._settings = None

    from importlib import reload
    reload(app.config)
    s = app.config.Settings()

    assert s.evolution_api_url == "https://evo.test.com"
    assert s.evolution_api_key == "test-key"
    assert s.evolution_instance == "test-instance"
    assert s.buffer_base_timeout == 15
    assert s.buffer_max_timeout == 45
