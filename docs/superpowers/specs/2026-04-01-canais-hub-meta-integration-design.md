# Canais Hub Central + Meta Official Integration

**Data:** 2026-04-01
**Status:** Aprovado
**Substitui:** 2026-03-31-multi-channel-crm-design.md (refina escopo)

## Objetivo

Consolidar a gestao de canais WhatsApp numa unica pagina (`/canais`), remover paginas e componentes fora de escopo (`/agentes`, aba WhatsApp do `/config`), e integrar o backend-evolution para receber webhooks de ambos os providers (Evolution API e Meta Cloud API oficial).

## Decisoes de Design

- **Canais e o hub central**: criar canal, escolher provider, linkar agente IA (ou nenhum), conectar
- **Pagina /agentes removida**: agent profiles sao gerenciados internamente, cliente nao edita
- **Aba WhatsApp do /config removida**: conexao QR code vive no /canais
- **Backend recebe tudo**: ambos webhooks (Evolution e Meta) chegam no backend-evolution
- **Agent profiles read-only no CRM**: dropdown para vincular ao canal, sem CRUD

---

## 1. Backend Multi-Channel

### 1.1 Webhook Endpoints

Dois endpoints novos substituem o `/webhook` atual:

**`POST /webhook/evolution`**
- Recebe payload Evolution API v2
- Extrai numero destino do payload
- Busca canal na tabela `channels` por phone + provider="evolution"
- Se canal nao encontrado ou `is_active=false` → ignora

**`POST /webhook/meta`**
- Recebe payload Meta Cloud API
- `GET /webhook/meta` responde ao challenge de verificacao (Meta envia `hub.verify_token` + `hub.challenge`)
- Valida assinatura HMAC-SHA256 do payload usando `app_secret` do canal
- Extrai `phone_number_id` do payload para identificar o canal
- Busca canal na tabela `channels` por `provider_config->phone_number_id` + provider="meta_cloud"

### 1.2 Fluxo Unificado

```
Webhook chega → identifica canal (by phone ou phone_number_id)
    → canal nao encontrado ou is_active=false → ignora
    → canal encontrado → parse mensagem (parser especifico por provider)
        → canal tem agent_profile_id → busca profile → roda agente IA
        → canal sem agent_profile_id → salva mensagem apenas (modo humano)
```

### 1.3 WhatsApp Client Multi-Provider

Abstrai o envio de mensagens por provider:

**`EvolutionClient`** — mantem logica atual:
- `send_text(to, body)` via `/message/sendText/{instance}`
- `send_image(to, url, caption)` via `/message/sendMedia/{instance}`
- `send_audio(to, url)` via `/message/sendWhatsAppAudio/{instance}`
- `mark_read(message_id, remote_jid)` via `/chat/markMessageAsRead/{instance}`

**`MetaCloudClient`** — mesmas operacoes via Meta Cloud API:
- `send_text(to, body)` via `POST /v21.0/{phone_number_id}/messages` com type=text
- `send_image(to, url, caption)` via mesma URL com type=image
- `send_audio(to, url)` via mesma URL com type=audio
- `mark_read(message_id)` via mesma URL com status=read
- Header: `Authorization: Bearer {access_token}`

**Factory function:**
```python
def get_whatsapp_client(channel: dict) -> WhatsAppClient:
    if channel["provider"] == "evolution":
        config = channel["provider_config"]
        return EvolutionClient(config["api_url"], config["api_key"], config["instance"])
    elif channel["provider"] == "meta_cloud":
        config = channel["provider_config"]
        return MetaCloudClient(config["phone_number_id"], config["access_token"])
```

### 1.4 Orchestrator Atualizado

- Recebe `channel` como contexto (alem do lead e texto)
- Usa `channel["agent_profile_id"]` para buscar o profile do banco
- Profile define: stages, prompts, model por stage, tools
- Client de envio vem do factory baseado no provider do canal
- Se `agent_profile_id` is None → nao roda orchestrator, so salva mensagem

### 1.5 Config Atualizado

