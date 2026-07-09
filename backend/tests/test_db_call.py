"""db_call: retry de transporte unificado + execução fora do event loop."""
import threading
from unittest.mock import patch

import httpx
import pytest

from app.db.supabase import db_call


async def test_db_call_roda_fora_da_thread_do_loop():
    loop_thread = threading.get_ident()
    seen = {}

    def q():
        seen["thread"] = threading.get_ident()
        return 42

    assert await db_call(q) == 42
    assert seen["thread"] != loop_thread


async def test_db_call_retenta_transport_error():
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 2:
            raise httpx.RemoteProtocolError("GOAWAY")
        return "ok"

    with patch("app.db.supabase.time.sleep"):
        assert await db_call(flaky, label="test") == "ok"
    assert len(attempts) == 2


async def test_db_call_nao_retenta_erro_de_aplicacao():
    attempts = []

    def bad():
        attempts.append(1)
        raise ValueError("erro de aplicação")

    with pytest.raises(ValueError):
        await db_call(bad)
    assert len(attempts) == 1
