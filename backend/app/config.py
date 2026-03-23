from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Meta WhatsApp
    meta_phone_number_id: str
    meta_access_token: str
    meta_verify_token: str = "valeria_webhook_verify"
    meta_app_secret: str = ""
    meta_api_version: str = "v21.0"

    # OpenAI
    openai_api_key: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App
    api_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    # Buffer
    buffer_base_timeout: int = 15
    buffer_extend_timeout: int = 10
    buffer_max_timeout: int = 45

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Lazy proxy so `from app.config import settings` works at import time
class _SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)


settings = _SettingsProxy()  # type: ignore
