"""Orquestração da ValerIA de botões v2 (vitrine primeiro): o único módulo da v2 com I/O.

Mesma divisão do runner da v1 (`valeria_runner.py`): guardas -> evento -> decisão ->
efeitos -> envio -> estado. `valeria_engine_v2.decidir` é puro, `valeria_registry_v2`
é só dado e `valeria_classifier` só devolve uma etiqueta; aqui ficam o banco, a Meta,
o catálogo e o CRM.

REUSA da v1 por import (via o módulo `v1`, para que um dublê no namespace da v1 valha
também aqui): releitura do estado, guarda de não-rodar, montagem do evento, detector
do robô do lead, histórico de rótulos, evidência do turno, score, envio de nó/terminal
(`_enviar`), cartão do vendedor, foto pública e persistência de estado. O que a v2
precisou ter localmente é o que na v1 carimba `reg.FLOW_ID`: `estado_inicial_v2`,
`no_atual_v2`, `proximo_estado_v2` e `_notificar_sem_rodar` (o da v1 grava
`estado_inicial()` da v1 quando o `flow_state` está vazio, e `runner.fluxo_efetivo`
passaria a mandar a conversa para a v1 no dia em que o humano a devolvesse).

── Decisões que o plano não fixava ──────────────────────────────────────────
1. A 3ª MENSAGEM DA VITRINE. Em "completa" o motor põe em `decisao.mensagem` o corpo
   do NÓ (que é o corpo do carrossel) e os botões de ação; então o carrossel usa
   `mensagem.corpo` e a 3ª mensagem é `CORPO_ACOES` + `mensagem.botoes`. Em "tabela"
   e "acoes" a 3ª mensagem é `decisao.mensagem` INTEIRA (corpo e botões), como o
   docstring de `DecisaoV2.vitrine` exige: ela traz `CORPO_ACOES` no caso normal e o
   corpo do nudge no RUIDO.
2. O CATÁLOGO DE PRODUÇÃO NÃO PROJETA `is_active`. `catalog._fetch_active_products`
   filtra `is_active=true` na query e não devolve a coluna, mas
   `valeria_tabela.precos_por_nome` descarta linha sem `is_active` verdadeiro — sem a
   marca abaixo (`_ler_catalogo`) TODO card sumiria e TODA vitrine viraria "tabela
   sendo atualizada" + repasse.
3. A TABELA É CALCULADA ANTES DO CARROSSEL. Sem preço nenhum não sai NEM o carrossel
   (o lead receberia uma vitrine sem preço seguida de "a tabela tá sendo atualizada").
4. CARD SEM FOTO PUBLICADA. A Meta exige imagem em todo card; se alguma foto não
   publicou, a mensagem 1 sai como texto com todos os cards (a degradação de "menos
   de 2 cards"), em vez de esconder um produto do carrossel.
5. `flow_state.viu` ("vitrine", "tabela") existe para a linha "Viu:" da nota (§5.3):
   só o envio sabe o que de fato saiu.
6. A MENSAGEM PRONTA DO ANÚNCIO não entra em "Mensagens escritas pelo lead": quem a
   escreveu foi o anúncio, e o ramo já está no cabeçalho da nota.
7. A NOTA GENÉRICA DA v1 NÃO SAI. `effects.aplicar(..., nota_sem_qualificacao=False)`
   tira do transbordo o "Nenhuma qualificação por conversa — abordar direto", que
   contradiria o resumo da v2 (`montar_nota`), gravado logo depois.
8. CATÁLOGO VAZIO = UMA MENSAGEM. O aviso já diz que o João foi chamado; o corpo do
   terminal de handoff repetiria isso, então sai só o aviso + o cartão do vendedor.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone

from app.agent import catalog as _catalogo
from app.button_flow import config, effects, interativo, valeria_classifier, valeria_content, valeria_tabela
from app.button_flow import runner as _irmao
from app.button_flow import valeria_engine as motor_v1
from app.button_flow import valeria_registry as reg1
from app.button_flow import valeria_engine_v2 as motor
from app.button_flow import valeria_registry_v2 as r2
from app.button_flow import valeria_runner as v1
from app.button_flow.engine import Clique, Mensagem, Texto, normalizar
from app.button_flow.valeria_engine_v2 import DecisaoV2, TextoClassificado
from app.conversations.service import get_history, save_message
from app.db.supabase import get_supabase
from app.whatsapp.meta import extract_wamid

logger = logging.getLogger(__name__)

_LOG = "[VALERIA V2]"

# O mesmo `sent_by` da v1: o CRM e o detector de autoresponder já leem esse valor.
SENT_BY = "valeria_botoes"

MSG_TABELA_INDISPONIVEL = ("nossa tabela tá sendo atualizada; já chamei o João Brás aqui "
                           "pra te passar os valores")
MSG_REPASSE_AUTO = "vou deixar o João te chamando por aqui pra seguir com você 🙂"
MOTIVO_SEM_TABELA = "tabela indisponível (catálogo sem preço) — repasse automático"
# Marcador de preço que não resolveu no catálogo: nunca um número inventado, nunca o
# marcador cru.
SOB_CONSULTA = "sob consulta"

# `products.sector` de cada ramo (valores de produção conferidos em 08/10/2026).
SETOR_DO_RAMO = {"atacado": "Atacado", "private_label": "Private Label"}
ROTULO_DO_RAMO = {"atacado": "Atacado", "private_label": "Marca própria",
                  "consumo": "Consumo próprio", "exportacao": "Exportação"}
# (nó, rótulo na nota, sufixo) — as respostas de qualificação que viram linha da nota.
_QUALIFICACAO = (("QA1", "Negócio", ""), ("QA2", "Volume", "/mês"),
                 ("QP1", "Marca", ""), ("QP2", "Quantidade", ""),
                 ("E1", "Destino", ""), ("E2", "Exporta por", ""), ("E3", "Objetivo", ""))

_LINHAS_HISTORICO = 30
_MAX_TEXTOS_NOTA = 5
_MAX_CHARS_TEXTO_NOTA = 200
_MARCADOR_PRECO = re.compile(r"\{preco:([^}]+)\}")
_PREFIXO_CARD = "card:"


# ── Estado ──────────────────────────────────────────────────────────────────
def estado_inicial_v2() -> dict:
    return {"flow": r2.FLOW_ID, "node": r2.NO_ENTRADA, "nudges": 0}


def no_atual_v2(estado) -> str | None:
    """Nó da v2 em que o lead está; None = primeiro contato (ou estado de outro fluxo)."""
    if not isinstance(estado, dict) or estado.get("flow") != r2.FLOW_ID:
        return None
    node = estado.get("node")
    return node if isinstance(node, str) and node else None


# Desfechos da v1 que encerram o atendimento em SILÊNCIO para sempre (o motor da v1
# devolve `ignorar` neles). Lidos pela v2 como "estado alheio", recomeçariam o lead
# como primeiro contato no dia da troca de perfil — então a v2 os respeita.
_ENCERRADOS_NA_V1 = frozenset({"T_HUMANO", "T_FIM"})


def encerrado_na_v1(estado) -> bool:
    """True para o lead que a v1 deixou em `T_HUMANO`/`T_FIM` (silêncio definitivo).

    Só esses dois: v1 no meio do fluxo, `T_ADIADO` e Recuperação seguem recomeçando
    na v2 como primeiro contato, como antes.
    """
    return (isinstance(estado, dict) and estado.get("flow") == reg1.FLOW_ID
            and estado.get("node") in _ENCERRADOS_NA_V1)


def _ramo(estado, no: str | None) -> str | None:
    """Ramo da conversa: `flow_state.ramo`; senão o do nó, exceto "entrada" (VK/VO/N0)."""
    ramo = estado.get("ramo") if isinstance(estado, dict) else None
    if isinstance(ramo, str) and ramo:
        return ramo
    ramo = r2.RAMO_DO_NO.get(no or "")
    return ramo if ramo and ramo != "entrada" else None


def proximo_estado_v2(estado, decisao: DecisaoV2, *, viu=()) -> dict:
    """Estado do turno seguinte. Pura — o `updated_at` é do persistidor.

    Merge sobre o estado anterior (chaves de outros donos sobrevivem, como na v1):
    `decisao.memoria` é mesclada (`respostas` um nível abaixo), `faqs` acumula o
    `decisao.faq` do turno e `viu` acumula o que a vitrine de fato enviou.
    """
    base = dict(estado) if isinstance(estado, dict) else {}
    for chave, valor in (decisao.memoria or {}).items():
        if chave == "respostas" and isinstance(valor, dict):
            antigas = base.get("respostas")
            base["respostas"] = {**(antigas if isinstance(antigas, dict) else {}), **valor}
        else:
            base[chave] = valor
    if decisao.faq:
        faqs = base.get("faqs")
        base["faqs"] = [*(faqs if isinstance(faqs, list) else []), decisao.faq]
    if viu:
        vistos = base.get("viu")
        vistos = list(vistos) if isinstance(vistos, list) else []
        base["viu"] = vistos + [v for v in viu if v not in vistos]
    base["flow"] = r2.FLOW_ID
    base["node"] = decisao.proximo_no
    base["nudges"] = v1._nudges(estado) + (1 if decisao.marcar_nudge else 0)
    return base


# ── Conteúdo editável ───────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Conteudo:
    nos: dict
    terminais: dict
    nudge: str | None
    rotulo_lista: str | None
    historico: dict
    textos: dict          # chave de CHAVES_TEXTO -> texto (override ou default)


def _carregar_conteudo() -> _Conteudo:
    """Overrides de `valeria_flow_content` para a v2. Fail-open: erro = defaults."""
    try:
        overrides = valeria_content.carregar(r2.FLOW_ID)
    except Exception as exc:
        logger.warning("%s overrides não lidos — defaults do registry: %s", _LOG, exc)
        overrides = {}
    if not isinstance(overrides, dict):
        overrides = {}

    def _corpo(chave: str) -> str | None:
        linha = overrides.get(chave)
        corpo = linha.get("corpo") if isinstance(linha, dict) else None
        return corpo or None

    textos = {chave: _corpo(chave) or valeria_content.texto_default(chave, r2)
              for chave in valeria_content.chaves_de_texto(r2)}
    return _Conteudo(
        # `aplicar` também funde o corpo dos cards (`card:<nó>:<card_id>`).
        nos=valeria_content.aplicar(r2.NOS, overrides),
        terminais=valeria_content.aplicar_terminais(r2.TERMINAIS, overrides),
        nudge=_corpo(r2.CHAVE_NUDGE),
        rotulo_lista=_corpo(r2.CHAVE_ROTULO_LISTA),
        historico=valeria_content.historico_de_rotulos(overrides),
        textos=textos,
    )


# ── Catálogo ────────────────────────────────────────────────────────────────
def _ler_catalogo() -> list[dict] | None:
    """Produtos ativos, ou None quando o catálogo está fora. Bloqueante.

    `is_active` é acrescentado (ver decisão 2 no cabeçalho): a query já filtrou.
    """
    try:
        linhas = _catalogo._fetch_active_products()
    except Exception as exc:
        logger.warning("%s catálogo indisponível — vitrine sem preço: %s", _LOG, exc)
        return None
    return [{"is_active": True, **p} for p in (linhas or []) if isinstance(p, dict)]


class _Catalogo:
    """O catálogo lido NO MÁXIMO uma vez por turno, e só se alguém precisar dele."""

    def __init__(self):
        self._lido = False
        self._linhas: list[dict] | None = None

    async def linhas(self) -> list[dict]:
        if not self._lido:
            self._linhas = await asyncio.to_thread(_ler_catalogo)
            self._lido = True
        return self._linhas or []

    async def precos(self, ramo: str | None) -> dict[str, str]:
        setor = SETOR_DO_RAMO.get(ramo or "")
        return valeria_tabela.precos_por_nome(await self.linhas(), setor) if setor else {}

    async def min_lots(self, ramo: str | None) -> dict[str, str]:
        setor = SETOR_DO_RAMO.get(ramo or "")
        return valeria_tabela.min_lots_por_nome(await self.linhas(), setor) if setor else {}

    async def cards(self, no) -> list[tuple]:
        """[(Card, texto resolvido)] dos cards do nó que podem sair agora."""
        cards = getattr(no, "cards", ()) or ()
        if not cards:
            return []
        ramo = r2.RAMO_DO_NO.get(no.id)
        precos, lots = await self.precos(ramo), await self.min_lots(ramo)
        saida = []
        for card in cards:
            texto = valeria_tabela.resolver_card(card, precos, lots)
            if texto:
                saida.append((card, texto))
        return saida


def _nome_do_card(card) -> str:
    """"Clássico", "Sua marca na embalagem Canastra"... — do corpo DEFAULT do registry.

    Default e não override: o nome vai para a nota e para o prompt, e não pode mudar
    porque alguém reescreveu a copy do card.
    """
    original = next((c for no in r2.NOS.values() for c in (no.cards or ())
                     if c.id == card.id and c.foto == card.foto), card)
    primeira = (original.corpo or "").split("\n", 1)[0]
    nome = primeira.split(" · ", 1)[0].strip()
    return nome[:40] or card.id


def _mensagem_2(ramo: str | None, precos: dict, textos: dict) -> str | None:
    """Tabela (atacado) ou "como funciona" (marca própria); None sem preço."""
    if not precos:
        return None
    if ramo == "atacado":
        return valeria_tabela.tabela_atacado(precos, textos.get(r2.CHAVE_REGRAS_ATACADO) or "")
    if ramo == "private_label":
        modelo = textos.get(r2.CHAVE_COMO_FUNCIONA_PL) or r2.COMO_FUNCIONA_PL_DEFAULT
        return valeria_tabela.como_funciona_pl(precos, modelo)
    return None


# ── Histórico da conversa ───────────────────────────────────────────────────
def _linhas_da_conversa(conversation_id: str | None) -> list[dict]:
    try:
        return get_history(conversation_id, limit=_LINHAS_HISTORICO,
                           roles=("user", "assistant")) or []
    except Exception as exc:
        logger.warning("%s histórico indisponível conv=%s: %s", _LOG, conversation_id, exc)
        return []


def _ultima_mensagem_do_bot(conversation_id: str | None) -> str:
    for linha in reversed(_linhas_da_conversa(conversation_id)):
        if linha.get("role") == "assistant" and linha.get("sent_by") == SENT_BY:
            return linha.get("content") or ""
    return ""


def _e_clique(linha: dict) -> bool:
    meta = linha.get("metadata")
    return linha.get("message_type") == "button" or (isinstance(meta, dict) and bool(meta.get("payload")))


def _textos_do_lead(conversation_id: str | None) -> list[str]:
    """O que o lead ESCREVEU nesta conversa (sem cliques e sem a mensagem pronta)."""
    textos = []
    for linha in _linhas_da_conversa(conversation_id):
        conteudo = (linha.get("content") or "").strip()
        if linha.get("role") != "user" or not conteudo or _e_clique(linha):
            continue
        if motor.primeira_tela(conteudo) != r2.NO_ENTRADA:
            continue
        textos.append(conteudo[:_MAX_CHARS_TEXTO_NOTA])
    return textos[-_MAX_TEXTOS_NOTA:]


# ── Nota de repasse (spec §5.3) ─────────────────────────────────────────────
def _rotulo_do_botao(nos: dict, no_id: str, botao_id) -> str | None:
    no = nos.get(no_id)
    if no is None or not isinstance(botao_id, str):
        return None
    return next((b.rotulo for b in no.botoes if b.id == botao_id), botao_id)


def _texto_ja_na_origem(texto: str, motivo: str | None) -> bool:
    """True quando a "Origem do repasse" já cita este texto (PERGUNTA/VENDEDOR/escreveu)."""
    return bool(motivo) and (motivo.endswith(f": {texto}") or f'"{texto}"' in motivo)


def montar_nota(estado: dict, nos: dict, *, textos: list[str], motivo: str | None,
                ramo: str | None = None) -> str:
    """Resumo do atendimento para o vendedor. Pura.

    `ramo` é o do turno (estado + nó em que o lead ESTAVA): o nó gravado depois do
    turno é o terminal, que não diz ramo — sem isto a exportação, que não grava
    `flow_state.ramo`, saía como "ramo não escolhido".
    """
    estado = estado if isinstance(estado, dict) else {}
    ramo = ramo or _ramo(estado, estado.get("node"))
    cabecalho = f"[ValerIA botões v2] {ROTULO_DO_RAMO.get(ramo or '', 'ramo não escolhido')}"
    interesse = estado.get("interesse")
    if isinstance(interesse, str) and interesse:
        vitrine = nos.get(r2.VITRINE_DO_RAMO.get(ramo or "", ""))
        card = next((c for c in getattr(vitrine, "cards", ()) or () if c.id == interesse), None)
        cabecalho += f" · interesse: {_nome_do_card(card) if card else interesse}"
    linhas = [cabecalho]

    respostas = estado.get("respostas") if isinstance(estado.get("respostas"), dict) else {}
    qualificacao = []
    for no_id, rotulo, sufixo in _QUALIFICACAO:
        valor = _rotulo_do_botao(nos, no_id, respostas.get(no_id))
        if valor:
            qualificacao.append(f"{rotulo}: {valor}{sufixo}")
    if qualificacao:
        linhas.append(" · ".join(qualificacao))

    jornada = []
    viu = estado.get("viu")
    if isinstance(viu, list) and viu:
        # A mensagem 2 da marca própria não é tabela: é o "como funciona" (§6.2).
        nomes_viu = {"tabela": "como funciona"} if ramo == "private_label" else {}
        jornada.append("Viu: " + " + ".join(nomes_viu.get(str(v), str(v)) for v in viu))
    faqs = estado.get("faqs")
    if isinstance(faqs, list) and faqs:
        duvidas = nos.get(r2.DUVIDAS_DO_RAMO.get(ramo or "", ""))
        nomes = []
        for faq_id in faqs:
            rotulo = _rotulo_do_botao(nos, duvidas.id, f"faq_{faq_id}") if duvidas else None
            nome = (rotulo or str(faq_id)).lower()
            if nome not in nomes:
                nomes.append(nome)
        jornada.append("Perguntou: " + ", ".join(nomes))
    if jornada:
        linhas.append(" · ".join(jornada))

    textos = [t for t in textos if not _texto_ja_na_origem(t, motivo)]
    if textos:
        linhas.append("Mensagens escritas pelo lead: " + " / ".join(f'"{t}"' for t in textos))
    linhas.append(f"Origem do repasse: {motivo or '—'}")
    return "\n".join(linhas)


async def _anotar_repasse(lead: dict, conversation: dict, estado: dict, nos: dict,
                          motivo: str | None, *, ramo: str | None) -> None:
    """Observação no lead + mensagem de sistema na conversa (`effects.anotar`). Fail-soft."""
    try:
        textos = await asyncio.to_thread(_textos_do_lead, conversation.get("id"))
        nota = montar_nota(estado, nos, textos=textos, motivo=motivo, ramo=ramo)
        await asyncio.to_thread(effects.anotar, lead.get("id"), conversation.get("id"), nota)
    except Exception as exc:
        logger.warning("%s nota de repasse não gravada conv=%s: %s", _LOG,
                       conversation.get("id"), exc)


# ── Envio ───────────────────────────────────────────────────────────────────
class _Saida:
    """Envio + persistência das mensagens da v2 que não são a tela do nó da v1."""

    def __init__(self, *, provider, lead: dict, conversation: dict, channel,
                 conteudo: _Conteudo, catalogo: _Catalogo):
        self.provider = provider
        self.lead = lead
        self.conversation = conversation
        self.channel = channel
        self.conteudo = conteudo
        self.catalogo = catalogo
        self.destino = v1.resolve_send_target(lead, lead.get("phone"))
        self.viu: list[str] = []

    async def _registrar(self, texto: str, resultado, *, message_type: str | None = None,
                         media_url: str | None = None, metadata: dict | None = None) -> None:
        """`metadata` leva a tela interativa (`metadata.interativo`) para a bolha do CRM."""
        if resultado is None:
            return
        try:
            await asyncio.to_thread(
                save_message, self.conversation.get("id"), self.lead.get("id"), "assistant",
                texto, self.conversation.get("stage"), sent_by=SENT_BY,
                media_url=media_url, message_type=message_type,
                wamid=extract_wamid(resultado), metadata=metadata,
            )
        except Exception as exc:
            logger.warning("%s mensagem enviada mas não persistida conv=%s: %s", _LOG,
                           self.conversation.get("id"), exc)

    async def texto(self, texto: str) -> bool:
        try:
            resultado = await self.provider.send_text(self.destino, texto)
        except Exception as exc:
            logger.error("%s falha ao enviar texto conv=%s: %s", _LOG,
                         self.conversation.get("id"), exc, exc_info=True)
            return False
        await self._registrar(texto, resultado)
        return True

    async def botoes(self, corpo: str, botoes, *, image_url: str | None = None) -> bool:
        try:
            resultado = await self.provider.send_interactive_buttons(
                self.destino, corpo, v1._pares(botoes), image_url=image_url)
        except Exception as exc:
            logger.error("%s falha ao enviar botões conv=%s: %s", _LOG,
                         self.conversation.get("id"), exc, exc_info=True)
            return False
        await self._registrar(
            corpo, resultado, media_url=image_url,
            message_type="image" if image_url else None,
            metadata=interativo.metadata(lambda: interativo.botoes(
                [b.titulo for b in botoes], imagem=image_url)))
        return True

    async def faq(self, ramo: str | None, faq_id: str) -> None:
        """Resposta fixa da lista de dúvidas: override `faq:<ramo>:<id>` ou default."""
        texto = (self.conteudo.textos.get(f"faq:{ramo}:{faq_id}")
                 or (r2.FAQ.get(ramo or "") or {}).get(faq_id))
        if not texto:
            logger.warning("%s FAQ %r sem texto no ramo %r — nada enviado", _LOG, faq_id, ramo)
            return
        if _MARCADOR_PRECO.search(texto):
            precos = await self.catalogo.precos(ramo)
            texto = _MARCADOR_PRECO.sub(lambda m: precos.get(m.group(1)) or SOB_CONSULTA, texto)
        # Qualquer outro `{x}` (texto editado na tela) leva a linha embora, como na v1.
        texto = v1._resolver(texto, {})
        if not texto:
            logger.warning("%s FAQ %r vazia depois de resolver — nada enviado", _LOG, faq_id)
            return
        await self.texto(texto)

    async def montar_mensagem_2(self, ramo: str | None, onde: str) -> str | None:
        """Mensagem 2 do ramo, já resolvida. None = setor SEM PREÇO NENHUM (repasse).

        "" = há preço mas a mensagem 2 não sai (SKU base faltando, nenhuma linha de
        tabela): quem chama pula a mensagem 2 e segue com o resto.
        """
        precos = await self.catalogo.precos(ramo)
        if not precos:
            return None
        texto = v1._resolver(_mensagem_2(ramo, precos, self.conteudo.textos) or "", {})
        if not texto:
            logger.warning("%s %s com preço mas sem mensagem 2 — segue sem ela", _LOG, onde)
        return texto

    async def enviar_mensagem_2(self, texto: str | None) -> None:
        # `viu` guarda "tabela" nos dois ramos; a nota escreve "como funciona" no PL.
        if texto and await self.texto(texto):
            self.viu.append("tabela")

    async def vitrine(self, decisao: DecisaoV2) -> bool:
        """Mensagens 1-3 da vitrine conforme `decisao.vitrine`. False = sem tabela.

        False só acontece quando o setor do ramo não tem PREÇO NENHUM (catálogo vazio
        ou fora), e ANTES de qualquer envio: o chamador troca o turno pelo repasse
        (spec §6.3). Com preço mas sem mensagem 2 (um SKU base faltando, nenhuma linha
        de tabela), a mensagem 2 é pulada e o resto da vitrine sai — um SKU ausente não
        pode derrubar todas as vitrines do ramo.

        Carrossel recusado pela Meta: os botões com a foto saem DEPOIS da mensagem 2,
        no lugar da 3ª — os botões ficam por último, onde o lead os vê.
        """
        no = self.conteudo.nos[decisao.proximo_no]
        ramo = r2.RAMO_DO_NO.get(no.id)
        modo = decisao.vitrine if decisao.vitrine in ("completa", "tabela") else "acoes"
        mensagem = decisao.mensagem or Mensagem(corpo=r2.CORPO_ACOES, botoes=no.botoes)
        botoes = mensagem.botoes or no.botoes

        mensagem_2 = None
        if modo != "acoes":
            mensagem_2 = await self.montar_mensagem_2(ramo, no.id)
            if mensagem_2 is None:
                return False

        foto_do_fallback = None
        if modo == "completa":
            foto_do_fallback = await self._carrossel(no, mensagem)
        await self.enviar_mensagem_2(mensagem_2)
        if foto_do_fallback and await self.botoes(v1._resolver(mensagem.corpo, {}), botoes,
                                                  image_url=foto_do_fallback):
            self.viu.append("vitrine")
            return True
        # Decisão 1 do cabeçalho: em "completa" a `mensagem` é a do carrossel.
        corpo = r2.CORPO_ACOES if modo == "completa" else mensagem.corpo
        await self.botoes(v1._resolver(corpo, {}) or r2.CORPO_ACOES, botoes)
        return True

    async def _carrossel(self, no, mensagem: Mensagem) -> str | None:
        """Mensagem 1. Devolve a foto do 1º card quando a Meta RECUSOU o carrossel.

        Com a foto em mãos, `vitrine` manda os botões de ação com ela no header depois
        da mensagem 2 (spec §6.3).
        """
        corpo = v1._resolver(mensagem.corpo, {})
        cards = await self.catalogo.cards(no)
        if not cards:
            logger.warning("%s nenhum card de %s pode sair — vitrine sem carrossel", _LOG, no.id)
            return None
        if len(cards) >= 2:
            urls = [await asyncio.to_thread(v1.url_publica_da_foto, card.foto)
                    for card, _ in cards]
            if all(urls):
                payload = [{"image_url": url, "body": texto,
                            "buttons": [(f"{_PREFIXO_CARD}{card.id}", card.rotulo_botao)]}
                           for (card, texto), url in zip(cards, urls)]
                try:
                    resultado = await self.provider.send_interactive_carousel(
                        self.destino, corpo, payload)
                except Exception as exc:
                    logger.error("%s carrossel recusado conv=%s — botões com foto: %s", _LOG,
                                 self.conversation.get("id"), exc, exc_info=True)
                    return urls[0]
                # SEM `message_type`: o CRM (frontend lib/message-preview.ts) só lê o
                # `content` de None/"text"/"button"; "interactive" virava "📎 Mídia" e o
                # vendedor não via o que o lead recebeu.
                # `metadata.interativo` leva os cards (foto, texto e botão como saíram)
                # para a bolha do CRM desenhar o carrossel; o `content` segue texto.
                await self._registrar(
                    "\n\n".join([corpo, *(texto for _, texto in cards)]), resultado,
                    metadata=interativo.metadata(lambda: interativo.carrossel(
                        (c["image_url"], c["body"], [titulo for _, titulo in c["buttons"]])
                        for c in payload)))
                self.viu.append("vitrine")
                return None
            logger.warning("%s foto de card não publicada em %s — cards como texto", _LOG, no.id)
        else:
            logger.warning("%s só %d card enviável em %s — cards como texto", _LOG,
                           len(cards), no.id)
        if await self.texto("\n\n".join(texto for _, texto in cards)):
            self.viu.append("vitrine")
        return None


def _decisao_de_terminal(destino: str, nos: dict, terminais: dict, **extra) -> DecisaoV2:
    """A `Decisao` declarada de `destino` (mesma do motor), como `DecisaoV2`."""
    base = motor_v1._ir_para(destino, nos, terminais)
    return DecisaoV2(**{f.name: getattr(base, f.name) for f in fields(base)}, **extra)


# ── Ponto de entrada ────────────────────────────────────────────────────────
async def processar_inbound(
    *, lead: dict, conversation: dict, channel: dict | None = None, provider=None,
    texto: str = "", message_type: str | None = None, metadata: dict | None = None,
    wamid: str | None = None,
) -> str | None:
    """Roda um turno da v2. Nunca levanta.

    Mesmo contrato da v1 (`valeria_runner.processar_inbound`): devolve o MOTIVO de não
    ter rodado (o gate do processor decide a ponte pós-handoff por ele) ou None quando
    não há mais nada a fazer com este inbound.
    """
    try:
        return await _executar_turno(
            lead=lead, conversation=conversation, channel=channel, provider=provider,
            texto=texto, message_type=message_type, metadata=metadata, wamid=wamid,
        )
    except Exception as exc:
        logger.error("%s turno falhou conv=%s lead=%s wamid=%s: %s", _LOG,
                     (conversation or {}).get("id"), (lead or {}).get("id"), wamid, exc,
                     exc_info=True)
        return None


async def _classificar(evento, *, no: str | None, estado, conteudo: _Conteudo,
                       catalogo: _Catalogo, lead: dict, conversation: dict,
                       pediu_saida: bool):
    """O evento que vai ao motor: clique fica clique; texto vira `TextoClassificado`.

    Sem LLM: primeiro contato (o motor roteia pela mensagem pronta), fluxo encerrado
    (o motor ignora) e nó desconhecido (o motor repassa). O pedido de saída
    determinístico (`pediu_para_sair_v2`) vale em TODOS esses casos — inclusive no
    primeiro contato, onde a v1 só honrava a lista exata.
    """
    if not isinstance(evento, Texto):
        return evento
    if pediu_saida:
        return TextoClassificado(evento.conteudo, "SAIR")
    if no is None:
        return evento
    botoes = motor_v1._botoes_declarados(no, conteudo.nos, conteudo.terminais)
    if botoes is None or motor_v1._encerrado(no, conteudo.nos, conteudo.terminais):
        return evento

    if motor.primeira_tela(evento.conteudo) in motor.VITRINES:
        # Mensagem pronta do anúncio no meio do fluxo: o motor reabre a vitrine
        # pelo texto (regra 5b), sem etiqueta — não gasta LLM.
        return evento

    ramo = _ramo(estado, no)
    pares = v1._pares(botoes)
    if no in motor.VITRINES:
        for card, _ in await catalogo.cards(conteudo.nos.get(no)):
            pares.append((f"{_PREFIXO_CARD}{card.id}",
                          f"{card.rotulo_botao} — {_nome_do_card(card)}"))
    validas = set(r2.FAQ.get(ramo or "", {})) | {"preco"}
    faqs = {k: v for k, v in r2.FAQ_DESCRICAO.items() if k in validas}
    ultima = await asyncio.to_thread(_ultima_mensagem_do_bot, conversation.get("id"))
    try:
        c = await valeria_classifier.classificar(
            evento.conteudo, no_id=no, ramo=ramo, botoes=pares, faqs=faqs,
            ultima_mensagem=ultima, lead_id=lead.get("id"))
    except Exception as exc:   # o contrato diz que não levanta; o turno não confia
        logger.warning("%s classificador levantou — RUIDO: %s", _LOG, exc)
        c = valeria_classifier.RUIDO
    return TextoClassificado(evento.conteudo, c.classe, c.botao_id, c.faq_id)


def _rotulo_do_turno(evento) -> str:
    """Evidência do critério de score: o rótulo tocado ou o texto escrito."""
    if isinstance(evento, Clique):
        return v1._rotulo_clicado(evento)
    if isinstance(evento, TextoClassificado):
        return (evento.conteudo or "").strip()[:_MAX_CHARS_TEXTO_NOTA]
    return ""


async def _executar_turno(
    *, lead: dict, conversation: dict, channel, provider, texto: str,
    message_type: str | None, metadata: dict | None, wamid: str | None,
) -> str | None:
    conversation_id = conversation.get("id")
    lead_id = lead.get("id")

    if not config.enabled(r2.FLOW_ID):
        logger.info("%s kill switch OFF — nada a fazer conv=%s", _LOG, conversation_id)
        return None

    estado = await asyncio.to_thread(v1._reler_estado, conversation)
    deal = await asyncio.to_thread(v1.get_open_deal, lead_id)
    motivo = v1._motivo_para_nao_rodar(lead, estado, deal)
    if motivo:
        await _notificar_sem_rodar(lead, conversation, estado, motivo)
        return motivo

    evento = v1._montar_evento(texto, message_type, metadata)
    # Lista exata do motor OU gramática determinística do classificador: os dois sem
    # LLM — a frase exata não pode gastar uma chamada que o motor já resolve sozinho.
    pediu_saida = isinstance(evento, Texto) and (
        normalizar(evento.conteudo) in motor_v1.FRASES_OPTOUT
        or valeria_classifier.pediu_para_sair_v2(evento.conteudo))
    # Lead que a v1 encerrou em silêncio: o turno não acontece (como `ignorar`). Só o
    # pedido de saída passa — o opt-out vence o encerramento, na v1 e aqui.
    if not pediu_saida and encerrado_na_v1(estado):
        logger.info("%s lead encerrado na v1 (%s) — v2 não recomeça conv=%s", _LOG,
                    estado.get("node"), conversation_id)
        return None

    # O pedido de saída vence o detector do robô do lead (a v1 faz o mesmo com a
    # lista exata, dentro de `_e_robo_do_lead`).
    if not pediu_saida and await v1._e_robo_do_lead(lead, conversation_id, evento):
        return None

    conteudo = await asyncio.to_thread(_carregar_conteudo)
    catalogo = _Catalogo()
    no = no_atual_v2(estado)
    evento_motor = await _classificar(
        evento, no=no, estado=estado, conteudo=conteudo, catalogo=catalogo,
        lead=lead, conversation=conversation, pediu_saida=pediu_saida)

    decisao = motor.decidir(no, evento_motor, v1._com_historico(estado, conteudo.historico),
                            conteudo.nos, conteudo.terminais, corpo_nudge=conteudo.nudge)
    if decisao.ignorar:
        logger.info("%s evento ignorado (nó=%s) conv=%s wamid=%s", _LOG,
                    decisao.proximo_no, conversation_id, wamid)
        return None

    if not await _aplicar_efeitos(decisao, lead=lead, conversation_id=conversation_id,
                                  evidencia=v1._evidencia_do_turno(evento, texto, wamid)):
        return None

    saida = _Saida(provider=provider, lead=lead, conversation=conversation,
                   channel=channel, conteudo=conteudo, catalogo=catalogo)
    efetiva = await _enviar(decisao, saida, estado=estado, no=no)
    await v1.aplicar_criterios(lead_id, decisao.criterios, rotulo=_rotulo_do_turno(evento_motor))

    campos = proximo_estado_v2(estado, efetiva, viu=saida.viu)
    if deal and deal.get("stage_id"):
        campos["deal_stage_id"] = deal["stage_id"]
    if efetiva.efeitos.handoff:
        await _anotar_repasse(lead, conversation, campos, conteudo.nos,
                              efetiva.repasse_motivo, ramo=_ramo(campos, no))
    await v1._persistir_estado(conversation, estado, campos)
    logger.info("%s turno aplicado conv=%s nó=%s vitrine=%s faq=%s", _LOG, conversation_id,
                efetiva.proximo_no, efetiva.vitrine, efetiva.faq)
    return None


async def _aplicar_efeitos(decisao: DecisaoV2, *, lead: dict, conversation_id,
                           evidencia: dict) -> bool:
    avancar = await asyncio.to_thread(
        effects.aplicar, decisao.efeitos, lead=lead, conversation_id=conversation_id,
        evidencia=evidencia, fluxo=effects.FLUXO_VALERIA,
        # A nota da v2 (`montar_nota`) substitui o "Nenhuma qualificação" da v1.
        nota_sem_qualificacao=False,
    )
    if not avancar:
        # Só o opt-out devolve False (ver v1): sem `opt_out=true` gravado, nada sai.
        logger.error("%s efeitos bloquearam o turno (opt-out não gravado) conv=%s lead=%s",
                     _LOG, conversation_id, lead.get("id"))
    return bool(avancar)


async def _enviar(decisao: DecisaoV2, saida: _Saida, *, estado, no: str | None) -> DecisaoV2:
    """FAQ, vitrine ou a tela do nó/terminal. Devolve a decisão EFETIVA do turno.

    A efetiva só difere da do motor quando a vitrine (ou o `tabela_antes`) não tem
    preço nenhum: o turno vira o repasse do ramo (spec §6.3).
    """
    if decisao.faq:
        ramo = decisao.memoria.get("ramo") or _ramo(estado, no)
        await saida.faq(ramo, decisao.faq)

    if getattr(decisao, "tabela_antes", False):
        # Preço no meio da qualificação: mensagem 2 do ramo e a MESMA tela de novo,
        # sem carrossel nem botões de ação (o nó não muda).
        ramo = _ramo(estado, no) or r2.RAMO_DO_NO.get(decisao.proximo_no)
        mensagem_2 = await saida.montar_mensagem_2(ramo, decisao.proximo_no)
        if mensagem_2 is None:
            return await _repassar_sem_tabela(decisao, saida, ramo=ramo)
        await saida.enviar_mensagem_2(mensagem_2)

    if decisao.proximo_no in motor.VITRINES and decisao.proximo_no in saida.conteudo.nos:
        if await saida.vitrine(decisao):
            return decisao
        return await _repassar_sem_tabela(decisao, saida)

    await v1._enviar(decisao, lead=saida.lead, conversation=saida.conversation,
                     channel=saida.channel, provider=saida.provider,
                     nos=saida.conteudo.nos, terminais=saida.conteudo.terminais,
                     rotulo_lista=saida.conteudo.rotulo_lista)
    return decisao


async def _repassar_sem_tabela(decisao: DecisaoV2, saida: _Saida, *,
                               ramo: str | None = None) -> DecisaoV2:
    """Sem preço nenhum: UMA mensagem (o aviso já diz que o João foi chamado), o handoff
    do ramo e o cartão do vendedor — sem o corpo do terminal, que repetiria o aviso."""
    ramo = ramo or r2.RAMO_DO_NO.get(decisao.proximo_no)
    destino = r2.HANDOFF_DO_RAMO.get(ramo or "", motor.ID_HUMANO)
    logger.error("%s sem tabela para %s — repasse para %s conv=%s", _LOG,
                 decisao.proximo_no, destino, saida.conversation.get("id"))
    nova = _decisao_de_terminal(destino, saida.conteudo.nos, saida.conteudo.terminais,
                                memoria=dict(decisao.memoria), repasse_motivo=MOTIVO_SEM_TABELA)
    await _aplicar_efeitos(nova, lead=saida.lead, conversation_id=saida.conversation.get("id"),
                           evidencia={"origem": "sem_tabela"})
    if await saida.texto(MSG_TABELA_INDISPONIVEL):
        await v1._enviar_cartao(saida.provider, saida.destino,
                                saida.conteudo.terminais.get(destino), saida.channel,
                                conversation=saida.conversation, lead=saida.lead)
    return nova


async def _notificar_sem_rodar(lead: dict, conversation: dict, estado, motivo: str) -> None:
    """O `_notificar_sem_rodar` da v1, carimbando a v2 (ver cabeçalho)."""
    conversation_id = conversation.get("id")
    logger.info("%s não roda conv=%s: %s", _LOG, conversation_id, motivo)
    if isinstance(estado, dict) and estado.get("notificado_humano"):
        return
    await asyncio.to_thread(
        effects.anotar, lead.get("id"), conversation_id,
        f"🤖 [VALERIA BOTÕES v2] Bot saiu de cena nesta conversa: {motivo}.",
    )
    campos = dict(estado) if isinstance(estado, dict) else {}
    campos["notificado_humano"] = True
    if not campos.get("flow"):
        campos.update(estado_inicial_v2())
    await v1._persistir_estado(conversation, estado, campos)


# ── Repasse automático de parados (spec §8; chamado pelo T9) ────────────────
def _travar_repasse(conversation_id, estado: dict, node: str, quando: str) -> bool:
    """UPDATE condicional: só grava se o nó é o lido e `repasse_auto` ainda é nulo.

    PostgREST aceita o caminho jsonb (`flow_state->>node`) como filtro de PATCH, então
    a condição é avaliada no MESMO UPDATE do Postgres: duas réplicas que tentem o mesmo
    lead serializam na linha, e só a primeira devolve a linha alterada.

    CORRIDA RESIDUAL: o `flow_state` gravado aqui é o LIDO pelo varredor + a trava. Um
    turno do lead que mudou outra chave sem mudar o nó (ex.: `ruidos` num nudge) entre
    a leitura e este UPDATE é sobrescrito. E um turno do lead que roda DEPOIS da trava
    e antes da gravação final (`_persistir_estado` em `repassar_parado`) pode ter o nó
    sobrescrito pelo terminal — o lead fica repassado do mesmo jeito, que é o desfecho
    seguro (o varredor não segura o `lead_run_lock` do processor).
    """
    novo = dict(estado)
    novo["repasse_auto"] = quando
    resultado = (
        get_supabase().table("conversations")
        .update({"flow_state": novo})
        .eq("id", conversation_id)
        .eq("flow_state->>node", node)
        .is_("flow_state->>repasse_auto", "null")
        .execute()
    )
    return bool(getattr(resultado, "data", None))


async def repassar_parado(*, lead: dict, conversation: dict, channel: dict, provider,
                          horas: float) -> bool:
    """Repasse automático (spec §8): aplica o handoff do ramo como se o lead tivesse pedido.

    Devolve True só se ESTE chamador ganhou a trava (`flow_state.repasse_auto`). Nunca
    levanta. Depois da trava ganha, cada passo é fail-soft: o lead já é deste
    chamador, e devolver False faria o varredor não contar um repasse que aconteceu.
    """
    conversation_id = (conversation or {}).get("id")
    try:
        estado = (conversation or {}).get("flow_state")
        node = no_atual_v2(estado)
        if node not in r2.NOS_COM_INTENCAO:
            logger.info("%s repasse automático fora de nó de intenção (%s) conv=%s",
                        _LOG, node, conversation_id)
            return False
        # As MESMAS guardas de um turno: kill switch, human_control, card movido pelo
        # vendedor e blacklist (`_motivo_para_nao_rodar`), mais o opt-out.
        if not config.enabled(r2.FLOW_ID):
            return False
        # A conversa ainda é da v2? (perfil do canal trocado, fluxo desligado...)
        fluxo = await asyncio.to_thread(_irmao.fluxo_efetivo, conversation, channel)
        if fluxo != r2.FLOW_ID:
            logger.info("%s repasse automático: conversa não é mais da v2 (%s) conv=%s",
                        _LOG, fluxo, conversation_id)
            return False
        if lead.get("opt_out") is True:
            return False
        deal = await asyncio.to_thread(v1.get_open_deal, lead.get("id"))
        motivo = await asyncio.to_thread(v1._motivo_para_nao_rodar, lead, estado, deal)
        if motivo:
            logger.info("%s repasse automático não roda conv=%s: %s", _LOG,
                        conversation_id, motivo)
            return False
        ramo = _ramo(estado, node)
        destino = r2.HANDOFF_DO_RAMO.get(ramo or "")
        if destino is None:
            logger.warning("%s repasse automático sem ramo com vendedor (%r) conv=%s",
                           _LOG, ramo, conversation_id)
            return False
        quando = datetime.now(timezone.utc).isoformat()
        if not await asyncio.to_thread(_travar_repasse, conversation_id, estado, node, quando):
            logger.info("%s trava de repasse perdida conv=%s nó=%s", _LOG, conversation_id, node)
            return False
    except Exception as exc:
        logger.error("%s repasse automático não travado conv=%s: %s", _LOG,
                     conversation_id, exc, exc_info=True)
        return False

    estado_travado = {**estado, "repasse_auto": quando}
    try:
        conteudo = await asyncio.to_thread(_carregar_conteudo)
        decisao = _decisao_de_terminal(
            destino, conteudo.nos, conteudo.terminais,
            repasse_motivo=f"automático — parado há {horas:.0f}h em {node}")
        await _aplicar_efeitos(decisao, lead=lead, conversation_id=conversation_id,
                               evidencia={"origem": "repasse_auto"})
        saida = _Saida(provider=provider, lead=lead, conversation=conversation,
                       channel=channel, conteudo=conteudo, catalogo=_Catalogo())
        if await saida.texto(MSG_REPASSE_AUTO):
            await v1._enviar_cartao(provider, saida.destino, conteudo.terminais.get(destino),
                                    channel, conversation=conversation, lead=lead)
        campos = proximo_estado_v2(estado_travado, decisao)
        await _anotar_repasse(lead, conversation, campos, conteudo.nos,
                              decisao.repasse_motivo, ramo=ramo)
        await v1._persistir_estado(conversation, estado_travado, campos)
        logger.info("%s repasse automático conv=%s %s -> %s", _LOG, conversation_id,
                    node, destino)
    except Exception as exc:
        logger.error("%s repasse automático incompleto conv=%s: %s", _LOG,
                     conversation_id, exc, exc_info=True)
    return True
