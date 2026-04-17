# Webhook Dev Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Intercept incoming webhooks at the production FastAPI and forward them to a dev `uvicorn` server (port 8001) for numbers in a Redis whitelist, skipping production processing for those numbers.

**Architecture:** A new `app/dev_router/` module handles whitelist management (Redis Set `dev:phone_whitelist`) and HTTP forwarding (`httpx` fire-and-forget). Both webhook routers (`webhook/router.py` for Evolution and `webhook/meta_router.py` for Meta) check the whitelist per message and, if matched, dispatch a `BackgroundTask` to forward the raw payload bytes to `http://172.17.0.1:8001` then skip all local processing.

**Tech Stack:** FastAPI `BackgroundTasks`, `httpx.AsyncClient`, Redis Set operations, `respx` for mocking in tests.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/tests/conftest.py` | Add Set operations to `FakeRedis` |
| Modify | `backend/app/config.py` | Add `dev_server_url` and `dev_api_key` fields |
| Create | `backend/app/dev_router/__init__.py` | Empty module marker |
| Create | `backend/app/dev_router/service.py` | Whitelist CRUD on Redis Set |
| Create | `backend/app/dev_router/forwarder.py` | Async HTTP forward via httpx |
| Create | `backend/app/dev_router/router.py` | `/api/dev/whitelist` REST endpoints |
| Create | `backend/tests/test_dev_router_service.py` | Unit tests for whitelist service |
| Create | `backend/tests/test_dev_router_forwarder.py` | Unit tests for forwarder |
| Modify | `backend/app/main.py` | Register `dev_router` |
| Modify | `backend/app/webhook/router.py` | Intercept Evolution webhooks |
| Modify | `backend/app/webhook/meta_router.py` | Intercept Meta webhooks |
| Create | `backend/tests/test_webhook_dev_routing.py` | Integration tests for interception |
| Modify | `.vscode/tasks.json` | Change backend dev port to 8001 |

---

## Task 1: Extend FakeRedis + Add Config Fields

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add Set operations to `FakeRedis` in `conftest.py`**

  Open `backend/tests/conftest.py`. Add `_sets: dict = {}` to `__init__` and append these methods to the `FakeRedis` class (after the `exists` method):

  ```python
  def __init__(self):
      self._lists: dict = {}
      self._sorted: dict = {}
      self._strings: dict = {}
      self._sets: dict = {}
  ```

  Then add after the existing `exists` method:

  ```python
  async def sadd(self, key, *values):
      self._sets.setdefault(key, set()).update(values)
      return len(values)

  async def sismember(self, key, value):
      return value in self._sets.get(key, set())

  async def smembers(self, key):
      return set(self._sets.get(key, set()))

  async def srem(self, key, *values):
      s = self._sets.get(key, set())
      removed = sum(1 for v in values if v in s)
      s -= set(values)
      if s:
          self._sets[key] = s
      else:
          self._sets.pop(key, None)
      return removed
  ```

  Also update `delete` to handle sets:
  ```python
  async def delete(self, *keys):
      for k in keys:
          self._lists.pop(k, None)
          self._sorted.pop(k, None)
          self._strings.pop(k, None)
          self._sets.pop(k, None)
  ```

- [ ] **Step 2: Add `dev_server_url` and `dev_api_key` to `config.py`**

  Open `backend/app/config.py`. Add these two fields inside the `Settings` class, after the `meta_phone_number_id` field:

  ```python
  # Dev routing
  dev_server_url: str = "http://172.17.0.1:8001"
  dev_api_key: str = ""
  ```

- [ ] **Step 3: Run existing tests to confirm no regressions**

  ```bash
  cd backend && python -m pytest tests/ -x -q
  ```
  Expected: all existing tests pass.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/tests/conftest.py backend/app/config.py
  git commit -m "feat(dev-router): add FakeRedis set ops and config fields"
  ```

---

## Task 2: Create `dev_router/service.py`

**Files:**
- Create: `backend/app/dev_router/__init__.py`
- Create: `backend/app/dev_router/service.py`
- Create: `backend/tests/test_dev_router_service.py`

