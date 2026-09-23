"""Config-as-code das cadências de follow-up do vendedor João, por FUNIL.

Spec: docs/superpowers/specs/2026-09-21-followup-funil-por-funil-design.md (a forma
deste módulo — funil como eixo) e
docs/superpowers/specs/2026-09-18-motor-followup-joao-design.md (§4 e §5, a fonte dos
NÚMEROS — dias, toques, templates — que NÃO mudam entre os dois specs). Fonte dos
números: a ata da reunião de 10/09/2026 (`Reuniao-Decisao-Funil-Joao.txt`), com o
timestamp citado em cada decisão abaixo.

Mesma FORMA de `follow_up/cadence.py` (a cadência da ValerIA): dataclass congelada +
tupla de toques, funções puras, zero I/O. Uma diferença, e é ela que justifica um
módulo separado:

    ValerIA  →  Touch.objective_prompt  (a janela de 24h está ABERTA: o texto sai do LLM)
    João     →  Touch.template_name     (o lead está em SILÊNCIO: só template aprovado sai)

Este módulo só DECLARA. Quem envia é o handler dos jobs; quem cria os jobs é o
agendador (`service.py`); quem grava a sobreposição é a API (`api.py`).

──────────────────────────────────────────────────────────────────────────────
FUNIL É O EIXO, CADÊNCIA É O QUE EXISTE DENTRO DELE
──────────────────────────────────────────────────────────────────────────────

Cinco funis. Quatro têm cadência; o quinto é espaço reservado:

  funil                            pipeline_id (produção, 10/09/2026)   cadências
  ──────────────────────────────────────────────────────────────────────────────
  João - Atacado                   9706a14a-3d9a-...    Novo, Em conversa, Proposta Enviada
  João - Private Label             24fb6ce8-6b7b-...    Novo, Em conversa, Proposta Enviada
  João - Reposição Atacado         79e35e6b-01d1-...    Reposição, Em atenção
  João - Reposição Private Label   9c027143-72f6-...    Reposição, Em atenção
  João - Recuperação               fa94029b-d524-...    (nenhuma — de propósito)

Cada CÓDIGO de cadência (`novo`, `em_conversa`, `proposta`, `reposicao`,
`em_atencao`) existe em
DOIS funis-irmãos (Atacado/Private Label, ou Reposição Atacado/Reposição Private
Label) — mas cada ocorrência é um objeto `Cadencia` PRÓPRIO, com sua PRÓPRIA tupla de
`touches` (templates diferentes). Não existe mais um mapa achatado só por código: antes
existia (`CADENCIAS: Mapping[str, Cadencia]`) e era o bug — a MESMA string "atacado"
apontava para pipelines DIFERENTES dependendo de qual cadência estava por cima (spec
2026-09-21 §1). Agora o funil é sempre a primeira metade da chave — `resolver(funil,
codigo, overrides)`, funil primeiro.

  código        gatilho                                 toques              fonte
  ─────────────────────────────────────────────────────────────────────────────────
  novo          2 dias em `novo` E 2 de silêncio        3: 0, 2, 4          23/09 §1
  em_conversa   2 dias em `respondeu` E 2 de silêncio   4: 0, 2, 4, 9       23/09 §1
  proposta      1 dia em `proposta_enviada`             4: 0, 1, 4, 8       23/09 §1
  reposicao     45 dias em "Cliente Ativo"              4, de 15 em 15      ata 26:35, 34:24
  em_atencao    90 dias sem comprar                     1 a cada 3 dias     ata 38:08, 41:12

`offset` é contado a partir da MATRÍCULA (o instante em que o gatilho disparou), nunca
do toque anterior — é como `cadence.py` conta, e é o número que a tela edita. O gatilho
já consumiu os dias de espera, então o toque 1 de toda cadência é sempre o dia 0.

As três primeiras são as cadências de PROSPECÇÃO, reformuladas em 23/09/2026
(`docs/superpowers/specs/2026-09-23-esteiras-joao-v2-design.md`). Elas eram duas
(Novo com 1 toque, Em conversa com 7 ao longo de ~30 dias) e viraram três, mais curtas
e com uma saída explícita para quem nunca responde (decisão 5 abaixo). As duas de
Reposição NÃO foram tocadas — os números delas continuam sendo os da ata de 10/09/2026.

──────────────────────────────────────────────────────────────────────────────
CINCO DECISÕES QUE PARECEM ARBITRÁRIAS E NÃO SÃO
──────────────────────────────────────────────────────────────────────────────

1. **"Em atenção" não tem template, e isso é uma declaração.**
   Os 24 templates aprovados na Meta em 13/09/2026
   (`scripts/create_templates_esteiras_joao.py`) cobrem Novo (2), Em conversa (14) e
   Reposição (8) — a quarta cadência nasceu depois do lote e não tem texto aprovado.
   `template_name=None` é o que faz a trava de ativação (API, "ligar exige template
   aprovado em todo toque") RECUSAR ligar "Em atenção". Inventar um nome de template
   aqui trocaria essa recusa por um envio que morre em runtime, no meio da cadência,
   sem ninguém olhando.

2. **O gatilho de "Em atenção" é a mesma etapa do de "Reposição" — e o RÓTULO desse
   gatilho é "Cliente Ativo", nunca "Em atenção".**
   A ata diz "90 dias que ele não compra" (38:08). Dias sem comprar são, no CRM, dias
   na coluna "Cliente Ativo" do funil de Reposição (key `novo`; label real em
   `pipeline_stages`, confirmado em `20260910_contrato_etapas_joao.sql:131`) — o card
   nasce ali quando a venda fecha. É a MESMA etapa que "Reposição" vigia aos 45 dias.
   As duas cadências (`reposicao` e `em_atencao`) moram no MESMO par de funis
   (Reposição Atacado / Reposição Private Label) e apontam para o MESMO
   `gatilho_stage_key="novo"` / `gatilho_stage_rotulo="Cliente Ativo"`.
   Existe também, nos quatro funis, uma etapa DE VERDADE chamada `em_atencao` / "Em
   atenção" — a cadência "Em atenção" NÃO a vigia. Usar o nome da cadência como se
   fosse o nome da etapa reintroduziria a mesma classe de confusão que a mudança para
   funil-primeiro corrige (spec 2026-09-21 §2, "Armadilha a evitar").
   CONSEQUÊNCIA, nomeada para quem lê o agendador (`service.py`): um card no dia 90
   casa os DOIS gatilhos. Enquanto "Em atenção" não tiver template ela não liga, então
   a sobreposição é inerte — mas precisa ser resolvida antes de alguém criar os
   templates.

3. **João - Recuperação existe no código, sem cadência nenhuma.**
   É um funil manual do vendedor (Entrada de Inativos → Em Follow-UP → Recuperado →
   Perdido Churn) que este motor ainda não sabe operar. `cadencias=()` é deliberado —
   não é um TODO, é o estado real: zero gatilho, zero toque, pronto para ganhar uma
   cadência quando alguém definir os dois (spec 2026-09-21 §1).

4. **TODOS os toques de Novo, Em conversa e Proposta Enviada nascem SEM template —
   inclusive os que já tinham um APROVADO na Meta. NÃO "conserte" isto.**
   É decisão explícita do dono do funil em 23/09/2026 (spec 2026-09-23 §2): os textos
   das três cadências passam a ser preenchidos pela TELA, sem deploy. Os 16 templates
   que este arquivo referenciava até ontem (`joao_novo_atacado_t1`,
   `joao_novo_privatelabel_t1` e os 14 `joao_conversa_*`) continuam aprovados na Meta
   e ficaram DESCONECTADOS de propósito: a forma da cadência mudou (7 toques viraram
   4), e escolher quais 4 dos 7 sobreviveriam seria uma decisão de TEXTO tomada por
   quem não escreve o texto.
   Consequência, e ela é o ponto: **nenhuma das três pode ser ligada** enquanto
   ninguém preencher os textos — é a mesma trava de "Em atenção" da decisão 1, agora
   valendo para as cinco cadências menos `reposicao`. A recusa é o comportamento
   desejado, não um bug a corrigir reconectando os nomes antigos.
   Os 8 templates de Reposição (`joao_reposicao_*`) seguem conectados: aquela cadência
   não mudou.

5. **As três cadências de prospecção MOVEM o card no fim — e é a única exceção ao
   "o motor nunca move card" do spec de 18/09.**
   Passado o último toque, se o lead nunca respondeu, o card vai para a etapa
   `em_atencao` ("Em atenção") — que existe nos quatro funis com cadência
   (`20260910_contrato_etapas_joao.sql:146`). Aqui isto é só DECLARAÇÃO: os campos
   `etapa_final_key`, `etapa_final_rotulo` e `dias_ate_mover` dizem o quê e quando;
   quem cria o job de mover é o agendador (`service.py`) e quem o executa é o handler.
   Cuidado com a ambiguidade de nome, irmã da decisão 2: `em_atencao` é, ao mesmo
   tempo, o código de uma CADÊNCIA (a dos funis de Reposição) e a key de uma ETAPA
   (nos funis de prospecção). `etapa_final_key` é sempre a ETAPA — as cadências de
   Reposição têm `etapa_final_key=None` e não movem card nenhum.

──────────────────────────────────────────────────────────────────────────────
O BANCO SOBREPÕE, O CÓDIGO É A ORIGEM (ata 33:28)
──────────────────────────────────────────────────────────────────────────────

    "45 dias, mas opção do João editar o número de dias."

`supabase/migrations/20260918_followup_joao_config.sql` cria duas tabelas de
SOBREPOSIÇÃO, que nascem VAZIAS — e vazio significa "vale o código":

    followup_joao_toque      (funil, cadencia, toque) → dias, template_name
    followup_joao_cadencia   (funil, cadencia)         → gatilho_dias, ativa

Cada FUNIL tem seu próprio liga/desliga e seu próprio prazo de gatilho — Atacado e
Private Label deixaram de estar acoplados (spec 2026-09-21 §2, decisão 1): ligar só
metade não é mais uma alavanca escondida, é o comportamento normal de duas chaves
independentes.

Adicionar ou remover TOQUE continua sendo mudança de código: é o que impede a tela de
virar builder de novo, que é o erro que este desenho corrige. O lado do banco tem a
mesma trava, num CHECK por (funil, cadência).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Mapping

# ── Funis do João (UUIDs de produção, medidos em 10/09/2026) ───────────────────
# Mesma fonte de supabase/migrations/20260910_contrato_etapas_joao.sql, e a suíte
# cruza os dois: um dígito trocado apontaria a cadência para um funil que não é do
# João, e o sintoma em produção seria "a esteira não pega ninguém".
PIPELINE_ATACADO = "9706a14a-3d9a-413b-bceb-26838fc2cc45"
PIPELINE_PRIVATE_LABEL = "24fb6ce8-6b7b-4612-970d-8debb8c041b7"
PIPELINE_REPOSICAO_ATACADO = "79e35e6b-01d1-482a-bdf0-64c733ff1ca4"
PIPELINE_REPOSICAO_PRIVATE_LABEL = "9c027143-72f6-42d6-861f-a494ba5bbb4f"
# João - Recuperação: funil manual do vendedor (Entrada de Inativos → Em Follow-UP →
# Recuperado → Perdido Churn). Entra nesta versão só como espaço reservado — zero
# cadência (ver FUNIS abaixo) — pronto para ganhar uma quando alguém definir o gatilho
# e os toques (spec 2026-09-21 §1). Mesma fonte das quatro constantes acima.
PIPELINE_RECUPERACAO = "fa94029b-d524-4550-919e-67233dfe3a94"

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
      Não é decoração: é o que diz ao agendador (`service.py`) que a resposta pode
      adiar em 60 dias em vez de cancelar. A suíte cruza este campo com os BOTÕES
      REAIS do template, para que ele nunca prometa um botão que não existe.
    """

    sequence: int
    offset: timedelta
    template_name: str | None
    aceita_adiamento: bool = False


