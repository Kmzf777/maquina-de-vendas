# Design — Rehearsal Automático da Valéria

**Data:** 2026-04-20
**Contexto:** Task 1.3 do plano `2026-04-20-valeria-mvp-pilot.md` prevê rehearsal manual dos 5 arquétipos (A1-A5) via dev router. Este design substitui o rehearsal manual por um processo automatizado que executa os 5 arquétipos sequencialmente, com isolamento total entre eles, captura completa de logs, e verificação por arquétipo antes de avançar.

**Princípios:** isolamento total entre arquétipos, verificação completa por lead antes do próximo, logs organizados para análise posterior, reuso da infraestrutura de produção (webhook + worker + orquestrador real).

---

## 1. Arquitetura geral

```
┌─────────────────────────────────────────────────────────────────┐
│  backend/scripts/rehearsal_runner.py                            │
│                                                                 │
│  for archetype in [A1, A2, A3, A4, A5]:                         │
│     1. WIPE Supabase (lead + messages + conversations + deals)  │
│     2. Conversation loop (até max 20 turnos):                   │
│        ┌─ Gemini 2.5 Pro gera fala do lead (persona-driven)     │
│        ├─ POST webhook Meta → dev backend (REHEARSAL_MODE)      │
│        ├─ Polling Supabase.messages por respostas novas         │
│        ├─ Detectar eventos de parada em tool events             │
│        └─ Repete                                                │
│     3. Hard checks (eventos) + soft check (LLM-as-judge)        │
│     4. Persiste artefatos em rehearsal-runs/<ts>/<A_n>/         │
│  Escreve summary.md consolidado do run                          │
└─────────────────────────────────────────────────────────────────┘
                               │
                    POST /webhook/meta (Meta payload sintético)
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  Backend DEV (flag REHEARSAL_MODE=true)                         │
│                                                                 │
│  webhook → parser → buffer → worker → orchestrator → tools      │
│                                                                 │
│  Provider real substituído por MockProvider:                    │
│    - send_text: salva mensagem no Supabase + log local          │
│    - send_image_base64: idem (sem envio real)                   │
│    - send_template: idem                                        │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    Supabase (messages / leads / conversations)
```

### Princípio de isolamento

- **Um arquétipo por vez.** O script não paraleliza.
- **Mesmo telefone, estado zerado.** Todos os arquétipos usam o número `REHEARSAL_PHONE` (whitelistado no Redis dev:phone_routes). Entre arquétipos, o script **deleta** lead + messages + conversations + deals desse número, garantindo que a próxima conversa comece como se fosse um lead recém-criado.
- **Sem reuso de contexto.** A LLM (Valéria) carrega histórico da conversa a partir da tabela `messages` via `get_history`. Wipe da tabela = sem contexto residual.

---

## 2. Componentes

### 2.1. Mock provider

**Arquivo:** `backend/app/whatsapp/mock_provider.py` (novo)

Implementa a mesma interface dos providers reais (`send_text`, `send_image_base64`, `send_template`, etc.) mas:
- Não chama nenhuma API externa.
- Escreve cada chamada em `/tmp/rehearsal-<timestamp>.jsonl` para o runner coletar.
- O `save_message` no Supabase continua sendo chamado pelo orquestrador como de costume — o mock só substitui o envio externo.

### 2.2. Registry condicional

**Arquivo:** `backend/app/whatsapp/registry.py` (modificar)

Quando `os.environ.get("REHEARSAL_MODE") == "true"`, o `get_provider(channel)` retorna `MockProvider()` em vez do provider configurado no canal.

Efeito colateral: enquanto `REHEARSAL_MODE` estiver ligado, **nenhuma mensagem real sai do backend** — portanto o backend dev com essa flag ativa é seguro para rodar o rehearsal sem spam no WhatsApp do usuário.

### 2.3. Rehearsal runner (script principal)

**Arquivo:** `backend/scripts/rehearsal_runner.py` (novo)

