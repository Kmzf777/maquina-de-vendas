# ValerIA - Agente de IA Multi-Agent para WhatsApp (Meta Cloud API)

**Data:** 2026-03-23
**Status:** Aprovado
**Stack:** Python (FastAPI) + Redis + Supabase + OpenAI + React/Tailwind (Vercel)

---

## 1. Visao Geral

ValerIA e um agente de IA para WhatsApp que opera via Meta Cloud API (API oficial). O sistema:

- **Envia mensagens ativas** (templates aprovados pela Meta) para listas de leads importadas
- **Atende leads automaticamente** via agente orquestrador com prompts dinamicos por stage
- **Humaniza respostas** com buffer de mensagens, fragmentacao em bolhas, simulacao de digitacao
- **Gerencia campanhas** atraves de um painel web simples

### Arquitetura: Agente Unico com Roteamento por Contexto

Em vez de 5 agentes separados (como no n8n anterior), um unico agente orquestrador carrega o system prompt dinamicamente baseado no `stage` do lead. Isso resolve:

- **Historico unificado** - o agente de atacado sabe o que a secretaria conversou
- **Re-roteamento natural** - se o lead muda de ideia, troca o stage e o prompt muda
- **Pipeline unica** de humanizacao e envio
- **Mais simples** de manter e debugar

---

## 2. Arquitetura

```
+---------------------------+     +------------------------------------+
|   Frontend (Vercel)       |     |         VPS (Docker)               |
|   React + Tailwind        |     |                                    |
|                           |     |  +-----------+  +-----------+      |
|  - Gerenciar templates    |---->|  |  FastAPI   |  |  Redis    |      |
|  - Importar listas        |     |  |  (Backend) |  |  (Buffer) |      |
|  - Dashboard de leads     |     |  +-----+-----+  +-----------+      |
|                           |     |        |                            |
+---------------------------+     |        v                            |
                                  |  +-----------+                      |
                                  |  |  Worker    |                     |
                                  |  |  (Disparos)|                     |
                                  |  +-----------+                      |
                                  +------------------------------------+
                                           |
                            +--------------+--------------+
                            v              v              v
                     +----------+  +--------------+  +----------+
                     | Meta     |  |  Supabase    |  | OpenAI   |
                     | WhatsApp |  |  (Leads +    |  | API      |
                     | Cloud API|  |   Memoria)   |  |          |
                     +----------+  +--------------+  +----------+
```

### Componentes

| Componente | Responsabilidade |
|---|---|
| **FastAPI** | Recebe webhooks da Meta, processa mensagens, gerencia agentes, API pro frontend |
| **Redis** | Buffer de mensagens (acumula msgs rapidas), filas de disparo |
| **Worker** | Processa filas de disparo ativo (envia templates em lote com rate limiting) |
| **Supabase** | Tabela de leads, historico de conversas, status de campanhas |
| **Meta Cloud API** | Envio/recebimento de mensagens WhatsApp |
| **OpenAI** | GPT-4.1 para agente orquestrador, Whisper para audio, Vision para imagens |
| **Frontend** | Painel para gerenciar templates, importar listas, visualizar leads |

---

## 3. Fluxo de Mensagens (Receptivo)

```
Lead envia mensagem no WhatsApp
          |
          v
   Meta Webhook (POST /webhook)
          |
          v
   Identifica tipo de midia
   +- Texto -> usa direto
   +- Audio -> Whisper transcricao
   +- Imagem -> GPT-4o Vision descricao
          |
          v
   Busca/Cria lead no Supabase
          |
          v
   +- Buffer (Redis) --------------------------+
   |                                            |
   |  PUSH mensagem na lista do lead            |
   |                                            |
   |  Primeiro msg? -> Agenda timer             |
   |  Msg seguinte? -> Reseta timer (+10s)      |
   |                                            |
   |  Timer expira:                             |
   |  -> GET todas msgs acumuladas              |
   |  -> Junta em texto unico                   |
   |  -> DELETE buffer                          |
   +--------------------------------------------+
          |
          v
   Carrega stage do lead (Supabase)
          |
          v
   Monta prompt dinamico:
   +- System prompt do stage atual
   +- Historico de conversa (Supabase)
   +- Mensagem combinada do buffer
          |
          v
   OpenAI GPT-4.1 (com tools)
          |
          v
   Processa tool calls (se houver):
   +- salvar_nome -> PATCH Supabase
   +- mudar_stage -> PATCH Supabase
   +- encaminhar_humano -> notifica vendedor
   +- enviar_fotos -> envia imagens
          |
          v
   +- Humanizacao ----------------------------+
   |                                           |
   |  1. Split por \n\n -> array de msgs       |
   |  2. Para cada msg:                        |
   |     - POST typing indicator               |
   |     - Calcula delay de digitacao           |
   |       (chars x 25-80ms + pausa 300-800ms) |
   |     - Aguarda delay                        |
   |     - Envia mensagem via Meta API          |
   +-------------------------------------------+
          |
          v
   Atualiza last_msg no Supabase
```

