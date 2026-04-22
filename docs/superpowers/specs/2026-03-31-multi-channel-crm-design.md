# Multi-Channel CRM com Dual Provider (Meta Cloud + Evolution)

**Data:** 2026-03-31
**Status:** Aprovado

## Objetivo

Transformar o backend da ValerIA num CRM base multi-número e multi-provider. Qualquer número de WhatsApp pode ser cadastrado como channel, conectado via Meta Cloud API ou Evolution API, com ou sem agente de IA. Campanhas ficam restritas a channels Meta Cloud.

## Decisões de Design

- **Provider por channel**: cada número escolhe seu provider (Meta Cloud ou Evolution)
- **Perfis de agente reutilizáveis**: cria perfis com stages/prompts/tools e atribui a channels
- **Lead global, conversa por channel**: lead único por telefone, conversation isolada por lead+channel
- **Campanhas só Meta Cloud**: validação no backend ao criar campanha
- **Sem auth por agora**: acesso aberto ao CRM, estrutura preparada pra auth futuro

---

## 1. Modelo de Dados

### 1.1 `channels`

Entidade central — um número de WhatsApp conectado.

```sql
CREATE TABLE channels (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    phone text NOT NULL UNIQUE,
    provider text NOT NULL,                -- 'meta_cloud' | 'evolution'
    provider_config jsonb NOT NULL,
    agent_profile_id uuid REFERENCES agent_profiles(id),
    is_active boolean DEFAULT true,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_channels_phone ON channels(phone);
CREATE INDEX idx_channels_provider ON channels(provider);
```

**`provider_config` por tipo:**

Meta Cloud:
```json
{
  "phone_number_id": "...",
  "access_token": "...",
  "app_secret": "...",
  "verify_token": "..."
}
```

Evolution:
```json
{
  "api_url": "...",
  "api_key": "...",
  "instance": "..."
}
```

### 1.2 `agent_profiles`

Perfis de agente reutilizáveis.

```sql
CREATE TABLE agent_profiles (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    model text NOT NULL DEFAULT 'gpt-4.1',
    stages jsonb NOT NULL,
    base_prompt text NOT NULL,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
```

**`stages` JSON:**
```json
{
  "secretaria": {
    "prompt": "Você é a secretária da empresa...",
    "model": "gpt-4.1",
    "tools": ["salvar_nome", "mudar_stage"]
  },
  "atacado": {
    "prompt": "Você atende clientes B2B...",
    "model": "gpt-4.1",
    "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos"]
  }
}
```

### 1.3 `conversations`

Conversa = lead + channel. Stage e status por conversa, não por lead.

```sql
CREATE TABLE conversations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id uuid REFERENCES leads(id) ON DELETE CASCADE,
    channel_id uuid REFERENCES channels(id) ON DELETE CASCADE,
    stage text DEFAULT 'secretaria',
    status text DEFAULT 'active',          -- active | converted | paused | closed
    campaign_id uuid REFERENCES campaigns(id),
    last_msg_at timestamptz,
    created_at timestamptz DEFAULT now(),
    UNIQUE(lead_id, channel_id)
);

CREATE INDEX idx_conversations_channel ON conversations(channel_id);
CREATE INDEX idx_conversations_lead ON conversations(lead_id);
CREATE INDEX idx_conversations_status ON conversations(status);
```

### 1.4 Ajustes em tabelas existentes

**`leads`** — simplifica (remove stage, status, campaign_id):
```sql
-- Mantém: id, phone, name, company, created_at
-- Remove: stage, status, campaign_id (migram pra conversations)
-- Adiciona:
ALTER TABLE leads ADD COLUMN metadata jsonb DEFAULT '{}';
```

**`messages`** — referencia conversation em vez de lead:
```sql
-- Antes:  lead_id uuid REFERENCES leads(id)
-- Depois: conversation_id uuid REFERENCES conversations(id)
ALTER TABLE messages ADD COLUMN conversation_id uuid REFERENCES conversations(id);
-- Manter lead_id temporariamente para migração, depois remover
```

**`campaigns`** — vincula a channel:
```sql
ALTER TABLE campaigns ADD COLUMN channel_id uuid REFERENCES channels(id);
```

**`templates`** — vincula a channel:
```sql
ALTER TABLE templates ADD COLUMN channel_id uuid REFERENCES channels(id);
```

---

## 2. Provider Abstraction Layer

### 2.1 Interface base

```python
# providers/base.py
class WhatsAppProvider(ABC):

    @abstractmethod
    async def send_text(self, to: str, body: str) -> str:
        """Envia texto, retorna message_id"""

    @abstractmethod
    async def send_template(self, to: str, template_name: str,
                            components: list, language: str = "pt_BR") -> str:
        """Envia template — só MetaCloudProvider implementa"""

    @abstractmethod
    async def send_image(self, to: str, image_url: str, caption: str = None) -> str:
        """Envia imagem"""

    @abstractmethod
    async def mark_read(self, message_id: str) -> None:
        """Marca como lido"""

    @abstractmethod
    async def download_media(self, media_id: str) -> bytes:
        """Baixa mídia por ID"""
```

### 2.2 Implementações

**`MetaCloudProvider`** — adapta código atual de `/backend/app/whatsapp/client.py`. Recebe credenciais do `provider_config` do channel.