Responsabilidades:
1. Ler variáveis de ambiente (`GEMINI_API_KEY`, `DEV_BACKEND_URL`, `REHEARSAL_PHONE`, `SUPABASE_*`).
2. Health check do dev backend antes de começar (`GET /health`).
3. Criar pasta do run: `docs/superpowers/plans/pilot/rehearsal-runs/<ISO-timestamp>/`.
4. Para cada arquétipo em ordem (A1 → A5):
   - Chamar `supabase_io.wipe_lead(REHEARSAL_PHONE)` + `supabase_io.wipe_redis_buffer(REHEARSAL_PHONE, redis)`.
   - Executar `conversation_loop(archetype)` — até encontrar evento de parada ou atingir 20 turnos.
   - Executar `verifier.verify(archetype, run_data)`.
   - Chamar `logger.write_artifacts(archetype, run_data, verification)`.
5. Escrever `summary.md` consolidado e `run.json` final.

### 2.4. Arquétipos como dados

**Arquivo:** `backend/scripts/rehearsal/archetypes.py` (novo)

Dataclass por arquétipo, contendo:
- `id`: "A1" etc.
- `slug`: "cafeteria-atacado" (usado no path da pasta)
- `persona_prompt`: string longa usada como system prompt do Gemini
- `first_message`: fala inicial do lead (determinística — fixa a partida)
- `hard_checks`: lista de callables que recebem `run_data` e retornam `(bool, reason)`

Arquétipos: A1 (cafeteria ATACADO), A2 (private_label), A3 (multi-intent), A4 (objetor de preço), A5 (exportação) — personas já definidas em `docs/superpowers/plans/pilot/2026-04-20-rehearsal-scripts.md`.

### 2.5. Gemini actor

**Arquivo:** `backend/scripts/rehearsal/gemini_actor.py` (novo)

Usa `google-generativeai` com modelo `gemini-2.5-pro`. Duas funções principais:

**`generate_next_lead_message(persona_prompt, conversation_history, last_assistant_message) -> str`**
- Monta prompt: "Você é {persona}. Histórico: {formatted}. Última mensagem da Valéria: {last}. Responda na próxima fala (1-2 frases, tom coloquial, português brasileiro)."
- Retorna só a fala.

**`judge_conversation(transcript, archetype) -> dict`**
- Recebe o `transcript.md` renderizado + critérios do arquétipo.
- Retorna JSON com `bot_score_1_10`, `linhas_robotizadas`, `resposta_incorreta_ou_inventada`, `veredito_curto`.

Ambas têm retry de 3× com backoff exponencial. Se o retry falhar, o script registra um erro no `verification.json` e continua — não aborta o run.

### 2.6. Verifier

**Arquivo:** `backend/scripts/rehearsal/verifier.py` (novo)

Hard checks por arquétipo (`tool_events` é a lista de chamadas de tool extraídas de `messages.role = 'system'` ou de logs do orquestrador):

| Arquétipo | Checks |
|-----------|--------|
| A1 | `mudar_stage("atacado")` ∈ tool_events AND (`enviar_fotos` ∈ tool_events OR `enviar_foto_produto` ∈ tool_events) AND transcript contém regex `\d+\s*(kg|quilos?)` |
| A2 | `mudar_stage("private_label")` ∈ tool_events AND `encaminhar_humano` ∈ tool_events |
| A3 | `len({stages visitados}) >= 2` OR transcript contém menção simultânea a "cafeteria" e "marca própria" em mesma resposta da Valéria |
| A4 | `mudar_stage("atacado")` ∈ tool_events AND `turns_count >= 5` |
| A5 | `mudar_stage("exportacao")` ∈ tool_events AND `encaminhar_humano` ∈ tool_events |

Soft check: chamada ao `gemini_actor.judge_conversation()`.

Output em `verification.json`:
```json
{
  "archetype_id": "A1",
  "status": "passed" | "failed",
  "hard_checks": [
    {"name": "mudar_stage_atacado", "passed": true, "reason": "..."},
    ...
  ],
  "soft_check": { /* LLM-as-judge output */ },
  "turns_count": 14,
  "terminated_by": "encaminhar_humano" | "stage_reached" | "max_turns" | "timeout"
}
```

### 2.7. Supabase IO

**Arquivo:** `backend/scripts/rehearsal/supabase_io.py` (novo)

Usa o cliente Supabase do próprio backend (`from app.supabase_client import get_supabase`) — reusa credenciais já configuradas.

