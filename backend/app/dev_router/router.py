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
