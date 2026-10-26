"""Reconciliacao diaria Bling x banco, POR CONTA e POR DIA (Fase 3 da avaliacao
2026-10-13).

E o que transforma "achamos que esta sincronizado" em "conferido ate ontem".
Uma vez por dia por conta (de madrugada, horario de Brasilia, no mesmo tick da
varredura e sob a mesma trava `bling:pedidos:{conta}`):
  1. lista os pedidos do Bling dos ultimos `DIAS_PADRAO` dias fechados
     (ate ontem), pela data do pedido — `dataInicial`/`dataFinal`, o mesmo
     filtro que o backfill ja usa em producao;
  2. le as vendas do banco da conta no mesmo intervalo;
  3. compara POR DIA (dia de Brasilia): quantidade, soma do total e conjunto
     de ids (faltando no banco, sobrando no banco, mesmo id com valor diferente,
     mesmo id com situacao diferente);
  4. dia divergente -> reimporta so os ids envolvidos (detalhe + contato sob
     demanda + upsert) e confere de novo;
  5. grava o resultado de TODOS os dias em `bling_reconciliacao`
     (status ok | reimportado | divergente) e alerta (`system_alerts`,
     `bling_reconciliacao_divergente`) se algum dia continuar divergente.

Pedido que sobra no banco e da 404 no Bling (apagado no ERP, G10) NAO e
cancelado aqui: fica em `divergentes.apagados_no_bling` e o dia continua
divergente ate o dono decidir. Mudar status de venda sozinho por ausencia na
listagem e decisao de negocio, nao de sincronia.

EXCECAO (revisao 2026-10-13): se a venda JA esta `cancelada` no banco (o
`order.deleted` chegou, ou alguem cancelou), nao ha nada a decidir: o dia fica
`ok` com `divergentes.observacao = "apagado"` e o id em `apagados_no_bling`.
Esse registro e a memoria: nas noites seguintes o mesmo id (ainda cancelado) nao
e reimportado de novo nem alerta.

Erro SISTEMICO na reimportacao (429, 5xx, timeout, token, teto diario) para a
reimportacao e NAO grava nada nem marca a conta como reconciliada hoje: o
proximo tick tenta de novo. Gravar "divergente" ali seria culpar o dado por uma
falha da API.

Redis fora (sem a trava): WARNING a cada pulo e alerta
`bling_redis_indisponivel` depois de `trava.PULOS_PARA_ALERTAR` pulos seguidos.

A comparacao conta TODAS as vendas com o pedido (inclusive canceladas), porque
a listagem do Bling tambem traz todas as situacoes. `value` x `total` do Bling.

Situacao (1e6381fe): `situacao.id` da listagem diferente de
`sales.bling_situacao_id` tambem e divergencia e o pedido e reimportado. E assim
que um cancelamento no Bling chega ao CRM em ate 1 dia mesmo sem webhook. Se um
dos lados nao tem a situacao, nao ha o que comparar.
"""
import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.bling import config, pedido_import
from app.bling.alertas import alertar
from app.bling.errors import (
    BlingAuthError, BlingNotConfigured, BlingRateLimitError, BlingServerError,
    BlingValidationError,
)
from app.bling.sync import _load_sync_state, _save_sync_state
from app.bling.trava import (
    PULOS_PARA_ALERTAR, RedisIndisponivel, TravaOcupada, registrar_pulo_sem_redis,
    trava_pedidos, zerar_pulos_sem_redis,
)
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

RESOURCE = "reconciliacao"
DIAS_PADRAO = 35
# Roda a partir das 03:00 de Brasilia: o dia anterior ja fechou para os dois
# CNPJs e a madrugada e o horario de menor uso da API.
HORA_BRT = 3
_TZ = ZoneInfo("America/Sao_Paulo")
_TOLERANCIA = Decimal("0.01")
_TRAVA_TTL = 3600
# Pagina da leitura de `sales`: o PostgREST corta em `max_rows` (1000 no
# Supabase) SEM erro, e um `.limit(10000)` devolveria 1000 linhas em silencio.
_PAGINA = 1000
_SISTEMICOS = (BlingAuthError, BlingNotConfigured, BlingRateLimitError, BlingServerError)
OBS_APAGADO = "apagado"


def _new_client(account: str):
    from app.bling.client import BlingClient
    return BlingClient(account=account)


def _carregar_estado(conta: str) -> dict | None:
    return _load_sync_state(RESOURCE, conta)


def _salvar_estado(conta: str, quando: str) -> None:
    _save_sync_state(RESOURCE, conta, last_sync_at=quando)


