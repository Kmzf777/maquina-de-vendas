# Meta BSUID Resilience — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Meta WhatsApp integration process messages, identify leads, and send replies correctly when the phone number is omitted and only a BSUID is present.

**Architecture:** Treat the BSUID as a fallback identity for the whole pipeline. The shared primitive `normalize_phone` passes a BSUID through unchanged, so the existing phone-keyed buffer/processor/lead code keeps working with a BSUID string. `get_or_create_lead` gains a `bsuid` column and lookup; the Meta send client auto-routes a BSUID target to the `recipient` field (vs `to` for phones) by format detection. Phone is backfilled/merged onto the lead when it later reappears.

**Tech Stack:** Python 3, FastAPI, redis.asyncio, Supabase (PostgREST), pytest.

**Reference spec:** `docs/superpowers/specs/2026-07-01-meta-bsuid-resilience-design.md`

---

## Conventions (read once)

- Run tests from the `backend/` directory: `cd backend && python -m pytest <path> -v`.
- BSUID format: two ASCII letters, a dot, then alphanumerics — e.g. `US.13491208655302741918`. Phone numbers are digits only. This is how we tell them apart.
- Keep the Dev Router operating on the **raw payload before parsing** (CLAUDE.md §2). Do not introduce `localhost`/fixed IPs (CLAUDE.md §3).
- Commit after each task with the message shown.

---

## File Structure

- **Modify** `backend/app/leads/service.py` — `is_bsuid()` helper, `normalize_phone()` BSUID passthrough, `get_or_create_lead(bsuid=…)`, `resolve_lead_identity()`, `resolve_send_target()` includes bsuid.
- **Modify** `backend/app/webhook/parser.py` — `IncomingMessage` gains `bsuid`/`username`; `webhook_identity()` helper.
- **Modify** `backend/app/webhook/meta_parser.py` — extract `from_user_id`, contacts `user_id`, `profile.username`.
- **Modify** `backend/app/webhook/meta_router.py` — `_extract_from_number` returns phone-or-BSUID; register lead with bsuid; delivery-status phone backfill.
- **Modify** `backend/app/buffer/manager.py` — buffer identity = `normalize_phone(from_number) or bsuid`.
- **Modify** `backend/app/whatsapp/meta.py` — `_recipient_field()` and `_post` route BSUID → `recipient`.
- **Create** `backend/migrations/2026-07-01_leads_bsuid.sql` — `bsuid` column + partial unique index.
- **Create** 5 test files under `backend/tests/` (see tasks).

---

## Task 1: Identity primitives (`is_bsuid`, `normalize_phone` passthrough)

**Files:**
- Modify: `backend/app/leads/service.py`
- Test: `backend/tests/test_bsuid_identity_2026_07_01.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_bsuid_identity_2026_07_01.py
from app.leads.service import is_bsuid, normalize_phone


def test_is_bsuid_true_for_bsuid_format():
    assert is_bsuid("US.13491208655302741918") is True
    assert is_bsuid("BR.9988776655") is True


def test_is_bsuid_false_for_phone_and_junk():
    assert is_bsuid("5534999999999") is False
    assert is_bsuid("+55 34 99999-9999") is False
    assert is_bsuid("") is False
    assert is_bsuid(None) is False


def test_normalize_phone_passes_bsuid_through_unchanged():
    assert normalize_phone("US.13491208655302741918") == "US.13491208655302741918"


def test_normalize_phone_still_normalizes_real_phones():
    # 12-digit BR mobile gets the 9th digit injected (existing behaviour preserved)
    assert normalize_phone("553499999999") == "5534999999999"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bsuid_identity_2026_07_01.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_bsuid'`.

- [ ] **Step 3: Implement `is_bsuid` and the passthrough guard**

In `backend/app/leads/service.py`, add near the top (after `_PHONE_RE`):

```python
# BSUID (Business-Scoped User ID): two ASCII letters + '.' + alphanumerics,
# e.g. "US.13491208655302741918". Phones are digits-only, so the letter+dot
# prefix disambiguates them. Optional "ENT." segment = parent BSUID (also matches).
_BSUID_RE = re.compile(r"^[A-Za-z]{2}\.(?:ENT\.)?[A-Za-z0-9]+$")


def is_bsuid(value: str | None) -> bool:
    """True if the value is a WhatsApp Business-Scoped User ID (not a phone number)."""
    if not value:
        return False
    return bool(_BSUID_RE.match(value.strip()))
```

