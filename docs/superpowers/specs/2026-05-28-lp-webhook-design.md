# Design: Webhook de Landing Pages → CRM ValerIA

**Data:** 2026-05-28  
**Status:** Aprovado  
**Domínio do CRM:** `https://crm.canastrainteligencia.com`  
**Endpoint novo:** `POST https://crm.canastrainteligencia.com/webhook/landing-page`

---

## Contexto

As landing pages da Canastra disparam webhooks em paralelo via `Promise.all()`. Atualmente um dos destinos é o n8n. O objetivo é substituir o n8n por um endpoint nativo no backend do CRM, que:

1. Salva o lead no Supabase (com email e origem)
2. Cria uma conversa na inbox da Valéria
3. Agenda disparo automático de template WhatsApp após delay configurável (padrão 15 min)
4. Permite configurar o template e o delay via interface no CRM (Configurações)

---

## Origens conhecidas das LPs

| `origem`          | Fonte                                      |
|-------------------|--------------------------------------------|
| `"graocafeteria"` | Formulário da página `/graocafeteria`      |
| `"atacado"`       | Chat WhatsApp na página `/cafeatacado`     |
| `"terceirizacao"` | Chat WhatsApp em `/terceirizacaocafe`      |
| `"Chat WhatsApp"` | Chat WhatsApp em outras páginas            |
| *(campo ausente)* | Formulário da página `/terceirizacaocafe`  |

---

## Payload recebido das LPs

```json
{
  "nome": "João Silva",
  "whatsapp": "5534999999999",
  "email": "joao@email.com",
  "timestamp": "2026-05-28T10:00:00.000Z",
  "origem": "graocafeteria"
}
```

Todos os campos exceto `origem` são sempre enviados. `email` pode ser vazio string.  
`whatsapp` pode vir em vários formatos — será normalizado para E.164 sem `+`.

---

## Arquitetura

```
LP form submit
  → POST /webhook/landing-page
  → normalize_phone(whatsapp)
  → get_or_create_lead(phone, name)   ← leads.service existente
  → update lead: email, metadata.origem
  → get_or_create_conversation(lead_id, valeria_channel_id)
  → insert follow_up_jobs (job_type='lp_welcome', fire_at=now+delay)
  → [scheduler tick] → MetaCloudClient.send_template() → mark sent
```

---

## Componentes

### 1. Novo módulo `backend/app/lp_webhook/`

#### `router.py`

| Método | Path                        | Descrição                                     |
|--------|-----------------------------|-----------------------------------------------|
| POST   | `/webhook/landing-page`     | Recebe payload da LP. Sem autenticação.       |
| GET    | `/api/lp-webhook/settings`  | Retorna config atual (do Redis).              |
| PUT    | `/api/lp-webhook/settings`  | Salva config no Redis.                        |

**Response de sucesso do POST:**
```json
{ "ok": true, "lead_id": "uuid", "conversation_id": "uuid" }
```

**Response de erro (ex: telefone inválido):**
```json
{ "ok": false, "error": "Telefone inválido" }
```
> Retorna sempre HTTP 200 para não derrubar o fluxo da LP (o usuário é redirecionado independentemente).

#### `service.py` — `process_landing_page_lead(payload, redis)`

1. `normalize_phone(payload.whatsapp)` — usa `leads.service.normalize_phone`
2. `get_or_create_lead(phone, name=payload.nome)` — upsert no Supabase
3. Atualiza `leads.email` se fornecido
4. Atualiza `leads.metadata` adicionando `{"origem": payload.origem}` (merge com metadata existente)
5. Lê config do Redis (`lp_webhook:config`)
6. `get_or_create_conversation(lead_id, config.channel_id)`
7. Insere `follow_up_jobs` com `job_type='lp_welcome'`

### 2. `follow_up_jobs` — novo `job_type='lp_welcome'`

Job inserido com:
```json
{
  "conversation_id": "...",
  "lead_id": "...",
  "channel_id": "...",
  "sequence": 1,
  "fire_at": "<now + delay_minutes>",
  "status": "pending",
  "env_tag": "production",
  "job_type": "lp_welcome",
  "metadata": {
    "lead_phone": "5534999999999",
    "template_name": "boas_vindas_lp",
    "language_code": "pt_BR"
  }
}
```

Handler no `follow_up/scheduler.py`:
- Extrai `template_name`, `language_code`, `lead_phone` do `metadata`
- Busca canal pelo `channel_id` do job
- `MetaCloudClient(channel.provider_config).send_template(lead_phone, template_name, language_code)`
- Marca `sent`. Em falha: não marca (retry no próximo tick).
- Sem guard de janela 24h (lead novo, nunca interagiu).

### 3. Settings no Redis

Chave: `lp_webhook:config`  
Valor (JSON string):
```json
{
  "channel_id": "uuid-da-valeria",
  "template_name": "boas_vindas_lp",
  "language_code": "pt_BR",
  "delay_minutes": 15
}
```

Default quando não configurado:
- `delay_minutes`: 15
- `language_code`: `"pt_BR"`
- `template_name`: `""` (jobs não serão criados enquanto não configurado)
- `channel_id`: `""` (jobs não serão criados enquanto não configurado)

### 4. Frontend — Configurações

Nova seção **"Webhook de Landing Pages"** na página de Configurações:
- Dropdown **Canal** — lista canais do Supabase (`GET /api/channels`)
- Input **Nome do template** — texto livre (ex: `boas_vindas_lp`)
- Input **Language code** — texto, default `pt_BR`
- Stepper/input numérico **Delay (minutos)** — default `15`
- Botão **Salvar**
- Feedback visual de sucesso/erro após salvar

---

## Registro no `main.py`

```python
from app.lp_webhook.router import router as lp_webhook_router
app.include_router(lp_webhook_router)
```

---

## Tratamento de erros

| Situação                        | Comportamento                                          |
|---------------------------------|--------------------------------------------------------|
| Telefone vazio ou inválido      | Log warning, retorna `{"ok": false}` com HTTP 200     |
| Settings não configuradas       | Salva lead/conversa, mas **não** cria job             |
| Falha no Supabase               | Log error, retorna `{"ok": false}` com HTTP 200       |
| Template falha no envio         | Job não marcado como sent → retry automático           |
| Lead já existe                  | `get_or_create_lead` faz upsert, sem duplicação       |

---

## Arquivo de handoff para agente das LPs

Será gerado em `docs/lp-webhook-integration.md` com:
- Endpoint correto, domínio e payload esperado
- Instrução para remover URL do n8n e adicionar URL do CRM
- Descrição dos campos obrigatórios/opcionais
- Exemplos de código

---

## Fora do escopo

- Autenticação no endpoint (adicionada futuramente)
- Dropdown de templates sincronizados da Meta API (usa input livre por agora)
- Múltiplas configurações por origem da LP
