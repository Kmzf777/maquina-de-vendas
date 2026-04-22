# WhatsApp Template Buttons — Backend Design

**Date:** 2026-04-18
**Scope:** Backend only. Frontend não é alterado neste ciclo.
**Goal:** Adicionar suporte a botões QUICK_REPLY na criação de templates WhatsApp, com validação estrita no backend antes de chamar a Meta API.

---

## Contexto

O backend já possui `TemplateButton` e suporte ao componente `BUTTONS` nos schemas Pydantic, mas:
- `TemplateButton.type` é `str` sem restrição
- Não há validação de limites (máx 3 botões QUICK_REPLY por template, conforme Meta API)
- Não há validação de limite de caracteres no texto do botão (máx 25 chars, conforme Meta API)
- Campos irrelevantes para QUICK_REPLY (`url`, `phone_number`, `payload`) estão presentes

**Importante:** A Meta API **não aceita** o campo `payload` na requisição de criação de template. O `payload` é um atributo de envio de mensagem (definido ao disparar o template para um destinatário), não de definição do template. Enviá-lo na criação causará erro.

O service já passa `components` diretamente para a Meta API — estruturalmente correto, só falta validação adequada dos campos.

---

## Arquitetura

### Arquivos alterados

| Arquivo | Tipo de mudança |
|---|---|
| `backend/app/templates/schemas.py` | Modificar — refinar `TemplateButton`, adicionar validators |
| `backend/tests/test_templates_service.py` | Modificar — novos casos de teste de schema |

`service.py` **não muda** — nenhuma lógica de preenchimento de campos necessária.

Nenhum arquivo novo é criado. Nenhuma migração de banco necessária (`components` já é `jsonb`).

---

## Componentes

### `TemplateButton` (schema)

```python
from pydantic import Field

class TemplateButton(BaseModel):
    type: Literal["QUICK_REPLY"]
    text: str = Field(..., max_length=25)
```

- `type: Literal["QUICK_REPLY"]` — documenta e restringe ao único tipo suportado
- `text` com `max_length=25` — limite estrito da API do WhatsApp para texto de botão QUICK_REPLY
- Remove `url`, `phone_number` e `payload` — nenhum desses campos é aceito pela Meta API na criação de template para QUICK_REPLY

### `TemplateComponent` (schema)

Adicionar `@model_validator(mode="after")`:
- Se `type == "BUTTONS"`: `buttons` deve ter entre 1 e 3 itens (limite da Meta para QUICK_REPLY)
- Se `type != "BUTTONS"`: `buttons` deve ser `None` ou lista vazia

### `TemplateCreate` (schema)

Adicionar `@model_validator(mode="after")`:
- No máximo um componente `"BUTTONS"` por template

---

## Fluxo de dados

```
POST /api/channels/{id}/templates
  body: {
    name, language, category,
    components: [
      { type: "BODY", text: "..." },
      { type: "BUTTONS", buttons: [{ type: "QUICK_REPLY", text: "Sim" }] }
    ]
  }

1. Router recebe → Pydantic valida schema
   → 422 se: tipo inválido, text > 25 chars, 0 ou 4+ botões, 2+ componentes BUTTONS

2. service.create_template recebe data (dict) já validado
   → passa components direto para o payload (sem transformação)

3. MetaTemplateClient.create_template(payload) → Meta API

4. Meta responde:
   → categoria inalterada → 201 + { status: "pending", template }
   → categoria alterada   → 202 + { status: "pending_category_review", suggested_category, template }
```

---

## Validação e erros

| Cenário | HTTP | Quem detecta |
|---|---|---|
| Tipo de botão inválido | 422 | Pydantic (`Literal["QUICK_REPLY"]`) |
| Texto do botão > 25 chars | 422 | Pydantic (`Field(max_length=25)`) |
| BUTTONS com 0 botões | 422 | `model_validator` em `TemplateComponent` |
| BUTTONS com 4+ botões | 422 | `model_validator` em `TemplateComponent` |
| Dois componentes BUTTONS | 422 | `model_validator` em `TemplateCreate` |
| `text` ausente no botão | 422 | Pydantic (campo obrigatório) |
| Meta API rejeita | 502 | service (já tratado) |

---

## Testes

### Validação de schema (unitários — instanciação Pydantic com `ValidationError`)

- `test_quick_reply_button_valid` — botão com texto ≤ 25 chars → válido
- `test_quick_reply_button_text_too_long_raises` — texto com 26+ chars → `ValidationError`
- `test_buttons_component_empty_raises` — BUTTONS sem botões → `ValidationError`
- `test_buttons_component_too_many_raises` — BUTTONS com 4 botões → `ValidationError`
- `test_two_buttons_components_raises` — dois BUTTONS no template → `ValidationError`

### Comportamento do service (com mock — regressão)

- `test_create_template_no_buttons` — template sem BUTTONS → comportamento atual inalterado

---

## Decisões e trade-offs

**`payload` removido do schema:** A Meta API não aceita esse campo na criação de templates QUICK_REPLY. O `payload` é definido somente ao enviar a mensagem template para um destinatário (via `components` do envio). Incluí-lo causaria erro 400 na Meta.

**`max_length=25` via `Field`:** Limite documentado pela Meta para texto de botão QUICK_REPLY. Validar no backend evita uma roundtrip desnecessária à Meta API.

**`service.py` não muda:** Toda a validação é feita pelo schema Pydantic antes de o service ser invocado. O service já passa `components` diretamente — comportamento correto.

**`Literal["QUICK_REPLY"]` em vez de `Enum`:** Consistente com o restante do projeto (`Literal` em `TemplateComponent.type` e `TemplateCreate.category`).

**Sem migration:** `components jsonb` já armazena o array completo incluindo botões.

**Sem suporte a CTA (URL/PHONE_NUMBER) agora:** Escopo explicitamente excluído. Quando necessário: expandir `Literal`, restaurar `url`/`phone_number` com validators cross-field.
