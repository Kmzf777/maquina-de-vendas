"""Config-as-code das quatro cadências de follow-up do vendedor João.

Spec: docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md (§4 e §5).
Fonte dos números: a ata da reunião de 10/09/2026 (`Reuniao-Decisao-Funil-Joao.txt`),
com o timestamp citado em cada decisão abaixo.

Mesma FORMA de `follow_up/cadence.py` (a cadência da ValerIA): dataclass congelada +
tupla de toques, funções puras, zero I/O. Uma diferença, e é ela que justifica um
módulo separado:

    ValerIA  →  Touch.objective_prompt  (a janela de 24h está ABERTA: o texto sai do LLM)
    João     →  Touch.template_name     (o lead está em SILÊNCIO: só template aprovado sai)

Este módulo só DECLARA. Quem envia é o handler (Task J2); quem cria os jobs é o
agendador (Task J3); quem grava a sobreposição é a API (Task J4).

──────────────────────────────────────────────────────────────────────────────
AS QUATRO CADÊNCIAS
──────────────────────────────────────────────────────────────────────────────

  código        gatilho                            toques                ata
  ─────────────────────────────────────────────────────────────────────────────
  novo          2 dias na etapa `novo`             1                     01:07:10
  em_conversa   2 dias na etapa `respondeu`        7 em ~30 dias         41:02
  reposicao     45 dias em "Cliente Ativo"         4, de 15 em 15        26:35, 34:24
  em_atencao    90 dias sem comprar                1 a cada 3 dias       38:08, 41:12

Cada uma existe em DUAS LINHAS — Atacado e Private Label — porque o funil e o texto
do template diferem entre elas.

`offset` é contado a partir da MATRÍCULA (o instante em que o gatilho disparou), nunca
do toque anterior — é como `cadence.py` conta, e é o número que a tela edita. Por isso
"Em conversa" aparece aqui como 0/2/5/10/16/22/28 e não como o D+2/4/7/12/18/24/30 da
ata: aqueles são contados da ENTRADA na etapa, e o gatilho já consumiu os 2 primeiros
dias.

──────────────────────────────────────────────────────────────────────────────
DUAS DECISÕES QUE PARECEM ARBITRÁRIAS E NÃO SÃO
──────────────────────────────────────────────────────────────────────────────

1. **"Em atenção" não tem template, e isso é uma declaração.**
   Os 24 templates aprovados na Meta em 13/09/2026
   (`scripts/create_templates_esteiras_joao.py`) cobrem Novo (2), Em conversa (14) e
   Reposição (8) — a quarta cadência nasceu depois do lote e não tem texto aprovado.
   `template_name=None` é o que faz a trava de ativação (Task J4, "ligar exige
   template aprovado em todo toque") RECUSAR ligar "Em atenção". Inventar um nome de
   template aqui trocaria essa recusa por um envio que morre em runtime, no meio da
   cadência, sem ninguém olhando.

2. **O gatilho de "Em atenção" é a mesma etapa do de "Reposição".**
   A ata diz "90 dias que ele não compra" (38:08). Dias sem comprar são, no CRM, dias
   na coluna "Cliente Ativo" do funil de Reposição (key `novo`) — o card nasce ali
   quando a venda fecha. É a mesma etapa que "Reposição" vigia aos 45.
   CONSEQUÊNCIA, nomeada para quem for escrever o agendador (Task J3): um card no dia
   90 casa os DOIS gatilhos. No desenho antigo isso não acontecia porque a esteira
   movia o card para "Em atenção" ao terminar; o handler novo não move card nenhum.
   Enquanto "Em atenção" não tiver template ela não liga, então a sobreposição é
   inerte — mas ela precisa ser resolvida ANTES de alguém criar os templates.

──────────────────────────────────────────────────────────────────────────────
O BANCO SOBREPÕE, O CÓDIGO É A ORIGEM (ata 33:28)
──────────────────────────────────────────────────────────────────────────────

    "45 dias, mas opção do João editar o número de dias."

`supabase/migrations/20260918_followup_joao_config.sql` cria duas tabelas de
SOBREPOSIÇÃO, que nascem VAZIAS — e vazio significa "vale o código":

    followup_joao_toque     (cadencia, linha, toque) → dias, template_name
    followup_joao_cadencia   cadencia               → gatilho_dias, ativa

Quatro botões, e nada além disso. Adicionar ou remover TOQUE continua sendo mudança de
código: é o que impede a tela de virar builder de novo, que é o erro que este desenho
corrige. O lado do banco tem a mesma trava, num CHECK por cadência.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any, Mapping

# ── Linhas ─────────────────────────────────────────────────────────────────────
LINHA_ATACADO = "atacado"
LINHA_PRIVATE_LABEL = "private_label"
LINHAS: tuple[str, ...] = (LINHA_ATACADO, LINHA_PRIVATE_LABEL)

# ── Funis do João (UUIDs de produção, medidos em 10/09/2026) ───────────────────
# Mesma fonte de supabase/migrations/20260910_contrato_etapas_joao.sql, e a suíte
# cruza os dois: um dígito trocado apontaria a cadência para um funil que não é do
# João, e o sintoma em produção seria "a esteira não pega ninguém".
PIPELINE_ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PIPELINE_PRIVATE_LABEL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"
PIPELINE_REPOSICAO_ATACADO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"
PIPELINE_REPOSICAO_PRIVATE_LABEL = "9c027143-72f6-42d6-861f-a494ba5bbb4f"

# ── Respostas do lead (ata 41:40) ──────────────────────────────────────────────
RESPOSTA_ADIAR = "adiar"
RESPOSTA_OPTOUT = "optout"

# "Ainda tenho estoque" → adia 60 dias, SEM recomeçar a contagem.
ADIAMENTO_ESTOQUE = timedelta(days=60)

# O rótulo é literal da ata E literal dos templates aprovados, já normalizado
# (minúsculas, sem acento, sem pontuação) para bater com `_normalize_reply`. Um
# rótulo que não casa é um BOTÃO MORTO — o lead aperta e nada acontece, que foi
# exatamente o destino de "Nao atendo mais" e "Tirar dos contatos" em produção.
ROTULOS_ADIAMENTO: frozenset[str] = frozenset({"ainda tenho estoque"})


@dataclass(frozen=True)
class Touch:
    """Um toque. `template_name` é o que substitui o `objective_prompt` da ValerIA.

    - `sequence`  : 1..N, a chave do toque na tabela de sobreposição.
    - `offset`    : desde a MATRÍCULA (não desde o toque anterior).
    - `template_name`: nome do template APROVADO na Meta; `None` = ainda não existe
      texto aprovado, e a cadência não pode ser ligada enquanto for assim.
    - `aceita_adiamento`: o template deste toque traz o botão "Ainda tenho estoque".
      Não é decoração: é o que diz ao agendador (Task J3) que a resposta pode adiar
      em 60 dias em vez de cancelar. A suíte cruza este campo com os BOTÕES REAIS do
      template, para que ele nunca prometa um botão que não existe.
    """

    sequence: int
    offset: timedelta
    template_name: str | None
    aceita_adiamento: bool = False


@dataclass(frozen=True)
class Linha:
    """A metade da cadência que é específica de um funil."""

    linha: str
    pipeline_id: str
    touches: tuple[Touch, ...]


@dataclass(frozen=True)
class Cadencia:
    """Uma cadência inteira: o gatilho (comum às duas linhas) + as duas linhas.

    `ativa` é SEMPRE False no código (spec §7, "tudo nasce desligado"). Ligar é ato
    humano, gravado na tabela de sobreposição — nunca um redeploy. Medido em
    16/09/2026: no instante em que uma cadência liga, 888 cards ficam elegíveis.
    """

    codigo: str
    rotulo: str
    gatilho_stage_key: str
    gatilho_dias: int
    linhas: Mapping[str, Linha]
    # Só "Em atenção" repete: a ata pede "uma mensagem a cada três dias ATÉ ele falar
    # que não quer mais" (38:08) — uma cadência sem fim declarado. As outras três
    # terminam no último toque.
    repete_ultimo: bool = False
    ativa: bool = False

    @property
    def job_type(self) -> str:
        """O `job_type` destes jobs em `follow_up_jobs`.

        `follow_up_jobs` já é executor multi-tipo — `standard`, `ai_scheduled_return`,
        `ai_reengage`, `handoff_rescue`, `lp_welcome` — e o despacho por tipo é o
        ÚNICO ponto de contato entre o ramo do João e o caminho da ValerIA, que é o
        único follow-up que funciona em produção hoje (8.140 jobs na história).
        O prefixo `joao_` garante que nenhum job do João caia no handler dela.
        """
        return f"joao_{self.codigo}"


@dataclass(frozen=True)
class CadenciaResolvida:
    """A cadência DEPOIS da sobreposição do banco — o que o agendador consome."""

    codigo: str
    linha: str
    job_type: str
    pipeline_id: str
    gatilho_stage_key: str
    gatilho_dias: int
    ativa: bool
    repete_ultimo: bool
    touches: tuple[Touch, ...]

    @property
    def intervalo_repeticao(self) -> timedelta | None:
        """De quanto em quanto tempo o ÚLTIMO toque se repete, ou None se acaba.

        O intervalo é o próprio espaçamento do último toque — a diferença para o
        penúltimo, ou o próprio offset quando a cadência tem um toque só. É de
        propósito que ele NÃO seja um campo à parte: assim "a cada quantos dias" já é
        editável pelos mesmos `dias` do toque, sem abrir uma quinta coluna fora do que
        o spec §5 permite editar.

        Intervalo <= 0 devolve None: um zero gravado na tela faria o motor reenviar em
        laço. Parar a cadência é a falha segura; bombardear o cliente não é.
        """
        if not self.repete_ultimo or not self.touches:
            return None
        if len(self.touches) == 1:
            intervalo = self.touches[0].offset
        else:
            intervalo = self.touches[-1].offset - self.touches[-2].offset
        return intervalo if intervalo > timedelta(0) else None


# ═══════════════════════════════════════════════════════════════════════════════
# As cadências
# ═══════════════════════════════════════════════════════════════════════════════
def _toques(offsets_em_dias: tuple[int, ...], templates: tuple[str | None, ...],
            adiamento: tuple[int, ...] = ()) -> tuple[Touch, ...]:
    """Monta os toques de uma linha. `adiamento` lista as sequences com o botão."""
    return tuple(
        Touch(
            sequence=i,
            offset=timedelta(days=dias),
            template_name=template,
            aceita_adiamento=i in adiamento,
        )
        for i, (dias, template) in enumerate(zip(offsets_em_dias, templates), start=1)
    )


# ── "Novo" — 01:07:10, "é de dois dias". Um toque, e o card não se move. ───────
#
# Dois dias e não as "36 horas" que a ata também cita: `get_deals_stage_stagnant` é o
# único gatilho do sistema com as guardas completas (blacklist, número errado, conversa
# finalizada) e só entende dias inteiros (`p_stage_days int`). Ganhar 36h custaria um
# gatilho novo, sem essas guardas.
_NOVO = Cadencia(
    codigo="novo",
    rotulo="Novo",
    gatilho_stage_key="novo",
    gatilho_dias=2,
    linhas={
        LINHA_ATACADO: Linha(
            LINHA_ATACADO, PIPELINE_ATACADO,
            _toques((0,), ("joao_novo_atacado_t1",)),
        ),
        LINHA_PRIVATE_LABEL: Linha(
            LINHA_PRIVATE_LABEL, PIPELINE_PRIVATE_LABEL,
            _toques((0,), ("joao_novo_privatelabel_t1",)),
        ),
    },
)

# ── "Em conversa" — 41:02, "deve durar uns 30 dias". 7 toques. ────────────────
#
# A etapa é `respondeu`, não `em_conversa`: é a key que 20260910_contrato_etapas_joao
# atribuiu à coluna "Em conversa" (e que `advance_deal_on_reply` já procura).
# Arco dos 7 textos: dúvida → valor → prova social → tirar atrito → pergunta direta →
# motivo concreto → despedida digna.
_EM_CONVERSA_OFFSETS = (0, 2, 5, 10, 16, 22, 28)

_EM_CONVERSA = Cadencia(
    codigo="em_conversa",
    rotulo="Em conversa",
    gatilho_stage_key="respondeu",
    gatilho_dias=2,
    linhas={
        LINHA_ATACADO: Linha(
            LINHA_ATACADO, PIPELINE_ATACADO,
            _toques(_EM_CONVERSA_OFFSETS,
                    tuple(f"joao_conversa_atacado_t{n}" for n in range(1, 8))),
        ),
        LINHA_PRIVATE_LABEL: Linha(
            LINHA_PRIVATE_LABEL, PIPELINE_PRIVATE_LABEL,
            _toques(_EM_CONVERSA_OFFSETS,
                    tuple(f"joao_conversa_privatelabel_t{n}" for n in range(1, 8))),
        ),
    },
)

# ── "Reposição" — 34:24, "o dia 45 ele vai receber uma mensagem... de 15 em 15" ─
#
# DIVERGÊNCIA CONSCIENTE com a esteira que foi apagada: ela usava D+0/3/18/33 (um
# toque extra aos 3 dias, depois 15 em 15). A ata diz 15 em 15 a partir do primeiro,
# e a ata é a fonte. Os 4 templates são os mesmos; o que muda é o espaçamento.
#
# O público aqui é CLIENTE, não prospect: o botão de saída dos textos é "Parar
# mensagens" (e não "Não tenho interesse", que soaria a ruptura com quem já compra).
# Os dois são reconhecidos por `is_optout_reply`.
_REPOSICAO_OFFSETS = (0, 15, 30, 45)
# t1..t3 trazem "Ainda tenho estoque"; o t4 é a despedida ("vou parar de te chamar"),
# e não tem o que adiar.
_REPOSICAO_ADIAMENTO = (1, 2, 3)

_REPOSICAO = Cadencia(
    codigo="reposicao",
    rotulo="Reposição",
    # "Cliente Ativo" é a key `novo` do funil de Reposição — o card nasce ali quando a
    # venda fecha, então dias na etapa == dias desde a compra.
    gatilho_stage_key="novo",
    gatilho_dias=45,
    linhas={
        LINHA_ATACADO: Linha(
            LINHA_ATACADO, PIPELINE_REPOSICAO_ATACADO,
            _toques(_REPOSICAO_OFFSETS,
                    tuple(f"joao_reposicao_atacado_t{n}" for n in range(1, 5)),
                    _REPOSICAO_ADIAMENTO),
        ),
        LINHA_PRIVATE_LABEL: Linha(
            LINHA_PRIVATE_LABEL, PIPELINE_REPOSICAO_PRIVATE_LABEL,
            _toques(_REPOSICAO_OFFSETS,
                    tuple(f"joao_reposicao_privatelabel_t{n}" for n in range(1, 5)),
                    _REPOSICAO_ADIAMENTO),
        ),
    },
)

# ── "Em atenção" — 38:08, "uma mensagem a cada três dias até ele falar que não" ──
#
# UM toque que se repete (`repete_ultimo`), e o intervalo é o próprio offset dele: 3
# dias. Por isso o offset é 3 e não 0 — é ele que a tela edita quando o João quiser
# mudar "a cada quantos dias", e um offset 0 deixaria a repetição sem número.
#
# `template_name=None`: ver a decisão 1 no cabeçalho. `aceita_adiamento=True` porque
# 41:40 é literal sobre esta fase ("essa mensagem pode ser com o botão: ainda tenho
# estoque") — quem criar o template tem de incluir o botão, e a suíte cobra isso no
# instante em que o template aparecer.
_EM_ATENCAO = Cadencia(
    codigo="em_atencao",
    rotulo="Em atenção",
    gatilho_stage_key="novo",
    gatilho_dias=90,
    repete_ultimo=True,
    linhas={
        LINHA_ATACADO: Linha(
            LINHA_ATACADO, PIPELINE_REPOSICAO_ATACADO,
            _toques((3,), (None,), (1,)),
        ),
        LINHA_PRIVATE_LABEL: Linha(
            LINHA_PRIVATE_LABEL, PIPELINE_REPOSICAO_PRIVATE_LABEL,
            _toques((3,), (None,), (1,)),
        ),
    },
)

CADENCIAS: Mapping[str, Cadencia] = {
    c.codigo: c for c in (_NOVO, _EM_CONVERSA, _REPOSICAO, _EM_ATENCAO)
}

CODIGOS: tuple[str, ...] = tuple(CADENCIAS)

JOB_TYPES: frozenset[str] = frozenset(c.job_type for c in CADENCIAS.values())

_POR_JOB_TYPE: Mapping[str, Cadencia] = {c.job_type: c for c in CADENCIAS.values()}


def cadencia_por_job_type(job_type: str | None) -> Cadencia | None:
    """A cadência de um `job_type`, ou None se o tipo não é do João.

    O None importa: é ele que deixa o despacho perguntar "este job é meu?" sem ter de
    conhecer os cinco tipos que já existem.
    """
    return _POR_JOB_TYPE.get(job_type or "")


# ═══════════════════════════════════════════════════════════════════════════════
# A sobreposição do banco
# ═══════════════════════════════════════════════════════════════════════════════
#
# FORMA do `overrides` — é o contrato entre este módulo, a API (J4) e o agendador (J3):
#
#     {
#       "gatilho_dias": 60 | None,          # linha de followup_joao_cadencia
#       "ativa": True | False | None,
#       "toques": {                          # linhas de followup_joao_toque
#          1: {"dias": 3 | None, "template_name": "..." | None},
#          ...                               # chave = `toque` (int ou str)
#       },
#     }
#
# Regra única, e vale para todos os campos: AUSENTE ou None = vale o código. Nunca
# "apague o que o código diz" — sem isso, gravar só os dias apagaria o template.
def _toques_override(overrides: Mapping[str, Any] | None) -> dict[int, Mapping[str, Any]]:
    """Normaliza o bloco `toques`, tolerando chave em texto.

    O JSON que sobe do Postgres/PostgREST pode trazer a chave do toque como string;
    exigir int aqui faria a sobreposição ser silenciosamente ignorada — o pior modo de
    falha possível para uma tela de configuração.
    """
    if not overrides:
        return {}
    bruto = overrides.get("toques") or {}
    normalizado: dict[int, Mapping[str, Any]] = {}
    for chave, valor in bruto.items():
        try:
            sequence = int(chave)
        except (TypeError, ValueError):
            continue
        if isinstance(valor, Mapping):
            normalizado[sequence] = valor
    return normalizado


def resolver_cadencia(
    codigo: str, linha: str, overrides: Mapping[str, Any] | None = None,
) -> tuple[Touch, ...]:
    """Os toques de (cadência, linha) com a sobreposição do banco aplicada. PURA.

    Sem override, vale o código. Com override, vale o banco — toque a toque, campo a
    campo. Uma sequence que não existe na cadência é IGNORADA: a tabela sobrepõe, não
    acrescenta nem remove toque (spec §5). O banco tem a mesma trava, num CHECK.
    """
    do_codigo = CADENCIAS[codigo].linhas[linha].touches
    por_sequence = _toques_override(overrides)
    if not por_sequence:
        return do_codigo

    resolvidos = []
    for toque in do_codigo:
        override = por_sequence.get(toque.sequence) or {}
        mudancas: dict[str, Any] = {}
        dias = override.get("dias")
        if dias is not None:
            mudancas["offset"] = timedelta(days=dias)
        template = override.get("template_name")
        if template is not None:
            mudancas["template_name"] = template
        resolvidos.append(replace(toque, **mudancas) if mudancas else toque)
    return tuple(resolvidos)


def resolver(
    codigo: str, linha: str, overrides: Mapping[str, Any] | None = None,
) -> CadenciaResolvida:
    """A cadência inteira resolvida — o que o agendador (Task J3) consome. PURA."""
    cadencia = CADENCIAS[codigo]
    da_linha = cadencia.linhas[linha]
    overrides = overrides or {}

    gatilho_dias = overrides.get("gatilho_dias")
    ativa = overrides.get("ativa")
    return CadenciaResolvida(
        codigo=cadencia.codigo,
        linha=da_linha.linha,
        job_type=cadencia.job_type,
        pipeline_id=da_linha.pipeline_id,
        gatilho_stage_key=cadencia.gatilho_stage_key,
        gatilho_dias=cadencia.gatilho_dias if gatilho_dias is None else gatilho_dias,
        ativa=cadencia.ativa if ativa is None else bool(ativa),
        repete_ultimo=cadencia.repete_ultimo,
        touches=resolver_cadencia(codigo, linha, overrides),
    )


def toques_sem_template(
    codigo: str, linha: str, overrides: Mapping[str, Any] | None = None,
) -> tuple[int, ...]:
    """As sequences que ainda não têm template — vazio significa "pode ligar".

    É a metade que este módulo sabe responder da trava da Task J4 ("ligar exige
    template aprovado em todo toque"). A outra metade — se o template EXISTE e está
    APPROVED na Meta — é da API, que tem como perguntar.
    """
    return tuple(
        t.sequence
        for t in resolver_cadencia(codigo, linha, overrides)
        if not t.template_name
    )


def validar_toques(touches: tuple[Touch, ...]) -> tuple[str, ...]:
    """Os problemas de uma tupla de toques. Vazia = pode gravar. PURA.

    Existe para a API recusar ANTES de gravar: dias negativos, ou um toque marcado
    para antes do anterior. Ordem invertida não quebra nada visível no banco — ela
    aparece lá na frente, como o lead recebendo a despedida antes da oferta.
    """
    problemas: list[str] = []
    anterior: Touch | None = None
    for toque in touches:
        if toque.offset < timedelta(0):
            problemas.append(
                f"toque {toque.sequence}: dias não pode ser negativo "
                f"({toque.offset.days})"
            )
        if anterior is not None and toque.offset <= anterior.offset:
            problemas.append(
                f"toque {toque.sequence}: {toque.offset.days} dias não pode vir antes "
                f"do toque {anterior.sequence} ({anterior.offset.days} dias)"
            )
        anterior = toque
    return tuple(problemas)


# ═══════════════════════════════════════════════════════════════════════════════
# As duas regras de resposta da ata (41:40)
# ═══════════════════════════════════════════════════════════════════════════════
def classificar_resposta(texto: str | None) -> str | None:
    """`RESPOSTA_OPTOUT`, `RESPOSTA_ADIAR` ou None. PURA.

    As duas regras que a ata dá para a resposta do lead, e nada além delas:

      · botão de saída            → opt-out REAL (blacklist, não só "para de tocar")
      · botão "ainda tenho estoque" → adia `ADIAMENTO_ESTOQUE` (60 dias), sem recomeçar

    O opt-out é DELEGADO a `campaigns/worker.py::is_optout_reply`, a única autoridade
    sobre o que conta como botão de saída (frozenset de duas frases, igualdade
    normalizada). Uma segunda cópia da regra divergiria no primeiro dia — e o custo do
    desvio é um lead quente virar blacklist permanente, ou um "parar mensagens" que o
    sistema não honra.

    A comparação do adiamento é IGUALDADE normalizada pelo mesmo `_normalize_reply`,
    nunca substring: "ainda tenho estoque mas quero ver a tabela" é um lead QUENTE, e
    adiar 60 dias seria perdê-lo. O parser da Meta achata o clique de QUICK_REPLY em
    texto, então botão e digitação chegam aqui indistinguíveis — a igualdade é o que
    faz só a frase exata contar.

    Import tardio de propósito: mantém este módulo de configuração sem dependência de
    import sobre o de campanhas (e deixa o teste substituir a autoridade para provar
    que a delegação é real).
    """
    from app.campaigns.worker import _normalize_reply, is_optout_reply

    if is_optout_reply(texto):
        return RESPOSTA_OPTOUT
    if _normalize_reply(texto) in ROTULOS_ADIAMENTO:
        return RESPOSTA_ADIAR
    return None


def adiar_toques(
    touches: tuple[Touch, ...], *, ultimo_enviado: int,
    adiamento: timedelta = ADIAMENTO_ESTOQUE,
) -> tuple[Touch, ...]:
    """Os toques que AINDA NÃO saíram, cada um empurrado `adiamento` para a frente.

    A ata (41:40) pede duas coisas ao mesmo tempo, e a segunda é a que costuma se
    perder: adiar 60 dias, **sem recomeçar a contagem**. Recomeçar seria devolver a
    cadência inteira a partir do toque 1 — o lead que disse "ainda tenho estoque"
    receberia de novo o texto que já leu. Por isso os toques até `ultimo_enviado`
    simplesmente não voltam, e o espaçamento entre os que sobraram é preservado: o
    bloco inteiro desliza, ele não é reescrito.

    Função pura: a tupla de origem não é tocada (os `Touch` são congelados).
    """
    return tuple(
        replace(t, offset=t.offset + adiamento)
        for t in touches
        if t.sequence > ultimo_enviado
    )
