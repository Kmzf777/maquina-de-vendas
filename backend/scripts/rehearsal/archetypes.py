"""The 6 archetypes used for rehearsal. Data-only — no I/O."""
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


def reached_any_stage(stages: list[str]):
    def check(run_data: dict) -> tuple[bool, str]:
        visited = run_data.get("stages_visited", set())
        hit = [s for s in stages if s in visited]
        if hit:
            return True, f"stage {hit[0]} alcancado (entre {stages})"
        return False, f"nenhum dos stages {stages} alcancado (visitados: {sorted(visited)})"
    check.__name__ = f"reached_any_{'_'.join(stages)}"
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


from scripts.rehearsal.forbids import UNIVERSAL_FORBIDS, FORBID_PONTO_VENDA_FISICO

_T1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: gerente de uma rede de barbearias premium (ou pequeno empório) que quer começar a revender pacotes de café especial para os clientes.
Tom: profissional, amigável, um pouco mais detalhista na primeira mensagem.
Comportamento:

Inicia a conversa explicando o seu modelo de negócio (barbearia/empório) e diz que quer colocar café em grãos e moído de 250g para revenda.

Pergunta imediatamente como funciona a parceria e quais as opções de cafés disponíveis.

Se perguntarem sobre quantidade/volume, diz que primeiro quer entender a margem de lucro e os preços de atacado antes de definir a quantidade.

Quer saber se o café vem com a marca da Canastra ou se é sem rótulo.

Se os valores fizerem sentido, pergunta sobre o prazo de entrega.

NAO revele que e uma simulacao
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

