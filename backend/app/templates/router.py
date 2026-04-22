from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.templates.schemas import TemplateCreate
from app.templates import service

router = APIRouter(prefix="/api/channels/{channel_id}/templates", tags=["templates"])


@router.post("")
async def create_template(channel_id: str, body: TemplateCreate):
    result, status = await service.create_template(
        channel_id, body.model_dump(exclude_none=True)
    )
    code = 202 if status == "pending_category_review" else 201
    return JSONResponse(content=result, status_code=code)


@router.post("/{template_id}/confirm")
async def confirm_template(channel_id: str, template_id: str):
    return await service.confirm_template(channel_id, template_id)


@router.delete("/{template_id}")
async def delete_template(channel_id: str, template_id: str):
    return await service.delete_template(channel_id, template_id)
