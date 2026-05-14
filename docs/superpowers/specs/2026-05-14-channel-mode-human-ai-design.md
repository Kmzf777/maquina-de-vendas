# Channel Mode: Human vs AI — Design Spec

**Data:** 2026-05-14
**Branch:** fix/channel-mode-human-ai (a criar)
**Status:** Aprovado pelo usuário

---

## Contexto

O sistema atualmente não possui um gate por canal para controle de IA. O controle existente opera em dois níveis:

- **Global:** `VALERIA_ENABLED` (hardcoded em `processor.py`)
- **Por lead:** `lead.ai_enabled` (fonte de verdade per-lead)
- **Por conversa:** `conversation.followup_enabled` (follow-up)

O canal comercial atual (usado por vendedores humanos) precisa desativar completamente qualquer automação de LLM/IA. Um novo número será adicionado à Meta exclusivamente para a IA.

---

## Objetivo

1. Desativar Valeria e follow-up automático no canal comercial atual.
2. Introduzir separação estrutural clara entre **canal humano** e **canal IA**.
3. Garantir que broadcasts no canal humano nunca reativem a IA nos leads.

---

## Banco de Dados

### Migration

```sql
ALTER TABLE channels
  ADD COLUMN mode TEXT NOT NULL DEFAULT 'ai'
  CHECK (mode IN ('ai', 'human'));
```

- Default `'ai'` — todos os canais existentes ficam com comportamento atual (sem quebra).
- Aplicar via Supabase MCP / dashboard após aprovação do spec.

### Atualização do canal atual

```sql
UPDATE channels SET mode = 'human' WHERE id = '<phone_number_id_atual>';
```

Executar após a migration e deploy do backend.

---

## Backend — Pontos de Bloqueio

### 1. `backend/app/buffer/processor.py`

**Onde:** logo após `get_channel_by_id`, antes de qualquer gate de IA.

```python
if channel.get("mode", "ai") == "human":
    logger.info(
        f"[HUMAN CHANNEL] mode=human — IA e follow-up desativados "
        f"channel_id={channel_id} phone={phone}"
    )
    _update_last_msg(conversation["id"])
    return
```

**Efeito:** Para canais `mode='human'`, o processador salva a mensagem do usuário, atualiza unread_count, e retorna — nunca chama `run_agent` nem agenda follow-up.

### 2. `backend/app/follow_up/scheduler.py`

**Onde:** dentro do loop `process_due_followups`, logo após o guard de `followup_enabled`.

```python
if channel.get("mode", "ai") == "human":
    _cancel_job(job["id"], "human_channel")
    logger.info(
        f"[FOLLOWUP] mode=human — cancelando seq={sequence} conversation={conversation_id}"
    )
    continue
```

**Pré-requisito:** o select em `follow_up/service.py` (função `get_due_followups`) precisa incluir `mode` no join de canais:

```python
"channels!inner(id, name, provider, provider_config, mode)"
```

**Efeito:** Jobs de follow-up agendados antes da mudança de modo também são cancelados.

### 3. `backend/app/broadcast/worker.py`

**Onde:** função `_broadcast_ai_enabled`, adicionar parâmetro `channel`.

```python
def _broadcast_ai_enabled(broadcast: dict, channel: dict | None = None) -> bool:
    """Returns the ai_enabled value to set on the lead for this broadcast.

    Invariant: human channel → always False; ai channel with agent → True.
    """
    if channel and channel.get("mode", "ai") == "human":
        return False
    return bool(broadcast.get("agent_profile_id"))
```

Passar o canal na chamada existente (o worker já tem acesso ao canal).

**Efeito:** Disparos no canal humano nunca setam `lead.ai_enabled=True`, mesmo que o broadcast tenha um `agent_profile_id`.

---

## Invariantes

| Canal | Valeria responde? | Follow-up automático? | Broadcast seta ai_enabled? |
|-------|:-----------------:|:---------------------:|:--------------------------:|
| `mode='ai'` | Sim (se `lead.ai_enabled=True`) | Sim (se `followup_enabled=True`) | Sim (se broadcast tem agent) |
| `mode='human'` | **Nunca** | **Nunca** | **Nunca** |

---

## O que NÃO muda

- Vendedores podem enviar mensagens manualmente (via `/api/channels/{id}/send`) em qualquer modo.
- Disparos (broadcasts) continuam funcionando em canais `mode='human'` — apenas sem automação de resposta.
- `lead.ai_enabled` e `conversation.followup_enabled` continuam existindo; o gate de canal é apenas uma camada adicional antes deles.
- Frontend: nenhuma alteração nesta branch.

---

## Sequência de Deploy

1. Criar branch `fix/channel-mode-human-ai`
2. Implementar as mudanças de backend
3. Commitar e testar no dev
4. Usuário aplica migration SQL via Supabase MCP
5. Usuário atualiza o canal atual para `mode='human'`
6. Usuário autoriza push para master
7. Novo número da Meta é adicionado como canal com `mode='ai'`
