# WhatsApp Template Variable Samples — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar seção "Amostras de Variáveis" ao modal de criação de templates WhatsApp, com detecção reativa de variáveis no body, validação de sequência e preenchimento obrigatório, e inclusão de `example.body_text` no payload enviado à Meta.

**Architecture:** Frontend: `create-template-modal.tsx` recebe estado `variableSamples` e valor derivado `detectedVars` (calculado em cada render via regex global). Validação de sequência e amostras ocorre no `handleSubmit` antes do fetch. Backend: `TemplateComponent` ganha campo `example: dict | None = None`; o serviço já passa `components` direto para a Meta, nenhuma outra mudança necessária.

**Tech Stack:** React (useState), TypeScript, Tailwind CSS, Pydantic v2 (Python 3.10+, operador `|`).

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `frontend/src/components/canais/create-template-modal.tsx` | Modificar |
| `backend/app/templates/schemas.py` | Modificar |

---

## Task 1: Backend — campo `example` no TemplateComponent

**Files:**
- Modify: `backend/app/templates/schemas.py`

- [ ] **Step 1: Adicionar campo `example` ao modelo `TemplateComponent`**

Substitua o modelo `TemplateComponent` inteiro por:

```python
class TemplateComponent(BaseModel):
    type: Literal["HEADER", "BODY", "FOOTER", "BUTTONS"]
    format: str | None = None
    text: str | None = None
    buttons: list[TemplateButton] | None = None
    example: dict | None = None

    @model_validator(mode="after")
    def validate_buttons(self) -> "TemplateComponent":
        if self.type == "BUTTONS":
            if not self.buttons:
                raise ValueError("BUTTONS component must have at least 1 button")
            if len(self.buttons) > 3:
                raise ValueError("BUTTONS component cannot have more than 3 buttons")
        else:
            if self.buttons:
                raise ValueError(f"Component type {self.type!r} cannot have buttons")
        return self
```

- [ ] **Step 2: Verificar que o campo é aceito e serializado corretamente**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/backend" && python -c "
from app.templates.schemas import TemplateComponent

# Com example: deve aparecer no dump
c = TemplateComponent(type='BODY', text='Ola {{1}}', example={'body_text': [['Joao']]})
d = c.model_dump(exclude_none=True)
assert 'example' in d and d['example'] == {'body_text': [['Joao']]}, 'example deve estar presente'

# Sem example: nao deve aparecer no dump
c2 = TemplateComponent(type='BODY', text='Ola')
d2 = c2.model_dump(exclude_none=True)
assert 'example' not in d2, 'example nao deve aparecer quando None'

print('OK')
"
```

Esperado: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/templates/schemas.py
git commit -m "feat: add example field to TemplateComponent schema"
```

---

## Task 2: Frontend — constante, estado, derivação e reset

**Files:**
- Modify: `frontend/src/components/canais/create-template-modal.tsx`

- [ ] **Step 1: Adicionar `VARS_RE_GLOBAL` ao escopo de módulo**

Após a linha `const VARIABLE_RE = /\{\{\d+\}\}/;`, adicione:

```ts
const VARS_RE_GLOBAL = /\{\{([1-9]\d*)\}\}/g;
```

Captura apenas inteiros positivos sem zero à esquerda — `{{0}}` e `{{01}}` são ignorados.

- [ ] **Step 2: Adicionar o estado `variableSamples`**

Após a linha `const [buttons, setButtons] = useState<ButtonItem[]>([]);`, adicione:

```ts
const [variableSamples, setVariableSamples] = useState<Record<string, string>>({});
```

- [ ] **Step 3: Adicionar a derivação de `detectedVars`**

Após a linha `const activeChannelId = channelId ?? selectedChannelId;`, adicione:

```ts
const detectedVars: string[] = [
  ...new Set([...form.bodyText.matchAll(VARS_RE_GLOBAL)].map(m => m[1]))
].sort((a, b) => Number(a) - Number(b));
```

`matchAll` clona internamente a regex — o `lastIndex` do módulo não é mutado entre renders.

- [ ] **Step 4: Atualizar `resetAndClose` para limpar `variableSamples`**

Substitua a função `resetAndClose` por:

```ts
const resetAndClose = () => {
  setStep("form");
  setForm(EMPTY_FORM);
  setButtons([]);
  setVariableSamples({});
  setError(null);
  setPendingTemplateId(null);
  setSuggestedCategory(null);
  setSelectedChannelId("");
  onClose();
};
```

