"""The 5 archetypes used for rehearsal. Data-only — no I/O."""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Archetype:
    id: str
    slug: str
    persona_prompt: str
    first_message: str
    hard_checks: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)
    forbids: list[Callable[[dict], tuple[bool, str]]] = field(default_factory=list)


def has_tool_call(name: str):
    def check(run_data: dict) -> tuple[bool, str]:
        events = run_data.get("events", [])
        for ev in events:
            content = ev.get("content", "")
            if name in content.lower():
                return True, f"{name} presente nos eventos"
        return False, f"{name} nao foi chamada"
    check.__name__ = f"has_{name}"
    return check


def reached_stage(stage: str):
    def check(run_data: dict) -> tuple[bool, str]:
        if stage in run_data.get("stages_visited", set()):
            return True, f"stage {stage} alcancado"
        return False, f"stage {stage} NAO alcancado"
    check.__name__ = f"reached_{stage}"
    return check


def visited_multiple_stages(min_count: int = 2):
    def check(run_data: dict) -> tuple[bool, str]:
        count = len(run_data.get("stages_visited", set()))
        if count >= min_count:
            return True, f"{count} stages visitados"
        return False, f"apenas {count} stage(s) visitado(s)"
    check.__name__ = f"visited_gte_{min_count}_stages"
    return check


def min_turns(n: int):
    def check(run_data: dict) -> tuple[bool, str]:
        turns = run_data.get("turns_count", 0)
        if turns >= n:
            return True, f"{turns} turnos (>= {n})"
        return False, f"apenas {turns} turno(s)"
    check.__name__ = f"min_{n}_turns"
    return check


def transcript_matches(pattern: str, description: str):
    import re
    compiled = re.compile(pattern, re.IGNORECASE)

    def check(run_data: dict) -> tuple[bool, str]:
        messages = run_data.get("messages", [])
        text = "\n".join(m.get("content", "") for m in messages)
        if compiled.search(text):
            return True, f"{description} (match)"
        return False, f"{description} (sem match)"
    check.__name__ = f"regex_{description}"
    return check


_A1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: dono de uma cafeteria pequena em Belo Horizonte. Tem 1 loja, compra cerca de 10kg/mes de um torrefador local, esta cogitando trocar de fornecedor.
Tom: direto, ocupado, portugues informal brasileiro. Erra acentos de vez em quando, frases curtas.
Comportamento:
- Pergunta preco logo no inicio
- Pergunta MOQ (pedido minimo) e entrega pra BH
- Aceita ver fotos dos produtos quando oferecerem (responde "pode mandar" ou similar)
- Pede amostra antes de fechar pedido grande
- Se convencido com precos e qualidade, confirma intencao de comprar ~10kg e pede pra fechar
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

A1 = Archetype(
    id="A1",
    slug="cafeteria-atacado",
    persona_prompt=_A1_PERSONA,
    first_message="oi, vi a mensagem. o que voces tem de cafe?",
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("enviar_foto"),
        transcript_matches(r"\d+\s*(kg|quilos?)", "mencao de volume em kg"),
    ],
)


_A2_PERSONA = """Voce esta interpretando um LEAD.

Papel: influenciador de cafe (15k seguidores) querendo lancar a propria marca de cafe em 2026.
Tom: entusiasmado, perguntas sobre branding, fala informal mas articulado.
Comportamento:
- Pergunta se a empresa faz marca propria (private label)
- Pergunta quantidade minima, prazo, custo de embalagem personalizada, uso do proprio design
- Quer detalhes do processo e contato com humano pra avancar

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A2 = Archetype(
    id="A2",
    slug="private-label",
    persona_prompt=_A2_PERSONA,
    first_message="voces fazem marca propria?",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
    ],
)


_A3_PERSONA = """Voce esta interpretando um LEAD com duplo interesse.

Papel: tem uma cafeteria ATIVA em operacao hoje (compra atacado) E quer lancar uma MARCA PROPRIA de cafe em 2027.
Tom: direto, profissional, quer explorar os dois lados numa conversa so.
Comportamento:
- Deixa claro que tem interesse nas DUAS coisas
- Insiste se a Valeria tentar focar so num
- Espera respostas que cubram ambos os modelos de negocio

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A3 = Archetype(
    id="A3",
    slug="multi-intent",
    persona_prompt=_A3_PERSONA,
    first_message="tenho uma cafeteria mas tambem penso em criar minha marca de cafe. da pra falar dos dois?",
    hard_checks=[
        visited_multiple_stages(2),
    ],
)


_A4_PERSONA = """Voce esta interpretando um LEAD cetico/objetor.

Papel: ja tem um fornecedor de cafe, esta curioso mas resistente.
Tom: seco, confronta, pede justificativas. Nao e grosseiro mas nao compra papinho.
Comportamento:
- Abre dizendo que ja tem fornecedor
- Menciona preco do fornecedor atual (inventa algo plausivel, R$ 35/kg)
- Pergunta diferencial, prazo, qualidade
- NAO fecha facil — tem que ser convencido com argumentos concretos

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A4 = Archetype(
    id="A4",
    slug="objetor-preco",
    persona_prompt=_A4_PERSONA,
    first_message="ja tenho fornecedor, mas me conta o que voces tem de diferente",
    hard_checks=[
        reached_stage("atacado"),
        min_turns(5),
    ],
)


_A5_PERSONA = """Voce esta interpretando um LEAD internacional.

Papel: brasileiro morando em Portugal, vai abrir uma cafeteria em Lisboa no segundo semestre de 2026. Quer importar cafe brasileiro.
Tom: cordial, perguntas sobre logistica internacional, portugues brasileiro.
Comportamento:
- Primeira mensagem deixa claro que e para CAFETERIA EM LISBOA (nao consumo pessoal)
- Pergunta sobre exportacao, prazos, documentacao
- Quer ser encaminhado pra alguem que entenda de exportacao

Responda APENAS com a proxima mensagem do lead (1-2 frases)."""

A5 = Archetype(
    id="A5",
    slug="exportacao",
    persona_prompt=_A5_PERSONA,
    first_message="vou abrir um cafe em Lisboa no segundo semestre. voces exportam?",
    hard_checks=[
        reached_stage("exportacao"),
        has_tool_call("encaminhar_humano"),
    ],
)


ALL_ARCHETYPES = [A1, A2, A3, A4, A5]
