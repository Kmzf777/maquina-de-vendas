import time
import pytest
import jwt as pyjwt
from fastapi import HTTPException

JWT_SECRET = "test-jwt-secret-32-chars-minimum!"


def _make_token(role: str = "admin", expired: bool = False) -> str:
    exp = int(time.time()) + (3600 if not expired else -1)
    payload = {
        "aud": "authenticated",
        "exp": exp,
        "sub": "00000000-0000-0000-0000-000000000001",
        "email": "test@example.com",
        "app_metadata": {"role": role},
        "role": "authenticated",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


def test_valid_admin_token_returns_payload():
    from app.auth.jwt import validate_token
    token = _make_token("admin")
    payload = validate_token(f"Bearer {token}")
    assert payload["app_metadata"]["role"] == "admin"


def test_valid_vendedor_token_returns_payload():
    from app.auth.jwt import validate_token
    token = _make_token("vendedor")
    payload = validate_token(f"Bearer {token}")
    assert payload["app_metadata"]["role"] == "vendedor"


def test_expired_token_raises_401():
    from app.auth.jwt import validate_token
    token = _make_token(expired=True)
    with pytest.raises(HTTPException) as exc_info:
        validate_token(f"Bearer {token}")
    assert exc_info.value.status_code == 401


def test_invalid_signature_raises_401():
    from app.auth.jwt import validate_token
    token = pyjwt.encode({"aud": "authenticated", "exp": int(time.time()) + 3600}, "wrong-secret", algorithm="HS256")
    with pytest.raises(HTTPException) as exc_info:
        validate_token(f"Bearer {token}")
    assert exc_info.value.status_code == 401


def test_missing_bearer_prefix_raises_401():
    from app.auth.jwt import validate_token
    token = _make_token("admin")
    with pytest.raises(HTTPException) as exc_info:
        validate_token(token)  # sem "Bearer "
    assert exc_info.value.status_code == 401


def test_malformed_token_raises_401():
    from app.auth.jwt import validate_token
    with pytest.raises(HTTPException) as exc_info:
        validate_token("Bearer not.a.valid.jwt")
    assert exc_info.value.status_code == 401


def test_require_role_allows_admin():
    from app.auth.dependencies import require_role
    import jwt as pyjwt
    import time
    payload = {
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "sub": "00000000-0000-0000-0000-000000000001",
        "app_metadata": {"role": "admin"},
        "role": "authenticated",
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    dep = require_role(["admin"])
    result = dep(credentials=creds)
    assert result == "admin"


def test_require_role_blocks_vendedor_from_admin_route():
    from app.auth.dependencies import require_role
    import jwt as pyjwt
    import time
    payload = {
        "aud": "authenticated",
        "exp": int(time.time()) + 3600,
        "sub": "00000000-0000-0000-0000-000000000001",
        "app_metadata": {"role": "vendedor"},
        "role": "authenticated",
    }
    token = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")
    from fastapi.security import HTTPAuthorizationCredentials
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    dep = require_role(["admin"])
    with pytest.raises(HTTPException) as exc_info:
        dep(credentials=creds)
    assert exc_info.value.status_code == 403


def test_require_role_raises_401_when_no_credentials():
    from app.auth.dependencies import require_role
    dep = require_role(["admin"])
    with pytest.raises(HTTPException) as exc_info:
        dep(credentials=None)
    assert exc_info.value.status_code == 401
