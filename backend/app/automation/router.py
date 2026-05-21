from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.automation.triggers import fire_trigger

router = APIRouter(prefix="/api/automation", tags=["automation"])


class TriggerEvent(BaseModel):
    event_type: str
    lead_id: str
    data: dict = {}


@router.post("/trigger")
async def fire_automation_trigger(event: TriggerEvent, background_tasks: BackgroundTasks):
    """Called by event hooks (Next.js routes) to fire automation triggers asynchronously."""
    background_tasks.add_task(fire_trigger, event.event_type, event.lead_id, event.data)
    return {"ok": True}
