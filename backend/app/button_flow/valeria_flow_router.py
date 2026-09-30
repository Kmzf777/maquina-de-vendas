"""As cinco rotas de `/api/valeria-flow` — a fronteira HTTP do modal de /campanhas.

A tela edita TEXTO; a estrutura é código. Este módulo é o único caminho de escrita
que `valeria_flow_content` tem, e cada rota existe para que a tela não precise ter
opinião sobre nada:

  GET    /api/valeria-flow             registry + overrides JÁ MESCLADOS
  PUT    /api/valeria-flow/{node_id}   grava `corpo`/`rotulos`, valida, versiona rótulo
  DELETE /api/valeria-flow/{node_id}   apaga o override (volta ao default do registry)
  GET    /api/valeria-flow/channels    canais + perfil atual + perfil compartilhado
  POST   /api/valeria-flow/activate    cria perfil novo, aponta o canal, limpa o cache

── Por que a FUSÃO é do servidor ────────────────────────────────────────────
O `GET` devolve o texto final, não "registry + tabela, mescla você". Se a tela
mesclasse, existiriam DUAS implementações da regra de default (`if corpo:`,
`id ausente mantém o registry`) e elas divergiriam — é a classe de bug que
`app/campaigns/node_registry.py` documenta no cabeçalho: a tela gravando uma chave e
o motor lendo outra coisa no mesmo nome, com 16 campanhas construídas e 0 matrículas
na história. Aqui a fusão é UMA função (`valeria_content.aplicar`), e ela é a MESMA
que o runner chama no instante do envio (`valeria_runner._carregar_conteudo`). O
`corpo_default` viaja ao lado do valor atual só para a tela poder oferecer
"restaurar o texto original" sem recalcular nada.

── Por que `destino` não tem caminho de escrita ─────────────────────────────
`ConteudoUpdate` declara `corpo` e `rotulos`, e mais nada. Um payload com `destino`
ou `grava` não é filtrado: não existe campo onde pousar, exatamente como
`valeria_content.aplicar` não tem linha que os leia. O `destino` VIAJA no `GET`
(a tela mostra `→ N2`, para o editor entender o efeito do botão) e não volta nunca.

── Por que "Ativar" nunca edita perfil existente ────────────────────────────
`runner.py` registra, verificado em produção em 09/09, que o canal do João
(`a3a607b1`) já aponta para o MESMO `agent_profile_id` do canal da ValerIA
(`674beb13`). Virar o `kind` daquele perfil para `button_flow` transformaria o número
pessoal do vendedor em robô no mesmo instante. Então o "Ativar" só INSERE: cria um
perfil novo e aponta SÓ o canal escolhido (`channels.agent_profile_id`). Nenhuma
rota deste módulo faz UPDATE ou DELETE em `agent_profiles`.

E cria SEMPRE, sem reaproveitar um perfil `button_flow` que já exista: reaproveitar
faria dois canais compartilharem um perfil, que é precisamente o acoplamento acima.

── Fail-open no GET, fail-CLOSED no PUT ────────────────────────────────────
A migration `20260929_valeria_botoes.sql` não está aplicada em nenhum banco, e
`valeria_content.carregar` é fail-open por isso — o `GET` abre nos defaults em vez de
500, e a tela funciona. O `PUT` é o contrário: gravar sem ter conseguido LER
`rotulos_antigos` apagaria em silêncio o histórico de quem recebeu a tela antiga, e
esse histórico é o que faz `valeria_engine._casar` não perder o clique de um lead por
causa de uma edição de copy. Leitura falhou → 503 com o número da migration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.auth.dependencies import require_role
from app.button_flow import config as flow_config
from app.button_flow import runner as gate
from app.button_flow import valeria_content as conteudo
from app.button_flow import valeria_registry as reg
from app.button_flow.runner import limpar_cache_de_perfis
from app.channels.service import get_channel, list_channels, update_channel
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

_TABELA = "valeria_flow_content"
_LOG = "[VALERIA_FLOW_API]"

# A dependência RESOLVIDA, num nome de módulo, e não `Depends(require_role([...]))`
# inline. `require_role` devolve uma closure nova a cada chamada: inline, nenhum teste
# conseguiria recriar a mesma referência para pôr em `app.dependency_overrides` — a
# guarda só seria testável desligando a autenticação do app inteiro.
EXIGIR_ADMIN = require_role(["admin"])

router = APIRouter(
    prefix="/api/valeria-flow",
    tags=["valeria_flow"],
    dependencies=[Depends(EXIGIR_ADMIN)],
)

# Mensagem única da migration pendente. Uma só para os dois caminhos que dependem
# dela (gravar conteúdo e criar o perfil) — duas redações divergiriam.
_MSG_MIGRATION = (
    "a migration 20260929_valeria_botoes.sql ainda não foi aplicada neste banco — "
    "aplique-a no Supabase antes de editar ou ativar"
)


# ═══════════════════════════════════════════════════════════════════════════════
# Corpos de requisição
# ═══════════════════════════════════════════════════════════════════════════════
class ConteudoUpdate(BaseModel):
    """O que a tela pode gravar. `extra="ignore"` é explícito de propósito.

    A tela ecoa no PUT o objeto que recebeu do GET — e o GET traz `destino`, `grava`,
    `tela`, `ramo`, `corpo_default`. Recusar o excedente (`extra="forbid"`) faria todo
    salvamento virar 422 e obrigaria a tela a montar um payload à mão; ignorar é o que
    `valeria_content.aplicar` já faz com as mesmas chaves, e por isso é o mesmo
    contrato nas duas pontas.
    """

    model_config = ConfigDict(extra="ignore")

    corpo: str | None = None
    rotulos: dict[str, str] | None = None


class AtivarRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    channel_id: str
    # Nome do perfil novo. Opcional: sem ele o nome sai do canal, para o operador
    # distinguir os perfis na lista de /canais quando houver mais de um.
    nome: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Serialização — o registry, já mesclado, em JSON
# ═══════════════════════════════════════════════════════════════════════════════
def _limite_de_rotulo(no: reg.No) -> int:
    """O limite da Meta DESTE nó. Lista aceita 24, botão comum 20.

    Delegado a `valeria_content._limite_de_rotulo`: é a mesma regra que `validar` usa
    para RECUSAR o salvamento, e a tela mostra o contador de caracteres a partir deste
    número. Dois números diferentes fariam o contador dizer "cabe" e o save dizer
    "não cabe".
    """
    return conteudo._limite_de_rotulo(no)


def _botao_json(botao: reg.Botao, default: reg.Botao, limite: int, editado: bool) -> dict:
    return {
        "id": botao.id,
        "rotulo": botao.rotulo,
        "rotulo_default": default.rotulo,
        # SÓ-LEITURA. Viaja para a tela desenhar `→ N2`; não há campo que o receba
        # de volta (ver `ConteudoUpdate`).
        "destino": botao.destino,
        "grava": [[campo, valor] for campo, valor in botao.grava],
        "descricao": botao.descricao,
        "limite_rotulo": limite,
        "editado": editado,
    }


def _no_json(node_id: str, override: dict | None) -> dict:
    """Um nó com o override JÁ aplicado, ao lado dos defaults do registry."""
    override = override or {}
    default = reg.NOS[node_id]
    # A fusão é de `aplicar`, e de mais ninguém: é a mesma função que o runner chama.
    no = conteudo.aplicar(reg.NOS, {node_id: override})[node_id]

    rotulos = override.get("rotulos") or {}
    limite = _limite_de_rotulo(default)
    botoes = [
        _botao_json(botao, padrao, limite, botao.id in rotulos)
        for botao, padrao in zip(no.botoes, default.botoes)
    ]
    return {
        "id": no.id,
        "tipo": "no",
        "rotulo_interno": no.rotulo_interno,
        "tela": no.tela,
        "ramo": no.ramo,
        "corpo": no.corpo,
        "corpo_default": default.corpo,
        "foto": no.foto,
        "produto": no.produto,
        "botoes": botoes,
        "editaveis": list(no.editaveis),
        "rotulos_antigos": override.get("rotulos_antigos") or [],
        "editado": bool(override.get("corpo")) or bool(rotulos),
    }


def _terminal_json(terminal_id: str, override: dict | None) -> dict:
    """Um terminal com o override aplicado. Só `corpo` é editável.

    Os campos de EFEITO (`vendedor`, `tags`, `handoff`, `optout`, `silenciar_ia`,
    `prazos`) viajam para a tela poder dizer ao operador o que aquele desfecho FAZ —
    e, como o `destino` dos botões, não têm caminho de volta.
    """
    override = override or {}
    default = reg.TERMINAIS[terminal_id]
    terminal = conteudo.aplicar_terminais(reg.TERMINAIS, {terminal_id: override})[terminal_id]
    return {
        "id": terminal.id,
        "tipo": "terminal",
        "rotulo_interno": terminal.rotulo_interno,
        "corpo": terminal.corpo,
        "corpo_default": default.corpo,
        "vendedor": terminal.vendedor,
        "tags": list(terminal.tags),
        "silenciar_ia": terminal.silenciar_ia,
        "handoff": terminal.handoff,
        "optout": terminal.optout,
        "prazos": terminal.prazos,
        "editaveis": ["corpo"],
        "editado": bool(override.get("corpo")),
    }


def _reservado_json(chave: str, override: dict | None) -> dict:
    """O nudge e o rótulo do botão de lista: texto que o lead LÊ e não é de nó nenhum.

    `valeria_flow_content` é chaveada por `node_id`, então os dois têm chave
    reservada no registry (`CHAVE_NUDGE`, `CHAVE_ROTULO_LISTA`) e entram pela MESMA
    fresta de qualquer nó — sem segundo mecanismo de armazenamento.
    """
    override = override or {}
    if chave == reg.CHAVE_NUDGE:
        padrao, rotulo_interno, limite = reg.CORPO_NUDGE, "Reoferecimento (nudge)", None
    else:
        padrao, rotulo_interno = reg.ROTULO_BOTAO_LISTA, "Botão que abre a folha de opções"
        limite = reg.LIMITE_ROTULO_BOTAO

    atual = override.get("corpo")
    item = {
        "chave": chave,
        "id": chave,
        "tipo": "reservado",
        "rotulo_interno": rotulo_interno,
        "corpo": atual if atual else padrao,
        "corpo_default": padrao,
        "editaveis": ["corpo"],
        "editado": bool(atual),
    }
    if limite is not None:
        item["limite"] = limite
    if chave == reg.CHAVE_NUDGE:
        item["teto"] = reg.TETO_NUDGES
    return item


def _item_json(node_id: str, override: dict | None) -> dict:
    """Despacha para o serializador do tipo de `node_id`. 404 se não existir."""
    if node_id in reg.NOS:
        return _no_json(node_id, override)
    if node_id in reg.TERMINAIS:
        return _terminal_json(node_id, override)
    if node_id in (reg.CHAVE_NUDGE, reg.CHAVE_ROTULO_LISTA):
        return _reservado_json(node_id, override)
    raise HTTPException(404, f"nó {node_id!r} não existe no fluxo")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/valeria-flow
# ═══════════════════════════════════════════════════════════════════════════════
@router.get("")
async def api_get_fluxo():
    """O fluxo inteiro, com os overrides já aplicados. A tela nunca mescla."""
    overrides = conteudo.carregar(reg.FLOW_ID)
    return {
        "flow_id": reg.FLOW_ID,
        "no_entrada": reg.NO_ENTRADA,
        "limites": {
            "rotulo_botao": reg.LIMITE_ROTULO_BOTAO,
            "titulo_lista": reg.LIMITE_TITULO_LISTA,
            "desc_lista": reg.LIMITE_DESC_LISTA,
            "max_botoes": reg.MAX_BOTOES,
            "max_linhas_lista": reg.MAX_LINHAS_LISTA,
        },
        "editaveis": {"no": ["corpo", "rotulos"], "terminal": ["corpo"]},
        "nos": [_no_json(node_id, overrides.get(node_id)) for node_id in reg.NOS],
        "terminais": [
            _terminal_json(terminal_id, overrides.get(terminal_id))
            for terminal_id in reg.TERMINAIS
        ],
        "nudge": _reservado_json(reg.CHAVE_NUDGE, overrides.get(reg.CHAVE_NUDGE)),
        "rotulo_lista": _reservado_json(
            reg.CHAVE_ROTULO_LISTA, overrides.get(reg.CHAVE_ROTULO_LISTA)
        ),
        # A folha 30/60/90 do `T_ADIAR` é só-leitura mesmo no banco: mora em
        # `flows.PRAZOS`, que a Recuperação também serve, e o número de dias tem de
        # dizer a mesma coisa nos dois fluxos (nota de `reg.BOTOES_PRAZO`).
        "prazos": [
            {
                "id": botao.id,
                "rotulo": botao.rotulo,
                "destino": botao.destino,
                "dias": reg.DIAS_POR_PRAZO.get(botao.id),
                "editavel": False,
            }
            for botao in reg.BOTOES_PRAZO
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/valeria-flow/channels — declarada ANTES de /{node_id}
# ═══════════════════════════════════════════════════════════════════════════════
# Mesma armadilha que `test_node_schema_endpoint_2026_09_16.py` documenta: rota
# estática depois da parametrizada faz "channels" casar como `node_id`. Aqui os
# métodos até divergem (GET vs PUT/DELETE), mas a ordem é gratuita e a regressão não.
@router.get("/channels")
async def api_get_canais():
    """Canais, perfil atual de cada um e o aviso de perfil compartilhado."""
    canais = list_channels() or []

    # Quantos canais apontam para cada perfil. `None` fora da conta de propósito:
    # dois canais sem perfil não compartilham nada, e agrupá-los por None acenderia
    # o aviso onde não há risco nenhum.
    por_perfil: dict[str, list[dict]] = {}
    for canal in canais:
        profile_id = canal.get("agent_profile_id")
        if profile_id:
            por_perfil.setdefault(profile_id, []).append(canal)

    saida = []
    for canal in canais:
        profile_id = canal.get("agent_profile_id")
        perfil = canal.get("agent_profiles") or {}
        irmaos = [
            outro.get("name")
            for outro in por_perfil.get(profile_id or "", [])
            if outro.get("id") != canal.get("id")
        ]
        # `_fluxo_de` e não uma reimplementação: a regra "flow_id NULL =
        # recuperacao_v1" tem UM dono (§2 da migration 20260929), e é o gate do
        # inbound. Duas cópias dela é a divergência que este projeto todo evita.
        fluxo = gate._fluxo_de(perfil.get("kind"), perfil.get("flow_id"))
        saida.append({
            "id": canal.get("id"),
            "name": canal.get("name"),
            "phone": canal.get("phone"),
            "mode": canal.get("mode"),
            "is_active": canal.get("is_active"),
            "agent_profile_id": profile_id,
            "perfil": {
                "id": perfil.get("id"),
                "name": perfil.get("name"),
                "kind": perfil.get("kind") or "llm",
                "flow_id": perfil.get("flow_id"),
            } if perfil else None,
            "perfil_compartilhado": bool(irmaos),
            "compartilhado_com": irmaos,
            "atende_este_fluxo": fluxo == reg.FLOW_ID,
        })

    return {
        "flow_id": reg.FLOW_ID,
        # O kill switch é POR FLUXO: a tela precisa dizer "ativado no canal, mas a
        # chave está off" — apontar o canal sem ligar a chave não faz o bot atender.
        "ligado": flow_config.enabled(reg.FLOW_ID),
        "canais": saida,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/valeria-flow/activate
# ═══════════════════════════════════════════════════════════════════════════════
@router.post("/activate")
async def api_ativar(body: AtivarRequest):
    """Cria um perfil `button_flow` novo e aponta SÓ o canal escolhido para ele."""
    channel_id = (body.channel_id or "").strip()
    if not channel_id:
        raise HTTPException(400, "informe o canal que vai atender pelo fluxo de botões")

    canal = get_channel(channel_id)
    if not canal:
        raise HTTPException(404, f"canal {channel_id} não encontrado")

    nome = (body.nome or "").strip() or f"Valéria Botões · {canal.get('name') or channel_id}"

    # As colunas NOT NULL de `agent_profiles` vão EXPLÍCITAS, mesmo as que têm
    # default, porque os defaults não servem a um perfil sem LLM:
    #   • `model` default 'gpt-4.1' e `base_prompt`/`stages` NOT NULL — um perfil de
    #     botões não tem modelo, prompt nem etapa. Os vazios são o que
    #     `20260820_button_flow_agent.sql` já grava no perfil da Recuperação.
    #   • `prompt_key` default 'valeria_inbound' — e ESSE é o perigoso: omitir a chave
    #     faria o perfil de botões nascer com a persona da ValerIA LLM, e
    #     `get_profile_id_by_prompt_key('valeria_inbound')` resolve com `.limit(1)`
    #     (agent_profiles/service.py), então `buffer/processor.py:361` poderia
    #     devolver ESTE perfil para uma conversa que devia ir ao orquestrador.
    perfil_novo = {
        "name": nome,
        "kind": "button_flow",
        "flow_id": reg.FLOW_ID,
        "prompt_key": "valeria_botoes",
        "model": "",
        "base_prompt": "",
        "stages": {},
    }

    try:
        criado = get_supabase().table("agent_profiles").insert(perfil_novo).execute().data
    except Exception as exc:
        # `flow_id` só existe depois de 20260929. Sem a coluna o perfil não pode
        # nascer, e a spec §10 exige mensagem clara em vez de ativar errado: um
        # perfil `button_flow` sem `flow_id` cai no default `recuperacao_v1` — o
        # fluxo que roda no número pessoal do vendedor e está desligado.
        logger.warning("%s perfil de botões não criado p/ canal %s: %s", _LOG, channel_id, exc)
        raise HTTPException(503, _MSG_MIGRATION) from exc

    if not criado:
        raise HTTPException(503, "o perfil do fluxo de botões não foi criado")

    novo_id = criado[0]["id"]
    # Só o canal escolhido. `update_channel` toca `channels`, nunca `agent_profiles`.
    update_channel(channel_id, {"agent_profile_id": novo_id})
    # O gate cacheia (`kind`, `flow_id`) por 5 minutos; sem isto a troca levaria até
    # 5 min para valer e o operador veria o número mudo achando que ativou.
    limpar_cache_de_perfis()

    logger.info("%s canal %s passou a atender pelo perfil %s (%s)",
                _LOG, channel_id, novo_id, reg.FLOW_ID)
    return {
        "channel_id": channel_id,
        "agent_profile_id": novo_id,
        "flow_id": reg.FLOW_ID,
        "perfil": criado[0],
        "ligado": flow_config.enabled(reg.FLOW_ID),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Leitura e escrita de UMA linha de conteúdo
# ═══════════════════════════════════════════════════════════════════════════════
def _linha_atual(node_id: str) -> dict:
    """A linha de `valeria_flow_content` deste nó, ou `{}`. NÃO é fail-open.

    Ao contrário de `carregar` (que o GET usa e que devolve `{}` em qualquer erro),
    aqui a falha PROPAGA: gravar sem ter lido `rotulos_antigos` sobrescreveria o
    histórico da tela antiga com uma lista vazia, e é esse histórico que faz
    `valeria_engine._casar` aceitar o clique de quem recebeu o rótulo anterior.
    """
    linhas = (
        get_supabase()
        .table(_TABELA)
        .select("id, corpo, rotulos, rotulos_antigos")
        .eq("flow_id", reg.FLOW_ID)
        .eq("node_id", node_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return linhas[0] if linhas else {}


def _override_da_linha(linha: dict) -> dict:
    """A linha no formato que `aplicar`/`aplicar_terminais` consomem."""
    return {
        "corpo": linha.get("corpo"),
        "rotulos": linha.get("rotulos") or {},
        "rotulos_antigos": linha.get("rotulos_antigos") or [],
    }


def _rotulo_no_ar(node_id: str, botao_id: str, rotulos_atuais: dict) -> str | None:
    """O rótulo que o lead está vendo AGORA: o override, ou o default do registry."""
    if botao_id in rotulos_atuais:
        return rotulos_atuais[botao_id]
    no = reg.NOS.get(node_id)
    if no is None:
        return None
    for botao in no.botoes:
        if botao.id == botao_id:
            return botao.rotulo
    return None


def _versionar(node_id: str, novos: dict, atuais: dict, historico: list) -> list:
    """Acrescenta ao histórico os rótulos que estão saindo do ar. Nunca sobrescreve.

    Guarda o PAR (`botao_id`, `rotulo`) porque é disso que o motor precisa: o clique
    de uma tela antiga pode trazer só o texto, e `_casar` usa o mapa
    `rótulo antigo -> id do botão` para achar o botão certo. Só o texto não bastaria.
    """
    acumulado = list(historico or [])
    vistos = {
        (e.get("botao_id"), e.get("rotulo"))
        for e in acumulado
        if isinstance(e, dict)
    }
    agora = datetime.now(timezone.utc).isoformat()
    for botao_id, novo in (novos or {}).items():
        anterior = _rotulo_no_ar(node_id, botao_id, atuais)
        if not anterior or anterior == novo:
            continue
        if (botao_id, anterior) in vistos:
            continue
        acumulado.append({"botao_id": botao_id, "rotulo": anterior, "em": agora})
        vistos.add((botao_id, anterior))
    return acumulado


@router.put("/{node_id}")
async def api_put_conteudo(node_id: str, body: ConteudoUpdate):
    """Grava `corpo`/`rotulos` de um nó, terminal ou chave reservada."""
    # 404 antes de qualquer coisa: `validar` devolveria uma MENSAGEM para nó
    # inexistente, e mensagem de erro de validação é 400 — a tela não distinguiria
    # "seu texto está inválido" de "esse nó não existe mais no fluxo".
    conhecido = (
        node_id in reg.NOS
        or node_id in reg.TERMINAIS
        or node_id in (reg.CHAVE_NUDGE, reg.CHAVE_ROTULO_LISTA)
    )
    if not conhecido:
        raise HTTPException(404, f"nó {node_id!r} não existe no fluxo")

    payload = {"corpo": body.corpo, "rotulos": body.rotulos}
    if body.corpo is None and not body.rotulos:
        raise HTTPException(400, "nada a gravar: informe o corpo ou os rótulos")

    # `rotulos` só é PERSISTIDO em nó (é o único lugar onde `aplicar` o lê). `validar`
    # já recusa rótulo em terminal — "override morto e invisível" é o problema que ele
    # nomeia —, mas as duas chaves reservadas ficam fora daquela checagem porque
    # `validar` volta antes. Quem sabe que a coluna não seria escrita aqui é esta
    # rota, então é esta rota que recusa: um 200 sem gravar seria a tela achando que
    # salvou. Não é o limite da Meta duplicado, é a regra de onde a coluna se aplica.
    if body.rotulos and node_id not in reg.NOS:
        raise HTTPException(400, f"{node_id!r} não tem botões próprios — só o corpo é editável")

    # O portão de gravação é `valeria_content.validar`, e só ele. Duplicar limite da
    # Meta aqui faria a tela recusar por um número e o banco aceitar por outro.
    erro = conteudo.validar(node_id, payload)
    if erro:
        raise HTTPException(400, erro)

    try:
        linha = _linha_atual(node_id)
    except Exception as exc:
        logger.warning("%s conteúdo de %s não lido antes de gravar: %s", _LOG, node_id, exc)
        raise HTTPException(503, _MSG_MIGRATION) from exc

    rotulos_atuais = linha.get("rotulos") or {}
    # `rotulos` é MERGE e não substituição: a tela salva um nó por vez, mas pode
    # mandar só o botão que mudou, e substituir o mapa apagaria os outros rótulos.
    rotulos_finais = {**rotulos_atuais, **(body.rotulos or {})} if body.rotulos else rotulos_atuais
    historico = _versionar(node_id, body.rotulos or {}, rotulos_atuais,
                           linha.get("rotulos_antigos") or [])

    gravar = {
        "flow_id": reg.FLOW_ID,
        "node_id": node_id,
        "corpo": body.corpo if body.corpo is not None else linha.get("corpo"),
        # `rotulos` só é lido em nó: terminal não tem botão próprio (e `validar`
        # recusa) e as duas chaves reservadas guardam o texto em `corpo`.
        "rotulos": (rotulos_finais or None) if node_id in reg.NOS else None,
        "rotulos_antigos": historico,
    }
    try:
        get_supabase().table(_TABELA).upsert(gravar, on_conflict="flow_id,node_id").execute()
    except Exception as exc:
        logger.warning("%s conteúdo de %s não gravado: %s", _LOG, node_id, exc)
        raise HTTPException(503, _MSG_MIGRATION) from exc

    logger.info("%s %s atualizado (corpo=%s, rotulos=%s)",
                _LOG, node_id, body.corpo is not None, sorted((body.rotulos or {})))
    return _item_json(node_id, _override_da_linha(gravar))


@router.delete("/{node_id}")
async def api_delete_conteudo(node_id: str):
    """Apaga o override e devolve o item no default do registry.

    O `rotulos_antigos` NÃO vai embora com ele, e restaurar o default é justamente o
    momento em que ele mais importa: o rótulo editado sai do ar agora, e quem o
    recebeu pode tocar nele depois. Então a linha é ZERADA (`corpo`/`rotulos` nulos,
    que para `aplicar` é indistinguível de linha ausente — `if corpo:` / `if rotulos:`)
    e o rótulo que estava no ar entra no histórico. Sem histórico a guardar, a linha é
    removida de verdade, para a tabela não acumular linha inerte.
    """
    if not (
        node_id in reg.NOS
        or node_id in reg.TERMINAIS
        or node_id in (reg.CHAVE_NUDGE, reg.CHAVE_ROTULO_LISTA)
    ):
        raise HTTPException(404, f"nó {node_id!r} não existe no fluxo")

    try:
        linha = _linha_atual(node_id)
    except Exception as exc:
        logger.warning("%s conteúdo de %s não lido antes de restaurar: %s", _LOG, node_id, exc)
        raise HTTPException(503, _MSG_MIGRATION) from exc

    if linha:
        rotulos_atuais = linha.get("rotulos") or {}
        # Os rótulos do REGISTRY são os "novos" aqui: é para eles que a tela volta.
        voltando = {}
        no = reg.NOS.get(node_id)
        if no is not None:
            voltando = {b.id: b.rotulo for b in no.botoes if b.id in rotulos_atuais}
        historico = _versionar(node_id, voltando, rotulos_atuais,
                               linha.get("rotulos_antigos") or [])
        try:
            tabela = get_supabase().table(_TABELA)
            if historico:
                (
                    tabela.update({"corpo": None, "rotulos": None,
                                   "rotulos_antigos": historico})
                    .eq("flow_id", reg.FLOW_ID).eq("node_id", node_id).execute()
                )
            else:
                (
                    tabela.delete()
                    .eq("flow_id", reg.FLOW_ID).eq("node_id", node_id).execute()
                )
        except Exception as exc:
            logger.warning("%s override de %s não removido: %s", _LOG, node_id, exc)
            raise HTTPException(503, _MSG_MIGRATION) from exc

    logger.info("%s %s restaurado ao default do registry", _LOG, node_id)
    return _item_json(node_id, None)
