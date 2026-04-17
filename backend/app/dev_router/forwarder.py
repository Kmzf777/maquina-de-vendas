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
