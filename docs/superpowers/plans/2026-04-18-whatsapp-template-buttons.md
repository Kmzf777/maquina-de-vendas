# WhatsApp Template Buttons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar suporte a botões QUICK_REPLY na criação de templates WhatsApp com validação estrita no backend (tipo, limite de 25 chars no texto, máx 3 botões por componente, único componente BUTTONS por template).

**Architecture:** Apenas `schemas.py` é alterado — `TemplateButton` passa a usar `Literal["QUICK_REPLY"]` e `Field(max_length=25)`. Validators Pydantic em `TemplateComponent` e `TemplateCreate` impõem as regras de negócio antes de qualquer chamada à Meta API. `service.py` não muda.

**Tech Stack:** FastAPI, Pydantic v2 (`model_validator`, `Field`), pytest com `asyncio_mode = auto`.

---

## Mapa de arquivos

| Arquivo | Ação |
|---|---|
| `backend/app/templates/schemas.py` | Modificar — `TemplateButton`, validators em `TemplateComponent` e `TemplateCreate` |
| `backend/tests/test_templates_service.py` | Modificar — adicionar 6 testes de schema no final do arquivo |

---

## Task 1: Escrever os testes de schema (TDD — falham primeiro)

**Files:**
- Modify: `backend/tests/test_templates_service.py`

- [ ] **Step 1: Adicionar imports de schema ao topo do arquivo de testes**

No `backend/tests/test_templates_service.py`, adicione após a linha `from fastapi import HTTPException`:

```python
from pydantic import ValidationError
from app.templates.schemas import TemplateButton, TemplateComponent, TemplateCreate
```

- [ ] **Step 2: Adicionar os 6 testes de schema ao final do arquivo**

Adicione ao final de `backend/tests/test_templates_service.py`:

```python
# --- schema: TemplateButton ---

def test_quick_reply_button_valid():
    btn = TemplateButton(type="QUICK_REPLY", text="Sim")
    assert btn.type == "QUICK_REPLY"
    assert btn.text == "Sim"


def test_quick_reply_button_text_too_long_raises():
    with pytest.raises(ValidationError):
        TemplateButton(type="QUICK_REPLY", text="A" * 26)


# --- schema: TemplateComponent ---

def test_buttons_component_empty_raises():
    with pytest.raises(ValidationError):
        TemplateComponent(type="BUTTONS", buttons=[])


def test_buttons_component_too_many_raises():
    buttons = [TemplateButton(type="QUICK_REPLY", text=f"Op{i}") for i in range(4)]
    with pytest.raises(ValidationError):
        TemplateComponent(type="BUTTONS", buttons=buttons)


# --- schema: TemplateCreate ---

def test_two_buttons_components_raises():
    buttons = [TemplateButton(type="QUICK_REPLY", text="Sim")]
    btn_component = TemplateComponent(type="BUTTONS", buttons=buttons)
    with pytest.raises(ValidationError):
        TemplateCreate(
            name="test",
            language="pt_BR",
            category="UTILITY",
            components=[
                TemplateComponent(type="BODY", text="Hello"),
                btn_component,
                btn_component,
            ],
        )


def test_create_template_schema_no_buttons_valid():
    tc = TemplateCreate(
        name="test",
        language="pt_BR",
        category="UTILITY",
        components=[TemplateComponent(type="BODY", text="Hello")],
    )
    assert len(tc.components) == 1
```

- [ ] **Step 3: Rodar os novos testes para confirmar que falham**

```bash
cd backend && pytest tests/test_templates_service.py::test_quick_reply_button_text_too_long_raises tests/test_templates_service.py::test_buttons_component_empty_raises tests/test_templates_service.py::test_buttons_component_too_many_raises tests/test_templates_service.py::test_two_buttons_components_raises -v
```

Esperado: 4 falhas — sem validators implementados, Pydantic não levanta `ValidationError` ainda. (`test_quick_reply_button_valid` e `test_create_template_schema_no_buttons_valid` já passam e podem ser incluídos; os outros 4 devem falhar.)

---

## Task 2: Implementar as mudanças no schema

**Files:**
- Modify: `backend/app/templates/schemas.py`

- [ ] **Step 1: Substituir o conteúdo completo de `schemas.py`**

Substitua `backend/app/templates/schemas.py` pelo seguinte:

```python
from pydantic import BaseModel, Field, model_validator
from typing import Literal


class TemplateButton(BaseModel):
    type: Literal["QUICK_REPLY"]
    text: str = Field(..., max_length=25)


class TemplateComponent(BaseModel):
    type: Literal["HEADER", "BODY", "FOOTER", "BUTTONS"]
    format: str | None = None
    text: str | None = None
    buttons: list[TemplateButton] | None = None

    @model_validator(mode="after")
    def validate_buttons(self) -> "TemplateComponent":
        if self.type == "BUTTONS":
            if not self.buttons or len(self.buttons) < 1:
                raise ValueError("BUTTONS component must have at least 1 button")
            if len(self.buttons) > 3:
                raise ValueError("BUTTONS component cannot have more than 3 buttons")
        else:
            if self.buttons:
                raise ValueError(f"Component type {self.type!r} cannot have buttons")
        return self


class TemplateCreate(BaseModel):
    name: str
    language: str = "pt_BR"
    category: Literal["UTILITY", "MARKETING"]
    components: list[TemplateComponent]

    @model_validator(mode="after")
    def validate_single_buttons_component(self) -> "TemplateCreate":
        buttons_count = sum(1 for c in self.components if c.type == "BUTTONS")
        if buttons_count > 1:
            raise ValueError("Template cannot have more than one BUTTONS component")
        return self
```

- [ ] **Step 2: Rodar os novos testes para confirmar que passam**

```bash
cd backend && pytest tests/test_templates_service.py::test_quick_reply_button_valid tests/test_templates_service.py::test_quick_reply_button_text_too_long_raises tests/test_templates_service.py::test_buttons_component_empty_raises tests/test_templates_service.py::test_buttons_component_too_many_raises tests/test_templates_service.py::test_two_buttons_components_raises tests/test_templates_service.py::test_create_template_schema_no_buttons_valid -v
```

Esperado: `6 passed`.

- [ ] **Step 3: Rodar a suite completa para verificar regressões**

```bash
cd backend && pytest tests/test_templates_service.py -v
```

Esperado: todos os 14 testes passando (8 existentes + 6 novos).

- [ ] **Step 4: Commit**

```bash
git add backend/app/templates/schemas.py backend/tests/test_templates_service.py
git commit -m "feat: add QUICK_REPLY button support with strict validation to template schemas"
```