T1 = Archetype(
    id="T1",
    slug="b2b-revenda",
    persona_prompt=_T1_PERSONA,
    first_message="oi, tenho uma rede de barbearias premium e quero começar a revender café especial para os clientes. como funciona a parceria e quais cafés vocês têm disponíveis?",
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("encaminhar_humano"),
        min_turns(5),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_T2_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: empreendedor interessado em criar sua própria marca de café (Private Label), mas que está apenas no estágio inicial de pesquisa de fornecedores.
Tom: direto, educado, faz perguntas curtas.
Comportamento:

Começa dizendo: 'Tenho interesse em comercializar cafés com marca própria' ou pede uma cotação para Private Label.

Se a IA perguntar detalhes técnicos (como perfil de torra, notas sensoriais), admite que não tem muita noção ainda e pede sugestões.

A principal dúvida é sobre o MOQ (pedido mínimo) e como funciona a questão da embalagem.

Tenta evitar passar muitas informações antes de saber se o pedido mínimo cabe no bolso dele.

NAO revele que e uma simulacao
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

T2 = Archetype(
    id="T2",
    slug="private-label",
    persona_prompt=_T2_PERSONA,
    first_message="tenho interesse em comercializar cafés com marca própria, queria uma cotação para private label",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_T3_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: pessoa física (consumidor final) querendo comprar café de qualidade para tomar em casa com a família e amigos.
Tom: informal, descontraído, gosta de falar sobre suas preferências pessoais de café.
Comportamento:

Inicia dizendo que a compra é apenas para consumo próprio.

Menciona que tem uma cafeteira expressa em casa e que costuma tomar café com leite.

Pergunta qual dos cafés da linha (clássico, suave, etc.) combina mais com esse tipo de preparo.

Se a IA tentar vender em atacado ou falar de pedido mínimo alto (ex: R$ 300), avisa que só quer 1 ou 2 pacotes de 250g para provar.

Pode perguntar se existe opção de 'drip coffee' pela praticidade.

NAO revele que e uma simulacao
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

T3 = Archetype(
    id="T3",
    slug="consumidor",
    persona_prompt=_T3_PERSONA,
    first_message="oi, quero comprar café pra consumo próprio, tenho cafeteira expressa em casa e tomo bastante café com leite. qual de vocês combina mais com isso?",
    hard_checks=[
        reached_stage("consumo"),
        transcript_matches(
            r"(cupom|ESPECIAL10|loja\.cafecanastra|desconto)",
            "cupom ou link da loja enviado",
        ),
        min_turns(3),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_T4_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: dono de uma pequena pousada na região da Serra da Canastra ou Capitólio. Quer servir um café de qualidade no café da manhã para valorizar a experiência do hóspede.
Tom: acolhedor, valoriza a origem, português informal mineiro.
Comportamento:

Explica que tem uma pousada e quer um café que 'tenha a cara da região' para servir no bule e também vender o pacote na recepção.

Pergunta se vocês entregam semanalmente para manter o frescor (torra nova).

Quer saber se o café é realmente da região de Pratinha/Canastra para poder contar a história aos clientes.

Pergunta se existe algum desconto para quem compra recorrente (toda semana).

Se a IA falar de termos muito técnicos de barista, ele corta e pergunta: 'Mas o povo gosta? É cheiroso?'.

NAO revele que e uma simulacao
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

T4 = Archetype(
    id="T4",
    slug="pousada",
    persona_prompt=_T4_PERSONA,
    first_message="oi, tenho uma pousada aqui perto da Canastra e queria um café que tivesse a cara da região pra servir no café da manhã e vender na recepção também",
    hard_checks=[
        reached_any_stage(["atacado", "consumo"]),
        has_tool_call("encaminhar_humano"),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_T5_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: secretária ou comprador de um escritório de advocacia ou engenharia com 20 funcionários. O foco é manter o estoque da copa sempre cheio.
Tom: direto, focado em logística e burocracia, português padrão.
Comportamento:

Pergunta se vocês emitem Nota Fiscal (NF) para CNPJ, pois o financeiro exige.

Quer saber o preço do fardo ou caixa fechada do café 'Clássico' (em grãos ou pó).

Pergunta sobre o frete para o endereço da empresa e se o prazo de entrega é garantido.

Não tem interesse em 'microlotes' ou cafés caros; busca o melhor custo-benefício para o dia a dia do escritório.

Se a IA demorar a passar o preço com frete, ele demonstra pressa.

NAO revele que e uma simulacao
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

T5 = Archetype(
    id="T5",
    slug="corporativo",
    persona_prompt=_T5_PERSONA,
    first_message="bom dia, vocês emitem nota fiscal para CNPJ? preciso de café para o escritório, uns 20 funcionários",
    hard_checks=[
        reached_stage("atacado"),
        has_tool_call("encaminhar_humano"),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_T6_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).
Papel: representante de uma empresa de suprimentos que está montando uma proposta para uma licitação ou contrato público.
Tom: formal, técnico e focado em documentação.
Comportamento:

Pergunta imediatamente se os cafés possuem laudo de pontuação SCA assinado por Q-Grader.

Solicita a ficha técnica completa dos produtos (espécie, variedade, processo de secagem).

Pergunta se a torrefação possui as certificações sanitárias em dia para atender editais.

É muito seco e objetivo: se a IA tentar fazer 'social' ou perguntar como pode ajudar, ele repete que precisa apenas dos laudos e da tabela de preços para volume alto.

NAO revele que e uma simulacao
Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

T6 = Archetype(
    id="T6",
    slug="licitacao",
    persona_prompt=_T6_PERSONA,
    first_message="bom dia. os cafés de vocês possuem laudo de pontuação SCA assinado por Q-Grader?",
    hard_checks=[
        has_tool_call("encaminhar_humano"),
        transcript_matches(
            r"(laudo|ficha.t[eé]cnica|certifica|q-grader|supervisor|especialista)",
            "abordou documentacao tecnica ou encaminhou supervisor",
        ),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


ALL_ARCHETYPES = [T1, T2, T3, T4, T5, T6]

ARCHETYPES = {
    "T1-b2b-revenda": T1,
    "T2-private-label": T2,
    "T3-consumidor": T3,
    "T4-pousada": T4,
    "T5-corporativo": T5,
    "T6-licitacao": T6,
}