- [ ] **Step 1: Write the failing tests**

  Create `backend/tests/test_dev_router_service.py`:

  ```python
  import pytest
  from app.dev_router.service import (
      is_dev_number,
      add_dev_number,
      remove_dev_number,
      list_dev_numbers,
  )


  @pytest.mark.anyio
  async def test_unknown_number_returns_false(fake_redis):
      assert await is_dev_number(fake_redis, "5511000000000") is False


  @pytest.mark.anyio
  async def test_add_and_check_number(fake_redis):
      await add_dev_number(fake_redis, "5511999999999")
      assert await is_dev_number(fake_redis, "5511999999999") is True


  @pytest.mark.anyio
  async def test_normalize_strips_plus(fake_redis):
      await add_dev_number(fake_redis, "+5511999999999")
      assert await is_dev_number(fake_redis, "5511999999999") is True


  @pytest.mark.anyio
  async def test_normalize_strips_spaces_and_hyphens(fake_redis):
      await add_dev_number(fake_redis, "55 11 99999-9999")
      # stored as "5511999999999"; lookup also normalizes, so both forms resolve
      assert await is_dev_number(fake_redis, "5511999999999") is True
      assert await is_dev_number(fake_redis, "55 11 99999-9999") is True


  @pytest.mark.anyio
  async def test_remove_number(fake_redis):
      await add_dev_number(fake_redis, "5511999999999")
      await remove_dev_number(fake_redis, "5511999999999")
      assert await is_dev_number(fake_redis, "5511999999999") is False


  @pytest.mark.anyio
  async def test_list_numbers(fake_redis):
      await add_dev_number(fake_redis, "5511111111111")
      await add_dev_number(fake_redis, "5511222222222")
      numbers = await list_dev_numbers(fake_redis)
      assert "5511111111111" in numbers
      assert "5511222222222" in numbers


  @pytest.mark.anyio
  async def test_list_empty(fake_redis):
      numbers = await list_dev_numbers(fake_redis)
      assert numbers == []
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```bash
  cd backend && python -m pytest tests/test_dev_router_service.py -v
  ```
  Expected: `ModuleNotFoundError: No module named 'app.dev_router'`

- [ ] **Step 3: Create `backend/app/dev_router/__init__.py`** (empty)

  ```bash
  touch backend/app/dev_router/__init__.py
  ```

- [ ] **Step 4: Create `backend/app/dev_router/service.py`**

  ```python
  import re

  DEV_WHITELIST_KEY = "dev:phone_whitelist"


  def _normalize(phone: str) -> str:
      return re.sub(r"[\s+\-]", "", phone)


  async def is_dev_number(redis, phone: str) -> bool:
      return bool(await redis.sismember(DEV_WHITELIST_KEY, _normalize(phone)))


  async def add_dev_number(redis, phone: str) -> str:
      normalized = _normalize(phone)
      await redis.sadd(DEV_WHITELIST_KEY, normalized)
      return normalized


  async def remove_dev_number(redis, phone: str) -> str:
      normalized = _normalize(phone)
      await redis.srem(DEV_WHITELIST_KEY, normalized)
      return normalized


  async def list_dev_numbers(redis) -> list[str]:
      members = await redis.smembers(DEV_WHITELIST_KEY)
      return sorted(members)
  ```

- [ ] **Step 5: Run tests to confirm they pass**

  ```bash
  cd backend && python -m pytest tests/test_dev_router_service.py -v
  ```
  Expected: 7 tests PASS.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/app/dev_router/__init__.py backend/app/dev_router/service.py backend/tests/test_dev_router_service.py
  git commit -m "feat(dev-router): add whitelist service with Redis Set"
  ```

---

## Task 3: Create `dev_router/forwarder.py`

**Files:**
- Create: `backend/app/dev_router/forwarder.py`
- Create: `backend/tests/test_dev_router_forwarder.py`

