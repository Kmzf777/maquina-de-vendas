"""Motivo de perda estruturado (frente F4, 06/11/2026).

`deals.lost_reason` era texto livre e opcional: ninguém conseguia contar por que o atacado
não fecha. Agora toda perda grava também `deals.lost_reason_code` (vocabulário FECHADO,
o mesmo do CHECK em `supabase/migrations/20261106_f4_deals_lost_reason_code.sql` e de
`frontend/src/lib/lost-reason.ts`) e, quando o lead comprou de outro, `lost_competitor`.
O texto livre continua como observação.

Também mora aqui o disparo de `deal_closed_lost` para as perdas que acontecem NO BACKEND
(descarte do agente, ação `mark_deal_lost` da automação, pesquisa de perda). Até a F4 só a
rota do Next (`api/deals/[id]`) emitia o evento, então automação ligada a "Card perdido"
nunca via as perdas feitas pela Valéria.

Leaf module quanto ao banco: não importa o cliente do Supabase.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import unicodedata
from typing import Any

logger = logging.getLogger(__name__)

# (código gravado, rótulo humano). A ORDEM é a do select da tela.
MOTIVOS: tuple[tuple[str, str], ...] = (
    ("preco_margem", "Preço / margem não fechou"),
    ("frete", "Frete"),
    ("pedido_minimo", "Pedido mínimo alto"),
    ("condicao_bonificacao", "Faltou condição / bonificação"),
    ("comprou_outro", "Comprou de outro fornecedor"),
    ("ainda_pesquisando", "Ainda pesquisando"),
    ("consumidor_final", "Era consumidor final (uso próprio)"),
    ("sem_resposta", "Sem resposta"),
    ("outro", "Outro"),
)
CODIGOS: tuple[str, ...] = tuple(c for c, _ in MOTIVOS)
ROTULOS: dict[str, str] = dict(MOTIVOS)

COMPROU_OUTRO = "comprou_outro"
SEM_RESPOSTA = "sem_resposta"
OUTRO = "outro"

# Teto do texto do concorrente: é um nome, não um relato.
MAX_CONCORRENTE = 120


def normalizar_codigo(codigo: Any) -> str | None:
    """O código se ele estiver no vocabulário, senão None. Nunca levanta."""
    if not isinstance(codigo, str):
        return None
    c = codigo.strip().lower()
    return c if c in ROTULOS else None


def codigo_ou_padrao(codigo: Any, padrao: str = OUTRO) -> str:
    """Para caminhos automáticos (agente, automação), que não podem falhar por motivo:
    código inválido ou ausente vira `padrao` ('outro')."""
    return normalizar_codigo(codigo) or padrao


def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


# Palavras que o agente usa no `motivo` do descarte (prompts/base.py pede um motivo
# "analítico e detalhado"). Conservador de propósito: só infere quando UM motivo casa;
# dois ou nenhum viram 'outro', e a pesquisa de perda corrige depois.
_PISTAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("consumidor_final", ("consumidor final", "uso proprio", "consumo proprio", "para casa",
                          "pra casa", "uso pessoal", "consumo pessoal")),
    ("comprou_outro", ("comprou do concorrente", "fechou com o concorrente", "outro fornecedor", "ja tem fornecedor", "ja temos fornecedor",
                       "ja possui fornecedor", "comprou de outro", "fechou com outro", "comprou com outro")),
    ("frete", ("frete",)),
    ("pedido_minimo", ("pedido minimo", "quantidade minima", "minimo alto")),
    ("condicao_bonificacao", ("bonificacao", "condicao de pagamento", "prazo de pagamento", "boleto")),
    ("preco_margem", ("preco", "caro", "margem", "valor alto")),
    ("ainda_pesquisando", ("pesquisando", "cotando", "comparando", "ainda vendo")),
    ("sem_resposta", ("sem resposta", "nao respondeu", "parou de responder", "sumiu")),
)


def inferir_codigo(motivo: Any) -> str | None:
    """Código a partir do texto livre do motivo, ou None quando não dá para dizer."""
    if not isinstance(motivo, str) or not motivo.strip():
        return None
    t = _sem_acento(motivo)
    achados = {cod for cod, pistas in _PISTAS
               if any(re.search(r"\b" + re.escape(p) + r"\b", t) for p in pistas)}
    return achados.pop() if len(achados) == 1 else None


def normalizar_concorrente(texto: Any) -> str | None:
    if not isinstance(texto, str):
        return None
    t = " ".join(texto.split())
    return t[:MAX_CONCORRENTE] or None


def campos_de_perda(codigo: Any, concorrente: Any = None, *, padrao: str = OUTRO) -> dict[str, Any]:
    """Os campos estruturados que vão no UPDATE/INSERT do deal.

    O concorrente só é gravado quando o código é `comprou_outro`; em qualquer outro caso
    a coluna é zerada, para um deal reaberto e perdido de novo não carregar o nome velho.
    """
    cod = codigo_ou_padrao(codigo, padrao)
    return {
        "lost_reason_code": cod,
        "lost_competitor": normalizar_concorrente(concorrente) if cod == COMPROU_OUTRO else None,
    }


# Tarefas em voo: sem referência forte o loop pode coletar a task antes de rodar.
_TAREFAS: set[asyncio.Task] = set()


def emitir_deal_closed_lost(lead_id: str | None, deal_id: str | None, codigo: str | None = None) -> None:
    """Dispara `deal_closed_lost` para a automação. Fail-soft: perder o evento nunca
    derruba a perda em si.

    Chamado de código síncrono que às vezes roda dentro do loop (tool do agente, motor
    da automação) e às vezes fora dele (script). Dentro do loop agenda uma task; fora,
    roda numa thread própria e espera — `asyncio.run` na thread de quem chamou faria
    `set_event_loop(None)` nela, e um `get_event_loop()` posterior ali passaria a falhar.
    """
    if not lead_id:
        return
    try:
        from app.automation.triggers import fire_trigger
        dados = {"deal_id": deal_id, "lost_reason_code": codigo}
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            t = threading.Thread(
                target=lambda: asyncio.run(fire_trigger("deal_closed_lost", lead_id, dados)),
                name="deal_closed_lost", daemon=True)
            t.start()
            t.join(timeout=30)
            return
        task = loop.create_task(fire_trigger("deal_closed_lost", lead_id, dados))
        _TAREFAS.add(task)
        task.add_done_callback(_TAREFAS.discard)
    except Exception as exc:
        logger.error("emitir_deal_closed_lost: lead %s deal %s: %s", lead_id, deal_id, exc)
