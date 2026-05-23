# Handoff Rescue — Design Spec

**Data:** 2026-05-23
**Status:** Aprovado
**Escopo:** Quando a IA qualifica um lead e invoca `encaminhar_humano`, enviar mensagem de redirecionamento imediata pelo canal da IA e agendar um "resgate" de 15 min que dispara o template `rabubens` pelo número do João se o lead não entrar em contato com ele.

---

## 1. Objetivo

Aumentar a taxa de conversão de leads qualificados garantindo que nenhum lead fique sem contato após o handoff para o João. O fluxo é:

1. IA invoca `encaminhar_humano` → mensagem de redirecionamento enviada pelo canal da IA.
2. Job agendado para `now + 15 min`.
3. Ao disparar: se o lead **não** enviou nenhuma mensagem para o canal do João nos últimos 15 min → dispara template `rabubens` pelo número do João.
4. Se o lead **já** contatou o João → nenhum envio (job marcado como `sent`).

---

## 2. Regras de Negócio

- **Gatilho:** tool `encaminhar_humano` invocada pela LLM.
- **Mensagem imediata:** enviada pelo canal da IA (mesmo `phone_number_id` que estava ativo na conversa). Texto fixo hardcoded.
- **Timer:** 15 minutos a partir do momento do handoff.
- **Verificação de contato:** busca mensagens com `role='user'` nas conversas do lead com o canal do João (`phone_number_id = 1049315514934778`) criadas nos últimos 15 minutos.
- **Resgate:** template `rabubens`, `language_code = pt_BR`, sem componentes adicionais (template simples sem variáveis).
- **Remetente do resgate:** `MetaCloudClient` instanciado diretamente com o `provider_config` do canal do João.
- **Idempotência:** cada invocação de `encaminhar_humano` cria um único job de resgate. Não há cancelamento de jobs anteriores (o cenário de dupla qualificação é improvável e inócuo — dois templates não são críticos).
- **Falha no envio da mensagem imediata:** logada, não bloqueia a criação do job de resgate nem o retorno da tool para a LLM.
- **Canal do João não encontrado no DB:** job cancelado com `reason='joao_channel_not_found'`, nenhum template enviado.

---

## 3. Banco de Dados

### 3.1 Migration: `20260523_handoff_rescue_job_type.sql`

Duas colunas novas na tabela `follow_up_jobs` existente:

```sql
ALTER TABLE follow_up_jobs
  ADD COLUMN IF NOT EXISTS job_type TEXT NOT NULL DEFAULT 'standard',
  ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_followup_jobs_type
  ON follow_up_jobs (job_type, status)
  WHERE status = 'pending';
```

Registros existentes recebem `job_type='standard'` e `metadata='{}'` pelo `DEFAULT` — sem breaking change.

---

## 4. Arquitetura e Fluxo

```
[LLM invoca encaminhar_humano]
        │
        ▼
[tools.py — execute_tool()]
  1. update_lead(ai_enabled=False, ...)      ← já existente
  2. create_deal(...)                         ← já existente
  3. get_channel_for_lead(lead_id)            ← busca canal ativo do lead
  4. await provider.send_text(phone, MSG)     ← mensagem de redirecionamento
  5. save_message(role='assistant', sent_by='handoff')
  6. schedule_handoff_rescue(lead_id, phone, conv_id, channel_id)
  7. return "Lead encaminhado para João"

[follow_up_jobs] ← job inserido:
  job_type   = 'handoff_rescue'
  sequence   = 0
  fire_at    = now + 15 min
  channel_id = canal da IA (satisfaz FK)
  metadata   = {lead_phone, joao_phone_number_id, template_name}

[worker — process_due_followups() — a cada 5s]
        │
        ├─ job_type == 'handoff_rescue'
        │       └─ _process_handoff_rescue(job)
        │               │
        │               ├─ Resolve canal João via provider_config
        │               ├─ Busca conversas lead × canal João
        │               ├─ Há msg role='user' nos últimos 15 min?
        │               │       └─ SIM → _mark_sent(job_id)
        │               └─ NÃO → send_template(phone, 'rabubens') → _mark_sent()
        │
        └─ job_type == 'standard' (ou ausente)
                └─ lógica de follow-up existente (sem mudança)
```

---

## 5. Constantes Fixas

| Constante | Valor |
|---|---|
| `JOAO_PHONE_NUMBER_ID` | `"1049315514934778"` |
| `HANDOFF_RESCUE_DELAY_MINUTES` | `15` |
| `HANDOFF_RESCUE_TEMPLATE` | `"rabubens"` |
| `HANDOFF_RESCUE_LANGUAGE` | `"pt_BR"` |
| `HANDOFF_MSG` | *(texto completo abaixo)* |

**Texto completo da mensagem de redirecionamento:**
```
Perfeito! Seu atendimento agora será continuado pelo João, um dos nossos especialistas.

👉 Clique no link abaixo e envie uma mensagem para ele agora mesmo para dar continuidade no seu atendimento com prioridade:
http://wa.me/553491461669

Assim que você chamar, ele já receberá seu contato e continuará seu atendimento.
```

---

## 6. Arquivos Afetados

| Arquivo | Tipo | O que muda |
|---|---|---|
| `backend/migrations/20260523_handoff_rescue_job_type.sql` | NOVO | 2 colunas + índice na `follow_up_jobs` |
| `backend/app/agent/tools.py` | MODIFICAR | `encaminhar_humano`: envia texto + agenda resgate |
| `backend/app/follow_up/service.py` | MODIFICAR | Adiciona `schedule_handoff_rescue()` |
| `backend/app/follow_up/scheduler.py` | MODIFICAR | Roteia `handoff_rescue`, adiciona `_process_handoff_rescue()` |

---

## 7. Tratamento de Erros

| Ponto de falha | Comportamento |
|---|---|
| `send_text` falha (canal da IA) | Log de erro, continua para agendar o job de resgate |
| Canal do João não encontrado | `_cancel_job(reason='joao_channel_not_found')` |
| `send_template` falha | Log de erro, job **não** marcado como `sent` → será retentado no próximo tick do worker |
| Conversa/mensagens inacessíveis | Log de erro, segurança: envia o template (falso negativo é melhor que falso positivo) |

---

## 8. O que NÃO muda

- Lógica de follow-up padrão (`job_type='standard'`) — nenhuma alteração.
- Guards de `followup_enabled`, `mode='human'` e janela de 24h — continuam válidos para jobs padrão. Jobs `handoff_rescue` são roteados antes desses guards.
- Estrutura do worker (`broadcast/worker.py`) — nenhuma alteração.
- API de canais, leads, conversas — nenhuma alteração.
