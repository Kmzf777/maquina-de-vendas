import os
import pytest

# Set required env vars before any app imports trigger Settings validation
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")


@pytest.fixture
def anyio_backend():
    return "asyncio"
