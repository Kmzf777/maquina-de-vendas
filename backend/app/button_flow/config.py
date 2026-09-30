"""Env vars dos fluxos de botões, lidas cruas de os.getenv.

O kill switch é POR FLUXO (`_CHAVE_POR_FLUXO`): a Recuperação e a ValerIA de
botões têm chaves separadas e nenhuma liga a outra.

NÃO existe campo correspondente no `Settings` do pydantic, e isso é deliberado:
`app/config.py:65-69` declara `extra: "allow"`, que faz o Settings ACEITAR a
variável no `.env` sem criar o atributo — `settings.recuperacao_enabled` levantaria
`AttributeError` em produção, no primeiro turno, depois de o operador jurar que
"configurou a variável". Molde do repo: `app/bling/config.py:27-43`.

Ler o env a cada chamada (em vez de congelar no import) é o que torna o kill switch
utilizável: dá para desligar o bot com um restart do container, sem deploy.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_LIGADO = ("1", "true", "yes", "on")

# Fora desta janela o clique é velho demais para retomar o nó de onde parou.
# 30% dos cliques da base chegam fora das 24h e o máximo observado foi 43 dias:
# retomar "aguardando_prazo" 43 dias depois é responder a uma pergunta que o lead
# não lembra ter recebido.
_JANELA_RETOMA_DIAS_PADRAO = 7


def _env(name: str, padrao: str = "") -> str:
    valor = os.getenv(name)
    return (valor if valor is not None else padrao).strip()


# Cada fluxo tem a SUA chave. Uma chave só fechava os dois: ligar a ValerIA de
# botões armaria a Recuperação junto — que está desligada, roda no número pessoal
# de um vendedor, e tem 3 bloqueantes antes de poder ser ligada.
_CHAVE_POR_FLUXO = {
    "recuperacao_v1": "RECUPERACAO_ENABLED",
    "valeria_botoes_v1": "VALERIA_BOTOES_ENABLED",
}


def enabled(flow_id: str) -> bool:
    """Kill switch POR FLUXO. Default OFF, e fluxo desconhecido é OFF.

    Default fechado porque o gate roda ANTES do gate de canal humano
    (`buffer/processor.py`, gate de `mode='human'`): um bug aqui não deixaria a
    ValerIA falar demais, deixaria um robô falando no número pessoal do vendedor.

    Fluxo desconhecido devolve False em vez de levantar: este gate roda em TODO
    inbound, e um `flow_id` novo gravado à mão num perfil não pode virar exceção
    no caminho da mensagem.

    SEM sobrecarga sem argumento, de propósito: um default silencioso aqui é
    exatamente como uma chave passou a fechar os dois fluxos.
    """
    chave = _CHAVE_POR_FLUXO.get(flow_id)
    if not chave:
        return False
    return _env(chave, "off").lower() in _LIGADO


def algum_fluxo_ligado() -> bool:
    """True quando QUALQUER fluxo de botões está ligado.

    Existe para o gate do inbound (`runner.fluxo_da_conversa`) poder sair sem
    TOCAR NO BANCO quando nenhum fluxo está ligado: resolver de qual fluxo é a
    conversa custa uma consulta a `agent_profiles`, e com tudo desligado a
    resposta já é "nenhum". É o contrato que `buffer/processor.py` documenta nos
    dois chamadores — `_optout_deterministico_cabe` e o gate dos fluxos de botões —
    como "sem tocar no banco".
    """
    return any(enabled(fluxo) for fluxo in _CHAVE_POR_FLUXO)


def classifier_enabled() -> bool:
    """Camada 2 (classificação de texto livre por LLM). Default ON.

    Desligar não quebra o fluxo: sem classificador, texto livre cai na regra de
    nudge do motor (reoferece os botões uma vez, depois entrega ao humano) — o
    comportamento da máquina de estados pura, que entende ~40% dos turnos.
    """
    return _env("RECUPERACAO_CLASSIFIER_ENABLED", "on").lower() in _LIGADO


def janela_retoma_dias() -> int:
    """Idade máxima do estado para RETOMAR o nó em vez de recomeçar limpo."""
    bruto = _env("RECUPERACAO_JANELA_RETOMA_DIAS")
    if not bruto:
        return _JANELA_RETOMA_DIAS_PADRAO
    try:
        dias = int(bruto)
    except ValueError:
        logger.warning(
            "[BUTTON FLOW] RECUPERACAO_JANELA_RETOMA_DIAS inválido (%r) — usando %s",
            bruto, _JANELA_RETOMA_DIAS_PADRAO,
        )
        return _JANELA_RETOMA_DIAS_PADRAO
    return dias if dias > 0 else _JANELA_RETOMA_DIAS_PADRAO
