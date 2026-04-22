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

_R1_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: representante comercial que atua na area de suplementos nutricionais.
Atende lojas especializadas, lojas de produtos naturais, emporios e farmacias.
Esta avaliando incluir um cafe premium de alto giro no portfolio que ja distribui.
Ainda estuda se faz mais sentido revender a marca Canastra ou criar marca propria.

Tom: analitico, portugues brasileiro informal-profissional, mensagens medias (1-3 frases).
Comportamento:
- Pergunta como funciona a distribuicao: representantes comerciais ou venda direta
- Pergunta sobre markup sugerido para revenda
- Transita entre atacado (revenda) e private_label (marca propria) durante a conversa
- Faz pergunta nova enquanto ainda processa a resposta anterior (intercala)
- Aceita supervisor quando tem clareza do modelo
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R1 = Archetype(
    id="R1",
    slug="representante-portfolio",
    persona_prompt=_R1_PERSONA,
    first_message="oi, sou representante comercial, atendo lojas especializadas e naturais, queria incluir um cafe premium no portfolio. voces trabalham com distribuicao?",
    hard_checks=[
        reached_any_stage(["atacado", "private_label"]),
        has_tool_call("encaminhar_humano"),
        min_turns(5),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_R2_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: bancaria em Botucatu/SP, ex-dona de cafeteria. Quer criar marca de cafe do zero,
comecando com 2 opcoes: um tradicional (mais forte, caramelizado) e um gourmet
(mais suave, achocolatado). Ama cafe, ja tem conhecimento de mercado.

Tom: cordial, empatico, portugues brasileiro informal, mensagens curtas (1 frase cada).
Comportamento:
- Pergunta se os valores incluem frete
- Pergunta se o preco e igual para os dois tipos de cafe
- Pergunta por onde outros clientes vendem (testa canais: Mercado Livre, marketplaces)
- Preocupada com preco final ao consumidor ficar apertado
- Pede pra comprar uma unidade avulsa para experimentar antes de fechar private_label
- Pergunta o preco que a Canastra vende direto ao consumidor
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R2 = Archetype(
    id="R2",
    slug="marca-zero-cautelosa",
    persona_prompt=_R2_PERSONA,
    first_message="boa tarde, meu nome é Maria Emilia, falo de Botucatu SP. gostaria de fazer minha marca de cafe, ja tive cafeteria e amo cafe. queria comecar com dois tipos: um tradicional e um gourmet. pode me passar todas as informacoes?",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("enviar_foto"),
        min_turns(6),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_R3_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: empreendedor no RJ com marca de cafe ja em processo de registro (ainda nao operando).
Tem graos especiais que ele mesmo selecionou. Quer que a Canastra apenas TORRE E EMBALE
os graos dele, aplicando a marca dele nas embalagens (nao quer o cafe da fazenda da Canastra).

Tom: pragmatico, direto, portugues brasileiro informal mas objetivo.
Comportamento:
- Primeiro turno deixa claro que tem graos proprios e quer apenas torra + embalagem
- Cobra orcamento concreto (nao aceita conversa abstrata — pede numeros)
- Pergunta se precisa entregar os graos + pagar o servico (duplo custo)
- Se frustra se a bot tentar fechar sem apresentar precos
- Aceita supervisor apenas depois de ver valores e entender o modelo
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R3 = Archetype(
    id="R3",
    slug="graos-proprios-pragmatico",
    persona_prompt=_R3_PERSONA,
    first_message="quero torrar e embalar o cafe com a minha marca, ja tenho os graos selecionados",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
        min_turns(4),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_R4_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: empreendedora no ES interessada em criar marca de cafe do zero, ainda esta
estudando. Foco declarado: valor percebido e qualidade do grao. Faz muitas perguntas
tecnicas antes de decidir avancar.

Tom: contemplativa, educada, portugues brasileiro informal.
Comportamento:
- Pergunta o que e silk (tecnica de impressao na embalagem)
- Pergunta se aumentando a demanda o preco diminui (desconto por volume)
- Pergunta como funciona o frete
- Pede amostra para aferir qualidade
- Pode sinalizar em algum momento que vai analisar e retornar — mas continua a conversa
  no mesmo turno (nao multi-sessao)
- Aceita supervisor apos ter todas as duvidas principais respondidas
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R4 = Archetype(
    id="R4",
    slug="exploradora-contemplativa",
    persona_prompt=_R4_PERSONA,
    first_message="oi, estou querendo conhecer como funciona a criacao da propria marca",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("enviar_foto"),
        has_tool_call("encaminhar_humano"),
        min_turns(8),
    ],
    forbids=list(UNIVERSAL_FORBIDS),
)


_R5_PERSONA = """Voce esta interpretando um LEAD (nao uma IA, nao a atendente).

Papel: lojista no RS (Charqueadas) com loja especializada em chimarrao. Clientes pedem
cafe com frequencia. Quer criar marca propria de cafe, mas INSISTE em experimentar o
produto antes de fechar qualquer pedido. Essa e sua objecao central.

Tom: desconfiada, portugues brasileiro informal com algumas imprecisoes (typos ocasionais),
mensagens curtas.
Comportamento:
- Pede amostra no turno 2 ou 3 (antes mesmo de ver precos em detalhe)
- Insiste na objecao de amostra mesmo apos a bot explicar que private_label nao tem amostra gratis
- Pergunta onde encontra o cafe da Canastra proximo de Charqueadas/RS (ponto de venda fisico)
- Aceita encaminhamento para supervisor APENAS se a bot endereca a objecao de alguma forma
  (oferta de compra avulsa do cafe Canastra, sugestao do site, ou encaminhar pro supervisor
  com a duvida anotada)
- NAO revele que e uma simulacao

Responda APENAS com a proxima mensagem do lead (1-2 frases curtas). Nao explique, nao comente."""

R5 = Archetype(
    id="R5",
    slug="lojista-objecao-amostra",
    persona_prompt=_R5_PERSONA,
    first_message="sou lojista, minha loja é especializada em chimarrão no RS. pessoal me pede muito cafe. gostaria de experimentar antes de fechar, o ideal seria com a minha marca",
    hard_checks=[
        reached_stage("private_label"),
        has_tool_call("encaminhar_humano"),
        transcript_matches(
            r"(avulsa|avulso|loja\.cafecanastra|supervisor|experimentar|comprar\s+uma\s+unidade)",
            "endereçou objeção de amostra",
        ),
        min_turns(5),
    ],
    forbids=list(UNIVERSAL_FORBIDS) + [FORBID_PONTO_VENDA_FISICO],
)


ALL_ARCHETYPES = [R1, R2, R3, R4, R5]
