"""Registry de tools do agente — módulo PURO (nenhum import de app.*).

Card 3 da revisão de arquitetura (12/07/2026). Antes, adicionar uma tool exigia
editar TRÊS estruturas em tools.py acopladas só pelo nome-string — a lista
TOOL_DECLARATIONS (schema Gemini), a escada de 16 `elif tool_name ==` em
execute_tool e o dict inline de allowlist por stage — e o contrato de EFEITOS
(desliga a IA? difere mídia? cascateia noutra tool?) era invisível no call site,
viajando por dicts globais mutados de dentro do corpo das tools.

Aqui a unidade é a `Tool`: nome, schema, stages, efeitos e executor no mesmo lugar.
As três estruturas antigas viram views derivadas (`declarations()`,
`declarations_for_stage()`, `get()`), e o efeito de um turno viaja tipado pelo valor
de retorno (`ToolResult.effects` → `TurnEffects`), não por estado global.

O módulo é puro de propósito (como app/agent/handoff.py): pode ser importado por
tools/orchestrator/processor/testes sem ciclo e sem tocar em rede ou banco.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class ToolEffects:
    """O que esta tool faz ALÉM de devolver texto — parte da interface, não do corpo.

    disables_ai:    desliga `ai_enabled` no meio do turno. Quem declara isto DEVE enviar
                    a própria mensagem final antes de desligar a flag (trava B2 do
                    processor engole as bolhas do turno depois disso — forense 11/07).
    defers_media:   enfileira mídia para o processor despachar DEPOIS do texto.
    marks_interest: sinaliza interesse comercial (gatilho de follow-up).
    quotes_price:   este turno cotou preço de fato (gatilho de follow-up — Frente B3).
    may_cascade_to: tools que esta pode invocar em cascata (fix S1 — o handoff nascido
                    dentro do qualificar_lead era invisível ao sentinel do orchestrator).
    """

    disables_ai: bool = False
    defers_media: bool = False
    marks_interest: bool = False
    quotes_price: bool = False
    may_cascade_to: tuple[str, ...] = ()


@dataclass
class TurnEffects:
    """Efeitos acumulados de UM turno. Viajam pelo retorno das tools, não por global.

    O processor consome isto (hoje pela camada de compat pop_* em tools.py; quando o
    Card 8 abrir o retorno do run_agent, direto pelo valor de retorno).
    """

    deferred_media: list[dict] = field(default_factory=list)
    interest: dict | None = None
    quote_executed: bool = False

    def merge(self, other: "TurnEffects") -> None:
        """Absorve os efeitos de uma tool (ou de uma cascata) neste turno."""
        self.deferred_media.extend(other.deferred_media)
        if other.interest is not None:
            self.interest = other.interest
        self.quote_executed = self.quote_executed or other.quote_executed


@dataclass(frozen=True)
class ToolResult:
    """Retorno de um executor: o texto que volta ao modelo + os efeitos do turno."""

    message: str
    effects: TurnEffects = field(default_factory=TurnEffects)


@dataclass(frozen=True)
class ToolContext:
    """Tudo que um executor recebe. `invoke` é a única porta de cascata entre tools."""

    args: dict[str, Any]
    lead_id: str
    phone: str
    conversation_id: str
    # Mídia JÁ enfileirada neste turno (leitura para dedup intra-turno). O executor não
    # escreve aqui: devolve o que enfileirou em ToolResult.effects.deferred_media.
    queued_media: tuple[dict, ...] = ()
    invoke: Callable[..., Awaitable[str]] | None = None


Handler = Callable[[ToolContext], Awaitable[str | ToolResult]]


@dataclass(frozen=True)
class Tool:
    """Uma declaração por ferramenta: schema, stages, efeitos e executor co-locados."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    stages: frozenset[str] = frozenset()
    effects: ToolEffects = ToolEffects()

    def declaration(self) -> dict[str, Any]:
        """View no formato que o Gemini espera — sem vazar campos internos do registry."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Fonte única. Declarações, dispatch e allowlist por stage saem daqui."""

    # Stage desconhecido: mínimo seguro (só salvar_nome) — comportamento preservado.
    FALLBACK_STAGE_TOOLS: tuple[str, ...] = ("salvar_nome",)

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool duplicada no registry: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def declarations(self) -> list[dict[str, Any]]:
        return [t.declaration() for t in self._tools.values()]

    def tools_for_stage(self, stage: str) -> list[Tool]:
        allowed = [t for t in self._tools.values() if stage in t.stages]
        if allowed:
            return allowed
        return [self._tools[n] for n in self.FALLBACK_STAGE_TOOLS if n in self._tools]

    def declarations_for_stage(self, stage: str) -> list[dict[str, Any]]:
        return [t.declaration() for t in self.tools_for_stage(stage)]

    def with_effects(self, name: str, **kwargs: Any) -> Tool:
        """Helper de teste/introspecção: cópia da tool com efeitos sobrescritos."""
        tool = self._tools[name]
        return replace(tool, effects=replace(tool.effects, **kwargs))
