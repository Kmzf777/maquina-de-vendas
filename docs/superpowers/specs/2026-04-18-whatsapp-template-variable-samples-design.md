# WhatsApp Template Variable Samples — Design

**Data:** 2026-04-18
**Escopo:** Modal de criação de templates WhatsApp (`create-template-modal.tsx`) + schema backend

---

## Objetivo

Quando o usuário adiciona variáveis (`{{1}}`, `{{2}}`, etc.) ao campo BODY do template, deve aparecer automaticamente uma seção "Amostras de Variáveis" com um campo de preenchimento por variável. O envio das amostras é obrigatório e elas são incluídas no payload para a Meta via `example.body_text`.

---

## Arquivos alterados

| Arquivo | Ação |
|---|---|
| `frontend/src/components/canais/create-template-modal.tsx` | Modificar |
| `backend/app/templates/schemas.py` | Modificar |

---

## Seção 1: Estado e extração de variáveis

### Estado novo

```ts
const [variableSamples, setVariableSamples] = useState<Record<string, string>>({});
```

Chave = número da variável (`"1"`, `"2"`...), valor = texto de exemplo.

### Extração reativa (derivada, sem useState)

```ts
const VARS_RE_GLOBAL = /\{\{(\d+)\}\}/g;
const detectedVars: string[] = [
  ...new Set([...form.bodyText.matchAll(VARS_RE_GLOBAL)].map(m => m[1]))
].sort((a, b) => Number(a) - Number(b));
```

- Roda em cada render — sem efeito colateral
- Variáveis duplicadas no texto resultam em um único campo de amostra
- Quando o usuário apaga uma variável do textarea, ela desaparece da lista automaticamente
- `variableSamples` pode acumular chaves órfãs; o payload usa apenas as chaves em `detectedVars`

**Nota:** `VARS_RE_GLOBAL` é uma constante de módulo separada de `VARIABLE_RE` (que existe para validação dos botões). As duas são diferentes: `VARIABLE_RE` é sem flag `g` (usada com `.test()`), `VARS_RE_GLOBAL` tem flag `g` (usada com `.matchAll()`).

### Reset

```ts
const resetAndClose = () => {
  // ... existente ...
  setVariableSamples({});
  onClose();
};
```

---

## Seção 2: UI da seção de amostras

A seção é renderizada condicionalmente no `{step === "form"}`, **entre o campo BODY e a seção de botões**, quando `detectedVars.length > 0`.

### Estrutura

```
<label> AMOSTRAS DE VARIÁVEIS </label>

<div> ← aviso (bg-[#faf9f6], border-[#dedbd6])
  Inclua exemplos para todas as variáveis da sua mensagem para
  ajudar a Meta a analisar o template.
  Por motivos de privacidade, não inclua dados reais de clientes.
</div>

<label> Corpo </label>
{detectedVars.map(v => (
  <input placeholder="Insira um exemplo para {{v}}" />
))}
```

### Comportamento

- A lista de inputs é controlada pelo conteúdo do textarea — o usuário não adiciona nem remove manualmente
- Todos os campos são obrigatórios (validado no submit, não via `disabled`)
- Estilo visual consistente com o resto do formulário (label `text-[11px] uppercase`, inputs com borda `#dedbd6`)

---

## Seção 3: Validação e payload

### Validação no `handleSubmit`

Inserida após as validações existentes (nome, body, botões), antes de `setSaving(true)`:

```ts
if (detectedVars.some(v => !variableSamples[v]?.trim())) {
  setError("Preencha os exemplos de todas as variáveis do corpo.");
  return;
}
```

### Payload do componente BODY

**Com variáveis:**
```ts
{
  type: "BODY",
  text: form.bodyText.trim(),
  example: {
    body_text: [detectedVars.map(v => variableSamples[v].trim())]
  }
}
```

**Sem variáveis** (comportamento atual, sem alteração):
```ts
{ type: "BODY", text: form.bodyText.trim() }
```

O campo `example.body_text` é um array de arrays — o array externo representa múltiplos exemplos (enviamos apenas um), o array interno tem um valor por variável em ordem numérica.

---

## Seção 4: Backend

### `backend/app/templates/schemas.py`

Adicionar campo `example` ao modelo `TemplateComponent`:

```python
example: Optional[dict] = None
```

O serviço (`service.py`) já passa `components` direto para o payload da Meta — nenhuma outra alteração necessária no backend.

---

## Fora de escopo

- Preview live do body com amostras substituídas
- Validação de sequência de variáveis (ex: avisar se o usuário pula `{{2}}` e usa `{{3}}`)
- Limite de caracteres por amostra (a Meta não documenta um limite fixo; o backend rejeitará se inválido)
