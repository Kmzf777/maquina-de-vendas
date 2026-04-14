from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Evolution API (optional — per-channel config used instead)
    evolution_api_url: str = ""
    evolution_api_key: str = ""
    evolution_instance: str = ""

    # Gemini (via OpenAI-compatible API)
    gemini_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"

    # Buffer
    buffer_base_timeout: int = 15
    buffer_extend_timeout: int = 10
    buffer_max_timeout: int = 45

    # Meta Cloud API — used by outbound dispatcher
    meta_access_token: str = ""
    meta_phone_number_id: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()  # type: ignore
