import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    # Start with buffer OFF
    await app.state.redis.set("config:buffer_enabled", "0")
    yield
    await app.state.redis.close()


app = FastAPI(title="ValerIA", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.webhook.router import router as webhook_router
from app.leads.router import router as leads_router
from app.broadcast.router import router as broadcast_router
from app.cadence.router import router as cadence_router
from app.stats.router import router as stats_router
from app.stats.pricing_router import router as pricing_router
from app.webhook.meta_router import router as meta_webhook_router

app.include_router(webhook_router)
app.include_router(meta_webhook_router)
app.include_router(leads_router)
app.include_router(broadcast_router)
app.include_router(cadence_router)
app.include_router(stats_router)
app.include_router(pricing_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# --- Buffer toggle API ---

@app.get("/api/buffer")
async def get_buffer_status(request: Request):
    r = request.app.state.redis
    val = await r.get("config:buffer_enabled")
    enabled = val != "0"  # Default: enabled
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
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0a0a0a;
            color: #fafafa;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            background: #18181b;
            border: 1px solid #27272a;
            border-radius: 16px;
            padding: 40px;
            width: 400px;
            text-align: center;
        }
        .logo { font-size: 32px; font-weight: 700; margin-bottom: 8px; }
        .logo span { color: #22c55e; }
        .subtitle { color: #71717a; font-size: 14px; margin-bottom: 32px; }
        .toggle-section {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: #09090b;
            border: 1px solid #27272a;
            border-radius: 12px;
            padding: 20px 24px;
            margin-bottom: 16px;
        }
        .toggle-label { font-size: 16px; font-weight: 500; }
        .toggle-status {
            font-size: 13px;
            color: #71717a;
            margin-top: 4px;
        }
        .toggle-status.on { color: #22c55e; }
        .toggle-status.off { color: #ef4444; }
        .switch {
            position: relative;
            width: 56px;
            height: 30px;
            cursor: pointer;
        }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: #3f3f46;
            border-radius: 30px;
            transition: 0.3s;
        }
        .slider:before {
            content: "";
            position: absolute;
            height: 22px;
            width: 22px;
            left: 4px;
            bottom: 4px;
            background: white;
            border-radius: 50%;
            transition: 0.3s;
        }
        input:checked + .slider { background: #22c55e; }
        input:checked + .slider:before { transform: translateX(26px); }
        .loading { color: #71717a; font-size: 14px; }
    </style>
</head>
<body>
    <div id="root"></div>
    <script type="text/babel">
        const { useState, useEffect } = React;

        function App() {
            const [bufferOn, setBufferOn] = useState(true);
            const [loading, setLoading] = useState(true);

            useEffect(() => {
                fetch('/api/buffer')
                    .then(r => r.json())
                    .then(data => { setBufferOn(data.enabled); setLoading(false); })
                    .catch(() => setLoading(false));
            }, []);

            const toggle = async () => {
                const newState = !bufferOn;
                setBufferOn(newState);
                await fetch('/api/buffer', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ enabled: newState }),
                });
            };

            if (loading) return <div className="card"><p className="loading">Carregando...</p></div>;

            return (
                <div className="card">
                    <div className="logo">Valer<span>IA</span></div>
                    <p className="subtitle">Painel de Controle</p>

                    <div className="toggle-section">
                        <div style={{ textAlign: 'left' }}>
                            <div className="toggle-label">Buffer de Mensagens</div>
                            <div className={`toggle-status ${bufferOn ? 'on' : 'off'}`}>
                                {bufferOn ? 'Ativado — agrupa mensagens antes de processar' : 'Desativado — processa cada mensagem imediatamente'}
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
