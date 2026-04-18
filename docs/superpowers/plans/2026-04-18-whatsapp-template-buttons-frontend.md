# WhatsApp Template Buttons Frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar seção de botões QUICK_REPLY opcionais (máx 3) no modal de criação de templates WhatsApp.

**Architecture:** Todas as mudanças estão em um único componente React (`create-template-modal.tsx`). O estado de botões usa `ButtonItem[]` com IDs estáveis para evitar bugs de re-render. A validação de duplicatas e variáveis ocorre no `handleSubmit` antes de chamar a API. O componente BUTTONS é incluído no payload apenas quando há botões válidos.

**Tech Stack:** React (useState), TypeScript, Tailwind CSS, Next.js App Router, `crypto.randomUUID()` (sem imports adicionais).

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `frontend/src/components/canais/create-template-modal.tsx` | Modificar — único arquivo alterado |

---

## Task 1: Tipo, estado, handlers e reset

**Files:**
- Modify: `frontend/src/components/canais/create-template-modal.tsx`

- [ ] **Step 1: Adicionar o tipo `ButtonItem` após `type ModalStep`**

No arquivo, após a linha `type ModalStep = "form" | "review";`, adicione:

```ts
type ButtonItem = { id: string; text: string };
```

- [ ] **Step 2: Adicionar o estado `buttons` após os estados existentes**

Após a linha `const [selectedChannelId, setSelectedChannelId] = useState("");`, adicione:

```ts
const [buttons, setButtons] = useState<ButtonItem[]>([]);
```

- [ ] **Step 3: Adicionar os três handlers após `activeChannelId`**

Após a linha `const activeChannelId = channelId ?? selectedChannelId;`, adicione:

```ts
const addButton = () => {
  setButtons(prev =>
    prev.length < 3 ? [...prev, { id: crypto.randomUUID(), text: "" }] : prev
  );
};

const updateButton = (id: string, value: string) => {
  const sanitized = value.replace(/[{}]/g, "");
  setButtons(prev =>
    prev.map(b => b.id === id ? { ...b, text: sanitized } : b)
  );
};

const removeButton = (id: string) => {
  setButtons(prev => prev.filter(b => b.id !== id));
};
```

- [ ] **Step 4: Atualizar `resetAndClose` para limpar `buttons`**

Substitua a função `resetAndClose` por:

```ts
const resetAndClose = () => {
  setStep("form");
  setForm(EMPTY_FORM);
  setButtons([]);
  setError(null);
  setPendingTemplateId(null);
  setSuggestedCategory(null);
  setSelectedChannelId("");
  onClose();
};
```

- [ ] **Step 5: Verificar que o arquivo compila sem erros**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros de tipo relacionados a `ButtonItem`, `buttons`, `addButton`, `updateButton`, `removeButton`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: add ButtonItem state and handlers for QUICK_REPLY buttons"
```

---

## Task 2: Validação e payload no handleSubmit

**Files:**
- Modify: `frontend/src/components/canais/create-template-modal.tsx`

- [ ] **Step 1: Substituir `handleSubmit` completo**

Substitua toda a função `handleSubmit` por:

```ts
const handleSubmit = async () => {
  if (!activeChannelId) {
    setError("Selecione um canal.");
    return;
  }
  if (!form.name.trim() || !form.bodyText.trim()) {
    setError("Nome e texto do corpo são obrigatórios.");
    return;
  }

  const validTexts = buttons.map(b => b.text.trim()).filter(Boolean);

  if (new Set(validTexts).size !== validTexts.length) {
    setError("Botões não podem ter textos duplicados.");
    return;
  }

  const VARIABLE_RE = /\{\{\d+\}\}/;
  if (validTexts.some(t => VARIABLE_RE.test(t))) {
    setError("Botões não podem conter variáveis como {{1}}.");
    return;
  }

  setSaving(true);
  setError(null);

  const body = {
    name: form.name.trim(),
    language: form.language,
    category: form.category,
    components: [
      { type: "BODY", text: form.bodyText.trim() },
      ...(validTexts.length > 0
        ? [{ type: "BUTTONS", buttons: validTexts.map(text => ({ type: "QUICK_REPLY", text })) }]
        : []),
    ],
  };

  try {
    const res = await fetch(`/api/channels/${activeChannelId}/templates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();

    if (res.status === 201) {
      onCreated();
      resetAndClose();
      return;
    }

    if (res.status === 202) {
      setPendingTemplateId(data.template?.id ?? null);
      setSuggestedCategory(data.suggested_category ?? null);
      setStep("review");
      return;
    }

    setError(data?.detail || data?.error || "Erro ao criar template.");
  } catch {
    setError("Erro de conexão. Tente novamente.");
  } finally {
    setSaving(false);
  }
};
```

- [ ] **Step 2: Verificar que o arquivo compila sem erros**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: update handleSubmit with BUTTONS payload and validation"
```

---

## Task 3: UI — seção de botões no formulário

**Files:**
- Modify: `frontend/src/components/canais/create-template-modal.tsx`

- [ ] **Step 1: Adicionar a seção de botões no JSX**

No bloco `{step === "form" && (...)}`, após o `</div>` que fecha a seção do campo BODY (textarea + hint), e antes do bloco `{error && ...}`, adicione:

```tsx
<div>
  <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
    Botões de Resposta Rápida (Opcional)
  </label>
  <div className="space-y-2">
    {buttons.map(btn => (
      <div key={btn.id} className="flex items-center gap-2">
        <input
          value={btn.text}
          onChange={e => updateButton(btn.id, e.target.value)}
          maxLength={25}
          className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none flex-1"
          placeholder="ex: Sim"
        />
        <button
          type="button"
          onClick={() => removeButton(btn.id)}
          className="text-[#7b7b78] hover:text-[#111111] text-lg transition-colors leading-none"
        >
          &times;
        </button>
      </div>
    ))}
  </div>
  {buttons.length < 3 && (
    <button
      type="button"
      onClick={addButton}
      className="text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors mt-2"
    >
      + Adicionar botão
    </button>
  )}
  <p className="text-[11px] text-[#7b7b78] mt-1">
    Máx 3 botões, 25 caracteres. Não use variáveis como &#123;&#123;1&#125;&#125;.
  </p>
</div>
```

- [ ] **Step 2: Verificar que o arquivo compila sem erros**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros.

- [ ] **Step 3: Iniciar o servidor de desenvolvimento e testar manualmente**

```bash
cd frontend && npm run dev
```

Abra o modal "Criar Template WhatsApp" e verifique:

1. A seção "BOTÕES DE RESPOSTA RÁPIDA (OPCIONAL)" aparece abaixo do campo BODY
2. Clicar "+ Adicionar botão" adiciona um input
3. Adicionar 3 botões oculta o link "+ Adicionar botão"
4. `×` remove o botão correto mesmo quando removido do meio da lista (sem bug de foco)
5. Digitar `{{1}}` no input do botão: os colchetes são removidos automaticamente
6. Tentar submeter com dois botões com o mesmo texto → erro "Botões não podem ter textos duplicados."
7. Submeter sem botões → funciona normalmente (regressão)
8. Submeter com botões válidos → request vai com componente BUTTONS no payload (verificar no Network tab do browser)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: add QUICK_REPLY buttons UI section to create template modal"
```
