"""Declaração do fluxo de botões da recuperação. Dados puros, zero lógica.

Separado de engine.py de propósito: mudar um texto ou um rótulo não deve exigir
reler o motor de decisão, e o motor não deve precisar mudar para um fluxo novo.

Leaf module: não importa nada de `app`, evitando ciclos de import.

── Por que os rótulos são estes (09/09/2026) ────────────────────────────────
O trio original ("Continuar atendimento" / "Tirar duvidas" / "Nao tenho interesse")
foi medido em ~1.300 envios reais e tem três defeitos:
  - "Tirar duvidas" é botão MORTO: 4 cliques (0,3%). Slot desperdiçado.
  - "Nao tenho interesse" captura quem só queria dizer "agora não": 64 cliques, e
    41% dessas pessoas continuaram conversando — 2 compraram depois. Tratar isso
    como opt-out destrói pipeline com histórico de venda.
  - o trio produz 2,2x mais recusas do que aceites (64 vs 29).
E o achado que decide o desenho: pergunta de ESTADO ("Falo com {{1}} neste
número?") teve 33,5% de resposta e 74% de positivos, contra 8,6% de resposta da
pergunta de COMPROMISSO ("pedido em aberto, continuar?"). Por isso o slot do meio
virou ADIAMENTO — que preserva o lead — e não uma recusa.
"""
from __future__ import annotations

from dataclasses import dataclass

# Versão do fluxo. Gravada em conversations.flow_state["flow"]; um estado com
# versão diferente é tratado como incompatível e devolvido ao humano.
FLOW_ID = "recuperacao_v1"

# ── Nós ─────────────────────────────────────────────────────────────────────
NO_INTERESSE = "aguardando_interesse"
NO_PRAZO = "aguardando_prazo"
NO_ENCERRADO = "encerrado"

# ── Tags de desfecho (semeadas em 20260820_button_flow_agent.sql §4) ────────
# O ponteiro dizia 20260909_recuperacao_stages_optout.sql até 09/09/2026 e estava
# errado: aquela migração cria as ETAPAS do funil e as colunas de opt-out, e a §3
# dela é só uma nota dizendo que as tags NÃO moram lá. Quem fosse conferir um nome
# de tag pelo comentário abriria o arquivo errado — e um nome divergente aqui não
# levanta nada: add_tags_to_lead resolve por nome exato e devolve em silêncio.
TAG_QUENTE = "Recuperação: Quente"
TAG_RECUSOU = "Recuperação: Recusou"
TAG_HUMANO = "Recuperação: Atendimento humano"
TAG_CADASTRO_MANTIDO = "Recuperação: Cadastro mantido"
TAG_ENGANO = "Recuperação: Pretexto contestado"


@dataclass(frozen=True)
class Botao:
    """Um botão do fluxo.

    `titulo` é o rótulo da mensagem INTERATIVA (limite Meta: 20 chars) e também o
    rótulo do template quando ele cabe — todos os nossos cabem, de propósito, para
    que o mesmo texto sirva nas duas superfícies (o template aceita 25).

    `rotulos_extras` são outros rótulos aprovados que mapeiam para o MESMO id: um
    clique vindo do template da trilha A traz "Retomar o pedido" e um da trilha B
    traz "Preciso repor" — os dois são o botão `repor`.
    """
    id: str
    titulo: str
    rotulos_extras: tuple[str, ...] = ()

    @property
    def titulos_aceitos(self) -> tuple[str, ...]:
        return (self.titulo, *self.rotulos_extras)


@dataclass(frozen=True)
class Prazo:
    id: str
    titulo: str
    dias: int
    rotulo_humano: str
    tag: str


# ── Ids de botão (o contrato estável; os rótulos mudam, os ids não) ─────────
ID_REPOR = "repor"
ID_ADIAR = "adiar"
ID_OPTOUT = "optout"
ID_MANTER = "manter"
ID_ATUALIZAR = "atualizar"

# ── Nível 1, por trilha ─────────────────────────────────────────────────────
# Trilha A (pedido não faturado, 62 leads) e B (reposição, 303) compartilham a
# semântica: avanço / adiamento / saída. A trilha C (higienização, 665) NÃO vende
# — "Manter cadastro" é opt-in prospectivo registrado, não intenção de compra.
TRILHA_PEDIDO = "pedido"
TRILHA_ESTOQUE = "estoque"
TRILHA_CADASTRO = "cadastro"
TRILHA_PADRAO = TRILHA_ESTOQUE

BTN_REPOR = Botao(ID_REPOR, "Preciso repor", ("Retomar o pedido",))
BTN_ADIAR = Botao(ID_ADIAR, "Ainda tenho estoque", ("Quero outro item",))
BTN_OPTOUT = Botao(ID_OPTOUT, "Parar mensagens")
BTN_MANTER = Botao(ID_MANTER, "Manter cadastro")
BTN_ATUALIZAR = Botao(ID_ATUALIZAR, "Atualizar dados")

# Rótulo exibido no nudge de cada trilha. O id é o mesmo; só o texto muda, para
# ecoar o template que o lead recebeu.
BTN_REPOR_PEDIDO = Botao(ID_REPOR, "Retomar o pedido")
BTN_ADIAR_PEDIDO = Botao(ID_ADIAR, "Quero outro item")

BOTOES_POR_TRILHA: dict[str, tuple[Botao, ...]] = {
    TRILHA_PEDIDO: (BTN_REPOR_PEDIDO, BTN_ADIAR_PEDIDO, BTN_OPTOUT),
    TRILHA_ESTOQUE: (BTN_REPOR, BTN_ADIAR, BTN_OPTOUT),
    TRILHA_CADASTRO: (BTN_MANTER, BTN_ATUALIZAR, BTN_OPTOUT),
}

