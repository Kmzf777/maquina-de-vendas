"""Backfill de `messages.metadata.interativo` nas mensagens antigas da ValerIA de botões (v1).

Dry-run por padrão. Só escreve com `--apply` explícito.

── Por que existe ─────────────────────────────────────────────────────────────
Até 09/10/2026 a linha persistida de cada tela da ValerIA guardava só o TEXTO: a
lista, os botões e a foto que o lead tinha na tela não chegavam ao /conversas. Os
runners agora gravam a estrutura em `metadata.interativo` (forma em
`app/button_flow/interativo.py`). Este script reconstrói a mesma estrutura para as
linhas antigas, para o vendedor ver também o histórico.

── Como reconstrói ────────────────────────────────────────────────────────────
1. TELA: o `content` gravado é o corpo do nó já resolvido (`valeria_runner._resolver`).
   Casa contra o corpo de cada nó do registry v1 com os overrides de
   `valeria_flow_content` aplicados (como o runner faz), linha a linha: a linha com
   marcador (`{preco}`, `{prazo}`) aceita qualquer texto ou some inteira (o runner
   CORTA a linha cujo marcador não resolveu). A foto é o `media_url` da própria linha
   quando ela foi gravada como `image` — é a URL pública que foi no header.
2. NUDGE: o corpo do nudge reenvia os botões do MESMO nó (sem a foto). O nó vem da
   tela anterior da mesma conversa, na ordem de `created_at`. Sem tela anterior
   casada, a linha é pulada (nunca chutada).
3. Casamento ambíguo (dois nós com o mesmo corpo) ou nenhum: a linha fica como está.
4. RÓTULO EDITADO: nó que tem `rotulos_antigos` em `valeria_flow_content` teve algum
   botão renomeado na tela. Não há como saber qual rótulo o lead viu naquela linha,
   então ela (e o nudge que reenviou aquela tela) fica de fora, contada como
   `rotulo_editado` — gravar o rótulo de HOJE mostraria uma tela que o lead não viu.

LIMITES CONHECIDOS: overrides são os de HOJE. Uma linha enviada com um corpo que foi
editado depois não casa (aparece em "sem_casamento") — e é o comportamento certo:
desenhar botões com o rótulo de hoje numa mensagem antiga seria mentir. As linhas da
v2 (vitrine/carrossel) não são reconstruídas: os cards são montados do catálogo no
envio e o texto deles não está no registry.

── O que NUNCA faz ────────────────────────────────────────────────────────────
- Não sobrescreve `metadata.interativo` existente (o UPDATE também filtra por isso).
- Não apaga chave de `metadata`: o valor gravado é o metadata existente + `interativo`.
- Não envia nada a ninguém.

Leitura paginada (`_PAGINA` < 1000: o PostgREST corta toda leitura em 1000 linhas e
uma página cheia precisa significar "tem mais").

Uso (dentro do container da API, onde `app` e o `.env` existem):
    python -m scripts.backfill_interativo_valeria                    # só mostra
    python -m scripts.backfill_interativo_valeria --amostra 20       # mostra mais
    python -m scripts.backfill_interativo_valeria --desde 2026-09-29 # recorte
    python -m scripts.backfill_interativo_valeria --apply            # GRAVA (autorizar antes)
"""
from __future__ import annotations

import argparse
import logging
import re
from dataclasses import dataclass

from app.button_flow import interativo
from app.button_flow import valeria_content
from app.button_flow import valeria_registry as reg

logger = logging.getLogger(__name__)

_PAGINA = 500
SENT_BY = "valeria_botoes"
# Corpo default do nudge ANTES de 01/10/2026 (valeria_registry.py, commit 20022cc0).
# As linhas desse período foram enviadas com ele.
NUDGE_ANTIGO = "pra eu te passar o valor certo, é só tocar numa das opções 👇"
_MARCADOR = re.compile(r"\{[a-z_]+\}")
_EDITADA = "rotulo_editado"


# ── Lógica pura (o que o teste exercita) ────────────────────────────────────
def _linhas(texto: str | None) -> list[str]:
    """Linhas não vazias, sem espaço nas pontas — a forma comparável de um corpo."""
    return [l.strip() for l in (texto or "").splitlines() if l.strip()]


def _padrao(corpo: str) -> re.Pattern:
    """Regex do corpo resolvido: linha com marcador = qualquer linha OU nenhuma."""
    partes = []
    for linha in _linhas(corpo):
        if _MARCADOR.search(linha):
            partes.append(r"(?:[^\n]+\n)?")
        else:
            partes.append(re.escape(linha) + r"\n")
    return re.compile("".join(partes))


