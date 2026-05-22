import os
import re

DEV_ROUTES_KEY = "dev:phone_routes"


def _normalize(phone: str) -> str:
    """Canonical normalizer for dev-whitelist Redis keys.
    Strips all non-digits and injects the Brazilian 9th digit for 12-digit BR
    numbers (553496652412 → 5534996652412). Must produce the same output as
    leads.service.normalize_phone for any given input.
    """
    digits = re.sub(r"[^\d]", "", phone)
    # Brazilian mobiles: CC55 + DDD(2) + 8 digits = 12 total → inject 9th digit
    if len(digits) == 12 and digits.startswith("55"):
        digits = digits[:4] + "9" + digits[4:]
    return digits


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


async def is_dev_number(redis, phone: str) -> bool:
    return bool(await redis.hexists(DEV_ROUTES_KEY, _normalize(phone)))


async def add_dev_number(redis, phone: str, dev_url: str | None = None) -> str:
    normalized = _normalize(phone)
    route = dev_url or os.environ.get("DEV_SERVER_URL") or "http://127.0.0.1:8001"
    await redis.hset(DEV_ROUTES_KEY, normalized, route)
    return normalized


async def remove_dev_number(redis, phone: str) -> str:
    return await remove_dev_route(redis, phone)


async def list_dev_numbers(redis) -> list[str]:
    numbers = await redis.hkeys(DEV_ROUTES_KEY)
    return [n.decode("utf-8") if isinstance(n, bytes) else n for n in numbers]
