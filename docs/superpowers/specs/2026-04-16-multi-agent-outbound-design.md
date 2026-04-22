# Multi-Agent Outbound: Infraestrutura e Agente Valéria Outbound

**Data:** 2026-04-16  
**Branch:** feature/novos-agentes-e-campanhas  
**Status:** Aprovado para implementação

---

## Contexto

O sistema atual tem um único agente (Valéria Inbound) hardcoded no orchestrator. Ele atende leads que chegam espontaneamente via landing pages e tráfego pago — fluxo passivo. Os prompts são arquivos Python estáticos; a tabela `agent_profiles` existe mas é ignorada pelo orchestrator (serve apenas para decidir "tem agente ou não").

Queremos suportar múltiplos agentes, cada um com prompts próprios, selecionável na criação de um broadcast. O primeiro novo agente é a **Valéria Outbound** — projetada para recuperar leads ociosos e abordar leads frios via disparo ativo.

---

## Objetivos

1. Infraestrutura para múltiplos agentes por conversa (não por canal)
2. Broadcasts podem selecionar qual agente atende as respostas
3. Agente Valéria Outbound com prompts adaptados para abordagem ativa
4. Agente inbound existente inalterado

---

## Arquitetura

### Schema

```sql
-- Qual agente está atendendo esta conversa
ALTER TABLE conversations
  ADD COLUMN agent_profile_id uuid REFERENCES agent_profiles(id);

-- Qual agente atenderá as respostas deste broadcast
ALTER TABLE broadcasts
  ADD COLUMN agent_profile_id uuid REFERENCES agent_profiles(id);

-- Qual conjunto de prompts Python usar
ALTER TABLE agent_profiles
  ADD COLUMN prompt_key text NOT NULL DEFAULT 'valeria_inbound';
```

### Fluxo de disparo

```
Broadcast worker
  → envia template para lead
  → get_or_create_conversation(lead_id, channel_id)
  → update_conversation(id, agent_profile_id = broadcast.agent_profile_id)
     (stage NÃO é resetado — mantém onde parou)
```

### Fluxo de resposta do lead

```
Webhook → buffer → processor
  → carrega conversation (tem agent_profile_id)
  → carrega agent_profile da DB (tem prompt_key)
  → orchestrator usa prompt_key para selecionar pasta de prompts
  → run_agent normal com os prompts corretos
```

### Resolução de agente no processor

Prioridade:
1. `conversation.agent_profile_id` — agente explicitamente atribuído (pelo broadcast)
2. `channel.agent_profile_id` — fallback para o agente padrão do canal (inbound)
3. Sem agente → human-only mode (comportamento atual)

---

## Estrutura de arquivos de prompts

```
backend/app/agent/prompts/
  valeria_inbound/       ← prompts atuais (movidos)
    base.py
    secretaria.py
    atacado.py
    private_label.py
    exportacao.py
    consumo.py
  valeria_outbound/      ← novo agente
    base.py              ← mesma personalidade + contexto outbound
    secretaria.py
    atacado.py
    private_label.py
    exportacao.py
    consumo.py
```

O orchestrator mapeia `prompt_key` → pasta:

```python
PROMPT_REGISTRY = {
    "valeria_inbound":  "app.agent.prompts.valeria_inbound",
    "valeria_outbound": "app.agent.prompts.valeria_outbound",
}
```

---

## Agente Valéria Outbound — Estratégia de Prompts

### Contexto geral

A Valéria Outbound sabe que:
- Ela iniciou o contato via template WhatsApp (geralmente genérico/utilidade)
- O lead pode ter respondido com "oi", curiosidade ou até desconfiança
- Se o lead tem histórico anterior, ela lê o contexto e retoma — não começa do zero
- Ela está "interrompendo" o dia do lead, então precisa ser rápida em criar valor

### Diferenças vs Inbound

| Dimensão | Inbound | Outbound |
|---|---|---|
| Quem inicia | Lead chega | Valéria disparou template |
| Apresentação | Se apresenta sempre | Só se lead não tem histórico |
| Tom | Acolhedor, segue o ritmo | Assertivo mas não agressivo |
| Objeções | Raras — lead quis falar | Comuns — lead foi abordado |
| Mudança de stage | Segue o funil | Relê contexto, pivota se mudou de ideia |
| Persistência | Baixa — cliente conduz | Média — tenta 1x superar objeção |

