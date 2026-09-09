"""Env vars do agente de recuperação, lidas cruas de os.getenv.

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


def enabled() -> bool:
    """Kill switch do agente. Default OFF — o gate do processor nem chega a resolver
    o perfil da conversa enquanto isto for falso.

    Default fechado porque o gate roda ANTES do gate de canal humano
    (`buffer/processor.py`, gate de `mode='human'`): um bug aqui não deixaria a
    ValerIA falar demais, deixaria um robô falando no número pessoal do vendedor.
    """
    return _env("RECUPERACAO_ENABLED", "off").lower() in _LIGADO


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
