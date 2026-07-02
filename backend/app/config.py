try:
    from pydantic_settings import BaseSettings
    PYDANTIC_V2 = True
except Exception:
    from pydantic import BaseSettings
    PYDANTIC_V2 = False

from typing import Optional
import os
from pathlib import Path


# Load .env.local first (if present) to override defaults for local development
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        k, v = line.split('=', 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # don't overwrite existing environment variables
        if k not in os.environ:
            os.environ[k] = v

# load local env then default .env
_load_env_file(Path(__file__).resolve().parent.parent / '.env.local')
_load_env_file(Path(__file__).resolve().parent.parent / '.env')


if PYDANTIC_V2:
    class Settings(BaseSettings):
        gemini_api_key: Optional[str] = None
        supabase_url: str = ""
        supabase_service_key: str = ""
        supabase_jwt_secret: str = ""
        redis_url: str = "redis://localhost:6379"
        api_base_url: str = "http://localhost:8000"
        frontend_url: str = "http://localhost:5173"
        dev_api_key: Optional[str] = None
        dev_server_url: Optional[str] = None
        buffer_base_timeout: int = 15
        buffer_extend_timeout: int = 5
        buffer_max_timeout: int = 60
        # Modelo Gemini usado para transcrição de áudio (via generateContent, NÃO
        # /audio/transcriptions — esse endpoint OpenAI-compat não existe no Gemini).
        transcription_model: str = "gemini-2.5-flash"
        rehearsal_mode: bool = False
        ai_phone_number_id: Optional[str] = None

        model_config = {
            "extra": "allow",
            "env_file": ".env",
            "env_file_encoding": "utf-8",
        }
        @property
        def ai_phone_number_ids(self) -> frozenset[str]:
            if not self.ai_phone_number_id:
                return frozenset()
            return frozenset(x.strip() for x in self.ai_phone_number_id.split(",") if x.strip())

        @property
        def is_dev_env(self) -> bool:
            return any(x in (self.api_base_url or "") for x in ("localhost", "127.0.0.1"))

else:
    class Settings(BaseSettings):
        gemini_api_key: Optional[str] = None
        supabase_url: str = ""
        supabase_service_key: str = ""
        supabase_jwt_secret: str = ""
        redis_url: str = "redis://localhost:6379"
        api_base_url: str = "http://localhost:8000"
        frontend_url: str = "http://localhost:5173"
        dev_api_key: Optional[str] = None
        dev_server_url: Optional[str] = None
        buffer_base_timeout: int = 15
        buffer_extend_timeout: int = 5
        buffer_max_timeout: int = 60
        # Modelo Gemini usado para transcrição de áudio (via generateContent, NÃO
        # /audio/transcriptions — esse endpoint OpenAI-compat não existe no Gemini).
        transcription_model: str = "gemini-2.5-flash"
        rehearsal_mode: bool = False
        ai_phone_number_id: Optional[str] = None

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "allow"
        @property
        def ai_phone_number_ids(self) -> frozenset[str]:
            if not self.ai_phone_number_id:
                return frozenset()
            return frozenset(x.strip() for x in self.ai_phone_number_id.split(",") if x.strip())

        @property
        def is_dev_env(self) -> bool:
            return any(x in (self.api_base_url or "") for x in ("localhost", "127.0.0.1"))


settings = Settings()


def get_settings() -> Settings:
    return settings
