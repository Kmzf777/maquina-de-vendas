# Design: Isolamento de Conversas e Controle de Acesso por Atendente

**Data:** 2026-06-10  
**Branch:** `feat/conversas-isolamento-acesso`  
**Status:** Aprovado

---

## Contexto

O sistema possui múltiplos canais WhatsApp — cada canal é operado por um atendente específico (ex: Valéria = IA qualificadora, João = vendedor). Atualmente não há vínculo entre usuários (`auth.users`) e canais (`channels`), fazendo com que todos os atendentes vejam todas as conversas de todos os canais.

O fluxo de negócio é:
1. Lead contata o número da Valéria → qualificação pela IA
2. Valéria chama `encaminhar_humano` → seta `ai_enabled=False`, agenda `handoff_rescue` (15 min)
3. Lead contata o número do João (Cenário 1), ou João dispara o template `automacao_valeria_to_joao` (Cenário 2)
4. Nova conversa é criada para o par `(lead, canal_do_joao)`

---

## Problemas a Resolver

### Problema 1: Card da Valéria atualizado indevidamente
Após o lead migrar para João, mensagens no canal de João atualizam o `last_msg_at` do sistema, causando reordenação e rebuild da lista para todos — inclusive Valéria, que não tem mais relação com essa conversa.

### Problema 2: João vê histórico completo da Valéria
A conversa do João é nova e isolada, mas não há contexto de qualificação disponível para ele no momento certo. O ideal é um resumo estruturado gerado automaticamente, visível diretamente no chat do João.

### Problema 3: João vê os cards de Valéria
`/api/conversations` não filtra por usuário logado. Todos os atendentes veem todas as conversas de todos os canais.

---

## Decisões de Design

### D1: Channel Ownership (`owner_user_id` em `channels`)
Adicionar `owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL` à tabela `channels`.

- Modelo: 1 usuário → 1 canal (Valéria, João)
- Admins (3 usuários com `role=admin`) → acesso a todos os canais/conversas
- Filtro aplicado na camada Next.js API (não RLS) para não quebrar queries com `service_role`

**Resolve Problema 3 e Problema 1** (Valéria não vê nem recebe updates de conversas do João).

### D2: Resumo de Qualificação gerado no handoff

Ponto de gatilho: chamada da ferramenta `encaminhar_humano` em `backend/app/agent/tools.py`.

**Fluxo:**
1. Ao chamar `encaminhar_humano`: buscar histórico completo da conversa da Valéria, gerar resumo estruturado via LLM (mesmo modelo do orchestrator)
2. Salvar resumo na tabela `lead_notes` com `author="qualificação-ia"` — registro permanente visível na sidebar para admins e João
3. Salvar também o resumo em `leads.metadata->>'handoff_summary'` para acesso eficiente sem JOINs extras
4. Quando a conversa do João é criada pela primeira vez (`get_or_create_conversation`): detectar se é nova → checar `leads.metadata->>'handoff_summary'` → inserir mensagem `sent_by="handoff_context"`, `role="system"` com o resumo
5. Frontend: detectar `sent_by === "handoff_context"` e renderizar como card "Contexto da Qualificação"

**Cobre automaticamente ambos os cenários:**
- Cenário 1: lead contata João → `get_or_create_conversation` é chamado no webhook → injeta resumo
- Cenário 2: `handoff_rescue` dispara → cria conversa do João → injeta resumo

---

## Componentes Afetados

### Backend
- `backend/migrations/YYYYMMDD_channel_owner.sql` — adiciona `owner_user_id` a `channels`
- `backend/app/agent/tools.py` — `encaminhar_humano`: gera resumo + salva em `lead_notes` + `metadata`
- `backend/app/conversations/service.py` — `get_or_create_conversation`: injeta mensagem de handoff_context em conversas novas

### Frontend
- `frontend/src/app/api/conversations/route.ts` — filtra por canais do usuário logado (vendedor) ou todos (admin)
- `frontend/src/components/conversas/message-bubble.tsx` — renderizar `handoff_context` como card especial
- `frontend/src/app/(authenticated)/canais/page.tsx` — interface para vincular `owner_user_id` a um canal

---

## Estrutura do Resumo de Qualificação

O LLM deve gerar um JSON estruturado que é serializado como markdown para exibição:

```
## Resumo da Qualificação — [data/hora]

**Interesse:** [categoria do produto identificada]
**Nome:** [nome do lead]
**Empresa:** [empresa, se coletado]
**CNPJ:** [se informado]

**Necessidades identificadas:**
- [ponto 1]
- [ponto 2]

**Observações para o vendedor:**
- [ponto relevante 1]
- [ponto relevante 2]

**Status da qualificação:** [qualificado / circuit breaker / opt-out]
```

---

## Restrições

- Não alterar a lógica do `dev_router` (opera antes do parsing)
- Não usar `localhost`/`127.0.0.1` em código de produção
- Não fazer push para master sem autorização do usuário
- Manter compatibilidade com canais que não têm `owner_user_id` (admin vê todos)
- O filtro de acesso deve ser na camada Next.js, não em RLS (queries com service_role continuam funcionando)
