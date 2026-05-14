import jwt as pyjwt
from fastapi import HTTPException

from app.config import settings


def validate_token(authorization: str) -> dict:
    """Valida JWT Supabase e retorna o payload. Lança HTTPException em caso de falha."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token inválido")

    token = authorization[len("Bearer "):]

    try:
        payload = pyjwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")