- [ ] **Step 1: Write the failing tests**

  Create `backend/tests/test_dev_router_forwarder.py`:

  ```python
  import pytest
  import respx
  import httpx
  from app.dev_router.forwarder import forward_to_dev


  @pytest.mark.anyio
  @respx.mock
  async def test_forward_posts_to_dev_url():
      route = respx.post("http://172.17.0.1:8001/webhook/evolution").mock(
          return_value=httpx.Response(200, json={"status": "ok"})
      )
      await forward_to_dev(
          dev_url="http://172.17.0.1:8001",
          path="/webhook/evolution",
          headers={"content-type": "application/json"},
          body=b'{"event":"messages.upsert"}',
      )
      assert route.called
      assert route.calls[0].request.content == b'{"event":"messages.upsert"}'


  @pytest.mark.anyio
  @respx.mock
  async def test_forward_passes_signature_header():
      route = respx.post("http://172.17.0.1:8001/webhook/meta").mock(
          return_value=httpx.Response(200)
      )
      await forward_to_dev(
          dev_url="http://172.17.0.1:8001",
          path="/webhook/meta",
          headers={
              "content-type": "application/json",
              "x-hub-signature-256": "sha256=abc123",
              "host": "api.canastrainteligencia.com",
          },
          body=b"{}",
      )
      sent_headers = route.calls[0].request.headers
      assert sent_headers["x-hub-signature-256"] == "sha256=abc123"
      assert "host" not in sent_headers  # host is not forwarded


  @pytest.mark.anyio
  @respx.mock
  async def test_forward_swallows_connection_error():
      respx.post("http://172.17.0.1:8001/webhook/evolution").mock(
          side_effect=httpx.ConnectError("refused")
      )
      # Must not raise
      await forward_to_dev(
          dev_url="http://172.17.0.1:8001",
          path="/webhook/evolution",
          headers={},
          body=b"{}",
      )


  @pytest.mark.anyio
  @respx.mock
  async def test_forward_swallows_timeout():
      respx.post("http://172.17.0.1:8001/webhook/evolution").mock(
          side_effect=httpx.TimeoutException("timeout")
      )
      await forward_to_dev(
          dev_url="http://172.17.0.1:8001",
          path="/webhook/evolution",
          headers={},
          body=b"{}",
      )
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```bash
  cd backend && python -m pytest tests/test_dev_router_forwarder.py -v
  ```
  Expected: `ImportError: cannot import name 'forward_to_dev'`

- [ ] **Step 3: Create `backend/app/dev_router/forwarder.py`**

  ```python
  import logging

  import httpx

  logger = logging.getLogger(__name__)

  _FORWARD_HEADERS = {"content-type", "x-hub-signature-256"}


  async def forward_to_dev(dev_url: str, path: str, headers: dict, body: bytes) -> None:
      filtered = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
      try:
          async with httpx.AsyncClient(
              timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
          ) as client:
              response = await client.post(f"{dev_url}{path}", content=body, headers=filtered)
              logger.info(f"Dev forward {path} → {response.status_code}")
      except Exception as e:
          logger.warning(f"Dev forward failed for {path}: {e}")
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```bash
  cd backend && python -m pytest tests/test_dev_router_forwarder.py -v
  ```
  Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/dev_router/forwarder.py backend/tests/test_dev_router_forwarder.py
  git commit -m "feat(dev-router): add httpx forwarder with error swallowing"
  ```

---

## Task 4: Create `dev_router/router.py` + Register in `main.py`

**Files:**
- Create: `backend/app/dev_router/router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `backend/app/dev_router/router.py`**

  ```python
  import logging
  from typing import Annotated

  from fastapi import APIRouter, Header, Request, Response

  from app.config import settings
  from app.dev_router.service import add_dev_number, list_dev_numbers, remove_dev_number

  logger = logging.getLogger(__name__)
  router = APIRouter()


  def _auth(x_dev_key: str | None) -> Response | None:
      if not settings.dev_api_key:
          return Response(status_code=503)
      if x_dev_key != settings.dev_api_key:
          return Response(status_code=401)
      return None


  @router.get("/api/dev/whitelist")
  async def get_whitelist(
      request: Request,
      x_dev_key: Annotated[str | None, Header()] = None,
  ):
      if err := _auth(x_dev_key):
          return err
      numbers = await list_dev_numbers(request.app.state.redis)
      return {"numbers": numbers}


  @router.post("/api/dev/whitelist/{phone}")
  async def add_to_whitelist(
      phone: str,
      request: Request,
      x_dev_key: Annotated[str | None, Header()] = None,
  ):
      if err := _auth(x_dev_key):
          return err
      normalized = await add_dev_number(request.app.state.redis, phone)
      logger.info(f"Dev whitelist: added {normalized}")
      return {"added": normalized}


  @router.delete("/api/dev/whitelist/{phone}")
  async def remove_from_whitelist(
      phone: str,
      request: Request,
      x_dev_key: Annotated[str | None, Header()] = None,
  ):
      if err := _auth(x_dev_key):
          return err
      normalized = await remove_dev_number(request.app.state.redis, phone)
      logger.info(f"Dev whitelist: removed {normalized}")
      return {"removed": normalized}
  ```

