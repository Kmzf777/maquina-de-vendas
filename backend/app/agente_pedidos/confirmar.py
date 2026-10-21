"""Confirmacao de um rascunho: o UNICO ponto do agente que cria algo no Bling.

Garantias:
- clique duplo nunca duplica: o resultado fica gravado (`CHAVE_RESULTADO`, 24 h)
  e a criacao roda sob uma trava `SET NX` (`CHAVE_TRAVA`, 120 s);
- venda leva `numeroLoja = agp-<id>` e, antes do POST, procura pedido com essa
  chave (mesmo mecanismo do `orders.create_order`);
- compra nao tem `numeroLoja`: as observacoes internas recebem `[agp-<id>]` e a
  retentativa da fila procura essa marca antes de repetir o POST;
- contato usa `criar_contato_sem_lead` (trava por documento + checagem ao vivo);
- erro TRANSITORIO vira job (`agente_venda`/`agente_compra`/`agente_contato`);
  validacao nunca entra na fila.
"""
import json
import logging

from app.agente_pedidos import rascunhos
from app.bling import contacts, jobs, orders
from app.bling.errors import TRANSIENT, BlingError, BlingValidationError

logger = logging.getLogger(__name__)

CHAVE_TRAVA = "agente_pedidos:confirmando:{}"
CHAVE_RESULTADO = "agente_pedidos:resultado:{}"
TTL_TRAVA = 120
TTL_RESULTADO = 24 * 3600

LINKS = {
    "venda": "https://www.bling.com.br/vendas.php#edit/{}",
    "compra": "https://www.bling.com.br/compras.php#edit/{}",
    "contato": "https://www.bling.com.br/contatos.php#edit/{}",
}
KINDS = {"venda": "agente_venda", "compra": "agente_compra", "contato": "agente_contato"}
_MAX_COMPRAS_VERIFICADAS = 20

VENCIDO = {"erro": "vencido", "mensagem": "rascunho inexistente ou vencido (30 min); peça de novo"}
NA_FILA = {"status": "na_fila"}


def novo_cliente(conta: str):
    """Fabrica de `BlingClient` (os testes trocam por um duble)."""
    from app.bling.client import BlingClient
    return BlingClient(account=conta, max_attempts=2)


def _marca(id_: str) -> str:
    return f"agp-{id_}"


def mensagem_bling(exc: BlingValidationError) -> str:
    """Mensagem do Bling + o motivo campo a campo (o `message` sozinho e generico)."""
    base = str(exc)
    detalhes = [f"{c['campo']}: {c['mensagem']}" if c.get("campo") else c["mensagem"]
                for c in exc.fields]
    return base + (" — " + "; ".join(detalhes) if detalhes else "")


async def _ler_resultado(id_: str) -> dict | None:
    bruto = await rascunhos.get_redis().get(CHAVE_RESULTADO.format(id_))
    return json.loads(bruto) if bruto else None


async def _gravar_resultado(id_: str, dados: dict) -> None:
    await rascunhos.get_redis().set(CHAVE_RESULTADO.format(id_),
                                    json.dumps(dados, ensure_ascii=False), ex=TTL_RESULTADO)


def _de_resultado(res: dict) -> tuple[int, dict]:
    if res.get("status") == "criado":
        return 201, res
    if res.get("status") == "falhou":
        return 422, {"erro": "bling", "mensagem": res.get("mensagem") or "o Bling recusou"}
    return 202, dict(NA_FILA)


# --------------------------------------------------------------------------
# Criacao (sem trava; quem chama garante a exclusividade)
# --------------------------------------------------------------------------
async def _numero(client, caminho: str):
    """`numero` e cosmetico: falha no GET nao derruba um pedido ja criado."""
    try:
        return ((await client.get(caminho)).get("data") or {}).get("numero")
    except Exception:  # noqa: BLE001
        logger.warning("[AGENTE PEDIDOS] GET %s falhou; numero fica vazio", caminho,
                       exc_info=True)
        return None


async def _criar_venda(client, id_: str, r: dict) -> tuple[int, object]:
    chave = _marca(id_)
    existente = await orders._find_order_by_key(client, chave)
    if existente:
        logger.warning("[AGENTE PEDIDOS] venda %s reaproveitada pela chave %s",
                       existente.get("id"), chave)
        return int(existente["id"]), existente.get("numero")
    payload = {**r["payload"], "numeroLoja": chave}
    dados = (await client.post("/pedidos/vendas", payload)).get("data") or {}
    bling_id = int(dados["id"])
    numero = dados.get("numero")
    if numero is None:
        numero = await _numero(client, f"/pedidos/vendas/{bling_id}")
    return bling_id, numero


async def _achar_compra(client, payload: dict, marca: str) -> tuple[int, object] | None:
    resp = await client.get("/pedidos/compras", {
        "idFornecedor": payload["fornecedor"]["id"], "dataInicial": payload["data"]})
    for pedido in (resp.get("data") or [])[:_MAX_COMPRAS_VERIFICADAS]:
        obs = pedido.get("observacoesInternas")
        if obs is None:
            detalhe = (await client.get(f"/pedidos/compras/{pedido['id']}")).get("data") or {}
            pedido = {**pedido, **detalhe}
            obs = pedido.get("observacoesInternas")
        if marca in (obs or ""):
            return int(pedido["id"]), pedido.get("numero")
    return None


