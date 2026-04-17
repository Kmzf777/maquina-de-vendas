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