def _vendas_do_banco(conta: str, inicio: date, fim: date) -> list[dict]:
    """Vendas com pedido Bling da conta com `sold_at` em [inicio, fim].

    `sold_at` de venda Bling e `<data do pedido>T12:00:00-03:00`, meio-dia de
    Brasilia (`_sold_at_iso` e `create_order`). As vendas antigas, gravadas a
    `T12:00:00+00:00` (09:00 BRT), caem no mesmo dia em Brasilia. Os limites
    sao os do dia de Brasilia.

    Paginada por `range` com ordem estavel (`bling_order_id`): ver `_PAGINA`.
    """
    vendas: list[dict] = []
    while True:
        res = (get_supabase().table("sales")
               .select("bling_order_id, sold_at, value, status, bling_situacao_id")
               .eq("bling_account", conta)
               .not_.is_("bling_order_id", "null")
               .gte("sold_at", f"{inicio.isoformat()}T00:00:00-03:00")
               .lt("sold_at", f"{(fim + timedelta(days=1)).isoformat()}T00:00:00-03:00")
               .order("bling_order_id")
               .range(len(vendas), len(vendas) + _PAGINA - 1).execute())
        pagina = getattr(res, "data", None) or []
        vendas.extend(pagina)
        if len(pagina) < _PAGINA:
            return vendas


def _apagados_conhecidos(conta: str, inicio: date, fim: date) -> set[int]:
    """Ids que uma reconciliacao anterior ja confirmou como apagados no Bling
    (404) e cancelados no banco (`observacao = "apagado"`)."""
    res = (get_supabase().table("bling_reconciliacao")
           .select("dia, divergentes")
           .eq("account", conta)
           .gte("dia", inicio.isoformat()).lte("dia", fim.isoformat())
           .execute())
    ids: set[int] = set()
    for linha in getattr(res, "data", None) or []:
        detalhe = linha.get("divergentes") or {}
        if detalhe.get("observacao") == OBS_APAGADO:
            ids.update(int(i) for i in detalhe.get("apagados_no_bling") or [])
    return ids


def _gravar(linhas: list[dict]) -> None:
    if linhas:
        (get_supabase().table("bling_reconciliacao")
         .upsert(linhas, on_conflict="account,dia").execute())


def _dec(valor) -> Decimal:
    return Decimal(str(valor or 0))


