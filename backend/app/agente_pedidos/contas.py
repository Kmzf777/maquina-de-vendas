"""Contas Bling vistas pelo agente: apelido de negócio, rótulo e contato da fábrica."""
import os

from app.agente_pedidos.erros import erro
from app.bling import config
from app.bling.errors import BlingUnknownAccount

APELIDOS = {"default": "boaventura", "secundaria": "caferural"}
ROTULOS = {"default": "Bling Boaventura", "secundaria": "Bling Caferural"}


def validar(conta: str) -> str:
    try:
        return config.account(conta).key
    except BlingUnknownAccount as exc:
        raise erro(400, "conta", f"conta desconhecida: {conta}") from exc


def rotulo(conta: str) -> str:
    return ROTULOS.get(conta) or config.account(conta).label


def listar() -> list[dict]:
    return [{"conta": c.key, "apelido": APELIDOS.get(c.key, c.key), "rotulo": rotulo(c.key)}
            for c in config.accounts()]


def _var_fabrica(conta: str) -> str:
    if conta == config.DEFAULT_ACCOUNT:
        return "BLING_FABRICA_CONTATO_ID"
    return f"BLING_{conta.upper()}_FABRICA_CONTATO_ID"


def fabrica(conta: str) -> int:
    """ID do contato "Fábrica" NESTA conta. Sem cair para a variável da conta
    default: IDs de contato não valem entre contas."""
    nome = _var_fabrica(conta)
    bruto = (os.getenv(nome) or "").strip()
    if not bruto.isdigit():
        raise erro(422, "fabrica", f"contato da fábrica não configurado ({nome})")
    return int(bruto)
