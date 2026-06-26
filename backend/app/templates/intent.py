"""Registro de Intenção de Template — fonte única de verdade que classifica um
disparo de WhatsApp pela sua INTENÇÃO comercial, independente do nome exato.

Consumido por:
- resolução de persona (Eixo 1): só um disparo `cold_reactivation` ainda não
  respondido mantém a conversa em `valeria_outbound`.
- contexto de 1º turno (Eixo 2c): `warm_lp` muda o frame de "atualizar cadastro"
  para "o lead pediu informação na landing page".
- fallback de janela (Eixo 3B): a reabertura usa templates de continuação que
  NÃO podem reverter o lead para o frame frio.

Leaf module: não importa nada de `app`, evitando ciclos de import.
"""
from __future__ import annotations

# Intenções conhecidas
WARM_LP = "warm_lp"                 # lead veio até nós por uma landing page (quente)
COLD_REACTIVATION = "cold_reactivation"  # base fria: "estamos atualizando seu cadastro"
GENERIC = "generic"                # continuação/utility/desconhecido — trate como morno

# Prefixos/substrings que marcam recuperação fria. Mantido explícito e auditável.
_COLD_PREFIXES = ("atualizacao",)
_COLD_SUBSTRINGS = ("reativ",)  # reativar_*, *_reativacao, reativacao_*


def classify_template_intent(template_name: str | None) -> str:
    """Classifica o template pela intenção. Default conservador: GENERIC (morno)."""
    name = (template_name or "").strip().lower()
    if not name:
        return GENERIC
    if name.startswith("lp_"):
        return WARM_LP
    if name.startswith(_COLD_PREFIXES):
        return COLD_REACTIVATION
    if any(sub in name for sub in _COLD_SUBSTRINGS):
        return COLD_REACTIVATION
    return GENERIC


def dispatch_metadata(template_name: str | None) -> dict:
    """Bloco a ser gravado em messages.metadata p/ disparos broadcast/followup.

    Consumido pela resolução de persona (Eixo 1): `intent` distingue cold-open de quente.
    """
    return {
        "dispatch": {
            "template": template_name,
            "intent": classify_template_intent(template_name),
        }
    }