- [ ] **Step 5: Verificar que compila sem erros**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/frontend" && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: add variableSamples state and detectedVars derivation"
```

---

## Task 3: Frontend — validação e payload no handleSubmit

**Files:**
- Modify: `frontend/src/components/canais/create-template-modal.tsx`

- [ ] **Step 1: Adicionar validações de sequência e amostras**

No `handleSubmit`, após o bloco:
```ts
    if (validTexts.some(t => VARIABLE_RE.test(t))) {
      setError("Botões não podem conter variáveis como {{1}}.");
      return;
    }
```

e antes de `setSaving(true);`, insira:

```ts
    const varNumbers = detectedVars.map(Number);
    if (varNumbers.length > 0 && !varNumbers.every((n, i) => n === i + 1)) {
      setError("As variáveis devem ser sequenciais começando em {{1}} (ex: {{1}}, {{2}}, {{3}}).");
      return;
    }

    if (detectedVars.some(v => !variableSamples[v]?.trim())) {
      setError("Preencha os exemplos de todas as variáveis do corpo.");
      return;
    }
```

- [ ] **Step 2: Atualizar o componente BODY para incluir `example` quando há variáveis**

No `handleSubmit`, antes de `const body = {`, adicione:

```ts
    const bodyComponent = detectedVars.length > 0
      ? {
          type: "BODY",
          text: form.bodyText.trim(),
          example: { body_text: [detectedVars.map(v => variableSamples[v].trim())] },
        }
      : { type: "BODY", text: form.bodyText.trim() };
```

Em seguida, dentro de `const body = { ... }`, substitua:

```ts
      { type: "BODY", text: form.bodyText.trim() },
```

por:

```ts
      bodyComponent,
```

- [ ] **Step 3: Verificar que compila sem erros**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/frontend" && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: add variable sequence/samples validation and example payload to handleSubmit"
```

---

## Task 4: Frontend — UI da seção de amostras

**Files:**
- Modify: `frontend/src/components/canais/create-template-modal.tsx`

- [ ] **Step 1: Adicionar a seção de amostras no JSX**

No bloco `{step === "form" && (...)}`, após o `</div>` que fecha a seção BODY (o div que contém o textarea e o `<p>` de hint com "Use {{1}}, {{2}}..."), e antes do `<div>` que inicia a seção de botões ("Botões de Resposta Rápida"), adicione:

```tsx
            {detectedVars.length > 0 && (
              <div>
                <label className="block text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1">
                  Amostras de Variáveis
                </label>
                <div className="p-3 bg-[#faf9f6] border border-[#dedbd6] rounded-[6px] mb-2">
                  <p className="text-[12px] text-[#7b7b78]">
                    Inclua exemplos para todas as variáveis da sua mensagem para ajudar a Meta a analisar o template.
                  </p>
                  <p className="text-[12px] text-[#7b7b78] mt-1">
                    Por motivos de privacidade, não inclua dados reais de clientes.
                  </p>
                </div>
                <div className="space-y-2">
                  {detectedVars.map(v => (
                    <input
                      key={v}
                      value={variableSamples[v] ?? ""}
                      onChange={e => setVariableSamples(prev => ({ ...prev, [v]: e.target.value }))}
                      className="bg-white border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] placeholder:text-[#7b7b78] focus:border-[#111111] focus:outline-none w-full"
                      placeholder={`Insira um exemplo para {{${v}}}`}
                    />
                  ))}
                </div>
              </div>
            )}
```

- [ ] **Step 2: Verificar que compila sem erros**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/frontend" && npx tsc --noEmit 2>&1 | head -20
```

Esperado: sem erros.

- [ ] **Step 3: Testar manualmente**

```bash
cd "/home/Kelwin/Kelwin - Maquinadevendascanastra/frontend" && npm run dev
```

Abra o modal "Criar Template WhatsApp" e verifique:

1. Digitar `Olá {{1}}` no campo BODY → seção "AMOSTRAS DE VARIÁVEIS" aparece com um input, placeholder "Insira um exemplo para {{1}}"
2. Adicionar `{{2}}` → segundo input aparece automaticamente
3. Apagar `{{2}}` do textarea → segundo input desaparece
4. Digitar `{{0}}` ou `{{01}}` → nenhum input aparece (regex ignora)
5. Submeter com amostra vazia → erro "Preencha os exemplos de todas as variáveis do corpo."
6. Digitar `{{1}}` e `{{3}}` (pulando `{{2}}`) e submeter → erro "As variáveis devem ser sequenciais..."
7. Preencher `{{1}}` com amostra válida e submeter → Network tab mostra `example: { body_text: [["valor"]] }` dentro do componente BODY
8. Submeter template sem nenhuma variável no body → request não inclui `example` (regressão: comportamento original preservado)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/canais/create-template-modal.tsx
git commit -m "feat: add variable samples UI section to create template modal"
```
