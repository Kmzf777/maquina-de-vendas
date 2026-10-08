"""ValerIA de botões v2: texto livre (ou transcrição de áudio) vira UMA etiqueta.

Spec: docs/superpowers/specs/2026-10-08-valeria-botoes-v2-vitrine-design.md §7.

Por que existe: na v1 o texto livre era rebatido com o nudge, e essa foi a maior perda
medida em 07/10 (leads bons entregues −38%). Aqui a IA LÊ o texto e devolve uma das 6
etiquetas de `CLASSES`; o motor (`valeria_engine_v2`) escolhe a mensagem fixa.

O que este módulo NÃO é: ele não conversa e não escreve uma palavra para o cliente.
Clique em botão nunca passa por aqui. Sem persona, sem catálogo, sem histórico longo:
a entrada é a tela atual (id, ramo, botões), as FAQs válidas do ramo, a última
mensagem enviada e o texto do lead (~400 tokens).

Reaproveita os mecanismos do classificador da Recuperação via `_llm_comum`:
`json_mode=True`, `budget_guard`, `token_usage` (`call_type='valeria_botoes_classify'`)
e timeout explícito. Env por `os.getenv`, nunca `Settings` — o motivo está no
cabeçalho de `classifier.py`.

NUNCA levanta. Timeout, quota, teto estourado, JSON inválido, classe inventada, id
fora da tela ou FAQ fora do ramo: tudo vira RUIDO. RUIDO é a saída sem efeito
destrutivo — o motor reoferece os botões e, no 2º seguido, repassa ao vendedor.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.agent.gemini_client import generate, user_content
from app.button_flow import _llm_comum

logger = logging.getLogger(__name__)

_LOG = "[VALERIA V2]"

CLASSES = ("BOTAO", "FAQ", "PERGUNTA", "VENDEDOR", "SAIR", "RUIDO")

CALL_TYPE = "valeria_botoes_classify"


@dataclass(frozen=True)
class Classificacao:
    classe: str                 # uma de CLASSES
    botao_id: str | None = None
    faq_id: str | None = None


RUIDO = Classificacao("RUIDO")

# Mesmo modelo e timeout da Recuperação: a tarefa é escolher um rótulo com os
# exemplos na frente, não redigir.
_MODELO_PADRAO = "gemini-2.5-flash-lite"
_TIMEOUT_PADRAO = 12.0

# {"classe":"BOTAO","botao_id":"card:microlote_pl","faq_id":null} cabe folgado.
_MAX_OUTPUT_TOKENS = 64

# Tetos de entrada: a etiqueta se decide nas primeiras linhas, e quem cola um
# catálogo não pode estourar o orçamento de ~400 tokens.
_MAX_CHARS_TEXTO = 600
_MAX_CHARS_ULTIMA = 300
_MAX_CHARS_ROTULO = 80

# Papel, etiquetas e formato. Sem acento de propósito (mesma regra do `classifier.py`:
# o texto do WhatsApp raramente tem, e sai mais barato em tokens).
_CABECALHO = """Classifique a mensagem do lead em UMA etiqueta. NAO responda ao lead: devolva so o JSON.
Formato: {"classe":"...","botao_id":null,"faq_id":null}

