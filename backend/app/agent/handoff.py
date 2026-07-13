"""Deep module do Handoff — único dono do vocabulário e da detecção de transbordo.

Antes desta refatoração (12/07) o comportamento vivia espalhado por 5 arquivos
acoplados por string: tools.py emitia HANDOFF_RESULT_PREFIX, o orchestrator o
detectava em dois loops (principal + retry), o watchdog casava o marcador por
LIKE no SQL e a guarda verbalizada morava no corpo do orchestrator. Manter os
três pontos de detecção sincronizados na mão foi exatamente onde nasceu o bug
do cartão duplo (fix S1 11/07, caso Prof. Sebastião).

Este módulo é PURO (strings + regex, sem I/O e sem imports de app.*) para poder
ser consumido por tools, orchestrator e watchdog sem risco de ciclo.

Contratos persistidos que NÃO podem mudar (dados em produção + daily QA):
  - HANDOFF_RESULT_PREFIX  = "Lead encaminhado para "
  - marcador system        = "[encaminhar_humano] Lead encaminhado para <v>: <motivo>"
  - QA_HANDOFF_MARKER_LIKE = "[encaminhar_humano] Lead encaminhado%"
    (LIKE estreito por lição do relatório de 10/07: cada handoff grava DUAS
    system messages e o LIKE amplo dobrava a contagem)
"""

import re
import unicodedata

# Tool que materializa o transbordo. qualificar_lead pode chamá-la em CASCATA
# por dentro do execute_tool — nesse caso o nome nunca aparece nos
# function_calls do turno e a detecção se dá pelo prefixo do resultado.
HANDOFF_TOOL_NAME = "encaminhar_humano"

# Base única de onde TODO o vocabulário deriva. Alterar esta string quebra o
# daily QA (LIKE em system messages) e os marcadores já persistidos.
_HANDOFF_BASE = "Lead encaminhado"

HANDOFF_RESULT_PREFIX = f"{_HANDOFF_BASE} para "

# Padrão LIKE consumido pelo watchdog (daily QA). Derivado da MESMA base do
# prefixo — byte-idêntico ao literal que vivia hardcoded em watchdog/service.py.
QA_HANDOFF_MARKER_LIKE = f"[{HANDOFF_TOOL_NAME}] {_HANDOFF_BASE}%"


def handoff_result(vendedor: str) -> str:
    """Resultado da tool de handoff — o sentinel que o orchestrator detecta.

    Propagado verbatim pela cascata qualificar_lead → encaminhar_humano.
    """
    return f"{HANDOFF_RESULT_PREFIX}{vendedor}"


def handoff_system_marker(vendedor: str, motivo: str) -> str:
    """Marcador persistido como system message — casado pelo LIKE do daily QA."""
    return f"[{HANDOFF_TOOL_NAME}] {HANDOFF_RESULT_PREFIX}{vendedor}: {motivo}"


def is_handoff(tool_name: str, tool_result: object) -> bool:
    """Detecção ÚNICA de handoff num turno (fix S1 11/07).

    True quando a tool é o handoff explícito (fc.name) OU quando o resultado
    carrega o prefixo (handoff em cascata via qualificar_lead). Usada pelo loop
    principal E pelo loop de retry do orchestrator — um só predicado, impossível
    os dois pontos divergirem.
    """
    return tool_name == HANDOFF_TOOL_NAME or (
        isinstance(tool_result, str) and tool_result.startswith(HANDOFF_RESULT_PREFIX)
    )


# ---------------------------------------------------------------------------
# Guarda determinística de handoff verbalizado (2026-06-30)
# ---------------------------------------------------------------------------
# Defesa em profundidade: quando a Valéria ANUNCIA a transferência no texto comum
# ("vou te conectar com o João", "vou deixar o contato dele aqui") SEM chamar
# encaminhar_humano, o lead fica parado — o cartão de contato nunca sai e a IA
# continua ativa. Este guard detecta o CTA no texto final; o orchestrator força
# o handoff quando ele dispara.
#
# Frases que NÃO disparam (menções informacionais):
#   "quem prepara isso é o Joao Bras"
#   "vou deixar salvo pro Joao dar uma olhada"
#   "você já tá em boas mãos com o time"
#   "qualquer coisa é só chamar"
# O guard é construído em torno do CTA de CONTATO/CONECTAR/TRANSFERIR, nunca do
# nome "João Bras" isolado.

def _strip_diacritics(text: str) -> str:
    """Remove diacríticos via NFD + filtro de combining marks (Mn)."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _normalize_for_handoff_re(text: str) -> str:
    """Lowercase + remoção de diacríticos para matching acento-insensitivo."""
    return _strip_diacritics(text.lower())


# Padrões compilados uma vez; operam sobre texto já normalizado (lowercase, sem acentos).
_HANDOFF_ANNOUNCEMENT_RE = re.compile(
    r"(?:"
    r"vou te conectar"
    r"|deixa.{0,10}eu te conectar"   # "deixa eu te conectar" / "deixa-eu te conectar"
    r"|te conectar com o joao"
    r"|vou deixar o contato"          # "vou deixar o contato dele aqui"
    r"|deixando o contato"
    r"|te passar o contato"
    r"|contato dele aqui"
    r"|contato do joao aqui"
    r"|vou transferir"
    r"|vou te transferir"
    r"|vou te passar (?:pro|para o) joao"
    r")"
)


def looks_like_handoff_announcement(text: str) -> bool:
    """Return True ONLY for unambiguous transfer-CTA phrasing.

    Accent- and case-insensitive (via diacritic stripping + lowercase).
    Returns False for mere informational mentions of the seller that are NOT
    a transfer CTA — e.g. "quem cuida disso é o Joao Bras", "em boas mãos".

    Função pura — sem I/O, testável sem mocks.
    """
    if not text:
        return False
    return bool(_HANDOFF_ANNOUNCEMENT_RE.search(_normalize_for_handoff_re(text)))
