# Isolamento de Conversas e Controle de Acesso — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolar conversas por atendente (channel ownership), impedir acesso cruzado entre vendedor/qualificador, e injetar resumo estruturado de qualificação na conversa do João quando o lead é transferido.

**Architecture:** Adiciona `owner_user_id` à tabela `channels` para vincular cada canal a um usuário. O endpoint `/api/conversations` filtra por canais do usuário logado (admin vê tudo, vendedor vê só os seus). O hook `encaminhar_humano` gera um resumo via LLM e o armazena em `lead_notes` + `leads.metadata`. Quando a conversa do João é criada pela primeira vez (`get_or_create_conversation`), o resumo é injetado como mensagem `sent_by="handoff_context"`, renderizada no frontend como card especial.

**Tech Stack:** Python 3.11 / FastAPI / Supabase (PostgreSQL + Realtime) / Next.js 14 App Router / Tailwind CSS / OpenAI-compatible SDK (Gemini 2.5 Flash)

**Branch:** `feat/conversas-isolamento-acesso`

---

## File Map

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `backend/migrations/20260610_channel_owner_user.sql` | Criar | Adiciona `owner_user_id` à tabela `channels` |
| `backend/app/agent/summary.py` | Criar | Gera resumo estruturado da qualificação via LLM |
| `backend/tests/test_summary.py` | Criar | Testes unitários do gerador de resumo |
| `backend/app/agent/tools.py` | Modificar | `encaminhar_humano`: gera e armazena resumo no handoff |
| `backend/app/conversations/service.py` | Modificar | `get_or_create_conversation`: injeta `handoff_context` em conversas novas |
| `frontend/src/app/api/conversations/route.ts` | Modificar | Filtra conversas pelo usuário logado (owner de canal) |
| `frontend/src/app/(authenticated)/canais/page.tsx` | Modificar | Adiciona UI para vincular `owner_user_id` ao canal |
| `frontend/src/components/conversas/message-bubble.tsx` | Modificar | Renderiza `sent_by="handoff_context"` como card especial |

---

## Task 1: DB Migration — owner_user_id em channels

**Files:**
- Create: `backend/migrations/20260610_channel_owner_user.sql`

- [ ] **Step 1: Criar o arquivo de migration**

Criar `backend/migrations/20260610_channel_owner_user.sql` com o seguinte conteúdo:

```sql
-- Vincula cada canal a um usuário do Supabase Auth
-- NULL = canal sem dono (visível apenas para admins)
ALTER TABLE channels
  ADD COLUMN IF NOT EXISTS owner_user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_channels_owner_user_id ON channels(owner_user_id);

COMMENT ON COLUMN channels.owner_user_id IS
  'ID do usuário (auth.users) responsável por este canal. NULL = canal administrativo, visível apenas para admins.';
```

- [ ] **Step 2: Aplicar a migration via Supabase MCP (mcp__supabase-prod__apply_migration)**

Usar o tool `mcp__supabase-prod__apply_migration` com:
- `name`: `20260610_channel_owner_user`
- `query`: o conteúdo SQL acima

Confirmar que a migration foi aplicada sem erro.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/20260610_channel_owner_user.sql
git commit -m "feat(db): adiciona owner_user_id a channels para controle de acesso"
```

---

## Task 2: Backend — módulo de geração de resumo de qualificação

**Files:**
- Create: `backend/app/agent/summary.py`
- Create: `backend/tests/test_summary.py`

- [ ] **Step 1: Criar o módulo de resumo**

Criar `backend/app/agent/summary.py`:

```python
import logging
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM_PROMPT = """Você é um assistente que gera resumos objetivos de conversas de qualificação de leads.

Analise o histórico e gere um resumo em markdown com EXATAMENTE este formato (sem alterar os cabeçalhos):

## Resumo da Qualificação

**Interesse:** [categoria: atacado / private_label / exportacao / consumo / não identificado]
**Nome:** [nome informado ou "não informado"]
**Empresa:** [empresa ou "não informada"]
**CNPJ:** [CNPJ ou "não informado"]

**Necessidades identificadas:**
- [ponto 1 — máximo 3 pontos]

**Observações para o vendedor:**
- [ponto 1 — máximo 3 pontos]

**Status:** [qualificado e encaminhado / encaminhado por circuit breaker / opt-out registrado]

Seja direto. Inclua apenas informações explicitamente mencionadas na conversa."""


