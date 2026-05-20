# Multi-Channel AI Isolation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor o campo `mode` (`ai` | `human`) via API e frontend para que operadores possam cadastrar o novo número IA e visualizar/editar o modo de cada canal.

**Architecture:** O banco já tem a coluna `mode` com DEFAULT `'ai'` e CHECK constraint. O código Python já aplica o gate `channel.mode == 'human'`. Faltam apenas (1) o campo `mode` nos Pydantic models do backend e (2) o seletor de modo + badge no frontend `/canais`.

**Tech Stack:** FastAPI + Pydantic (backend), Next.js 14 App Router + TypeScript (frontend), pytest (testes).

---

## Arquivos Modificados

| Arquivo | Operação | Responsabilidade |
|---|---|---|
| `backend/app/channels/router.py` | Modificar | Adicionar `mode` a `ChannelCreate` e `ChannelUpdate` + validação |
| `backend/tests/test_channels_mode_api.py` | Criar | Testes de validação do campo `mode` na API |
| `frontend/src/app/(authenticated)/canais/page.tsx` | Modificar | Interface, formulário, tabela com `mode` |

---

## Task 1: Backend — Expor `mode` nos Pydantic models

**Files:**
- Modify: `backend/app/channels/router.py`
- Create: `backend/tests/test_channels_mode_api.py`

- [ ] **Step 1: Escrever o teste falhando**

Criar `backend/tests/test_channels_mode_api.py`:

```python
"""Tests for mode field validation in channels API models."""
import pytest
from pydantic import ValidationError
from app.channels.router import ChannelCreate, ChannelUpdate


def test_channel_create_default_mode_is_ai():
    body = ChannelCreate(
        name="Test",
        phone="5534999999999",
        provider="meta_cloud",
        provider_config={},
    )
    assert body.mode == "ai"


def test_channel_create_accepts_human():
    body = ChannelCreate(
        name="Vendedor",
        phone="5534999999999",
        provider="meta_cloud",
        provider_config={},
        mode="human",
    )
    assert body.mode == "human"


def test_channel_update_mode_none_by_default():
    body = ChannelUpdate()
    assert body.mode is None


def test_channel_update_accepts_mode_human():
    body = ChannelUpdate(mode="human")
    assert body.mode == "human"


def test_channel_update_accepts_mode_ai():
    body = ChannelUpdate(mode="ai")
    assert body.mode == "ai"
```

- [ ] **Step 2: Rodar para confirmar falha**

```
cd backend
pytest tests/test_channels_mode_api.py -v
```

Esperado: `FAILED` com `ValidationError` ou `unexpected keyword argument`.

- [ ] **Step 3: Implementar — adicionar `mode` aos Pydantic models**

Abrir `backend/app/channels/router.py`. Substituir as duas classes:

```python
class ChannelCreate(BaseModel):
    name: str
    phone: str
    provider: str  # "meta_cloud" | "evolution"
    provider_config: dict
    agent_profile_id: str | None = None
    mode: str = "ai"  # "ai" | "human"


class ChannelUpdate(BaseModel):
    name: str | None = None
    provider_config: dict | None = None
    agent_profile_id: str | None = None
    is_active: bool | None = None
    mode: str | None = None  # "ai" | "human"
```

E adicionar validação de `mode` nos dois endpoints. No `api_create_channel`:

```python
@router.post("")
async def api_create_channel(body: ChannelCreate):
    if body.provider not in ("meta_cloud", "evolution"):
        raise HTTPException(400, "Provider must be 'meta_cloud' or 'evolution'")
    if body.mode not in ("ai", "human"):
        raise HTTPException(400, "mode must be 'ai' or 'human'")
    return create_channel(body.model_dump(exclude_none=True))
```

No `api_update_channel`:

```python
@router.put("/{channel_id}")
async def api_update_channel(channel_id: str, body: ChannelUpdate):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(400, "No fields to update")
    if "mode" in data and data["mode"] not in ("ai", "human"):
        raise HTTPException(400, "mode must be 'ai' or 'human'")
    return update_channel(channel_id, data)
```

- [ ] **Step 4: Rodar testes para confirmar que passam**

```
cd backend
pytest tests/test_channels_mode_api.py -v
```

Esperado: todos `PASSED`.

- [ ] **Step 5: Garantir que testes existentes continuam passando**

```
cd backend
pytest tests/test_channels_service.py -v
```

Esperado: todos `PASSED`.

- [ ] **Step 6: Commit**

