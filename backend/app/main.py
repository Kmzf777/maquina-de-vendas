import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings
from app.buffer.flusher import run_flusher
from app.whatsapp.meta import close_shared_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)

logger = logging.getLogger(__name__)


async def _recover_orphaned_buffers(redis: aioredis.Redis) -> None:
    """Flush buffer keys left in Redis after a container restart.

    manager.py stores asyncio Tasks in-process; a restart destroys them while
    the Redis list keys (buffer:{phone}:{channel_id}) survive. This scan finds
    lists whose lock has already expired (timer gone) and re-processes them so
    no inbound message is silently dropped.
    """
    from app.buffer.processor import process_buffered_messages

    recovered = 0
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="buffer:*", count=200)
        for key in keys:
            if key.endswith(":lock") or key.endswith(":deadline"):
                continue
            parts = key.split(":", 2)
            if len(parts) != 3:
                continue
            _, phone, channel_id = parts

            lock_key = f"buffer:{phone}:{channel_id}:lock"
            has_lock = await redis.exists(lock_key)
            if has_lock:
                continue

            messages = await redis.lrange(key, 0, -1)
            if not messages:
                await redis.delete(key)
                continue

            await redis.delete(key)
            pending_wamid = await redis.get(f"pending_wamid:{phone}:{channel_id}")
            pending_quoted = await redis.get(f"pending_quoted:{phone}:{channel_id}")
            await redis.delete(f"pending_wamid:{phone}:{channel_id}")
            await redis.delete(f"pending_quoted:{phone}:{channel_id}")

            combined = "\n".join(messages)
            logger.warning(
                "[BUFFER RECOVERY] %d mensagem(ns) órfã(s) recuperada(s) para phone=%s channel=%s",
                len(messages), phone, channel_id,
            )
            asyncio.create_task(
                process_buffered_messages(
                    phone, combined, channel_id,
                    wamid=pending_wamid,
                    quoted_wamid=pending_quoted,
                )
            )
            recovered += 1

        if cursor == 0:
            break

    if recovered:
        logger.warning("[BUFFER RECOVERY] %d buffer(s) órfão(s) reprocessado(s) no startup", recovered)


