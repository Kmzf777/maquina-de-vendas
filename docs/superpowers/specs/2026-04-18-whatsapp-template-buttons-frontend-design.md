# WhatsApp Template Buttons — Frontend Design

**Date:** 2026-04-18
**Scope:** Frontend only. Modal `create-template-modal.tsx` — adição de seção de botões QUICK_REPLY opcionais.
**Goal:** Permitir que o usuário adicione até 3 botões de resposta rápida ao criar um template WhatsApp.

---

## Contexto

O backend já suporta botões QUICK_REPLY (implementado em 2026-04-18). O modal atual (`frontend/src/components/canais/create-template-modal.tsx`) envia apenas o componente BODY. Esta feature adiciona suporte opcional a botões no mesmo modal, sem alterar o fluxo existente (step "form" → step "review").

---

## Arquitetura

**Arquivo alterado:** apenas `frontend/src/components/canais/create-template-modal.tsx`

Nenhum novo arquivo. Nenhuma mudança no backend, router, ou outros componentes.

---

## Estado

Novo estado adicionado ao componente:

```ts
type ButtonItem = { id: string; text: string };
const [buttons, setButtons] = useState<ButtonItem[]>([]);
```

- Array de objetos `{ id, text }` onde `id` é um identificador estável gerado com `crypto.randomUUID()` no momento da criação
- `id` é usado como `key` no `.map()` do render — nunca o índice — evitando bugs de DOM reuse no React quando itens são removidos do meio da lista
- Vazio por padrão (botões são opcionais)
- Máximo de 3 itens (limite da Meta API)
- Limpo em `resetAndClose` junto com o restante do estado

`EMPTY_FORM` não muda — botões são uma lista dinâmica, não um campo escalar.

---

## Validação client-side (antes do submit)

Além de filtrar botões vazios, `handleSubmit` valida:

1. **Duplicatas:** após trim, textos iguais são rejeitados com erro inline:
   ```
   "Botões não podem ter textos duplicados."
   ```
   Verificação: `new Set(validTexts).size !== validTexts.length`

2. **Variáveis (`{{n}}`):** o campo input bloqueia caracteres `{` e `}` via `onChange` — se o usuário colar texto com `{{1}}`, os colchetes são removidos antes de entrar no estado. Um hint fixo na UI informa: "Não use variáveis como {{1}} nos botões."

   Validação adicional no submit como safety net:
   ```ts
   const VARIABLE_RE = /\{\{\d+\}\}/;
   if (validTexts.some(t => VARIABLE_RE.test(t))) {
     setError("Botões não podem conter variáveis como {{1}}.");
     return;
   }
   ```

---

## Payload na submissão

```ts
const validTexts = buttons
  .map(b => b.text.trim())
  .filter(Boolean);

// Validar duplicatas
if (new Set(validTexts).size !== validTexts.length) {
  setError("Botões não podem ter textos duplicados.");
  return;
}

// Validar variáveis
const VARIABLE_RE = /\{\{\d+\}\}/;
if (validTexts.some(t => VARIABLE_RE.test(t))) {
  setError("Botões não podem conter variáveis como {{1}}.");
  return;
}

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
```

Botões com texto vazio após trim são descartados silenciosamente. O backend valida o restante (422 como fallback).

---

## UI — Seção de botões

Posicionamento: abaixo do campo BODY, antes da área de erro e dos botões de ação.

### Estrutura visual

```
BOTÕES DE RESPOSTA RÁPIDA (OPCIONAL)
[ texto do botão 1          ] [×]
[ texto do botão 2          ] [×]
+ Adicionar botão                     ← oculto quando buttons.length >= 3
Máx 3 botões, 25 caracteres. Não use variáveis como {{1}}.
```

### Especificação de estilos (seguindo padrão do modal)

**Label:**
```
text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1
```

**Cada row de botão (flex, items-center, gap-2), key={button.id}:**
- Input: `border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none flex-1` com `maxLength={25}`
- Botão remover (`×`): `text-[#7b7b78] hover:text-[#111111] text-lg transition-colors`

**Link "＋ Adicionar botão":**
```
text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors mt-1
```
Oculto quando `buttons.length >= 3`.

**Hint abaixo:**
```
text-[11px] text-[#7b7b78] mt-1
```
Texto: `Máx 3 botões, 25 caracteres. Não use variáveis como {{1}}.`

---

## Handlers

Todos usam a forma funcional do setter (`prev =>`) para evitar stale closure:

```ts
const addButton = () => {
  setButtons(prev =>
    prev.length < 3 ? [...prev, { id: crypto.randomUUID(), text: "" }] : prev
  );
};

const updateButton = (id: string, value: string) => {
  // Remove { e } para bloquear variáveis na digitação
  const sanitized = value.replace(/[{}]/g, "");
  setButtons(prev =>
    prev.map(b => b.id === id ? { ...b, text: sanitized } : b)
  );
};

const removeButton = (id: string) => {
  setButtons(prev => prev.filter(b => b.id !== id));
};
```

---

## Reset

```ts
const resetAndClose = () => {
  setStep("form");
  setForm(EMPTY_FORM);
  setButtons([]);          // ← novo
  setError(null);
  setPendingTemplateId(null);
  setSuggestedCategory(null);
  setSelectedChannelId("");
  onClose();
};
```

---

## Fluxo completo

1. Usuário preenche nome, idioma, categoria, corpo
2. Usuário clica em "＋ Adicionar botão" → input aparece (key estável via UUID)
3. Usuário digita texto — `{` e `}` são removidos automaticamente; máx 25 chars via `maxLength`
4. Usuário pode adicionar até 3 botões ou remover com `×` (remove por `id`, sem bug de índice)
5. Ao clicar "Criar Template":
   - Botões vazios são filtrados
   - Duplicatas bloqueiam o submit com erro inline
   - Variáveis bloqueiam o submit (safety net)
   - Se restarem botões válidos, componente BUTTONS é incluído no payload
   - Fluxo 201/202 segue como antes

---

## Decisões

**`{ id, text }` em vez de `string[]`:** IDs estáveis eliminam o bug de DOM reuse do React ao remover itens do meio da lista. `crypto.randomUUID()` é disponível em todos os browsers modernos e no Node/Next.js sem import adicional.

**Handlers com forma funcional (`prev =>`):** Evita stale closure quando chamados em sequência rápida.

**Sanitizar `{` e `}` no `onChange`:** Bloqueia variáveis na origem, antes de entrar no estado. A validação no submit é safety net para texto colado que escape o sanitizer.

**Validação de duplicatas no cliente:** A Meta API rejeita templates com textos iguais entre botões. Validar antes do submit evita uma roundtrip desnecessária.

**Filtrar vazios silenciosamente:** Melhor UX do que bloquear submit por input esquecido em branco.

**`maxLength={25}` no input:** Previne digitação além do limite sem necessidade de contador para MVP.

**Sem mudança no step "review":** O fluxo 202 (categoria divergente) não é afetado pelos botões.