Funções:
- `wipe_lead(phone: str) -> None`: deleta em ordem: `messages` → `conversations` → `deals` → `leads` por telefone.
- `get_messages_since(lead_id: str, since_iso: str) -> list[dict]`: retorna mensagens criadas após timestamp.
- `get_assistant_messages(lead_id: str) -> list[dict]`: retorna só as mensagens da Valéria.
- `get_system_events(lead_id: str) -> list[dict]`: retorna mensagens `role="system"` que são o canal pelo qual tools registram seus efeitos.
- `get_lead_by_phone(phone: str) -> dict | None`.
- `wipe_redis_buffer(phone: str, redis_client) -> None`: deleta qualquer entrada no buffer Redis (`buffer:<phone>` ou key equivalente — o plano valida o padrão de key lendo `backend/app/buffer/manager.py`). Evita que mensagens pendentes de um arquétipo anterior sejam processadas dentro do próximo.

### 2.8. Logger

**Arquivo:** `backend/scripts/rehearsal/logger.py` (novo)

Escreve os artefatos por arquétipo:
- `transcript.md` — conversa formatada em markdown, com cabeçalhos por turno, separando lead (simulado pelo Gemini) e Valéria.
- `events.jsonl` — um evento por linha (tool call, stage change, system message, timeout).
- `messages.json` — dump bruto das mensagens do Supabase para o lead.
- `verification.json` — output do verifier.
- `archetype-prompt.md` — cópia do persona_prompt usado (para reprodutibilidade).

Também escreve `run.json` e `summary.md` no nível do run completo.

### 2.9. Webhook sintético

Para injetar a fala do lead no backend, o runner monta um payload Meta mínimo:

```json
{
  "object": "whatsapp_business_account",
  "entry": [{
    "id": "rehearsal",
    "changes": [{
      "value": {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": "<rehearsal_phone_number_id>"},
        "messages": [{
          "from": "<REHEARSAL_PHONE>",
          "id": "wamid.rehearsal.<uuid>",
          "timestamp": "<unix_ts>",
          "type": "text",
          "text": {"body": "<gemini_response>"}
        }]
      },
      "field": "messages"
    }]
  }]
}
```

POST para `<DEV_BACKEND_URL>/webhook/meta`. O plano de implementação valida esse caminho lendo `backend/app/main.py` antes de codar o runner — se o path real for outro, o plano ajusta.

---

## 3. Fluxo detalhado de um turno

1. Script chama `gemini_actor.generate_next_lead_message(persona, history, last_valeria_msg)`.
2. Script monta payload Meta com `text=<gemini_output>`.
3. `POST {DEV_BACKEND_URL}/webhook/meta` — espera 200 OK.
4. Script marca `t_sent = now()`.
5. Backend: buffer (∼1.5s) → worker → `run_agent()` → tools → `MockProvider.send_text` → `save_message` no Supabase.
6. Script faz polling: `supabase_io.get_messages_since(lead_id, t_sent)` a cada 500ms, até 15s.
   - Se aparecerem mensagens novas com `role="assistant"`, considera a rodada completa.
   - Se aparecer evento de parada (`encaminhar_humano` chamado, ou `mudar_stage` para stage final), marca terminação.
   - Se passar 15s sem resposta, registra `timeout` e pula turno.
7. Script decide: continuar ou encerrar.

Timeout de 15s foi escolhido considerando buffer de 1.5s + latência do OpenAI (∼3-8s por resposta) + margem. Tunável via env `REHEARSAL_TURN_TIMEOUT`.

---

## 4. Critérios de parada por arquétipo

Além dos hard checks (que definem pass/fail), a conversa termina quando:

- `encaminhar_humano` é chamado (lead passou para humano — fim natural).
- `mudar_stage` para stage final específico do arquétipo (ex: A5 chega em `exportacao`).
- 20 turnos atingidos (limite de segurança).
- Timeout consecutivo em 2 turnos (Valéria parou de responder).

**Importante:** encerrar por `encaminhar_humano` NÃO quer dizer "passou" — quer dizer que a conversa terminou. O verifier depois decide se o caminho até ali cumpriu os critérios.

---

## 5. Estrutura de saída

```
docs/superpowers/plans/pilot/rehearsal-runs/
└── 2026-04-20T14-30-00/
    ├── run.json
    ├── summary.md
    ├── A1-cafeteria-atacado/
    │   ├── transcript.md
    │   ├── events.jsonl
    │   ├── messages.json
    │   ├── verification.json
    │   └── archetype-prompt.md
    ├── A2-private-label/…
    ├── A3-multi-intent/…
    ├── A4-objetor-preco/…
    └── A5-exportacao/…
```

