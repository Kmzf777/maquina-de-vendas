import os
import re

DEV_ROUTES_KEY = "dev:phone_routes"


def _normalize(phone: str) -> str:
    return re.sub(r"[\s+\-()\[\]]", "", phone)


async def get_dev_route(redis, phone: str) -> str | None:
    # Se ja estamos no servidor de dev, nao roteamos novamente.
    if os.environ.get("IS_DEV_ENV") == "true":
        return None
    route = await redis.hget(DEV_ROUTES_KEY, _normalize(phone))
    return route.decode("utf-8") if isinstance(route, bytes) else route


async def set_dev_route(redis, phone: str, dev_url: str) -> str:
    normalized = _normalize(phone)
    await redis.hset(DEV_ROUTES_KEY, normalized, dev_url)
    return normalized


async def remove_dev_route(redis, phone: str) -> str:
    normalized = _normalize(phone)
    await redis.hdel(DEV_ROUTES_KEY, normalized)
    return normalized


async def list_dev_routes(redis) -> dict[str, str]:
    routes = await redis.hgetall(DEV_ROUTES_KEY)
    return {
        k.decode("utf-8") if isinstance(k, bytes) else k: getattr(v, "decode", lambda: v)("utf-8") if isinstance(v, bytes) else v
        for k, v in routes.items()
    }