```
git add backend/app/channels/router.py backend/tests/test_channels_mode_api.py
git commit -m "feat(channels): expor campo mode (ai/human) na API de canais"
```

---

## Task 2: Frontend — Seletor de modo e badge na tabela

**Files:**
- Modify: `frontend/src/app/(authenticated)/canais/page.tsx`

Não há testes unitários de frontend neste projeto. Verificação é manual.

- [ ] **Step 1: Atualizar as interfaces TypeScript**

No topo do arquivo, localizar a interface `Channel` e adicionar `mode`:

```typescript
interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud" | "evolution";
  provider_config: Record<string, string>;
  agent_profile_id: string | null;
  agent_profiles: AgentProfile | null;
  is_active: boolean;
  mode: "ai" | "human";
  created_at: string;
}
```

Na interface `FormData`, adicionar `mode`:

```typescript
interface FormData {
  name: string;
  provider: "meta_cloud" | "evolution";
  phone: string;
  agent_profile_id: string;
  is_active: boolean;
  mode: "ai" | "human";
  // Evolution fields
  evo_api_url: string;
  evo_api_key: string;
  evo_instance: string;
  // Meta fields
  meta_phone_number_id: string;
  meta_access_token: string;
  meta_app_secret: string;
  meta_verify_token: string;
}
```

- [ ] **Step 2: Atualizar EMPTY_FORM e handleEdit**

Localizar `EMPTY_FORM` e adicionar `mode: "ai"`:

```typescript
const EMPTY_FORM: FormData = {
  name: "",
  provider: "evolution",
  phone: "",
  agent_profile_id: "",
  is_active: true,
  mode: "ai",
  evo_api_url: "",
  evo_api_key: "",
  evo_instance: "",
  meta_phone_number_id: "",
  meta_access_token: "",
  meta_app_secret: "",
  meta_verify_token: "",
};
```

Localizar `handleEdit` e adicionar `mode` na chamada `setForm`:

```typescript
const handleEdit = (ch: Channel) => {
  const config = ch.provider_config || {};
  setForm({
    name: ch.name,
    provider: ch.provider,
    phone: ch.phone || "",
    agent_profile_id: ch.agent_profile_id || "",
    is_active: ch.is_active,
    mode: ch.mode ?? "ai",
    evo_api_url: config.api_url || "",
    evo_api_key: config.api_key || "",
    evo_instance: config.instance || "",
    meta_phone_number_id: config.phone_number_id || "",
    meta_access_token: config.access_token || "",
    meta_app_secret: config.app_secret || "",
    meta_verify_token: config.verify_token || "",
  });
  setEditingId(ch.id);
  setShowForm(true);
};
```

- [ ] **Step 3: Incluir `mode` no body do POST/PUT**

Localizar `handleSave` e a constante `body`. Adicionar `mode: form.mode`:

```typescript
const body = {
  name: form.name,
  phone: form.provider === "meta_cloud" ? form.phone : "",
  provider: form.provider,
  provider_config: providerConfig,
  agent_profile_id: form.agent_profile_id || null,
  is_active: form.is_active,
  mode: form.mode,
};
```

- [ ] **Step 4: Adicionar seletor de modo no formulário**

No modal de criação/edição, após o bloco de "Agente IA" e antes do toggle "Ativo", inserir:

```tsx
{/* Channel Mode */}
<div>
  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">Modo do Canal</label>
  <div className="flex gap-2">
    <button
      type="button"
      onClick={() => setForm({ ...form, mode: "ai" })}
      className={`flex-1 px-3 py-2 rounded-[6px] text-[14px] border transition-colors ${
        form.mode === "ai"
          ? "bg-[#111111] text-white border-[#111111]"
          : "bg-white text-[#7b7b78] border-[#dedbd6] hover:border-[#111111]"
      }`}
    >
      IA
    </button>
    <button
      type="button"
      onClick={() => setForm({ ...form, mode: "human" })}
      className={`flex-1 px-3 py-2 rounded-[6px] text-[14px] border transition-colors ${
        form.mode === "human"
          ? "bg-[#111111] text-white border-[#111111]"
          : "bg-white text-[#7b7b78] border-[#dedbd6] hover:border-[#111111]"
      }`}
    >
      Humano
    </button>
  </div>
</div>
```

- [ ] **Step 5: Adicionar coluna "Modo" na tabela**

No `<thead>`, após a coluna "Agente", adicionar:

```tsx
<th className="px-4 py-3 text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] text-left font-normal">Modo</th>
```

No `<tbody>`, no map de canais, após a célula de agente, adicionar:

```tsx
<td className="px-4 py-3">
  {ch.mode === "human" ? (
    <span className="bg-[#faf9f6] border border-[#dedbd6] text-[#7b7b78] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px]">
      Humano
    </span>
  ) : (
    <span className="bg-[#0bdf50]/10 text-[#0bdf50] text-[11px] uppercase tracking-[0.6px] px-2 py-0.5 rounded-[4px] border border-[#0bdf50]/20">
      IA
    </span>
  )}
</td>
```

- [ ] **Step 6: Ajustar `colSpan` da linha vazia**

Localizar a linha de "Nenhum canal configurado" e atualizar `colSpan={7}` para `colSpan={8}` (nova coluna Modo).

- [ ] **Step 7: Verificação manual**

Iniciar o servidor dev:
```
cd frontend && npm run dev
```

Verificar:
1. Abrir `/canais` — coluna "Modo" aparece na tabela
2. Canal "Canastra Meta Cloud" exibe badge **Humano** (cinza)
3. Clicar Editar no canal — toggle mostra "Humano" selecionado, não "IA"
4. Clicar "Novo Canal" — toggle aparece com "IA" selecionado por padrão
5. Alterar para "Humano" e salvar — badge atualiza na tabela

- [ ] **Step 8: Commit**

```
git add frontend/src/app/\(authenticated\)/canais/page.tsx
git commit -m "feat(canais): adicionar seletor de modo AI/Humano e badge na tabela"
```

---

## Task 3: Cadastrar o Novo Canal IA (Operacional)

Este task é executado via interface, não via código.

- [ ] **Step 1: Obter dados do novo número no Meta Business Suite**

No [Meta Business Suite](https://business.facebook.com/) → WhatsApp Manager:
- Confirmar o número de telefone real associado ao Phone ID `1079773125220705`
- Confirmar que o webhook `https://<seu-dominio>/webhook/meta` está subscrito a esse número

- [ ] **Step 2: Cadastrar o canal via `/canais`**

Clicar "Novo Canal" e preencher:
- **Nome:** `Canastra IA — Atendimento Automatizado`
- **Provider:** `Meta Cloud API (Oficial)`
- **Telefone:** número real do Phone ID `1079773125220705`
- **Phone Number ID:** `1079773125220705`
- **Access Token:** mesmo system user token do canal existente (ou token específico)
- **App Secret:** mesmo App Secret da conta
- **Verify Token:** gerar um token **único** (ex: `canastra-ia-verify-2026`) — diferente do token do canal do vendedor
- **Agente IA:** selecionar o perfil desejado (ex: Agente Canastra — Reciprocidade)
- **Modo do Canal:** `IA`

- [ ] **Step 3: Configurar webhook no Meta para o novo número**

No Meta Business Suite → WhatsApp Manager → Configurações do número `1079773125220705`:
- URL do Webhook: `https://<seu-dominio>/webhook/meta`
- Verify Token: o token único definido no Step 2
- Campos subscritos: `messages`

- [ ] **Step 4: Verificar os dois canais na tabela**

| Canal | Modo | Resultado esperado |
|---|---|---|
| Canastra Meta Cloud (vendedor) | Humano | Badge cinza "Humano" |
| Canastra IA — Atendimento Automatizado | IA | Badge verde "IA" |

---

## Task 4: Testes de Validação Pré-Produção

- [ ] **Step 1: Testar isolamento do canal do vendedor**

Enviar uma mensagem de teste para `553491461669` (número do vendedor).

Verificar nos logs do backend:
```
[HUMAN CHANNEL] mode=human — IA e follow-up desativados channel_id=... phone=...
```
Não deve haver resposta da IA.

- [ ] **Step 2: Testar canal IA**

Enviar uma mensagem de teste para o novo número IA.

Verificar nos logs do backend que o agente é invocado e responde.

- [ ] **Step 3: Testar isolamento de histórico**

Usando o mesmo número de telefone de teste, enviar mensagem para ambos os canais.

No CRM (/conversas), verificar que existem duas conversas separadas para o lead — uma por canal — sem cruzamento de mensagens.

- [ ] **Step 4: Commit final (se houver ajustes)**

```
git add -p
git commit -m "chore: ajustes pós-validação de isolamento de canais"
```

---

## Ordem de Execução Recomendada

```
Task 1 (backend) → Task 2 (frontend) → commit → usuário testa dev → Task 3 (operacional) → Task 4 (validação)
```

Tasks 1 e 2 são independentes e podem ser executadas em paralelo.