### Buffer inteligente (melhoria vs n8n)

O n8n usava timers fixos (30-60s, 20-50s, 20-40s). O novo buffer usa expiracao adaptativa:

- **Timer base:** 15 segundos
- **Se o lead manda outra msg:** timer reseta para +10s (ate maximo 45s)
- **Resultado:** espera o lead terminar de digitar, nao um tempo arbitrario

Implementacao com Redis:
- `buffer:{phone}` -> lista de mensagens (RPUSH)
- `buffer:{phone}:lock` -> flag indicando que um timer ja esta ativo
- Quando o timer expira, um callback processa o lote

---

## 4. Fluxo de Mensagens Ativas (Templates)

### Meta Cloud API - regras de templates

- Toda conversa iniciada pela empresa comeca com template aprovado
- Apos o lead responder, janela de 24h aberta para mensagens livres
- Templates precisam de aprovacao da Meta (categoria MARKETING ou UTILITY)

### Fluxo de disparo

```
Frontend: criar campanha (template + CSV)
          |
          v
   POST /api/campaigns -> FastAPI
          |
          v
   Importa CSV: valida numeros, cria leads no Supabase
   Enfileira no Redis (fila: campaign:{id})
          |
          v
   Worker consome fila:
   - Respeita rate limit da Meta (80 msg/seg tier basico)
   - Intervalo configuravel entre msgs (ex: 3-8 seg)
   - Envia template via Cloud API
   - Atualiza status no Supabase (enviado/falhou/entregue)
```

### Ciclo de vida do lead

```
1. Importado          -> status: "imported", stage: null
2. Template enviado   -> status: "template_sent", stage: null
3. Lead responde      -> status: "active", stage: "secretaria"
                         Janela 24h aberta, agente assume
4. Conversa segue     -> stage: "secretaria" -> "atacado" (etc)
5. Janela expira      -> status: "window_expired"
                         Pode reagendar novo template
```

---

## 5. Sistema de Humanizacao

### Camada 1: Escrita que parece humana

- **Minusculas sempre** - parece WhatsApp real sem ser desleixado
- **Fragmentacao por \n\n** - cada \n\n vira uma bolha separada, 2-5 bolhas por turno
- **Frases curtas** - 5-15 palavras por bolha
- **Sem emojis** - diferenciador de bot
- **Pontuacao natural** - virgulas e pontos normais

### Camada 2: Tom profissional gente boa

O agente e um vendedor amigavel e profissional. Nao e colega de bar, nao e robo corporativo.

**Exemplos do tom correto:**

```
oi, tudo bem? aqui e a valeria, da cafe canastra

vi que voce demonstrou interesse nos nossos cafes, queria entender melhor o que voce procura

voce trabalha com revenda ou seria pra consumo proprio?
```

```
perfeito, trabalho com atacado faz um bom tempo ja

a gente tem uma linha bem completa, desde o classico ate microlotes especiais

me conta um pouco do seu negocio que eu te direciono pro que faz mais sentido
```

**Vocabulario:**
- Usa: "perfeito", "com certeza", "otimo", "bacana", "entendo perfeitamente"
- Nao usa: "kk", "show", "massa", gírias excessivas, alongamentos ("seriooo")
- Contrações naturais: "to", "pra", "pro", "voce" ou "vc" (alternar)

### Camada 3: Regras de conversacao

1. **Uma pergunta por turno** - maximo uma, nunca duas. Escolhe a mais importante
2. **Nunca repetir perguntas ja feitas** - checa historico inteiro antes
3. **Consciencia total do historico** - nunca ignora o que foi dito
4. **Responder ao que foi dito primeiro** - sempre reage antes de avancar
5. **O cliente conduz o ritmo** - sem pressa, sem forcar

### Camada 4: Buffer + Typing (tecnico)

```
Mensagem chega -> Buffer Redis (acumula)
                      |
              Timer expira (adaptativo 15-45s)
                      |
              Texto combinado -> OpenAI
                      |
              Resposta da IA
                      |
              Split por \n\n -> ["msg1", "msg2", "msg3"]
                      |
              Para cada bolha:
              +- POST typing indicator
              +- await delay(chars x randInt(25,80)ms + randInt(300,800)ms)
              +- POST mensagem via Meta API
```

### Camada 5: Anti-deteccao de bot

