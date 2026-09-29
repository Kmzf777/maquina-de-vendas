"""Overrides de conteúdo para os TERMINAIS: a mesma promessa de `NOS`, que até
aqui não valia pra eles.

`valeria_content.aplicar`/`validar` só enxergavam `reg.NOS` e `reg.CHAVE_NUDGE`.
Terminal não é nó — não tem `botoes` próprios, e 6 dos 8 carregam efeito
(`vendedor`, `tags`, `handoff`, `optout`, `silenciar_ia`, `prazos`) que a tela
NUNCA pode tocar — mas o `corpo` de um terminal é a mesma classe de texto que o
de um nó, e o do handoff é a linha mais consequente do fluxo inteiro (a
auditoria 08/07 mediu que maiúscula, "!" e emoji ali quebraram a máscara no
momento mais frágil da conversa). Sem este módulo, os 8 corpos de terminal
ficavam hardcoded — a promessa de "a tela edita o texto" quebrada pra 8 das 25
mensagens do fluxo.

Regra do corpo em branco, que é DIFERENTE da regra de nó: `T_HUMANO` e `T_FIM`
têm `corpo=""` no registry por CONTRATO — "spends no billed message"
(valeria_registry.py:602-616). Um override em branco nesses dois só reafirma o
contrato que já vale. Nos outros seis, `corpo=""` no registry é ausência de
dado, não contrato: braquear `T_HANDOFF` deixaria o lead sem ser avisado que
foi encaminhado, em silêncio, depois de pedir pra falar com alguém — e é
exatamente esse o "momento mais frágil" que a auditoria mediu. Por isso a regra
implementada é: **override em branco só é aceito nos terminais cujo DEFAULT do
registry já é em branco** — a mesma pergunta que `validar` já faz pra nó
("o corpo não pode ficar vazio"), só que a resposta depende do terminal, não é
fixa.
"""
from dataclasses import replace

from app.button_flow import valeria_content as conteudo
from app.button_flow import valeria_registry as reg

# Terminais cujo corpo PADRÃO já é vazio — onde branco é contrato, não descuido.
_TERMINAIS_COM_DEFAULT_VAZIO = {t.id for t in reg.TERMINAIS.values() if t.corpo == ""}


def test_defaults_sao_os_do_registry_sem_default_vazio_estar_vazio_por_engano():
    """Trava de sanidade do próprio teste: se o registry mudar e os dois
    terminais de corpo vazio deixarem de ser T_HUMANO/T_FIM, os testes de
    branco abaixo estariam testando o par errado."""
    assert _TERMINAIS_COM_DEFAULT_VAZIO == {"T_HUMANO", "T_FIM"}


# ── aplicar_terminais ───────────────────────────────────────────────────────

def test_sem_override_devolve_os_defaults_do_registry():
    terminais = conteudo.aplicar_terminais(reg.TERMINAIS, {})
    for terminal_id, terminal in reg.TERMINAIS.items():
        assert terminais[terminal_id] == terminal


def test_override_de_corpo_aplica_e_nao_vaza_para_outro_terminal():
    terminais = conteudo.aplicar_terminais(
        reg.TERMINAIS, {"T_HANDOFF": {"corpo": "já te encaminhei, um instante"}}
    )
    assert terminais["T_HANDOFF"].corpo == "já te encaminhei, um instante"
    assert terminais["T_HANDOFF_PL"].corpo == reg.TERMINAIS["T_HANDOFF_PL"].corpo, (
        "override de um terminal não pode vazar pro outro, mesmo os dois sendo "
        "handoff do mesmo vendedor"
    )


def test_override_nunca_muda_efeito_nenhum():
    """`vendedor`, `tags`, `handoff`, `optout`, `silenciar_ia`, `prazos` são
    EFEITO, não texto. Um override carregando qualquer um deles não pode
    mudar nada além de `corpo` — a mesma garantia que `aplicar` já dá pros
    nós, agora pros terminais."""
    original = reg.TERMINAIS["T_HANDOFF"]
    override_hostil = {
        "T_HANDOFF": {
            "corpo": "novo texto do handoff",
            "vendedor": "Ninguem",
            "tags": ("Tag Forjada",),
            "handoff": False,
            "optout": True,
            "silenciar_ia": False,
            "prazos": True,
        }
    }
    terminais = conteudo.aplicar_terminais(reg.TERMINAIS, override_hostil)
    resultado = terminais["T_HANDOFF"]

    assert resultado.corpo == "novo texto do handoff"
    assert resultado.vendedor == original.vendedor
    assert resultado.tags == original.tags
    assert resultado.handoff == original.handoff
    assert resultado.optout == original.optout
    assert resultado.silenciar_ia == original.silenciar_ia
    assert resultado.prazos == original.prazos


