from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import validate_token

_bearer = HTTPBearer(auto_error=False)


def require_role(allowed_roles: list[str]):
    """Retorna uma FastAPI dependency que exige um dos roles listados."""

    def _dependency(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    ) -> str:
        if credentials is None:
            raise HTTPException(status_code=401, detail="Não autenticado")

        payload = validate_token(f"Bearer {credentials.credentials}")
        role: str | None = payload.get("app_metadata", {}).get("role")

        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Permissão insuficiente")

        return role

    return _dependency