- **Variacao de tempo de resposta** - nao responde sempre no mesmo intervalo
- **Variacao de tamanho** - alterna respostas curtas e medias
- **Horario comercial** - fora do horario, delay grande simulando "vi agora"
- **Se chamam de bot** - "imagina, sou eu mesma aqui do escritorio. qualquer duvida posso mandar um audio"

---

## 6. Agente Orquestrador

### Prompt dinamico por stage

O system prompt e montado em runtime combinando:

1. **Base** - identidade, regras de humanizacao, formato de escrita, checklist
2. **Contexto** - data, saudacao, nome do lead, empresa
3. **Stage** - funil especifico do stage atual (secretaria, atacado, etc)
4. **Catalogo** - produtos e precos (apenas nos stages que precisam)

### Stages e funis

**SECRETARIA (stage inicial)**
- Modelo: GPT-4.1
- Objetivo: rapport, identificar necessidade, classificar e redirecionar
- Funil: saudacao -> diagnostico -> qualificacao -> mudar_stage silencioso
- Tools: salvar_nome, mudar_stage

**ATACADO (stage 2)**
- Modelo: GPT-4.1
- Objetivo: vender cafe no atacado (B2B)
- Funil: diagnostico de dor -> apresentacao de produto -> precos/frete -> encaminhar humano
- Tools: encaminhar_humano, enviar_fotos, salvar_nome, mudar_stage
- Catalogo completo com precos e tabela de frete

**PRIVATE LABEL (stage 3)**
- Modelo: GPT-4.1
- Objetivo: vender servico de marca propria
- Funil: explicar private label -> precos -> interesse -> encaminhar supervisor
- Tools: encaminhar_humano, enviar_fotos, salvar_nome, mudar_stage
- Catalogo private label com precos

**EXPORTACAO (stage 4)**
- Modelo: GPT-4.1-mini
- Objetivo: qualificar leads de exportacao
- Funil: pais alvo -> experiencia com exportacao -> objetivo -> encaminhar equipe
- Tools: encaminhar_humano, salvar_nome, mudar_stage

**CONSUMO (stage 5)**
- Modelo: GPT-4.1-mini
- Objetivo: redirecionar pra loja online
- Funil: cupom de desconto + link da loja
- Tools: salvar_nome

### Tools do agente

```python
tools = [
    {
        "name": "salvar_nome",
        "description": "Salva o nome do lead quando descoberto na conversa",
        "parameters": {"name": "string"}
    },
    {
        "name": "mudar_stage",
        "description": "Transfere o lead para outro stage quando identificada a necessidade",
        "parameters": {"stage": "atacado | private_label | exportacao | consumo | secretaria"}
    },
    {
        "name": "encaminhar_humano",
        "description": "Encaminha o lead para um vendedor humano quando qualificado",
        "parameters": {"vendedor": "string", "motivo": "string"}
    },
    {
        "name": "enviar_fotos",
        "description": "Envia catalogo de fotos dos produtos",
        "parameters": {"categoria": "atacado | private_label"}
    }
]
```

---

## 7. Banco de Dados (Supabase)

### Tabelas

```sql
-- Leads
CREATE TABLE leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    phone text UNIQUE NOT NULL,
    name text,
    company text,
    stage text DEFAULT 'pending',
    status text DEFAULT 'imported',
    campaign_id uuid REFERENCES campaigns(id),
    last_msg_at timestamptz,
    created_at timestamptz DEFAULT now()
);

-- Historico de conversa (unificado, todos os stages)
CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    role text NOT NULL,
    content text NOT NULL,
    stage text,
    created_at timestamptz DEFAULT now()
);

-- Campanhas de disparo
CREATE TABLE campaigns (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    template_name text NOT NULL,
    template_params jsonb,
    total_leads int DEFAULT 0,
    sent int DEFAULT 0,
    failed int DEFAULT 0,
    replied int DEFAULT 0,
    status text DEFAULT 'draft',
    send_interval_min int DEFAULT 3,
    send_interval_max int DEFAULT 8,
    created_at timestamptz DEFAULT now()
);

-- Templates (espelho dos aprovados na Meta)
CREATE TABLE templates (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    meta_id text,
    name text NOT NULL,
    language text DEFAULT 'pt_BR',
    category text,
    body_text text,
    status text,
    synced_at timestamptz
);

-- Index
CREATE INDEX idx_leads_phone ON leads(phone);
CREATE INDEX idx_leads_status ON leads(status);
CREATE INDEX idx_messages_lead_id ON messages(lead_id);
CREATE INDEX idx_messages_created ON messages(created_at);
```

### Campos de stage e status

