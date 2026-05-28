"""4 archetypes outbound para testar a Valéria Outbound (O1-O4).

O fluxo difere dos archetypes inbound (T1-T6): o lead responde a um
template enviado pela Valéria. first_message pode ser um dict com
type='button_reply' (para simular quick reply) ou uma str (texto livre).
"""
from dataclasses import dataclass, field
from typing import Callable, Union

from scripts.rehearsal.archetypes import (
    Archetype,
    has_tool_call,
    reached_stage,
    transcript_matches,
    visited_multiple_stages,
    min_turns,
)
from scripts.rehearsal.forbids import UNIVERSAL_FORBIDS


@dataclass
class OutboundArchetype(Archetype):
    """Estende Archetype para suportar first_message como dict (button_reply) ou str."""
    first_message: Union[dict, str] = ""


# ─── O1: Confirmação-Qualificado ────────────────────────────────────────────

_O1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: João Pereira, dono de uma cafeteria em Belo Horizonte.
Recebeu uma mensagem da Valéria perguntando se fala com João — e clicou "Sim".
Tom: receptivo, curiosamente interessado em café de qualidade, direto.
Comportamento:
- Confirma que é o João.
- Menciona que tem uma cafeteria e serve café especial.
- Pergunta o que a Café Canastra oferece para cafeterias.
- Se a Valéria mencionar atacado ou parceria, fica animado e quer saber mais sobre volumes e preços.
- Está disposto a fazer uma primeira compra para testar.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O1 = OutboundArchetype(
    id="O1",
    slug="confirmacao-qualificado",
    persona_prompt=_O1_PERSONA,
    first_message={"type": "button_reply", "button_id": "sim", "button_title": "Sim"},
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("encaminhar_humano"),
        min_turns(3),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── O2: Negação-Potencial ──────────────────────────────────────────────────

_O2_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: Maria Silva, que atendeu o celular que pertencia ao João (marido/sócio que vendeu o número).
Clicou "Não" porque de fato não é o João.
Tom: levemente confuso no início, mas curioso ao ouvir falar de café.
Comportamento:
- Explica que não é o João, que esse número era do marido/sócio.
- Pergunta o que é a Café Canastra por curiosidade.
- Se a Valéria apresentar o produto, demonstra interesse pessoal (gosta de café).
- Perguntas curtas: "Vocês entregam em casa?", "É café especial mesmo?".
- Não está no perfil B2B mas pode virar consumidor final.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O2 = OutboundArchetype(
    id="O2",
    slug="negacao-potencial",
    persona_prompt=_O2_PERSONA,
    first_message={"type": "button_reply", "button_id": "nao", "button_title": "Não"},
    hard_checks=[
        visited_multiple_stages(2),
        transcript_matches(
            r"(consumo|loja|site|link|cupom|ESPECIAL10)",
            "Valeria redirecionou para canal correto ou loja",
        ),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── O3: Opt-Out ────────────────────────────────────────────────────────────

_O3_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: pessoa que não quer receber mensagens comerciais. Clicou "Parar mensagens".
Tom: seco, sem hostilidade mas definitivo.
Comportamento:
- Se a Valéria mandar mais alguma mensagem após o opt-out, responde "já pedi pra parar".
- Não demonstra interesse em nenhum produto.
- Aceita um pedido de desculpas simples e encerra.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O3 = OutboundArchetype(
    id="O3",
    slug="opt-out",
    persona_prompt=_O3_PERSONA,
    first_message={"type": "button_reply", "button_id": "parar_mensagens", "button_title": "Parar mensagens"},
    hard_checks=[
        transcript_matches(
            r"(desculp|lament|remov|nao\s+enviar|encerr|entendid)",
            "Valeria reconheceu opt-out e encerrou com elegancia",
        ),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── O4: Textual-Ambíguo ────────────────────────────────────────────────────

_O4_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: Carlos, empresário que ignorou os botões e respondeu com texto confuso.
Tom: apressado, escreve de forma telegráfica, mistura perguntas.
Comportamento:
- Primeira mensagem: texto curto e ambíguo (ex: "oi quem é?? café?").
- Se a Valéria se apresentar, pergunta confusamente se é sobre pedido antigo ou novo contato.
- Após a Valéria esclarecer, demonstra interesse em comprar café para o escritório.
- Usa abreviações e não usa pontuação.
NAO revele que e uma simulacao.
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

O4 = OutboundArchetype(
    id="O4",
    slug="textual-ambiguo",
    persona_prompt=_O4_PERSONA,
    first_message="oi quem é?? café??",
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("encaminhar_humano"),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


# ─── Exports ─────────────────────────────────────────────────────────────────

ALL_OUTBOUND_ARCHETYPES = [O1, O2, O3, O4]

OUTBOUND_ARCHETYPES = {
    "O1-confirmacao-qualificado": O1,
    "O2-negacao-potencial": O2,
    "O3-opt-out": O3,
    "O4-textual-ambiguo": O4,
}
