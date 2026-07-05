"""Guardas determinísticas de aderência do agente (2026-07-04).

Funções PURAS (sem I/O, sem efeitos colaterais) usadas para:

1. `strip_prohibited_phrases` — limpar, do texto final do assistente, frases que a
   Valéria não deve emitir (ex.: "pra te direcionar da melhor forma" — jargão de
   call-center que não combina com a persona).
2. `detect_auto_producer` — detectar, na mensagem do LEAD, sinais explícitos de que
   ele mesmo PRODUZ café (torrefador/produtor/marca própria) — fora do ICP de compra.

Ambas seguem o mesmo padrão de normalização (NFD + lower, removendo diacríticos) já
usado em `app.agent.tools._normalize_text` e `app.agent.orchestrator._strip_diacritics`,
replicado aqui localmente para não criar acoplamento entre módulos.
"""

from __future__ import annotations

import re
import unicodedata


def _normalize(text: str | None) -> str:
    """Lowercase + remoção de diacríticos (NFD, filtra combining marks Mn).

    Espelha `_normalize_text` de tools.py — mesma técnica, sem importar de lá para
    manter este módulo independente (guarda de aderência é sua própria unidade).
    """
    nfd = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------------
# 1. strip_prohibited_phrases
# ---------------------------------------------------------------------------
# Frases-alvo (e variações próximas) que a IA às vezes emite e que soam como
# jargão de call-center — não combinam com a voz da Valéria. Operamos sobre o
# texto NORMALIZADO para casar, mas removemos do texto ORIGINAL usando os spans
# encontrados na versão normalizada (normalização preserva o comprimento — NFD +
# filtro de Mn nunca muda o índice de um caractere não-combinante), então os
# offsets batem 1:1 entre normalizado e original.
#
# O regex cobre o núcleo comum "pra/para (eu) te direcionar" com um sufixo
# opcional "da melhor forma", incluindo possíveis variações de espaçamento.
_PROHIBITED_PHRASE_RE = re.compile(
    r"\b(?:pra|para)\s+(?:eu\s+)?te\s+direcionar(?:\s+da\s+melhor\s+forma)?\b"
)


def _collapse_whitespace_and_punctuation(text: str) -> str:
    """Normaliza espaços/pontuação duplicada deixados pela remoção de uma frase.

    - Colapsa espaços múltiplos em um único espaço.
    - Remove espaço antes de pontuação (", ", "  ,").
    - Colapsa pontuação duplicada resultante (",," "..", "  ").
    - Apara espaços nas bordas de cada linha e do texto todo.
    """
    # Colapsa espaços/tabs (não mexe em quebras de linha propositais)
    collapsed = re.sub(r"[ \t]{2,}", " ", text)
    # Remove espaço sobrando antes de vírgula/ponto/exclamação/interrogação
    collapsed = re.sub(r"[ \t]+([,.!?])", r"\1", collapsed)
    # Colapsa pontuação duplicada (",," "..." sobrando de junções, mas preserva "...")
    collapsed = re.sub(r",{2,}", ",", collapsed)
    collapsed = re.sub(r"([,.!?]) ,", r"\1", collapsed)
    # Remove vírgula/ponto isolado sobrando logo após outra pontuação
    collapsed = re.sub(r"([,.!?])\s*\1+", r"\1", collapsed)
    # Apara espaços em cada linha e remove linhas que ficaram vazias entre textos
    lines = [ln.strip() for ln in collapsed.split("\n")]
    collapsed = "\n".join(lines)
    # Colapsa 3+ quebras de linha resultantes em no máximo 2 (parágrafo)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def strip_prohibited_phrases(text: str) -> str:
    """Remove frases proibidas do texto final do assistente, preservando o resto.

    Robusto a acentos e caixa (casa sobre uma versão normalizada do texto, mas
    remove os trechos correspondentes do texto ORIGINAL — preservando acentos e
    maiúsculas do restante da mensagem). Limpa espaços/pontuação duplicada
    deixados pela remoção. Se nada casar, retorna o texto inalterado (idêntico,
    sem sequer passar pelo collapse).

    Função pura — sem I/O, sem logging, testável isoladamente.
    """
    if not text:
        return text

    normalized = _normalize(text)
    matches = list(_PROHIBITED_PHRASE_RE.finditer(normalized))
    if not matches:
        return text

    # Remove os spans casados (na ordem inversa, para não invalidar os índices
    # dos spans anteriores) diretamente do texto ORIGINAL — normalização NFD +
    # filtro de Mn nunca insere/remove caracteres não-combinantes, então os
    # índices batem entre `normalized` e `text`.
    result = text
    for m in reversed(matches):
        result = result[: m.start()] + result[m.end() :]

    return _collapse_whitespace_and_punctuation(result)


# ---------------------------------------------------------------------------
# 2. detect_auto_producer
# ---------------------------------------------------------------------------
# Sinais explícitos (e só explícitos) de que o LEAD é ele mesmo produtor/torrefador
# de café — fora do ICP de compra da Café Canastra. CONSERVADOR de propósito:
# frases elípticas/ambíguas ("sou eu mesma") NÃO devem casar — só entram sinais
# que mencionam produção/torra/marca/fazenda de café de forma inequívoca.
_AUTO_PRODUCER_SIGNALS = (
    "eu que produzo",
    "eu mesmo torro",
    "eu mesma torro",
    "sou produtor",
    "sou produtora",
    "produzo meu cafe",
    "produzo meu proprio cafe",
    "meu proprio cafe",
    "tenho minha marca de cafe",
    "tenho minha fazenda de cafe",
    "tenho minha propria marca de cafe",
)


def detect_auto_producer(text: str) -> bool:
    """True quando a mensagem do LEAD indica que ele mesmo PRODUZ café.

    Casa apenas sinais explícitos de produção/torra/marca/fazenda de café
    (lista `_AUTO_PRODUCER_SIGNALS`). Robusto a acentos e caixa via `_normalize`.
    Deliberadamente CONSERVADOR: NÃO casa com elípticas ambíguas como
    "sou eu mesma" isoladas, nem com menções neutras de consumo
    ("tomo café todo dia", "quero comprar café").

    Função pura — sem I/O, testável isoladamente.
    """
    if not text:
        return False
    normalized = _normalize(text)
    return any(signal in normalized for signal in _AUTO_PRODUCER_SIGNALS)