- [ ] **Step 2: Register `dev_router` in `backend/app/main.py`**

  Add after the existing router imports (around line 60):

  ```python
  from app.dev_router.router import router as dev_router
  ```

  Add after the existing `app.include_router(agent_profiles_router)` line:

  ```python
  app.include_router(dev_router)
  ```

- [ ] **Step 3: Run all tests to confirm no regressions**

  ```bash
  cd backend && python -m pytest tests/ -x -q
  ```
  Expected: all tests pass.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/dev_router/router.py backend/app/main.py
  git commit -m "feat(dev-router): add whitelist REST endpoints and register router"
  ```

---

## Task 5: Intercept Evolution Webhook

**Files:**
- Modify: `backend/app/webhook/router.py`
- Create: `backend/tests/test_webhook_dev_routing.py`

- [ ] **Step 1: Write failing tests**

  Create `backend/tests/test_webhook_dev_routing.py`:

  ```python
  import json
  import pytest
  from unittest.mock import AsyncMock, patch, MagicMock
  from fastapi import FastAPI
  from fastapi.testclient import TestClient

  from app.webhook.router import router as evo_router

  EVOLUTION_PAYLOAD = {
      "event": "messages.upsert",
      "instance": {"instanceName": "test-instance"},
      "data": {
          "key": {
              "remoteJid": "5511999999999@s.whatsapp.net",
              "fromMe": False,
              "id": "msg123",
          },
          "pushName": "Dev Tester",
          "message": {"conversation": "oi"},
          "messageType": "conversation",
          "messageTimestamp": 1764253714,
      },
  }

  FAKE_CHANNEL = {
      "id": "ch-test",
      "is_active": True,
      "provider": "evolution",
      "provider_config": {"instance": "test-instance"},
  }


  @pytest.fixture
  def evo_client(fake_redis):
      app = FastAPI()
      app.include_router(evo_router)
      app.state.redis = fake_redis
      return TestClient(app, raise_server_exceptions=True)


  def test_evolution_dev_number_skips_buffer_and_forwards(evo_client, fake_redis):
      """Dev-whitelisted sender: forward called, push_to_buffer not called."""
      with patch("app.webhook.router.get_channel_by_provider_config", return_value=FAKE_CHANNEL), \
           patch("app.webhook.router.get_provider") as mock_provider, \
           patch("app.webhook.router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
           patch("app.webhook.router.is_dev_number", new_callable=AsyncMock, return_value=True), \
           patch("app.webhook.router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

          mock_provider.return_value.mark_read = AsyncMock()

          response = evo_client.post(
              "/webhook/evolution",
              content=json.dumps(EVOLUTION_PAYLOAD),
              headers={"content-type": "application/json"},
          )

          assert response.status_code == 200
          assert response.json() == {"status": "ok"}
          mock_push.assert_not_called()
          mock_forward.assert_called_once()
          call_kwargs = mock_forward.call_args
          assert call_kwargs.kwargs["path"] == "/webhook/evolution"


  def test_evolution_non_dev_number_processes_normally(evo_client, fake_redis):
      """Non-whitelisted sender: push_to_buffer called, forward not called."""
      with patch("app.webhook.router.get_channel_by_provider_config", return_value=FAKE_CHANNEL), \
           patch("app.webhook.router.get_provider") as mock_provider, \
           patch("app.webhook.router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
           patch("app.webhook.router.is_dev_number", new_callable=AsyncMock, return_value=False), \
           patch("app.webhook.router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

          mock_provider.return_value.mark_read = AsyncMock()

          response = evo_client.post(
              "/webhook/evolution",
              content=json.dumps(EVOLUTION_PAYLOAD),
              headers={"content-type": "application/json"},
          )

          assert response.status_code == 200
          mock_push.assert_called_once()
          mock_forward.assert_not_called()
  ```

- [ ] **Step 2: Run tests to confirm they fail**

  ```bash
  cd backend && python -m pytest tests/test_webhook_dev_routing.py -v
  ```
  Expected: FAIL — `is_dev_number` and `forward_to_dev` are not yet imported in `webhook/router.py`.

- [ ] **Step 3: Update `backend/app/webhook/router.py`**

  Replace the entire file with:

  ```python
  import json
  import logging

  from fastapi import APIRouter, BackgroundTasks, Request

  from app.webhook.parser import parse_webhook_payload
  from app.whatsapp.registry import get_provider
  from app.buffer.manager import push_to_buffer
  from app.leads.service import get_or_create_lead, reset_lead
  from app.channels.service import get_channel_by_provider_config
  from app.dev_router.service import is_dev_number
  from app.dev_router.forwarder import forward_to_dev
  from app.config import settings

  logger = logging.getLogger(__name__)

  router = APIRouter()


  def _find_evolution_channel(payload: dict) -> dict | None:
      instance_name = ""
      instance_data = payload.get("instance")
      if isinstance(instance_data, dict):
          instance_name = instance_data.get("instanceName", "")
      elif isinstance(instance_data, str):
          instance_name = instance_data

      if not instance_name:
          instance_name = payload.get("instanceName", "")

      if instance_name:
          channel = get_channel_by_provider_config("instance", instance_name, "evolution")
          if channel:
              return channel

      logger.warning(f"No Evolution channel found for instance={instance_name}")
      return None


  @router.post("/webhook/evolution")
  async def receive_evolution_webhook(request: Request, background_tasks: BackgroundTasks):
      payload_bytes = await request.body()
      payload = json.loads(payload_bytes)
      logger.info(f"Evolution webhook event: {payload.get('event', 'unknown')}")

      channel = _find_evolution_channel(payload)
      if not channel:
          return {"status": "ok"}

      if not channel.get("is_active"):
          logger.info(f"Channel {channel['id']} is inactive, skipping")
          return {"status": "ok"}

      messages = parse_webhook_payload(payload)
      redis = request.app.state.redis

      for msg in messages:
          logger.info(f"Message from {msg.from_number} ({msg.push_name}): type={msg.type}")
          msg.channel_id = channel["id"]

          if await is_dev_number(redis, msg.from_number):
              logger.info(f"Dev routing: forwarding {msg.from_number} to {settings.dev_server_url}")
              background_tasks.add_task(
                  forward_to_dev,
                  dev_url=settings.dev_server_url,
                  path="/webhook/evolution",
                  headers=dict(request.headers),
                  body=payload_bytes,
              )
              continue

          try:
              provider = get_provider(channel)
              await provider.mark_read(msg.message_id, msg.remote_jid)
          except Exception as e:
              logger.warning(f"Failed to mark read: {e}")

          if msg.text and msg.text.strip().lower() == "!resetar":
              try:
                  lead = get_or_create_lead(msg.from_number)
                  reset_lead(lead["id"])
                  provider = get_provider(channel)
                  await provider.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
              except Exception as e:
                  logger.error(f"Failed to reset lead: {e}", exc_info=True)
              continue

          await push_to_buffer(redis, msg)

      return {"status": "ok"}


  @router.post("/webhook")
  async def receive_webhook_legacy(request: Request, background_tasks: BackgroundTasks):
      return await receive_evolution_webhook(request, background_tasks)
  ```

- [ ] **Step 4: Run tests to confirm they pass**

  ```bash
  cd backend && python -m pytest tests/test_webhook_dev_routing.py tests/test_webhook_parser.py -v
  ```
  Expected: all tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/webhook/router.py backend/tests/test_webhook_dev_routing.py
  git commit -m "feat(dev-router): intercept Evolution webhook for dev-whitelisted numbers"
  ```

---

## Task 6: Intercept Meta Webhook

**Files:**
- Modify: `backend/app/webhook/meta_router.py`
- Modify: `backend/tests/test_webhook_dev_routing.py`

- [ ] **Step 1: Add Meta interception test to `test_webhook_dev_routing.py`**

  Append to `backend/tests/test_webhook_dev_routing.py`:

  ```python
  from app.webhook.meta_router import router as meta_router

  META_PAYLOAD = {
      "object": "whatsapp_business_account",
      "entry": [
          {
              "id": "WABA_ID",
              "changes": [
                  {
                      "value": {
                          "messaging_product": "whatsapp",
                          "metadata": {"phone_number_id": "PHONE_ID"},
                          "messages": [
                              {
                                  "from": "5511999999999",
                                  "id": "msg-meta-001",
                                  "timestamp": "1764253714",
                                  "type": "text",
                                  "text": {"body": "ola pelo meta"},
                              }
                          ],
                      },
                      "field": "messages",
                  }
              ],
          }
      ],
  }

  FAKE_META_CHANNEL = {
      "id": "ch-meta-test",
      "is_active": True,
      "provider": "meta_cloud",
      "provider_config": {"phone_number_id": "PHONE_ID", "app_secret": ""},
  }


  @pytest.fixture
  def meta_client(fake_redis):
      app = FastAPI()
      app.include_router(meta_router)
      app.state.redis = fake_redis
      return TestClient(app, raise_server_exceptions=True)


  def test_meta_dev_number_skips_buffer_and_forwards(meta_client):
      with patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL), \
           patch("app.webhook.meta_router.get_provider") as mock_provider, \
           patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
           patch("app.webhook.meta_router.is_dev_number", new_callable=AsyncMock, return_value=True), \
           patch("app.webhook.meta_router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

          mock_provider.return_value.mark_read = AsyncMock()

          response = meta_client.post(
              "/webhook/meta",
              content=json.dumps(META_PAYLOAD),
              headers={"content-type": "application/json"},
          )

          assert response.status_code == 200
          mock_push.assert_not_called()
          mock_forward.assert_called_once()
          assert mock_forward.call_args.kwargs["path"] == "/webhook/meta"


  def test_meta_non_dev_number_processes_normally(meta_client):
      with patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL), \
           patch("app.webhook.meta_router.get_provider") as mock_provider, \
           patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock) as mock_push, \
           patch("app.webhook.meta_router.is_dev_number", new_callable=AsyncMock, return_value=False), \
           patch("app.webhook.meta_router.forward_to_dev", new_callable=AsyncMock) as mock_forward:

          mock_provider.return_value.mark_read = AsyncMock()

          response = meta_client.post(
              "/webhook/meta",
              content=json.dumps(META_PAYLOAD),
              headers={"content-type": "application/json"},
          )

          assert response.status_code == 200
          mock_push.assert_called_once()
          mock_forward.assert_not_called()
  ```

- [ ] **Step 2: Run new tests to confirm they fail**

  ```bash
  cd backend && python -m pytest tests/test_webhook_dev_routing.py::test_meta_dev_number_skips_buffer_and_forwards -v
  ```
  Expected: FAIL — `is_dev_number` not yet imported in `meta_router.py`.

- [ ] **Step 3: Update `backend/app/webhook/meta_router.py`**

  Replace the entire file with:

  ```python
  import hashlib
  import hmac
  import json
  import logging

  from fastapi import APIRouter, BackgroundTasks, Request, Response

  from app.webhook.meta_parser import parse_meta_webhook_payload, extract_phone_number_id
  from app.whatsapp.registry import get_provider
  from app.buffer.manager import push_to_buffer
  from app.leads.service import get_or_create_lead, reset_lead
  from app.channels.service import get_channel_by_provider_config
  from app.dev_router.service import is_dev_number
  from app.dev_router.forwarder import forward_to_dev
  from app.config import settings

  logger = logging.getLogger(__name__)

  router = APIRouter()


  def _verify_signature(payload_bytes: bytes, signature_header: str, app_secret: str) -> bool:
      if not signature_header or not signature_header.startswith("sha256="):
          return False
      expected = signature_header[7:]
      computed = hmac.new(app_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
      return hmac.compare_digest(computed, expected)


  @router.get("/webhook/meta")
  async def verify_meta_webhook(request: Request):
      params = request.query_params
      mode = params.get("hub.mode")
      token = params.get("hub.verify_token")
      challenge = params.get("hub.challenge")

      if mode != "subscribe" or not token or not challenge:
          return Response(status_code=403)

      channel = get_channel_by_provider_config("verify_token", token, "meta_cloud")
      if not channel:
          logger.warning(f"Meta verify: no channel found with verify_token={token}")
          return Response(status_code=403)

      logger.info(f"Meta webhook verified for channel {channel['id']}")
      return Response(content=challenge, media_type="text/plain")


  @router.post("/webhook/meta")
  async def receive_meta_webhook(request: Request, background_tasks: BackgroundTasks):
      payload_bytes = await request.body()
      payload = json.loads(payload_bytes)

      phone_number_id = extract_phone_number_id(payload)
      if not phone_number_id:
          logger.warning("Meta webhook: no phone_number_id found in payload")
          return {"status": "ok"}

      channel = get_channel_by_provider_config("phone_number_id", phone_number_id, "meta_cloud")
      if not channel:
          logger.warning(f"No active Meta channel for phone_number_id={phone_number_id}")
          return {"status": "ok"}

      if not channel.get("is_active"):
          logger.info(f"Channel {channel['id']} is inactive, skipping")
          return {"status": "ok"}

      signature = request.headers.get("x-hub-signature-256", "")
      app_secret = channel.get("provider_config", {}).get("app_secret", "")
      if app_secret and not _verify_signature(payload_bytes, signature, app_secret):
          logger.warning(f"Meta webhook: invalid signature for channel {channel['id']}")
          return Response(status_code=403)

      messages = parse_meta_webhook_payload(payload)
      redis = request.app.state.redis

      for msg in messages:
          logger.info(f"Meta message from {msg.from_number}: type={msg.type}")
          msg.channel_id = channel["id"]

          if await is_dev_number(redis, msg.from_number):
              logger.info(f"Dev routing: forwarding Meta {msg.from_number} to {settings.dev_server_url}")
              background_tasks.add_task(
                  forward_to_dev,
                  dev_url=settings.dev_server_url,
                  path="/webhook/meta",
                  headers=dict(request.headers),
                  body=payload_bytes,
              )
              continue

          try:
              provider = get_provider(channel)
              await provider.mark_read(msg.message_id)
          except Exception as e:
              logger.warning(f"Failed to mark read via Meta: {e}")

          if msg.text and msg.text.strip().lower() == "!resetar":
              try:
                  lead = get_or_create_lead(msg.from_number)
                  reset_lead(lead["id"])
                  provider = get_provider(channel)
                  await provider.send_text(msg.from_number, "Memoria resetada! Pode comecar uma nova conversa do zero.")
              except Exception as e:
                  logger.error(f"Failed to reset lead: {e}", exc_info=True)
              continue

          await push_to_buffer(redis, msg)

      return {"status": "ok"}
  ```

- [ ] **Step 4: Run all tests to confirm everything passes**

  ```bash
  cd backend && python -m pytest tests/ -x -q
  ```
  Expected: all tests PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/webhook/meta_router.py backend/tests/test_webhook_dev_routing.py
  git commit -m "feat(dev-router): intercept Meta webhook for dev-whitelisted numbers"
  ```

---

## Task 7: Update VS Code Task Port

**Files:**
- Modify: `.vscode/tasks.json`

- [ ] **Step 1: Change `--port 8000` to `--port 8001` in the Start Backend task**

  Open `.vscode/tasks.json`. In the `"Start Backend"` task, update the `command` field from:

  ```json
  "command": "source venv/bin/activate 2>/dev/null || true && uvicorn app.main:app --reload --port 8000"
  ```

  to:

  ```json
  "command": "source venv/bin/activate 2>/dev/null || true && uvicorn app.main:app --reload --port 8001"
  ```

- [ ] **Step 2: Run full test suite one final time**

  ```bash
  cd backend && python -m pytest tests/ -q
  ```
  Expected: all tests PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add .vscode/tasks.json
  git commit -m "chore: change dev backend port to 8001 to avoid collision with production Docker"
  ```

---

## Post-Implementation Setup

After all tasks are complete, add to the production `.env` on the VPS:

```env
DEV_SERVER_URL=http://172.17.0.1:8001
DEV_API_KEY=<generate with: openssl rand -hex 16>
```

Then redeploy production to pick up the new config. No other infra changes needed.

**Activate dev routing for your test number:**

```bash
curl -X POST https://api.canastrainteligencia.com/api/dev/whitelist/5511999999999 \
  -H "X-Dev-Key: <your-key>"
```

**Start dev server:**

Use VS Code Task `Run All Dev (CRM & Backend)` — backend will start on port `8001`, VS Code port-forwards it to your local machine automatically.