Then, at the very start of `normalize_phone`, after the empty-string guard, add the passthrough:

```python
def normalize_phone(phone: str | None) -> str:
    """Normalize to E.164 without '+'. Injects the Brazilian 9th digit when missing.

    A BSUID (e.g. "US.1349...") is returned unchanged — it is the fallback identity
    when the phone number is omitted from Meta webhooks, and must not be stripped.
    """
    if not phone:
        return ""
    if is_bsuid(phone):
        return phone.strip()
    if phone.startswith("whatsapp:"):
        phone = phone[len("whatsapp:"):]
    # ...rest of existing body unchanged...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_bsuid_identity_2026_07_01.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/leads/service.py backend/tests/test_bsuid_identity_2026_07_01.py
git commit -m "feat(bsuid): is_bsuid helper + normalize_phone passthrough for BSUIDs"
```

---

## Task 2: `IncomingMessage` fields + `webhook_identity` helper

**Files:**
- Modify: `backend/app/webhook/parser.py`
- Test: `backend/tests/test_bsuid_parser_2026_07_01.py` (created here, extended in Task 3-of-parser below)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_bsuid_parser_2026_07_01.py
from app.webhook.parser import IncomingMessage, webhook_identity


def _msg(**kw):
    base = dict(from_number="", remote_jid="", message_id="w1", timestamp="1", type="text")
    base.update(kw)
    return IncomingMessage(**base)


def test_webhook_identity_prefers_phone():
    m = _msg(from_number="5534999999999", bsuid="US.123")
    assert webhook_identity(m) == "5534999999999"


def test_webhook_identity_falls_back_to_bsuid():
    m = _msg(from_number="", bsuid="US.13491208655302741918")
    assert webhook_identity(m) == "US.13491208655302741918"


def test_incoming_message_has_bsuid_and_username_fields():
    m = _msg(bsuid="US.123", username="pablomorales")
    assert m.bsuid == "US.123"
    assert m.username == "pablomorales"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bsuid_parser_2026_07_01.py -v`
Expected: FAIL — `ImportError: cannot import name 'webhook_identity'` / unexpected keyword `bsuid`.

- [ ] **Step 3: Add fields and helper**

In `backend/app/webhook/parser.py`, add two fields to the `IncomingMessage` dataclass (after `ctwa_origem`):

```python
    bsuid: str | None = None       # Business-Scoped User ID (from_user_id) — fallback identity
    username: str | None = None    # WhatsApp username (contacts.profile.username), if adopted
```

Add at the end of the file:

```python
def webhook_identity(msg: "IncomingMessage") -> str:
    """Canonical routing key for a message: phone if present, else the BSUID.

    Meta omits the phone number once a user adopts a username, sending only the
    BSUID. This helper gives every consumer a single non-empty identity to key on.
    """
    return msg.from_number or (msg.bsuid or "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_bsuid_parser_2026_07_01.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/webhook/parser.py backend/tests/test_bsuid_parser_2026_07_01.py
git commit -m "feat(bsuid): IncomingMessage bsuid/username fields + webhook_identity helper"
```

---

## Task 3: Parse BSUID/username from Meta webhooks

**Files:**
- Modify: `backend/app/webhook/meta_parser.py:31-181` (`parse_meta_webhook_payload`)
- Test: `backend/tests/test_bsuid_meta_parser_2026_07_01.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_bsuid_meta_parser_2026_07_01.py
from app.webhook.meta_parser import parse_meta_webhook_payload


def _payload(contact, message):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "WABA",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "155", "phone_number_id": "PNID"},
                    "contacts": [contact],
                    "messages": [message],
                },
            }],
        }],
    }


def test_username_user_phone_omitted():
    # User adopted a username; Meta omits the phone, sends only the BSUID.
    payload = _payload(
        contact={"profile": {"name": "Pablo M.", "username": "pablomorales"},
                 "user_id": "US.13491208655302741918"},
        message={"from_user_id": "US.13491208655302741918", "id": "w1",
                 "timestamp": "1", "type": "text", "text": {"body": "oi"}},
    )
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].from_number == ""
    assert msgs[0].bsuid == "US.13491208655302741918"
    assert msgs[0].username == "pablomorales"
    assert msgs[0].push_name == "Pablo M."


