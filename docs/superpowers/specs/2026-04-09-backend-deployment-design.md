# Backend Deployment Design — ValerIA

**Date:** 2026-04-09  
**Status:** Approved  

---

## Context

The ValerIA project is a WhatsApp AI agent platform. The frontend (Next.js CRM) is already deployed on Vercel. The backend (`backend-evolution/`) — FastAPI + Redis + background worker — needs to be deployed to a Hostinger VPS and exposed via HTTPS so the Meta WhatsApp Business API can reach the webhook endpoint.

---

## Architecture

```
Internet
   │
   ▼
DNS: api.<domain> → VPS IP (Hostinger)
   │
   ▼
VPS Hostinger
   ├── Nginx (ports 80/443, SSL via Certbot/Let's Encrypt)
   │     └── proxy_pass → 127.0.0.1:8000
   │
   └── Docker Compose (backend-evolution/)
         ├── api        (FastAPI, port 8000 — internal only)
         ├── worker     (campaign worker, no exposed port)
         └── redis      (port 6379 — internal only)

Vercel (Next.js CRM)
   └── NEXT_PUBLIC_FASTAPI_URL=https://api.<domain>
```

### Webhook flow

```
Meta → POST https://api.<domain>/webhook/meta
     → Nginx → FastAPI (port 8000) → Redis buffer → worker → OpenAI → WhatsApp reply
```

### Security boundary

- Port 8000 (FastAPI) is **not publicly exposed** — Nginx proxies to it on localhost only
- Port 6379 (Redis) is **not publicly exposed** — Docker internal network only
- UFW firewall: allow 22 (SSH), 80 (HTTP→redirect), 443 (HTTPS); deny all others

---

## Configuration

### Backend `.env` (on VPS at `backend-evolution/.env`)

```env
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
REDIS_URL=redis://redis:6379
API_BASE_URL=https://api.<domain>
FRONTEND_URL=https://<vercel-app>.vercel.app
```

> `REDIS_URL` must use the Docker Compose service name `redis`, not `localhost`.

### Nginx config (`/etc/nginx/sites-available/valeria`)

```nginx
server {
    listen 80;
    server_name api.<domain>;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name api.<domain>;

    ssl_certificate /etc/letsencrypt/live/api.<domain>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.<domain>/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Meta WhatsApp — callback URL

```
https://api.<domain>/webhook/meta
```

### Vercel — environment variable

```
NEXT_PUBLIC_FASTAPI_URL=https://api.<domain>
```

---

## Deployment Sequence

### Phase 1 — DNS
1. Create `A` record: `api.<domain>` → VPS IP
2. Wait for propagation (5–30 min)

### Phase 2 — Prepare VPS
1. SSH into VPS
2. Install Docker + Docker Compose plugin
3. Install Nginx + Certbot
4. Enable Docker on boot: `systemctl enable docker`

### Phase 3 — Deploy code
1. Clone repo on VPS (or upload `backend-evolution/`)
2. Create `.env` file with production values
3. Start containers: `docker compose up -d`
4. Verify: `docker compose logs -f api`

### Phase 4 — SSL + Nginx
1. Create Nginx config for `api.<domain>`
2. Issue certificate: `certbot --nginx -d api.<domain>`
3. Test: `curl https://api.<domain>/health` → `{"status":"ok"}`

### Phase 5 — Connect everything
1. Set `NEXT_PUBLIC_FASTAPI_URL` in Vercel, trigger redeploy
2. Set callback URL in Meta developer console: `https://api.<domain>/webhook/meta`
3. Test webhook verification (GET challenge)
4. Send test WhatsApp message, verify logs

### Phase 6 — Basic hardening
1. Configure UFW: allow 22, 80, 443; deny 8000, 6379
2. Test certificate auto-renewal: `certbot renew --dry-run`

---

## Success Criteria

- `GET https://api.<domain>/health` returns `{"status":"ok"}`
- Meta webhook verification passes (green checkmark in developer console)
- WhatsApp message triggers a response from the AI agent
- Containers restart automatically after VPS reboot
- Ports 8000 and 6379 are not reachable from the internet
