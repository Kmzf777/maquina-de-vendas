"""Por onde o lead de landing page entra na ValerIA de botões (v1).

O lead da LP já disse o que quer ao escolher a página: perguntar de novo "o café é pra
qual caso?" (N0) é uma tela a mais, faturada, para uma resposta que já temos. Então a
`origem` do formulário escolhe o nó de entrada e o primeiro contato abre direto nele.

Como chega ao runner: `lp_webhook` grava `flow_state = {"flow": v1, "entrada": <nó>}`
numa conversa que ainda não está no fluxo. Sem `node`, o runner trata como primeiro
contato (`valeria_runner.no_atual` → None) e `_decidir` lê a entrada daqui. Depois do
primeiro turno a chave sai do estado (`proximo_estado`).

Origem fora do mapa (inclusive as páginas em inglês e espanhol, porque o texto do fluxo
é em português) continua na tela de entrada N0.

A abertura é texto de código, e não override de tela: `valeria_flow_content` edita o
`corpo` do nó (P1/N1), que segue valendo para quem chega a eles pela N0.

Origens medidas nos leads de 30/09 a 13/11/2026: terceirizacao 218, atacado 113,
site-cafecanastra-atacado 8.
"""
from __future__ import annotations

CHAVE_ENTRADA = "entrada"

ENTRADA_POR_ORIGEM: dict[str, str] = {
    "terceirizacao": "P1",
    "atacado": "N1",
    "site-cafecanastra-atacado": "N1",
}

_APRESENTACAO = "oi! aqui é a Valéria, do comercial da Café Canastra ☕"

ABERTURA_POR_ENTRADA: dict[str, str] = {
    "P1": (
        f"{_APRESENTACAO}\n\n"
        "vi que você quer café com a sua marca, que projeto bom!\n\n"
        "você já tem uma marca criada ou tá pensando em lançar do zero?"
    ),
    "N1": (
        f"{_APRESENTACAO}\n\n"
        "vi que você procura café pro seu negócio\n\n"
        "que tipo de negócio você tem?"
    ),
}


def entrada_da_origem(origem: str | None) -> str | None:
    """Nó de entrada para esta `origem` de LP, ou None para a tela de entrada N0."""
    return ENTRADA_POR_ORIGEM.get((origem or "").strip().lower())