def test_aplicar_terminais_nao_muta_o_registry():
    """O registry é frozen, mas o dict que o contém não é — mesma defesa de
    `aplicar`: devolver um dict NOVO."""
    antes = reg.TERMINAIS["T_HANDOFF"].corpo
    conteudo.aplicar_terminais(reg.TERMINAIS, {"T_HANDOFF": {"corpo": "outro"}})
    assert reg.TERMINAIS["T_HANDOFF"].corpo == antes


def test_terminal_desconhecido_no_override_e_ignorado():
    terminais = conteudo.aplicar_terminais(reg.TERMINAIS, {"NAO_EXISTE": {"corpo": "x"}})
    assert set(terminais) == set(reg.TERMINAIS)


def test_override_em_branco_nao_aplica_para_terminal_de_default_vazio():
    """`T_HUMANO` já nasce com corpo vazio; um override vazio não muda nada
    de observável — não aplicar ou aplicar branco dá o mesmo resultado."""
    terminais = conteudo.aplicar_terminais(reg.TERMINAIS, {"T_HUMANO": {"corpo": ""}})
    assert terminais["T_HUMANO"].corpo == ""


# ── validar ──────────────────────────────────────────────────────────────
# (o portão de GRAVAÇÃO — é aqui, não em `aplicar_terminais`, que uma linha
# ruim é barrada antes de chegar no banco)

def test_validar_aceita_override_de_corpo_de_terminal():
    assert conteudo.validar("T_HANDOFF", {"corpo": "já chamei o João"}) is None


def test_validar_rejeita_rotulos_em_terminal():
    """Terminal não declara `botoes` — nem `T_ADIAR` (a folha 30/60/90 vem de
    `reg.BOTOES_PRAZO`, declarada à parte). Um `rotulos` em override de
    terminal não tem em que pousar: silenciar isso deixaria a tela achando
    que salvou um rótulo que nunca é lido em lugar nenhum."""
    erro = conteudo.validar("T_HANDOFF", {"rotulos": {"sim": "Bora"}})
    assert erro is not None
    assert "rótulo" in erro or "rotulo" in erro.lower()


def test_validar_rejeita_rotulos_mesmo_com_corpo_valido_junto():
    erro = conteudo.validar(
        "T_ADIAR", {"corpo": "texto novo", "rotulos": {"p30": "Em 30"}}
    )
    assert erro is not None


def test_validar_permite_corpo_em_branco_so_nos_terminais_de_default_vazio():
    """A regra do módulo: branco é aceito SÓ onde o próprio registry já
    declara `corpo=""` por contrato (T_HUMANO, T_FIM). Nos outros seis,
    branco é rejeitado — igual a nó — porque lá branco não é contrato, é o
    lead ficando sem resposta depois de pedir pra ser encaminhado."""
    for terminal_id in reg.TERMINAIS:
        erro = conteudo.validar(terminal_id, {"corpo": "   "})
        if terminal_id in _TERMINAIS_COM_DEFAULT_VAZIO:
            assert erro is None, f"{terminal_id} deveria aceitar corpo em branco"
        else:
            assert erro is not None, (
                f"{terminal_id} tem default não-vazio — corpo em branco tinha "
                "que ser rejeitado, senão o handoff vira silêncio"
            )


def test_validar_terminal_desconhecido():
    assert conteudo.validar("T_NAO_EXISTE", {"corpo": "x"}) is not None


def test_validar_terminal_corpo_ausente_no_payload_nao_e_erro():
    """Payload só com `rotulos` de outra coisa, ou dict vazio: sem chave
    `corpo`, não há o que validar de texto."""
    assert conteudo.validar("T_HANDOFF", {}) is None


# ── Nó continua exatamente como antes ───────────────────────────────────────
# (reassert: estender `validar` pra terminal não pode afrouxar a regra de nó)

def test_no_ainda_rejeita_corpo_vazio():
    assert conteudo.validar("N1", {"corpo": "   "}) is not None


def test_no_ainda_aceita_rotulos():
    assert conteudo.validar("N1", {"rotulos": {"cafeteria": "Sou cafeteria"}}) is None


def test_no_ainda_e_o_default_sem_override():
    nos = conteudo.aplicar(reg.NOS, {})
    assert nos["N1"].corpo == reg.NOS["N1"].corpo
