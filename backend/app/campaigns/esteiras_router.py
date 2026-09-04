"""API achatada das esteiras do vendedor — o que a aba `/campanhas > Esteiras` consome.

CONTRATO — e o que o frontend consome; mudar qualquer linha abaixo quebra a tela.

  GET  /api/automation/esteiras
       200 { "esteiras": [ {
              key, campaign_id, nome, descricao, ativa, canal_id,
              funil_id, etapa_id, etapa_key,
              relogio: "silence_days"|"stage_days",   ← rotulo do prazo do toque 1
              gatilho: {…config do no de gatilho: last_speaker, stage_days, …},
              toques: [ {ordem, dias, template_name} ], acao_final, stage_id_perdido
            } ] }                      sempre as 4, mesmo antes do seed rodar

  PUT  /api/automation/esteiras/{key}
       corpo (todos os campos opcionais — a escrita e PARCIAL):
            { ativa, canal_id, funil_id, etapa_id,
              toques: [ {ordem, dias, template_name} ], stage_id_perdido }
       200 { "ok": true, "aviso": null|str, "stage_id_perdido": null|str }
            `aviso` e texto para mostrar na tela: gravou, mas com uma ressalva.
       400 corpo invalido, ligar sem etapa de gatilho (regra 1) ou sem canal (regra 2),
           etapa que nao pertence ao funil escolhido, ou primeiro toque com menos de
           1 dia (regra 6) — a mensagem vai em `detail`
       404 key desconhecida
       409 a campanha ainda nao existe no banco (o seed do startup nao rodou)

O frontend NAO conhece o formato do grafo de `campaign_nodes`. Este modulo traduz nos
dois sentidos, e a escrita so mexe em PARAMETRO (dias, template, canal, funil, etapa) —
nunca na topologia. Quem quiser mudar a FORMA do fluxo usa o builder de Cadencias.

## Seis regras que este arquivo existe para garantir

1. **Ligar exige etapa de gatilho.** Na RPC `get_deals_stage_stagnant`,
   `p_stage_id IS NULL` **e** `p_stage_key IS NULL` significam "sem filtro de etapa" —
   fail-open. Uma esteira ligada antes de configurada ficaria elegivel a *todo card
   aberto de todo funil*, 20 por tick, repetindo. O `status='draft'` do seed protege
   so ate o primeiro clique. A checagem roda sobre o gatilho JA COM o corpo aplicado:
   um PUT que traz etapa e `ativa: true` junto passa — o usuario configura e liga numa
   tacada so. E, como a validacao acontece antes de qualquer escrita, PUT recusado nao
   grava nada pela metade.

1b. **Ligar exige canal.** A regra 1 sozinha nao basta: a esteira de proposta nasce do
   seed com `stage_key='proposta_enviada'`, entao ela ja passaria na checagem de etapa
   antes de o dono escolher canal nenhum. E sem `campaigns.channel_id` caem DUAS
   protecoes de uma vez:

   - `_conversation_followup_disabled(lead, None)` devolve `False` sem consultar nada —
     a flag "Finalizar Conversa" que o vendedor marca em /conversas passa a ser
     ignorada, tanto na inscricao quanto na execucao. A esteira escreve por cima de
     conversa que ele fechou a mao.
   - `_execute_send_node` cai em `get_channel_for_lead`, que devolve o canal da conversa
     ATIVA MAIS RECENTE — pode ser o numero da Valeria. Um template assinado "Aqui e o
     Joao" sairia do numero da IA, numa conversa que o vendedor nao acompanha.

   Como a da etapa, roda sobre o valor JA COM o corpo aplicado (escolher canal e ligar
   no mesmo PUT passa) e antes de qualquer escrita.

2. **A etapa de Perdido da reposicao e resolvida aqui, nao digitada.** O seed nasce com
   `stage_id: None` no `mark_deal_lost` e `engine._execute_action` retorna cedo sem ele:
   a esteira faria os tres toques e terminaria SEM mover o card — o oposto da decisao do
   dono. E a tela mostra a acao final como texto fixo, entao ninguem preencheria esse
   campo a mao. Ao gravar o funil, resolvemos a etapa de perda com o mesmo
   `leads.service._perdido_stage_id` que a soft-rejection usa (mesmo vocabulario de
   keys, mesmo fallback). Funil sem etapa de perda NAO falha o PUT: grava o resto e
   devolve `aviso` — bloquear a configuracao inteira por causa disso seria pior. Trocar
   de funil sem etapa de perda no novo APAGA a etapa antiga: mover o card para uma
   coluna de outro funil o faria sumir do Kanban de origem; virar no-op e o mal menor.

3. **A leitura segue o GRAFO, nao a ordem do banco.** O seed insere os nos em ordem
   topologica REVERSA (o FK `next_node_id` exige o alvo antes), entao confiar na ordem
   devolvida pelo PostgREST inverteria os toques na tela.

4. **A escrita e parcial e nao destrutiva.** O `config` gravado nasce do que esta NO
   BANCO, nao do seed. Ler do seed faria um `{"ativa": false}` devolver o gatilho aos
   defaults (`stage_id: None`), apagando a configuracao do dono.

5. **Etapa e funil tem de casar.** A RPC filtra pelos dois; a combinacao errada nao
   levanta erro nenhum, so para de achar card. Uma esteira ligada e muda e pior do que
   um 400 na hora de salvar.

6. **O primeiro toque espera no minimo 1 dia.** Ele nao grava numa espera: grava no
   GATILHO, no relogio que `_relogio()` escolheu. Na esteira de proposta o campo escreve
   `stage_days` e `silence_days` ja e 0 no seed — gravar 0 zera os dois, e a RPC entao
   nao aplica filtro temporal nenhum: todo card em "Proposta Enviada" fica elegivel no
   proximo tick, inclusive a proposta enviada ha cinco minutos. As esperas ENTRE toques
   continuam aceitando 0 (ali 0 so quer dizer "no mesmo ciclo").
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from app.campaigns.esteiras import ESTEIRAS
from app.db.supabase import get_supabase
from app.leads.service import _perdido_stage_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/automation/esteiras", tags=["esteiras"])

_POR_KEY = {e["key"]: e for e in ESTEIRAS}
_ACAO_PERDIDO = "mark_deal_lost"
_COLUNAS_NO = "id, campaign_id, type, config, next_node_id"
_MAX_DIAS = 365
# Regra 6: o toque 1 grava no gatilho, e gatilho com relogio zerado nao filtra tempo
# nenhum. As esperas entre toques nao mexem no gatilho — ali 0 e legitimo.
_MIN_DIAS_PRIMEIRO_TOQUE = 1


# ── Traducao grafo → tela ────────────────────────────────────────────────────────


def _gatilho_do_seed(esteira: dict) -> dict:
    return next(n for n in esteira["nodes"] if n["type"] == "trigger")


def _relogio(esteira: dict) -> str:
    """Qual campo do gatilho e o prazo do primeiro toque.

    Depende da esteira: a de proposta conta dias NA ETAPA (`stage_days`), as outras
    contam dias de SILENCIO. A decisao vem do SEED, nao do valor atual — se viesse do
    valor, gravar `dias: 0` uma vez trocaria o relogio da esteira em silencio.
    """
    return "stage_days" if _gatilho_do_seed(esteira)["config"].get("stage_days") else "silence_days"


def _nos_ordenados(esteira: dict, linhas: list[dict]) -> list[dict]:
    """Nos da esteira em ordem de execucao, seguindo `next_node_id` a partir do gatilho.

    Cai nos nos do seed quando o banco ainda nao tem nenhum (seed nao rodou) e completa
    com o do seed qualquer no que falte, para a tela nunca aparecer vazia.
    """
    por_id = {linha["id"]: linha for linha in linhas}
    if not por_id:
        return [dict(n) for n in esteira["nodes"]]

    inicio = _gatilho_do_seed(esteira)["id"]
    if inicio not in por_id:
        inicio = next((linha["id"] for linha in linhas if linha.get("type") == "trigger"), "")
    if not inicio:
        return [por_id.get(n["id"], dict(n)) for n in esteira["nodes"]]

    ordem: list[dict] = []
    vistos: set[str] = set()
    atual: str | None = inicio
    while atual and atual in por_id and atual not in vistos:
        vistos.add(atual)
        no = por_id[atual]
        ordem.append(no)
        atual = no.get("next_node_id")
    return ordem


def _achatar(esteira: dict, campanha: dict, nos: list[dict]) -> dict[str, Any]:
    tcfg = (next((n for n in nos if n["type"] == "trigger"), {}) or {}).get("config") or {}
    envios = [n for n in nos if n["type"] == "send"]
    esperas = [n for n in nos if n["type"] == "wait"]
    acoes = [n for n in nos if n["type"] == "action"]
    relogio = _relogio(esteira)

    toques = []
    for i, envio in enumerate(envios):
        if i == 0:
            dias = tcfg.get(relogio)
            if dias is None:  # gatilho editado no builder: aceita o outro relogio
                dias = tcfg.get("silence_days") or tcfg.get("stage_days") or 0
        else:
            espera = esperas[i - 1] if i - 1 < len(esperas) else {}
            dias = (espera.get("config") or {}).get("days", 0)
        toques.append({
            "ordem": i + 1,
            "dias": dias,
            "template_name": (envio.get("config") or {}).get("template_name"),
        })

    acao = (acoes[0].get("config") or {}) if acoes else {}
    return {
        "key": esteira["key"],
        # Link "abrir no builder" (/campanhas/cadencias/{id}). Sem ele a tela teria de
        # achar a campanha por (nome, env_tag) — e renomear no builder e exatamente o
        # que a decisao do dono ("eles editam sozinhos") convida a acontecer.
        "campaign_id": esteira["campaign_id"],
        # Config crua do gatilho: a tela escreve a regra em portugues a partir dela
        # ("15 dias sem conversa, nao importa quem falou por ultimo"). Sem
        # `last_speaker` as duas esteiras de "Novo" ficam identicas na tela — o falante
        # e a UNICA coisa que as separa.
        "gatilho": dict(tcfg),
        # Que relogio o primeiro toque usa — a tela rotula "dias NA ETAPA" (proposta)
        # ou "dias SEM RESPOSTA" (as outras). Sem isso o mesmo numero significa duas
        # coisas diferentes na mesma tela.
        "relogio": relogio,
        "nome": esteira["name"],
        "descricao": esteira["description"],
        "ativa": campanha.get("status") == "active",
        "canal_id": campanha.get("channel_id"),
        "funil_id": tcfg.get("pipeline_id"),
        "etapa_id": tcfg.get("stage_id"),
        "etapa_key": tcfg.get("stage_key"),
        "toques": toques,
        "acao_final": acao.get("action_type"),
        # So a esteira de reposicao move card. Nas outras vem None e a tela mostra o
        # texto fixo do alerta.
        "stage_id_perdido": acao.get("stage_id") if acao.get("action_type") == _ACAO_PERDIDO else None,
    }


@router.get("")
async def listar_esteiras() -> dict[str, Any]:
    sb = get_supabase()
    ids = [e["campaign_id"] for e in ESTEIRAS]
    campanhas = {
        c["id"]: c for c in
        (sb.table("campaigns").select("id, status, channel_id").in_("id", ids).execute().data or [])
    }
    nos_por_campanha: dict[str, list[dict]] = {}
    for no in (sb.table("campaign_nodes").select(_COLUNAS_NO)
               .in_("campaign_id", ids).execute().data or []):
        nos_por_campanha.setdefault(no["campaign_id"], []).append(no)

    return {"esteiras": [
        _achatar(e, campanhas.get(e["campaign_id"]) or {},
                 _nos_ordenados(e, nos_por_campanha.get(e["campaign_id"]) or []))
        for e in ESTEIRAS
    ]}


# ── Traducao tela → grafo ────────────────────────────────────────────────────────


def _prazo(toque: dict, ordem: int) -> int | None:
    """Prazo do toque em dias. None quando o corpo nao trouxe o campo (preserva o atual).

    O piso muda com a posicao (regra 6): o toque 1 escreve no GATILHO e zero ali desliga
    o filtro temporal da RPC inteira; do toque 2 em diante o numero vira uma espera entre
    envios, onde 0 so quer dizer "no mesmo ciclo".
    """
    if not isinstance(toque, dict) or "dias" not in toque:
        return None
    valor = toque["dias"]
    try:
        dias = int(valor)
    except (TypeError, ValueError):
        raise HTTPException(400, f"prazo invalido no toque {ordem}: {valor!r}")
    minimo = _MIN_DIAS_PRIMEIRO_TOQUE if ordem == 1 else 0
    if dias < minimo or dias > _MAX_DIAS:
        if ordem == 1:
            raise HTTPException(
                400,
                "o primeiro toque tem de esperar pelo menos 1 dia (e no maximo "
                f"{_MAX_DIAS}): com 0 o gatilho fica sem filtro de tempo e a esteira "
                "pega todo card que estiver na etapa, inclusive o que acabou de chegar.",
            )
        raise HTTPException(400, f"prazo do toque {ordem} tem de estar entre 0 e {_MAX_DIAS} dias")
    return dias


def _grava_config(sb, node_id: str, config: dict) -> None:
    sb.table("campaign_nodes").update({"config": config}).eq("id", node_id).execute()


def _etapa_pertence_ao_funil(sb, stage_id: str, pipeline_id: str) -> bool | None:
    """A etapa e daquele funil? None quando nao da para saber (etapa desconhecida/erro).

    Fail-open de proposito: a checagem existe para pegar o erro de digitacao da tela,
    nao para virar mais um jeito de o PUT falhar quando o Supabase oscila.
    """
    try:
        linhas = (sb.table("pipeline_stages").select("id, pipeline_id")
                  .eq("id", stage_id).limit(1).execute().data or [])
    except Exception as exc:
        logger.warning("[ESTEIRAS] nao deu para conferir a etapa %s: %s", stage_id, exc)
        return None
    return linhas[0].get("pipeline_id") == pipeline_id if linhas else None


def _resolver_perdido(sb, body: dict, tcfg: dict, acao: dict | None,
                      funil_mudou: bool) -> tuple[str | None, bool, str | None]:
    """(stage_id de Perdido, limpar o que estava la, aviso) para a acao `mark_deal_lost`.

    Regra 2 da docstring do modulo. `limpar` existe para o caso de troca de funil sem
    etapa de perda no novo: manter o stage_id do funil ANTIGO faria a esteira mover o
    card para uma coluna de outro funil — ele sumiria do Kanban de origem. Virar no-op
    (que e o comportamento do motor sem stage_id) e o mal menor.
    """
    if acao is None:
        return None, False, None
    explicito = body.get("stage_id_perdido") or None
    if explicito:
        return explicito, False, None

    ja_gravado = (acao.get("config") or {}).get("stage_id")
    funil = tcfg.get("pipeline_id")
    sem_etapa = (
        "O funil escolhido nao tem etapa de Perdido (keys 'perdido', 'fechado_perdido' "
        "ou 'encerrado'). A esteira vai enviar os toques e terminar SEM mover o card. "
        "Crie a etapa no funil e salve de novo."
    )
    if not funil:
        # Funil removido: o que estava gravado e de outro funil.
        return (None, True, sem_etapa) if (funil_mudou and ja_gravado) else (None, False, None)
    if "funil_id" not in body and ja_gravado:
        return None, False, None  # nada a decidir: o funil nao mudou e a etapa ja esta la
    try:
        resolvido = _perdido_stage_id(sb, funil)
    except Exception as exc:  # nunca derruba a configuracao inteira
        logger.warning("[ESTEIRAS] falha ao resolver etapa de Perdido de %s: %s", funil, exc)
        resolvido = None
    if resolvido:
        return resolvido, False, None
    return None, bool(funil_mudou and ja_gravado), sem_etapa


@router.put("/{key}")
async def gravar_esteira(key: str, body: dict = Body(...)) -> dict[str, Any]:
    esteira = _POR_KEY.get(key)
    if not esteira:
        raise HTTPException(404, f"esteira '{key}' nao existe")
    if not isinstance(body, dict):
        raise HTTPException(400, "corpo invalido")

    sb = get_supabase()
    cid = esteira["campaign_id"]

    campanha = (sb.table("campaigns").select("id, status, channel_id")
                .eq("id", cid).limit(1).execute().data or [])
    linhas = (sb.table("campaign_nodes").select(_COLUNAS_NO)
              .eq("campaign_id", cid).execute().data or [])
    nos = _nos_ordenados(esteira, linhas)
    gatilho = next((n for n in nos if n["type"] == "trigger"), None)
    ids_no_banco = {linha["id"] for linha in linhas}
    if not campanha or gatilho is None or gatilho["id"] not in ids_no_banco:
        # Update em linha inexistente e no-op silencioso no PostgREST: a tela acharia
        # que gravou. O seed roda no startup da API (main.lifespan) e e fail-soft —
        # se a migration 20260904 nao foi aplicada, ele falha e cai exatamente aqui.
        raise HTTPException(
            409,
            f"a esteira '{key}' ainda nao existe no banco — o seed roda no startup da API "
            "e pode ter falhado (migration 20260904 aplicada?). Reinicie a API e tente de novo.",
        )

    # ── 1. Aplica o corpo sobre o que ESTA no banco (nunca sobre o seed) ──────────
    toques = body.get("toques") or []
    if not isinstance(toques, list):
        raise HTTPException(400, "'toques' tem de ser uma lista")
    # Todos os prazos sao validados ANTES de qualquer escrita: prazo invalido no toque
    # 3 nao pode deixar os toques 1 e 2 gravados.
    prazos = [_prazo(t, i + 1) for i, t in enumerate(toques)]

    cfg_atual = gatilho.get("config") or {}
    tcfg = dict(cfg_atual)
    if "funil_id" in body:
        tcfg["pipeline_id"] = body["funil_id"] or None
    if "etapa_id" in body:
        tcfg["stage_id"] = body["etapa_id"] or None
    if prazos and prazos[0] is not None:
        tcfg[_relogio(esteira)] = prazos[0]
    funil_mudou = "funil_id" in body and tcfg.get("pipeline_id") != cfg_atual.get("pipeline_id")

    # ── 2. Etapa e funil tem de casar ────────────────────────────────────────────
    # A RPC filtra por etapa E funil: a combinacao errada nao levanta erro nenhum, so
    # para de achar card. Esteira ligada e muda e pior do que um 400 na hora de salvar.
    if ("funil_id" in body or "etapa_id" in body) and tcfg.get("stage_id") and tcfg.get("pipeline_id"):
        if _etapa_pertence_ao_funil(sb, tcfg["stage_id"], tcfg["pipeline_id"]) is False:
            raise HTTPException(
                400, "a etapa de gatilho escolhida nao pertence ao funil selecionado — "
                     "escolha a etapa de novo depois de trocar o funil.",
            )

    # ── 3. Regra 1: ligar exige etapa (stage_id OU stage_key) ────────────────────
    if body.get("ativa") and not (tcfg.get("stage_id") or tcfg.get("stage_key")):
        raise HTTPException(
            400,
            f"escolha a etapa de gatilho antes de ligar a esteira '{esteira['name']}': "
            "sem etapa o gatilho fica valendo para todo card aberto de todo funil "
            "(a RPC trata etapa vazia como 'sem filtro').",
        )

    # ── 3b. Regra 1b: ligar exige canal ──────────────────────────────────────────
    # Sem canal a esteira nao fica muda (como no caso da etapa) — fica falante no lugar
    # errado, e por dois caminhos independentes. Ver a regra 1b da docstring do modulo.
    # Como a etapa, o valor do CORPO vale antes da checagem: escolher canal e ligar no
    # mesmo PUT passa, e nada foi gravado ate aqui.
    canal = body["canal_id"] or None if "canal_id" in body else campanha[0].get("channel_id")
    if body.get("ativa") and not canal:
        raise HTTPException(
            400,
            f"escolha o canal antes de ligar a esteira '{esteira['name']}': e o numero de "
            "onde a mensagem sai. Sem ele a esteira envia pelo canal da conversa mais "
            "recente do lead — que pode ser o da Valeria, assinando como o vendedor — e "
            "ignora as conversas que o vendedor ja finalizou a mao em /conversas.",
        )

    # ── 4. Regra 2: etapa de Perdido resolvida pela API ──────────────────────────
    acao_perdido = next(
        (n for n in nos if n["type"] == "action"
         and (n.get("config") or {}).get("action_type") == _ACAO_PERDIDO),
        None,
    )
    stage_perdido, limpar_perdido, aviso = _resolver_perdido(
        sb, body, tcfg, acao_perdido, funil_mudou)

    # ── 5. Escritas ──────────────────────────────────────────────────────────────
    linha_campanha: dict[str, Any] = {}
    if "ativa" in body:
        linha_campanha["status"] = "active" if body["ativa"] else "draft"
    if "canal_id" in body:
        linha_campanha["channel_id"] = body["canal_id"] or None
    if linha_campanha:
        sb.table("campaigns").update(linha_campanha).eq("id", cid).execute()

    if tcfg != cfg_atual:
        _grava_config(sb, gatilho["id"], tcfg)

    envios = [n for n in nos if n["type"] == "send"]
    esperas = [n for n in nos if n["type"] == "wait"]
    for i, toque in enumerate(toques):
        # Toque a mais do que a esteira tem e IGNORADO: a tela nao cria no.
        if i < len(envios) and isinstance(toque, dict) and toque.get("template_name"):
            cfg = dict(envios[i].get("config") or {})
            cfg["template_name"] = toque["template_name"]
            _grava_config(sb, envios[i]["id"], cfg)
        # O prazo do toque N>1 e a espera ANTERIOR a ele.
        if i > 0 and i - 1 < len(esperas) and prazos[i] is not None:
            cfg = dict(esperas[i - 1].get("config") or {})
            cfg["days"] = prazos[i]
            _grava_config(sb, esperas[i - 1]["id"], cfg)

    if acao_perdido is not None and (stage_perdido or limpar_perdido):
        cfg = dict(acao_perdido.get("config") or {})
        cfg["stage_id"] = stage_perdido  # None quando limpando a etapa do funil antigo
        _grava_config(sb, acao_perdido["id"], cfg)

    logger.info(
        "[ESTEIRAS] '%s' atualizada: %s%s", key,
        {k: v for k, v in body.items() if k != "toques"},
        f" +{len(toques)} toque(s)" if toques else "",
    )
    return {"ok": True, "aviso": aviso, "stage_id_perdido": stage_perdido}
