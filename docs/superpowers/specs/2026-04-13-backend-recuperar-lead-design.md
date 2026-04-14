# Design: backend-recuperar-lead — SDR Agent Proativo

**Data:** 2026-04-13
**Branch:** feature/crm-template-dispatcher
**Status:** Aprovado para implementação

---

## Contexto

O `backend/` em produção atende leads reativos (lead inicia contato). O `backend-evolution` é a versão evoluída com multi-stage e prompts ricos, mas ainda reativo. O `backend-recuperar-lead` é um terceiro serviço — um SDR proativo que:

1. Recebe um disparo manual do vendedor (via futura integração CRM)
2. Envia um template Meta aprovado ao lead ocioso
3. Quando o lead responde, o agent assume a conversa e qualifica
4. Ao qualificar, entrega para o vendedor humano continuar pelo mesmo número (API oficial)
5. Serve também para migrar a base de conversas para a API oficial

---

## Arquitetura

### Estrutura de pastas

```
backend-recuperar-lead/
├── app/
│   ├── agent/
│   │   ├── orchestrator.py        # fork do backend-evolution, com lead_context
│   │   ├── token_tracker.py       # igual ao backend-evolution
│   │   ├── tools.py               # igual ao backend-evolution
│   │   └── prompts/
│   │       ├── __init__.py
│   │       ├── base.py            # base prompt adaptado para outbound
│   │       ├── secretaria.py      # NOVO — secretaria SDR (proativo, comercial)
│   │       ├── atacado.py         # igual ao backend-evolution
│   │       ├── private_label.py   # igual ao backend-evolution
│   │       ├── exportacao.py      # igual ao backend-evolution
│   │       └── consumo.py         # igual ao backend-evolution
│   ├── outbound/
│   │   ├── __init__.py
│   │   ├── dispatcher.py          # NOVO — envia template hardcoded via Meta API
│   │   └── router.py              # NOVO — POST /api/outbound/dispatch
│   ├── buffer/
│   │   └── processor.py           # fork do backend-evolution, com check human_control
│   ├── webhook/
│   │   ├── router.py              # recebe webhooks da Evolution API (fallback)
│   │   └── meta_router.py         # recebe webhooks da Meta Cloud API (principal)
│   ├── leads/
│   │   └── service.py             # igual ao backend-evolution
│   ├── whatsapp/
│   │   ├── client.py              # igual
│   │   ├── factory.py             # igual
│   │   ├── media.py               # igual
│   │   └── meta_cloud.py          # igual
│   ├── channels/
│   │   └── service.py             # igual
│   ├── humanizer/
│   │   ├── splitter.py            # igual
│   │   └── typing.py              # igual
│   ├── photos/                    # igual (catálogo de fotos)
│   ├── cadence/                   # igual (pausa cadência quando lead responde)
│   ├── db/
│   │   └── supabase.py            # igual
│   ├── config.py                  # igual
│   └── main.py                    # igual + inclui outbound router
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── pytest.ini
```

---

## Componentes Novos

### 1. `app/agent/prompts/secretaria.py` — Prompt SDR Proativo

Completamente reescrito em relação ao `backend-evolution`. Diferenças-chave:

- **Valeria está abordando**, não recebendo. O tom é mais comercial e propositivo.
- **Contexto adaptativo:** se tiver nome do lead, usa desde o início; se tiver histórico/empresa, menciona contextualmente.
- **Objetivo da secretaria:** criar interesse → qualificar necessidade → mudar stage (mesmo funil, abordagem inversa).
- **Sem etapa de "receber boas-vindas"** — Valeria abre com proposta de valor, não com pergunta genérica.
- **Mais tolerante a frieza:** lead pode não responder ou ser frio; o prompt inclui estratégias de reabertura.

### 2. `app/agent/prompts/base.py` — Base Prompt com `lead_context`

O `build_base_prompt()` recebe um dict `lead_context` opcional com:
```python
{
    "name": str | None,
    "company": str | None,
    "previous_stage": str | None,   # e.g. "atacado"
    "notes": str | None,            # qualquer contexto do CRM
}
```
Se `lead_context` tiver dados, o base prompt injeta: "Contexto do lead: [dados]" para o agent personalizar a abordagem.

### 3. `app/outbound/dispatcher.py` — Dispatcher de Template

```python
async def dispatch_to_lead(phone: str, lead_context: dict) -> dict:
    """Envia template hardcoded via Meta Cloud API e salva registro."""
```

- Template hardcoded: texto de re-engajamento da Cafe Canastra (a ser definido no arquivo)
- Usa `META_PHONE_NUMBER_ID` e `META_ACCESS_TOKEN` do env
- Salva mensagem no histórico do lead como `role="assistant"` (para o agent ter contexto do que foi enviado)
- Retorna `{"status": "sent", "lead_id": ..., "phone": ...}`

### 4. `app/outbound/router.py` — Endpoint de Disparo

```
POST /api/outbound/dispatch
Body: { "phone": "+5511999999999", "lead_context": { "name": "João", ... } }
Response: { "status": "sent", "lead_id": "..." }
```

Por enquanto sem auth (integração CRM virá depois). Em produção, proteger com API key.

---

## Fluxo Completo

```
Vendedor seleciona lead no CRM
         ↓
POST /api/outbound/dispatch
         ↓
dispatcher.py envia template Meta → lead recebe no WhatsApp
         ↓
Lead responde
         ↓
Meta → POST /webhook/meta → buffer → processor.py
         ↓
processor.py checa human_control: false → roda agent
         ↓
Agent (secretaria SDR) qualifica o lead
         ↓
Tool call: mudar_stage → atacado/private_label/exportacao/consumo
         ↓
Agent do novo stage continua a conversa
         ↓
Tool call: encaminhar_humano → update_lead(human_control=True)
         ↓
Próxima mensagem do lead: processor.py checa human_control: true → NÃO roda agent
         ↓
Vendedor atende manualmente pelo CRM / número oficial
```

---

## Diferenças em Relação ao backend-evolution

| Aspecto | backend-evolution | backend-recuperar-lead |
|---|---|---|
| Quem inicia | Lead | Valeria (outbound) |
| Tom da secretaria | Receptivo, qualificador | Comercial, propositivo |
| Primeiro contato | Lead já chegou interessado | Template de re-engajamento |
| Após qualificação | Guardrail automático de stage | `encaminhar_humano` direto ao vendedor |
| `human_control` | Opcional | Central — bloqueia agent após encaminhar |
| Endpoint novo | Nenhum | `POST /api/outbound/dispatch` |
| Lead context | Só nome/empresa | Nome + empresa + stage anterior + notas |

---

## Configuração (Env Vars)

Idênticas ao `backend/` em produção:
```
SUPABASE_URL
SUPABASE_SERVICE_KEY
REDIS_URL
OPENAI_API_KEY           # GPT-4.1 para secretaria/atacado/private_label
META_ACCESS_TOKEN
META_PHONE_NUMBER_ID
API_BASE_URL
FRONTEND_URL
```

---

## Decisões Técnicas

- **Sem tocar no CRM** — endpoint `/api/outbound/dispatch` é a única interface com o exterior por enquanto
- **Template hardcoded** — texto fixo em `dispatcher.py`, fácil de trocar depois
- **Sem auth no endpoint** — proteger com API key em integração futura
- **Sem guardrail automático de stage** — SDR deve qualificar mais rápido; o guardrail no backend-evolution é um fallback para leads que ficam presos; aqui o agent SDR já é mais direto
- **Mantém token_tracker** — essencial para medir custo por lead recuperado
- **Mantém cadência** — para pausar cadências ativas quando lead responde ao disparo