async def generate_qualification_summary(
    history: list[dict[str, Any]],
    lead: dict[str, Any],
    client: AsyncOpenAI,
    model: str,
) -> str:
    """Gera resumo estruturado da qualificação a partir do histórico da conversa.

    Args:
        history: lista de mensagens com campos role, content (de leads.service.get_history)
        lead: dict do lead com campos name, stage, company
        client: instância AsyncOpenAI (OpenAI ou Gemini-compat)
        model: nome do modelo a usar

    Returns:
        Resumo em markdown pronto para exibição.
    """
    if not history:
        return "## Resumo da Qualificação\n\n*Nenhuma mensagem encontrada no histórico.*"

    lines = []
    for m in history:
        role = m.get("role", "")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            label = "Lead" if role == "user" else "Valéria"
            lines.append(f"[{label}]: {content}")

    if not lines:
        return "## Resumo da Qualificação\n\n*Histórico sem mensagens relevantes.*"

    lead_name = lead.get("name") or "não informado"
    lead_stage = lead.get("stage") or "não identificado"
    context = (
        f"Informações do lead — Nome: {lead_name} | Segmento identificado: {lead_stage}\n\n"
        f"Histórico da conversa:\n" + "\n".join(lines)
    )

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            max_tokens=600,
            temperature=0.2,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("generate_qualification_summary: falha na chamada LLM: %s", exc, exc_info=True)
        return f"## Resumo da Qualificação\n\n*Erro ao gerar resumo automático.*\n\nSegmento: {lead_stage} | Nome: {lead_name}"
```

- [ ] **Step 2: Criar os testes unitários**

Criar `backend/tests/__init__.py` (arquivo vazio se não existir) e `backend/tests/test_summary.py`:

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.agent.summary import generate_qualification_summary


def _make_client(response_text: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = response_text
    completion = MagicMock()
    completion.choices = [choice]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=completion)
    return client


@pytest.mark.asyncio
async def test_empty_history_returns_fallback():
    client = _make_client("irrelevante")
    result = await generate_qualification_summary([], {}, client, "gpt-4o-mini")
    assert "Resumo da Qualificação" in result
    assert "Nenhuma mensagem" in result


@pytest.mark.asyncio
async def test_history_without_user_or_assistant_returns_fallback():
    history = [{"role": "system", "content": "stage alterado"}]
    client = _make_client("irrelevante")
    result = await generate_qualification_summary(history, {}, client, "gpt-4o-mini")
    assert "Resumo da Qualificação" in result
    assert "sem mensagens relevantes" in result


@pytest.mark.asyncio
async def test_calls_llm_and_returns_response():
    history = [
        {"role": "user", "content": "Quero comprar café"},
        {"role": "assistant", "content": "Qual é o seu interesse?"},
        {"role": "user", "content": "Atacado, minha empresa é Padaria XYZ"},
    ]
    lead = {"name": "Carlos", "stage": "atacado"}
    expected = "## Resumo da Qualificação\n\n**Interesse:** atacado"
    client = _make_client(expected)

    result = await generate_qualification_summary(history, lead, client, "gemini-2.5-flash")

    assert result == expected
    client.chat.completions.create.assert_called_once()
    call_kwargs = client.chat.completions.create.call_args
    # Verifica que o contexto incluiu o nome do lead
    messages_sent = call_kwargs.kwargs["messages"]
    user_msg = next(m for m in messages_sent if m["role"] == "user")
    assert "Carlos" in user_msg["content"]
    assert "atacado" in user_msg["content"]
    assert "[Lead]: Quero comprar café" in user_msg["content"]


@pytest.mark.asyncio
async def test_llm_failure_returns_graceful_fallback():
    from openai import APIError
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("timeout"))
    lead = {"name": "Ana", "stage": "private_label"}

    result = await generate_qualification_summary(
        [{"role": "user", "content": "Interesse em private label"}],
        lead,
        client,
        "gemini-2.5-flash",
    )

    assert "Resumo da Qualificação" in result
    assert "Erro" in result
```

- [ ] **Step 3: Instalar pytest-asyncio se necessário e rodar os testes**

```bash
cd backend
pip install pytest pytest-asyncio --quiet
python -m pytest tests/test_summary.py -v
```

