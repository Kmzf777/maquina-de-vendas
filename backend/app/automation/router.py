from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
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


@router.get("/campaigns/{campaign_id}/test")
async def test_campaign_sse(campaign_id: str, phone: str, skip_delays: bool = True):
    """SSE endpoint: executes campaign nodes for a test phone, emitting events per node."""
    from app.automation.test_runner import run_test_campaign

    return StreamingResponse(
        run_test_campaign(campaign_id, phone, skip_delays),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