**stage:** `pending` | `secretaria` | `atacado` | `private_label` | `exportacao` | `consumo`
**status:** `imported` | `template_sent` | `active` | `converted` | `window_expired`

---

## 8. Meta Cloud API - Integracao

### Webhook de recebimento

```
GET  /webhook  -> verificacao do webhook (hub.verify_token)
POST /webhook  -> recebe mensagens, status updates, etc
```

### Payload da Meta (mensagem recebida)

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "value": {
        "messages": [{
          "from": "5534999999999",
          "type": "text|image|audio",
          "text": {"body": "mensagem"},
          "timestamp": "1234567890"
        }],
        "metadata": {
          "phone_number_id": "ID_DO_NUMERO"
        }
      }
    }]
  }]
}
```

### Envio de mensagens

```python
# Mensagem de texto
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
{
    "messaging_product": "whatsapp",
    "to": "5534999999999",
    "type": "text",
    "text": {"body": "mensagem aqui"}
}

# Template
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
{
    "messaging_product": "whatsapp",
    "to": "5534999999999",
    "type": "template",
    "template": {
        "name": "nome_do_template",
        "language": {"code": "pt_BR"},
        "components": [...]
    }
}

# Typing indicator
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
{
    "messaging_product": "whatsapp",
    "to": "5534999999999",
    "status": "typing"
}

# Marcar como lida
POST https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages
{
    "messaging_product": "whatsapp",
    "message_id": "wamid.xxx",
    "status": "read"
}
```

---

## 9. Estrutura de Pastas

```
valeria/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── webhook/
│   │   │   ├── router.py
│   │   │   ├── verify.py
│   │   │   └── parser.py
│   │   │
│   │   ├── buffer/
│   │   │   ├── manager.py
│   │   │   └── processor.py
│   │   │
│   │   ├── agent/
│   │   │   ├── orchestrator.py
│   │   │   ├── prompts/
│   │   │   │   ├── base.py
│   │   │   │   ├── secretaria.py
│   │   │   │   ├── atacado.py
│   │   │   │   ├── private_label.py
│   │   │   │   ├── exportacao.py
│   │   │   │   └── consumo.py
│   │   │   └── tools.py
│   │   │
│   │   ├── humanizer/
│   │   │   ├── splitter.py
│   │   │   └── typing.py
│   │   │
│   │   ├── whatsapp/
│   │   │   ├── client.py
│   │   │   └── media.py
│   │   │
│   │   ├── campaign/
│   │   │   ├── router.py
│   │   │   ├── worker.py
│   │   │   └── importer.py
│   │   │
│   │   ├── leads/
│   │   │   ├── router.py
│   │   │   └── service.py
│   │   │
│   │   └── db/
│   │       └── supabase.py
│   │
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Templates.tsx
│   │   │   ├── Campaigns.tsx
│   │   │   └── Leads.tsx
│   │   ├── components/
│   │   │   ├── CsvUploader.tsx
│   │   │   ├── LeadTable.tsx
│   │   │   └── CampaignProgress.tsx
│   │   ├── api/
│   │   │   └── client.ts
│   │   └── App.tsx
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
│
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-23-valeria-whatsapp-agent-design.md
```

---

## 10. Deploy

### Docker Compose (VPS)

```yaml
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - redis
    restart: unless-stopped

  worker:
    build: ./backend
    command: python -m app.campaign.worker
    env_file: .env
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

### Variaveis de ambiente

```env
# Meta WhatsApp
META_PHONE_NUMBER_ID=
META_ACCESS_TOKEN=
META_VERIFY_TOKEN=
META_APP_SECRET=

# OpenAI
OPENAI_API_KEY=

# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=

# Redis
REDIS_URL=redis://redis:6379

# App
API_BASE_URL=
FRONTEND_URL=
```

### Frontend (Vercel)

- Deploy automatico via GitHub
- Variavel de ambiente: `VITE_API_URL` apontando para o backend na VPS

---

## 11. Melhorias vs Sistema n8n Anterior

| Problema no n8n | Solucao no ValerIA |
|---|---|
| Roteamento fragil da Secretaria | Re-roteamento via tool `mudar_stage` em qualquer direcao |
| Sem re-roteamento | Qualquer stage pode chamar `mudar_stage` para corrigir |
| Buffer com timers fixos | Buffer adaptativo (15s base, reseta +10s, max 45s) |
| Sub-agentes via webhooks internos | Agente unico com prompt dinamico |
| Historico fragmentado por agente | Tabela `messages` unificada |
| Sem controle de qualidade | Logs estruturados, historico auditavel |
| Sem mensagens ativas | Campanhas com templates Meta + worker de disparo |
| Evolution API (nao-oficial) | Meta Cloud API (oficial) |
