"""Declaração do fluxo de botões da reativação. Dados puros, zero lógica.

Separado de engine.py de propósito: mudar um texto ou um rótulo não deve exigir
reler o motor de decisão, e o motor não deve precisar mudar para um fluxo novo.

Leaf module: não importa nada de `app`, evitando ciclos de import.
"""
from __future__ import annotations

from dataclasses import dataclass

# Versão do fluxo. Gravada em conversations.flow_state["flow"]; um estado com
# versão diferente é tratado como incompatível e devolvido ao humano.
FLOW_ID = "reativacao_v1"

# ── Nós ─────────────────────────────────────────────────────────────────────
NO_INTERESSE = "aguardando_interesse"
NO_PRAZO = "aguardando_prazo"
NO_ENCERRADO = "encerrado"

# ── Tags de desfecho (semeadas em 20260820_button_flow_agent.sql) ───────────
TAG_QUENTE = "Reativação: Quente"
TAG_RECUSOU = "Reativação: Recusou"
TAG_HUMANO = "Reativação: Atendimento humano"


@dataclass(frozen=True)
class Botao:
    """Um botão do fluxo.

    `titulo` é o rótulo da mensagem INTERATIVA (limite Meta: 20 chars).
    `rotulo_template` é o rótulo aprovado no TEMPLATE (limite: 25 chars), quando ele
    precisa ser diferente por não caber nos 20. O motor aceita os dois ao casar um
    clique — é o mesmo botão, em duas superfícies com limites diferentes.
    """
    id: str
    titulo: str
    rotulo_template: str | None = None

    @property
    def titulos_aceitos(self) -> tuple[str, ...]:
        if self.rotulo_template and self.rotulo_template != self.titulo:
            return (self.titulo, self.rotulo_template)
        return (self.titulo,)


@dataclass(frozen=True)
class Prazo:
    id: str
    titulo: str
    meses: int
    rotulo_humano: str
    tag: str


# ── Nível 1: interesse ──────────────────────────────────────────────────────
# Os IDs só valem para o reoferecimento (nudge), que sai como mensagem interativa:
# quick reply de template não aceita payload customizado — o payload chega igual ao
# texto do botão. Por isso o motor casa nível 1 por id OU por título normalizado.
#
# Dois rótulos por botão: a Meta permite 25 chars no template e só 20 na interativa,
# e a copy aprovada de dois deles tem 22. O template (a mensagem que os leads de fato
# recebem no disparo) fica com a copy aprovada; o nudge usa a versão curta.
BTN_QUENTE = Botao("interesse_quente", "Quero comprar agora")
BTN_TALVEZ = Botao("interesse_talvez", "Mais pra frente", "Talvez em alguns meses")
BTN_SAIR = Botao("interesse_sair", "Sair da lista", "Não quero mais receber")

BOTOES_INTERESSE: tuple[Botao, ...] = (BTN_QUENTE, BTN_TALVEZ, BTN_SAIR)

# Contrato com o template aprovado — verificado pelo preflight do disparo.
ROTULOS_TEMPLATE_NIVEL1: tuple[str, ...] = tuple(
    b.rotulo_template or b.titulo for b in BOTOES_INTERESSE
)

# ── Nível 2: prazo de recontato ─────────────────────────────────────────────
PRAZOS: tuple[Prazo, ...] = (
    Prazo("prazo_1m", "Daqui a 1 mês", 1, "daqui a 1 mês", "Reativação: 1 mês"),
    Prazo("prazo_3m", "Daqui a 3 meses", 3, "daqui a 3 meses", "Reativação: 3 meses"),
    Prazo("prazo_6m", "Daqui a 6 meses", 6, "daqui a 6 meses", "Reativação: 6 meses"),
)

BOTOES_PRAZO: tuple[Botao, ...] = tuple(Botao(p.id, p.titulo) for p in PRAZOS)

BOTOES_POR_NO: dict[str, tuple[Botao, ...]] = {
    NO_INTERESSE: BOTOES_INTERESSE,
    NO_PRAZO: BOTOES_PRAZO,
}

# ── Textos ──────────────────────────────────────────────────────────────────
# O corpo do nível 1 NÃO vive aqui: ele é o template aprovado na Meta, escolhido
# pelo operador no disparo. Só o corpo do reoferecimento é nosso.
CORPO_NUDGE = "Pra facilitar, é só tocar numa das opções abaixo:"

CORPO_PRAZO = "Beleza! Quando faz sentido eu te chamar de novo?"

MSG_QUENTE_VALERIA = (
    "Perfeito! Vou te passar pro João, nosso especialista — ele te chama já já. "
    "Deixo o contato dele aqui embaixo pra agilizar."
)
MSG_QUENTE_VENDEDOR = "Perfeito! Já te chamo por aqui pra gente resolver."

MSG_PRAZO_FECHAMENTO = (
    "Combinado, {prazo}. Vou anotar aqui e te chamo nessa época. "
    "Qualquer coisa antes disso, é só me escrever!"
)

MSG_OPTOUT = "Entendido, não te mando mais nada. Obrigado pelo tempo e um abraço!"

# Corpo do reoferecimento por nó: no nível 1 só o convite (a pergunta já foi feita
# pelo template); no nível 2 a pergunta inteira, porque ela é nossa.
CORPO_NUDGE_POR_NO: dict[str, str] = {
    NO_INTERESSE: CORPO_NUDGE,
    NO_PRAZO: f"{CORPO_NUDGE}\n\n{CORPO_PRAZO}",
}