@dataclass(frozen=True)
class Tela:
    """Uma tela interativa que o runner v1 pode ter enviado."""
    no_id: str
    tipo: str                          # "lista" | "botoes"
    padrao: re.Pattern
    rotulos: tuple[str, ...] = ()
    linhas: tuple[tuple[str, str], ...] = ()
    botao_lista: str = reg.ROTULO_BOTAO_LISTA
    com_foto: bool = False
    rotulo_editado: bool = False

    def estrutura(self, media_url: str | None = None) -> dict:
        if self.tipo == "lista":
            return interativo.lista(self.botao_lista, self.linhas)
        return interativo.botoes(self.rotulos, imagem=media_url if self.com_foto else None)


def nos_com_rotulo_editado(overrides: dict) -> set[str]:
    """Nós com algum botão renomeado (há `rotulos_antigos`). Mesma leitura do runner."""
    return set(valeria_content.historico_de_rotulos(overrides))


def montar_telas(nos: dict, terminais: dict, *, rotulo_lista: str | None = None,
                 editados: set[str] | frozenset = frozenset()) -> list[Tela]:
    """As telas candidatas, espelhando `valeria_runner.enviar_no`/`enviar_terminal`.

    `editados` marca as telas cujo rótulo mudou depois do envio (`nos_com_rotulo_editado`).
    """
    telas: list[Tela] = []
    for no in nos.values():
        if not no.botoes or not _linhas(no.corpo):
            continue
        if no.tela == "lista":
            telas.append(Tela(no.id, "lista", _padrao(no.corpo),
                              linhas=tuple((b.titulo, b.descricao) for b in no.botoes),
                              botao_lista=rotulo_lista or reg.ROTULO_BOTAO_LISTA,
                              rotulo_editado=no.id in editados))
        elif no.tela in ("botoes", "foto_botoes"):
            telas.append(Tela(no.id, "botoes", _padrao(no.corpo),
                              rotulos=tuple(b.titulo for b in no.botoes),
                              com_foto=no.tela == "foto_botoes",
                              rotulo_editado=no.id in editados))
    for terminal in terminais.values():
        if terminal.prazos and _linhas(terminal.corpo):
            telas.append(Tela(terminal.id, "botoes", _padrao(terminal.corpo),
                              rotulos=tuple(b.titulo for b in reg.BOTOES_PRAZO),
                              rotulo_editado=terminal.id in editados))
    return telas


def casar_tela(content: str | None, telas: list[Tela]) -> list[Tela]:
    """Todas as telas cujo corpo casa com `content` (0, 1 ou — ambíguo — mais)."""
    alvo = "\n".join(_linhas(content))
    if not alvo:
        return []
    return [t for t in telas if t.padrao.fullmatch(alvo + "\n")]


def _do_nudge(anterior: dict) -> dict:
    """O nudge reenvia a MESMA tela sem a foto (`enviar_no(..., sem_foto=True)`)."""
    estrutura = dict(anterior)
    if estrutura.get("tipo") == "botoes":
        estrutura["imagem"] = None
    return estrutura


def inferir(linhas: list[dict], telas: list[Tela],
            corpos_nudge: set[str]) -> tuple[list[tuple[str, dict]], dict]:
    """(escritas, contagem) para linhas em ordem de `created_at`. Pura.

    `escritas` = [(message_id, metadata_completo)], com o metadata existente mesclado.
    A tela anterior por conversa vale para o nudge seguinte; uma linha que não casa
    ZERA essa memória (o nudge depois dela seria da tela que não reconhecemos).
    """
    nudges = {"\n".join(_linhas(c)) for c in corpos_nudge if c}
    contagem = {"lidas": 0, "ja_tinha": 0, "tela": 0, "nudge": 0, "nudge_sem_tela": 0,
                "ambiguo": 0, "sem_casamento": 0, "rotulo_editado": 0}
    # Tela anterior por conversa; `_EDITADA` = a tela casou, mas com rótulo editado.
    ultima: dict[str, dict | str] = {}
    escritas: list[tuple[str, dict]] = []
    for linha in linhas:
        contagem["lidas"] += 1
        conv = linha.get("conversation_id")
        meta = linha.get("metadata") if isinstance(linha.get("metadata"), dict) else None
        if meta and isinstance(meta.get(interativo.CHAVE), dict):
            contagem["ja_tinha"] += 1
            ultima[conv] = meta[interativo.CHAVE]
            continue
        texto = "\n".join(_linhas(linha.get("content")))
        if texto in nudges:
            anterior = ultima.get(conv)
            if anterior is None:
                contagem["nudge_sem_tela"] += 1
                continue
            if anterior == _EDITADA:
                contagem["rotulo_editado"] += 1
                continue
            estrutura = _do_nudge(anterior)
            contagem["nudge"] += 1
        else:
            casadas = casar_tela(texto, telas)
            if len(casadas) != 1:
                contagem["ambiguo" if casadas else "sem_casamento"] += 1
                ultima.pop(conv, None)
                continue
            if casadas[0].rotulo_editado:
                contagem["rotulo_editado"] += 1
                ultima[conv] = _EDITADA
                continue
            media = linha.get("media_url") if linha.get("message_type") == "image" else None
            estrutura = casadas[0].estrutura(media)
            ultima[conv] = estrutura
            contagem["tela"] += 1
        novo = interativo.metadata(lambda e=estrutura: e, base=meta)
        if novo:
            escritas.append((linha["id"], novo))
    return escritas, contagem