async def _wait_for_redis(redis: aioredis.Redis, max_wait: float = 30.0) -> None:
    """Espera o Redis aceitar conexões antes de prosseguir o startup.

    No Windows/WSL2, o Docker pode levar vários segundos para mapear a porta 6379 no
    host no primeiro boot. `aioredis.from_url` é preguiçoso (não conecta), então o
    primeiro comando real falharia com ConnectionRefusedError [WinError 1225] e
    derrubaria o FastAPI ("Application startup failed"). Aqui fazemos PING com backoff
    por até max_wait segundos (≈6-8 tentativas) antes de desistir, dando tempo ao WSL2.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_wait
    attempt = 0
    while True:
        attempt += 1
        try:
            await redis.ping()
            if attempt > 1:
                logger.info("Redis disponível após %d tentativa(s)", attempt)
            return
        except Exception as e:
            if loop.time() >= deadline:
                logger.error(
                    "Redis indisponível após %.0fs — abortando startup: %s", max_wait, e
                )
                raise
            delay = min(1.0 * attempt, 2.0)
            logger.warning(
                "Redis ainda não pronto (tentativa %d): %s — retry em %.1fs",
                attempt, e, delay,
            )
            await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True,
        socket_connect_timeout=5, socket_timeout=5,
    )
    # Tolerância à inicialização: aguarda o Redis aceitar conexões (Docker/Windows
    # pode demorar a expor a porta) antes do primeiro comando real.
    await _wait_for_redis(app.state.redis)
    # Default buffer ON; can be overridden in Redis via POST /api/buffer.
    # setnx only sets the key if it does NOT exist — preserves runtime toggles across restarts.
    await app.state.redis.setnx("config:buffer_enabled", "1")

    await _recover_orphaned_buffers(app.state.redis)

    flusher_task = asyncio.create_task(run_flusher(app))

    yield

    flusher_task.cancel()
    try:
        await flusher_task
    except asyncio.CancelledError:
        pass

    await close_shared_client()
    await app.state.redis.close()


app = FastAPI(title="ValerIA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
from app.webhook.router import router as webhook_router
from app.webhook.meta_router import router as meta_webhook_router
from app.leads.router import router as leads_router
from app.broadcast.router import router as broadcast_router
from app.stats.router import router as stats_router
from app.stats.pricing_router import router as pricing_router
from app.outbound.router import router as outbound_router
from app.channels.router import router as channels_router
from app.agent_profiles.router import router as agent_profiles_router
from app.conversations.router import router as conversations_router
from app.dev_router.router import router as dev_router
from app.templates.router import router as templates_router
from app.follow_up.router import router as follow_up_router
from app.campaigns.router import router as campaigns_router
from app.automation.router import router as automation_router
from app.lp_webhook.router import router as lp_webhook_router

app.include_router(webhook_router)
app.include_router(meta_webhook_router)
app.include_router(leads_router)
app.include_router(broadcast_router)
app.include_router(stats_router)
app.include_router(pricing_router)
app.include_router(outbound_router)
app.include_router(channels_router)
app.include_router(agent_profiles_router)
app.include_router(conversations_router)
app.include_router(dev_router)
app.include_router(templates_router)
app.include_router(follow_up_router)
app.include_router(campaigns_router)
app.include_router(automation_router)
app.include_router(lp_webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/debug/agent")
async def debug_agent():
    """Diagnostic endpoint: tests Gemini connectivity and agent pipeline."""
    import traceback

    result = {"gemini_key_set": bool(settings.gemini_api_key)}

    try:
        from app.agent.orchestrator import get_ai_client

        client = get_ai_client("gemini-2.5-flash")
        resp = await client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
        )
        result["gemini_test"] = "ok"
        result["gemini_response"] = resp.choices[0].message.content
    except Exception as e:
        result["gemini_test"] = "error"
        result["gemini_error"] = str(e)
        result["gemini_traceback"] = traceback.format_exc()

    try:
        from app.agent.orchestrator import run_agent
        conv = {
            "id": "00000000-0000-0000-0000-000000000000",
            "stage": "secretaria",
            "leads": {"id": "00000000-0000-0000-0000-000000000001", "name": None, "phone": "5500000000000"},
        }
        resp = await run_agent(conv, "ping de diagnostico")
        result["agent_test"] = "ok"
        result["agent_response"] = resp[:100]
    except Exception as e:
        result["agent_test"] = "error"
        result["agent_error"] = str(e)
        result["agent_traceback"] = traceback.format_exc()

    return result


# --- Buffer toggle API ---

@app.get("/api/buffer")
async def get_buffer_status(request: Request):
    r = request.app.state.redis
    val = await r.get("config:buffer_enabled")
    enabled = val != "0"
    return {"enabled": enabled}


@app.post("/api/buffer")
async def set_buffer_status(request: Request):
    body = await request.json()
    r = request.app.state.redis
    enabled = body.get("enabled", True)
    await r.set("config:buffer_enabled", "1" if enabled else "0")
    return {"enabled": enabled}


# --- Web dashboard ---

@app.get("/web", response_class=HTMLResponse)
async def web_dashboard():
    return """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ValerIA - Painel</title>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0a0a0a; color: #fafafa; min-height: 100vh;
               display: flex; align-items: center; justify-content: center; }
        .card { background: #18181b; border: 1px solid #27272a; border-radius: 16px;
                padding: 40px; width: 400px; text-align: center; }
        .logo { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
        .logo span { color: #22c55e; }
        .subtitle { color: #71717a; font-size: 14px; margin-bottom: 32px; }
        .toggle-section { display: flex; align-items: center; justify-content: space-between;
                          background: #09090b; border: 1px solid #27272a; border-radius: 12px;
                          padding: 20px 24px; margin-bottom: 16px; }
        .toggle-label { font-size: 16px; font-weight: 500; }
        .toggle-status { font-size: 13px; color: #71717a; margin-top: 4px; }
        .toggle-status.on { color: #22c55e; }
        .toggle-status.off { color: #ef4444; }
        .switch { position: relative; width: 56px; height: 30px; cursor: pointer; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; top: 0; left: 0; right: 0; bottom: 0;
                  background: #3f3f46; border-radius: 30px; transition: 0.3s; }
        .slider:before { content: ""; position: absolute; height: 22px; width: 22px;
                         left: 4px; bottom: 4px; background: white; border-radius: 50%; transition: 0.3s; }
        input:checked + .slider { background: #22c55e; }
        input:checked + .slider:before { transform: translateX(26px); }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const { useState, useEffect } = React;
        function App() {
            const [bufferOn, setBufferOn] = useState(false);
            const [loading, setLoading] = useState(true);
            useEffect(() => {
                fetch('/api/buffer').then(r => r.json())
                    .then(d => { setBufferOn(d.enabled); setLoading(false); })
                    .catch(() => setLoading(false));
            }, []);
            const toggle = async () => {
                const next = !bufferOn;
                setBufferOn(next);
                await fetch('/api/buffer', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({enabled: next}),
                });
            };
            if (loading) return <div className="card"><p>Carregando...</p></div>;
            return (
                <div className="card">
                    <div className="logo">Valer<span>IA</span></div>
                    <p className="subtitle">Painel de Controle</p>
                    <div className="toggle-section">
                        <div style={{textAlign: 'left'}}>
                            <div className="toggle-label">Buffer de Mensagens</div>
                            <div className={"toggle-status " + (bufferOn ? "on" : "off")}>
                                {bufferOn ? "Ativado — agrupa mensagens" : "Desativado — processa imediatamente"}
                            </div>
                        </div>
                        <label className="switch">
                            <input type="checkbox" checked={bufferOn} onChange={toggle} />
                            <span className="slider"></span>
                        </label>
                    </div>
                </div>
            );
        }
        ReactDOM.createRoot(document.getElementById('root')).render(<App />);
    </script>
</body>
</html>"""