Remover variaveis globais de instancia unica:
- ~~`EVOLUTION_INSTANCE`~~ (agora vem do `provider_config` de cada canal)
- ~~`EVOLUTION_API_URL`~~ (idem)
- ~~`EVOLUTION_API_KEY`~~ (idem)

Manter apenas variaveis de infra:
- `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `REDIS_URL`, `API_BASE_URL`, `FRONTEND_URL`

---

## 2. CRM Cleanup

### 2.1 Remover

| Item | Arquivo |
|------|---------|
| Pagina `/agentes` | `crm/src/app/(authenticated)/agentes/page.tsx` |
| API routes agent-profiles (POST/PUT/DELETE) | `crm/src/app/api/agent-profiles/` (manter GET) |
| Aba WhatsApp do `/config` | `crm/src/components/config/whatsapp-tab.tsx` + referencia em `config/page.tsx` |
| Item "Agentes" do sidebar | `crm/src/components/sidebar.tsx` |
| API routes Evolution globais | `crm/src/app/api/evolution/` (connect/status/disconnect globais) |

### 2.2 Manter (read-only)

| Item | Motivo |
|------|--------|
| `GET /api/agent-profiles` | Popular dropdown de agentes no modal de canal |
| `GET /api/channels` | Listagem de canais |
| CRUD `/api/channels` | Criar/editar/deletar canais |

---

## 3. Pagina Canais Refatorada

### 3.1 Listagem

Tabela com colunas:
- Nome
- Telefone (vazio para Evolution nao conectado)
- Provider (badge "Meta" ou "Evolution")
- Agente vinculado (nome do profile ou "Sem agente")
- Status conexao (conectado/desconectado — apenas Evolution)
- Ativo/Inativo (toggle)
- Acoes (editar, deletar, conectar/desconectar)

### 3.2 Modal Criar/Editar Canal

**Campos comuns:**
- Nome do canal (text)
- Provider: select "Meta Cloud API" | "Evolution API"
- Agente IA: select com profiles do banco + opcao "Nenhum (100% humano)"
- Ativo: toggle

**Campos Evolution (quando provider = evolution):**
- API URL
- API Key
- Nome da instancia

**Campos Meta (quando provider = meta_cloud):**
- Telefone (obrigatorio — ja conhecido)
- Phone Number ID
- Access Token
- App Secret
- Verify Token

### 3.3 Conexao QR Code (Evolution only)

- Botao "Conectar" na listagem para canais Evolution desconectados
- Abre modal com QR code gerado via backend
- Polling de status a cada 3s ate conectar
- Apos conectar: telefone preenchido automaticamente no canal
- Botao "Desconectar" para canais conectados

### 3.4 Webhook URL (Meta only)

- Apos criar canal Meta, exibe:
  - Webhook URL: `{backend_url}/webhook/meta`
  - Verify Token: valor do `verify_token` configurado
  - Instrucao: "Configure esta URL no Meta Developer Portal"

### 3.5 API Routes do CRM para Canais

- `GET /api/channels` — lista canais com join em agent_profiles
- `POST /api/channels` — cria canal
- `PUT /api/channels/{id}` — edita canal
- `DELETE /api/channels/{id}` — deleta canal
- `POST /api/channels/{id}/connect` — proxy: gera QR code via Evolution API do canal
- `GET /api/channels/{id}/status` — proxy: checa conexao via Evolution API do canal
- `POST /api/channels/{id}/disconnect` — proxy: desconecta via Evolution API do canal

---

## 4. Modelo de Dados

Tabelas ja existem via migration `007_multi_channel.sql`:

- **`channels`**: id, name, phone, provider, provider_config (jsonb), agent_profile_id (FK), is_active
- **`agent_profiles`**: id, name, model, stages (jsonb), base_prompt
- **`conversations`**: id, lead_id, channel_id, stage, status, last_msg_at

Nenhuma alteracao de schema necessaria.

---

## 5. Fora de Escopo

- Auth/permissoes no CRM
- CRUD de agent profiles pelo cliente
- Campanhas via Meta (ja definido no spec anterior, nao muda)
- Migrar dados existentes de instancia unica
