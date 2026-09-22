"""API da DEFINIÇÃO das cadências de follow-up — a da ValerIA e as dos cinco funis do
João.

O painel de Follow-up (aba em /campanhas) renderiza a esteira de toques a partir
deste endpoint, mantendo `follow_up/cadence.py` e `follow_up/cadence_joao.py` como
única fonte de verdade — uma cópia hardcoded no frontend divergiria em silêncio a
cada ajuste do motor.

Os JOBS vivos (follow_up_jobs) não passam por aqui: o CRM os lê direto do Supabase
(mesmo padrão de broadcasts/campaigns), com RLS/service key do lado Next.

──────────────────────────────────────────────────────────────────────────────
DOIS MOTORES, UM ENDPOINT — E A VALERIA NÃO MUDA UMA VÍRGULA
──────────────────────────────────────────────────────────────────────────────
`followup-board.tsx` lê HOJE quatro chaves no TOPO do payload (`touches`,
`outbound_nudge`, `min_gap_hours`, `business_window`). O João entra como chave NOVA
ao lado (`joao`), e a ValerIA ganha um espelho nomeado (`valeria`) para o seletor da
tela — o MESMO dicionário, não uma segunda cópia que possa divergir. Aninhar a
definição atual em `{"valeria": ...}` e remover as chaves do topo apagaria a esteira
da tela em produção, no mesmo deploy, sem um erro sequer no log.

──────────────────────────────────────────────────────────────────────────────
FUNIL É O EIXO (spec 2026-09-21) — O BANCO SOBREPÕE, O CÓDIGO É A ORIGEM
──────────────────────────────────────────────────────────────────────────────
O João não é mais "cadência → {linha: pipeline}", é "funil → [cadências deste
funil]" (`cadence_joao.FUNIS`). `followup_joao_cadencia` e `followup_joao_toque`
(migration 20260918, editada em 2026-09-21 para a chave `funil, cadencia[, toque]`)
nascem VAZIAS, e vazio quer dizer "vale o código". A migration é aplicada À MÃO: até
lá as tabelas NÃO EXISTEM e o PostgREST responde PGRST205 — por isso toda leitura
aqui é fail-open para o código. Um GET que quebrasse nesse erro deixaria a aba
inteira (inclusive a metade da ValerIA) vazia por causa de uma tabela que ainda não
existe.

A GRAVAÇÃO é MERGE, nunca replace: o corpo com só `dias` não pode derrubar o
`template_name` já configurado. E a FORMA da cadência não é editável — `sequence`
fora do que o código declara é recusada, mesma regra do CHECK
`followup_joao_toque_dentro_da_cadencia` do lado do banco. Sem isso a tela volta a
ser um builder: o toque extra é gravado, aparece configurado e o motor o ignora em
silêncio (`resolver_cadencia` descarta sequence que não existe).

Cada PUT é sempre UM funil e UMA cadência — não existe mais "aplicar nas duas
linhas" (Atacado e Private Label deixaram de estar acoplados, spec §2 decisão 1):
`funil` é campo OBRIGATÓRIO do corpo.

──────────────────────────────────────────────────────────────────────────────
A TRAVA DE ATIVAÇÃO
──────────────────────────────────────────────────────────────────────────────
Ligar exige template com status APPROVED em TODO toque do par (funil, cadência). É
a guarda mais cara do projeto, e a razão é a mesma de `campaigns/validation.py`
(regra 12): template que não envia não impede a MATRÍCULA, só o envio — a cadência
inscreve o card, não manda nada e caminha até o fim, registrando "não teve
resposta" para quem nunca foi contatado. A mensagem diz NOME e STATUS de cada um
porque a ação muda com o status: PENDING é esperar, REJECTED é corrigir e
ressubmeter, e ausente da Meta é criar do zero.

"Em atenção" hoje não tem NENHUM template (os 24 aprovados em 13/09/2026 cobrem só
Novo + Em conversa + Reposição), então ligá-la é sempre recusado — e isso é uma
declaração do `cadence_joao.py`, não um bug.

FAIL-OPEN, UM ÚNICO: `message_templates` inacessível pula SÓ a regra de status
(mesmo critério de `campaigns/router.api_activate_campaign`, pelo mesmo motivo — a
tela já escolhe entre aprovados, e travar a ativação por um timeout do Supabase é
pior do que o risco que a guarda cobre). Oscilação de banco NÃO é anistia para o
toque sem NOME de template: essa metade da regra não depende da Meta.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Request

from app.follow_up import cadence_joao as cj
from app.follow_up.cadence import CADENCE, MIN_GAP, OUTBOUND_NUDGE, Touch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cadence", tags=["cadence"])

# Visibilidade do ESPELHO do motor no CRM (decisão executiva 10/07: oculto até a
# análise interna concluir; religável pela própria interface, sem deploy). Mesmo
# padrão Redis do /api/buffer (config:buffer_enabled). SÓ APRESENTAÇÃO: não toca o
# status da campanha nem as guardas 409 — impossível causar execução dupla por aqui.
_MIRROR_VISIBILITY_KEY = "config:cadence_mirror_visible"


@router.get("/mirror-visibility")
async def get_mirror_visibility(request: Request) -> dict:
    """Default OCULTO: só é visível com opt-in explícito ('1') gravado no Redis."""
    val = await request.app.state.redis.get(_MIRROR_VISIBILITY_KEY)
    return {"visible": val == "1"}


@router.post("/mirror-visibility")
async def set_mirror_visibility(request: Request) -> dict:
    body = await request.json()
    visible = bool(body.get("visible", False))
    await request.app.state.redis.set(_MIRROR_VISIBILITY_KEY, "1" if visible else "0")
    return {"visible": visible}


# ═══════════════════════════════════════════════════════════════════════════════
# A definição da ValerIA — intocada
# ═══════════════════════════════════════════════════════════════════════════════
def _touch_payload(touch: Touch) -> dict:
    return {
        "sequence": touch.sequence,
        "offset_hours": touch.offset.total_seconds() / 3600,
        "jitter_minutes": list(touch.jitter_minutes) if touch.jitter_minutes else None,
        "objective": touch.objective,
        "objective_prompt": touch.objective_prompt,
    }


def _valeria_definition() -> dict:
    return {
        "touches": [_touch_payload(t) for t in CADENCE],
        "outbound_nudge": _touch_payload(OUTBOUND_NUDGE),
        "min_gap_hours": MIN_GAP.total_seconds() / 3600,
        # Espelha _BUSINESS_START/_BUSINESS_END/seg-sex de follow_up/service.py —
        # valores estáveis do clamp comercial (mudá-los lá exige atualizar aqui e o teste).
        "business_window": {
            "start": "09:00",
            "end": "16:00",
            "days": "seg-sex",
            "timezone": "America/Sao_Paulo",
        },
    }


def build_cadence_definition() -> dict:
    """Payload PURO da definição da ValerIA — sem I/O, para teste isolado.

    As quatro chaves ficam NO TOPO (é o que `followup-board.tsx` lê hoje) e o bloco
    `valeria` aponta para os MESMOS objetos, para o seletor ValerIA/João da tela.
    """
    valeria = _valeria_definition()
    return {**valeria, "valeria": valeria}


# ═══════════════════════════════════════════════════════════════════════════════
# A definição do João — código + sobreposição do banco, funil como eixo
# ═══════════════════════════════════════════════════════════════════════════════
_TABELA_CADENCIA = "followup_joao_cadencia"
_TABELA_TOQUE = "followup_joao_toque"
_TABELA_TEMPLATES = "message_templates"

# `message_templates.status`: o sync local grava minúsculo, o payload cru da Meta vem
# 'APPROVED'. Comparamos normalizado, como `campaigns/validation.py`.
_STATUS_APROVADO = "approved"

# O que o operador tem de FAZER, por status — a ação muda com o status, e é por isso
# que a trava recebe um mapa nome→status e não um conjunto de aprovados.
_ACAO_POR_STATUS = {
    "pending": "Espere a aprovação da Meta e ligue a cadência depois.",
    "rejected": "A Meta recusou este template: corrija o texto e submeta de novo — "
                "enquanto estiver nesse estado ele nunca vai enviar.",
    "paused": "A Meta pausou este template por qualidade: só volta a enviar depois "
              "de sair da pausa.",
    "disabled": "A Meta desabilitou este template: ele não volta — crie outro e "
                "submeta.",
}
_ACAO_GENERICA = ("Só template com status APPROVED envia: resolva a pendência na "
                  "Meta e ligue a cadência depois.")

# Explica a CONSEQUÊNCIA uma vez, em todas as variantes da trava. É o que o dono
# precisa entender: o estrago não é "não enviou", é "registrou que não teve resposta".
_ENVIO_MUDO = (
    "Template que não envia não impede a MATRÍCULA, só o envio: a cadência inscreve "
    "o card, não manda nada e caminha até o fim, registrando \"não teve resposta\" "
    "para quem nunca foi contatado."
)


@dataclass(frozen=True)
class Problema:
    """Um motivo para o PUT ser recusado.

    `funil` e `sequence` viajam junto com a mensagem porque a tela destaca o toque
    culpado — um 400 com string solta obrigaria o frontend a adivinhar qual é. O
    `codigo` existe para ela agrupar/estilizar; o texto é o que a pessoa lê.

    Campo `funil` (antes `linha`): cada PUT é sempre um funil só (spec 2026-09-21),
    então o problema aponta o funil do próprio pedido — não mais uma entre duas
    linhas acopladas.
    """

    codigo: str
    mensagem: str
    cadencia: str | None = None
    funil: str | None = None
    sequence: int | None = None


def _recusa(problemas: list[Problema]) -> HTTPException:
    return HTTPException(400, detail={"problemas": [asdict(p) for p in problemas]})


# ─── Leitura da sobreposição ────────────────────────────────────────────────────
def _supabase():
    """Import TARDIO de propósito: é o que deixa o teste trocar o cliente inteiro."""
    from app.db.supabase import get_supabase

    return get_supabase()


def _ler_linhas(tabela: str, funil_codigo: str | None = None,
                codigo: str | None = None) -> list[dict]:
    """As linhas de uma tabela de sobreposição — [] quando não dá para ler.

    A migration 20260918 é aplicada À MÃO: até que alguém a rode, estas tabelas não
    existem e o PostgREST responde PGRST205. Cair no código é o comportamento certo;
    um 500 aqui esvaziaria a aba Follow-up inteira.
    """
    try:
        consulta = _supabase().table(tabela).select("*")
        if funil_codigo:
            consulta = consulta.eq("funil", funil_codigo)
        if codigo:
            consulta = consulta.eq("cadencia", codigo)
        return list(consulta.execute().data or [])
    except Exception as exc:
        logger.warning(
            "[FOLLOWUP JOAO] nao deu para ler %s (%s) - vale o codigo de "
            "cadence_joao.py. Esperado enquanto 20260918_followup_joao_config.sql "
            "nao for aplicada a mao no Supabase.", tabela, exc,
        )
        return []


def _sobreposicao(funil_codigo: str | None = None,
                  codigo: str | None = None) -> tuple[dict, dict]:
    """(por cadência, por toque) — as duas tabelas indexadas pela chave primária
    NOVA (`funil, cadencia[, toque]`, spec 2026-09-21 §4)."""
    por_cadencia: dict[tuple[str, str], dict] = {}
    for linha in _ler_linhas(_TABELA_CADENCIA, funil_codigo, codigo):
        chave_funil = str(linha.get("funil") or "")
        chave_cad = str(linha.get("cadencia") or "")
        if chave_funil and chave_cad:
            por_cadencia[(chave_funil, chave_cad)] = dict(linha)

    por_toque: dict[tuple[str, str, int], dict] = {}
    for linha in _ler_linhas(_TABELA_TOQUE, funil_codigo, codigo):
        try:
            chave_toque = (str(linha.get("funil") or ""),
                           str(linha.get("cadencia") or ""),
                           int(linha.get("toque")))
        except (TypeError, ValueError):
            continue
        por_toque[chave_toque] = dict(linha)
    return por_cadencia, por_toque


def _overrides(funil_codigo: str, codigo: str, por_cadencia: dict,
               por_toque: dict) -> dict:
    """A sobreposição no formato que `cadence_joao.resolver` já sabe ler.

    Uma segunda forma de override seria uma segunda regra de precedência, e as duas
    divergiriam no primeiro ajuste.
    """
    da_cadencia = por_cadencia.get((funil_codigo, codigo)) or {}
    return {
        "gatilho_dias": da_cadencia.get("gatilho_dias"),
        "ativa": da_cadencia.get("ativa"),
        "toques": {
            seq: {"dias": r.get("dias"), "template_name": r.get("template_name")}
            for (f, c, seq), r in por_toque.items() if f == funil_codigo and c == codigo
        },
    }


def _cadencia_payload(funil_codigo: str, cadencia: cj.Cadencia, por_cadencia: dict,
                      por_toque: dict) -> dict:
    """Uma cadência RESOLVIDA de UM funil (o efetivo + o que o código manda por
    baixo).

    `*_codigo` viaja junto porque a tela precisa mostrar "padrão 45" ao lado do 60
    gravado — sem isso ninguém descobre o que a configuração mudou nem como voltar.
    `gatilho_stage_rotulo` vem SEMPRE de `cadencia` (o código de `cadence_joao.py`),
    nunca do banco — é o rótulo hardcoded que a decisão 2 da spec 2026-09-21 exige.
    """
    ov = _overrides(funil_codigo, cadencia.codigo, por_cadencia, por_toque)
    do_codigo = cadencia.touches
    resolvidos = cj.resolver_cadencia(funil_codigo, cadencia.codigo, ov)
    faltando = list(cj.toques_sem_template(funil_codigo, cadencia.codigo, ov))

    da_cadencia = por_cadencia.get((funil_codigo, cadencia.codigo)) or {}
    gatilho_dias = da_cadencia.get("gatilho_dias")
    ativa = da_cadencia.get("ativa")
    return {
        "codigo": cadencia.codigo,
        "rotulo": cadencia.rotulo,
        "job_type": cadencia.job_type,
        "gatilho_stage_key": cadencia.gatilho_stage_key,
        "gatilho_stage_rotulo": cadencia.gatilho_stage_rotulo,
        "gatilho_dias": cadencia.gatilho_dias if gatilho_dias is None else gatilho_dias,
        "gatilho_dias_codigo": cadencia.gatilho_dias,
        "ativa": cadencia.ativa if ativa is None else bool(ativa),
        "repete_ultimo": cadencia.repete_ultimo,
        # Só a metade que NÃO depende da Meta: "todo toque tem NOME de template". O
        # status APPROVED é conferido na hora de LIGAR, que é quando há uma ação
        # humana esperando a resposta.
        "pode_ligar": not faltando,
        "toques": [
            {
                "sequence": efetivo.sequence,
                "dias": efetivo.offset.days,
                "dias_codigo": original.offset.days,
                "template_name": efetivo.template_name,
                "template_name_codigo": original.template_name,
                "aceita_adiamento": efetivo.aceita_adiamento,
            }
            for efetivo, original in zip(resolvidos, do_codigo)
        ],
        "toques_sem_template": faltando,
    }


def _funil_payload(f: cj.Funil, por_cadencia: dict, por_toque: dict) -> dict:
    """Um funil e as cadências resolvidas dele — `[]` para "recuperacao" (espaço
    reservado, spec 2026-09-21 §1)."""
    return {
        "codigo": f.codigo,
        "rotulo": f.rotulo,
        "pipeline_id": f.pipeline_id,
        "cadencias": [_cadencia_payload(f.codigo, c, por_cadencia, por_toque)
                     for c in f.cadencias],
    }


def build_joao_definition(por_cadencia: dict | None = None,
                          por_toque: dict | None = None) -> dict:
    if por_cadencia is None or por_toque is None:
        por_cadencia, por_toque = _sobreposicao()
    return {"funis": [_funil_payload(f, por_cadencia, por_toque) for f in cj.FUNIS]}


@router.get("/definition")
async def get_cadence_definition() -> dict:
    payload = build_cadence_definition()
    payload["joao"] = build_joao_definition()
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# PUT: grava a sobreposição de UM (funil, cadência)
# ═══════════════════════════════════════════════════════════════════════════════
def _toques_validos(cadencia: cj.Cadencia) -> list[int]:
    return sorted(t.sequence for t in cadencia.touches)


def _descricao_dos_toques(validos: list[int]) -> str:
    if len(validos) == 1:
        return f"o toque {validos[0]}"
    return f"os toques {validos[0]} a {validos[-1]}"


def _toque_inexistente(cadencia: cj.Cadencia, pedido: Any,
                       validos: list[int]) -> Problema:
    return Problema(
        "toque_inexistente",
        f"O toque {pedido} não existe em \"{cadencia.rotulo}\": essa cadência tem "
        f"{_descricao_dos_toques(validos)}. Adicionar ou remover toque é mudança de "
        f"código, não de configuração — a tela edita os dias e o template de cada "
        f"toque, nunca a forma da cadência.",
        cadencia=cadencia.codigo,
    )


def _status_dos_templates(nomes: list[str]) -> dict[str, str] | None:
    """Mapa nome → status CRU da Meta, ou None quando não deu para consultar.

    `{}` e `None` são estados OPOSTOS: `{}` é uma RESPOSTA ("a Meta não conhece
    nenhum desses nomes") e REPROVA; `None` é "não deu para consultar" e pula SÓ a
    regra de status. Um `if not mapa: mapa = None` transformaria oscilação do
    Supabase em ativação aprovada em silêncio.
    """
    try:
        linhas = (_supabase().table(_TABELA_TEMPLATES).select("name, status")
                  .in_("name", nomes).execute().data) or []
    except Exception as exc:
        logger.warning(
            "[FOLLOWUP JOAO] nao deu para conferir os templates %s em "
            "message_templates (%s) - regra de STATUS pulada (fail-open); a de "
            "template ausente continua valendo.", nomes, exc,
        )
        return None

    mapa: dict[str, str] = {}
    for linha in linhas:
        nome = str(linha.get("name") or "")
        if not nome:
            continue
        # Cada template tem uma linha-espelho POR CANAL (os canais compartilham a
        # mesma WABA) e o sync tem buracos: entre dois espelhos do mesmo nome vale o
        # APROVADO, senão um espelho desatualizado reprovaria template que a Meta
        # aprovou. Mesmo critério de `campaigns/router.api_activate_campaign`.
        anterior = mapa.get(nome)
        if anterior is not None and anterior.strip().lower() == _STATUS_APROVADO:
            continue
        mapa[nome] = str(linha.get("status") or "")
    return mapa


def _problema_de_template(funil_codigo: str, codigo: str, sequence: int, nome: str,
                          status: dict[str, str]) -> list[Problema]:
    """As três situações que um conjunto de aprovados fundiria numa só.

    Ausente, PENDING e REJECTED pedem ações diferentes do operador (criar, esperar,
    corrigir). Dizer só "não está aprovado" devolve a pessoa para a Meta sem saber o
    que procurar — e no caso do ausente ela procura o que não há.
    """
    if nome not in status:
        return [Problema(
            "template_nao_aprovado",
            f"O toque {sequence} usa o template `{nome}`, que NÃO EXISTE na Meta — "
            f"nunca foi submetido, ou foi criado com outro nome. {_ENVIO_MUDO} Crie "
            f"o template com esse nome exato, espere a aprovação e ligue a cadência "
            f"depois.",
            cadencia=codigo, funil=funil_codigo, sequence=sequence,
        )]

    bruto = str(status[nome] or "")
    if bruto.strip().lower() == _STATUS_APROVADO:
        return []

    acao = _ACAO_POR_STATUS.get(bruto.strip().lower(), _ACAO_GENERICA)
    como_esta = f"está {bruto} na Meta" if bruto else "está sem status na Meta"
    return [Problema(
        "template_nao_aprovado",
        f"O toque {sequence} usa o template `{nome}`, que {como_esta}. "
        f"{_ENVIO_MUDO} {acao}",
        cadencia=codigo, funil=funil_codigo, sequence=sequence,
    )]


def _problemas_de_ativacao(funil_codigo: str, codigo: str, por_cadencia: dict,
                           por_toque: dict) -> list[Problema]:
    """A trava: template APROVADO em todo toque do par (funil, cadência).

    Olha a configuração RESULTANTE (banco + o que este PUT grava), não a que estava
    no banco antes — configurar o template e ligar no MESMO PUT tem de funcionar.
    Escopada a UM funil por vez (spec 2026-09-21): Atacado e Private Label deixaram
    de estar acoplados, então ligar um não depende mais do outro.
    """
    problemas: list[Problema] = []
    onde: dict[str, list[int]] = {}

    ov = _overrides(funil_codigo, codigo, por_cadencia, por_toque)
    for sequence in cj.toques_sem_template(funil_codigo, codigo, ov):
        problemas.append(Problema(
            "toque_sem_template",
            f"O toque {sequence} não tem template configurado. {_ENVIO_MUDO} "
            f"Escolha um template aprovado para esse toque antes de ligar a "
            f"cadência.",
            cadencia=codigo, funil=funil_codigo, sequence=sequence,
        ))
    for toque in cj.resolver_cadencia(funil_codigo, codigo, ov):
        if toque.template_name:
            onde.setdefault(toque.template_name, []).append(toque.sequence)

    if not onde:
        return problemas

    status = _status_dos_templates(sorted(onde))
    if status is None:
        # Fail-open SÓ aqui. As linhas acima (toque sem NOME) não dependem da Meta e
        # continuam valendo: oscilação de banco não é anistia para cadência quebrada.
        return problemas

    for nome in sorted(onde):
        for sequence in onde[nome]:
            problemas.extend(
                _problema_de_template(funil_codigo, codigo, sequence, nome, status))
    return problemas


@router.put("/joao")
async def put_joao_definition(request: Request) -> dict:
    """Grava a sobreposição de UM par (funil, cadência) do João e devolve ele já
    resolvido.

    Corpo: `{funil, cadencia, gatilho_dias?, ativa?, atualizado_por?,
             toques?: {sequence: {dias?, template_name?}}}`.

    `funil` é OBRIGATÓRIO (spec 2026-09-21 §5) — não existe mais "aplicar nas duas
    linhas": cada funil tem seu próprio liga/desliga e seu próprio prazo de
    gatilho. `funil` ausente ou fora de `cj.FUNIL_CODIGOS` é 404. Um par
    `(funil, cadencia)` que não existe (ex. `funil=atacado, cadencia=reposicao`) é
    404 nomeando as cadências VÁLIDAS DAQUELE funil, não a lista genérica de 4
    códigos — a lista genérica confundiria mais do que ajudaria.

    AUSENTE e `null` não são a mesma coisa: ausente é "não mexe", `null` é "apaga a
    sobreposição e volta a valer o código" — é o botão de desfazer da tela.
    """
    try:
        corpo = await request.json()
    except Exception:
        raise _recusa([Problema("corpo_invalido", "O corpo não é um JSON válido.")])
    if not isinstance(corpo, dict):
        raise _recusa([Problema("corpo_invalido", "O corpo precisa ser um objeto.")])

    funil_codigo = str(corpo.get("funil") or "").strip()
    f = cj.funil(funil_codigo)
    if f is None:
        raise HTTPException(
            404,
            f"funil '{funil_codigo}' não existe — os do João são "
            f"{', '.join(cj.FUNIL_CODIGOS)}.",
        )

    codigo = str(corpo.get("cadencia") or "").strip()
    cadencia = cj.cadencia_do_funil(funil_codigo, codigo)
    if cadencia is None:
        validas = [c.codigo for c in f.cadencias]
        if validas:
            raise HTTPException(
                404,
                f"cadência '{codigo}' não existe em \"{f.rotulo}\" — as cadências "
                f"desse funil são {', '.join(validas)}.",
            )
        raise HTTPException(
            404,
            f"cadência '{codigo}' não existe em \"{f.rotulo}\" — esse funil ainda "
            f"não tem nenhuma cadência configurada.",
        )

    atualizado_por = corpo.get("atualizado_por")
    atualizado_por = str(atualizado_por).strip() if atualizado_por else None

    # ── 1. A FORMA: o que o corpo pede existe? ────────────────────────────────
    problemas: list[Problema] = []
    validos = _toques_validos(cadencia)
    bruto = corpo.get("toques") or {}
    if not isinstance(bruto, dict):
        problemas.append(Problema(
            "toques_invalidos",
            "`toques` precisa ser um objeto {sequence: {dias, template_name}}.",
            cadencia=codigo, funil=funil_codigo,
        ))
        bruto = {}

    pedidos: dict[int, dict[str, Any]] = {}
    for chave, valor in bruto.items():
        try:
            sequence = int(chave)
        except (TypeError, ValueError):
            problemas.append(_toque_inexistente(cadencia, f'"{chave}"', validos))
            continue
        if sequence not in validos:
            problemas.append(_toque_inexistente(cadencia, sequence, validos))
            continue
        if not isinstance(valor, dict):
            problemas.append(Problema(
                "toque_invalido",
                f"O toque {sequence} precisa ser um objeto com `dias` e/ou "
                f"`template_name`.",
                cadencia=codigo, funil=funil_codigo, sequence=sequence,
            ))
            continue

        campos: dict[str, Any] = {}
        if "dias" in valor:
            dias = valor["dias"]
            if dias is not None and (isinstance(dias, bool)
                                     or not isinstance(dias, int)):
                problemas.append(Problema(
                    "dias_invalido",
                    f"O toque {sequence} recebeu `dias` que não é um número inteiro "
                    f"({dias!r}).",
                    cadencia=codigo, funil=funil_codigo, sequence=sequence,
                ))
                continue
            campos["dias"] = dias
        if "template_name" in valor:
            nome = valor["template_name"]
            nome = str(nome).strip() if nome is not None else None
            campos["template_name"] = nome or None
        pedidos[sequence] = campos

    grava_gatilho = "gatilho_dias" in corpo
    gatilho_dias = corpo.get("gatilho_dias")
    if grava_gatilho and gatilho_dias is not None:
        if (isinstance(gatilho_dias, bool) or not isinstance(gatilho_dias, int)
                or gatilho_dias < 1):
            # Espelha o CHECK `followup_joao_cadencia_gatilho_positivo`: zero dia
            # pegaria o card no instante em que ele entra na etapa, e a cadência
            # inteira perde o sentido de "parado há N dias".
            problemas.append(Problema(
                "gatilho_invalido",
                f"`gatilho_dias` precisa ser um inteiro de 1 dia para cima (veio "
                f"{gatilho_dias!r}).",
                cadencia=codigo, funil=funil_codigo,
            ))

    grava_ativa = "ativa" in corpo
    ativa = corpo.get("ativa")
    if grava_ativa and ativa is not None:
        ativa = bool(ativa)

    if problemas:
        raise _recusa(problemas)

    # ── 2. O MERGE: banco + corpo, em memória, ANTES de gravar ────────────────
    por_cadencia, por_toque = _sobreposicao(funil_codigo, codigo)

    novos_toques: list[dict] = []
    for sequence, campos in sorted(pedidos.items()):
        atual = dict(por_toque.get((funil_codigo, codigo, sequence)) or {})
        # `updated_at` é do trigger: reenviar o valor lido congelaria a coluna na
        # data da primeira gravação.
        atual.pop("updated_at", None)
        atual.update({"funil": funil_codigo, "cadencia": codigo, "toque": sequence})
        atual.update(campos)
        if atualizado_por:
            atual["atualizado_por"] = atualizado_por
        novos_toques.append(atual)
        por_toque[(funil_codigo, codigo, sequence)] = atual

    nova_cadencia: dict | None = None
    if grava_gatilho or grava_ativa:
        atual = dict(por_cadencia.get((funil_codigo, codigo)) or {})
        atual.pop("updated_at", None)
        atual["funil"] = funil_codigo
        atual["cadencia"] = codigo
        if grava_gatilho:
            atual["gatilho_dias"] = gatilho_dias
        if grava_ativa:
            atual["ativa"] = ativa
        if atualizado_por:
            atual["atualizado_por"] = atualizado_por
        nova_cadencia = atual
        por_cadencia[(funil_codigo, codigo)] = atual

    # ── 3. As regras que só a configuração RESULTANTE responde ────────────────
    if pedidos:
        ov = _overrides(funil_codigo, codigo, por_cadencia, por_toque)
        for texto in cj.validar_toques(cj.resolver_cadencia(funil_codigo, codigo, ov)):
            problemas.append(Problema(
                "dias_invalido",
                f"{texto}. Ordem invertida não quebra nada visível no banco — "
                f"aparece lá na frente, como o lead recebendo a despedida antes da "
                f"oferta.",
                cadencia=codigo, funil=funil_codigo,
            ))

    if grava_ativa and ativa is True:
        problemas.extend(
            _problemas_de_ativacao(funil_codigo, codigo, por_cadencia, por_toque))

    # Recusa não grava NADA — nem o gatilho, nem os dias, nem o `ativa`. Gravar
    # metade deixaria a configuração num estado que ninguém pediu, com a tela
    # mostrando erro em cima de dado já alterado.
    if problemas:
        raise _recusa(problemas)

    # ── 4. A gravação ─────────────────────────────────────────────────────────
    if nova_cadencia or novos_toques:
        sb = _supabase()
        if nova_cadencia:
            sb.table(_TABELA_CADENCIA).upsert(
                [nova_cadencia], on_conflict="funil,cadencia").execute()
        if novos_toques:
            sb.table(_TABELA_TOQUE).upsert(
                novos_toques, on_conflict="funil,cadencia,toque").execute()

    return _cadencia_payload(funil_codigo, cadencia, por_cadencia, por_toque)