# ── I/O ─────────────────────────────────────────────────────────────────────
def _conteudo_atual() -> tuple[list[Tela], set[str]]:
    """Telas e corpos de nudge com os overrides de hoje — o mesmo caminho do runner."""
    overrides = valeria_content.carregar(reg.FLOW_ID)
    nos = valeria_content.aplicar(reg.NOS, overrides)
    terminais = valeria_content.aplicar_terminais(reg.TERMINAIS, overrides)
    rotulo_lista = (overrides.get(reg.CHAVE_ROTULO_LISTA) or {}).get("corpo")
    nudge = (overrides.get(reg.CHAVE_NUDGE) or {}).get("corpo")
    return (montar_telas(nos, terminais, rotulo_lista=rotulo_lista,
                         editados=nos_com_rotulo_editado(overrides)),
            {reg.CORPO_NUDGE, NUDGE_ANTIGO, nudge or ""})


def _ler_linhas(db, desde: str | None) -> list[dict]:
    """Todas as saídas da ValerIA de botões, em ordem, página a página."""
    linhas: list[dict] = []
    inicio = 0
    while True:
        consulta = (db.table("messages")
                    .select("id,conversation_id,content,metadata,media_url,message_type,created_at")
                    .eq("sent_by", SENT_BY).eq("role", "assistant"))
        if desde:
            consulta = consulta.gte("created_at", desde)
        pagina = (consulta.order("created_at").order("id")
                  .range(inicio, inicio + _PAGINA - 1).execute().data or [])
        linhas.extend(pagina)
        if len(pagina) < _PAGINA:
            return linhas
        inicio += _PAGINA


def _gravar(db, escritas: list[tuple[str, dict]]) -> dict:
    """Grava com o UPDATE protegido. Só conta como gravada a linha que ele DEVOLVEU.

    `sem_efeito` = o filtro `metadata->interativo is null` não casou (a linha ganhou
    `interativo` entre a leitura e a escrita, ou sumiu) — nada foi alterado.
    """
    contagem = {"gravadas": 0, "sem_efeito": 0, "erros": 0}
    for message_id, metadata in escritas:
        try:
            resultado = (db.table("messages").update({"metadata": metadata})
                         .eq("id", message_id).is_("metadata->interativo", "null").execute())
        except Exception as exc:
            contagem["erros"] += 1
            logger.error("backfill_interativo_valeria: %s não gravada: %s", message_id, exc)
            continue
        contagem["gravadas" if getattr(resultado, "data", None) else "sem_efeito"] += 1
    return contagem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="grava (default: dry-run)")
    parser.add_argument("--desde", help="só linhas com created_at >= esta data (ISO)")
    parser.add_argument("--amostra", type=int, default=8, help="quantas linhas mostrar")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    from app.db.supabase import get_supabase  # só aqui: o import do teste não toca o banco
    db = get_supabase()
    telas, nudges = _conteudo_atual()
    linhas = _ler_linhas(db, args.desde)
    escritas, contagem = inferir(linhas, telas, nudges)

    print(f"telas candidatas do registry v1: {len(telas)}")
    print("contagem:", contagem)
    por_id = {l["id"]: l for l in linhas}
    for message_id, metadata in escritas[: args.amostra]:
        conteudo = (por_id[message_id].get("content") or "").replace("\n", " ")[:70]
        print(f"  {message_id}  {metadata[interativo.CHAVE]}  <- {conteudo!r}")
    if not args.apply:
        print(f"DRY-RUN: {len(escritas)} linhas seriam gravadas. Rode com --apply para gravar.")
        return
    print("gravação:", _gravar(db, escritas))


if __name__ == "__main__":
    main()
