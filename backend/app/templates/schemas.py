from pydantic import BaseModel
from typing import Literal


class TemplateButton(BaseModel):
    type: str
    text: str
    url: str | None = None
    phone_number: str | None = None
    payload: str | None = None


class TemplateComponent(BaseModel):
    type: Literal["HEADER", "BODY", "FOOTER", "BUTTONS"]
    format: str | None = None
    text: str | None = None
    buttons: list[TemplateButton] | None = None


class TemplateCreate(BaseModel):
    name: str
    language: str = "pt_BR"
    category: Literal["UTILITY", "MARKETING"]
    components: list[TemplateComponent]