BOTAO: a mensagem equivale a um dos botoes da tela atual; botao_id = id do botao.
FAQ: duvida que esta na lista de duvidas abaixo; faq_id = id da duvida.
PERGUNTA: duvida ou pedido real que nao casa com nenhum botao nem duvida da lista.
VENDEDOR: quer falar com uma pessoa, atendente ou vendedor.
SAIR: nao quer mais conversa nem mensagens.
RUIDO: saudacao solta, emoji, agradecimento, nada decidivel.
Use so ids listados abaixo; sem id que case, nao use BOTAO nem FAQ."""

# Exemplos de casamento (spec §7.3, tirados das conversas reais). Os de BOTAO e FAQ
# só entram quando o id existe na tela/ramo atual: um exemplo com id ausente
# ensinaria o modelo a devolver um id que a validação vai jogar fora.
_EXEMPLOS_BOTAO = (
    ("tenho uma cafeteria", "cafeteria"),
    ("uns 200 kgs", "mais100"),
)
_EXEMPLOS_FAQ = (
    ("qual o valor do quilo?", "preco"),
    ("tem frete gratis?", "frete"),
)
_EXEMPLOS_FIXOS = (
    ("voces fazem cafe com acai?", "PERGUNTA"),
    ("bom dia", "RUIDO"),
    ("quero falar com alguem", "VENDEDOR"),
    ("nao quero mais", "SAIR"),
)

_ESPACOS = re.compile(r"\s+")


def modelo() -> str:
    """Modelo do classificador. Env VALERIA_CLASSIFIER_MODEL."""
    return _llm_comum.ler_modelo("VALERIA_CLASSIFIER_MODEL", _MODELO_PADRAO)


def timeout_segundos() -> float:
    """Teto de espera pela classificação. Env VALERIA_CLASSIFIER_TIMEOUT_S."""
    return _llm_comum.ler_timeout("VALERIA_CLASSIFIER_TIMEOUT_S", _TIMEOUT_PADRAO, _LOG)


def _linha(texto, teto: int) -> str:
    """Uma linha só, sem quebras, truncada."""
    return _ESPACOS.sub(" ", str(texto or "")).strip()[:teto]


def _json(objeto: dict) -> str:
    return json.dumps(objeto, ensure_ascii=False, separators=(",", ":"))


def _ids_botoes(botoes) -> list[tuple[str, str]]:
    pares = []
    for item in botoes or ():
        try:
            bid, rotulo = item
        except (TypeError, ValueError):
            continue
        if isinstance(bid, str) and bid:
            pares.append((bid, _linha(rotulo, _MAX_CHARS_ROTULO)))
    return pares


def _faqs_validas(faqs) -> dict[str, str]:
    if not isinstance(faqs, dict):
        return {}
    return {
        fid: _linha(desc, _MAX_CHARS_ROTULO)
        for fid, desc in faqs.items() if isinstance(fid, str) and fid
    }


def montar_prompt(
    texto: str, *, no_id: str | None, ramo: str | None,
    botoes: list[tuple[str, str]], faqs: dict[str, str], ultima_mensagem: str,
) -> str:
    """Prompt completo (enviado como UM turno de usuário, sem system_instruction)."""
    pares = _ids_botoes(botoes)
    duvidas = _faqs_validas(faqs)
    ids = {bid for bid, _ in pares}

    partes = [_CABECALHO, "", f"Tela atual: {no_id or '-'} (ramo: {ramo or '-'})"]
    partes.append("Botoes da tela (id: rotulo):")
    if pares:
        partes.extend(f"{bid}: {rotulo}" for bid, rotulo in pares)
    else:
        partes.append("(nenhum)")
    partes.append("Duvidas (faq_id: descricao):")
    if duvidas:
        partes.extend(f"{fid}: {desc}" for fid, desc in duvidas.items())
    else:
        partes.append("(nenhuma)")

    partes.append("Exemplos:")
    for frase, bid in _EXEMPLOS_BOTAO:
        if bid in ids:
            partes.append(f'"{frase}" -> {_json({"classe": "BOTAO", "botao_id": bid})}')
    for frase, fid in _EXEMPLOS_FAQ:
        if fid in duvidas:
            partes.append(f'"{frase}" -> {_json({"classe": "FAQ", "faq_id": fid})}')
    for frase, classe in _EXEMPLOS_FIXOS:
        partes.append(f'"{frase}" -> {_json({"classe": classe})}')

    partes.append("")
    partes.append(f"Ultima mensagem enviada ao lead: {_linha(ultima_mensagem, _MAX_CHARS_ULTIMA) or '-'}")
    partes.append(f"Mensagem do lead: {_linha(texto, _MAX_CHARS_TEXTO)}")
    return "\n".join(partes)


def _validar(bruto: str | None, ids_botoes: set[str], ids_faq: set[str]) -> Classificacao | None:
    """Saída do modelo -> Classificacao válida, ou None (o chamador devolve RUIDO).

    Aceita JSON com cerca de markdown ou prosa em volta, mas SEM o fallback por
    palavra solta do `classifier.py`: aqui a etiqueta precisa vir com o id certo, e
    adivinhar id em prosa é inventar.
    """
    texto = (bruto or "").strip()
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        return None
    try:
        objeto = json.loads(texto[inicio:fim + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(objeto, dict):
        return None
    classe = objeto.get("classe")
    if not isinstance(classe, str) or classe.strip().upper() not in CLASSES:
        return None
    classe = classe.strip().upper()
    if classe == "BOTAO":
        bid = objeto.get("botao_id")
        return Classificacao("BOTAO", botao_id=bid) if isinstance(bid, str) and bid in ids_botoes else None
    if classe == "FAQ":
        fid = objeto.get("faq_id")
        return Classificacao("FAQ", faq_id=fid) if isinstance(fid, str) and fid in ids_faq else None
    return Classificacao(classe)


async def classificar(
    texto: str, *, no_id: str, ramo: str | None,
    botoes: list[tuple[str, str]], faqs: dict[str, str],
    ultima_mensagem: str, lead_id: str | None = None,
) -> Classificacao:
    """Classifica UM texto livre do lead. Nunca levanta; qualquer falha → RUIDO.

    `botao_id` sai sempre entre os ids de `botoes`, e `faq_id` entre as chaves de
    `faqs`. `lead_id` só serve para atribuir a linha de `token_usage`.
    """
    try:
        limpo = str(texto or "").strip()
        if not limpo or not any(c.isalnum() for c in limpo):
            # Emoji solto, figurinha, áudio não transcrito: RUIDO sem gastar token.
            return RUIDO

        if _llm_comum.budget_estourado(_LOG):
            logger.warning("%s teto diario de LLM estourado — classificador devolvendo RUIDO", _LOG)
            return RUIDO

        prompt = montar_prompt(
            limpo, no_id=no_id, ramo=ramo, botoes=botoes, faqs=faqs,
            ultima_mensagem=ultima_mensagem,
        )
        modelo_usado = modelo()
        # `generate` resolvido no namespace deste módulo: é o ponto que os testes patcham.
        resultado = await _llm_comum.chamar_com_timeout(
            generate,
            modelo_usado,
            timeout=timeout_segundos(),
            contents=[user_content(prompt)],
            json_mode=True,
            thinking_off=True,
            temperature=0.0,
            max_output_tokens=_MAX_OUTPUT_TOKENS,
        )
        _llm_comum.contabilizar(
            resultado, modelo_usado, lead_id, call_type=CALL_TYPE, prefixo_log=_LOG,
        )

        bruto = getattr(resultado, "text", None)
        classificacao = _validar(
            bruto, {bid for bid, _ in _ids_botoes(botoes)}, set(_faqs_validas(faqs)),
        )
        if classificacao is None:
            logger.warning(
                "%s saida inutilizavel do classificador no=%s (%.120s) — devolvendo RUIDO",
                _LOG, no_id, bruto or "",
            )
            return RUIDO
        logger.info(
            "%s no=%s classe=%s botao=%s faq=%s texto=%.80s", _LOG, no_id,
            classificacao.classe, classificacao.botao_id, classificacao.faq_id, limpo,
        )
        return classificacao
    except Exception as exc:
        logger.warning(
            "%s classificador falhou (%s: %s) — devolvendo RUIDO", _LOG, type(exc).__name__, exc,
        )
        return RUIDO
