import logging
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel

from app.config import settings
from app.dev_router.service import set_dev_route, list_dev_routes, remove_dev_route

logger = logging.getLogger(__name__)
router = APIRouter()

class RoutePayload(BaseModel):
    dev_url: str

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
    routes = await list_dev_routes(request.app.state.redis)
    return {"routes": routes}

@router.post("/api/dev/whitelist/{phone}")
async def add_to_whitelist(
    phone: str,
    payload: RoutePayload,
    request: Request,
    x_dev_key: Annotated[str | None, Header()] = None,
):
    if err := _auth(x_dev_key):
        return err
    normalized = await set_dev_route(request.app.state.redis, phone, payload.dev_url)
    logger.info(f"Dev mapping: added {normalized} -> {payload.dev_url}")
    return {"added": normalized, "url": payload.dev_url}

@router.delete("/api/dev/whitelist/{phone}")
async def remove_from_whitelist(
    phone: str,
    request: Request,
    x_dev_key: Annotated[str | None, Header()] = None,
):
    if err := _auth(x_dev_key):
        return err
    normalized = await remove_dev_route(request.app.state.redis, phone)
    logger.info(f"Dev mapping: removed {normalized}")
    return {"removed": normalized}
