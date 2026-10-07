"""Hierarquia de erros da integracao Bling.

A distincao que importa no fluxo de venda: erro TRANSITORIO (rate limit, 5xx,
timeout) vai para a fila e e retentado; erro de VALIDACAO nao vai — repetir o
mesmo payload invalido nunca conserta.
"""
import html
import re


class BlingError(Exception):
    """Base de todos os erros da integracao."""


class BlingNotConfigured(BlingError):
    """Faltam BLING_CLIENT_ID / BLING_CLIENT_SECRET, ou nunca houve autorizacao."""


class BlingUnknownAccount(BlingError):
    """Slug de conta que nao esta em BLING_ACCOUNTS. Erro de configuracao."""


class BlingAuthError(BlingError):
    """401 apos tentativa de renovacao — precisa refazer o fluxo OAuth."""


class BlingRateLimitError(BlingError):
    """429 do Bling, ou o token-bucket local recusou. TRANSITORIO."""


class BlingDailyCapError(BlingRateLimitError):
    """Teto diario local atingido. TRANSITORIO (destrava na virada do dia)."""


class BlingServerError(BlingError):
    """5xx ou timeout. TRANSITORIO."""


class BlingValidationError(BlingError):
    """4xx de validacao. NAO retentar.

    Carrega os campos que o Bling devolve em `error` para repassar ao vendedor.
    """

    def __init__(self, message: str, *, type_: str = "", description: str = "",
                 status: int = 400, payload: dict | None = None):
        super().__init__(message)
        self.type = type_
        self.description = description
        self.status = status
        self.payload = payload or {}

    @property
    def fields(self) -> list[dict]:
        """Motivo real da recusa, campo a campo — ver `campos_da_recusa`."""
        return campos_da_recusa(self.payload)


# Rotulo que o vendedor reconhece no formulario para o `element` do Bling.
ROTULOS_CAMPOS = {
    "numeroDocumento": "CPF/CNPJ",
    "email": "E-mail",
    "cep": "CEP",
    "uf": "UF",
    "municipio": "Município",
    "endereco": "Endereço",
    "numero": "Número",
    "bairro": "Bairro",
    "telefone": "Telefone",
    "celular": "Celular",
    "nome": "Nome",
    "ie": "Inscrição estadual",
    "indicadorIe": "Indicador de IE",
}

_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"\s+")


def _texto_limpo(valor) -> str:
    if not isinstance(valor, str):
        return ""
    # Tag sai antes e depois do unescape: `&lt;b&gt;` so vira tag no segundo passo.
    sem_tag = _TAG.sub(" ", html.unescape(_TAG.sub(" ", valor)))
    return _ESPACOS.sub(" ", sem_tag).strip()


def _itens_brutos(payload) -> list[dict]:
    """`error.fields` cru, tolerante ao formato.

    O Bling v3 manda uma lista de objetos, mas ja apareceu como objeto indexado
    ("0": {...}); qualquer outra coisa (ausente, nulo, texto) vira lista vazia.
    """
    if not isinstance(payload, dict):
        return []
    erro = payload.get("error")
    if not isinstance(erro, dict):
        return []
    fields = erro.get("fields")
    if isinstance(fields, dict):
        fields = list(fields.values())
    if not isinstance(fields, list):
        return []
    return [f for f in fields if isinstance(f, dict)]


def _element(item: dict) -> str:
    element = item.get("element")
    return element.strip() if isinstance(element, str) else ""


def campos_da_recusa(payload) -> list[dict]:
    """Extrai `error.fields` do corpo de erro do Bling como `[{campo, mensagem}]`.

    E o que diz ao vendedor O QUE corrigir. `message`/`description` do Bling sao
    genericos ("O contato nao pode ser salvo pois ocorreram problemas com sua
    validacao") e, sozinhos, deixaram o vendedor sem saida em 06/10.

    `campo` e o rotulo em portugues do `element` (ultima parte, se vier com
    caminho); desconhecido fica como veio; ausente vira "". Item sem `msg`
    util e descartado — um rotulo sem motivo nao ajuda ninguem.
    """
    saida = []
    for item in _itens_brutos(payload):
        mensagem = _texto_limpo(item.get("msg"))
        if not mensagem:
            continue
        element = _element(item)
        chave = element.rsplit(".", 1)[-1]
        saida.append({"campo": ROTULOS_CAMPOS.get(chave, element), "mensagem": mensagem})
    return saida


# Para o LOG: o `msg` do Bling as vezes repete o valor recusado ("O CPF
# 123.456.789-09 e invalido"). E-mail e qualquer sequencia longa de digitos
# (documento, telefone, CEP) sao mascarados — o log precisa do motivo, nao do
# dado do cliente.
_EMAIL = re.compile(r"[^\s@<>()]+@[^\s@<>()]+")
_DIGITOS = re.compile(r"\(?\d[\d().\-/\s]{3,}\d")


def _sem_pii(texto: str) -> str:
    return _DIGITOS.sub("***", _EMAIL.sub("***", texto))


def resumo_da_recusa_para_log(payload) -> str:
    """`element: msg; element: msg` com dado pessoal mascarado — so para log."""
    partes = []
    for item in _itens_brutos(payload):
        mensagem = _sem_pii(_texto_limpo(item.get("msg")))
        partes.append(f"{_element(item) or '?'}: {mensagem}")
    return "; ".join(partes) or "sem fields"


def corpo_da_recusa(exc: "BlingValidationError") -> dict:
    """Corpo JSON padrao de toda resposta a `BlingValidationError` nos routers."""
    return {
        "error": "validation",
        "message": str(exc),
        "detail": exc.description,
        "type": exc.type,
        "fields": exc.fields,
    }


TRANSIENT = (BlingRateLimitError, BlingServerError)
