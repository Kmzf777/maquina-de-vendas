import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.buffer.flusher import run_flusher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )

    flusher_task = asyncio.create_task(run_flusher(app))

    yield

    flusher_task.cancel()
    try:
        await flusher_task
    except asyncio.CancelledError:
        pass

    await app.state.redis.close()


app = FastAPI(title="ValerIA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.campaign.router import router as campaign_router
from app.channels.router import router as channels_router
from app.agent_profiles.router import router as agent_profiles_router

app.include_router(webhook_router)
app.include_router(leads_router)
app.include_router(campaign_router)
app.include_router(channels_router)
app.include_router(agent_profiles_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
