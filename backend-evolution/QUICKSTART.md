# ValerIA - Backend Evolution API - Quickstart

## Pre-requisitos

- Python 3.12+
- Redis rodando (local ou Docker)
- Evolution API v2.x rodando na sua VPS
- Conta OpenAI com API key
- Projeto Supabase com as tabelas criadas

## 1. Instalar dependencias

```bash
cd backend-evolution
pip install -r requirements.txt
```

## 2. Configurar .env

Copie o arquivo de exemplo e preencha com suas credenciais:

```bash
cp .env.example .env
```

Edite o `.env`:

```env
# Evolution API - preencha com os dados da sua instancia
EVOLUTION_API_URL=https://sua-evolution.seudominio.com
EVOLUTION_API_KEY=sua-api-key-aqui
EVOLUTION_INSTANCE=nome-da-sua-instancia

# OpenAI
OPENAI_API_KEY=sk-...

# Supabase
SUPABASE_URL=https://seu-projeto.supabase.co
SUPABASE_SERVICE_KEY=eyJ...

# Redis (padrao localhost)
REDIS_URL=redis://localhost:6379
```

## 3. Criar tabelas no Supabase

Execute este SQL no Supabase SQL Editor:

```sql
CREATE TABLE IF NOT EXISTS leads (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    email TEXT,
    status TEXT DEFAULT 'active',
    stage TEXT DEFAULT 'novo',
    notes TEXT,
    tags TEXT[] DEFAULT '{}',
    last_msg_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    lead_id UUID REFERENCES leads(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

## 4. Iniciar Redis

Se voce nao tem Redis rodando:

```bash
# Com Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Ou instale localmente
# Linux: sudo apt install redis-server
# Mac: brew install redis
```

## 5. Iniciar o backend

```bash
cd backend-evolution
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Voce deve ver:

```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

Teste: acesse `http://localhost:8000/health` — deve retornar `{"status":"ok"}`

## 6. Expor o backend para a internet

A Evolution API precisa enviar webhooks para o seu backend. Se esta rodando local, use ngrok ou similar:

```bash
ngrok http 8000
```

Anote a URL publica (ex: `https://abc123.ngrok-free.app`)

Se o backend roda no mesmo servidor da Evolution, use a URL local diretamente.

## 7. Configurar webhook na Evolution API

Na interface da Evolution API (ou via curl), configure o webhook da sua instancia:

```bash
curl -X POST "https://sua-evolution.seudominio.com/webhook/set/NOME-DA-INSTANCIA" \
  -H "apikey: SUA-API-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://abc123.ngrok-free.app/webhook",
    "webhook_by_events": false,
    "webhook_base64": false,
    "events": [
      "MESSAGES_UPSERT"
    ]
  }'
```

Substitua:
- `NOME-DA-INSTANCIA` pelo nome da sua instancia Evolution
- `SUA-API-KEY` pela sua API key
- A URL do webhook pela URL publica do seu backend

## 8. Testar

Envie uma mensagem no WhatsApp para o numero conectado na sua instancia Evolution. Voce deve ver nos logs do backend:

```
INFO  Webhook event: messages.upsert
INFO  Message from 5534999999999 (Joao): type=text, text=oi
INFO  Buffer started for 5534999999999: 15s
```

Apos ~15 segundos (buffer timeout), a ValerIA processa e responde automaticamente.

## Rodar testes

```bash
cd backend-evolution
python -m pytest tests/ -v
```

## Estrutura

```
backend-evolution/
├── app/
│   ├── main.py              # FastAPI app
│   ├── config.py             # Settings (Evolution env vars)
│   ├── webhook/
│   │   ├── router.py         # POST /webhook
│   │   └── parser.py         # Parse Evolution MESSAGES_UPSERT
│   ├── whatsapp/
│   │   ├── client.py         # Evolution API: send_text, send_image, mark_read
│   │   └── media.py          # Download media + transcribe/describe
│   ├── buffer/
│   │   ├── manager.py        # Redis buffer adaptativo (15s base, +10s/msg, 45s max)
│   │   └── processor.py      # Resolve media, run agent, humanize, send
│   ├── agent/
│   │   ├── orchestrator.py   # GPT-4.1 single-agent com dynamic prompts
│   │   ├── prompts.py        # Prompts por stage do lead
│   │   └── tools.py          # Tools do agent (buscar catalogo, etc)
│   ├── humanizer/
│   │   ├── splitter.py       # Split resposta em bubbles
│   │   └── typing.py         # Simula delay de digitacao
│   ├── leads/
│   │   ├── service.py        # CRUD leads no Supabase
│   │   └── router.py         # API REST leads
│   └── campaign/
│       ├── importer.py       # Import CSV de leads
│       ├── router.py         # API import
│       └── worker.py         # Disparo em lote
├── tests/
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```