def test_username_user_phone_present():
    payload = _payload(
        contact={"profile": {"name": "Pablo M.", "username": "pablomorales"},
                 "wa_id": "16505551234", "user_id": "US.1349"},
        message={"from": "16505551234", "from_user_id": "US.1349", "id": "w2",
                 "timestamp": "1", "type": "text", "text": {"body": "oi"}},
    )
    msgs = parse_meta_webhook_payload(payload)
    assert msgs[0].from_number == "16505551234"
    assert msgs[0].bsuid == "US.1349"
    assert msgs[0].username == "pablomorales"


def test_no_username_user_bsuid_and_phone():
    payload = _payload(
        contact={"profile": {"name": "Ana"}, "wa_id": "5534999999999", "user_id": "BR.999"},
        message={"from": "5534999999999", "from_user_id": "BR.999", "id": "w3",
                 "timestamp": "1", "type": "text", "text": {"body": "oi"}},
    )
    msgs = parse_meta_webhook_payload(payload)
    assert msgs[0].from_number == "5534999999999"
    assert msgs[0].bsuid == "BR.999"
    assert msgs[0].username is None
    assert msgs[0].push_name == "Ana"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bsuid_meta_parser_2026_07_01.py -v`
Expected: FAIL — `bsuid`/`username` are `None`/absent.

- [ ] **Step 3: Implement extraction**

In `backend/app/webhook/meta_parser.py`, inside the `for msg in value.get("messages", []):` loop, change the contact/name extraction block (currently lines ~46-55) to also read the BSUID and username:

```python
                from_number = msg.get("from", "")
                bsuid = msg.get("from_user_id")
                message_id = msg.get("id", "")
                timestamp = msg.get("timestamp", "")
                msg_type = msg.get("type", "")

                contacts = value.get("contacts", [])
                push_name = None
                username = None
                if contacts:
                    profile = contacts[0].get("profile", {})
                    push_name = profile.get("name")
                    username = profile.get("username")
                    # Fallback BSUID from the contacts block if the message lacked from_user_id.
                    if not bsuid:
                        bsuid = contacts[0].get("user_id")
```

Then pass the new fields into every `IncomingMessage(...)` construction (there is one, at the end of the loop). Add:

```python
                messages.append(IncomingMessage(
                    from_number=from_number,
                    remote_jid="",
                    message_id=message_id,
                    timestamp=timestamp,
                    type=parsed_type,
                    text=text,
                    media_url=media_url,
                    media_mime=media_mime,
                    push_name=push_name,
                    document_name=document_name,
                    metadata=metadata_dict,
                    quoted_wamid=quoted_wamid,
                    ctwa_clid=ctwa_clid,
                    ctwa_origem=ctwa_origem,
                    bsuid=bsuid,
                    username=username,
                ))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_bsuid_meta_parser_2026_07_01.py -v`
Expected: PASS (3 tests). Also run the full parser test file to check no regression: `python -m pytest tests/ -k meta_parser -v`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/webhook/meta_parser.py backend/tests/test_bsuid_meta_parser_2026_07_01.py
git commit -m "feat(bsuid): parse from_user_id/user_id/username from Meta webhooks"
```

---

## Task 4: Migration + BSUID-aware lead identity

**Files:**
- Create: `backend/migrations/2026-07-01_leads_bsuid.sql`
- Modify: `backend/app/leads/service.py` (`get_or_create_lead`, new `resolve_lead_identity`, `resolve_send_target`)
- Test: `backend/tests/test_bsuid_lead_identity_2026_07_01.py`

- [ ] **Step 1: Write the migration**

```sql
-- backend/migrations/2026-07-01_leads_bsuid.sql
-- BSUID (Business-Scoped User ID) resilience: store the Meta BSUID so leads whose
-- phone is omitted (username adopters) can still be identified and messaged.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS bsuid text;
CREATE UNIQUE INDEX IF NOT EXISTS leads_bsuid_key ON leads (bsuid) WHERE bsuid IS NOT NULL;
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_bsuid_lead_identity_2026_07_01.py
from app.leads.service import resolve_send_target


def test_resolve_send_target_prefers_wa_id_then_phone_then_bsuid():
    assert resolve_send_target({"wa_id": "16505551234", "phone": "16505551234", "bsuid": "US.1"}) == "16505551234"
    assert resolve_send_target({"phone": "5534999999999", "bsuid": "US.1"}) == "5534999999999"
    assert resolve_send_target({"bsuid": "US.13491208655302741918"}) == "US.13491208655302741918"
    assert resolve_send_target(None, fallback="US.9") == "US.9"


def test_resolve_send_target_empty_phone_falls_to_bsuid():
    # BSUID-only lead: phone/wa_id are empty strings, not missing keys.
    assert resolve_send_target({"phone": "", "wa_id": "", "bsuid": "US.7"}) == "US.7"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bsuid_lead_identity_2026_07_01.py -v`