async def _criar_compra(client, id_: str, r: dict, retentativa: bool) -> tuple[int, object]:
    marca = f"[{_marca(id_)}]"
    payload = dict(r["payload"])
    payload["observacoesInternas"] = f"{payload.get('observacoesInternas') or ''} {marca}".strip()
    if retentativa:
        achado = await _achar_compra(client, payload, marca)
        if achado:
            logger.warning("[AGENTE PEDIDOS] compra %s reaproveitada pela marca %s",
                           achado[0], marca)
            return achado
    dados = (await client.post("/pedidos/compras", payload)).get("data") or {}
    bling_id = int(dados["id"])
    numero = dados.get("numero")
    if numero is None:
        numero = await _numero(client, f"/pedidos/compras/{bling_id}")
    return bling_id, numero


async def criar(id_: str, r: dict, *, retentativa: bool = False) -> dict:
    """Cria no Bling o que o rascunho descreve e devolve o resultado `criado`."""
    tipo, conta = r["tipo"], r["conta"]
    async with novo_cliente(conta) as client:
        if tipo == "venda":
            bling_id, numero = await _criar_venda(client, id_, r)
        elif tipo == "compra":
            bling_id, numero = await _criar_compra(client, id_, r, retentativa)
        elif tipo == "contato":
            bling_id = await contacts.criar_contato_sem_lead(client, dict(r["payload"]),
                                                             account=conta)
            numero = None
        else:
            raise ValueError(f"tipo de rascunho desconhecido: {tipo}")
    logger.info("[AGENTE PEDIDOS] %s criado no Bling (conta %s): id %s numero %s, autor %s",
                tipo, conta, bling_id, numero, (r.get("autor") or {}).get("discord_id"))
    return {"status": "criado", "bling_id": int(bling_id),
            "numero": str(numero) if numero not in (None, "") else None,
            "link": LINKS[tipo].format(bling_id)}


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------
async def confirmar(id_: str, discord_id: str) -> tuple[int, dict]:
    if not rascunhos.id_valido(id_):
        return 410, dict(VENCIDO)
    res = await _ler_resultado(id_)
    if res:
        return _de_resultado(res)
    r = await rascunhos.carregar(id_)
    if not r:
        return 410, dict(VENCIDO)

    redis = rascunhos.get_redis()
    trava = CHAVE_TRAVA.format(id_)
    if not await redis.set(trava, discord_id or "?", nx=True, ex=TTL_TRAVA):
        return 202, dict(NA_FILA)
    try:
        # Outro clique pode ter terminado entre a leitura e a trava.
        res = await _ler_resultado(id_)
        if res:
            return _de_resultado(res)
        logger.info("[AGENTE PEDIDOS] confirmando rascunho %s (%s) por %s",
                    id_, r.get("tipo"), discord_id)
        try:
            criado = await criar(id_, r)
        except BlingValidationError as exc:
            return 422, {"erro": "bling", "mensagem": mensagem_bling(exc)}
        except TRANSIENT as exc:
            logger.warning("[AGENTE PEDIDOS] rascunho %s: Bling indisponivel (%s); "
                           "enfileirando", id_, exc)
            try:
                await jobs.enqueue(KINDS[r["tipo"]], {"id": id_, "rascunho": r},
                                   account=r["conta"])
            except Exception:  # noqa: BLE001
                logger.exception("[AGENTE PEDIDOS] rascunho %s: falhou ao enfileirar", id_)
                return 422, {"erro": "bling_indisponivel",
                             "mensagem": "o Bling não respondeu e não consegui pôr na fila; "
                                         "tente de novo em instantes"}
            await _gravar_resultado(id_, {"status": "pendente"})
            return 202, dict(NA_FILA)
        except BlingError as exc:
            # Conta sem token, autorizacao vencida etc.: nada foi criado.
            logger.error("[AGENTE PEDIDOS] rascunho %s: erro do Bling: %s", id_, exc)
            return 422, {"erro": "bling", "mensagem": str(exc)}
        await _gravar_resultado(id_, criado)
        await rascunhos.apagar(id_)
        return 201, criado
    finally:
        await redis.delete(trava)


async def resultado(id_: str) -> dict | None:
    """Desfecho gravado; `pendente` se o rascunho ainda existe sem desfecho;
    None se nao ha nem rascunho nem desfecho (a rota devolve 410)."""
    if not rascunhos.id_valido(id_):
        return None
    res = await _ler_resultado(id_)
    if res:
        return res
    return {"status": "pendente"} if await rascunhos.carregar(id_) else None


async def cancelar(id_: str) -> bool:
    if not await rascunhos.carregar(id_):
        return False
    await rascunhos.apagar(id_)
    return True


# --------------------------------------------------------------------------
# Fila (chamado pelos handlers de app/bling/jobs.py)
# --------------------------------------------------------------------------
async def executar_job(payload: dict, job: dict) -> dict:
    id_, r = payload["id"], payload["rascunho"]
    try:
        criado = await criar(id_, r, retentativa=True)
    except TRANSIENT as exc:
        if int(job.get("attempts") or 0) + 1 >= jobs.MAX_ATTEMPTS:
            await _gravar_resultado(id_, {
                "status": "falhou",
                "mensagem": f"o Bling não respondeu depois de várias tentativas ({exc})"})
        raise
    except BlingValidationError as exc:
        await _gravar_resultado(id_, {"status": "falhou", "mensagem": mensagem_bling(exc)})
        raise
    except Exception as exc:
        await _gravar_resultado(id_, {"status": "falhou", "mensagem": str(exc) or repr(exc)})
        raise
    await _gravar_resultado(id_, criado)
    await rascunhos.apagar(id_)
    return criado
