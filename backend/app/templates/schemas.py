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