Expected: FAIL — the third/fourth assertions return `""` because `resolve_send_target` doesn't know about `bsuid`.

- [ ] **Step 4: Implement `resolve_send_target` bsuid fallback**

In `backend/app/leads/service.py`, replace the body of `resolve_send_target`:

```python
def resolve_send_target(lead: dict[str, Any] | None, fallback: str | None = None) -> str:
    """Deliverable WhatsApp address for the lead.

    Prefers wa_id (the real `from` Meta delivered), then the normalized phone,
    then the BSUID (used when the phone was never disclosed — username adopters).
    NULL/empty everywhere -> fallback. The Meta client routes a BSUID target to the
    `recipient` field automatically (see whatsapp/meta.py).
    """
    if lead:
        target = lead.get("wa_id") or lead.get("phone") or lead.get("bsuid")
        if target:
            return target
    return fallback or ""
```

- [ ] **Step 5: Make `get_or_create_lead` BSUID-aware**

In `get_or_create_lead`, add a `bsuid` parameter and a BSUID branch. Change the signature:

```python
def get_or_create_lead(
    phone: str,
    name: str | None = None,
    channel: str | None = None,
    ctwa_clid: str | None = None,
    tracking: dict[str, Any] | None = None,
    bsuid: str | None = None,
) -> dict[str, Any]:
```

Immediately after `name = sanitize_display_name(name)` and before `normalized = normalize_phone(phone)`, insert the BSUID-first branch used when the caller passed a BSUID as the identity (phone absent):

```python
    sb = get_supabase()
    name = sanitize_display_name(name)

    # BSUID identity path: the phone was omitted (username adopter). Look the lead up by
    # its BSUID; create a phone-less lead keyed by BSUID if none exists yet. The phone is
    # merged in later by resolve_lead_identity when it reappears.
    incoming_bsuid = bsuid if is_bsuid(bsuid) else (phone if is_bsuid(phone) else None)
    if incoming_bsuid and not is_bsuid(phone):
        # phone may still carry a real number alongside an explicit bsuid kwarg.
        pass
    if incoming_bsuid and (not phone or is_bsuid(phone)):
        existing = sb.table("leads").select("*").eq("bsuid", incoming_bsuid).limit(1).execute()
        if existing.data:
            lead = existing.data[0]
            if name and not lead.get("name"):
                try:
                    sb.table("leads").update({"name": name}).eq("id", lead["id"]).execute()
                    lead = {**lead, "name": name}
                except Exception as exc:
                    logger.warning("leads.service: failed to backfill name for bsuid lead %s: %s", lead["id"], exc)
            return lead
        insert = {"phone": "", "bsuid": incoming_bsuid}
        if name:
            insert["name"] = name
        if channel:
            insert["channel"] = channel
        if ctwa_clid:
            insert["ctwa_clid"] = ctwa_clid
        created = sb.table("leads").insert(insert).execute()
        return created.data[0]

    normalized = normalize_phone(phone)
    # ...rest of existing body unchanged...
```

Note: the existing body's own `sb = get_supabase()` line (currently the first line) is now redundant — remove the duplicate so `sb` is assigned once at the top.

Also, where the phone path creates a lead with a real phone AND a `bsuid` kwarg was supplied, stamp the bsuid. Find the existing final insert in `get_or_create_lead` (the `sb.table("leads").insert(...)` for the new-phone case) and add `if is_bsuid(bsuid): insert_fields["bsuid"] = bsuid` to its payload dict before the insert. (Match the existing variable name for the insert dict in that block.)

- [ ] **Step 6: Add `resolve_lead_identity` (merge/backfill)**

Add a new function to `backend/app/leads/service.py`:

```python
def resolve_lead_identity(phone: str | None, bsuid: str | None, name: str | None = None) -> dict[str, Any]:
    """Resolve (and reconcile) a lead from a phone and/or BSUID.

    - Phone present  -> normal phone lookup/create; stamp the BSUID onto the lead.
    - Phone absent   -> BSUID lookup/create.
    - Merge: if a phone-lead exists and a separate BSUID-only lead also exists, prefer
      the phone-lead, stamp the BSUID onto it, and log the duplicate for manual review
      (never auto-delete a real lead).
    """
    sb = get_supabase()
    real_phone = phone if (phone and not is_bsuid(phone)) else None
    real_bsuid = bsuid if is_bsuid(bsuid) else (phone if is_bsuid(phone) else None)

    if real_phone:
        lead = get_or_create_lead(real_phone, name=name)
        if real_bsuid and lead.get("bsuid") != real_bsuid:
            # Is there a separate BSUID-only lead to reconcile?
            try:
                dup = sb.table("leads").select("id").eq("bsuid", real_bsuid).neq("id", lead["id"]).limit(1).execute()
                if dup.data:
                    logger.warning(
                        "leads.service: BSUID %s already on lead %s while phone-lead is %s — "
                        "keeping phone-lead, manual reconcile needed",
                        real_bsuid, dup.data[0]["id"], lead["id"],
                    )
                else:
                    sb.table("leads").update({"bsuid": real_bsuid}).eq("id", lead["id"]).execute()
                    lead = {**lead, "bsuid": real_bsuid}
            except Exception as exc:
                logger.warning("leads.service: failed to stamp bsuid on lead %s: %s", lead["id"], exc)
        return lead

    # Phone absent: BSUID identity.
    return get_or_create_lead("", name=name, bsuid=real_bsuid)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bsuid_lead_identity_2026_07_01.py tests/test_bsuid_identity_2026_07_01.py -v`