@dataclass(frozen=True)
class Cadencia:
    """Uma cadência DENTRO de um funil (antes vivia sozinha, com duas "linhas").

    `ativa` é SEMPRE False no código (spec §7 do design de 18/09, "tudo nasce
    desligado"). Ligar é ato humano, gravado na tabela de sobreposição — nunca um
    redeploy. Medido em 16/09/2026: no instante em que uma cadência liga, 888 cards
    ficam elegíveis.
    """

    codigo: str
    rotulo: str
    gatilho_stage_key: str
    # O nome da etapa que o gatilho vigia — hardcoded aqui, nunca lido do banco
    # (`pipeline_stages.label` é editável por qualquer operador no CRM e não é
    # contrato estável). Ver a decisão 2 no cabeçalho: para "Em atenção" isto TEM que
    # ser "Cliente Ativo", nunca "Em atenção".
    gatilho_stage_rotulo: str
    gatilho_dias: int
    touches: tuple[Touch, ...]
    # O SEGUNDO relógio do gatilho, e ele é um AND com `gatilho_dias`: dias sem
    # NENHUMA conversa (`p_silence_days` da RPC `get_deals_stage_stagnant`; 0 desliga
    # o filtro). O dono escreveu "2 dias sem conversar" para Novo e Em conversa
    # (spec 2026-09-23 §5); Proposta Enviada dispara só por tempo de etapa ("24h
    # depois"), e as duas de Reposição também — o relógio delas é mesmo o da etapa
    # ("45 dias em Cliente Ativo"). Por isso o default é 0: ele preserva exatamente o
    # que as cadências de Reposição já faziam.
    gatilho_silencio_dias: int = 0
    # Para onde o card vai quando a cadência termina sem o lead responder, e quanto
    # tempo depois do ÚLTIMO toque (decisão 5 no cabeçalho). `None` = esta cadência
    # não move card — o comportamento de sempre, e o das duas de Reposição.
    # O rótulo é hardcoded aqui pelo mesmo motivo de `gatilho_stage_rotulo`:
    # `pipeline_stages.label` é editável por qualquer operador do CRM.
    etapa_final_key: str | None = None
    etapa_final_rotulo: str | None = None
    dias_ate_mover: int = 1
    # Só "Em atenção" repete: a ata pede "uma mensagem a cada três dias ATÉ ele falar
    # que não quer mais" (38:08) — uma cadência sem fim declarado. As outras
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

        Continua ambíguo entre funis-irmãos que compartilham código (ex. os dois
        funis de Reposição compartilham `job_type="joao_reposicao"`) — é assim desde
        sempre (Atacado e Private Label já compartilhavam `joao_novo`). Quem resolve
        o funil certo é o `metadata` do job, nunca o `job_type` sozinho.
        """
        return f"joao_{self.codigo}"


@dataclass(frozen=True)
class Funil:
    """Um funil do João — a entidade de topo (spec 2026-09-21 §2/§3).

    Identificado pelo `pipeline_id` (o mesmo contrato estável que `PIPELINE_ATACADO`
    etc. já usam), não pelo nome digitável na tela do CRM. `cadencias` é `()` para
    "recuperacao" — vazio de propósito, não ausência de dado.
    """

    codigo: str
    rotulo: str
    pipeline_id: str
    cadencias: tuple[Cadencia, ...]


@dataclass(frozen=True)
class CadenciaResolvida:
    """A cadência DEPOIS da sobreposição do banco — o que o agendador consome."""

    codigo: str
    funil: str
    job_type: str
    pipeline_id: str
    gatilho_stage_key: str
    gatilho_stage_rotulo: str
    gatilho_dias: int
    ativa: bool
    repete_ultimo: bool
    touches: tuple[Touch, ...]
    # Os quatro campos de 23/09/2026. Não são sobrepostos pelo banco nesta entrega
    # (spec §5: "o de silêncio fica só no código"; a tela MOSTRA os dois números e
    # edita só o de etapa) — vêm direto da `Cadencia`. Ficam aqui porque o agendador
    # consome a RESOLVIDA e não deve ter que voltar ao código para buscá-los.
    gatilho_silencio_dias: int = 0
    etapa_final_key: str | None = None
    etapa_final_rotulo: str | None = None
    dias_ate_mover: int = 1

    @property
    def intervalo_repeticao(self) -> timedelta | None:
        """De quanto em quanto tempo o ÚLTIMO toque se repete, ou None se acaba.

        O intervalo é o próprio espaçamento do último toque — a diferença para o
        penúltimo, ou o próprio offset quando a cadência tem um toque só. É de
        propósito que ele NÃO seja um campo à parte: assim "a cada quantos dias" já é
        editável pelos mesmos `dias` do toque, sem abrir uma quinta coluna fora do que
        o spec permite editar.

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
# Os funis e suas cadências
# ═══════════════════════════════════════════════════════════════════════════════
def _toques(offsets_em_dias: tuple[int, ...], templates: tuple[str | None, ...],
            adiamento: tuple[int, ...] = ()) -> tuple[Touch, ...]:
    """Monta os toques de uma cadência. `adiamento` lista as sequences com o botão."""
    return tuple(
        Touch(
            sequence=i,
            offset=timedelta(days=dias),
            template_name=template,
            aceita_adiamento=i in adiamento,
        )
        for i, (dias, template) in enumerate(zip(offsets_em_dias, templates), start=1)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# As TRÊS cadências de prospecção (spec 2026-09-23) — Atacado e Private Label
# ═══════════════════════════════════════════════════════════════════════════════
#
# A etapa de destino das três, e o prazo. "Em atenção" aqui é ETAPA, nunca o código da
# cadência de mesmo nome que vive nos funis de Reposição (decisão 5 no cabeçalho).
ETAPA_FINAL_KEY = "em_atencao"
ETAPA_FINAL_ROTULO = "Em atenção"
DIAS_ATE_MOVER = 1


def _cadencia_de_prospeccao(
    *,
    codigo: str,
    rotulo: str,
    gatilho_stage_key: str,
    gatilho_stage_rotulo: str,
    gatilho_dias: int,
    gatilho_silencio_dias: int,
    offsets: tuple[int, ...],
) -> Cadencia:
    """Uma das três cadências de prospecção, SEM template em nenhum toque.

    ⚠️  `template_name=None` em TODOS os toques é deliberado (decisão 4 no cabeçalho,
    spec 2026-09-23 §2). Não é esquecimento e não há o que reconectar: os 16 templates
    que estas cadências usavam até 22/09/2026 seguem aprovados na Meta e foram
    DESCONECTADOS por decisão do dono do funil — os textos passam a ser preenchidos
    pela tela, sem deploy. Enquanto ninguém preencher, `toques_sem_template` devolve
    todas as sequences e a API RECUSA ligar as três. Essa recusa é o efeito desejado.

    A fábrica existe porque, sem template, Atacado e Private Label ficaram idênticas —
    era o nome do template a única coisa que as distinguia. Continuam sendo objetos
    `Cadencia` SEPARADOS, um por funil (a forma funil-primeiro do spec 2026-09-21), e
    cada funil segue com seu próprio liga/desliga e sua própria linha de sobreposição.
    """
    return Cadencia(
        codigo=codigo,
        rotulo=rotulo,
        gatilho_stage_key=gatilho_stage_key,
        gatilho_stage_rotulo=gatilho_stage_rotulo,
        gatilho_dias=gatilho_dias,
        gatilho_silencio_dias=gatilho_silencio_dias,
        touches=_toques(offsets, (None,) * len(offsets)),
        etapa_final_key=ETAPA_FINAL_KEY,
        etapa_final_rotulo=ETAPA_FINAL_ROTULO,
        dias_ate_mover=DIAS_ATE_MOVER,
    )


# ── "Novo" — 3 toques nos dias 0, 2 e 4 (spec 2026-09-23 §1) ──────────────────
#
# Dois dias na etapa E dois dias de silêncio, em AND. Dois dias e não as "36 horas"
# que a ata de 10/09 também citava: `get_deals_stage_stagnant` é o único gatilho do
# sistema com as guardas completas (blacklist, número errado, conversa finalizada) e só
# entende dias inteiros (`p_stage_days int`). Ganhar 36h custaria um gatilho novo, sem
# essas guardas.
#
# Era UM toque até 22/09/2026. Se o lead responder no meio, `advance_deal_on_reply`
# tira o card de "Novo" sozinho e "Em conversa" assume — as duas esteiras se emendam,
# em vez de a primeira se repetir (spec 2026-09-23 §4).
_NOVO_OFFSETS = (0, 2, 4)

_NOVO_ATACADO = _cadencia_de_prospeccao(
    codigo="novo", rotulo="Novo",
    gatilho_stage_key="novo", gatilho_stage_rotulo="Novo",
    gatilho_dias=2, gatilho_silencio_dias=2, offsets=_NOVO_OFFSETS,
)
_NOVO_PRIVATE_LABEL = _cadencia_de_prospeccao(
    codigo="novo", rotulo="Novo",
    gatilho_stage_key="novo", gatilho_stage_rotulo="Novo",
    gatilho_dias=2, gatilho_silencio_dias=2, offsets=_NOVO_OFFSETS,
)

# ── "Em conversa" — 4 toques nos dias 0, 2, 4 e 9 (spec 2026-09-23 §1) ────────
#
# Eram 7 toques ao longo de ~30 dias (0/2/5/10/16/22/28) até 22/09/2026. O dono pediu
# mais curta: quatro toques e uma saída em 10 dias.
#
# A etapa é `respondeu`, não `em_conversa`: é a key que 20260910_contrato_etapas_joao
# atribuiu à coluna "Em conversa" (e que `advance_deal_on_reply` já procura).
_EM_CONVERSA_OFFSETS = (0, 2, 4, 9)

_EM_CONVERSA_ATACADO = _cadencia_de_prospeccao(
    codigo="em_conversa", rotulo="Em conversa",
    gatilho_stage_key="respondeu", gatilho_stage_rotulo="Em conversa",
    gatilho_dias=2, gatilho_silencio_dias=2, offsets=_EM_CONVERSA_OFFSETS,
)
_EM_CONVERSA_PRIVATE_LABEL = _cadencia_de_prospeccao(
    codigo="em_conversa", rotulo="Em conversa",
    gatilho_stage_key="respondeu", gatilho_stage_rotulo="Em conversa",
    gatilho_dias=2, gatilho_silencio_dias=2, offsets=_EM_CONVERSA_OFFSETS,
)

# ── "Proposta Enviada" — NOVA, 4 toques nos dias 0, 1, 4 e 8 ──────────────────
#
# A única das três que dispara SÓ por tempo de etapa: `gatilho_silencio_dias=0`. O dono
# escreveu "24h depois" da proposta, e não "24h sem conversar" (spec 2026-09-23 §5) —
# a proposta recém-enviada é justamente o momento em que houve conversa, e exigir
# silêncio calaria a cadência inteira.
#
# O card chega à etapa `proposta_enviada` sozinho, quando a proposta é criada no
# /orcamento (`quotes/router.py`). E não precisa de regra para "só se não fechou": um
# card que virou Fechado Ganho não está mais na etapa que esta cadência vigia.
_PROPOSTA_OFFSETS = (0, 1, 4, 8)

_PROPOSTA_ATACADO = _cadencia_de_prospeccao(
    codigo="proposta", rotulo="Proposta Enviada",
    gatilho_stage_key="proposta_enviada", gatilho_stage_rotulo="Proposta Enviada",
    gatilho_dias=1, gatilho_silencio_dias=0, offsets=_PROPOSTA_OFFSETS,
)
_PROPOSTA_PRIVATE_LABEL = _cadencia_de_prospeccao(
    codigo="proposta", rotulo="Proposta Enviada",
    gatilho_stage_key="proposta_enviada", gatilho_stage_rotulo="Proposta Enviada",
    gatilho_dias=1, gatilho_silencio_dias=0, offsets=_PROPOSTA_OFFSETS,
)

# ═══════════════════════════════════════════════════════════════════════════════
# As duas cadências dos funis de Reposição — INTACTAS em 23/09/2026
# ═══════════════════════════════════════════════════════════════════════════════
#
# O spec de 23/09 reformula só a prospecção (§7, "o que NÃO muda"). Daqui para baixo
# tudo segue como estava: os números são os da ata de 10/09/2026, os 8 templates de
# Reposição continuam conectados, e os quatro campos novos ficam nos defaults — que
# foram escolhidos exatamente para isso: `gatilho_silencio_dias=0` (o relógio destas
# duas é mesmo o da ETAPA) e `etapa_final_key=None` (estas não movem card nenhum).

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

# "Cliente Ativo" é a key `novo` do funil de Reposição — o card nasce ali quando a
# venda fecha, então dias na etapa == dias desde a compra (decisão 2 no cabeçalho).
_REPOSICAO_ATACADO = Cadencia(
    codigo="reposicao",
    rotulo="Reposição",
    gatilho_stage_key="novo",
    gatilho_stage_rotulo="Cliente Ativo",
    gatilho_dias=45,
    touches=_toques(_REPOSICAO_OFFSETS,
                     tuple(f"joao_reposicao_atacado_t{n}" for n in range(1, 5)),
                     _REPOSICAO_ADIAMENTO),
)
_REPOSICAO_PRIVATE_LABEL = Cadencia(
    codigo="reposicao",
    rotulo="Reposição",
    gatilho_stage_key="novo",
    gatilho_stage_rotulo="Cliente Ativo",
    gatilho_dias=45,
    touches=_toques(_REPOSICAO_OFFSETS,
                     tuple(f"joao_reposicao_privatelabel_t{n}" for n in range(1, 5)),
                     _REPOSICAO_ADIAMENTO),
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
_EM_ATENCAO_ATACADO = Cadencia(
    codigo="em_atencao",
    rotulo="Em atenção",
    gatilho_stage_key="novo",
    gatilho_stage_rotulo="Cliente Ativo",
    gatilho_dias=90,
    repete_ultimo=True,
    touches=_toques((3,), (None,), (1,)),
)
_EM_ATENCAO_PRIVATE_LABEL = Cadencia(
    codigo="em_atencao",
    rotulo="Em atenção",
    gatilho_stage_key="novo",
    gatilho_stage_rotulo="Cliente Ativo",
    gatilho_dias=90,
    repete_ultimo=True,
    touches=_toques((3,), (None,), (1,)),
)

FUNIS: tuple[Funil, ...] = (
    Funil("atacado", "João - Atacado", PIPELINE_ATACADO,
          (_NOVO_ATACADO, _EM_CONVERSA_ATACADO, _PROPOSTA_ATACADO)),
    Funil("private_label", "João - Private Label", PIPELINE_PRIVATE_LABEL,
          (_NOVO_PRIVATE_LABEL, _EM_CONVERSA_PRIVATE_LABEL, _PROPOSTA_PRIVATE_LABEL)),
    Funil("reposicao_atacado", "João - Reposição Atacado", PIPELINE_REPOSICAO_ATACADO,
          (_REPOSICAO_ATACADO, _EM_ATENCAO_ATACADO)),
    Funil("reposicao_private_label", "João - Reposição Private Label",
          PIPELINE_REPOSICAO_PRIVATE_LABEL,
          (_REPOSICAO_PRIVATE_LABEL, _EM_ATENCAO_PRIVATE_LABEL)),
    # Espaço reservado — decisão 3 no cabeçalho. Zero cadência, de propósito.
    Funil("recuperacao", "João - Recuperação", PIPELINE_RECUPERACAO, ()),
)

# Só depende de `codigo`, não de funil — `joao_novo`, `joao_em_conversa`,
# `joao_proposta` (novo em 23/09/2026), `joao_reposicao` e `joao_em_atencao`, mesmo
# que cada código exista em dois objetos `Cadencia` distintos (um por funil-irmão).
# O frozenset dedupa sozinho. `joao_proposta` entra aqui SOZINHO, por ser derivado de
# `FUNIS` — mas a lista hardcoded do handler dos jobs é outra, e precisa dele à mão.
JOB_TYPES: frozenset[str] = frozenset(
    cadencia.job_type for f in FUNIS for cadencia in f.cadencias
)

FUNIL_CODIGOS: tuple[str, ...] = tuple(f.codigo for f in FUNIS)
_POR_FUNIL: Mapping[str, Funil] = {f.codigo: f for f in FUNIS}


def funil(codigo: str) -> Funil | None:
    """O funil pelo código, ou None. Usa `.cadencias` para saber o que ele tem."""
    return _POR_FUNIL.get(codigo)


def cadencia_do_funil(funil_codigo: str, cadencia_codigo: str) -> Cadencia | None:
    """A cadência de UM funil, ou None se o par não existe (ex. qualquer par com
    `funil_codigo="recuperacao"`, ou `funil_codigo="atacado"` com
    `cadencia_codigo="reposicao"`). É o `cj.CADENCIAS[codigo]` de antes, com o funil
    como parte obrigatória da chave — o mesmo motivo do cabeçalho deste módulo."""
    f = _POR_FUNIL.get(funil_codigo)
    if not f:
        return None
    return next((c for c in f.cadencias if c.codigo == cadencia_codigo), None)


# ═══════════════════════════════════════════════════════════════════════════════
# A sobreposição do banco
# ═══════════════════════════════════════════════════════════════════════════════
#
# FORMA do `overrides` — é o contrato entre este módulo, a API e o agendador:
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
    funil: str, codigo: str, overrides: Mapping[str, Any] | None = None,
) -> tuple[Touch, ...]:
    """Os toques de (funil, cadência) com a sobreposição do banco aplicada. PURA.

    Sem override, vale o código. Com override, vale o banco — toque a toque, campo a
    campo. Uma sequence que não existe na cadência é IGNORADA: a tabela sobrepõe, não
    acrescenta nem remove toque. O banco tem a mesma trava, num CHECK.

    `(funil, codigo)` que não formam um par válido levanta `KeyError` — mesmo
    comportamento de antes (`CADENCIAS[codigo].linhas[linha]`), só que agora a chave
    é (funil, código) em vez de (código, linha).
    """
    cadencia = cadencia_do_funil(funil, codigo)
    if cadencia is None:
        raise KeyError((funil, codigo))
    do_codigo = cadencia.touches
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
    funil: str, codigo: str, overrides: Mapping[str, Any] | None = None,
) -> CadenciaResolvida:
    """A cadência inteira resolvida — o que o agendador (`service.py`) consome. PURA."""
    f = _POR_FUNIL.get(funil)
    if f is None:
        raise KeyError(funil)
    cadencia = cadencia_do_funil(funil, codigo)
    if cadencia is None:
        raise KeyError((funil, codigo))
    overrides = overrides or {}

    gatilho_dias = overrides.get("gatilho_dias")
    ativa = overrides.get("ativa")
    return CadenciaResolvida(
        codigo=cadencia.codigo,
        funil=f.codigo,
        job_type=cadencia.job_type,
        pipeline_id=f.pipeline_id,
        gatilho_stage_key=cadencia.gatilho_stage_key,
        gatilho_stage_rotulo=cadencia.gatilho_stage_rotulo,
        gatilho_dias=cadencia.gatilho_dias if gatilho_dias is None else gatilho_dias,
        ativa=cadencia.ativa if ativa is None else bool(ativa),
        repete_ultimo=cadencia.repete_ultimo,
        touches=resolver_cadencia(funil, codigo, overrides),
        # Sem sobreposição de banco, de propósito (spec 2026-09-23 §5): o prazo
        # editável na tela é o de ETAPA (`gatilho_dias`). Estes quatro vêm do código
        # e a tela só os MOSTRA.
        gatilho_silencio_dias=cadencia.gatilho_silencio_dias,
        etapa_final_key=cadencia.etapa_final_key,
        etapa_final_rotulo=cadencia.etapa_final_rotulo,
        dias_ate_mover=cadencia.dias_ate_mover,
    )


def toques_sem_template(
    funil: str, codigo: str, overrides: Mapping[str, Any] | None = None,
) -> tuple[int, ...]:
    """As sequences que ainda não têm template — vazio significa "pode ligar".

    É a metade que este módulo sabe responder da trava da API ("ligar exige template
    aprovado em todo toque"). A outra metade — se o template EXISTE e está APPROVED
    na Meta — é da API, que tem como perguntar.
    """
    return tuple(
        t.sequence
        for t in resolver_cadencia(funil, codigo, overrides)
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
