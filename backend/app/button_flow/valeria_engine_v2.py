"""Motor do fluxo de botões v2 da ValerIA (vitrine primeiro). Núcleo puro: sem banco,
sem rede, sem relógio.

Mesmo desenho do `valeria_engine.py` (v1): intérprete do registry
(`valeria_registry_v2.py`), não matriz de `if`. O que a v2 acrescenta é:
  • a vitrine (`DecisaoV2.vitrine`): o runner sabe montar carrossel, tabela e
    botões de ação; o motor só diz QUAL parte sai;
  • os destinos especiais declarados no registry ("faq:<id>", "tabela",
    "handoff", "regra:QP2");
  • o texto livre já etiquetado pelo classificador (`TextoClassificado`), que
    escolhe uma resposta FIXA — nenhuma palavra gerada chega ao lead;
  • a memória da conversa (`DecisaoV2.memoria`): chaves que o runner MESCLA no
    `flow_state` (ramo, interesse, respostas, retorno, ruidos).

Reusa da v1 por import, sem copiar: `_casar`, `_encerrado`, `_botoes_declarados`,
`_ir_para`, `FRASES_OPTOUT` e `Decisao`. A v1 não muda.

As regras numeradas abaixo são as do Task 5 do plano
(docs/superpowers/plans/2026-10-08-valeria-botoes-v2-vitrine.md), na mesma ordem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields

from app.button_flow import valeria_engine as v1
from app.button_flow import valeria_registry as reg1
from app.button_flow import valeria_registry_v2 as r
from app.button_flow.engine import Clique, Mensagem, Texto, normalizar

__all__ = ["DecisaoV2", "TextoClassificado", "decidir", "primeira_tela"]


@dataclass(frozen=True)
class TextoClassificado:
    """Texto livre já etiquetado por `valeria_classifier.classificar` (contrato C4)."""
    conteudo: str
    classe: str                 # "BOTAO"|"FAQ"|"PERGUNTA"|"VENDEDOR"|"SAIR"|"RUIDO"
    botao_id: str | None = None
    faq_id: str | None = None   # inclui "preco"


@dataclass(frozen=True)
class DecisaoV2(v1.Decisao):
    """`Decisao` da v1 + o que só a v2 tem (contrato C3)."""
    # Chaves a MESCLAR no flow_state: ramo, interesse, respostas{no: botao_id},
    # retorno, ruidos. Só o que mudou neste turno.
    memoria: dict = field(default_factory=dict)
    # faq_id cuja resposta fixa sai ANTES da tela.
    faq: str | None = None
    # "completa" (carrossel+texto+ações) | "tabela" (texto+ações) | "acoes" (só
    # ações) | "nenhuma". Diferente de "nenhuma" só com proximo_no em VA/VP.
    vitrine: str = "nenhuma"
    # Texto da "Origem do repasse" na nota ao vendedor (spec §5.3).
    repasse_motivo: str | None = None


ID_HUMANO = v1.ID_HUMANO
ID_OPTOUT = v1.ID_OPTOUT
VITRINES = frozenset(r.VITRINE_DO_RAMO.values())
MOTIVO_RUIDO = "sem resposta a botões (2 mensagens não entendidas)"
_PREFIXO_CARD = "card:"
_LIMITE_TEXTO_MOTIVO = 200


# ─── 1. Mensagem pronta do anúncio (spec §5.1) ──────────────────────────────
#
# A spec diz "sem acento e sem pontuação"; `engine.normalizar` só tira acento e
# caixa. Esta chave tira também pontuação e espaço repetido, nas DUAS pontas — o
# índice é derivado das chaves do registry no import, sem mexer nele. Assim o
# lead que apaga o "." ou o "!" do anúncio continua indo para a vitrine.
_NAO_PALAVRA = re.compile(r"[^\w\s]+")


def _chave_pronta(texto: str | None) -> str:
    return " ".join(_NAO_PALAVRA.sub(" ", normalizar(texto)).split())


_PRONTAS: dict[str, str] = {_chave_pronta(k): v for k, v in r.MENSAGENS_PRONTAS.items()}


def primeira_tela(texto: str) -> str:
    """"VA" | "VP" para a mensagem pronta do anúncio; "N0" para qualquer outra."""
    return _PRONTAS.get(_chave_pronta(texto), r.NO_ENTRADA)


# ─── decidir ────────────────────────────────────────────────────────────────

def decidir(
    no_atual: str | None,
    evento: object,
    estado: dict | None,
    nos: dict[str, reg1.No],
    terminais: dict[str, reg1.Terminal],
    *,
    corpo_nudge: str | None = None,
) -> DecisaoV2:
    """Próximo passo do fluxo v2. Pura: mesma entrada, mesma saída, sempre.

    `nos`/`terminais` são as cópias com override de tela aplicado (como na v1);
    `corpo_nudge` é o override da chave reservada `CHAVE_NUDGE`.
    """
    est = estado if isinstance(estado, dict) else {}
    ctx = _Ctx(no_atual or "", est, nos, terminais, corpo_nudge)

    # 2. Primeiro contato.
    if no_atual is None:
        conteudo = _conteudo(evento)
        if conteudo is not None and _e_optout(evento):
            return ctx.ir_para(ID_OPTOUT)
        destino = primeira_tela(conteudo) if conteudo is not None else r.NO_ENTRADA
        if destino in VITRINES:
            return ctx.ir_para(destino, vitrine="completa",
                               memoria={"ramo": r.RAMO_DO_NO[destino]})
        return ctx.ir_para(destino)

    # 3. Nó desconhecido: flow_state corrompido nunca estoura.
    botoes = v1._botoes_declarados(no_atual, nos, terminais)
    if botoes is None:
        return ctx.ir_para(ID_HUMANO)

    # 4. Opt-out vence tudo — inclusive o encerramento — menos quem já está nele.
    if no_atual != ID_OPTOUT and _e_optout(evento):
        return ctx.ir_para(ID_OPTOUT)

    # 5. Fluxo encerrado: nenhum turno acontece.
    if v1._encerrado(no_atual, nos, terminais):
        return DecisaoV2(proximo_no=no_atual, ignorar=True)

    # 6. Clique.
    if isinstance(evento, Clique):
        return ctx.clique(evento, botoes)

    # 7. Texto classificado.
    if isinstance(evento, TextoClassificado):
        return ctx.classificado(evento, botoes)

    # 8. Texto puro (classificador não rodou) = RUIDO. No VO o texto é a pergunta.
    conteudo = _conteudo(evento) or ""
    if no_atual == "VO":
        return ctx.handoff(f"PERGUNTA: {conteudo[:_LIMITE_TEXTO_MOTIVO]}")
    return ctx.ruido(botoes)


def _conteudo(evento: object) -> str | None:
    if isinstance(evento, (Texto, TextoClassificado)):
        return evento.conteudo or ""
    return None


def _e_optout(evento: object) -> bool:
    """Pedido de saída: igualdade com a lista fixa, ou a etiqueta SAIR.

    SÓ igualdade normalizada, como na v1. A gramática ampla de parada mora no
    classificador (que roda antes do motor e devolve SAIR): aqui ela daria
    opt-out irreversível a frases de venda da v2 como "não quero receber o kit".
    """
    if isinstance(evento, TextoClassificado) and evento.classe == "SAIR":
        return True
    conteudo = _conteudo(evento)
    return conteudo is not None and normalizar(conteudo) in v1.FRASES_OPTOUT


def _int(valor: object) -> int:
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else 0


@dataclass(frozen=True)
class _Ctx:
    """O turno: posição, estado lido e registry com overrides."""
    no_atual: str
    est: dict
    nos: dict
    terminais: dict
    corpo_nudge: str | None

    # ── leitura do estado ──────────────────────────────────────────────────
    @property
    def ramo(self) -> str | None:
        """Ramo da conversa: `flow_state.ramo` primeiro; senão o do nó.

        VK e VO são compartilhados e declaram `ramo="entrada"` ("não fixa
        ramo"): para eles só vale o estado.
        """
        ramo = self.est.get("ramo")
        if isinstance(ramo, str) and ramo:
            return ramo
        ramo = r.RAMO_DO_NO.get(self.no_atual)
        return ramo if ramo and ramo != "entrada" else None

    @property
    def ruidos(self) -> int:
        return _int(self.est.get("ruidos"))

    @property
    def respostas(self) -> dict:
        resp = self.est.get("respostas")
        return dict(resp) if isinstance(resp, dict) else {}

    # ── saídas ─────────────────────────────────────────────────────────────
    def ir_para(self, destino: str, *, criterios=(), dias=None, **extra) -> DecisaoV2:
        """O `_ir_para` da v1 (mesma mensagem e efeitos), devolvido como DecisaoV2."""
        base = v1._ir_para(destino, self.nos, self.terminais,
                           criterios=tuple(dict(criterios).items()), dias=dias)
        return DecisaoV2(**{f.name: getattr(base, f.name) for f in fields(base)}, **extra)

    def tela(self, no_id: str, **extra) -> DecisaoV2:
        """Reapresenta uma tela SEM efeito, foto ou carrossel (volta de FAQ).

        Vitrine → só os botões de ação (`vitrine="acoes"`); nó comum → a tela
        normal; `T_ADIAR` → a folha de prazos, sem reaplicar o terminal.
        """
        no = self.nos.get(no_id)
        if no is not None:
            if no_id in VITRINES:
                return DecisaoV2(proximo_no=no_id, vitrine="acoes",
                                 mensagem=Mensagem(corpo=r.CORPO_ACOES, botoes=no.botoes),
                                 **extra)
            return DecisaoV2(proximo_no=no_id,
                             mensagem=Mensagem(corpo=no.corpo, botoes=no.botoes), **extra)
        terminal = self.terminais.get(no_id)
        if terminal is not None and terminal.prazos:
            return DecisaoV2(proximo_no=no_id,
                             mensagem=Mensagem(corpo=terminal.corpo, botoes=reg1.BOTOES_PRAZO),
                             **extra)
        return self.ir_para(ID_HUMANO, **extra)

    def tabela(self, **extra) -> DecisaoV2:
        """Reenvia a tabela + ações da vitrine do ramo (spec §7.3 e VK)."""
        vitrine = r.VITRINE_DO_RAMO.get(self.ramo or "")
        if vitrine is None:
            return self.ir_para(r.NO_ENTRADA, **extra)
        no = self.nos.get(vitrine)
        if no is None:
            return self.ir_para(ID_HUMANO, **extra)
        return DecisaoV2(proximo_no=vitrine, vitrine="tabela",
                         mensagem=Mensagem(corpo=r.CORPO_ACOES, botoes=no.botoes), **extra)

    def handoff(self, motivo: str, **extra) -> DecisaoV2:
        """Handoff do ramo; sem ramo com vendedor, T_HUMANO (spec §7.2)."""
        destino = r.HANDOFF_DO_RAMO.get(self.ramo or "", ID_HUMANO)
        return self.ir_para(destino, repasse_motivo=motivo, **extra)

    def faq(self, faq_id: str, retorno: str, **extra) -> DecisaoV2:
        return self.tela(retorno, faq=faq_id, **extra)

    # ── 6. Clique ──────────────────────────────────────────────────────────
    def clique(self, clique: Clique, botoes: tuple) -> DecisaoV2:
        card = self._casar_card(clique.payload)
        if card is not None:
            criterios = {"purchase_intent": "clear"} if self.ramo == "atacado" else {}
            return self.ir_para(card.destino, criterios=criterios,
                                memoria={"interesse": card.id, "ruidos": 0})
        botao = v1._casar(self.no_atual, clique, botoes, self.est)
        if botao is None:
            return self.ruido(botoes)
        return self._seguir(botao)

    def _casar_card(self, payload: str | None) -> reg1.Card | None:
        if not payload or not payload.startswith(_PREFIXO_CARD):
            return None
        no = self.nos.get(self.no_atual)
        cards = getattr(no, "cards", ()) if no is not None else ()
        card_id = payload[len(_PREFIXO_CARD):]
        return next((c for c in cards if c.id == card_id), None)

    def _seguir(self, botao: reg1.Botao) -> DecisaoV2:
        """Rota de um botão casado, pelo `destino` declarado."""
        respostas = {**self.respostas, self.no_atual: botao.id}
        memoria: dict = {"respostas": respostas, "ruidos": 0}
        criterios = dict(botao.grava)
        if self.ramo == "atacado" and botao.id == "pedido":
            criterios["purchase_intent"] = "clear"
        motivo = f'clicou "{botao.rotulo}"'
        destino = botao.destino

        if destino.startswith("faq:"):
            retorno = self.est.get("retorno")
            if not (isinstance(retorno, str) and retorno):
                retorno = r.VITRINE_DO_RAMO.get(self.ramo or "", r.NO_ENTRADA)
            return self.faq(destino[4:], retorno, memoria=memoria, criterios=criterios)

        if destino == "tabela":
            return self.tabela(memoria=memoria, criterios=criterios)

        if destino == "handoff":
            return self.handoff(motivo, memoria=memoria, criterios=criterios)

        if destino == "regra:QP2":
            destino = r.REGRA_QP2.get((respostas.get("QP1"), botao.id), "T_HANDOFF_PL")

        extra: dict = {}
        if destino in r.DUVIDAS_DO_RAMO.values():
            memoria["retorno"] = self.no_atual
        if destino in VITRINES:
            memoria["ramo"] = r.RAMO_DO_NO[destino]
            extra["vitrine"] = "completa"
        terminal = self.terminais.get(destino)
        if destino not in self.nos and terminal is not None and terminal.handoff:
            extra["repasse_motivo"] = motivo
        dias = reg1.DIAS_POR_PRAZO.get(botao.id) if botao in reg1.BOTOES_PRAZO else None
        return self.ir_para(destino, criterios=criterios, dias=dias, memoria=memoria, **extra)

    # ── 7. Texto classificado ──────────────────────────────────────────────
    def classificado(self, ev: TextoClassificado, botoes: tuple) -> DecisaoV2:
        conteudo = ev.conteudo or ""
        if self.no_atual == "VO":
            return self._no_vo(ev, conteudo)

        if ev.classe == "BOTAO":
            alvo = self._botao_classificado(ev.botao_id, botoes)
            if alvo is not None:
                return self.clique(Clique(payload=alvo, titulo=""), botoes)
            return self.ruido(botoes)

        if ev.classe == "FAQ":
            if ev.faq_id == "preco":
                return self._preco(conteudo)
            if self._faq_valida(ev.faq_id):
                return self.faq(ev.faq_id, self.no_atual, memoria={"ruidos": 0})
            return self.ruido(botoes)

        if ev.classe in ("PERGUNTA", "VENDEDOR"):
            return self.handoff(f"{ev.classe}: {conteudo[:_LIMITE_TEXTO_MOTIVO]}")

        # RUIDO e qualquer etiqueta desconhecida. (SAIR já saiu na regra 4.)
        return self.ruido(botoes)

    def _no_vo(self, ev: TextoClassificado, conteudo: str) -> DecisaoV2:
        """VO espera uma pergunta: FAQ responde e volta; o resto vai ao vendedor."""
        if ev.classe == "FAQ" and ev.faq_id == "preco":
            return self.tabela(memoria={"ruidos": 0})
        if ev.classe == "FAQ" and self._faq_valida(ev.faq_id):
            retorno = self.est.get("retorno")
            if not (isinstance(retorno, str) and retorno):
                retorno = r.VITRINE_DO_RAMO.get(self.ramo or "", r.NO_ENTRADA)
            return self.faq(ev.faq_id, retorno, memoria={"ruidos": 0})
        return self.handoff(f"PERGUNTA: {conteudo[:_LIMITE_TEXTO_MOTIVO]}")

    def _botao_classificado(self, botao_id: str | None, botoes: tuple) -> str | None:
        """Payload equivalente ao id que o classificador escolheu, ou None.

        Re-checa contra a tela atual. Card aceita "card:<id>" ou o id puro (o
        runner pode listar os cards ao classificador de um jeito ou de outro).
        """
        if not botao_id:
            return None
        if any(b.id == botao_id for b in botoes):
            return botao_id
        payload = botao_id if botao_id.startswith(_PREFIXO_CARD) else _PREFIXO_CARD + botao_id
        return payload if self._casar_card(payload) is not None else None

    def _faq_valida(self, faq_id: str | None) -> bool:
        return bool(faq_id) and faq_id in r.FAQ.get(self.ramo or "", {})

    def _preco(self, conteudo: str) -> DecisaoV2:
        """Pergunta de preço: tabela do ramo; antes do ramo, a tela de ramo.

        Ramo SEM vitrine (consumo, exportação) não volta ao N0 — isso apagaria o
        caminho já feito; vai ao vendedor do ramo, como uma pergunta.
        """
        ramo = self.ramo
        if ramo is None:
            return self.ir_para(r.NO_ENTRADA, memoria={"ruidos": 0})
        if ramo in r.VITRINE_DO_RAMO:
            return self.tabela(memoria={"ruidos": 0})
        return self.handoff(f"PERGUNTA: {conteudo[:_LIMITE_TEXTO_MOTIVO]}")

    # ── RUIDO (regras 7 e 8) ───────────────────────────────────────────────
    def ruido(self, botoes: tuple) -> DecisaoV2:
        """1º texto não entendido: nudge com os botões da tela. 2º: vendedor."""
        n = self.ruidos + 1
        if n < r.TETO_RUIDO and botoes:
            mensagem = Mensagem(corpo=self.corpo_nudge or r.CORPO_NUDGE, botoes=botoes)
            extra = {"vitrine": "acoes"} if self.no_atual in VITRINES else {}
            return DecisaoV2(proximo_no=self.no_atual, mensagem=mensagem,
                             marcar_nudge=True, memoria={"ruidos": n}, **extra)
        return self.handoff(MOTIVO_RUIDO, memoria={"ruidos": n})