Expected: PASS. (These tests don't hit Supabase; they cover `resolve_send_target`/`is_bsuid`. The DB-backed functions are exercised via the router test in Task 6 with mocks.)

- [ ] **Step 8: Commit**

```bash
git add backend/migrations/2026-07-01_leads_bsuid.sql backend/app/leads/service.py backend/tests/test_bsuid_lead_identity_2026_07_01.py
git commit -m "feat(bsuid): leads.bsuid column, BSUID-aware get_or_create_lead + resolve_lead_identity + send target"
```

---

## Task 5: Meta send client routes BSUID → `recipient`

**Files:**
- Modify: `backend/app/whatsapp/meta.py` (add `_recipient_field`, apply in every send payload)
- Test: `backend/tests/test_bsuid_send_routing_2026_07_01.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_bsuid_send_routing_2026_07_01.py
from app.whatsapp.meta import _recipient_field


def test_recipient_field_phone_uses_to():
    assert _recipient_field("5534999999999") == {"to": "5534999999999"}


def test_recipient_field_bsuid_uses_recipient():
    assert _recipient_field("US.13491208655302741918") == {"recipient": "US.13491208655302741918"}


def test_recipient_field_parent_bsuid_uses_recipient():
    assert _recipient_field("US.ENT.11815799212886844830") == {"recipient": "US.ENT.11815799212886844830"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bsuid_send_routing_2026_07_01.py -v`
Expected: FAIL — `ImportError: cannot import name '_recipient_field'`.

- [ ] **Step 3: Implement `_recipient_field` and use it in payloads**

In `backend/app/whatsapp/meta.py`, add near the top (after the imports, module level):

```python
from app.leads.service import is_bsuid


def _recipient_field(target: str) -> dict:
    """Meta addressing field for a recipient.

    A BSUID (e.g. "US.1349...") must be sent as `recipient`; a phone number as `to`.
    The two are format-distinguishable, so callers keep passing a single target string.
    """
    return {"recipient": target} if is_bsuid(target) else {"to": target}
```

Then, in each send method, replace `"to": to,` with `**_recipient_field(to),`. Apply to all payload dicts in: `send_text` (line ~203), `send_image` (~218), `send_image_bytes` (~280), `send_audio` (~295), `send_contact` (~305), `send_template` (~327). Example for `send_text`:

```python
    async def send_text(self, to: str, body: str) -> dict:
        result = await self._post({
            "messaging_product": "whatsapp",
            **_recipient_field(to),
            "type": "text",
            "text": {"body": body},
        }, request_type="send_text")
        # ...unchanged...
```

Note: keep the `log_outbound(..., to_number=payload.get("to"), ...)` call working — since a BSUID payload has no `to`, update that call to `to_number=payload.get("to") or payload.get("recipient")` (find it around line 195).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bsuid_send_routing_2026_07_01.py -v`
Expected: PASS (3 tests). Also run `python -m pytest tests/ -k "meta and send" -v` to check no regression in existing send tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whatsapp/meta.py backend/tests/test_bsuid_send_routing_2026_07_01.py
git commit -m "feat(bsuid): Meta client routes BSUID targets to recipient field"
```

---

## Task 6: Dev router + webhook wiring (extract BSUID, register lead, buffer key)

**Files:**
- Modify: `backend/app/webhook/meta_router.py` (`_extract_from_number`, `_register_lead`, `receive_meta_webhook` call site, delivery backfill)
- Modify: `backend/app/buffer/manager.py:25` (buffer identity)
- Test: `backend/tests/test_bsuid_dev_router_2026_07_01.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_bsuid_dev_router_2026_07_01.py
from app.webhook.meta_router import _extract_from_number, _extract_statuses


def _msg_payload(message):
    return {"entry": [{"changes": [{"value": {"messages": [message]}}]}]}


def test_extract_identity_prefers_phone():
    p = _msg_payload({"from": "5534999999999", "from_user_id": "BR.999"})
    assert _extract_from_number(p) == "5534999999999"


def test_extract_identity_falls_back_to_bsuid():
    p = _msg_payload({"from_user_id": "US.13491208655302741918"})
    assert _extract_from_number(p) == "US.13491208655302741918"


def test_extract_identity_from_status_recipient_user_id():
    p = {"entry": [{"changes": [{"value": {"statuses": [
        {"recipient_user_id": "US.1349", "status": "delivered", "id": "w1"}
    ]}}]}]}
    # No messages[].from -> caller falls back to statuses; recipient_id absent, use recipient_user_id.
    assert _extract_from_number(p) is None
    statuses = _extract_statuses(p)
    assert (statuses[0].get("recipient_id") or statuses[0].get("recipient_user_id")) == "US.1349"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_bsuid_dev_router_2026_07_01.py -v`
Expected: FAIL — `test_extract_identity_falls_back_to_bsuid` returns `None`.

- [ ] **Step 3: Update `_extract_from_number` to fall back to BSUID**

In `backend/app/webhook/meta_router.py`, change `_extract_from_number`:

```python
def _extract_from_number(payload: dict) -> str | None:
    """Routing identity from raw payload: phone (messages[].from) or BSUID (from_user_id).

    Runs on the raw payload before parsing so the Dev Router catches every message type
    (CLAUDE.md §2). Returns the phone when present, else the BSUID, else None.
    """
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                identity = msg.get("from") or msg.get("from_user_id")
                if identity:
                    return identity
    return None
```

And in the Dev Router block inside `receive_meta_webhook`, update the status fallback (currently `from_number = statuses[0].get("recipient_id")`) to:

```python
            if statuses:
                from_number = statuses[0].get("recipient_id") or statuses[0].get("recipient_user_id")
```

- [ ] **Step 4: Register lead with BSUID + set buffer identity**

In `backend/app/webhook/meta_router.py`, change `_register_lead` to accept and use the BSUID via `resolve_lead_identity`:

```python
def _register_lead(
    from_number: str,
    push_name: str | None,
    ctwa_clid: str | None = None,
    ctwa_origem: str | None = None,
    bsuid: str | None = None,
) -> None:
    """Ensure the lead exists in the CRM the moment they contact us (BackgroundTask).

    Uses resolve_lead_identity so a phone-less (BSUID-only) message still creates/finds a
    lead, and a later phone reappearance merges onto it.
    """
    try:
        from app.leads.service import resolve_lead_identity
        lead = resolve_lead_identity(from_number or None, bsuid, name=push_name)
    except Exception as exc:
        logger.warning("Failed to register lead for %s/%s: %s", from_number, bsuid, exc)
        return
    # wa_id capture only makes sense for a real phone address.
    try:
        if lead and from_number and not is_bsuid(from_number) and lead.get("wa_id") != from_number:
            update_lead(lead["id"], wa_id=from_number)
    except Exception as exc:
        logger.warning("Failed to capture wa_id=%s for lead %s: %s", from_number, lead.get("id"), exc)
    # ...keep the existing ctwa_clid and ctwa_origem stamping blocks unchanged...
```

Add the import at the top of `meta_router.py` (with the other `app.leads.service` imports): add `is_bsuid` to the existing import line
`from app.leads.service import get_or_create_lead, normalize_phone, reset_lead, purge_dev_lead, update_lead`
→ append `, is_bsuid`.

At the `_register_lead` call site inside the `for msg in messages:` loop, pass the BSUID:

```python
        background_tasks.add_task(_register_lead, msg.from_number, msg.push_name, msg.ctwa_clid, msg.ctwa_origem, msg.bsuid)
```

Also update the `push_to_buffer`/tracking calls that use `msg.from_number` to use the identity so BSUID-only messages don't collapse to `""`. Add a local at the top of the loop body:

```python
        identity = msg.from_number or msg.bsuid or ""
```

and use `identity` for `_track_inbound_message_time(identity)` and for the `!resetar` `purge_dev_lead(identity)` / provider replies. Leave `msg.from_number` in log lines. (The buffer itself derives its own key in Task 6 Step 5.)

- [ ] **Step 5: Buffer identity in `manager.py`**

In `backend/app/buffer/manager.py`, change line 25 from:

```python
    phone = normalize_phone(msg.from_number)
```
to:
```python
    # Identity = normalized phone, or the BSUID when the phone was omitted (username adopter).
    # normalize_phone passes a BSUID through unchanged, so the key stays unique per user.
    phone = normalize_phone(msg.from_number) or (msg.bsuid or "")
```

- [ ] **Step 6: Delivery-status phone backfill**

In `_handle_delivery_status` (or a small helper called from the status loop in `receive_meta_webhook`), when a `contacts` block carries both `wa_id` and `user_id`, stamp the phone onto the BSUID lead. Add this helper to `meta_router.py`:

```python
def _backfill_phone_from_status(payload: dict) -> None:
    """When a status/contacts block carries both wa_id and user_id, merge the phone
    onto the BSUID lead (free phone recovery for username adopters)."""
    try:
        from app.leads.service import resolve_lead_identity
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                for c in change.get("value", {}).get("contacts", []):
                    wa_id = c.get("wa_id")
                    user_id = c.get("user_id")
                    if wa_id and user_id:
                        resolve_lead_identity(wa_id, user_id)
    except Exception as exc:
        logger.warning("[DELIVERY] phone backfill failed: %s", exc)
```

Call it as a BackgroundTask right after the status loop in `receive_meta_webhook`:

```python
    if _extract_statuses(payload):
        background_tasks.add_task(_backfill_phone_from_status, payload)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_bsuid_dev_router_2026_07_01.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/app/webhook/meta_router.py backend/app/buffer/manager.py backend/tests/test_bsuid_dev_router_2026_07_01.py
git commit -m "feat(bsuid): dev router + lead registration + buffer key + status phone backfill"
```

---

## Task 7: Full-suite regression + wrap-up

**Files:** none (verification only)

- [ ] **Step 1: Run the BSUID suite**

Run: `cd backend && python -m pytest tests/ -k bsuid -v`
Expected: all BSUID tests PASS.

- [ ] **Step 2: Run the webhook/buffer/leads regression**

Run: `cd backend && python -m pytest tests/ -k "meta or buffer or lead or parser or send" -v`
Expected: PASS. Investigate and fix any regression before proceeding.

- [ ] **Step 3: Run the whole suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: no new failures vs. the pre-change baseline. (If pre-existing failures exist unrelated to this work, note them; do not fix unrelated tests.)

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "test(bsuid): full-suite regression pass for BSUID resilience"
```

---

## Self-Review notes

- **Spec §4.1–4.7 coverage:** identifier model (T2), parsing (T3), dev router (T6), buffer (T6), lead identity + migration (T4), send path (T5), status backfill (T6). ✅
- **Merge/reconcile (spec §4.5):** `resolve_lead_identity` in T4/T6, no auto-delete. ✅
- **Out-of-scope (spec §2):** parent BSUID matched by `_recipient_field`/`is_bsuid` regex but not otherwise implemented — intentional (defensive). ✅
- **Migration pending manual apply** in Supabase — flag to user at the end (project workflow).
