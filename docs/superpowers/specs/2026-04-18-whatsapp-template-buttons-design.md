# WhatsApp Template Buttons — Backend Design

**Date:** 2026-04-18
**Scope:** Backend only. Frontend não é alterado neste ciclo.
**Goal:** Adicionar suporte a botões QUICK_REPLY na criação de templates WhatsApp, com validação estrita no backend antes de chamar a Meta API.

---

## Contexto

O backend já possui `TemplateButton` e suporte ao componente `BUTTONS` nos schemas Pydantic, mas:
- `TemplateButton.type` é `str` sem restrição
- Não há validação de limites (máx 3 botões QUICK_REPLY por Meta)
- `payload` (campo obrigatório na Meta API) não tem default inteligente
- Campos irrelevantes para QUICK_REPLY (`url`, `phone_number`) estão presentes

O service já passa `components` diretamente para a Meta API — estruturalmente correto, só falta validação e preenchimento de `payload`.

---

## Arquitetura

### Arquivos alterados

| Arquivo | Tipo de mudança |
|---|---|
| `backend/app/templates/schemas.py` | Modificar — refinar `TemplateButton`, adicionar validators |
| `backend/app/templates/service.py` | Modificar — preencher `payload` com default |
| `backend/tests/test_templates_service.py` | Modificar — novos casos de teste |

Nenhum arquivo novo é criado. Nenhuma migração de banco necessária (`components` já é `jsonb`).

---

## Componentes

### `TemplateButton` (schema)

```python
class TemplateButton(BaseModel):
    type: Literal["QUICK_REPLY"]
    text: str
    payload: str | None = None
```

- Remove `url` e `phone_number` (irrelevantes para QUICK_REPLY)
- `payload` opcional no schema — preenchido pelo service se ausente

### `TemplateComponent` (schema)

Adicionar `@model_validator(mode="after")`:
- Se `type == "BUTTONS"`: `buttons` deve ter entre 1 e 3 itens
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
   → 422 se: tipo inválido, 0 ou 4+ botões, 2+ componentes BUTTONS

2. service.create_template recebeu data (dict) já validado
   → para cada botão sem payload: payload = button.text

3. payload montado → MetaTemplateClient.create_template(payload)

4. Meta responde:
   → categoria inalterada → 201 + { status: "pending", template }
   → categoria alterada   → 202 + { status: "pending_category_review", suggested_category, template }
```

---

## Validação e erros

| Cenário | HTTP | Quem detecta |
|---|---|---|
| Tipo de botão inválido | 422 | Pydantic (`Literal["QUICK_REPLY"]`) |
| BUTTONS com 0 botões | 422 | `model_validator` em `TemplateComponent` |
| BUTTONS com 4+ botões | 422 | `model_validator` em `TemplateComponent` |
| Dois componentes BUTTONS | 422 | `model_validator` em `TemplateCreate` |
| `text` ausente no botão | 422 | Pydantic (campo obrigatório) |
| Meta API rejeita | 502 | service (já tratado) |

---

## Testes

### Validação de schema (unitários — instanciação Pydantic)

- `test_quick_reply_button_valid` — botão com texto, sem payload → válido
- `test_quick_reply_button_payload_provided` — botão com texto e payload → válido
- `test_buttons_component_empty_raises` — BUTTONS sem botões → `ValidationError`
- `test_buttons_component_too_many_raises` — BUTTONS com 4 botões → `ValidationError`
- `test_two_buttons_components_raises` — dois BUTTONS no template → `ValidationError`

### Comportamento do service (com mock)

- `test_create_template_with_quick_reply_no_payload` — `payload` ausente → service preenche com `text`
- `test_create_template_with_quick_reply_payload_provided` — `payload` fornecido → service não sobrescreve
- `test_create_template_no_buttons` — template sem BUTTONS → comportamento atual inalterado (regressão)

---

## Decisões e trade-offs

**Payload default no service, não no schema:** o schema valida estrutura; o service aplica regras de negócio (default inteligente). Manter essa separação facilita testar cada camada independentemente.

**`Literal["QUICK_REPLY"]` em vez de `Enum`:** consistente com o restante do projeto (`Literal` em `TemplateComponent.type` e `TemplateCreate.category`).

**Sem migration:** `components jsonb` já armazena o array completo incluindo botões — nenhuma alteração de schema de banco é necessária.

**Sem suporte a CTA (URL/PHONE_NUMBER) agora:** deixado explicitamente fora do escopo. Quando necessário, expandir `Literal["QUICK_REPLY"]` para `Literal["QUICK_REPLY", "URL", "PHONE_NUMBER"]` e restaurar `url`/`phone_number` como campos opcionais com validators cross-field.