Saída esperada: 4 testes PASSED.

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/summary.py backend/tests/__init__.py backend/tests/test_summary.py
git commit -m "feat(agent): módulo de geração de resumo de qualificação com testes"
```

---

## Task 3: Backend — hook de resumo no encaminhar_humano

**Files:**
- Modify: `backend/app/agent/tools.py`

O bloco `elif tool_name == "encaminhar_humano":` começa na linha 222 e termina com `return f"Lead encaminhado para {vendedor}"` na linha 276. Adicionar a geração de resumo após o `save_message` de encaminhamento (linha 247) e antes do bloco de `channel`.

- [ ] **Step 1: Adicionar imports no topo de tools.py**

Adicionar ao bloco de imports existente (após as imports já presentes na linha 11):

```python
from app.conversations.service import get_history as get_conversation_history
```

(Note: `get_history` já importado de `leads.service` toma `lead_id`. Aqui adicionamos o de `conversations.service` que toma `conversation_id`.)

- [ ] **Step 2: Inserir geração de resumo em encaminhar_humano**

Localizar a linha:
```python
        save_message(lead_id, "system", f"[encaminhar_humano] Lead encaminhado para {vendedor}: {motivo}", conversation_id=conversation_id)
```

Logo **após** essa linha (antes de `channel = get_channel_for_lead(lead_id)`), adicionar:

```python
        # Gera e armazena resumo estruturado da qualificação
        try:
            from app.agent.summary import generate_qualification_summary
            from app.agent.orchestrator import _get_client, DEFAULT_MODEL
            from app.db.supabase import get_supabase
            conv_history = get_conversation_history(conversation_id, limit=100)
            fresh_lead = get_lead(lead_id) or {}
            _model = DEFAULT_MODEL
            summary_text = await generate_qualification_summary(
                conv_history, fresh_lead, _get_client(_model), _model
            )
            _sb = get_supabase()
            _sb.table("lead_notes").insert({
                "lead_id": lead_id,
                "author": "qualificação-ia",
                "content": summary_text,
            }).execute()
            existing_meta = dict(fresh_lead.get("metadata") or {})
            existing_meta["handoff_summary"] = summary_text
            update_lead(lead_id, metadata=existing_meta)
            logger.info("encaminhar_humano: resumo de qualificação salvo para lead %s", lead_id)
        except Exception as _exc:
            logger.error(
                "encaminhar_humano: falha ao gerar/salvar resumo para lead %s: %s",
                lead_id, _exc, exc_info=True,
            )
```

- [ ] **Step 3: Verificar manualmente que não há erros de sintaxe**

```bash
cd backend
python -c "from app.agent.tools import execute_tool; print('OK')"
```

Saída esperada: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/agent/tools.py
git commit -m "feat(agent): gerar e armazenar resumo de qualificação no handoff"
```

---

## Task 4: Backend — injetar handoff_context em novas conversas

**Files:**
- Modify: `backend/app/conversations/service.py`

A função `get_or_create_conversation` está na linha 25. Quando a conversa é **criada** (não encontrada), deve injetar uma mensagem `sent_by="handoff_context"` se o lead tiver `metadata->>'handoff_summary'`.

- [ ] **Step 1: Modificar get_or_create_conversation**

Substituir o bloco atual da função:

```python
def get_or_create_conversation(lead_id: str, channel_id: str) -> dict[str, Any]:
    """Get existing conversation or create new one for lead+channel pair."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .execute()
    )

    if result.data:
        return result.data[0]

    new_conv = {
        "lead_id": lead_id,
        "channel_id": channel_id,
        "stage": "secretaria",
        "status": "active",
    }
    result = sb.table("conversations").insert(new_conv).execute()
    return result.data[0]
```

Por:

```python
def get_or_create_conversation(lead_id: str, channel_id: str) -> dict[str, Any]:
    """Get existing conversation or create new one for lead+channel pair."""
    sb = get_supabase()
    result = (
        sb.table("conversations")
        .select("*")
        .eq("lead_id", lead_id)
        .eq("channel_id", channel_id)
        .execute()
    )

    if result.data:
        return result.data[0]

    new_conv = {
        "lead_id": lead_id,
        "channel_id": channel_id,
        "stage": "secretaria",
        "status": "active",
    }
    result = sb.table("conversations").insert(new_conv).execute()
    conversation = result.data[0]

    # Injeta contexto de qualificação se o lead foi encaminhado pela Valéria
    try:
        lead_result = (
            sb.table("leads")
            .select("metadata")
            .eq("id", lead_id)
            .single()
            .execute()
        )
        lead_meta = (lead_result.data or {}).get("metadata") or {}
        handoff_summary = lead_meta.get("handoff_summary")
        if handoff_summary:
            sb.table("messages").insert({
                "conversation_id": conversation["id"],
                "lead_id": lead_id,
                "role": "system",
                "content": handoff_summary,
                "sent_by": "handoff_context",
                "stage": "secretaria",
            }).execute()
            logger.info(
                "get_or_create_conversation: handoff_context injetado para lead %s conv %s",
                lead_id, conversation["id"],
            )
    except Exception as exc:
        logger.warning(
            "get_or_create_conversation: falha ao injetar handoff_context para lead %s: %s",
            lead_id, exc,
        )

    return conversation
```

