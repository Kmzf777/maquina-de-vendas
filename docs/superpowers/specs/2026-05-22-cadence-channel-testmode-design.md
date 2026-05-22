# Design: Canal por Cadência + Modo de Teste SSE

**Data:** 2026-05-22
**Status:** Aprovado

---

## Contexto

Cadências (campanhas de flow builder) não têm canal WhatsApp vinculado. O engine resolve o canal pelo lead, o que pode mandar pelo canal errado. Além disso, não existe forma de testar uma cadência antes de ativá-la em produção.

---

## Feature 1 — Canal por Cadência + Override por Nó

### Banco de Dados

```sql
-- Adicionar à tabela campaigns
ALTER TABLE campaigns
  ADD COLUMN IF NOT EXISTS channel_id UUID REFERENCES channels(id) ON DELETE SET NULL;

-- Limpar cadências existentes (ambiente de desenvolvimento)
DELETE FROM campaign_enrollments;
DELETE FROM campaign_nodes;
DELETE FROM campaigns;
```

### API — `POST /api/campaigns`

Aceitar e persistir `channel_id` no body:

```json
{ "name": "Follow-up Atacado", "channel_id": "uuid-do-canal", "priority": 5, "frequency_cap": 1 }
```

### Frontend — Modal "Nova Cadência"

- Dropdown "Canal padrão" obrigatório, carregando `GET /api/channels` (apenas canais com `status = "connected"`)
- Não permite criar sem canal selecionado
- Campos existentes mantidos: nome, prioridade, frequency_cap

### Frontend — Inspector (nós `send` e `send_text`)

- Campo "Canal (override)" — select com "— Usar padrão da cadência —" + lista de canais
- Valor salvo em `node.config.channel_id` (UUID ou null/vazio = usar padrão)

### Backend — Engine (`automation/engine.py`)

Resolução de canal em `_execute_send` e `_execute_send_text`:

```
1. node.config.channel_id (override explícito no nó)
2. campaign.channel_id (padrão da cadência)
3. ValueError → retry (nunca cai para canal do lead)
```

`get_due_enrollments()` deve incluir `campaigns!inner(channel_id, ...)` no select.

---

## Feature 2 — Modo de Teste SSE

### Fluxo do Usuário

1. Botão "⚡ Testar" no topbar do flow builder
2. Modal com:
   - Input de telefone (formato `5511999990000`)
   - Checkbox "Pular delays" — marcado por padrão
3. Clica "Executar" → modal fecha, painel de execução aparece no lugar do Inspector
4. Nós animam em tempo real enquanto o SSE recebe eventos
5. Botão "Fechar teste" restaura o estado normal do flow builder

### Backend — `GET /api/campaigns/{id}/test`

Endpoint SSE via `StreamingResponse` + `media_type="text/event-stream"`.

Recebe query params: `phone` e `skip_delays` (bool, default true).

**Algoritmo:**
1. Buscar lead pelo telefone (`leads.phone = phone`). Se não encontrar: criar lead temporário com `name="Teste"`, `phone=phone`, `env_tag=_ENV_TAG`, marcar com tag interna `_test_lead=true`.
2. Carregar campanha com seus nós e `channel_id`.
3. Percorrer nós em sequência a partir do nó trigger (ou primeiro nó com `type != "trigger"`).
4. Para cada nó:
   - Emitir `{"node_id": "...", "status": "running"}`
   - Executar lógica real do nó (usando o engine)
   - Emitir `{"node_id": "...", "status": "done"|"failed", "log": "...", "duration_ms": N}`
5. Nó `wait` com `skip_delays=true`: esperar 800ms simbólico.
6. Nó `condition`: executar condição real, seguir o branch correto, logar qual caminho tomou.
7. Ao terminar: emitir `{"node_id": null, "status": "finished"}` e fechar stream.
8. Limpar lead temporário se criado (DELETE após encerrar stream).

**Formato de evento SSE:**
```
data: {"node_id": "abc123", "status": "running"}\n\n
data: {"node_id": "abc123", "status": "done", "log": "Template reativacao_30d enviado", "duration_ms": 312}\n\n
data: {"node_id": "xyz456", "status": "failed", "log": "Nenhum canal encontrado para o lead", "duration_ms": 48}\n\n
data: {"node_id": null, "status": "finished"}\n\n
```

### Frontend — Estados Visuais dos Nós

| Estado | Visual |
|---|---|
| Neutro | Aparência normal |
| Running | Borda pulsando laranja (`#E85D26`) + spinner animado no canto superior direito do nó |
| Done | Borda verde (`#1A9B6C`) + ✓ no canto |
| Failed | Borda vermelha (`#ef4444`) + ✗ no canto |

Os estados são gerenciados via `testNodeStates: Record<string, "running"|"done"|"failed">` no `FlowBuilderInner`.

Os nós React Flow recebem `testState` via `data` e renderizam o overlay de status.

### Frontend — Painel de Execução

Aparece no lugar do Inspector (lado direito, mesma largura 256px):

- Header: "⚡ Execução de Teste" + botão "Fechar"
- Lista de eventos conforme chegam:
  - Ícone de status (spinner / ✓ / ✗)
  - Nome do nó (via NODE_META)
  - Log em texto
  - Duração em ms
- Nó com falha: log em vermelho expandível
- Ao receber `finished`: botão "Testar novamente" aparece

### Router (`automation/router.py`)

Adicionar o endpoint de teste ao router de automação existente:

```python
@router.get("/campaigns/{campaign_id}/test")
async def test_campaign(campaign_id: str, phone: str, skip_delays: bool = True):
    return StreamingResponse(
        _run_test(campaign_id, phone, skip_delays),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

---

## O que NÃO está no escopo

- Analytics de testes (histórico de execuções)
- Múltiplos leads simultâneos no teste
- Dry-run sem envio real