**`EvolutionProvider`** — adapta código de `/backend-evolution/`. Recebe credenciais do `provider_config` do channel. `send_template()` levanta `NotImplementedError`.

### 2.3 Resolução

```python
# channels/service.py
def get_provider(channel: Channel) -> WhatsAppProvider:
    if channel.provider == "meta_cloud":
        return MetaCloudProvider(channel.provider_config)
    elif channel.provider == "evolution":
        return EvolutionProvider(channel.provider_config)
    raise ValueError(f"Provider desconhecido: {channel.provider}")
```

---

## 3. Webhook Routing

### 3.1 Meta Cloud

Um endpoint para todos os números Meta. O `phone_number_id` no payload identifica o channel.

```
POST /webhook/meta
  → extrai phone_number_id do payload
  → busca channel por phone_number_id no provider_config
  → roteia pro pipeline
```

```
GET /webhook/meta
  → verificação do webhook (hub.verify_token)
  → cada channel Meta tem seu verify_token no provider_config
```

### 3.2 Evolution

Endpoint por channel. Cada instância Evolution registra seu webhook apontando pra cá.

```
POST /webhook/evolution/{channel_id}
  → channel_id identifica o canal
  → roteia pro pipeline
```

### 3.3 Pipeline unificado

```
Webhook → Identifica Channel → Get/Create Lead → Get/Create Conversation
  → channel tem agent_profile?
     SIM → Buffer → Agent → Humanize → Send (via provider do channel)
     NÃO → Salva mensagem → Notifica CRM (chat humano via Supabase Realtime)
```

---

## 4. Agent System

### 4.1 Carregamento dinâmico

O orchestrator não usa mais prompts hardcoded. Carrega do `agent_profile` vinculado ao channel:

```python
async def run_agent(conversation: Conversation, messages: list):
    channel = conversation.channel
    profile = channel.agent_profile

    if not profile:
        return None  # sem agente, chat humano

    stage_config = profile.stages[conversation.stage]
    system_prompt = profile.base_prompt + "\n\n" + stage_config["prompt"]
    model = stage_config.get("model", profile.model)
    tools = resolve_tools(stage_config["tools"])

    # ... chamada OpenAI igual ao atual
```

### 4.2 Tools

Tools continuam as mesmas (`salvar_nome`, `mudar_stage`, `encaminhar_humano`, `enviar_fotos`) mas operam sobre `conversation` em vez de `lead`:
- `mudar_stage` → atualiza `conversation.stage`
- `encaminhar_humano` → atualiza `conversation.status = 'converted'`
- `salvar_nome` → atualiza `lead.name` (dado global)

---

## 5. Campanhas

### 5.1 Vinculação a channel

Campanha pertence a um channel. Validação: `channel.provider == 'meta_cloud'`.

### 5.2 Worker

Resolve provider do channel da campanha para enviar templates:
```python
provider = get_provider(campaign.channel)
await provider.send_template(to, template_name, components)
```

### 5.3 Import de leads

CSV import cria:
1. Lead global (get_or_create por phone)
2. Conversation vinculada ao channel da campanha (status = 'imported')

### 5.4 Templates por channel

Cada channel Meta Cloud tem seus próprios templates. Sync de templates é por channel.

---

## 6. CRM Frontend

### 6.1 Novas páginas

- **`/canais`** — CRUD de channels. Cadastra número, escolhe provider, configura credenciais, atribui perfil de agente. Status de conexão.
- **`/agentes`** — CRUD de agent_profiles. Editor de stages, prompts, tools, modelo.

### 6.2 Páginas ajustadas

- **`/conversas`** — filtro por channel. Chat humano funciona pra qualquer channel. Mostra de qual número é a conversa.
- **`/campanhas`** — ao criar, seleciona channel (só Meta Cloud). Templates filtrados por channel.
- **`/leads`** — lead global. Badge com conversas ativas. Detalhe mostra conversas separadas por channel.
- **`/dashboard`** — métricas por channel ou consolidadas.

### 6.3 Chat humano em tempo real

Mensagens em channels sem agente → salvam no histórico → Supabase Realtime notifica CRM → vendedor responde pelo `/conversas` → resposta sai via provider do channel.

---

## 7. Estrutura de Diretórios (Backend)

```
backend/
  app/
    providers/
      __init__.py
      base.py
      meta_cloud.py
      evolution.py
    channels/
      __init__.py
      models.py
      router.py
      service.py
    agent_profiles/
      __init__.py
      models.py
      router.py
    conversations/
      __init__.py
      models.py
      router.py
      service.py
    campaigns/          (ajustado)
    leads/              (simplificado)
    webhook/            (meta + evolution routing)
    buffer/             (sem mudança)
    agent/              (carrega de agent_profile)
    humanizer/          (sem mudança)
  migrations/
    007_multi_channel.sql
```

---

## 8. Regras de Negócio

1. **Channel sem agent_profile** = chat humano puro
2. **Channel com agent_profile** = IA responde automaticamente
3. **Campanhas** = só channels `meta_cloud`
4. **Lead** = 1 por telefone, global
5. **Conversation** = 1 por lead+channel, stage/status isolados
6. **Templates** = por channel (cada WABA tem seus templates)
7. **Sem limite de números** = quantos channels quiser