# Contrato com o template aprovado — verificado pelo preflight do disparo.
ROTULOS_TEMPLATE_POR_TRILHA: dict[str, tuple[str, ...]] = {
    trilha: tuple(b.titulo for b in botoes)
    for trilha, botoes in BOTOES_POR_TRILHA.items()
}

# ── Nível 2: prazo de recontato ─────────────────────────────────────────────
# Em DIAS, não meses: o intervalo médio entre compras desta coorte é 78-122 dias,
# então 90 é o ciclo natural e 30/60 capturam os mais rápidos. "3 meses" seria um
# rótulo pior para o mesmo número.
PRAZOS: tuple[Prazo, ...] = (
    Prazo("snooze30", "Em 30 dias", 30, "em 30 dias", "Recuperação: 30 dias"),
    Prazo("snooze60", "Em 60 dias", 60, "em 60 dias", "Recuperação: 60 dias"),
    Prazo("snooze90", "Em 90 dias", 90, "em 90 dias", "Recuperação: 90 dias"),
)

BOTOES_PRAZO: tuple[Botao, ...] = tuple(Botao(p.id, p.titulo) for p in PRAZOS)

# Todos os botões conhecidos, para o índice de casamento do motor. Nível 1 entra
# por trilha; o casamento é global de propósito (um clique sempre resolve, mesmo
# que a trilha gravada no estado esteja errada ou ausente).
TODOS_BOTOES_NIVEL1: tuple[Botao, ...] = (
    BTN_REPOR, BTN_ADIAR, BTN_OPTOUT, BTN_MANTER, BTN_ATUALIZAR,
)

# ── Textos ──────────────────────────────────────────────────────────────────
# O corpo do nível 1 NÃO vive aqui: ele é o template aprovado na Meta, escolhido
# pelo operador no disparo. Só o corpo do reoferecimento é nosso.
CORPO_NUDGE = "Pra facilitar, é só tocar numa das opções abaixo:"
CORPO_PRAZO = "Beleza! Quando faz sentido eu te chamar de novo?"

# O turno que decide o projeto. Entrega concreta, ZERO pergunta.
#
# Autópsia que fixou este formato: 14 leads morreram logo depois da sequência
# "cadastro confirmado" + pergunta aberta, e a última coisa que cada um disse foi
# apenas "Sim". Abrir com ack de sistema dobra a chance de matar a thread (39% vs
# 18%) e corta o handoff pela metade (14% vs 27%). E 69,5% dos leads da base nunca
# viram preço nem foto — quem recebeu algo concreto chegou ao vendedor em 73-75%,
# contra 56,5% de quem não recebeu nada.
MSG_QUENTE_COM_PRODUTO = (
    "perfeito{vocativo}\n"
    "você levava {produto} — hoje ele está {preco} a unidade\n"
    "já chamei o João aqui, ele te responde em instantes"
)
# Sem preço: o produto do briefing não casou com nenhum dos 32 SKUs ativos (141
# leads compravam outras marcas, 123 cápsula, 47 drip — o Bling tem 444 produtos).
# Cotar de memória foi o que perdeu as 500 unidades da Ritz.
MSG_QUENTE_SEM_PRECO = (
    "perfeito{vocativo}\n"
    "você levava {produto} — já chamei o João aqui pra te passar a condição de hoje\n"
    "ele te responde em instantes"
)
# Sem produto conhecido no cadastro.
MSG_QUENTE_SEM_PRODUTO = (
    "perfeito{vocativo}\n"
    "já chamei o João aqui, ele te responde em instantes"
)

MSG_PRAZO_FECHAMENTO = (
    "combinado, {prazo}. anotei aqui e te chamo nessa época.\n"
    "qualquer coisa antes disso, é só me escrever!"
)

MSG_OPTOUT = "entendido, não te mando mais nada por aqui. obrigado pelo tempo!"

MSG_CADASTRO_MANTIDO = (
    "obrigado{vocativo}! deixei seu cadastro ativo por aqui.\n"
    "quando precisar de café, é só me chamar neste mesmo número."
)

MSG_ATUALIZAR_DADOS = (
    "combinado! já chamei o João aqui pra atualizar seus dados com você."
)

# Pretexto contestado ("não fiz nenhum pedido", "nunca comprei esse café"). Aborta
# o script comercial na hora. O template `rabubens` ("seu pedido já está sendo
# preparado") teve 44,2% de negação/confusão em 104 respostas, incluindo pânico de
# cliente legítimo — este é o caminho mais curto para um report na Meta.
MSG_ENGANO = (
    "me desculpe pelo transtorno! puxei seu contato do nosso cadastro antigo e "
    "posso ter me confundido.\n"
    "se preferir, é só tocar em \"Parar mensagens\" que eu não te escrevo mais."
)

# Corpo do reoferecimento por nó: no nível 1 só o convite (a pergunta já foi feita
# pelo template); no nível 2 a pergunta inteira, porque ela é nossa.
CORPO_NUDGE_POR_NO: dict[str, str] = {
    NO_INTERESSE: CORPO_NUDGE,
    NO_PRAZO: f"{CORPO_NUDGE}\n\n{CORPO_PRAZO}",
}


def render(corpo: str, dados: dict[str, str]) -> str:
    """Substitui placeholders `{chave}` conhecidos. NÃO é str.format.

    str.format estouraria em qualquer chave ausente e quebraria num corpo que
    contenha chave literal — e o corpo aqui é texto de negócio, editado por quem
    não pensa em sintaxe de formatação. Aqui, chave ausente fica como está e a
    ausência é visível no teste, em vez de virar KeyError em produção.

    Função pura.
    """
    for chave, valor in dados.items():
        corpo = corpo.replace("{" + chave + "}", valor)
    return corpo