def _situacao_id(valor) -> int | None:
    try:
        return int(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _por_dia_bling(pedidos: list[dict]) -> dict[str, dict[int, Decimal]]:
    dias: dict[str, dict[int, Decimal]] = defaultdict(dict)
    for p in pedidos:
        dias[str(p.get("data") or "")[:10]][int(p["id"])] = _dec(p.get("total"))
    return dias


def _situacoes_bling(pedidos: list[dict]) -> dict[int, int | None]:
    """`situacao.id` de cada pedido da listagem (paralelo a `_por_dia_bling`)."""
    return {int(p["id"]): _situacao_id((p.get("situacao") or {}).get("id")) for p in pedidos}


def _dia_brt(sold_at) -> str:
    """Dia de Brasilia de um `sold_at`. Nao usar o `[:10]` da string: e o dia
    no offset em que veio gravado (UTC), nao o de Brasilia."""
    texto = str(sold_at or "")
    try:
        instante = datetime.fromisoformat(texto)
    except ValueError:
        return texto[:10]
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(_TZ).date().isoformat()


def _por_dia_banco(vendas: list[dict]) -> dict[str, dict[int, Decimal]]:
    dias: dict[str, dict[int, Decimal]] = defaultdict(dict)
    for v in vendas:
        dias[_dia_brt(v.get("sold_at"))][int(v["bling_order_id"])] = _dec(v.get("value"))
    return dias


def _situacoes_banco(vendas: list[dict]) -> dict[int, int | None]:
    """`bling_situacao_id` de cada venda (paralelo a `_por_dia_banco`)."""
    return {int(v["bling_order_id"]): _situacao_id(v.get("bling_situacao_id")) for v in vendas}


def _comparar(bling: dict[int, Decimal], banco: dict[int, Decimal],
              sit_bling: dict[int, int | None] | None = None,
              sit_banco: dict[int, int | None] | None = None) -> dict:
    sit_bling, sit_banco = sit_bling or {}, sit_banco or {}
    comuns = set(bling) & set(banco)
    return {
        "faltando": sorted(set(bling) - set(banco)),
        "sobrando": sorted(set(banco) - set(bling)),
        "valor_diferente": sorted(i for i in comuns
                                  if abs(bling[i] - banco[i]) > _TOLERANCIA),
        # Situacao nula de um dos lados nao e divergencia: nao ha o que comparar.
        "situacao_diferente": sorted(
            i for i in comuns
            if sit_bling.get(i) is not None and sit_banco.get(i) is not None
            and sit_bling[i] != sit_banco[i]),
    }


def _diverge(d: dict) -> bool:
    return bool(d["faltando"] or d["sobrando"] or d["valor_diferente"]
                or d.get("situacao_diferente"))


def _soma(valores: dict[int, Decimal]) -> float:
    return float(sum(valores.values(), Decimal("0")))


async def reconciliar_conta(account: str, *, hoje: date | None = None,
                            dias: int | None = None) -> dict:
    """Reconcilia os ultimos `dias` dias FECHADOS (ate ontem, BRT) da conta."""
    conta = config.account(account).key
    hoje = hoje or datetime.now(_TZ).date()
    dias = dias or DIAS_PADRAO
    fim = hoje - timedelta(days=1)
    inicio = hoje - timedelta(days=dias)
    resultado: dict = {"conta": conta, "inicio": inicio.isoformat(), "fim": fim.isoformat()}

    try:
        async with trava_pedidos(conta, _TRAVA_TTL):
            zerar_pulos_sem_redis(RESOURCE, conta)
            async with _new_client(conta) as client:
                return await _reconciliar(client, conta, inicio, fim, resultado)
    except RedisIndisponivel as exc:
        pulos = registrar_pulo_sem_redis(RESOURCE, conta)
        logger.warning("[BLING RECONCILIACAO] conta %s pulada: Redis indisponivel "
                       "(%d seguida(s)): %s", conta, pulos, exc)
        if pulos >= PULOS_PARA_ALERTAR:
            alertar("bling_redis_indisponivel", conta,
                    "Reconciliacao Bling parada: Redis indisponivel",
                    f"{pulos} tentativas seguidas sem a trava bling:pedidos (Redis fora). "
                    "A conferencia Bling x CRM nao esta rodando.",
                    metadata={"job": RESOURCE, "pulos": pulos})
        resultado["status"] = "sem_redis"
        return resultado
    except TravaOcupada as exc:
        logger.info("[BLING RECONCILIACAO] conta %s pulada: %s", conta, exc)
        resultado["status"] = "ocupado"
        return resultado


async def _reconciliar(client, conta: str, inicio: date, fim: date, resultado: dict) -> dict:
    try:
        pedidos = [p async for p in client.paginate(
            "/pedidos/vendas", {"dataInicial": inicio.isoformat(), "dataFinal": fim.isoformat()})]
    except Exception as exc:  # noqa: BLE001 — sem a lista do Bling nao ha o que comparar
        logger.warning("[BLING RECONCILIACAO] conta %s: listagem falhou: %s", conta, exc)
        resultado.update(status="erro", erro=str(exc))
        return resultado

    bling = _por_dia_bling(pedidos)
    sit_bling = _situacoes_bling(pedidos)
    vendas = await asyncio.to_thread(_vendas_do_banco, conta, inicio, fim)
    banco = _por_dia_banco(vendas)
    sit_banco = _situacoes_banco(vendas)
    todos_os_dias = [(inicio + timedelta(days=i)).isoformat()
                     for i in range((fim - inicio).days + 1)]

    primeira = {d: _comparar(bling.get(d, {}), banco.get(d, {}), sit_bling, sit_banco)
                for d in todos_os_dias}
    divergentes = [d for d in todos_os_dias if _diverge(primeira[d])]

    erros: dict[int, str] = {}
    apagados: set[int] = set()
    cancelados = {int(v["bling_order_id"]) for v in vendas if v.get("status") == "cancelada"}
    if divergentes:
        alvo = []
        for d in divergentes:
            c = primeira[d]
            alvo.extend(c["faltando"] + c["valor_diferente"] + c["situacao_diferente"]
                        + c["sobrando"])
        sobrando_cancelados = {i for d in divergentes for i in primeira[d]["sobrando"]
                               if i in cancelados}
        if sobrando_cancelados:
            # Apagado ja confirmado numa noite anterior e ainda cancelado: nao rele de novo.
            conhecidos = await asyncio.to_thread(_apagados_conhecidos, conta, inicio, fim)
            apagados |= conhecidos & sobrando_cancelados
        lido_em = datetime.now(timezone.utc).isoformat()
        for order_id in dict.fromkeys(alvo):  # sem repetir (pedido que mudou de dia)
            if order_id in apagados:
                continue
            try:
                await pedido_import.importar_pedido(client, conta, order_id, event_date=lido_em)
            except BlingValidationError as exc:
                if exc.status == 404:
                    apagados.add(order_id)
                erros[order_id] = str(exc)
            except _SISTEMICOS as exc:
                # Falha da API, nao do dado: nao grava nada nem marca o dia; o
                # proximo tick (estado nao salvo) refaz a reconciliacao.
                logger.warning("[BLING RECONCILIACAO] conta %s: reimportacao parou no pedido "
                               "%s por erro sistemico, tenta no proximo tick: %s",
                               conta, order_id, exc)
                resultado.update(status="interrompido", erro=str(exc))
                return resultado
            except Exception as exc:  # noqa: BLE001
                logger.error("[BLING RECONCILIACAO] conta %s pedido %s: %s", conta, order_id, exc)
                erros[order_id] = str(exc)
        vendas = await asyncio.to_thread(_vendas_do_banco, conta, inicio, fim)
        banco = _por_dia_banco(vendas)
        sit_banco = _situacoes_banco(vendas)
        cancelados = {int(v["bling_order_id"]) for v in vendas
                      if v.get("status") == "cancelada"}

    # Apagado no Bling (404) E cancelado no banco: nada a decidir, nao diverge.
    tolerados = apagados & cancelados

    def _sem_tolerados(c: dict) -> dict:
        return {**c, "sobrando": [i for i in c["sobrando"] if i not in tolerados]}

    agora = datetime.now(timezone.utc).isoformat()
    linhas, ainda_divergentes = [], []
    for d in todos_os_dias:
        depois = _comparar(bling.get(d, {}), banco.get(d, {}), sit_bling, sit_banco)
        apagados_do_dia = sorted(tolerados & (set(primeira[d]["sobrando"]) | set(depois["sobrando"])))
        nota = ({"apagados_no_bling": apagados_do_dia, "observacao": OBS_APAGADO}
                if apagados_do_dia else {})
        antes_aj, depois_aj = _sem_tolerados(primeira[d]), _sem_tolerados(depois)
        if not _diverge(antes_aj):
            status, detalhe = "ok", nota
        elif not _diverge(depois_aj):
            status, detalhe = "reimportado", {**antes_aj, "reimportados": True, **nota}
        else:
            status = "divergente"
            ids = set(depois_aj["faltando"] + depois_aj["sobrando"] + depois_aj["valor_diferente"]
                      + depois_aj["situacao_diferente"])
            detalhe = {**depois_aj,
                       "apagados_no_bling": sorted(apagados & set(depois_aj["sobrando"])),
                       "erros": [{"pedido": i, "erro": erros[i]} for i in sorted(ids)
                                 if i in erros]}
            ainda_divergentes.append(d)
        linhas.append({
            "account": conta, "dia": d,
            "qtd_bling": len(bling.get(d, {})), "qtd_banco": len(banco.get(d, {})),
            "soma_bling": _soma(bling.get(d, {})), "soma_banco": _soma(banco.get(d, {})),
            "divergentes": detalhe, "status": status, "verificado_em": agora,
        })

    await asyncio.to_thread(_gravar, linhas)
    await asyncio.to_thread(_salvar_estado, conta, agora)

    conferido_ate = None
    for linha in linhas:
        if linha["status"] == "divergente":
            break
        conferido_ate = linha["dia"]

    resultado.update(
        status="divergente" if ainda_divergentes else "ok",
        dias=len(linhas), dias_reimportados=sum(1 for l in linhas if l["status"] == "reimportado"),
        dias_divergentes=ainda_divergentes, conferido_ate=conferido_ate,
    )
    if ainda_divergentes:
        alertar("bling_reconciliacao_divergente", conta,
                f"Bling x CRM divergente ({config.account(conta).label})",
                f"{len(ainda_divergentes)} dia(s) continuam divergentes depois de reimportar: "
                f"{', '.join(ainda_divergentes[:10])}. Detalhe em bling_reconciliacao.",
                metadata={"dias": ainda_divergentes})
    logger.info("[BLING RECONCILIACAO] %s", resultado)
    return resultado


async def reconciliar_se_devido(account: str, *, agora: datetime | None = None) -> dict | None:
    """Roda `reconciliar_conta` uma vez por dia (BRT), a partir de HORA_BRT.

    Chamado pelo tick da varredura. O estado so e gravado quando a reconciliacao
    chega ao fim (mesmo divergente); erro de listagem tenta de novo no proximo tick.
    """
    conta = config.account(account).key
    agora_brt = (agora or datetime.now(timezone.utc)).astimezone(_TZ)
    if agora_brt.time() < time(HORA_BRT):
        return None
    estado = await asyncio.to_thread(_carregar_estado, conta)
    ultima = (estado or {}).get("last_sync_at")
    if ultima:
        try:
            if datetime.fromisoformat(ultima).astimezone(_TZ).date() >= agora_brt.date():
                return None
        except ValueError:
            pass
    return await reconciliar_conta(conta, hoje=agora_brt.date())
