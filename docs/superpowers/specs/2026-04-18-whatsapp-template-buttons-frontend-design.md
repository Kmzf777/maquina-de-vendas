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
const [buttons, setButtons] = useState<string[]>([]);
```

- Array de strings onde cada item é o texto de um botão
- Vazio por padrão (botões são opcionais)
- Máximo de 3 itens (limite da Meta API)
- Limpo em `resetAndClose` junto com o restante do estado

`EMPTY_FORM` não muda — botões são uma lista dinâmica, não um campo escalar.

---

## Payload na submissão

```ts
const validButtons = buttons.map(b => b.trim()).filter(Boolean);

const body = {
  name: form.name.trim(),
  language: form.language,
  category: form.category,
  components: [
    { type: "BODY", text: form.bodyText.trim() },
    ...(validButtons.length > 0
      ? [{ type: "BUTTONS", buttons: validButtons.map(text => ({ type: "QUICK_REPLY", text })) }]
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
Máx 3 botões, 25 caracteres cada.
```

### Especificação de estilos (seguindo padrão do modal)

**Label:**
```
text-[11px] uppercase tracking-[0.6px] text-[#7b7b78] mb-1
```

**Cada row de botão (flex, items-center, gap-2):**
- Input: `border border-[#dedbd6] rounded-[6px] px-3 py-2 text-[14px] text-[#111111] focus:border-[#111111] focus:outline-none flex-1` com `maxLength={25}`
- Botão remover (`×`): `text-[#7b7b78] hover:text-[#111111] text-lg transition-colors`

**Link "＋ Adicionar botão":**
```
text-[12px] text-[#7b7b78] hover:text-[#111111] transition-colors mt-1
```
Oculto (`hidden` ou condicional) quando `buttons.length >= 3`.

**Hint abaixo:**
```
text-[11px] text-[#7b7b78] mt-1
```
Texto: "Máx 3 botões, 25 caracteres cada."

---

## Handlers

```ts
const addButton = () => {
  if (buttons.length < 3) setButtons([...buttons, ""]);
};

const updateButton = (index: number, value: string) => {
  const next = [...buttons];
  next[index] = value;
  setButtons(next);
};

const removeButton = (index: number) => {
  setButtons(buttons.filter((_, i) => i !== index));
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
2. Usuário clica em "＋ Adicionar botão" → input aparece
3. Usuário digita texto (máx 25 chars via `maxLength`)
4. Usuário pode adicionar até 3 botões ou remover com `×`
5. Ao clicar "Criar Template":
   - Botões vazios são filtrados
   - Se restarem botões válidos, componente BUTTONS é incluído no payload
   - Fluxo 201/202 segue como antes

---

## Decisões

**Botões fora do `form` object:** `form` contém apenas campos escalares. Botões são lista dinâmica — estado separado é mais simples de manipular e resetar.

**Filtrar vazios silenciosamente:** Melhor UX do que bloquear o submit por um input esquecido em branco. O backend valida o que chega.

**`maxLength={25}` no input:** Previne o usuário de digitar além do limite antes de atingir o backend. Não é necessário contador de caracteres para MVP.

**Sem mudança no step "review":** O fluxo 202 (categoria divergente) não é afetado pelos botões.
