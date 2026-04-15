from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.supabase import get_supabase

router = APIRouter(prefix="/api/agent-profiles", tags=["agent_profiles"])


class ProfileCreate(BaseModel):
    name: str
    model: str = "gpt-4.1"
    stages: dict
    base_prompt: str


class ProfileUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    stages: dict | None = None
    base_prompt: str | None = None


@router.get("")
async def list_profiles():
    sb = get_supabase()
    result = sb.table("agent_profiles").select("*").order("created_at", desc=True).execute()
    return {"data": result.data}


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    sb = get_supabase()
    result = sb.table("agent_profiles").select("*").eq("id", profile_id).single().execute()
    return result.data


@router.post("")
async def create_profile(body: ProfileCreate):
    sb = get_supabase()
    result = sb.table("agent_profiles").insert(body.model_dump()).execute()
    return result.data[0]


@router.put("/{profile_id}")
async def update_profile(profile_id: str, body: ProfileUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    sb = get_supabase()
    result = sb.table("agent_profiles").update(data).eq("id", profile_id).execute()
    return result.data[0]


@router.delete("/{profile_id}")
async def delete_profile(profile_id: str):
    sb = get_supabase()
    sb.table("agent_profiles").delete().eq("id", profile_id).execute()
    return {"status": "deleted"}