- [ ] **Step 2: Verificar importações**

O `logger` já está declarado no topo do arquivo (`logger = logging.getLogger(__name__)`). Não há imports adicionais necessários.

```bash
cd backend
python -c "from app.conversations.service import get_or_create_conversation; print('OK')"
```

Saída esperada: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/conversations/service.py
git commit -m "feat(conversations): injetar resumo de qualificação como handoff_context em novas conversas"
```

---

## Task 5: Next.js API — filtrar conversas por usuário logado

**Files:**
- Modify: `frontend/src/app/api/conversations/route.ts`

A função `GET` usa `getServiceSupabase()` e não filtra por usuário. Adicionar lógica de obtenção do usuário logado e filtro por canais do seu ownership.

- [ ] **Step 1: Adicionar import do server client**

Adicionar no topo de `frontend/src/app/api/conversations/route.ts`, após as imports já existentes:

```typescript
import { createClient as createServerClient } from "@/lib/supabase/server";
```

- [ ] **Step 2: Adicionar bloco de filtro por usuário na função GET**

Localizar o trecho no início da função `GET`:

```typescript
export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");
  const status = searchParams.get("status");

  // 1. Get DB conversations
  let dbQuery = supabase
    .from("conversations")
    .select(
```

Substituir por:

```typescript
export async function GET(request: NextRequest) {
  const supabase = await getServiceSupabase();
  const { searchParams } = new URL(request.url);
  const channelId = searchParams.get("channel_id");
  const status = searchParams.get("status");

  // Determina quais channel_ids o usuário logado pode ver
  let allowedChannelIds: string[] | null = null; // null = sem restrição (admin)
  try {
    const userClient = await createServerClient();
    const { data: { user } } = await userClient.auth.getUser();
    const role = user?.app_metadata?.role as string | undefined;
    if (user && role !== "admin") {
      // vendedor: apenas os canais que possui (owner_user_id = user.id)
      const { data: ownedChannels } = await supabase
        .from("channels")
        .select("id")
        .eq("owner_user_id", user.id);
      allowedChannelIds = (ownedChannels || []).map((c: { id: string }) => c.id);
    }
  } catch {
    // Se não conseguir autenticar, bloqueia tudo — nunca exibir dados sensíveis sem auth
    allowedChannelIds = [];
  }

  // 1. Get DB conversations
  let dbQuery = supabase
    .from("conversations")
    .select(
```

- [ ] **Step 3: Aplicar o filtro na query DB**

Localizar o trecho logo após o `.select(...)`:

```typescript
  if (channelId) dbQuery = dbQuery.eq("channel_id", channelId);
  if (status) dbQuery = dbQuery.eq("status", status);
```

Substituir por:

```typescript
  if (channelId) dbQuery = dbQuery.eq("channel_id", channelId);
  if (status) dbQuery = dbQuery.eq("status", status);
  // Restringe ao conjunto de canais permitidos para o usuário logado
  if (allowedChannelIds !== null) {
    if (allowedChannelIds.length === 0) {
      // Usuário não tem nenhum canal — retorna lista vazia imediatamente
      return NextResponse.json([]);
    }
    dbQuery = dbQuery.in("channel_id", allowedChannelIds);
  }
```

- [ ] **Step 4: Aplicar o mesmo filtro na query de Evolution channels**

Localizar:

```typescript
  let channelsQuery = supabase
    .from("channels")
    .select("id, name, phone, provider, provider_config, mode")
    .eq("provider", "evolution")
    .eq("is_active", true);

  if (channelId) channelsQuery = channelsQuery.eq("id", channelId);
```

Substituir por:

```typescript
  let channelsQuery = supabase
    .from("channels")
    .select("id, name, phone, provider, provider_config, mode")
    .eq("provider", "evolution")
    .eq("is_active", true);

  if (channelId) channelsQuery = channelsQuery.eq("id", channelId);
  if (allowedChannelIds !== null && allowedChannelIds.length > 0) {
    channelsQuery = channelsQuery.in("id", allowedChannelIds);
  }
```

- [ ] **Step 5: Verificar tipos — nenhum novo erro de TypeScript**

```bash
cd frontend
npx tsc --noEmit 2>&1 | head -30
```

Saída esperada: sem erros em `app/api/conversations/route.ts`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app/api/conversations/route.ts
git commit -m "feat(api): filtrar conversas por canal do usuário logado"
```

---

## Task 6: Frontend — UI de atribuição de owner no canal

**Files:**
- Modify: `frontend/src/app/(authenticated)/canais/page.tsx`

Adicionar um campo "Responsável" no formulário de edição/criação de canal para vincular um usuário como `owner_user_id`.

- [ ] **Step 1: Adicionar owner_user_id ao tipo Channel e FormData**

Localizar o tipo `Channel` no início do arquivo:

```typescript
interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud";
  provider_config: Record<string, string>;
  is_active: boolean;
  mode: "ai" | "human";
  created_at: string;
}
```

Substituir por:

```typescript
interface Channel {
  id: string;
  name: string;
  phone: string;
  provider: "meta_cloud";
  provider_config: Record<string, string>;
  is_active: boolean;
  mode: "ai" | "human";
  owner_user_id: string | null;
  created_at: string;
}

interface CrmUser {
  id: string;
  email: string;
  name: string;
}
```

Localizar `interface FormData` e adicionar o campo:

```typescript
interface FormData {
  name: string;
  phone: string;
  is_active: boolean;
  mode: "ai" | "human";
  meta_phone_number_id: string;
  owner_user_id: string;
}
```

Localizar `const EMPTY_FORM` e adicionar o campo:

```typescript
const EMPTY_FORM: FormData = {
  name: "",
  phone: "",
  is_active: true,
  mode: "ai",
  meta_phone_number_id: "",
  owner_user_id: "",
};
```

- [ ] **Step 2: Carregar lista de usuários e adicioná-la ao estado**

Localizar a linha `const [saving, setSaving] = useState(false);` e adicionar após:

```typescript
  const [users, setUsers] = useState<CrmUser[]>([]);
```

Localizar a função `fetchChannels` e adicionar após ela:

```typescript
  const fetchUsers = useCallback(async () => {
    try {
      const res = await fetch("/api/users");
      if (res.ok) setUsers(await res.json());
    } catch { /* silently ignore */ }
  }, []);
```

Localizar o `useEffect` que chama `fetchChannels()`:

```typescript
  useEffect(() => {
    fetchChannels();
  }, [fetchChannels]);
```

Substituir por:

```typescript
  useEffect(() => {
    fetchChannels();
    fetchUsers();
  }, [fetchChannels, fetchUsers]);
```

- [ ] **Step 3: Incluir owner_user_id no corpo do save**

Localizar dentro de `handleSave`:

```typescript
    const body = {
      name: form.name,
      phone: form.phone,
      provider: "meta_cloud",
      provider_config: { phone_number_id: form.meta_phone_number_id },
      is_active: form.is_active,
      mode: form.mode,
    };
```

Substituir por:

```typescript
    const body = {
      name: form.name,
      phone: form.phone,
      provider: "meta_cloud",
      provider_config: { phone_number_id: form.meta_phone_number_id },
      is_active: form.is_active,
      mode: form.mode,
      owner_user_id: form.owner_user_id || null,
    };
```

- [ ] **Step 4: Preencher owner_user_id no handleEdit**

Localizar dentro de `handleEdit`:

```typescript
    setForm({
      name: ch.name,
      phone: ch.phone || "",
      is_active: ch.is_active,
      mode: ch.mode ?? "ai",
      meta_phone_number_id: config.phone_number_id || "",
    });
```

Substituir por:

```typescript
    setForm({
      name: ch.name,
      phone: ch.phone || "",
      is_active: ch.is_active,
      mode: ch.mode ?? "ai",
      meta_phone_number_id: config.phone_number_id || "",
      owner_user_id: ch.owner_user_id || "",
    });
```

- [ ] **Step 5: Adicionar o campo "Responsável" no formulário JSX**

No formulário de edição/criação do canal, localizar o campo do modo (buscar por `"Modo"` ou `mode`) dentro do formulário de edição. Adicionar o campo "Responsável" após o campo de modo. Buscar o elemento de formulário existente que controla `mode` e adicionar após ele:

```tsx
              <div>
                <label className="block text-[13px] text-[#7b7b78] mb-1">
                  Responsável (vendedor/atendente)
                </label>
                <select
                  value={form.owner_user_id}
                  onChange={(e) => setForm({ ...form, owner_user_id: e.target.value })}
                  className="w-full border border-[#dedbd6] rounded-[4px] px-3 py-2 text-[14px] text-[#111111] bg-white focus:outline-none focus:border-[#111111]"
                >
                  <option value="">— Nenhum (somente admins) —</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name || u.email}
                    </option>
                  ))}
                </select>
                <p className="text-[12px] text-[#7b7b78] mt-1">
                  Vendedores só veem conversas dos seus canais. Admins veem tudo.
                </p>
              </div>
```

- [ ] **Step 6: Verificar tipos sem erros**

```bash
cd frontend
npx tsc --noEmit 2>&1 | head -30
```

Saída esperada: sem erros em `canais/page.tsx`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/(authenticated)/canais/page.tsx
git commit -m "feat(canais): adicionar campo de responsável (owner_user_id) por canal"
```

---

## Task 7: Frontend — renderizar card de contexto de qualificação

**Files:**
- Modify: `frontend/src/components/conversas/message-bubble.tsx`

Mensagens com `sent_by === "handoff_context"` devem ser renderizadas como um card amarelo/âmbar distinto, não como uma bolha de chat.

- [ ] **Step 1: Adicionar renderização especial no componente MessageBubble**

Localizar a função `MessageBubble` (linha 97) logo após a linha:

```typescript
  const isReaction = message.message_type === "reaction";
```

Adicionar logo após (antes do bloco `const mediaSrc = ...`):

```typescript
  // Contexto de qualificação: card especial, não bolha de chat
  if (message.sent_by === "handoff_context") {
    return (
      <div className="mx-2 my-3">
        <div className="rounded-[8px] border border-[#d4a840]/40 bg-[#fffbeb] p-4 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <svg
              className="w-4 h-4 text-[#b07d10] flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={1.8}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <span className="text-[11px] font-semibold text-[#7b5a00] uppercase tracking-wider">
              Contexto da Qualificação
            </span>
          </div>
          <div className="text-[13px] text-[#3d2e00] whitespace-pre-wrap leading-relaxed">
            {message.content}
          </div>
          <div className="mt-3 text-[11px] text-[#9a7a20]">
            {formatTimeOnly(message.created_at)}
          </div>
        </div>
      </div>
    );
  }
```

- [ ] **Step 2: Verificar tipos sem erros**

```bash
cd frontend
npx tsc --noEmit 2>&1 | head -30
```

Saída esperada: sem erros em `message-bubble.tsx`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversas/message-bubble.tsx
git commit -m "feat(conversas): renderizar card de contexto de qualificação no chat do vendedor"
```

---

## Verificação Final

- [ ] **Verificar que o build do frontend compila sem erros**

```bash
cd frontend
npm run build 2>&1 | tail -20
```

Saída esperada: `✓ Compiled successfully` (ou equivalente sem erros).

- [ ] **Verificar que os testes do backend passam**

```bash
cd backend
python -m pytest tests/test_summary.py -v
```

Saída esperada: 4 testes PASSED.

- [ ] **Verificar no Supabase que a coluna existe**

Usar `mcp__supabase-prod__execute_sql` com:
```sql
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'channels' AND column_name = 'owner_user_id';
```

Saída esperada: 1 linha com `owner_user_id | uuid | YES`.

- [ ] **Commit final de verificação (se houver ajustes)**

```bash
git add -p
git commit -m "fix: ajustes pós-verificação do isolamento de conversas"
```

---

## Ordem de Execução para Subagents

**Grupo 1 (sequencial, fundação):**
- Task 1 — Migration DB (obrigatório primeiro)

**Grupo 2 (paralelo após Task 1):**
- Task 2 — Módulo de resumo (summary.py + testes)
- Task 5 — API Next.js filtro de conversas
- Task 6 — UI Canais
- Task 7 — Card handoff_context

**Grupo 3 (após Task 2):**
- Task 3 — Hook encaminhar_humano (depende de summary.py)

**Grupo 4 (após Task 3):**
- Task 4 — Injeção em get_or_create_conversation (depende do hook)