### secretaria outbound

**Cenários que o agente deve dominar:**

1. **Lead novo (sem histórico):** Apresenta-se brevemente, explica por que entrou em contato, cria curiosidade. Não despeja informação — faz uma pergunta.

2. **Lead com histórico (esteve em stage X):** Não se apresenta de novo. Reconhece o contato anterior de forma natural: *"a gente já conversou antes sobre [tema] — queria saber se ainda faz sentido pra você"*. Se lead mudou de ideia, pivota sem resistência.

3. **Lead responde frio ("quem é?", "para de me mandar mensagem"):** Não insiste. Explica brevemente e oferece saída digna. Se qualquer abertura aparecer, aproveita.

4. **Lead responde neutro ("oi", "sim"):** Transforma em conversa — reage com calor, cria contexto, faz uma pergunta para qualificar.

### Stages especializados outbound

Cada stage inicia com uma verificação implícita do contexto anterior:
- Se tem histórico relevante, referencia: *"da última vez você mencionou X"*
- Pergunta se o interesse continua válido antes de presumir
- Diagnóstico de dor mais direto (não tem o luxo de uma chegada espontânea)
- Mais tolerante a objeções — tem scripts para contornar sem pressionar

---

## Componentes a implementar

### Backend

1. **Migração SQL** (`009_multi_agent_schema.sql`)
   - `conversations.agent_profile_id`
   - `broadcasts.agent_profile_id`
   - `agent_profiles.prompt_key`
   - Seed: update do perfil existente com `prompt_key = 'valeria_inbound'`

2. **Reorganização de prompts**
   - Mover arquivos de `prompts/*.py` para `prompts/valeria_inbound/`
   - Criar `prompts/valeria_outbound/` com 6 arquivos adaptados

3. **Orchestrator** (`agent/orchestrator.py`)
   - Remover `STAGE_PROMPTS` hardcoded
   - Adicionar `PROMPT_REGISTRY` + loader dinâmico por `prompt_key`
   - `run_agent` aceita `agent_profile_id` opcional

4. **Broadcast worker** (`broadcast/worker.py`)
   - Após enviar template, chama `get_or_create_conversation` + `update_conversation` com `agent_profile_id`

5. **Processor** (`buffer/processor.py`)
   - Resolve `agent_profile_id`: conversation > channel > None
   - Passa para `run_agent`

6. **Conversations service** (`conversations/service.py`)
   - `get_or_create_conversation` aceita `agent_profile_id` opcional
   - `update_conversation` aceita `agent_profile_id`

### Frontend

7. **Página `/campanhas` — formulário de broadcast**
   - Dropdown "Agente" listando `agent_profiles` da API
   - Envia `agent_profile_id` no payload de criação do broadcast

---

## Seed de dados

```sql
-- Perfil inbound existente: adicionar prompt_key
UPDATE agent_profiles
SET prompt_key = 'valeria_inbound'
WHERE name ILIKE '%ValerIA%' OR name ILIKE '%Canastra%';

-- Novo perfil outbound
INSERT INTO agent_profiles (name, model, prompt_key, base_prompt, stages)
VALUES (
  'ValerIA - Outbound / Recuperação',
  'gemini-3-flash-preview',
  'valeria_outbound',
  '',
  '{
    "secretaria": {"model": "gemini-3-flash-preview", "tools": ["salvar_nome", "mudar_stage"]},
    "atacado":    {"model": "gemini-3-flash-preview", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"]},
    "private_label": {"model": "gemini-3-flash-preview", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano", "enviar_fotos", "enviar_foto_produto"]},
    "exportacao": {"model": "gemini-3-flash-preview", "tools": ["salvar_nome", "mudar_stage", "encaminhar_humano"]},
    "consumo":    {"model": "gemini-3-flash-preview", "tools": ["salvar_nome", "mudar_stage"]}
  }'::jsonb
);
```

---

## O que NÃO muda

- Fluxo inbound: leads que chegam espontaneamente continuam com o agente padrão do canal
- Lógica de `human_control`: agente para de responder quando `human_control=True`
- Tool `encaminhar_humano`: cria deal no CRM, comportamento idêntico
- Stages e tools disponíveis por stage: mesma estrutura
- Personalidade base da Valéria: mesma identidade nos dois agentes