`summary.md` tem tabela A1-A5 com `status`, `turns_count`, `terminated_by`, `bot_score`, `veredito_curto` — pra olhar o run inteiro em 30 segundos.

`run.json` inclui metadata: modelo da Valéria, modelo do Gemini ator, timestamps, versão do branch (`git rev-parse HEAD`), env vars relevantes (sem secrets).

---

## 6. Variáveis de ambiente

Adicionar ao `backend/.env.local`:

| Variável | Propósito | Exemplo |
|----------|-----------|---------|
| `REHEARSAL_MODE` | Ativa mock provider no backend | `true` (só durante rehearsal) |
| `REHEARSAL_PHONE` | Número usado nos arquétipos | `5534996652412` |
| `GEMINI_API_KEY` | API key do Google AI Studio | `...` |
| `DEV_BACKEND_URL` | URL do backend dev onde o webhook entra | `http://127.0.0.1:8001` |
| `REHEARSAL_TURN_TIMEOUT` | Timeout por turno em segundos | `15` (default) |
| `REHEARSAL_MAX_TURNS` | Limite máximo de turnos por arquétipo | `20` (default) |

`REHEARSAL_MODE` **só deve existir no `.env.local`** — nunca em `.env` de produção. Comentário no `.env.local` deixa isso explícito.

---

## 7. Dependências

Adicionar em `backend/requirements.txt`:

```
google-generativeai>=0.8.0
```

Nenhuma outra dependência nova. `httpx` já existe para o POST webhook, `supabase` já existe.

---

## 8. Como rodar

```bash
# Terminal 1 — backend dev com rehearsal mode
cd backend
REHEARSAL_MODE=true uvicorn app.main:app --reload --env-file .env.local --port 8001

# Terminal 2 — rehearsal runner
cd backend
python -m scripts.rehearsal_runner
```

Alternativa: VS Code task `Run Rehearsal (all archetypes)` que orquestra os dois.

**Precaução operacional:** enquanto o backend dev está com `REHEARSAL_MODE=true`, ele não envia mensagens reais. Se o usuário esquecer a flag ligada e mandar uma mensagem real do número whitelistado, ela será processada mas a resposta não sairá — é uma falha silenciosa previsível. Mitigação: o backend loga em WARNING a cada `send_text` do mock. O usuário deve desligar a flag ao terminar.

---

## 9. Tratamento de erros

| Cenário | Comportamento |
|---------|---------------|
| Gemini falha (rate limit, 500) | 3× retry com backoff. Se persistir, arquétipo fica com status `error` no summary, runner continua próximo. |
| Backend dev offline | Health check no início aborta o run com mensagem clara. |
| Supabase rejeita wipe | Aborta o run e instrui o usuário a verificar credenciais. Nenhum arquétipo fica meio-executado. |
| Valéria não responde (timeout) | Registra turno como `[Valéria não respondeu]`, tenta próximo turno. Se 2 timeouts seguidos, encerra arquétipo por `timeout`. |
| Crash no script | Artefatos parciais ficam salvos (escrita incremental). `run.json` tem flag `completed: false` se o loop não terminou. |

---

## 10. Fora de escopo

- Paralelização entre arquétipos (constraint explícito: um por vez).
- Dashboard de comparação entre runs (análise manual em `summary.md` por enquanto).
- Edição inline de prompts durante o rehearsal (o usuário edita manualmente e re-roda).
- Áudio/imagem nos arquétipos (MVP é só texto — esses casos ficam para iteração futura).
- Testes unitários do próprio runner (script de automação de teste, pesar o custo vs. benefício).

---

## 11. Verificação end-to-end do design

- Automação: script roda sem interação do usuário após `python -m scripts.rehearsal_runner`. ✓
- Um lead por vez: loop sequencial, wipe entre arquétipos. ✓
- Salvar troca de mensagens: `transcript.md` + `messages.json` + `events.jsonl` por arquétipo. ✓
- Reset completo: `wipe_lead` deleta messages/conversations/deals/leads. ✓
- Usar número da whitelist: `REHEARSAL_PHONE` é o número whitelistado, usado em todo o run. ✓
- Logs organizados: estrutura timestamped por run, subpastas por arquétipo. ✓
- Verificação completa antes de avançar: hard checks + soft check são executados após cada arquétipo, artefatos escritos, e só então o próximo arquétipo começa. ✓
